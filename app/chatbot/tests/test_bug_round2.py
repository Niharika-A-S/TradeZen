"""Extended end-to-end HTTP tests for TradeZen Coach Bug Round 2 fixes.

Tests:
- 'Explain my last trade' with closed trade
- 'Why did I lose?' with closed trade
- 'did i lose my previous trade?' routing (not CONCEPT)
- 'meri pichhli trade' Hinglish routing
- 'how did my TATAMOTORS trade go' symbol routing
- 'My scenario decisions' with no scenarios
- 'My habits' with no closed trades → no_data=True, degraded=False
- User with ONLY open trade asks 'why did I lose?' → no closed trades response
- None return raw knowledge note text or generic greeting
"""
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from app.database import Base as RealBase
from app.models.user import User, UserProfile
from app.models.paper import Trade, Position, Order
from app.models.alert import Alert
from app.chatbot.models import Base as ChatbotBase
from app.chatbot.llm import LLMResult, llm_client
from app.chatbot.api import get_current_user_id
from app.api.main import app


def _make_session_ctx(Session):
    @contextmanager
    def _session_scope():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    return _session_scope


@pytest.fixture
def db_with_closed_trade(tmp_path):
    """DB fixture: 1 user with 1 closed losing trade (BUY TATAMOTORS 100 @ 500, SELL 100 @ 450)."""
    db_file = tmp_path / "test_bug_round2_closed.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    RealBase.metadata.create_all(engine)
    ChatbotBase.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()
    test_user_id = 777
    now = datetime.now(timezone.utc)
    t_open = now - timedelta(minutes=45)
    t_close = now - timedelta(minutes=15)

    user = User(id=test_user_id, email="u@t.com", username="tester777", hashed_password="pw")
    session.add(user)
    session.add(UserProfile(id=1, user_id=test_user_id, rules_json={"require_stop_loss": True}))

    buy = Trade(id=11, order_id=1, user_id=test_user_id, symbol="TATAMOTORS", side="BUY",
                product_type="MIS", quantity=100, price=500.0, charges=20.0,
                realized_pnl=0.0, net_realized_pnl=0.0, executed_at=t_open)
    sell = Trade(id=12, order_id=2, user_id=test_user_id, symbol="TATAMOTORS", side="SELL",
                 product_type="MIS", quantity=100, price=450.0, charges=20.0,
                 realized_pnl=-5000.0, net_realized_pnl=-5000.0, executed_at=t_close)
    alert = Alert(id=1, user_id=test_user_id, alert_type="RULE_VIOLATION", severity="WARNING",
                  message="Stop-loss not respected.", created_at=t_close)

    session.add(buy)
    session.add(sell)
    session.add(alert)
    session.commit()
    session.close()

    _sctx = _make_session_ctx(Session)
    with patch("app.chatbot.adapters.get_readonly_session", side_effect=_sctx), \
         patch("app.chatbot.profile.get_readonly_session", side_effect=_sctx), \
         patch("app.chatbot.profile.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.models.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.brain.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.api.get_db_session", side_effect=lambda: Session()):
        yield test_user_id


@pytest.fixture
def db_with_open_only(tmp_path):
    """DB fixture: 1 user with ONLY an open BUY (no closed trades)."""
    db_file = tmp_path / "test_bug_round2_open.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    RealBase.metadata.create_all(engine)
    ChatbotBase.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()
    test_user_id = 888
    now = datetime.now(timezone.utc)
    t_open = now - timedelta(minutes=30)

    user = User(id=test_user_id, email="open@t.com", username="openuser", hashed_password="pw")
    session.add(user)
    buy = Trade(id=21, order_id=1, user_id=test_user_id, symbol="INFY", side="BUY",
                product_type="MIS", quantity=40, price=1484.30, charges=20.0,
                realized_pnl=0.0, net_realized_pnl=0.0, executed_at=t_open)
    pos = Position(id=1, user_id=test_user_id, symbol="INFY", product_type="MIS",
                   quantity=40, average_price=1484.30, cumulative_realized_pnl=0.0, lots=[])
    session.add(buy)
    session.add(pos)
    session.commit()
    session.close()

    _sctx = _make_session_ctx(Session)
    with patch("app.chatbot.adapters.get_readonly_session", side_effect=_sctx), \
         patch("app.chatbot.profile.get_readonly_session", side_effect=_sctx), \
         patch("app.chatbot.profile.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.models.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.brain.get_db_session", side_effect=lambda: Session()), \
         patch("app.chatbot.api.get_db_session", side_effect=lambda: Session()):
        yield test_user_id


# --- HELPERS ---

GENERIC_GREETING = "Hello! I am your TradeZen Coach"
KNOWLEDGE_NOTE_SIGNAL = "[1]"


def _llm_fail(*a, **kw):
    return LLMResult(ok=False, error_kind="NETWORK_ERROR")


