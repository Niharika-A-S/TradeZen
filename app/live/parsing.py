"""
Pure functions (no network, no database): decode Upstox V3 protobuf frames into ticks
and aggregate ticks into 1-minute candles. Everything here is unit-tested offline.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_OPEN = dtime(9, 15)
SESSION_CLOSE = dtime(15, 30)

# The protobuf definition ships inside Upstox's official SDK (pip install upstox-python-sdk),
# so we never have to compile a .proto file ourselves.
try:
    from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb

    PB_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - depends on environment
    pb = None
    PB_ERROR = f"{type(exc).__name__}: {exc}"


class DecodeError(Exception):
    pass


@dataclass(frozen=True)
class Tick:
    symbol: str
    ltp: float
    prev_close: Optional[float]
    ltt_ms: int          # exchange last-trade time, epoch milliseconds
    ltq: int             # last traded quantity
    vtt: Optional[int]   # total volume traded today (full mode only)


@dataclass
class Candle:
    symbol: str
    minute: datetime     # IST, timezone-aware, second=0
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


def now_ist() -> datetime:
    return datetime.now(IST)


def ms_to_ist(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=IST)


def floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def in_session(dt: datetime) -> bool:
    """09:15 <= time < 15:30 IST (pre-open and closing auction are excluded)."""
    return SESSION_OPEN <= dt.astimezone(IST).time() < SESSION_CLOSE


def is_trading_window(dt: datetime) -> bool:
    d = dt.astimezone(IST)
    return d.weekday() < 5 and in_session(d)


def parse_frame(data: bytes):
    if pb is None:
        raise DecodeError(f"protobuf definitions unavailable: {PB_ERROR}")
    try:
        return pb.FeedResponse.FromString(data)
    except Exception as exc:
        raise DecodeError(str(exc)) from exc


def extract_market_status(resp) -> dict[str, str]:
    if pb is None or not resp.HasField("marketInfo"):
        return {}
    return {seg: pb.MarketStatus.Name(v) for seg, v in resp.marketInfo.segmentStatus.items()}


def extract_ticks(resp, key_to_symbol: dict[str, str]) -> list[Tick]:
    """Works for both 'ltpc' and 'full' subscription modes. Unknown keys / bad prices are skipped."""
    out: list[Tick] = []
    for key, feed in resp.feeds.items():
        symbol = key_to_symbol.get(key)
        if symbol is None:
            continue
        which = feed.WhichOneof("FeedUnion")
        ltpc = None
        vtt = None
        if which == "ltpc":
            ltpc = feed.ltpc
        elif which == "fullFeed":
            ff = feed.fullFeed
            if ff.HasField("marketFF"):
                ltpc = ff.marketFF.ltpc
                vtt = ff.marketFF.vtt or None
            elif ff.HasField("indexFF"):
                ltpc = ff.indexFF.ltpc
        if ltpc is None:
            continue
        ltp = ltpc.ltp
        if not (math.isfinite(ltp) and ltp > 0):
            continue
        ltt = ltpc.ltt or resp.currentTs or int(time.time() * 1000)
        cp = float(ltpc.cp) if math.isfinite(ltpc.cp) and ltpc.cp > 0 else None
        out.append(Tick(symbol, float(ltp), cp, int(ltt), int(ltpc.ltq), int(vtt) if vtt else None))
    return out


class CandleBuilder:
    """
    Builds real 1-minute candles from real ticks. Never invents data: a minute with no
    trades simply has no candle. Minute volume = change in Upstox's 'volume traded today'.
    """

    GRACE_SECONDS = 3  # wait a little for late ticks before closing a minute

    def __init__(self) -> None:
        self._cur: dict[str, Candle] = {}
        self._last_vtt: dict[str, int] = {}
        self._base_vtt: dict[str, Optional[int]] = {}
        self._last_final: dict[str, datetime] = {}

    def update(self, t: Tick) -> list[Candle]:
        ts = ms_to_ist(t.ltt_ms)
        if not in_session(ts):
            return []
        minute = floor_minute(ts)
        sym = t.symbol
        last_final = self._last_final.get(sym)
        if last_final is not None and minute <= last_final:
            return []  # late tick for a minute we already closed
        cur = self._cur.get(sym)
        if cur is not None and minute < cur.minute:
            return []  # out-of-order tick
        done: list[Candle] = []
        if cur is None or minute > cur.minute:
            if cur is not None:
                done.append(cur)
                self._last_final[sym] = cur.minute
            base = self._last_vtt.get(sym)
            if t.vtt is not None and (base is None or t.vtt < base):  # first tick, or new trading day
                base = max(t.vtt - t.ltq, 0)
            self._base_vtt[sym] = base
            cur = Candle(sym, minute, t.ltp, t.ltp, t.ltp, t.ltp, 0)
            self._cur[sym] = cur
        else:
            cur.high = max(cur.high, t.ltp)
            cur.low = min(cur.low, t.ltp)
            cur.close = t.ltp
        if t.vtt is not None:
            self._last_vtt[sym] = t.vtt
            base = self._base_vtt.get(sym)
            if base is not None:
                cur.volume = max(t.vtt - base, 0)
        return done

    def flush(self, now: datetime) -> list[Candle]:
        """Close minutes that are over (called every couple of seconds)."""
        out: list[Candle] = []
        for sym, cur in list(self._cur.items()):
            if now >= cur.minute + timedelta(seconds=60 + self.GRACE_SECONDS):
                out.append(cur)
                self._last_final[sym] = cur.minute
                del self._cur[sym]
        return out

    def flush_all(self) -> list[Candle]:
        out = list(self._cur.values())
        for c in out:
            self._last_final[c.symbol] = c.minute
        self._cur.clear()
        return out

    def forming(self, symbol: str) -> Optional[Candle]:
        return self._cur.get(symbol)
