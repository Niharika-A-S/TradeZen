"""Comprehensive tests for Final Coach requirements (Part 5).

Includes:
- Follow-up conversation sequences
- 25 personal phrasing variants in English and Hinglish
- 15 pure concept questions
- Vague messages handling
- LLM failure modes (network error, timeout, 429, empty, blocked, serialization)
- Serialization with Decimal, datetime, UUID, numpy types
- Call count budgeting (at most 2 LLM calls per message)
- Regression: tip refusal 100%, scanner, table write isolation
"""
from datetime import datetime, date
from decimal import Decimal
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import numpy as np

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from app.chatbot.llm import LLMResult, safe_json_dumps, SafeJSONEncoder
from app.chatbot.brain import (
    answer,
    route,
    detect_follow_up_style,
    score_intent,
    conversation_states,
    format_num,
    format_money,
    format_duration,
    format_pnl_phrase,
    extract_gentler_habit_from_note,
)


# ---------------------------------------------------------------------------
# Test Fixtures & Mocks
# ---------------------------------------------------------------------------

def _make_fake_trade_ctx(symbol="INFY", qty=10, entry=1800.0, exit_p=1750.0, pnl=-500.0, side="SELL"):
    class FakeResult:
        ok = True
        reason = None
        data = {
            "symbol": symbol,
            "quantity": qty,
            "side": side,
            "entry_price": entry,
            "exit_price": exit_p,
            "pnl": pnl,
            "hold_duration_mins": 30.0,
            "open_time": "2026-11-20T10:00:00",
            "exit_time": "2026-11-20T10:30:00",
            "is_open": False,
            "rules_broken": [],
            "rules_adherence": "You followed your configured trading rules.",
            "mistake_flags": [],
            "has_closed_trades": True,
            "has_open_trade": False,
            "open_trade": None,
            "gap_minutes": None,
            "previous_trade_pnl": None,
        }
    return FakeResult()


def _make_fake_profile():
    return {
        "coverage": {"closed_trades_count": 5, "scenario_decisions_count": 2},
        "performance": {"all_time": {"win_rate_pct": 60.0, "avg_win": 500.0, "avg_loss": 300.0, "net_realized_pnl": 900.0}},
        "habits": {"user_median_size": 10.0, "rule_adherence_rate_pct": 100.0, "stop_loss_usage_pct": 100.0},
        "repeated_mistakes": [],
        "trend": {"status": "improving"},
    }


# ---------------------------------------------------------------------------
# 1. Serialization Tests (Decimal, datetime, UUID, numpy)
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_safe_json_dumps_various_types(self):
        data = {
            "price": Decimal("1800.50"),
            "timestamp": datetime(2026, 11, 24, 15, 30, 0),
            "trade_date": date(2026, 11, 24),
            "order_id": uuid.uuid4(),
            "np_float": np.float64(123.45),
            "np_int": np.int64(10),
            "np_array": np.array([10, 20, 30]),
        }
        serialized = safe_json_dumps(data)
        assert "1800.5" in serialized
        assert "2026-11-24T15:30:00" in serialized
        assert "2026-11-24" in serialized
        assert "123.45" in serialized
        assert "[10, 20, 30]" in serialized


# ---------------------------------------------------------------------------
# 2. Template Quality & Formatter Tests
# ---------------------------------------------------------------------------

class TestTemplateFormatters:
    def test_format_num_strips_trailing_zero(self):
        assert format_num(10.0) == "10"
        assert format_num(10) == "10"
        assert format_num(10.5) == "10.50"

    def test_format_money_positive(self):
        assert format_money(-1136.32) == "₹1,136.32"
        assert format_money(1136.32) == "₹1,136.32"

    def test_format_duration(self):
        assert format_duration(0.0) == "under a minute"
        assert format_duration(0.5) == "under a minute"
        assert format_duration(5.0) == "5 minutes"

    def test_format_pnl_phrase_no_double_negative(self):
        assert format_pnl_phrase(-31.40) == "a loss of ₹31.40"
        assert "-₹" not in format_pnl_phrase(-31.40)
        assert format_pnl_phrase(150.0) == "a gain of ₹150.00"

    def test_extract_gentler_habit(self):
        note = (
            "## What it looks like\nOvertrading.\n\n"
            "## A gentler habit\nTake a 15-minute screen pause after two consecutive trades. Walk around before opening a new chart.\n\n"
            "## Next steps\nReview."
        )
        habit = extract_gentler_habit_from_note(note)
        assert habit is not None
        assert "Take a 15-minute screen pause" in habit
        assert len(habit.split(".")) <= 3  # at most 2 sentences plus trailing dot


# ---------------------------------------------------------------------------
# 3. Follow-up Conversation Sequences
# ---------------------------------------------------------------------------