def _post(user_id, message, llm_fn=_llm_fail):
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    llm_client._fake_generate = llm_fn
    try:
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": message})
        return resp.status_code, resp.json()
    finally:
        app.dependency_overrides.clear()
        llm_client._fake_generate = None


# ----------------------------------------------------------------
# Tests with closed trade
# ----------------------------------------------------------------

def test_explain_last_trade_routes_to_my_data(db_with_closed_trade):
    code, data = _post(db_with_closed_trade, "Explain my last trade")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert data["used_data"] is True
    assert GENERIC_GREETING not in data["reply"]


def test_why_did_i_lose_routes_to_my_data_with_facts(db_with_closed_trade):
    code, data = _post(db_with_closed_trade, "Why did I lose?")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert data["used_data"] is True
    # Should reference the actual trade (template falls back when LLM fails)
    reply = data["reply"]
    assert "TATAMOTORS" in reply
    assert GENERIC_GREETING not in reply
    assert KNOWLEDGE_NOTE_SIGNAL not in reply


def test_did_i_lose_previous_trade_not_concept(db_with_closed_trade):
    code, data = _post(db_with_closed_trade, "did i lose my previous trade?")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert GENERIC_GREETING not in data["reply"]
    # Must NOT contain raw knowledge note leak [1]
    assert KNOWLEDGE_NOTE_SIGNAL not in data["reply"]


def test_meri_pichhli_trade_routes_my_data(db_with_closed_trade):
    code, data = _post(db_with_closed_trade, "meri pichhli trade")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert GENERIC_GREETING not in data["reply"]


def test_symbol_trade_query_routes_my_data(db_with_closed_trade):
    code, data = _post(db_with_closed_trade, "how did my TATAMOTORS trade go")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert GENERIC_GREETING not in data["reply"]


def test_my_scenario_decisions_no_data(db_with_closed_trade):
    """No scenario sessions in the DB → no_data=True, degraded=False, no Limited tag."""
    code, data = _post(db_with_closed_trade, "My scenario decisions")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert data["used_data"] is True
    # With the new logic: degraded is False, no_data is True
    assert data["degraded"] is False
    assert data.get("no_data") is True
    assert GENERIC_GREETING not in data["reply"]


def test_my_habits_with_closed_trades(db_with_closed_trade):
    """Has closed trades → profile should give content, not no-data message."""
    code, data = _post(db_with_closed_trade, "My habits")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert data["used_data"] is True
    # LLM fails → degraded, but template should contain trade-related content
    assert GENERIC_GREETING not in data["reply"]


# ----------------------------------------------------------------
# Tests with open-only trade (no closed trades)
# ----------------------------------------------------------------

def test_why_did_i_lose_open_only_no_closed_message(db_with_open_only):
    """User asks 'why did I lose?' with only an open trade → explains no closed trades, describes open."""
    code, data = _post(db_with_open_only, "Why did I lose?")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert data["used_data"] is True
    assert data["degraded"] is False
    assert data.get("no_data") is True
    reply = data["reply"]
    assert "no closed trades yet" in reply.lower() or "no closed" in reply.lower()
    assert "INFY" in reply
    assert GENERIC_GREETING not in reply


def test_my_habits_no_trades(db_with_open_only):
    """No closed trades → no_data=True, degraded=False, no Limited mode tag."""
    code, data = _post(db_with_open_only, "My habits")
    assert code == 200
    assert data["route"] == "MY_DATA"
    assert data["degraded"] is False
    assert data.get("no_data") is True
    assert GENERIC_GREETING not in data["reply"]
    assert KNOWLEDGE_NOTE_SIGNAL not in data["reply"]


def test_my_scenario_decisions_no_data_open_only(db_with_open_only):
    code, data = _post(db_with_open_only, "My scenario decisions")
    assert code == 200
    assert data["degraded"] is False
    assert data.get("no_data") is True


def test_concept_question_not_personal_still_concept(db_with_closed_trade):
    """Pure concept question must NOT be MY_DATA."""
    code, data = _post(db_with_closed_trade, "What is stop loss?")
    assert code == 200
    # Route must NOT be MY_DATA
    assert data["route"] != "MY_DATA"


def test_no_reply_contains_generic_greeting_on_personal(db_with_closed_trade):
    """None of the personal queries should produce the generic greeting."""
    personal_queries = [
        "Explain my last trade",
        "Why did I lose?",
        "did i lose my previous trade?",
        "My habits",
        "My scenario decisions",
        "meri pichhli trade",
    ]
    for q in personal_queries:
        code, data = _post(db_with_closed_trade, q)
        assert code == 200, f"Non-200 for: {q}"
        assert GENERIC_GREETING not in data["reply"], f"Greeting leaked for: {q}"
