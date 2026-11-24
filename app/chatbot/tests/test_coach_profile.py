"""Comprehensive tests for TradeZen Coach personalization, profile build, adapters, guards, and safety.

Uses throwaway database only. Never touches real database.
"""
from datetime import datetime, timezone, timedelta
import os
import re
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base as RealBase
from app.models.paper import Trade, Order, Position
from app.models.alert import Alert
from app.models.decision import Attempt, BotDecision
from app.models.scenario import Scenario
from app.models.user import UserProfile

from app.chatbot.config import cfg
from app.chatbot.models import Base as ChatbotBase, ChatUserProfile, ChatMessage
from app.chatbot.adapters import (
    build_trade_facts,
    get_last_trade_context,
    get_trade_history_window,
    get_scenario_decisions,
    get_rule_adherence,
    validate_schema_health,
    SCHEMA_MAPPING
)
from app.chatbot.profile import (
    fingerprint,
    build_profile,
    ensure_fresh_profile,
    get_profile_summary
)
from app.chatbot.guards import (
    scan_coach_reply_violations,
    sanitize_coach_reply,
    reply_has_tip_language,
    numbers_ok,
    clean_user_text
)
from app.chatbot.brain import route, detect_my_data_focus, answer


@pytest.fixture
def throwaway_db(tmp_path):
    """Creates a temporary SQLite database with isolated test schema."""
    db_file = tmp_path / "test_throwaway.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})

    # Create real schema tables in isolated SQLite instance
    RealBase.metadata.create_all(engine)
    ChatbotBase.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)

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
         patch("app.chatbot.models.get_db_session", side_effect=lambda: Session()):
        yield Session, engine


# ===========================================================================
# 1. Fingerprint Changes and Stays Same Test
# ===========================================================================
def test_fingerprint_changes_and_stays_same(throwaway_db):
    Session, _ = throwaway_db

    # Initial fingerprint with zero data
    fp1 = fingerprint(user_id=101)
    assert isinstance(fp1, str)
    assert len(fp1) == 64

    # Calling again without data changes must return exact same fingerprint
    fp1_again = fingerprint(user_id=101)
    assert fp1 == fp1_again

    # Add a trade for user 101
    with Session() as s:
        t = Trade(order_id=1, user_id=101, symbol="INFY", side="BUY", quantity=10, price=100.0, net_realized_pnl=0.0)
        s.add(t)
        s.commit()

    fp2 = fingerprint(user_id=101)
    assert fp2 != fp1  # Changed!

    # Same data -> fingerprint stays same
    assert fingerprint(user_id=101) == fp2


# ===========================================================================
# 2. Profile Build Tests: Zero Data, Only Wins, Only Losses, Hard Test Values
# ===========================================================================
def test_profile_build_zero_data(throwaway_db):
    prof = build_profile(user_id=999)
    assert prof["coverage"]["trades_count"] == 0
    assert prof["coverage"]["sample_size_flag"] == "early sign"
    assert prof["performance"]["all_time"]["trades_count"] == 0
    assert prof["performance"]["all_time"]["win_rate_pct"] == 0.0
    assert prof["performance"]["all_time"]["net"] == 0.0


def test_profile_build_only_wins():
    trades = [
        {"net_realized_pnl": 500.0},
        {"net_realized_pnl": 500.0},
        {"net_realized_pnl": 500.0}
    ]
    facts = build_trade_facts(trades)
    assert facts["trades_count"] == 3
    assert facts["win_rate_pct"] == 100.0
    assert facts["net"] == 1500.0
    assert facts["avg_win"] == 500.0
    assert facts["avg_loss"] == 0.0
    assert facts["expectancy"] == 500.0


def test_profile_build_only_losses():
    trades = [
        {"net_realized_pnl": -400.0},
        {"net_realized_pnl": -400.0},
        {"net_realized_pnl": -400.0}
    ]
    facts = build_trade_facts(trades)
    assert facts["trades_count"] == 3
    assert facts["win_rate_pct"] == 0.0
    assert facts["net"] == -1200.0
    assert facts["avg_win"] == 0.0
    assert facts["avg_loss"] == 400.0
    assert facts["expectancy"] == -400.0


def test_hard_test_values_6_wins_300_and_4_losses_900():
    """Hard requirement test:
    6 wins of ₹300 and 4 losses of ₹900 must give:
    win rate 60%, net −1800, expectancy −180, break-even 75%.
    """
    trades = [{"net_realized_pnl": 300.0} for _ in range(6)] + [
        {"net_realized_pnl": -900.0} for _ in range(4)
    ]
    facts = build_trade_facts(trades)
    assert facts["trades_count"] == 10
    assert facts["win_rate_pct"] == 60.0
    assert facts["net"] == -1800.0
    assert facts["expectancy"] == -180.0
    assert facts["breakeven_win_rate_pct"] == 75.0


