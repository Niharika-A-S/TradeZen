"""
Runs the REAL LiveFeedService against a local fake Upstox server that speaks the same
protocol (binary subscribe in, protobuf frames out). Proves: binary subscription, decoding,
candles saved, reconnect after a drop, stall watchdog, auth/text-error reporting.
"""
import asyncio
import json

import pytest
import websockets
from sqlalchemy import create_engine, text

from app.live import feed as F
from app.live.instruments import all_keys
from app.live.store import BarStore
from live_helpers import make_frame, ms

INFY, TCS = "NSE_EQ|INE009A01021", "NSE_EQ|INE467B01029"


class FakeUpstox:
    def __init__(self, script):
        self.script = script          # async def script(ws, conn_no)
        self.connections = []         # first frame of each connection
        self._server = None

    async def _handler(self, ws):
        n = len(self.connections)
        first = await ws.recv()
        self.connections.append(first)
        await self.script(ws, n)

    async def __aenter__(self):
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *a):
        self._server.close()
        await self._server.wait_closed()


def make_service(url, with_store=False):
    store = None
    if with_store:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=__import__("sqlalchemy").pool.StaticPool)
        with eng.begin() as c:
            c.execute(text("CREATE TABLE price_bars (instrument TEXT, ts TIMESTAMP, open REAL, high REAL, low REAL, close REAL, volume BIGINT)"))
        store = BarStore(eng, ts_mode="ist_naive")
    svc = F.LiveFeedService(store=store)
    svc.backoff_scale = 0.02
    svc.closed_min_delay = 0.05

    async def fake_auth(token):
        assert token == "test-token"  # quotes, spaces and 'Bearer ' were cleaned
        return url

    svc._authorize = fake_auth
    return svc


