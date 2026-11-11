from datetime import datetime, date, time, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from app.clock.market_clock import (
    MarketClock,
    ClockMode,
    PriceQuote,
    LiveQuoteUnavailableError,
    get_price,
    get_bar,
    parse_timestamp,
)
from app.data.upstox_feed import UpstoxQuote


def test_timestamp_parsing():
    """Tests various timestamp string and datetime parsing."""
    dt1 = parse_timestamp("2022-03-10 10:15:00")
    assert dt1 == datetime(2022, 3, 10, 10, 15, 0)

    dt2 = parse_timestamp("2022-03-10 10:15")
    assert dt2 == datetime(2022, 3, 10, 10, 15, 0)

    dt3 = parse_timestamp(datetime(2022, 3, 10, 10, 15))
    assert dt3 == datetime(2022, 3, 10, 10, 15, 0)

    dt4 = parse_timestamp(date(2022, 3, 10))
    assert dt4 == datetime(2022, 3, 10, 9, 15, 0)


def test_price_quote_behavior():
    """Verifies that PriceQuote behaves as a float and provides bar attributes."""
    pq = PriceQuote(
        close=1818.0,
        open=1821.0,
        high=1821.1,
        low=1817.2,
        volume=21359,
        symbol="INFY",
        timestamp=datetime(2022, 3, 10, 10, 15, 0)
    )

    # Float comparisons
    assert pq == 1818.0
    assert float(pq) == 1818.0
    assert pq > 1800.0
    assert pq < 1850.0
    assert pq + 2 == 1820.0

    # Bar attributes
    assert pq.close == 1818.0
    assert pq.open == 1821.0
    assert pq.high == 1821.1
    assert pq.low == 1817.2
    assert pq.volume == 21359
    assert pq.symbol == "INFY"


def test_market_clock_replay_mode():
    """Verifies MarketClock in REPLAY mode advances minute by minute."""
    clock = MarketClock(
        mode=ClockMode.REPLAY,
        replay_date="2022-03-10",
        start_time="09:15",
        end_time="15:30"
    )

    assert clock.mode == ClockMode.REPLAY
    assert clock.current_time == datetime(2022, 3, 10, 9, 15, 0)
    assert clock.is_market_open is True

    # Tick 1 minute
    next_time = clock.tick()
    assert next_time == datetime(2022, 3, 10, 9, 16, 0)
    assert clock.current_time == datetime(2022, 3, 10, 9, 16, 0)

    # Advance 59 minutes to reach 10:15
    clock.advance(59)
    assert clock.current_time == datetime(2022, 3, 10, 10, 15, 0)

    # Check price at this minute
    price = clock.get_current_price("INFY")
    assert price == 1818.0
    assert price.close == 1818.0


def test_market_clock_live_mode():
    """Verifies MarketClock in LIVE mode tracks current time and requires live feed for prices."""
    clock = MarketClock(mode=ClockMode.LIVE, feed=None, auto_attach_feed=False)
    assert clock.mode == ClockMode.LIVE
    assert isinstance(clock.current_time, datetime)

    # Cannot tick in live mode
    with pytest.raises(RuntimeError):
        clock.tick()

    # Without feed, get_live_quote is None and get_current_price raises LiveQuoteUnavailableError
    assert clock.get_live_quote("INFY") is None
    with pytest.raises(LiveQuoteUnavailableError) as exc_info:
        clock.get_current_price("INFY")
    assert "Feed service is not attached" in str(exc_info.value)