# ===========================================================================
# 3. Reason Versus Outcome Aggregation Test
# ===========================================================================
def test_reason_versus_outcome_aggregation(throwaway_db):
    Session, _ = throwaway_db
    user_id = 301

    with Session() as s:
        # Scenario 1 (current=100, outcome_5m=110 -> diff=+10)
        s.add(Scenario(id=1, symbol="RELIANCE", event_type="drop", drop_pct=2.5, entry_price=100.0, current_price=100.0, outcome_5m=110.0, candles=[]))
        # 2 attempts with BUY_PLANNED (buy 10 -> outcome=100)
        s.add(Attempt(user_id=user_id, scenario_id=1, attempt_no=1, action="buy", size=10, reason="Plan", reason_code="BUY_PLANNED", decision_seconds=10.0))
        s.add(Attempt(user_id=user_id, scenario_id=1, attempt_no=2, action="buy", size=10, reason="Plan", reason_code="BUY_PLANNED", decision_seconds=12.0))
        # 1 attempt with FOMO (sell 5 -> outcome=-50)
        s.add(Attempt(user_id=user_id, scenario_id=1, attempt_no=1, action="sell", size=5, reason="Panic", reason_code="FOMO_PANIC", decision_seconds=8.0))
        s.commit()

    prof = build_profile(user_id=user_id)
    by_reason = prof["scenario_behavior"]["by_reason"]

    assert "buy_planned" in by_reason
    assert by_reason["buy_planned"]["count"] == 2
    assert by_reason["buy_planned"]["avg_outcome"] == 100.0

    assert "fomo_panic" in by_reason
    assert by_reason["fomo_panic"]["count"] == 1
    assert by_reason["fomo_panic"]["avg_outcome"] == -50.0


# ===========================================================================
# 4. Per-User Isolation Test
# ===========================================================================
def test_per_user_isolation(throwaway_db):
    Session, _ = throwaway_db
    user_a = 401
    user_b = 402

    with Session() as s:
        # User A has 5 winning trades of 200
        for i in range(5):
            s.add(Trade(order_id=i + 1, user_id=user_a, symbol="INFY", side="SELL", quantity=10, price=120.0, net_realized_pnl=200.0))
        # User B has 2 losing trades of -500
        for j in range(2):
            s.add(Trade(order_id=j + 10, user_id=user_b, symbol="TCS", side="SELL", quantity=5, price=80.0, net_realized_pnl=-500.0))
        s.commit()

    prof_a = build_profile(user_id=user_a)
    prof_b = build_profile(user_id=user_b)

    assert prof_a["coverage"]["closed_trades_count"] == 5
    assert prof_a["performance"]["all_time"]["net"] == 1000.0
    assert prof_a["performance"]["all_time"]["win_rate_pct"] == 100.0

    assert prof_b["coverage"]["closed_trades_count"] == 2
    assert prof_b["performance"]["all_time"]["net"] == -1000.0
    assert prof_b["performance"]["all_time"]["win_rate_pct"] == 0.0


# ===========================================================================
# 5. Adapters Never Raise With Missing Table or Column Test
# ===========================================================================
def test_adapters_never_raise_missing_table(throwaway_db):
    Session, engine = throwaway_db

    # Drop paper_trades table to simulate schema absence
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE paper_trades"))
        conn.commit()

    # Adapters must return ToolResult(ok=False, ...) and NEVER raise
    res_last = get_last_trade_context(user_id=1)
    assert not res_last.ok or res_last.data is None

    res_hist = get_trade_history_window(user_id=1, n=5)
    assert not res_hist.ok or res_hist.data == []


# ===========================================================================
# 6. Lock Timeout Returns Stale Profile Test
# ===========================================================================
def test_timeout_returns_stale_profile(throwaway_db):
    Session, _ = throwaway_db
    user_id = 601

    # First save an existing profile in chat_user_profile
    with Session() as s:
        s.add(ChatUserProfile(
            user_id=user_id,
            profile={"coverage": {"closed_trades_count": 5}, "status": "stale_version"},
            previous_profile=None,
            fingerprint="old_fp",
            updated_at=datetime.now(timezone.utc)
        ))
        s.commit()

    # Mock acquire timeout returning False
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = False
    with patch("app.chatbot.profile._get_user_lock", return_value=mock_lock):
        prof = ensure_fresh_profile(user_id)
        assert prof.get("status") == "stale_version" or prof.get("coverage", {}).get("closed_trades_count") == 5


