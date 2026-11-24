"""Bug Round 3 tests — scanner, routing, and llm_error diagnostics.

All tests use throwaway in-memory SQLite databases and fake LLM hooks.
No real PostgreSQL or Gemini API is used.
"""
import re
import sqlite3
import tempfile
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Ensure the PaperTrading package is importable
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Guard / scanner tests (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestOutputScanner:
    """Tests for scan_and_sanitize_gemini_reply."""

    def _import(self):
        from app.chatbot.guards import scan_and_sanitize_gemini_reply
        return scan_and_sanitize_gemini_reply

    def test_template_reply_never_modified(self):
        """Template replies (is_template=True) are returned unchanged."""
        fn = self._import()
        template = (
            "Your latest trade (BUY 10 shares at ₹1800.00) is open. "
            "Your rule: profit target 2%. "
            "You followed your stop-loss rule. "
            "One small habit: add a 10-minute pause."
        )
        sanitized, violations = fn(template, allowed_facts_text="", is_template=True)
        assert sanitized == template
        assert violations == []

    def test_advice_sentence_replaced_rest_kept(self):
        """A single advice sentence is replaced; fact sentences are kept."""
        fn = self._import()
        reply = (
            "Your INFY trade was a BUY of 10 shares at ₹1800.00. "
            "You should buy more tomorrow. "
            "Your stop loss was placed at ₹1750.00."
        )
        sanitized, violations = fn(reply, allowed_facts_text="₹1800 ₹1750 10 BUY INFY", is_template=False)
        # Violations detected
        assert len(violations) > 0
        # Advice sentence replaced
        assert "buy more tomorrow" not in sanitized.lower()
        # Fact sentences kept
        assert "₹1800" in sanitized or "1800" in sanitized
        assert "₹1750" in sanitized or "1750" in sanitized

    def test_no_advice_reply_unchanged(self):
        """A clean Gemini reply with no advice passes through unchanged."""
        fn = self._import()
        reply = (
            "Your last trade: BUY 40 shares of INFY at ₹1800.00. "
            "The data suggests you followed your stop-loss rule. "
            "One small habit to try: review your plan before entry."
        )
        sanitized, violations = fn(reply, allowed_facts_text="₹1800 40 BUY INFY", is_template=False)
        assert violations == []
        assert sanitized == reply

    def test_target_price_in_user_rule_not_flagged(self):
        """'target price' in user's own rule data is in allowed_facts so not flagged."""
        fn = self._import()
        # Gemini says "your profit target was 2%" — these are user rule values
        reply = "Your trade followed your profit target rule. The stop loss was at ₹1750."
        allowed = "profit target 2% stop loss ₹1750 BUY 40 INFY ₹1800"
        sanitized, violations = fn(reply, allowed_facts_text=allowed, is_template=False)
        # "profit target" does not match any _ADV_RECOMMENDATION or _ADV_PREDICTION pattern
        assert violations == []
        assert sanitized == reply

    def test_stock_price_prediction_flagged(self):
        """'will rise to' is a prediction and must be replaced."""
        fn = self._import()
        reply = "The stock will rise to ₹1900 based on momentum. Your entry was ₹1800."
        sanitized, violations = fn(reply, allowed_facts_text="₹1800 ₹1900 BUY INFY", is_template=False)
        assert "prediction" in violations
        assert "will rise to" not in sanitized.lower()

    def test_recommendation_you_should_buy_flagged(self):
        """'you should buy' is a direct recommendation."""
        fn = self._import()
        reply = "Your entry at ₹1800 was fine. You should buy more to average down."
        sanitized, violations = fn(reply, allowed_facts_text="₹1800 BUY INFY", is_template=False)
        assert "recommendation" in violations
        assert "buy more" not in sanitized.lower()

    def test_authority_claim_replaced_with_neutral(self):
        """Authority claims are replaced with the neutral authority sentence."""
        fn = self._import()
        reply = "As a certified financial advisor, I suggest you hold. Your trade was a BUY."
        sanitized, violations = fn(reply, allowed_facts_text="BUY hold", is_template=False)
        assert "authority" in violations
        assert "certified financial advisor" not in sanitized.lower()
        assert "TradeZen Coach" in sanitized

    def test_empty_reply_returned_unchanged(self):
        fn = self._import()
        sanitized, violations = fn("", allowed_facts_text="", is_template=False)
        assert sanitized == ""
        assert violations == []


class TestInputGate:
    """Tests for is_tip_request — must NOT fire on personal trade queries."""

    def _import(self):
        from app.chatbot.guards import is_tip_request
        return is_tip_request

    def test_personal_queries_do_not_fire(self):
        fn = self._import()
        safe = [
            "Explain my last trade",
            "summary of my trade",
            "summary of my trades",
            "my last trade",
            "how did my trade go",
            "meri pichhli trade",
            "why did I lose?",
            "summary of my trading",
        ]
        for q in safe:
            assert fn(q) is False, f"is_tip_request({q!r}) should be False"

    def test_actual_tip_requests_fire(self):
        fn = self._import()
        tips = [
            "which stocks should I buy?",
            "give me a stock tip",
            "should I buy INFY?",
        ]
        for q in tips:
            assert fn(q) is True, f"is_tip_request({q!r}) should be True"


class TestRouteAndFocus:
    """Tests that routing and focus detection work for the bug round 3 phrases."""

    def test_summary_of_my_trade_routes_to_last_trade(self):
        from app.chatbot.brain import route, detect_my_data_focus
        assert route("summary of my trade") == "MY_DATA"
        assert detect_my_data_focus("summary of my trade") == "LAST_TRADE"

    def test_summary_of_my_trades_routes_to_last_trade(self):
        from app.chatbot.brain import route, detect_my_data_focus
        assert route("summary of my trades") == "MY_DATA"
        assert detect_my_data_focus("summary of my trades") == "LAST_TRADE"

    def test_explain_my_last_trade_routes_to_last_trade(self):
        from app.chatbot.brain import route, detect_my_data_focus
        assert route("Explain my last trade") == "MY_DATA"
        assert detect_my_data_focus("Explain my last trade") == "LAST_TRADE"

    def test_how_did_my_trade_go_routes_to_last_trade(self):
        from app.chatbot.brain import route, detect_my_data_focus
        assert route("how did my trade go") == "MY_DATA"
        assert detect_my_data_focus("how did my trade go") == "LAST_TRADE"


# ---------------------------------------------------------------------------
# answer() integration tests with fake LLM and in-memory SQLite
# ---------------------------------------------------------------------------

def _build_in_memory_db_url():
    """Return a unique SQLite in-memory URL for each test."""
    tmp = tempfile.mktemp(suffix=".db")
    return f"sqlite:///{tmp}", tmp


@pytest.fixture()
def fake_db_url():
    url, path = _build_in_memory_db_url()
    yield url
    try:
        os.unlink(path)
    except Exception:
        pass


def _make_fake_trade_ctx(symbol="INFY", qty=10, entry=1800.0, exit_price=1750.0, pnl=-500.0, side="SELL"):
    """Returns a fake AdapterResult-like object for get_last_trade_context."""
    class FakeResult:
        ok = True
        reason = None
        data = {
            "symbol": symbol,
            "quantity": qty,
            "side": side,
            "entry_price": entry,
            "exit_price": exit_price,
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
        "coverage": {"closed_trades_count": 2, "scenario_decisions_count": 0},
        "performance": {"all_time": {"win_rate_pct": 50.0, "avg_win": 400.0, "avg_loss": 500.0}},
        "habits": {"user_median_size": 10.0, "rule_adherence_rate_pct": 100.0, "stop_loss_usage_pct": 100.0},
        "repeated_mistakes": [],
        "trend": {"status": "insufficient_data"},
    }


class TestAnswerWithFakeLLM:
    """Tests for answer() with controlled fake LLM — no real API or PostgreSQL."""

    def _patch_all(self, llm_response_text=None, llm_ok=True, error_kind=None):
        """Return a dict of patches to apply."""
        from app.chatbot.llm import LLMResult

        def fake_gen(**kwargs):
            if not llm_ok:
                return LLMResult(ok=False, error_kind=error_kind or "RATE_LIMIT")
            return LLMResult(ok=True, text=llm_response_text or "")

        patches = {
            "app.chatbot.brain.get_last_trade_context": lambda *a, **kw: _make_fake_trade_ctx(),
            "app.chatbot.brain.ensure_fresh_profile": lambda *a, **kw: _make_fake_profile(),
            "app.chatbot.brain.rag_engine.get_chunk_by_file_id": lambda *a, **kw: None,
            "app.chatbot.brain.rag_engine.retrieve": lambda *a, **kw: [],
            "app.chatbot.brain.save_message": lambda *a, **kw: None,
            "app.chatbot.brain.should_append_coach_disclaimer": lambda *a, **kw: False,
            "app.chatbot.brain.llm_client.generate": fake_gen,
        }
        return patches

    def _apply_patches(self, patch_dict):
        """Context manager that applies all patches."""
        import contextlib
        @contextlib.contextmanager
        def ctx():
            with contextlib.ExitStack() as stack:
                for target, replacement in patch_dict.items():
                    stack.enter_context(patch(target, side_effect=replacement if callable(replacement) else None, new=replacement if not callable(replacement) else MagicMock(side_effect=replacement)))
            yield
        return ctx()

    def test_clean_llm_reply_returned_unchanged(self):
        """When LLM returns clean text with exact figures, reply contains those figures."""
        from app.chatbot.brain import answer
        clean_reply = (
            "Your last trade: BUY 10 shares of INFY at ₹1,800.00 and sold at ₹1,750.00 "
            "after 30 minutes, a loss of -₹500.00. "
            "The data suggests you followed your stop-loss rule. "
            "One habit to try: review your entry criteria."
        )
        patches = self._patch_all(llm_response_text=clean_reply)
        with patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()), \
             patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _make_fake_profile()), \
             patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
             patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
             patch("app.chatbot.brain.save_message", return_value=None), \
             patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
             patch("app.chatbot.brain.llm_client.generate", return_value=__import__("app.chatbot.llm", fromlist=["LLMResult"]).LLMResult(ok=True, text=clean_reply)):
            result = answer(user_id=1, message="Explain my last trade")
        assert result["route"] == "MY_DATA"
        assert result["used_data"] is True
        assert result["degraded"] is False
        # Must contain exact trade figures
        assert "1,800" in result["reply"] or "1800" in result["reply"]
        assert "1,750" in result["reply"] or "1750" in result["reply"]
        # Must NOT be refusal text
        assert "SEBI registration" not in result["reply"]
        assert "cannot provide" not in result["reply"]

    def test_advice_sentence_replaced_facts_kept(self):
        """LLM reply with one advice sentence: that sentence replaced, fact sentences kept."""
        from app.chatbot.brain import answer
        from app.chatbot.llm import LLMResult
        reply_with_advice = (
            "Your last trade: BUY 10 shares of INFY at ₹1,800.00 sold at ₹1,750.00 after 30 minutes. "
            "You should buy more tomorrow to recover your loss. "
            "The data suggests you entered at a momentum high."
        )
        with patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()), \
             patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _make_fake_profile()), \
             patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
             patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
             patch("app.chatbot.brain.save_message", return_value=None), \
             patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
             patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text=reply_with_advice)):
            result = answer(user_id=1, message="Explain my last trade")
        # Must NOT be full refusal
        assert "SEBI registration" not in result["reply"]
        # Advice sentence replaced
        assert "buy more tomorrow" not in result["reply"].lower()
        # Fact sentence kept
        assert "1,800" in result["reply"] or "1800" in result["reply"]

    def test_llm_failure_returns_template_with_error_detail(self):
        """When LLM fails, template reply is returned with llm_error:detail in degraded_reason."""
        from app.chatbot.brain import answer
        from app.chatbot.llm import LLMResult
        with patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()), \
             patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _make_fake_profile()), \
             patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
             patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
             patch("app.chatbot.brain.save_message", return_value=None), \
             patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
             patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=False, error_kind="RATE_LIMIT")):
            result = answer(user_id=1, message="Explain my last trade")
        assert result["degraded"] is True
        assert result["degraded_reason"] is not None
        assert "llm_error" in result["degraded_reason"]
        # Template reply must contain trade figures from facts
        assert "INFY" in result["reply"]
        assert "1,800" in result["reply"] or "1800" in result["reply"]
        # Must NOT be refusal
        assert "SEBI registration" not in result["reply"]

    def test_summary_of_my_trade_routes_to_last_trade_route(self):
        """'summary of my trade' must route to MY_DATA / LAST_TRADE and return trade figures."""
        from app.chatbot.brain import answer
        from app.chatbot.llm import LLMResult
        clean_reply = (
            "Your INFY trade: BUY 10 shares at ₹1,800.00 sold at ₹1,750.00 after 30 minutes. "
            "Loss of -₹500.00. The data suggests you followed your rules."
        )
        with patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()), \
             patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _make_fake_profile()), \
             patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
             patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
             patch("app.chatbot.brain.save_message", return_value=None), \
             patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
             patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text=clean_reply)):
            result = answer(user_id=1, message="summary of my trade")
        assert result["route"] == "MY_DATA"
        assert result["used_data"] is True
        assert "SEBI registration" not in result["reply"]
        assert "1,800" in result["reply"] or "1800" in result["reply"]

    def test_no_refusal_when_no_advice_in_gemini_reply(self):
        """Input gate does not fire; output scanner does not fire → no refusal at all."""
        from app.chatbot.brain import answer
        from app.chatbot.llm import LLMResult
        reply = (
            "Your last trade was BUY 10 INFY shares at ₹1,800.00. "
            "After 30 minutes you exited at ₹1,750.00 for a loss of -₹500.00. "
            "The data suggests you held within your usual duration."
        )
        with patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()), \
             patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _make_fake_profile()), \
             patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
             patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
             patch("app.chatbot.brain.save_message", return_value=None), \
             patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
             patch("app.chatbot.brain.llm_client.generate", return_value=LLMResult(ok=True, text=reply)):
            result = answer(user_id=1, message="Explain my last trade")
        assert "SEBI registration" not in result["reply"]
        assert "cannot provide" not in result["reply"]
        assert result["degraded"] is False


class TestCircuitBreaker:
    """Tests for circuit breaker half-open and self-recovery."""

    def test_circuit_breaker_self_recovers(self):
        """After recovery_time passes, circuit breaker resets to closed."""
        from app.chatbot.llm import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, recovery_time=1.0)
        cb.record_failure(current_time=0.0)
        cb.record_failure(current_time=0.0)
        # Should be open immediately
        assert cb.allow_request(current_time=0.5) is False
        # After recovery_time, should allow (half-open → closed)
        assert cb.allow_request(current_time=2.0) is True
        # Consecutive failures reset
        assert cb.consecutive_failures == 0

    def test_circuit_breaker_does_not_block_across_flows(self):
        """A single request's failures do not trip the global breaker for other users."""
        from app.chatbot.llm import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, recovery_time=60.0)
        # 2 failures (not at threshold)
        cb.record_failure()
        cb.record_failure()
        # Should still allow
        assert cb.allow_request() is True

    def test_llm_result_has_error_kind(self):
        """LLMResult carries error_kind for diagnostics."""
        from app.chatbot.llm import LLMResult
        r = LLMResult(ok=False, error_kind="RATE_LIMIT")
        assert r.error_kind == "RATE_LIMIT"
        assert r.ok is False
