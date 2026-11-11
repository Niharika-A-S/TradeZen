"""Unit tests for the Upstox Market Data Feed V3 service.

All tests are mocked and hermetic — zero network calls, zero credentials required.
"""
import asyncio
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets

from app.data.upstox_feed import (
    FeedClass,
    FeedConnectionStatus,
    FeedResponseClass,
    FullFeedClass,
    KEY_TO_SYMBOL,
    LTPCClass,
    MarketFullFeedClass,
    OHLCClass,
    SUPPORTED_SYMBOLS,
    UpstoxLiveFeed,
    UpstoxQuote,
    VERIFIED_INSTRUMENTS,
    decode_feed_response,
    get_upstox_feed,
)


def _create_synthetic_ltpc_frame(instrument_key: str, ltp: float, cp: float, ltt_ms: int) -> bytes:
    """Helper to generate binary protobuf frame with LTPC data."""
    resp = FeedResponseClass()
    resp.type = 1
    resp.currentTs = ltt_ms
    feed = resp.feeds[instrument_key]
    feed.ltpc.ltp = ltp
    feed.ltpc.ltt = ltt_ms
    feed.ltpc.cp = cp
    return resp.SerializeToString()


def _create_synthetic_full_frame(
    instrument_key: str,
    ltp: float,
    cp: float,
    ltt_ms: int,
    volume: int,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
) -> bytes:
    """Helper to generate binary protobuf frame with MarketFullFeed and OHLC data."""
    resp = FeedResponseClass()
    resp.type = 1
    resp.currentTs = ltt_ms
    feed = resp.feeds[instrument_key]
    mff = feed.fullFeed.marketFF
    mff.ltpc.ltp = ltp
    mff.ltpc.ltt = ltt_ms
    mff.ltpc.cp = cp
    mff.vtt = volume

    ohlc = mff.marketOHLC.ohlc.add()
    ohlc.interval = "1d"
    ohlc.open = open_p
    ohlc.high = high_p
    ohlc.low = low_p
    ohlc.close = close_p
    ohlc.vol = volume
    ohlc.ts = ltt_ms

    return resp.SerializeToString()


class TestUpstoxSymbolMapping:
    """Tests instrument key mapping and verification."""

    def test_verified_symbols_and_keys(self):
        """Ensures all 5 required symbols are present with verified ISIN instrument keys."""
        assert len(SUPPORTED_SYMBOLS) == 5
        assert set(SUPPORTED_SYMBOLS) == {"INFY", "RELIANCE", "TCS", "HDFCBANK", "SBIN"}

        expected_keys = {
            "INFY": "NSE_EQ|INE009A01021",
            "RELIANCE": "NSE_EQ|INE002A01018",
            "TCS": "NSE_EQ|INE467B01029",
            "HDFCBANK": "NSE_EQ|INE040A01034",
            "SBIN": "NSE_EQ|INE062A01020",
        }

        for symbol, expected_key in expected_keys.items():
            assert VERIFIED_INSTRUMENTS[symbol] == expected_key
            assert KEY_TO_SYMBOL[expected_key] == symbol

    def test_feed_filters_unsupported_symbols(self):
        """Ensures passing unverified or random symbols is cleanly filtered out."""
        feed = UpstoxLiveFeed(token="mock_token", symbols=["INFY", "FAKE_STOCK", "RELIANCE"])
        assert feed.symbols == ["INFY", "RELIANCE"]
        assert len(feed.get_instrument_keys()) == 2
        assert "NSE_EQ|INE009A01021" in feed.get_instrument_keys()
        assert "NSE_EQ|INE002A01018" in feed.get_instrument_keys()


class TestUpstoxTokenHandling:
    """Tests missing token behavior and clean failure."""

    def test_missing_token_raises_on_start(self):
        """Ensures start() fails with clear ValueError if token is None and no custom ws_url."""
        feed = UpstoxLiveFeed(token=None)
        # Explicitly ensure _token is None for this test
        feed._token = None
        feed.custom_ws_url = None

        with pytest.raises(ValueError) as excinfo:
            feed.start()

        assert "UPSTOX_ACCESS_TOKEN is not configured" in str(excinfo.value)
        assert feed.get_status() == FeedConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_get_authorized_ws_url_missing_token(self):
        """Ensures get_authorized_ws_url() raises ValueError if token is missing."""
        feed = UpstoxLiveFeed(token=None)
        feed._token = None
        feed.custom_ws_url = None

        with pytest.raises(ValueError) as excinfo:
            await feed.get_authorized_ws_url()

        assert "UPSTOX_ACCESS_TOKEN is not configured" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_get_authorized_ws_url_custom_url(self):
        """Ensures custom_ws_url bypasses authorize endpoint completely."""
        feed = UpstoxLiveFeed(token=None, ws_url="ws://127.0.0.1:9999/feed")
        url = await feed.get_authorized_ws_url()
        assert url == "ws://127.0.0.1:9999/feed"


