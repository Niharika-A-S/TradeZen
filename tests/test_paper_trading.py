"""Step 2: Paper-Trading Engine Tests.

Verifies:
1. Required specification test:
   - Buy 100 @ 1500, buy 100 @ 1520 -> average price must be 1510.
   - Price moves to 1530 -> unrealized P&L must be Rs 4,000.
   - Sell 100 @ 1520 -> realized P&L must be Rs 2,000 minus charges (Rs 20).
2. Starting account balance at 10,00,000 INR fake cash.
3. Market orders with 0.05% slippage in adverse direction.
4. Limit orders staying pending until conditions met.
5. Rejection of orders that exceed available cash.
6. Rejection of sell orders exceeding owned quantity (no short selling).
7. Intraday (MIS) auto-square-off at cutoff time (15:15).
8. Paper trading API endpoints: POST /paper/orders, GET /paper/account,
   GET /paper/positions, GET /paper/trades, DELETE /paper/orders/{order_id}.
"""
from datetime import datetime, time
import pytest
from fastapi.testclient import TestClient

from app.models.user import User, UserProfile
from app.models.paper import (
    Account,
    Order,
    Trade,
    Position,
    OrderSide,
    OrderType,
    ProductType,
    OrderStatus,
    INITIAL_PAPER_CASH,
    ORDER_CHARGES,
    SLIPPAGE_RATE,
)
from app.broker.paper_broker import PaperBroker
from app.clock.market_clock import MarketClock, ClockMode


@pytest.fixture
def test_user(db_session):
    """Creates an isolated test user and account for each test."""
    username = f"trader_{int(datetime.now().timestamp() * 1000)}"
    user = User(username=username, email=f"{username}@tradezen.local")
    profile = UserProfile(user=user)
    account = Account(user=user, cash_balance=INITIAL_PAPER_CASH, initial_cash=INITIAL_PAPER_CASH)
    db_session.add_all([user, profile, account])
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(account)
    return user


def test_required_avg_price_pnl_verification(db_session, test_user, monkeypatch):
    """Primary Required Verification Test:

    Buy 100 @ 1500, buy 100 @ 1520 -> avg must be 1510.
    Price 1530 gives unrealized P&L Rs 4,000.
    Sell 100 @ 1520 gives realized P&L Rs 2,000 minus charges (Rs 1,980 net).
    """
    broker = PaperBroker()
    user_id = test_user.id

    # Make market price deterministic for this test
    monkeypatch.setattr(
        broker,
        "get_current_market_price",
        lambda symbol, db: 1500.0
    )

    # 1. Buy 100 @ 1500
    order1 = broker.place_order(
        user_id=user_id,
        symbol="TEST_STOCK",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=100,
        execution_price=1500.0,
        product_type=ProductType.MIS.value,
        db=db_session
    )
    assert order1.status == OrderStatus.FILLED.value
    assert order1.average_fill_price == 1500.0
    assert order1.charges == 20.0

    pos = db_session.query(Position).filter_by(user_id=user_id, symbol="TEST_STOCK").first()
    assert pos is not None
    assert pos.quantity == 100
    assert pos.average_price == 1500.0

    # 2. Buy 100 @ 1520
    order2 = broker.place_order(
        user_id=user_id,
        symbol="TEST_STOCK",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=100,
        execution_price=1520.0,
        product_type=ProductType.MIS.value,
        db=db_session
    )
    assert order2.status == OrderStatus.FILLED.value
    assert order2.average_fill_price == 1520.0

    # Required check 1: Average price must be 1510!
    db_session.refresh(pos)
    assert pos.quantity == 200
    assert pos.average_price == 1510.0, f"Expected avg price 1510, got {pos.average_price}"

    # Required check 2: Price 1530 gives unrealized P&L Rs 4,000!
    current_price = 1530.0
    pos_dict = pos.to_dict(current_price=current_price)
    expected_unrealized_pnl = (current_price - pos.average_price) * pos.quantity  # (1530 - 1510) * 200 = 4000
    assert pos_dict["unrealized_pnl"] == 4000.0
    assert expected_unrealized_pnl == 4000.0

    # Required check 3: Sell 100 @ 1520 gives realized P&L Rs 2,000 minus charges!
    order3 = broker.place_order(
        user_id=user_id,
        symbol="TEST_STOCK",
        side=OrderSide.SELL.value,
        order_type=OrderType.MARKET.value,
        quantity=100,
        execution_price=1520.0,
        product_type=ProductType.MIS.value,
        db=db_session
    )
    assert order3.status == OrderStatus.FILLED.value
    assert order3.average_fill_price == 1520.0
    assert order3.charges == 20.0

    # Fetch trade execution
    trade = db_session.query(Trade).filter_by(order_id=order3.id).first()
    assert trade is not None
    # Realized P&L is Rs 2,000 (FIFO matched against the 1500 lot: (1520 - 1500) * 100 = 2000)
    assert trade.realized_pnl == 2000.0, f"Expected gross realized PnL 2000.0, got {trade.realized_pnl}"
    assert trade.charges == 20.0
    # Net realized P&L is Rs 2,000 minus charges (Rs 1,980)
    assert trade.net_realized_pnl == 2000.0 - trade.charges, f"Expected net PnL 1980.0, got {trade.net_realized_pnl}"
    assert trade.net_realized_pnl == 1980.0

    db_session.refresh(pos)
    assert pos.quantity == 100