async def wait_for(cond, timeout=5.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


async def test_binary_subscribe_ticks_candles_and_price():
    async def script(ws, n):
        await ws.send(make_frame({}, "market_info", status={"NSE_EQ": "NORMAL_OPEN"}))
        await ws.send(make_frame({INFY: (1490.0, ms(9, 59, 58), 5, 1480.0, 900)}, "initial_feed"))
        await ws.send(make_frame({INFY: (1500.0, ms(10, 0, 5), 10, 1480.0, 1000)}))
        await ws.send(make_frame({INFY: (1503.0, ms(10, 0, 30), 10, 1480.0, 1040), TCS: (3900.0, ms(10, 0, 31), 3, 3880.0, 77)}))
        await ws.send(make_frame({INFY: (1501.0, ms(10, 1, 2), 10, 1480.0, 1100)}))  # new minute -> 10:00 closes
        await asyncio.sleep(1.5)

    async with FakeUpstox(script) as srv:
        svc = make_service(srv.url, with_store=True)
        await svc.start()
        try:
            assert await wait_for(lambda: svc.cache.get("INFY") and svc.cache["INFY"].tick.ltp == 1501.0)
            first = srv.connections[0]
            assert isinstance(first, bytes), "subscription MUST be a binary frame"
            req = json.loads(first)
            assert req["method"] == "sub" and req["data"]["mode"] == "full"
            assert req["data"]["instrumentKeys"] == all_keys()
            assert svc.state == "streaming" and svc.market_is_open()
            p = svc.get_price("INFY")
            assert p["ltp"] == 1501.0 and p["prev_close"] == 1480.0 and p["change"] == 21.0 and p["source"] == "ws"
            # the 10:00 candle closed when the 10:01 tick arrived and was saved to the DB
            assert await wait_for(lambda: len(_bars(svc, "INFY")) == 1)
            b = _bars(svc, "INFY")[0]
            assert (b["open"], b["high"], b["low"], b["close"]) == (1500.0, 1503.0, 1500.0, 1503.0)
            candles = await svc.get_candles("INFY")
            assert [c["final"] for c in candles] == [True, False]  # saved bar + live forming bar
            # the initial_feed snapshot (1490 @ 09:59) must NOT have produced a candle
            assert all(c["open"] != 1490.0 for c in candles)
        finally:
            await svc.stop()
    assert svc.state == "stopped"


def _bars(svc, sym):
    from datetime import datetime, timedelta
    from app.live import parsing as P
    return svc.store.recent_bars(sym, datetime(2026, 11, 13, 0, 0, tzinfo=P.IST) - timedelta(days=1))


async def test_reconnects_after_server_drops_the_connection():
    async def script(ws, n):
        await ws.send(make_frame({}, "market_info", status={"NSE_EQ": "NORMAL_OPEN"}))
        await ws.send(make_frame({INFY: (1500.0 + n, ms(10, 0, 5), 10, 1480.0, 1000)}))
        await asyncio.sleep(0.1)
        await ws.close()

    async with FakeUpstox(script) as srv:
        svc = make_service(srv.url)
        await svc.start()
        try:
            assert await wait_for(lambda: len(srv.connections) >= 3, 6)
            assert svc.reconnects >= 2 and svc.cache["INFY"].tick.ltp >= 1501.0
        finally:
            await svc.stop()


async def test_watchdog_reconnects_when_feed_goes_silent_in_market_hours():
    async def script(ws, n):
        await ws.send(make_frame({}, "market_info", status={"NSE_EQ": "NORMAL_OPEN"}))
        await asyncio.sleep(1.5)  # connected but never sends a tick: the 'websocket connects, no data' bug

    async with FakeUpstox(script) as srv:
        svc = make_service(srv.url)
        svc.stall_seconds = 0.3
        await svc.start()
        try:
            assert await wait_for(lambda: len(srv.connections) >= 2, 6)
            assert "no data" in (svc.last_error or "")
        finally:
            await svc.stop()


async def test_server_text_message_is_surfaced_not_swallowed():
    async def script(ws, n):
        await ws.send('{"error":"invalid instrument key"}')
        await asyncio.sleep(1.5)

    async with FakeUpstox(script) as srv:
        svc = make_service(srv.url)
        await svc.start()
        try:
            assert await wait_for(lambda: "invalid instrument key" in (svc.last_error or ""))
        finally:
            await svc.stop()


async def test_bad_token_reports_clear_reason_and_api_survives():
    svc = F.LiveFeedService(store=None)
    svc.backoff_scale = 0.02

    async def reject(token):
        raise F.AuthError("Upstox rejected the token (HTTP 401)")

    svc._authorize = reject
    await svc.start()
    try:
        assert await wait_for(lambda: svc.state == "auth_error")
        with pytest.raises(F.LivePriceUnavailable) as e:
            svc.get_price("INFY")
        assert e.value.reason == "token_problem"
    finally:
        await svc.stop()


async def test_missing_token_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("UPSTOX_ANALYTICS_TOKEN", raising=False)
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    svc = F.LiveFeedService(store=None)
    svc.backoff_scale = 0.02
    await svc.start()
    try:
        assert await wait_for(lambda: svc.state == "auth_error")
        assert "UPSTOX_ANALYTICS_TOKEN" in svc.last_error
    finally:
        await svc.stop()


def test_token_cleaning_and_expiry():
    assert F.clean_token('  "Bearer abc.def.ghi"\n') == "abc.def.ghi"
    import base64, json, time
    body = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) - 10}).encode()).decode().rstrip("=")
    assert F.token_expiry(f"x.{body}.y") is not None and F.token_expiry("not-a-jwt") is None


async def test_db_failure_never_stops_the_stream():
    async def script(ws, n):
        await ws.send(make_frame({}, "market_info", status={"NSE_EQ": "NORMAL_OPEN"}))
        for i in range(4):
            await ws.send(make_frame({INFY: (1500.0 + i, ms(10, i, 5), 10, 1480.0, 1000 + i)}))
        await asyncio.sleep(1.5)

    async with FakeUpstox(script) as srv:
        svc = make_service(srv.url, with_store=True)
        with svc.store.engine.begin() as c:
            c.execute(text("DROP TABLE price_bars"))  # table vanishes at runtime
        svc.store.check = lambda: None                 # skip the startup check to test the runtime path
        await svc.start()
        try:
            assert await wait_for(lambda: svc.cache.get("INFY") and svc.cache["INFY"].tick.ltp == 1503.0)
            assert await wait_for(lambda: svc.store_error is not None)
            assert svc.get_price("INFY")["ltp"] == 1503.0  # prices keep flowing
        finally:
            await svc.stop()