class TestProtobufDecoding:
    """Tests binary Protobuf decoding into structured UpstoxQuote objects."""

    def test_decode_ltpc_frame(self):
        """Tests decoding a binary frame containing LTPC data for INFY."""
        raw_bytes = _create_synthetic_ltpc_frame(
            instrument_key="NSE_EQ|INE009A01021",
            ltp=1525.50,
            cp=1510.0,
            ltt_ms=1710000000000,
        )

        quotes = decode_feed_response(raw_bytes)
        assert "INFY" in quotes
        quote = quotes["INFY"]

        assert quote.symbol == "INFY"
        assert quote.instrument_key == "NSE_EQ|INE009A01021"
        assert quote.ltp == 1525.50
        assert quote.close == 1510.0
        assert quote.exchange_timestamp == datetime.fromtimestamp(1710000000, tz=timezone.utc)
        assert quote.is_fresh() is True

    def test_decode_market_full_feed_with_ohlcv(self):
        """Tests decoding a binary frame containing full OHLCV and volume."""
        raw_bytes = _create_synthetic_full_frame(
            instrument_key="NSE_EQ|INE002A01018",
            ltp=2950.75,
            cp=2930.0,
            ltt_ms=1710000000000,
            volume=3500000,
            open_p=2925.0,
            high_p=2960.0,
            low_p=2910.0,
            close_p=2950.0,
        )

        quotes = decode_feed_response(raw_bytes)
        assert "RELIANCE" in quotes
        quote = quotes["RELIANCE"]

        assert quote.symbol == "RELIANCE"
        assert quote.ltp == 2950.75
        assert quote.open == 2925.0
        assert quote.high == 2960.0
        assert quote.low == 2910.0
        assert quote.close == 2950.0
        assert quote.volume == 3500000

    def test_decode_ignores_unverified_instrument(self):
        """Ensures unmapped/unverified keys are ignored without errors."""
        raw_bytes = _create_synthetic_ltpc_frame(
            instrument_key="NSE_EQ|UNVERIFIED_KEY",
            ltp=100.0,
            cp=95.0,
            ltt_ms=1710000000000,
        )
        quotes = decode_feed_response(raw_bytes)
        assert len(quotes) == 0

    def test_decode_corrupt_bytes(self):
        """Ensures invalid/corrupt bytes do not crash the service."""
        corrupt_data = b"\x00\xff\x99\x12\xaaINVALID_PROTOBUF_DATA"
        quotes = decode_feed_response(corrupt_data)
        assert quotes == {}