def test_initial_fake_cash_balance(db_session, test_user):
    """Account starts at 10,00,000 INR of fake cash."""
    broker = PaperBroker()
    summary = broker.get_account_summary(test_user.id, db=db_session)
    assert summary["cash_balance"] == 10_00_000.0
    assert summary["portfolio_value"] == 10_00_000.0
    assert summary["realized_pnl"] == 0.0
    assert summary["unrealized_pnl"] == 0.0


def test_market_order_slippage(db_session, test_user):
    """MARKET order fills at current price plus 0.05% slippage in adverse direction."""
    broker = PaperBroker()
    user_id = test_user.id

    market_price = 1000.0
    # BUY: pays +0.05%
    buy_slippage = broker.calculate_slippage_price(OrderSide.BUY.value, market_price)
    assert buy_slippage == 1000.5  # 1000 * 1.0005

    # SELL: receives -0.05%
    sell_slippage = broker.calculate_slippage_price(OrderSide.SELL.value, market_price)
    assert sell_slippage == 999.5  # 1000 * 0.9995


def test_insufficient_funds_rejection(db_session, test_user):
    """Reject orders that exceed available cash."""
    broker = PaperBroker()
    user_id = test_user.id

    # Try to buy 1,000 shares @ 2,000 INR = 20,00,000 INR (exceeds 10L cash)
    order = broker.place_order(
        user_id=user_id,
        symbol="INFY",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=1000,
        execution_price=2000.0,
        db=db_session
    )
    assert order.status == OrderStatus.REJECTED.value
    assert "Insufficient funds" in order.rejection_reason


def test_no_short_selling_rejection(db_session, test_user):
    """Reject sell orders that exceed owned quantity (no short selling)."""
    broker = PaperBroker()
    user_id = test_user.id

    # User owns 0 shares of TCS, attempts to sell 50
    order = broker.place_order(
        user_id=user_id,
        symbol="TCS",
        side=OrderSide.SELL.value,
        order_type=OrderType.MARKET.value,
        quantity=50,
        execution_price=3500.0,
        db=db_session
    )
    assert order.status == OrderStatus.REJECTED.value
    assert "No short selling allowed" in order.rejection_reason


