"""
Live market-data service for TradeZen (Upstox Market Data Feed V3, read-only).

What it does, in order:
  1. Reads your Upstox Analytics Token from the environment.
  2. Calls Upstox 'authorize' to get a single-use wss:// address.
  3. Connects and sends the subscription as a BINARY frame (a text frame is silently ignored
     by Upstox - this is the usual reason for "connected but no data").
  4. Decodes protobuf ticks -> keeps the latest price in memory -> builds 1-minute candles ->
     saves finished candles into price_bars.
  5. A watchdog reconnects if the feed goes quiet while the market is open; a REST LTP poll
     keeps real prices flowing while the socket is down. NOTHING is ever mocked or invented.

The service never raises into your API: every failure is recorded in status() and retried.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import httpx

from . import parsing as P
from .instruments import INSTRUMENTS, KEY_TO_SYMBOL, all_keys
from .store import BarStore

try:  # optional: loads .env so the token is found even if the app didn't load it
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

log = logging.getLogger("tradezen.live")

AUTH_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
LTP_URL = "https://api.upstox.com/v3/market-quote/ltp"
INTRADAY_URL = "https://api.upstox.com/v3/historical-candle/intraday/{key}/minutes/1"


class FeedError(Exception):
    pass


class AuthError(FeedError):
    pass


class StallError(FeedError):
    pass


class LivePriceUnavailable(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass
class CachedTick:
    tick: P.Tick
    received_at: datetime  # UTC
    source: str            # "ws" | "rest"


# ----------------------------------------------------------------------------- token helpers
def clean_token(raw: Optional[str]) -> str:
    """Remove the usual copy/paste damage: spaces, quotes, newline, a leading 'Bearer '."""
    t = (raw or "").strip().strip("'\"").strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return t


def token_expiry(token: str) -> Optional[datetime]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
    except Exception:
        return None


def build_subscribe(keys: list[str], mode: str = "full", method: str = "sub") -> bytes:
    """Upstox V3 requires the request as BINARY (bytes), not a text frame."""
    msg = {"guid": uuid.uuid4().hex[:24], "method": method, "data": {"mode": mode, "instrumentKeys": list(keys)}}
    return json.dumps(msg).encode("utf-8")


class LiveFeedService:
    def __init__(self, store: Optional[BarStore] = None) -> None:
        self.store = store
        self.keys = all_keys()
        self.enabled = os.getenv("LIVE_FEED_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
        self.mode = os.getenv("LIVE_FEED_MODE", "full").strip().lower()
        if self.mode not in ("full", "ltpc"):
            self.mode = "full"
        self.stall_seconds = float(os.getenv("LIVE_FEED_STALL_SECONDS", "45"))
        self.idle_recv_seconds = 120.0  # market closed: just wake up now and then
        self.backoff_scale = 1.0        # tests shrink this
        self.closed_min_delay = 30.0    # market closed: no point reconnecting faster than this

        self.builder = P.CandleBuilder()
        self.cache: dict[str, CachedTick] = {}
        self.market_status: dict[str, str] = {}

        self.state = "idle"
        self.last_error: Optional[str] = None
        self.last_error_at: Optional[datetime] = None
        self.store_error: Optional[str] = None
        self.backfill_state = "pending"
        self.ticks_total = 0
        self.reconnects = 0
        self.decode_errors = 0
        self.dropped_candles = 0
        self.rest_polls = 0
        self.connected_since: Optional[datetime] = None
        self.last_message_at: Optional[datetime] = None
        self.last_tick_mono = 0.0
        self._session_ticks = 0
        self._empty_sessions = 0
        self._assume_closed_until = 0.0
        self._rest_backoff_until = 0.0
        self._last_hk_log = 0.0

        self._q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._tasks: list[asyncio.Task] = []
        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._tasks:
            return
        if not self.enabled:
            self.state = "disabled"
            return
        if P.pb is None:
            self._fail(f"Upstox protobuf definitions missing ({P.PB_ERROR}). Run: pip install upstox-python-sdk", state="error")
            return
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=10.0))
        if self.store is not None:
            try:
                await asyncio.to_thread(self.store.check)
            except Exception as exc:
                self.store_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                log.error("price_bars not usable, live bars will NOT be saved (streaming continues): %s", self.store_error)
                self.store = None
        self._tasks = [
            asyncio.create_task(self._supervisor(), name="live-supervisor"),
            asyncio.create_task(self._writer(), name="live-writer"),
            asyncio.create_task(self._housekeeping(), name="live-housekeeping"),
        ]
        log.info("live feed started (mode=%s, stocks=%s)", self.mode, ",".join(INSTRUMENTS))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        leftovers = self.builder.flush_all()
        while not self._q.empty():
            leftovers.append(self._q.get_nowait())
        if leftovers and self.store is not None:
            try:
                await asyncio.to_thread(self.store.upsert_many, leftovers)
            except Exception as exc:
                log.warning("could not save %d candles on shutdown: %s", len(leftovers), exc)
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self.state = "stopped"

    # ------------------------------------------------------------------ small helpers
    def _fail(self, msg: str, state: Optional[str] = None) -> None:
        if msg != self.last_error:
            log.warning("live feed: %s", msg)
        self.last_error = msg
        self.last_error_at = datetime.now(timezone.utc)
        if state:
            self.state = state

    def _token(self) -> str:
        raw = os.getenv("UPSTOX_ANALYTICS_TOKEN") or os.getenv("UPSTOX_ACCESS_TOKEN")
        token = clean_token(raw)
        if not token:
            raise AuthError("No Upstox token found. Put your Analytics Token in .env as UPSTOX_ANALYTICS_TOKEN=...")
        exp = token_expiry(token)
        if exp is not None and exp <= datetime.now(timezone.utc):
            raise AuthError(f"Upstox token expired on {exp:%Y-%m-%d}. Generate a new Analytics Token in the Upstox developer app.")
        return token

    def market_is_open(self, now: Optional[datetime] = None) -> bool:
        now = now or P.now_ist()
        if time.monotonic() < self._assume_closed_until:
            return False
        st = self.market_status.get("NSE_EQ")
        if st is not None:
            return st == "NORMAL_OPEN"
        return P.is_trading_window(now)

    # ------------------------------------------------------------------ connection loop
    async def _supervisor(self) -> None:
        fails = 0
        while True:
            auth_failed = False
            try:
                token = self._token()
                self.state = "connecting"
                url = await self._authorize(token)
                await self._session(url)
                self._fail("connection closed by Upstox")
            except asyncio.CancelledError:
                raise
            except AuthError as exc:
                auth_failed = True
                self._fail(str(exc), state="auth_error")
            except Exception as exc:
                self._fail(self._explain(exc))

            if auth_failed:
                fails = 0
                delay = 60.0 * self.backoff_scale  # token problems: retry slowly, don't hammer Upstox
            else:
                if self._session_ticks > 0:
                    fails = 0
                    self._empty_sessions = 0
                else:
                    fails += 1
                    if self.market_is_open():
                        self._empty_sessions += 1
                        if self._empty_sessions >= 3:  # 'open' but silent: holiday? stop hammering
                            self._assume_closed_until = time.monotonic() + 900
                            self._empty_sessions = 0
                            self._fail("no ticks after 3 attempts - treating market as closed for 15 min (holiday?)")
                delay = min(60.0, 2.0 ** min(fails, 6)) * self.backoff_scale
                if not self.market_is_open():
                    delay = max(delay, self.closed_min_delay)
            self.reconnects += 1
            self.connected_since = None
            if not auth_failed:
                self.state = "backoff"
            self._session_ticks = 0
            await asyncio.sleep(delay + random.random() * self.backoff_scale)

    @staticmethod
    def _explain(exc: Exception) -> str:
        msg = f"{type(exc).__name__}: {str(exc)[:200]}"
        if "403" in msg or "401" in msg:
            msg += " (token rejected, or too many connections: Upstox allows only 2 websocket connections per user on the basic plan - close other running copies of this app)"
        return msg

    async def _authorize(self, token: str) -> str:
        assert self._http is not None
        r = await self._http.get(AUTH_URL, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if r.status_code in (401, 403):
            raise AuthError(f"Upstox rejected the token (HTTP {r.status_code}): {r.text[:150]}. Generate a new Analytics Token (only the newest one works).")
        if r.status_code == 429:
            raise FeedError("Upstox rate limit (429) on authorize")
        if r.status_code >= 400:
            raise FeedError(f"authorize failed: HTTP {r.status_code} {r.text[:150]}")
        data = (r.json() or {}).get("data") or {}
        url = data.get("authorizedRedirectUri") or data.get("authorized_redirect_uri")
        if not url:
            raise FeedError(f"authorize reply had no wss address (keys: {list(data)})")
        return url

    async def _connect(self, url: str):
        import websockets

        return websockets.connect(url, open_timeout=15, close_timeout=5, ping_interval=None, compression=None, max_size=2**23)

    async def _session(self, url: str) -> None:
        self._session_ticks = 0
        self.market_status = {}  # re-learn from this connection's market_info message
        ctx = await self._connect(url)
        async with ctx as ws:
            await ws.send(build_subscribe(self.keys, self.mode))  # bytes => binary frame
            self.state = "subscribed"
            self.connected_since = datetime.now(timezone.utc)
            log.info("connected and subscribed to %d instruments", len(self.keys))
            while True:
                expecting = self.market_is_open()
                timeout = self.stall_seconds if expecting else self.idle_recv_seconds
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout)
                except asyncio.TimeoutError:
                    if self.market_is_open():
                        raise StallError(f"no data for {timeout:.0f}s while the market is open")
                    continue
                self._session_ticks += self._on_frame(msg)

    # ------------------------------------------------------------------ message handling
    def _on_frame(self, msg) -> int:
        self.last_message_at = datetime.now(timezone.utc)
        if isinstance(msg, str):
            self._fail(f"text message from Upstox: {msg[:200]}")
            return 0
        try:
            resp = P.parse_frame(msg)
        except P.DecodeError as exc:
            self.decode_errors += 1
            if self.decode_errors in (1, 20, 200):
                self._fail(f"could not decode a frame ({exc}). If this repeats: pip install -U upstox-python-sdk protobuf")
            return 0
        status = P.extract_market_status(resp)
        if status:
            if status != self.market_status:
                log.info("market status: %s", status)
            self.market_status.update(status)
        ticks = P.extract_ticks(resp, KEY_TO_SYMBOL)
        is_live = resp.type == P.pb.Type.live_feed  # the 'initial_feed' snapshot may be old: price only
        for t in ticks:
            self._apply_tick(t, "ws", build_candle=is_live)
        if ticks:
            self.state = "streaming"
        return len(ticks)

    def _apply_tick(self, t: P.Tick, source: str, build_candle: bool) -> None:
        cur = self.cache.get(t.symbol)
        if cur is not None and cur.source == "ws" and source == "ws" and t.ltt_ms < cur.tick.ltt_ms:
            return  # out-of-order tick
        self.cache[t.symbol] = CachedTick(t, datetime.now(timezone.utc), source)
        if source == "ws":
            self.last_tick_mono = time.monotonic()
            self.ticks_total += 1
            if build_candle:
                for c in self.builder.update(t):
                    self._enqueue(c)
            if self.backfill_state == "pending" and self.store is not None:
                self.backfill_state = "scheduled"
                asyncio.get_running_loop().create_task(self._backfill_today())

    # ------------------------------------------------------------------ persistence
    def _enqueue(self, c: P.Candle) -> None:
        try:
            self._q.put_nowait(c)
        except asyncio.QueueFull:
            try:
                self._q.get_nowait()
                self.dropped_candles += 1
                self._q.put_nowait(c)
            except Exception:
                pass

    async def _writer(self) -> None:
        pending: list[P.Candle] = []
        failures = 0
        while True:
            if not pending:
                pending.append(await self._q.get())
            while len(pending) < 200 and not self._q.empty():
                pending.append(self._q.get_nowait())
            if self.store is None:
                pending.clear()
                continue
            try:
                await asyncio.to_thread(self.store.upsert_many, pending)
                pending = []
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                self.store_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                if failures in (1, 10, 100):
                    log.error("saving candles failed (will keep retrying): %s", self.store_error)
                await asyncio.sleep(min(30.0, 2.0 ** min(failures, 5)))
            else:
                self.store_error = None

    async def _housekeeping(self) -> None:
        while True:
            await asyncio.sleep(2)
            try:
                for c in self.builder.flush(P.now_ist()):
                    self._enqueue(c)
                await self._rest_fallback()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if time.monotonic() - self._last_hk_log > 60:  # no log spam
                    self._last_hk_log = time.monotonic()
                    log.warning("housekeeping error (ignored): %r", exc)

    # ------------------------------------------------------------------ REST fallback + backfill
    async def _rest_fallback(self) -> None:
        """Socket silent during market hours -> poll Upstox LTP (still 100% real prices)."""
        now = P.now_ist()
        if not P.is_trading_window(now) or self._http is None:
            return
        if time.monotonic() - self.last_tick_mono < 20 or time.monotonic() < self._rest_backoff_until:
            return
        try:
            token = self._token()
        except AuthError:
            return
        url = LTP_URL + "?instrument_key=" + ",".join(quote(k, safe="") for k in self.keys)
        self._rest_backoff_until = time.monotonic() + 4
        try:
            r = await self._http.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        except httpx.HTTPError:  # network down: quietly retry later (the socket loop reports connection problems)
            self._rest_backoff_until = time.monotonic() + 15
            return
        if r.status_code == 429:
            self._rest_backoff_until = time.monotonic() + 30
            return
        if r.status_code in (401, 403):
            self._rest_backoff_until = time.monotonic() + 120
            return
        if r.status_code != 200:
            self._rest_backoff_until = time.monotonic() + 15
            return
        for entry in ((r.json() or {}).get("data") or {}).values():
            sym = KEY_TO_SYMBOL.get(entry.get("instrument_token"))
            price = entry.get("last_price")
            if sym and isinstance(price, (int, float)) and price > 0:
                cp = entry.get("cp")
                t = P.Tick(sym, float(price), float(cp) if cp else None, int(time.time() * 1000), int(entry.get("ltq") or 0), None)
                self._apply_tick(t, "rest", build_candle=False)  # latest price only; candles stay tick-accurate
        self.rest_polls += 1

    async def _backfill_today(self) -> None:
        """Fill today's missing minutes (e.g. after a restart). Best effort: never raises."""
        try:
            now = P.now_ist()
            if self.store is None or self._http is None or not P.is_trading_window(now):
                self.backfill_state = "skipped"
                return
            token = self._token()
            total = 0
            for inst in INSTRUMENTS.values():
                r = await self._http.get(
                    INTRADAY_URL.format(key=quote(inst.key, safe="")),
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
                if r.status_code != 200:
                    self.backfill_state = f"unavailable (HTTP {r.status_code})"
                    log.info("intraday backfill not available with this token: HTTP %s", r.status_code)
                    return
                candles = []
                for row in ((r.json() or {}).get("data") or {}).get("candles") or []:
                    ts = datetime.fromisoformat(row[0]).astimezone(P.IST)
                    if ts.date() != now.date() or not P.in_session(ts) or ts >= P.floor_minute(now):
                        continue  # only finished minutes of today
                    candles.append(P.Candle(inst.symbol, ts, float(row[1]), float(row[2]), float(row[3]), float(row[4]), int(row[5] or 0)))
                total += await asyncio.to_thread(self.store.insert_missing, candles)
            self.backfill_state = f"done ({total} minutes added)"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.backfill_state = f"failed ({type(exc).__name__})"
            log.info("intraday backfill skipped: %s", exc)

    # ------------------------------------------------------------------ read side (used by the API)
    def _market_label(self) -> str:
        st = self.market_status.get("NSE_EQ")
        if st is not None:
            return st
        return "NORMAL_OPEN" if P.is_trading_window(P.now_ist()) else "CLOSED"

    def reason_no_price(self) -> tuple[str, str]:
        if not self.enabled:
            return "feed_disabled", "LIVE_FEED_ENABLED is off."
        if self.state == "auth_error":
            return "token_problem", self.last_error or "Upstox token problem."
        if self.state == "error":
            return "feed_error", self.last_error or "Live feed failed to start."
        if self.state in ("idle", "connecting", "backoff"):
            return "connecting", self.last_error or "Connecting to Upstox..."
        if not self.market_is_open():
            return "market_closed", "The market is closed and Upstox has not sent a last-price snapshot yet."
        return "no_ticks_yet", "Connected, waiting for the first price from Upstox."

    def get_price(self, symbol: str) -> dict:
        c = self.cache.get(symbol)
        if c is not None:
            age = (datetime.now(timezone.utc) - c.received_at).total_seconds()
            t = c.tick
            change = (t.ltp - t.prev_close) if t.prev_close else None
            open_now = self.market_is_open()
            return {
                "ok": True, "symbol": symbol, "instrument_key": INSTRUMENTS[symbol].key,
                "ltp": t.ltp, "prev_close": t.prev_close,
                "change": round(change, 2) if change is not None else None,
                "change_pct": round(change / t.prev_close * 100, 2) if change is not None else None,
                "last_trade_time": P.ms_to_ist(t.ltt_ms).isoformat(),
                "age_seconds": round(age, 1), "source": c.source,
                "market_status": self._market_label(),
                "stale": bool(open_now and age > max(60.0, self.stall_seconds * 1.5)),
            }
        if self.store is not None:
            try:
                bar = self.store.latest_bar(symbol)
            except Exception:
                bar = None
            if bar is not None:
                return {
                    "ok": True, "symbol": symbol, "instrument_key": INSTRUMENTS[symbol].key,
                    "ltp": bar["close"], "prev_close": None, "change": None, "change_pct": None,
                    "last_trade_time": bar["time"].isoformat(), "age_seconds": None, "source": "db",
                    "market_status": self._market_label(), "stale": True,
                }
        raise LivePriceUnavailable(*self.reason_no_price())

    async def get_candles(self, symbol: str, limit: int = 300) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        bars: list[dict] = []
        if self.store is not None:
            since = P.floor_minute(P.now_ist()).replace(hour=0, minute=0) - timedelta(days=3)
            try:
                bars = await asyncio.to_thread(self.store.recent_bars, symbol, since, limit)
            except Exception as exc:
                self.store_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        out = [{**b, "time": b["time"].isoformat(), "final": True} for b in bars]
        f = self.builder.forming(symbol)
        if f is not None:
            out = [b for b in out if b["time"] != f.minute.isoformat()]
            out.append({"time": f.minute.isoformat(), "open": f.open, "high": f.high, "low": f.low,
                        "close": f.close, "volume": f.volume, "final": False})
        return out[-limit:]

    def status(self) -> dict:
        now = datetime.now(timezone.utc)

        def iso(d):
            return d.isoformat() if d else None

        return {
            "enabled": self.enabled, "state": self.state, "mode": self.mode,
            "market_status": self._market_label(), "market_open": self.market_is_open(),
            "connected_since": iso(self.connected_since), "last_message_at": iso(self.last_message_at),
            "seconds_since_last_tick": round(time.monotonic() - self.last_tick_mono, 1) if self.last_tick_mono else None,
            "ticks_total": self.ticks_total, "reconnects": self.reconnects, "decode_errors": self.decode_errors,
            "rest_polls": self.rest_polls, "dropped_candles": self.dropped_candles,
            "queue_size": self._q.qsize(), "persistence": "on" if self.store is not None else "off",
            "store_error": self.store_error, "backfill": self.backfill_state,
            "last_error": self.last_error, "last_error_at": iso(self.last_error_at),
            "symbols": {s: {"ltp": c.tick.ltp, "source": c.source, "age_seconds": round((now - c.received_at).total_seconds(), 1)}
                        for s, c in self.cache.items()},
        }