def test_live_mode_fresh_quote():
    """Verifies MarketClock resolves a fresh live quote from an injected feed."""
    mock_feed = MagicMock()
    mock_feed.is_connected = True

    now = datetime.now(timezone.utc)
    fresh_quote = UpstoxQuote(
        symbol="INFY",
        instrument_key="NSE_EQ|INE009A01021",
        ltp=1550.50,
        exchange_timestamp=now,
        receipt_timestamp=now,
        close=1540.0,
        open=1530.0,
        high=1560.0,
        low=1525.0,
        volume=125000,
    )
    mock_feed.get_latest_quote.return_value = fresh_quote

    clock = MarketClock(mode=ClockMode.LIVE, feed=mock_feed)
    quote = clock.get_live_quote("INFY")
    assert quote is not None
    assert quote == 1550.50
    assert quote.close == 1550.50
    assert quote.open == 1530.0
    assert quote.high == 1560.0
    assert quote.low == 1525.0
    assert quote.volume == 125000
    assert quote.symbol == "INFY"
    assert quote.is_live is True

    # get_current_price returns the fresh quote
    price = clock.get_current_price("INFY")
    assert price == 1550.50
    assert price.is_live is True


def test_live_mode_missing_quote():
    """Verifies LiveQuoteUnavailableError when feed is connected but symbol has no quote."""
    mock_feed = MagicMock()
    mock_feed.is_connected = True
    mock_feed.get_latest_quote.return_value = None

    clock = MarketClock(mode=ClockMode.LIVE, feed=mock_feed)
    assert clock.get_live_quote("TCS") is None

    with pytest.raises(LiveQuoteUnavailableError) as exc_info:
        clock.get_current_price("TCS")
    assert "No quote exists in feed cache" in str(exc_info.value)


def test_live_mode_stale_quote():
    """Verifies LiveQuoteUnavailableError when quote exceeds freshness threshold."""
    mock_feed = MagicMock()
    mock_feed.is_connected = True

    stale_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    stale_quote = UpstoxQuote(
        symbol="RELIANCE",
        instrument_key="NSE_EQ|INE002A01018",
        ltp=2900.0,
        receipt_timestamp=stale_time,
    )
    mock_feed.get_latest_quote.return_value = stale_quote

    clock = MarketClock(mode=ClockMode.LIVE, feed=mock_feed, max_quote_age_seconds=15.0)
    assert clock.get_live_quote("RELIANCE") is None

    with pytest.raises(LiveQuoteUnavailableError) as exc_info:
        clock.get_current_price("RELIANCE")
    assert "stale" in str(exc_info.value).lower()


def test_live_mode_never_falls_back_to_historical():
    """Proves that LIVE mode never falls back to historical database prices when live quote is unavailable."""
    # Database contains historical price bar for INFY at 1818.0
    mock_feed = MagicMock()
    mock_feed.is_connected = False
    mock_feed.get_latest_quote.return_value = None

    clock = MarketClock(mode=ClockMode.LIVE, feed=mock_feed)

    # get_current_bar must return None in LIVE mode
    assert clock.get_current_bar("INFY") is None

    # get_current_price must raise LiveQuoteUnavailableError rather than returning DB price (1818.0)
    with pytest.raises(LiveQuoteUnavailableError) as exc_info:
        clock.get_current_price("INFY")
    assert "Feed is disconnected" in str(exc_info.value)


def test_live_mode_feed_injection_and_diagnostics():
    """Verifies feed setter/getter and diagnostic status reporting."""
    clock = MarketClock(mode=ClockMode.LIVE, feed=None, auto_attach_feed=False)
    assert clock.feed is None

    diag = clock.check_live_quote_status("SBIN")
    assert diag["is_available"] is False
    assert diag["reason"] == "Feed service is not attached"

    mock_feed = MagicMock()
    mock_feed.is_connected = True
    mock_feed.get_latest_quote.return_value = None
    clock.set_feed(mock_feed)
    assert clock.feed is mock_feed

    diag2 = clock.check_live_quote_status("SBIN")
    assert diag2["is_available"] is False
    assert "No quote exists in feed cache" in diag2["reason"]


def test_clock_mode_switching():
    """Verifies seamless switching between LIVE and REPLAY modes."""
    clock = MarketClock(mode=ClockMode.LIVE)
    assert clock.mode == ClockMode.LIVE

    clock.set_mode(ClockMode.REPLAY, replay_date="2022-03-10", start_time="10:15")
    assert clock.mode == ClockMode.REPLAY
    assert clock.current_time == datetime(2022, 3, 10, 10, 15, 0)

    price = clock.get_current_price("INFY")
    assert price == 1818.0