def test_limit_order_pending_stays_pending_and_can_cancel(db_session, test_user, monkeypatch):
    """LIMIT BUY order at price below market stays PENDING, and can be cancelled.

    Market price is mocked to 1500 so a BUY limit at 1400 is not filled
    (buy fills only when market_price <= limit_price, i.e. 1500 > 1400).
    """
    broker = PaperBroker()
    user_id = test_user.id

    # Mock market price to 1500 so limit @ 1400 stays pending
    monkeypatch.setattr(
        broker,
        "get_current_market_price",
        lambda symbol, db: 1500.0
    )

    # Place buy limit @ 1400 (current market price is 1500 -> stays PENDING)
    order = broker.place_order(
        user_id=user_id,
        symbol="INFY",
        side=OrderSide.BUY.value,
        order_type=OrderType.LIMIT.value,
        price=1400.0,
        quantity=10,
        execution_price=None,
        db=db_session
    )
    assert order.status == OrderStatus.PENDING.value, (
        f"Expected PENDING but got {order.status}. "
        f"Market price (mocked 1500) > limit price (1400), so order must stay pending."
    )

    # Cancel the pending order
    cancelled = broker.cancel_order(order.id, user_id=user_id, db=db_session)
    assert cancelled.status == OrderStatus.CANCELLED.value


def test_intraday_auto_square_off_at_cutoff(db_session, test_user):
    """Intraday (MIS) positions are auto-squared-off at cutoff time (15:15)."""
    clock = MarketClock(mode=ClockMode.REPLAY, replay_date="2022-03-10", start_time="15:10")
    broker = PaperBroker(clock=clock)
    user_id = test_user.id

    # Buy 10 MIS shares at 15:10
    broker.place_order(
        user_id=user_id,
        symbol="INFY",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=10,
        execution_price=1800.0,
        product_type=ProductType.MIS.value,
        db=db_session
    )

    pos = db_session.query(Position).filter_by(user_id=user_id, symbol="INFY", product_type="MIS").first()
    assert pos.quantity == 10

    # Advance clock to 15:15 (cutoff time)
    clock.tick(5)
    assert clock.current_time.time() == time(15, 15)

    # Trigger square-off
    squared = broker.auto_square_off_intraday(user_id=user_id, db=db_session)
    assert len(squared) == 1
    assert squared[0].side == OrderSide.SELL.value

    # Position should now be 0
    db_session.refresh(pos)
    assert pos.quantity == 0


def test_paper_trading_api_endpoints(client: TestClient, test_user):
    """Verifies all required REST endpoints:
    POST /paper/orders, GET /paper/account, GET /paper/positions, GET /paper/trades, DELETE /paper/orders/{id}
    """
    user_id = test_user.id

    # 1. POST /paper/orders
    order_payload = {
        "user_id": user_id,
        "symbol": "INFY",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": 10,
        "product_type": "MIS",
        "apply_slippage": True
    }
    resp = client.post("/paper/orders", json=order_payload)
    assert resp.status_code == 201
    order_data = resp.json()
    assert order_data["symbol"] == "INFY"
    assert order_data["status"] == "FILLED"
    assert order_data["charges"] == 20.0

    # 2. GET /paper/account
    acc_resp = client.get(f"/paper/account?user_id={user_id}")
    assert acc_resp.status_code == 200
    acc_data = acc_resp.json()
    assert acc_data["cash_balance"] < 10_00_000.0
    assert acc_data["open_positions_count"] == 1

    # 3. GET /paper/positions
    pos_resp = client.get(f"/paper/positions?user_id={user_id}")
    assert pos_resp.status_code == 200
    positions = pos_resp.json()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "INFY"
    assert positions[0]["quantity"] == 10

    # 4. GET /paper/trades
    trades_resp = client.get(f"/paper/trades?user_id={user_id}")
    assert trades_resp.status_code == 200
    trades = trades_resp.json()
    assert len(trades) >= 1
    assert trades[0]["symbol"] == "INFY"

    # 5. Place a limit order and DELETE /paper/orders/{order_id}
    limit_payload = {
        "user_id": user_id,
        "symbol": "RELIANCE",
        "side": "BUY",
        "order_type": "LIMIT",
        "price": 500.0,  # Below market price -> stays pending
        "quantity": 5
    }
    lim_resp = client.post("/paper/orders", json=limit_payload)
    assert lim_resp.status_code == 201
    lim_order = lim_resp.json()
    assert lim_order["status"] == "PENDING"
    order_id = lim_order["order_id"]

    del_resp = client.delete(f"/paper/orders/{order_id}?user_id={user_id}")
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["order"]["status"] == "CANCELLED"
