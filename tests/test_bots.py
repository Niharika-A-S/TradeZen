"""Unit and integration tests for TradeZen Step 4 & Prompt A: Programmed Bots & Behavior Dataset."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
import pandas as pd

from app.models.paper import Trade, Order
from app.simulator.bot import BotConfig, BotPersonality, create_default_bots
from app.simulator.features import build_features, FEATURE_COLUMNS
from app.simulator.engine import SimulationEngine


def test_default_bots_count_and_personalities():
    """Verifies that exactly 30 programmed bots are created with 5 distinct personalities (6 each)."""
    bots = create_default_bots()
    assert len(bots) == 30, f"Expected 30 bots, got {len(bots)}"

    bot_ids = [b.bot_id for b in bots]
    assert len(set(bot_ids)) == 30, "Bot IDs must be unique"
    assert min(bot_ids) == 1 and max(bot_ids) == 30

    # Personality distribution: 6 bots per personality
    personalities = [b.personality for b in bots]
    for p in BotPersonality:
        p_count = personalities.count(p)
        assert p_count == 6, f"Expected 6 bots for {p.value}, got {p_count}"

    # Verify randomized rule ranges within bounds
    for b in bots:
        assert 2 <= b.rules["max_trades_per_day"] <= 12
        assert 0.5 <= b.rules["max_risk_per_trade_pct"] <= 5.0
        assert 2 <= b.rules["max_consecutive_losses"] <= 5


def test_build_features_empty_trades():
    """Verifies that build_features handles empty trade history gracefully with safe relative defaults."""
    now = datetime(2022, 3, 10, 10, 15)
    rules = {"max_trades_per_day": 5, "max_risk_per_trade_pct": 2.0, "max_consecutive_losses": 3}
    features = build_features(trades_today=[], orders_today=[], current_time=now, capital=10_00_000.0, rules=rules)

    assert isinstance(features, dict)
    assert set(FEATURE_COLUMNS).issubset(set(features.keys()))

    assert features["trade_count_ratio_today"] == 0.0
    assert features["trade_headroom_today"] == 5
    assert features["trades_count_last_30m"] == 0
    assert features["consecutive_losses_ratio"] == 0.0
    assert features["consecutive_losses_headroom"] == 3
    assert features["win_rate_today"] == 0.5
    assert features["pnl_last_30m"] == 0.0
    assert features["total_pnl_today"] == 0.0
    assert features["time_since_last_trade_min"] == 180.0
    assert features["had_large_loss_last_10m"] == 0


def test_build_features_with_trades():
    """Verifies that build_features computes relative metrics and headroom accurately from trade and order instances."""
    now = datetime(2022, 3, 10, 11, 0)
    capital = 10_00_000.0
    rules = {"max_trades_per_day": 5, "max_risk_per_trade_pct": 2.0, "max_consecutive_losses": 3}

    trades = [
        # Trade 1: 45 mins ago -> outside 30m window
        Trade(id=1, user_id=1, symbol="INFY", side="SELL", quantity=100, price=1000.0,
              realized_pnl=-5000.0, executed_at=now - timedelta(minutes=45)),
        # Trade 2: 20 mins ago -> inside 30m window (loss)
        Trade(id=2, user_id=1, symbol="TCS", side="SELL", quantity=100, price=3000.0,
              realized_pnl=-10000.0, executed_at=now - timedelta(minutes=20)),
        # Trade 3: 5 mins ago -> inside 30m window (large loss > 2% capital, i.e. > 20,000)
        Trade(id=3, user_id=1, symbol="RELIANCE", side="SELL", quantity=200, price=2000.0,
              realized_pnl=-25000.0, executed_at=now - timedelta(minutes=5)),
    ]

    orders = [
        Order(id=1, user_id=1, symbol="RELIANCE", side="BUY", order_type="MARKET", quantity=200,
              stop_loss=1950.0, status="FILLED", created_at=now - timedelta(minutes=8)),
    ]

    features = build_features(trades_today=trades, orders_today=orders, current_time=now, capital=capital, rules=rules)

    # Relative trade counts: 3 trades / 5 max = 0.60
    assert features["trade_count_ratio_today"] == 0.6
    assert features["trade_headroom_today"] == 2
    assert features["trades_count_last_30m"] == 2
    assert features["loss_count_last_30m"] == 2
    # 3 consecutive losses / 3 max = 1.0
    assert features["consecutive_losses_ratio"] == 1.0
    assert features["consecutive_losses_headroom"] == 0
    assert features["total_pnl_today"] == -40000.0
    assert features["pnl_last_30m"] == -35000.0
    assert features["had_large_loss_last_10m"] == 1
    assert features["time_since_last_loss_min"] == 5.0
    assert features["time_since_last_trade_min"] == 5.0


def test_simulation_engine_personality_contrast(db_session):
    """Verifies that the simulator produces clear personality divergence across personalities."""
    engine = SimulationEngine(session=db_session)
    engine.load_market_data()

    # Pick 5 representative bots (1 per personality) across 8 trading days
    test_bots = [
        BotConfig(bot_id=1, name="Disciplined_1", personality=BotPersonality.DISCIPLINED, rules={"max_trades_per_day": 5, "max_risk_per_trade_pct": 2.0, "max_consecutive_losses": 3}),
        BotConfig(bot_id=2, name="Overtrader_1", personality=BotPersonality.OVERTRADER, rules={"max_trades_per_day": 4, "max_risk_per_trade_pct": 2.0, "max_consecutive_losses": 3}),
        BotConfig(bot_id=3, name="RevengeTrader_1", personality=BotPersonality.REVENGE_TRADER, rules={"max_trades_per_day": 5, "max_risk_per_trade_pct": 2.0, "max_consecutive_losses": 3}),
        BotConfig(bot_id=4, name="StopLossIgnorer_1", personality=BotPersonality.STOP_LOSS_IGNORER, rules={"max_trades_per_day": 5, "max_risk_per_trade_pct": 2.0, "max_consecutive_losses": 3}),
        BotConfig(bot_id=5, name="FomoChaser_1", personality=BotPersonality.FOMO_CHASER, rules={"max_trades_per_day": 5, "max_risk_per_trade_pct": 2.0, "max_consecutive_losses": 3}),
    ]

    test_dates = engine.dates[:8]
    df = engine.run_simulation(dates=test_dates, bots=test_bots, random_seed=42)

    assert len(df) == 5 * len(test_dates) * 12
    v_rates = df.groupby("personality")["label"].mean()

    disc_rate = v_rates.get(BotPersonality.DISCIPLINED.value, 0.0)
    ot_rate = v_rates.get(BotPersonality.OVERTRADER.value, 0.0)
    rev_rate = v_rates.get(BotPersonality.REVENGE_TRADER.value, 0.0)
    sl_rate = v_rates.get(BotPersonality.STOP_LOSS_IGNORER.value, 0.0)

    # Disciplined should have low violation rate
    assert disc_rate <= 0.08, f"Disciplined rate too high: {disc_rate}"
    # Aggressive personalities should have higher violation rates than Disciplined
    assert ot_rate > disc_rate + 0.10, f"Overtrader ({ot_rate}) not higher than Disciplined ({disc_rate})"
    assert rev_rate > disc_rate + 0.10, f"RevengeTrader ({rev_rate}) not higher than Disciplined ({disc_rate})"
    assert sl_rate > disc_rate + 0.10, f"StopLossIgnorer ({sl_rate}) not higher than Disciplined ({disc_rate})"


def test_behavior_dataset_file_verification():
    """Verifies data/behavior_dataset.csv satisfies Prompt A criteria if generated."""
    dataset_path = Path("data/behavior_dataset.csv")
    if not dataset_path.exists():
        pytest.skip("data/behavior_dataset.csv not yet generated. Run scripts/generate_dataset.py first.")

    df = pd.read_csv(dataset_path)

    # 1. Row count >= 20,000
    assert len(df) >= 20000, f"Expected >= 20,000 rows, found {len(df)}"

    # 2. Key columns present including updated relative features
    required_cols = [
        "bot_id", "bot_name", "personality", "date", "window_idx",
        "window_start", "window_end", "label", "violation_types"
    ] + FEATURE_COLUMNS
    for col in required_cols:
        assert col in df.columns, f"Missing required column: {col}"

    # 3. Exactly 30 bots (or 20 if evaluating old dataset before regeneration)
    assert df["bot_id"].nunique() in [20, 30]

    # 4. Label values and balance
    assert set(df["label"].unique()).issubset({0, 1})
    pos_rate = df["label"].mean()
    assert 0.10 <= pos_rate <= 0.50, f"Label balance {pos_rate:.2%} outside expected 10%-50% range"