# ===========================================================================
# 7. Route Detection Tests (English & Hinglish + Existing Routes)
# ===========================================================================
def test_route_detection_english_and_hinglish():
    # Last trade
    assert route("Explain my last trade") == "MY_DATA"
    assert detect_my_data_focus("Explain my last trade") == "LAST_TRADE"
    assert route("Why did I lose?") == "MY_DATA"
    assert detect_my_data_focus("Why did I lose?") == "LAST_TRADE"
    assert route("meri aakhri trade explain karo") == "MY_DATA"
    assert detect_my_data_focus("meri aakhri trade explain karo") == "LAST_TRADE"
    assert route("kyun loss hua") == "MY_DATA"
    assert detect_my_data_focus("kyun loss hua") == "LAST_TRADE"

    # Scenario
    assert route("My scenario decisions") == "MY_DATA"
    assert detect_my_data_focus("My scenario decisions") == "SCENARIO"
    assert route("why did I buy in that simulation") == "MY_DATA"
    assert detect_my_data_focus("why did I buy in that simulation") == "SCENARIO"

    # Profile
    assert route("My habits") == "MY_DATA"
    assert detect_my_data_focus("My habits") == "PROFILE"
    assert route("what do I keep doing wrong") == "MY_DATA"
    assert detect_my_data_focus("what do I keep doing wrong") == "PROFILE"
    assert route("meri aadatein kya hai") == "MY_DATA"
    assert detect_my_data_focus("meri aadatein kya hai") == "PROFILE"

    # Existing routes unchanged
    assert route("Which stock should I buy?") == "TIP_REFUSAL"
    assert route("kya nifty kal badhega?") == "TIP_REFUSAL"
    assert route("What is a stop-loss order?") == "CONCEPT"
    assert route("I want to end my life") == "DISTRESS"


# ===========================================================================
# 8. Static Test: Chatbot Code Writes ONLY to Chatbot-Owned Tables
# ===========================================================================
def test_chatbot_writes_only_to_chatbot_owned_tables():
    """Verifies that chatbot package contains no INSERT/UPDATE/DELETE targeting external tables."""
    chatbot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    allowed_tables = {"chat_kb_chunks", "chat_messages", "chat_notes", "chat_user_profile"}

    disallowed_tables = {
        "paper_trades", "paper_orders", "paper_positions", "paper_accounts",
        "alerts", "users", "user_profiles", "attempts", "scenarios", "bot_decisions"
    }

    write_patterns = [
        re.compile(r"insert\s+into\s+([a-zA-Z0-9_]+)", re.IGNORECASE),
        re.compile(r"update\s+([a-zA-Z0-9_]+)\s+set", re.IGNORECASE),
        re.compile(r"delete\s+from\s+([a-zA-Z0-9_]+)", re.IGNORECASE)
    ]

    for root, _, files in os.walk(chatbot_dir):
        if "tests" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    for pat in write_patterns:
                        matches = pat.findall(content)
                        for m in matches:
                            target_tbl = m.lower()
                            assert target_tbl in allowed_tables, f"Forbidden write to {target_tbl} in {file}"
                            assert target_tbl not in disallowed_tables, f"Forbidden write to {target_tbl} in {file}"


# ===========================================================================
# 9. Reply Guard Tests: Hindsight Advice, Predictions, Authority Claims
# ===========================================================================
def test_reply_guards_violations_and_sanitization():
    # Hindsight advice
    hindsight = "You should have bought at 1400 instead of holding."
    violations = scan_coach_reply_violations(hindsight)
    assert "hindsight" in violations
    assert reply_has_tip_language(hindsight)
    sanitized = sanitize_coach_reply(hindsight)
    assert "should have bought" not in sanitized.lower()

    # Prediction
    prediction = "INFY price will rise to 1600 next week."
    violations = scan_coach_reply_violations(prediction)
    assert "prediction" in violations
    assert reply_has_tip_language(prediction)
    sanitized = sanitize_coach_reply(prediction)
    assert "will rise to" not in sanitized.lower()

    # Certification / Authority claim
    authority = "As a certified financial advisor, I recommend following this rule."
    violations = scan_coach_reply_violations(authority)
    assert "authority" in violations
    sanitized = sanitize_coach_reply(authority)
    assert "certified financial advisor" not in sanitized.lower()


# ===========================================================================
# 10. Health Status Reports Connected Sources
# ===========================================================================
def test_schema_health_status(throwaway_db):
    health = validate_schema_health()
    assert "trades" in health
    assert "scenario_decisions" in health
    assert "rules" in health
    assert "mistakes" in health