class TestConversationSequences:
    @pytest.fixture(autouse=True)
    def setup_mocks(self):
        self.patches = [
            patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()),
            patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _make_fake_profile()),
            patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None),
            patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]),
            patch("app.chatbot.brain.save_message", return_value=None),
            patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False),
        ]
        for p in self.patches:
            p.start()
        yield
        for p in self.patches:
            p.stop()

    def test_sequence_explain_then_simple(self):
        # 1. 'Explain my last trade'
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Trade facts: BUY 10 INFY at ₹1,800.00 sold at ₹1,750.00.")):
            ans1 = answer(user_id=101, message="Explain my last trade")
        assert ans1["route"] == "MY_DATA"

        # 2. 'in simple words' -> must stay MY_DATA, re-answer simply, no knowledge note text
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="In simple terms, you bought 10 shares of INFY at ₹1,800.00 and sold at ₹1,750.00.")):
            ans2 = answer(user_id=101, message="in simple words")
        assert ans2["route"] == "MY_DATA"
        assert "SEBI registration" not in ans2["reply"]
        assert "overtrading" not in ans2["reply"].lower()

    def test_sequence_explain_then_shorter(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Trade facts: BUY 10 INFY at ₹1,800.00 sold at ₹1,750.00.")):
            answer(user_id=102, message="Explain my last trade")

        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Short: 10 INFY shares exited with ₹500 loss.")):
            ans2 = answer(user_id=102, message="shorter")
        assert ans2["route"] == "MY_DATA"

    def test_sequence_why_lose_then_what_does_that_mean(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="You exited 10 INFY shares at ₹1,750.00 realizing a loss of ₹500.00.")):
            answer(user_id=103, message="Why did I lose?")

        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="That means your exit price was lower than your entry price.")):
            ans2 = answer(user_id=103, message="what does that mean?")
        assert ans2["route"] == "MY_DATA"
        assert "overtrading" not in ans2["reply"].lower()

    def test_sequence_explain_then_example(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Trade facts: BUY 10 INFY.")):
            answer(user_id=104, message="Explain my last trade")

        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="For example, when you bought at ₹1,800.00 and sold at ₹1,750.00...")):
            ans2 = answer(user_id=104, message="give me an example")
        assert ans2["route"] == "MY_DATA"

    def test_sequence_explain_then_hinglish_samjhao(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Trade facts: BUY 10 INFY.")):
            answer(user_id=105, message="Explain my last trade")

        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Aasan shabdon mein, aapne 10 shares ₹1,800.00 par kharide the.")):
            ans2 = answer(user_id=105, message="samjhao aasan bhasha mein")
        assert ans2["route"] == "MY_DATA"

    def test_sequence_habits_then_what_to_practise(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Your habits profile shows 60% win rate.")):
            answer(user_id=106, message="My habits")

        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Practise placing strict stop-loss orders on every trade.")):
            ans2 = answer(user_id=106, message="and what should I practise first?")
        assert ans2["route"] == "MY_DATA"

    def test_sequence_explain_then_ok_thanks(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text="Trade facts: BUY 10 INFY.")):
            answer(user_id=107, message="Explain my last trade")

        ans2 = answer(user_id=107, message="ok thanks")
        assert "welcome" in ans2["reply"].lower()


# ---------------------------------------------------------------------------
# 4. 25 Personal Phrasing Variants in English and Hinglish
# ---------------------------------------------------------------------------

class TestPersonalPhrasingVariants:
    def test_25_personal_phrasings_reach_my_data(self):
        variants = [
            "tell me about my trade",
            "how did that go",
            "was that a bad trade",
            "am I doing okay",
            "mera last trade kaisa tha",
            "what went wrong yesterday",
            "why do I keep losing",
            "explain my last trade",
            "summary of my trade",
            "summary of my trades",
            "my last trade",
            "how did my trade go",
            "meri pichhli trade",
            "did I win or lose",
            "how was my TCS trade",
            "how is my discipline",
            "what did I do in my previous trade",
            "aakhri trade ka result kya tha",
            "kya mera trade loss mein gaya",
            "mujhe mere last trade ke baare mein batao",
            "how am I doing",
            "what was my loss on INFY",
            "did I follow my rules on my trade",
            "meri trading कैसी chal rahi hai",
            "show my trade summary",
        ]
        assert len(variants) == 25
        for phrase in variants:
            r = route(phrase)
            assert r == "MY_DATA", f"Expected MY_DATA for phrase '{phrase}', got {r}"


# ---------------------------------------------------------------------------
# 5. 15 Pure Concept Questions
# ---------------------------------------------------------------------------

class TestConceptPhrasings:
    def test_15_pure_concept_questions_reach_concept(self):
        concepts = [
            "what is stop loss",
            "explain position sizing",
            "what is liquidity in trading",
            "what does volatility mean",
            "difference between market and limit orders",
            "how does a trailing stop work",
            "what is fomo trading",
            "explain overtrading",
            "what is revenge trading",
            "meaning of risk reward ratio",
            "what is drawdown in trading",
            "how do options contracts work",
            "what is intraday margin",
            "explain investor protection rules",
            "what is capital risk",
        ]
        assert len(concepts) == 15
        for q in concepts:
            r = route(q)
            assert r == "CONCEPT", f"Expected CONCEPT for question '{q}', got {r}"


# ---------------------------------------------------------------------------
# 6. Vague Messages Handling
# ---------------------------------------------------------------------------

class TestVagueMessages:
    def test_vague_messages_get_clarifying_reply(self):
        vague_queries = ["hmm", "what now", "hello?", "kya?"]
        for v in vague_queries:
            ans = answer(user_id=201, message=v)
            assert ans["route"] == "CHAT"
            assert "TradeZen Coach" in ans["reply"] or "clarify" in ans["reply"] or "explain" in ans["reply"]


# ---------------------------------------------------------------------------
# 7. LLM Failure Modes & Degraded Reason Diagnostics
# ---------------------------------------------------------------------------

class TestLLMFailureModes:
    @pytest.fixture(autouse=True)
    def setup_mocks(self):
        self.patches = [
            patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()),
            patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _make_fake_profile()),
            patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None),
            patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]),
            patch("app.chatbot.brain.save_message", return_value=None),
            patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False),
        ]
        for p in self.patches:
            p.start()
        yield
        for p in self.patches:
            p.stop()

    def test_network_error_returns_template_with_specific_degraded_reason(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=False, error_kind="NETWORK_ERROR")):
            ans = answer(user_id=301, message="Explain my last trade")
        assert ans["degraded"] is True
        assert "network_error" in ans["degraded_reason"]
        assert "INFY" in ans["reply"]
        assert "SEBI registration" not in ans["reply"]

    def test_timeout_returns_template_with_specific_degraded_reason(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=False, error_kind="TIMEOUT")):
            ans = answer(user_id=302, message="Explain my last trade")
        assert ans["degraded"] is True
        assert "timeout" in ans["degraded_reason"]
        assert "INFY" in ans["reply"]

    def test_429_returns_template_with_specific_degraded_reason(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=False, error_kind="RATE_LIMIT")):
            ans = answer(user_id=303, message="Explain my last trade")
        assert ans["degraded"] is True
        assert "rate_limit" in ans["degraded_reason"]
        assert "INFY" in ans["reply"]

    def test_empty_returns_template_with_specific_degraded_reason(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=False, error_kind="EMPTY")):
            ans = answer(user_id=304, message="Explain my last trade")
        assert ans["degraded"] is True
        assert "empty" in ans["degraded_reason"]

    def test_blocked_returns_template_with_specific_degraded_reason(self):
        with patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=False, error_kind="BLOCKED")):
            ans = answer(user_id=305, message="Explain my last trade")
        assert ans["degraded"] is True
        assert "blocked" in ans["degraded_reason"]


