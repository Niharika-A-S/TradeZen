"""End-to-end HTTP tests for TradeZen Coach chat endpoints.

Holds one user and one closed losing trade in a throwaway SQLite database.
Verifies last-trade explanation with fake LLM success, fake LLM failure,
and hallucinated numbers failure.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base as RealBase
from app.models.user import User, UserProfile
from app.models.paper import Trade, Position, Order
from app.models.alert import Alert
from app.chatbot.models import Base as ChatbotBase
from app.chatbot.llm import LLMResult, llm_client
from app.chatbot.api import get_current_user_id
from app.api.main import app


@pytest.fixture
def throwaway_http_db(tmp_path):
    """Creates an isolated temporary SQLite database with throwaway schema and fixtures."""
    db_file = tmp_path / "test_http_throwaway.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})

    # Create real and chatbot tables
    RealBase.metadata.create_all(engine)
    ChatbotBase.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    # Fixture: 1 User
    test_user_id = 999
    user = User(
        id=test_user_id,
        email="coach_tester@tradezen.com",
        username="coachtester",
        hashed_password="fakehashpassword"
    )
    session.add(user)

    user_profile = UserProfile(
        id=1,
        user_id=test_user_id,
        rules_json={"max_trades_per_day": 5, "require_stop_loss": True}
    )
    session.add(user_profile)

    now = datetime.now(timezone.utc)
    t_open = now - timedelta(minutes=45)
    t_close = now - timedelta(minutes=15)

    # Fixture: 1 Closed Losing Trade (BUY 100 shares @ ₹500, SELL 100 shares @ ₹450 -> loss of ₹5,000)
    buy_trade = Trade(
        id=101,
        order_id=1,
        user_id=test_user_id,
        symbol="TATAMOTORS",
        side="BUY",
        product_type="INTRADAY",
        quantity=100,
        price=500.0,
        charges=20.0,
        realized_pnl=0.0,
        net_realized_pnl=0.0,
        executed_at=t_open
    )
    sell_trade = Trade(
        id=102,
        order_id=2,
        user_id=test_user_id,
        symbol="TATAMOTORS",
        side="SELL",
        product_type="INTRADAY",
        quantity=100,
        price=450.0,
        charges=20.0,
        realized_pnl=-5000.0,
        net_realized_pnl=-5000.0,
        executed_at=t_close
    )
    session.add(buy_trade)
    session.add(sell_trade)

    alert = Alert(
        id=1,
        user_id=test_user_id,
        alert_type="RULE_VIOLATION",
        severity="WARNING",
        message="Stop-loss was not respected on TATAMOTORS exit.",
        created_at=t_close
    )
    session.add(alert)
    session.commit()
    session.close()

    from contextlib import contextmanager

    @contextmanager
    def _session_scope():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    with patch("app.chatbot.adapters.get_readonly_session", side_effect=_session_scope), \
         patch("app.chatbot.profile.get_readonly_session", side_effect=_session_scope), \
         patch("app.chatbot.profile.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.models.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.brain.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.api.get_db_session", side_effect=lambda: Session()):
        yield test_user_id, Session


def test_explain_last_trade_success_with_fake_llm(throwaway_http_db):
    """With a functioning fake LLM:

    Asserts:
    - route is 'MY_DATA'
    - used_data is True
    - degraded is False
    - degraded_reason is None
    - reply contains the trade's exact figures (100 shares, ₹500, ₹450, -₹5,000, 30 minutes)
    """
    user_id, Session = throwaway_http_db

    # Override auth dependency
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    # Fake LLM returns structured response using exact trade figures from facts
    def fake_generate(system=None, messages=None, max_output_tokens=600, temperature=0.2):
        text = (
            "1) Your last trade was 100 shares of TATAMOTORS bought at ₹500.00 and sold at ₹450.00 "
            "after 30.0 minutes, resulting in a loss of -₹5,000.00.\n"
            "2) Your typical position size is 100 shares.\n"
            "3) Rules recorded: RULE_VIOLATION.\n"
            "4) The data suggests you held past your planned risk limit.\n"
            "5) One small habit to try: set a hard stop-loss immediately upon entry.\n"
            "6) What caused you to delay the exit?"
        )
        return LLMResult(ok=True, text=text)

    llm_client._fake_generate = fake_generate
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "Explain my last trade"})

        assert response.status_code == 200
        data = response.json()
        assert data["route"] == "MY_DATA"
        assert data["used_data"] is True
        assert data["degraded"] is False
        assert data["degraded_reason"] is None

        reply = data["reply"]
        assert "100" in reply
        assert "TATAMOTORS" in reply
        assert "500" in reply
        assert "450" in reply
        assert "5,000" in reply or "5000" in reply
    finally:
        llm_client._fake_generate = None
        app.dependency_overrides.clear()


def test_explain_last_trade_llm_failure_returns_template_and_degraded_reason(throwaway_http_db):
    """With the LLM failing:

    Asserts:
    - route is 'MY_DATA'
    - used_data is True
    - degraded is True
    - degraded_reason is 'llm_error'
    - reply is a deterministic template containing the trade's exact figures
    - reply is NEVER the generic greeting
    """
    user_id, Session = throwaway_http_db

    app.dependency_overrides[get_current_user_id] = lambda: user_id

    def fake_failing_generate(system=None, messages=None, max_output_tokens=600, temperature=0.2):
        return LLMResult(ok=False, error_kind="NETWORK_ERROR")

    llm_client._fake_generate = fake_failing_generate
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "Explain my last trade"})

        assert response.status_code == 200
        data = response.json()
        assert data["route"] == "MY_DATA"
        assert data["used_data"] is True
        assert data["degraded"] is True
        assert data["degraded_reason"] == "llm_error"

        reply = data["reply"]
        assert "Hello! I am your TradeZen Coach" not in reply
        assert "100 shares of TATAMOTORS" in reply
        assert "500.00" in reply
        assert "450.00" in reply
        assert "5,000.00" in reply or "5000" in reply
        assert "30.0 minutes" in reply
    finally:
        llm_client._fake_generate = None
        app.dependency_overrides.clear()


def test_explain_last_trade_numbers_check_fails_twice_returns_template(throwaway_http_db):
    """With LLM hallucinating numbers that fail the numbers check twice:

    Asserts:
    - route is 'MY_DATA'
    - used_data is True
    - degraded is True
    - degraded_reason is 'numbers_check_failed'
    - deterministic template is returned with the exact trade figures
    """
    user_id, Session = throwaway_http_db

    app.dependency_overrides[get_current_user_id] = lambda: user_id

    # Hallucinating LLM inventing numbers not in facts (e.g. 88888, 99999)
    def fake_hallucinating_generate(system=None, messages=None, max_output_tokens=600, temperature=0.2):
        return LLMResult(ok=True, text="You bought 88888 shares at ₹99999.")

    llm_client._fake_generate = fake_hallucinating_generate
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "Explain my last trade"})

        assert response.status_code == 200
        data = response.json()
        assert data["route"] == "MY_DATA"
        assert data["used_data"] is True
        assert data["degraded"] is True
        assert data["degraded_reason"] == "numbers_check_failed"

        reply = data["reply"]
        assert "Hello! I am your TradeZen Coach" not in reply
        assert "100 shares of TATAMOTORS" in reply
        assert "500.00" in reply
        assert "450.00" in reply
    finally:
        llm_client._fake_generate = None
        app.dependency_overrides.clear()
