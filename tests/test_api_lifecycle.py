"""Tests for UpstoxLiveFeed FastAPI application lifecycle integration."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.api.main import app, market_clock, upstox_feed
from app.clock.market_clock import ClockMode, LiveQuoteUnavailableError
from app.data.upstox_feed import UpstoxLiveFeed, get_upstox_feed


def test_feed_instance_shared_with_market_clock():
    """Verify that MarketClock and the API share the exact same singleton UpstoxLiveFeed instance."""
    assert market_clock.feed is not None
    assert market_clock.feed is upstox_feed
    assert upstox_feed is get_upstox_feed()


def test_lifespan_starts_feed_when_token_configured():
    """Verify that lifespan starts UpstoxLiveFeed when UPSTOX_ACCESS_TOKEN is configured."""
    mock_start = MagicMock()
    mock_stop = AsyncMock()

    with patch("app.api.main.settings.UPSTOX_ACCESS_TOKEN", "mock_live_token"), \
         patch.object(upstox_feed, "start", mock_start), \
         patch.object(upstox_feed, "stop", mock_stop):
        with TestClient(app) as client:
            mock_start.assert_called_once()
            response = client.get("/health")
            assert response.status_code == 200

        mock_stop.assert_awaited_once()


def test_lifespan_clean_shutdown():
    """Verify that exiting lifespan invokes and awaits stop() cleanly."""
    mock_stop = AsyncMock()

    with patch("app.api.main.settings.UPSTOX_ACCESS_TOKEN", "mock_token"), \
         patch.object(upstox_feed, "start", MagicMock()), \
         patch.object(upstox_feed, "stop", mock_stop):
        with TestClient(app) as client:
            assert client.get("/").status_code == 200

        mock_stop.assert_awaited_once()


def test_lifespan_missing_token_handling():
    """Verify backend starts cleanly and stays offline when token is missing or empty."""
    mock_start = MagicMock()
    mock_stop = AsyncMock()

    with patch("app.api.main.settings.UPSTOX_ACCESS_TOKEN", None), \
         patch.object(upstox_feed, "start", mock_start), \
         patch.object(upstox_feed, "stop", mock_stop):
        with TestClient(app) as client:
            mock_start.assert_not_called()

            # Health and clock endpoints function normally
            health_res = client.get("/health")
            assert health_res.status_code == 200

            clock_res = client.get("/clock")
            assert clock_res.status_code == 200
            assert clock_res.json()["mode"] == "REPLAY"

        mock_stop.assert_awaited_once()


def test_lifespan_connection_failure_handling():
    """Verify backend continues starting cleanly even if feed.start() raises an exception."""
    mock_start = MagicMock(side_effect=RuntimeError("Simulated connection error"))
    mock_stop = AsyncMock()

    with patch("app.api.main.settings.UPSTOX_ACCESS_TOKEN", "mock_token"), \
         patch.object(upstox_feed, "start", mock_start), \
         patch.object(upstox_feed, "stop", mock_stop):
        with TestClient(app) as client:
            mock_start.assert_called_once()

            # Application is still healthy and operational
            res = client.get("/health")
            assert res.status_code == 200

            clock_res = client.get("/clock")
            assert clock_res.status_code == 200

        mock_stop.assert_awaited_once()


def test_live_mode_reports_unavailable_quotes_when_feed_offline():
    """Verify that in LIVE mode, unavailable quotes raise LiveQuoteUnavailableError and never fall back to replay."""
    original_mode = market_clock.mode
    market_clock.mode = ClockMode.LIVE
    try:
        diag = market_clock.check_live_quote_status("INFY")
        assert diag["is_available"] is False

        with pytest.raises(LiveQuoteUnavailableError):
            market_clock.get_current_price("INFY")
    finally:
        # Restore clock to original mode for subsequent tests
        market_clock.mode = original_mode


def test_replay_mode_and_endpoints_intact_with_lifespan():
    """Verify that Replay Mode clock, tick, and price queries operate as expected."""
    with patch.object(upstox_feed, "start", MagicMock()), \
         patch.object(upstox_feed, "stop", AsyncMock()):
        with TestClient(app) as client:
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
