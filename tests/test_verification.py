"""Primary verification test for Step 1 of TradeZen.

Verifies:
get_price("INFY", "2022-03-10 10:15") returns the exact price from the CSV.
Also verifies all 5 stocks at this timestamp against the historical dataset.
"""
import pytest
from app.clock.market_clock import get_price, get_bar


def test_step_1_primary_verification_infy():
    """Main verification requirement:
    get_price('INFY', '2022-03-10 10:15') must return the price from the CSV.
    """
    price = get_price("INFY", "2022-03-10 10:15")

    # 1. Direct float comparison (price == 1818.0)
    assert price == 1818.0, f"Expected 1818.0 but got {price}"
    assert float(price) == 1818.0

    # 2. Bar attribute checks matching CSV row 656454:
    # 2022-03-10 10:15:00,1821.0,1821.1,1817.2,1818.0,21359
    assert price.close == 1818.0
    assert price.open == 1821.0
    assert price.high == 1821.1
    assert price.low == 1817.2
    assert price.volume == 21359
    assert price.symbol == "INFY"


def test_step_1_verification_all_5_symbols():
    """Verifies historical prices across all 5 symbols at 2022-03-10 10:15."""
    target_ts = "2022-03-10 10:15"

    expected_prices = {
        "INFY": {"close": 1818.0, "open": 1821.0, "high": 1821.1, "low": 1817.2, "volume": 21359},
        "RELIANCE": {"close": 1137.8, "open": 1137.85, "high": 1137.95, "low": 1137.65, "volume": 18706},
        "TCS": {"close": 3636.0, "open": 3639.65, "high": 3639.9, "low": 3636.0, "volume": 6809},
        "HDFCBANK": {"close": 705.0, "open": 703.4, "high": 705.0, "low": 703.2, "volume": 82298},
        "SBIN": {"close": 474.25, "open": 474.65, "high": 474.75, "low": 474.2, "volume": 119729},
    }

    for symbol, expected in expected_prices.items():
        price = get_price(symbol, target_ts)
        assert price == expected["close"], f"{symbol} close mismatch: expected {expected['close']}, got {price}"
        assert price.close == expected["close"]
        assert price.open == expected["open"]
        assert price.high == expected["high"]
        assert price.low == expected["low"]
        assert price.volume == expected["volume"]
        assert price.symbol == symbol


def test_get_bar_returns_price_bar_model():
    """Verifies get_bar returns SQLAlchemy PriceBar model instance."""
    bar = get_bar("INFY", "2022-03-10 10:15")
    assert bar is not None
    assert bar.symbol == "INFY"
    assert bar.close == 1818.0
    assert bar.volume == 21359
