"""Tests for app.live FastAPI application lifecycle integration."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.api.main import app, market_clock
from app.clock.market_clock import ClockMode
from app.live.feed import LiveFeedService, CachedTick
from app.live import parsing as P
from datetime import datetime, timezone


def test_live_service_installed_on_app_state():
    """Verify that app.live service is attached to app.state.live_feed."""
    assert hasattr(app.state, "live_feed")
    assert isinstance(app.state.live_feed, LiveFeedService)


def test_live_status_endpoint_returns_feed_status(client: TestClient):
    """Verify that /live/status returns the real status from app.live."""
    resp = client.get("/live/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert "symbols" in data
    assert "market_status" in data


def test_live_prices_endpoint_returns_all_stocks(client: TestClient):
    """Verify that /live/prices returns quotes/reasons for all 5 stocks."""
    resp = client.get("/live/prices")
    assert resp.status_code == 200
    data = resp.json()
    for sym in ["INFY", "RELIANCE", "TCS", "HDFCBANK", "SBIN"]:
        assert sym in data


def test_price_endpoint_in_live_mode_delegates_to_live_feed(client: TestClient):
    """Verify that in LIVE mode, /price delegates to app.live price_or_http_error."""
    original_mode = market_clock.mode
    market_clock.mode = ClockMode.LIVE
    try:
        # With no mock quote cached and live feed not streaming in test, expect HTTP error or price
        from app.live.router import get_service
        svc = get_service() or app.state.live_feed
        t = P.Tick("INFY", 1550.0, 1540.0, 1_700_000_000_000, 10, None)
        cached = CachedTick(t, datetime.now(timezone.utc), "ws")
        svc.cache["INFY"] = cached
        app.state.live_feed.cache["INFY"] = cached

        resp = client.get("/price?symbol=INFY")
        assert resp.status_code == 200
        pdata = resp.json()
        assert pdata["symbol"] == "INFY"
        assert pdata["close"] == 1550.0
    finally:
        market_clock.mode = original_mode


def test_replay_mode_and_endpoints_intact_with_lifespan(client: TestClient):
    """Verify that Replay Mode clock, tick, and price queries operate as expected."""
    # Root endpoint
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "online"

    # Reset clock to known state
    switch_res = client.post("/clock/mode", json={
        "mode": "REPLAY",
        "replay_date": "2022-03-10",
        "start_time": "09:15"
    })
    assert switch_res.status_code == 200

    # Clock status
    clock_res = client.get("/clock")
    assert clock_res.status_code == 200
    assert clock_res.json()["mode"] == "REPLAY"

    # Tick clock
    tick_res = client.post("/clock/tick", json={"minutes": 5})
    assert tick_res.status_code == 200
    assert tick_res.json()["current_time"] == "2022-03-10 09:20:00"

    # Price lookup in Replay Mode
    price_res = client.get("/price?symbol=INFY")
    assert price_res.status_code == 200
    data = price_res.json()
    assert data["symbol"] == "INFY"
    assert data["close"] > 0