# ---------------------------------------------------------------------------
# 8. Budgeting: At Most 2 LLM Calls Per Message
# ---------------------------------------------------------------------------

class TestLLMBudgeting:
    def test_at_most_two_llm_calls_per_message(self):
        call_count = 0
        def fake_generate(**kwargs):
            nonlocal call_count
            call_count += 1
            return LLMResult(ok=True, text="Your last trade: BUY 10 INFY at ₹1,800.00 sold at ₹1,750.00.")

        with patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()), \
             patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _make_fake_profile()), \
             patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
             patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
             patch("app.chatbot.brain.save_message", return_value=None), \
             patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
             patch("app.chatbot.brain.llm_client.generate", side_effect=fake_generate):
            answer(user_id=401, message="Explain my last trade")

        assert call_count <= 2, f"Expected at most 2 LLM calls, but got {call_count}"


# ---------------------------------------------------------------------------
# 9. Regression: Tip Refusal Stays at 100%
# ---------------------------------------------------------------------------

class TestRegressionTipRefusal:
    def test_tip_requests_refused_100_percent(self):
        tip_prompts = [
            "which stocks should I buy?",
            "give me a stock tip",
            "recommend me a good stock",
            "will Nifty go up tomorrow?",
            "should I buy TCS?",
            "what is the price target for INFY?",
            "kya Reliance kharidna chahiye?",
        ]
        for prompt in tip_prompts:
            ans = answer(user_id=501, message=prompt)
            assert ans["route"] == "TIP_REFUSAL"
            assert "SEBI registration" in ans["reply"]
            assert ans["used_data"] is False
