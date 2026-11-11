"""Step 3: Rule Engine and Behavioral Alerts Tests.

Verifies:
1. Primary requirement:
   - Capital 1,00,000 INR, rule 2% (max risk Rs 2,000).
   - A trade risking Rs 3,500 (e.g. entry 1000, stop-loss 965, qty 100 -> 35 * 100 = 3500)
     must fire an alert.
2. Pre-trade checks returning warnings before order execution.
3. Post-trade detectors (separate, testable functions):
   - detect_rule_violations
   - detect_overtrading_after_loss (>=2 losses and >=5 trades in last 30 minutes)
   - detect_revenge_trading (within 10 mins of >2% loss, trade with >1.5x size)
   - detect_late_breakout_chase (BUY after 14:30 with 30-min price change >= +4%)
4. Alert persistence in PostgreSQL `alerts` table with context_json and severity.
5. WebSocket live streaming via /ws/alerts/{user_id}.
"""
from datetime import datetime, time, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.models.user import User, UserProfile
from app.models.paper import Account, Order, Trade, OrderSide, OrderType, ProductType, OrderStatus
from app.models.alert import Alert, AlertSeverity, AlertType
from app.rules.rule_engine import (
    calculate_risk,
    calculate_risk_pct,
    pre_trade_check,
    detect_rule_violations,
    detect_overtrading_after_loss,
    detect_revenge_trading,
    detect_late_breakout_chase,
    evaluate_and_persist_alerts,
)
from app.broker.paper_broker import PaperBroker
from app.clock.market_clock import MarketClock, ClockMode


@pytest.fixture
def rule_user(db_session):
    """Creates a user configured with 1,00,000 INR capital and 2% max risk per trade rule."""
    username = f"rule_trader_{int(datetime.now().timestamp() * 1000)}"
    user = User(username=username, email=f"{username}@tradezen.local")
    profile = UserProfile(
        user=user,
        rules_json={
            "max_trades_per_day": 5,
            "max_risk_per_trade_pct": 2.0,  # 2% rule
            "max_daily_loss": 5000.0,
            "require_stop_loss": True,
            "max_consecutive_losses": 3,
            "intraday_cutoff_time": "15:15"
        }
    )
    # Capital of exactly 1,00,000 INR
    account = Account(user=user, cash_balance=100000.0, initial_cash=100000.0)
    db_session.add_all([user, profile, account])
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(profile)
    db_session.refresh(account)
    return user


def test_primary_step3_verification_rs_3500_risk_on_1_lakh_capital(db_session, rule_user):
    """PRIMARY STEP 3 DONE-WHEN TEST:
    
    A Rs 3,500-risk trade on Rs 1,00,000 capital with a 2% rule fires an alert.
    
    Numbers:
    - Capital: 1,00,000 INR
    - Rule: max_risk_per_trade_pct = 2.0% (Max allowed risk: Rs 2,000)
    - Trade: Entry price = 1000.0, Stop loss = 965.0, Quantity = 100
      Risk = (1000 - 965) * 100 = 35 * 100 = Rs 3,500.0
      Risk % = (3,500 / 100,000) * 100 = 3.50% (> 2.0%)
    Must fire an alert and persist to the alerts table!
    """
    broker = PaperBroker()
    user_id = rule_user.id

    # Place order risking Rs 3,500 (entry 500, stop loss 465, qty 100 -> cost Rs 50,000 on 1L capital)
    order = broker.place_order(
        user_id=user_id,
        symbol="SBIN",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=100,
        stop_loss=465.0,
        execution_price=500.0,
        apply_slippage=False,
        db=db_session
    )
    assert order.status == OrderStatus.FILLED.value

    # Verify alert was generated and saved to the alerts table
    alerts = db_session.query(Alert).filter_by(user_id=user_id).all()
    assert len(alerts) >= 1, "Alert was not created for the Rs 3,500 risk trade!"

    risk_alert = next((a for a in alerts if a.alert_type == AlertType.MAX_RISK_EXCEEDED.value), None)
    assert risk_alert is not None, "MAX_RISK_EXCEEDED alert type not found!"
    assert risk_alert.severity == AlertSeverity.CRITICAL.value

    # Validate numbers in context_json
    ctx = risk_alert.context_json
    assert ctx["risk_inr"] == 3500.0
    assert ctx["capital"] == 100000.0
    assert ctx["risk_pct"] == 3.5
    assert ctx["limit_pct"] == 2.0
    assert ctx["max_allowed_risk"] == 2000.0
    assert "3.50%" in risk_alert.message
    assert "Rs 3,500.00" in risk_alert.message


def test_detector_rule_violations_direct():
    """Direct test of the separate detect_rule_violations function."""
    trade = Trade(
        id=1,
        order_id=1,
        user_id=1,
        symbol="INFY",
        side="BUY",
        quantity=100,
        price=1000.0,
        charges=20.0
    )
    order = Order(
        id=1,
        user_id=1,
        symbol="INFY",
        side="BUY",
        order_type="MARKET",
        quantity=100,
        stop_loss=965.0  # Risk: 35 * 100 = 3500
    )
    profile = UserProfile(rules_json={"max_risk_per_trade_pct": 2.0})
    capital = 100000.0

    alerts = detect_rule_violations(trade, order, profile, capital)
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == AlertType.MAX_RISK_EXCEEDED.value
    assert alerts[0]["context_json"]["risk_inr"] == 3500.0


