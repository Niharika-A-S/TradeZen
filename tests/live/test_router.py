from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.live import install, parsing as P
from app.live.feed import CachedTick
from app.live.router import price_or_http_error


def _app(monkeypatch, enabled="false"):
    monkeypatch.setenv("LIVE_FEED_ENABLED", enabled)
    events = []

    @asynccontextmanager
    async def lifespan(app):  # the app's OWN lifespan must keep working
        events.append("app-start")
        yield
        events.append("app-stop")

    app = FastAPI(lifespan=lifespan)
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE price_bars (instrument TEXT, ts TIMESTAMP, open REAL, high REAL, low REAL, close REAL, volume BIGINT)"))
    svc = install(app, eng)
    return app, svc, events


def test_install_composes_with_existing_lifespan_and_never_breaks_api(monkeypatch):
    app, svc, events = _app(monkeypatch, enabled="false")
    with TestClient(app) as client:
        assert events == ["app-start"]
        assert svc.state == "disabled"
        assert client.get("/live/status").json()["state"] == "disabled"
    assert events == ["app-start", "app-stop"] and svc.state == "stopped"


def test_price_endpoint_aliases_unknown_symbol_and_reasons(monkeypatch):
    app, svc, _ = _app(monkeypatch)
    with TestClient(app) as client:
        r = client.get("/live/price", params={"symbol": "WIPRO"})
        assert r.status_code == 404 and r.json()["detail"]["reason"] == "unknown_symbol"
        assert "INFY" in r.json()["detail"]["supported"]

        r = client.get("/live/price", params={"symbol": "TCS"})  # nothing received yet: explicit reason, not a bare 404
        assert r.status_code == 503 and r.json()["detail"]["reason"] in {"feed_disabled", "connecting", "market_closed", "no_ticks_yet"}

        t = P.Tick("HDFCBANK", 1700.0, 1690.0, 1_700_000_000_000, 5, None)
        svc.cache["HDFCBANK"] = CachedTick(t, datetime.now(timezone.utc), "ws")
        r = client.get("/live/price", params={"symbol": "HDFC"})  # alias resolves
        body = r.json()
        assert r.status_code == 200 and body["symbol"] == "HDFCBANK" and body["ltp"] == 1700.0
        assert body["instrument_key"] == "NSE_EQ|INE040A01034" and body["change"] == 10.0

        assert set(client.get("/live/prices").json()) == {"INFY", "RELIANCE", "TCS", "HDFCBANK", "SBIN"}
        assert len(client.get("/live/instruments").json()) == 5
        assert client.get("/live/candles", params={"symbol": "SBI"}).json()["symbol"] == "SBIN"


def test_helper_for_existing_price_route(monkeypatch):
    app, svc, _ = _app(monkeypatch)
    t = P.Tick("INFY", 1500.0, None, 1_700_000_000_000, 1, None)
    svc.cache["INFY"] = CachedTick(t, datetime.now(timezone.utc), "rest")
    assert price_or_http_error("infosys")["source"] == "rest"