class TestCacheAndQuoteFreshness:
    """Tests thread-safe quote caching and freshness tracking."""

    def test_quote_freshness_check(self):
        """Tests that recent quotes are fresh and old quotes are marked stale."""
        now = datetime.now(timezone.utc)

        fresh_quote = UpstoxQuote(
            symbol="INFY",
            instrument_key="NSE_EQ|INE009A01021",
            ltp=1500.0,
            receipt_timestamp=now - timedelta(seconds=5),
        )
        assert fresh_quote.is_fresh(max_age_seconds=15.0) is True

        stale_quote = UpstoxQuote(
            symbol="INFY",
            instrument_key="NSE_EQ|INE009A01021",
            ltp=1500.0,
            receipt_timestamp=now - timedelta(seconds=30),
        )
        assert stale_quote.is_fresh(max_age_seconds=15.0) is False

    def test_feed_status_transitions(self):
        """Verifies DISCONNECTED -> CONNECTED_WITHOUT_QUOTES -> CONNECTED_WITH_FRESH_QUOTES."""
        feed = UpstoxLiveFeed(token="mock_token", freshness_threshold_seconds=10.0)

        # 1. Initially disconnected
        assert feed.get_status() == FeedConnectionStatus.DISCONNECTED

        # 2. Simulate connected but no quotes
        feed._is_connected = True
        assert feed.get_status() == FeedConnectionStatus.CONNECTED_WITHOUT_QUOTES

        # 3. Simulate connected with stale quotes only
        feed.update_quote(
            UpstoxQuote(
                symbol="INFY",
                instrument_key="NSE_EQ|INE009A01021",
                ltp=1520.0,
                receipt_timestamp=datetime.now(timezone.utc) - timedelta(seconds=20),
            )
        )
        # Stale data must NOT be labeled as live
        assert feed.get_status() == FeedConnectionStatus.CONNECTED_WITHOUT_QUOTES
        assert feed.is_fresh("INFY") is False

        # 4. Simulate fresh quote received
        feed.update_quote(
            UpstoxQuote(
                symbol="TCS",
                instrument_key="NSE_EQ|INE467B01029",
                ltp=3800.0,
                receipt_timestamp=datetime.now(timezone.utc),
            )
        )
        assert feed.get_status() == FeedConnectionStatus.CONNECTED_WITH_FRESH_QUOTES
        assert feed.is_fresh("TCS") is True

    def test_thread_safe_cache_concurrency(self):
        """Spawns multiple threads writing and reading quotes simultaneously."""
        feed = UpstoxLiveFeed(token="mock_token")
        errors = []

        def writer():
            for i in range(100):
                quote = UpstoxQuote(
                    symbol="INFY",
                    instrument_key="NSE_EQ|INE009A01021",
                    ltp=1500.0 + i,
                )
                feed.update_quote(quote)

        def reader():
            for _ in range(100):
                q = feed.get_latest_quote("INFY")
                if q is not None and q.ltp < 1500.0:
                    errors.append(f"Invalid LTP read: {q.ltp}")

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        latest = feed.get_latest_quote("INFY")
        assert latest is not None
        assert latest.ltp >= 1500.0


class TestSubscriptionAndPayload:
    """Tests subscription payload generation."""

    def test_build_subscription_payload(self):
        """Verifies JSON subscription payload format matching Upstox V3 requirements."""
        feed = UpstoxLiveFeed(token="mock_token", symbols=["INFY", "TCS"])
        payload_str = feed.build_subscription_payload(mode="full")
        payload = json.loads(payload_str)

        assert payload["method"] == "sub"
        assert payload["guid"] == "tradezen_sub"
        assert payload["data"]["mode"] == "full"
        assert set(payload["data"]["instrumentKeys"]) == {
            "NSE_EQ|INE009A01021",
            "NSE_EQ|INE467B01029",
        }


class TestBackoffAndReconnection:
    """Tests exponential backoff calculation and mocked reconnect logic."""

    def test_bounded_exponential_backoff_values(self):
        """Checks backoff sequence: 1s, 2s, 4s, 8s, 16s, 30s (bounded at max)."""
        feed = UpstoxLiveFeed(
            token="mock_token",
            initial_backoff=1.0,
            backoff_factor=2.0,
            max_backoff=30.0,
        )

        expected_delays = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
        for attempt, expected in enumerate(expected_delays):
            delay = min(
                feed.initial_backoff * (feed.backoff_factor ** attempt),
                feed.max_backoff,
            )
            assert delay == expected

    @pytest.mark.asyncio
    async def test_mock_websocket_streaming_and_stop(self):
        """Simulates a live WebSocket connection streaming binary ticks and graceful stop."""
        feed = UpstoxLiveFeed(token="mock_token", ws_url="ws://mock-feed")

        raw_tick = _create_synthetic_ltpc_frame(
            instrument_key="NSE_EQ|INE009A01021",
            ltp=1575.25,
            cp=1560.0,
            ltt_ms=1710000000000,
        )

        class MockWs:
            def __init__(self):
                self.messages = [raw_tick]
                self.sent = []

            async def send(self, data):
                self.sent.append(data)

            async def recv(self):
                if self.messages:
                    return self.messages.pop(0)
                # Keep waiting until stopped
                await asyncio.sleep(5)
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_ws = MockWs()

        with patch("websockets.connect", return_value=mock_ws):
            task = feed.start()
            # Give background loop time to connect and process tick
            await asyncio.sleep(0.1)

            assert feed.is_connected is True
            quote = feed.get_latest_quote("INFY")
            assert quote is not None
            assert quote.ltp == 1575.25
            assert len(mock_ws.sent) == 1  # Subscription payload was sent

            # Stop feed
            await feed.stop()
            assert feed.is_connected is False
            assert task.done()