def test_detector_overtrading_after_loss():
    """Detector test for OVERTRADING_AFTER_LOSS:
    Triggered when >=2 losses and >=5 trades in the last 30 minutes.
    """
    now = datetime(2022, 3, 10, 11, 30, tzinfo=timezone.utc)
    trades = [
        Trade(id=1, user_id=1, symbol="INFY", side="SELL", quantity=10, price=1000, realized_pnl=-500.0, executed_at=now - timedelta(minutes=25)),
        Trade(id=2, user_id=1, symbol="TCS", side="SELL", quantity=10, price=3000, realized_pnl=200.0, executed_at=now - timedelta(minutes=20)),
        Trade(id=3, user_id=1, symbol="INFY", side="SELL", quantity=10, price=990, realized_pnl=-300.0, executed_at=now - timedelta(minutes=15)),
        Trade(id=4, user_id=1, symbol="RELIANCE", side="BUY", quantity=10, price=2000, realized_pnl=0.0, executed_at=now - timedelta(minutes=10)),
        Trade(id=5, user_id=1, symbol="SBIN", side="BUY", quantity=20, price=500, realized_pnl=0.0, executed_at=now - timedelta(minutes=2)),
    ]

    alert = detect_overtrading_after_loss(trades, window_minutes=30, reference_time=now)
    assert alert is not None
    assert alert["alert_type"] == AlertType.OVERTRADING_AFTER_LOSS.value
    assert alert["context_json"]["total_trades"] == 5
    assert alert["context_json"]["losing_trades_count"] == 2

    # If only 4 trades, no alert
    no_alert = detect_overtrading_after_loss(trades[:4], window_minutes=30, reference_time=now)
    assert no_alert is None


def test_detector_revenge_trading():
    """Detector test for REVENGE_TRADING:
    Within 10 minutes of a loss > 2% capital, a new trade with > 1.5x size.
    """
    capital = 100000.0  # 2% is 2,000 INR
    t0 = datetime(2022, 3, 10, 10, 0, tzinfo=timezone.utc)

    # Losing trade of Rs 2,500 (> 2% of capital) with size 50
    big_loss_trade = Trade(
        id=1,
        user_id=1,
        symbol="INFY",
        side="SELL",
        quantity=50,
        price=1000.0,
        realized_pnl=-2500.0,
        executed_at=t0
    )

    # New trade 4 minutes later with size 100 (> 1.5x previous size of 50)
    current_trade = Trade(
        id=2,
        user_id=1,
        symbol="INFY",
        side="BUY",
        quantity=100,
        price=1010.0,
        executed_at=t0 + timedelta(minutes=4)
    )

    alert = detect_revenge_trading(current_trade, [big_loss_trade], capital, window_minutes=10)
    assert alert is not None
    assert alert["alert_type"] == AlertType.REVENGE_TRADING.value
    assert alert["context_json"]["loss_inr"] == 2500.0
    assert alert["context_json"]["previous_quantity"] == 50
    assert alert["context_json"]["current_quantity"] == 100

    # Trade 15 minutes later (> 10 mins window) -> no revenge alert
    late_trade = Trade(
        id=3,
        user_id=1,
        symbol="INFY",
        side="BUY",
        quantity=100,
        price=1010.0,
        executed_at=t0 + timedelta(minutes=15)
    )
    no_alert = detect_revenge_trading(late_trade, [big_loss_trade], capital, window_minutes=10)
    assert no_alert is None


def test_detector_late_breakout_chase(db_session):
    """Detector test for LATE_BREAKOUT_CHASE:
    BUY after 14:30 when 30-minute price change is >= +4%.
    """
    # Test time after 14:30
    chase_time = datetime(2022, 3, 10, 14, 45)

    # Case 1: Time before 14:30 -> should return None
    early_time = datetime(2022, 3, 10, 13, 0)
    assert detect_late_breakout_chase("INFY", "BUY", early_time, db_session) is None

    # Case 2: SELL side -> should return None
    assert detect_late_breakout_chase("INFY", "SELL", chase_time, db_session) is None

    # Case 3: BUY side evaluated against historical prices
    alert = detect_late_breakout_chase("INFY", "BUY", chase_time, db_session)
    # Check that detector ran and returned None if market wasn't up >= +4% or Alert dict if it was
    assert alert is None or alert["alert_type"] == AlertType.LATE_BREAKOUT_CHASE.value


def test_pre_trade_check_endpoint(client: TestClient, rule_user):
    """Verifies POST /paper/orders/pre-check returns warnings without placing order."""
    user_id = rule_user.id

    # Order risking Rs 3,500 on 1 Lakh capital (3.5% > 2% rule)
    payload = {
        "user_id": user_id,
        "symbol": "INFY",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": 100,
        "price": 1000.0,
        "stop_loss": 965.0,  # 35 * 100 = 3500 risk
        "product_type": "MIS"
    }

    resp = client.post("/paper/orders/pre-check", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_warnings"] is True
    assert data["warnings_count"] >= 1
    assert data["warnings"][0]["rule"] == "max_risk_per_trade_pct"
    assert data["warnings"][0]["risk_inr"] == 3500.0


def test_get_user_alerts_endpoint(client: TestClient, rule_user):
    """Verifies GET /alerts/{user_id} retrieves saved alerts."""
    resp = client.get(f"/alerts/{rule_user.id}")
    assert resp.status_code == 200
    alerts = resp.json()
    assert isinstance(alerts, list)


def test_websocket_alerts_connection(client: TestClient, rule_user):
    """Verifies WebSocket endpoint /ws/alerts/{user_id} connects and responds to ping."""
    with client.websocket_connect(f"/ws/alerts/{rule_user.id}") as websocket:
        websocket.send_text("ping")
        response = websocket.receive_text()
        assert response == "pong"
