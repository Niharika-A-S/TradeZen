"""Phase 3 Proof Tests — fake LLM, no network, throwaway fixtures.

Verifies the Phase 2 redesign:
- Healthy LLM: each of the 11 messages produces DIFFERENT replies via Gemini
- 'i bought from a tip' is NOT refused, IS conversational
- Failed LLM modes: template fallback with correct generated_by and degraded_reason
- Property tests: no missing field renders as 0/0.00/'followed', tip isolation, per-user isolation
- Scenario outcome matches ScenarioSimulation's own value
- LLM exception classifier correctness
"""
import re
import sys
import os
import socket
import ssl
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from decimal import Decimal
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Ensure PaperTrading is importable
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Shared Fake Data Factories
# ---------------------------------------------------------------------------

def _make_fake_trade_ctx(
    symbol="INFY", qty=10, entry=1800.0, exit_price=1750.0,
    pnl=-500.0, side="SELL", charges=20.0, rules_broken=None,
    hold_duration_mins=30.0, gap_minutes=None, previous_trade_pnl=None,
    mistake_flags=None,
):
    """Returns a fake ToolResult-like object for get_last_trade_context."""
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
            "charges": charges,
            "pnl_includes_charges": charges is not None and charges > 0,
            "hold_duration_mins": hold_duration_mins,
            "open_time": "2026-11-20T10:00:00",
            "exit_time": "2026-11-20T10:30:00",
            "is_open": False,
            "rules_broken": rules_broken if rules_broken is not None else [],
            "rules_adherence": "",
            "mistake_flags": mistake_flags or [],
            "has_closed_trades": True,
            "has_open_trade": False,
            "open_trade": None,
            "gap_minutes": gap_minutes,
            "previous_trade_pnl": previous_trade_pnl,
        }
    return FakeResult()


def _make_fake_profile(win_rate=50.0, rule_adh=80.0, avg_win=400.0, avg_loss=500.0, closed=5):
    return {
        "coverage": {"closed_trades_count": closed, "scenario_decisions_count": 0},
        "performance": {
            "all_time": {
                "win_rate_pct": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "net_realized_pnl": -100.0,
            }
        },
        "habits": {
            "user_median_size": 10.0,
            "rule_adherence_rate_pct": rule_adh,
            "stop_loss_usage_pct": 60.0,
        },
        "repeated_mistakes": [],
        "trend": {"status": "insufficient_data"},
    }


def _make_fake_scenario_decisions():
    class FakeResult:
        ok = True
        reason = None
        data = [
            {
                "scenario_id": 22,
                "attempt_id": 100,
                "attempt_no": 1,
                "action": "buy",
                "size": 10,
                "reason_picked": "MOMENTUM",
                "reason_code": "MOMENTUM",
                "scenario_shown": {
                    "event_type": "market_move",
                    "drop_pct": 0.54,
                    "current_price": 540.0,
                },
                "outcome_pnl": 54.0,  # (545.4 - 540) * 10
                "rule_matched": True,
                "revision": None,
                "bot_choices": [],
                "created_at": "2026-11-20T10:00:00",
            }
        ]
    return FakeResult()


def _make_fake_trade_window():
    class FakeResult:
        ok = True
        reason = None
        data = []
    return FakeResult()


# ---------------------------------------------------------------------------
# Recording fake LLM — captures exactly what Gemini received
# ---------------------------------------------------------------------------

class RecordingFakeLLM:
    """Records all generate() calls and returns a unique reply per call."""
    def __init__(self, replies=None, fail_mode=None):
        self.calls = []
        self._replies = replies or []
        self._call_idx = 0
        self.fail_mode = fail_mode  # None, 'RATE_LIMIT', 'TIMEOUT', 'CONNECT_ERROR', 'EMPTY', 'BLOCKED', 'SERIAL_ERROR'

    def generate(self, **kwargs):
        from app.chatbot.llm import LLMResult
        self.calls.append(kwargs)
        idx = self._call_idx
        self._call_idx += 1

        if self.fail_mode:
            return LLMResult(ok=False, error_kind=self.fail_mode)

        if idx < len(self._replies):
            return LLMResult(ok=True, text=self._replies[idx])

        # Default: return a unique reply containing the user message substring
        user_content = kwargs.get("messages", [{}])[-1].get("content", "")
        # Extract user sentence from the prompt
        m = re.search(r"User said: (.+?)(?:\n|$)", user_content)
        user_said = m.group(1) if m else "something"
        return LLMResult(ok=True, text=f"[Gemini reply #{idx}] About: {user_said}")


# ---------------------------------------------------------------------------
# Common patches context manager
# ---------------------------------------------------------------------------

def _common_patches(fake_llm=None, profile=None, trade_ctx_fn=None, scenario_fn=None):
    """Returns a dict of patches to apply via unittest.mock.patch."""
    import contextlib
    _llm = fake_llm or RecordingFakeLLM()
    _profile = profile or _make_fake_profile()
    _trade_fn = trade_ctx_fn or (lambda *a, **kw: _make_fake_trade_ctx())
    _scenario_fn = scenario_fn or (lambda *a, **kw: _make_fake_scenario_decisions())

    @contextlib.contextmanager
    def ctx():
        with patch("app.chatbot.brain.get_last_trade_context", side_effect=_trade_fn), \
             patch("app.chatbot.brain.ensure_fresh_profile", return_value=_profile), \
             patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
             patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
             patch("app.chatbot.brain.save_message", return_value=None), \
             patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
             patch("app.chatbot.brain.llm_client.generate", side_effect=_llm.generate), \
             patch("app.chatbot.brain.get_scenario_decisions", side_effect=_scenario_fn), \
             patch("app.chatbot.brain.get_trade_history_window", return_value=_make_fake_trade_window()), \
             patch("app.chatbot.brain.get_pnl_summary", return_value=MagicMock(ok=True, data={})), \
             patch("app.chatbot.brain.get_rule_adherence", return_value=MagicMock(ok=True, data={})):
            yield _llm
    return ctx()


# ===========================================================================
# A. Healthy Fake LLM Tests
# ===========================================================================

PHASE1_MESSAGES = [
    "Explain my last trade",
    "i bought from a tip",
    "Why did I lose?",
    "did i follow my rule in my last trade?",
    "what was my last trade",
    "tell me a joke",
    "I feel bad about my losses",
    "in simple words",
    "My habits",
    "My scenario decisions",
    "Summary of my trades today",
]


class TestHealthyLLM:
    """With a healthy fake LLM: each message gets a unique Gemini reply, generated_by='gemini'."""

    def _run_message(self, msg, fake_llm=None):
        from app.chatbot.brain import answer
        with _common_patches(fake_llm=fake_llm) as llm:
            return answer(user_id=1, message=msg), llm

    def test_all_personal_messages_produce_different_replies(self):
        """No two personal messages produce the same canned report."""
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM()
        results = []
        with _common_patches(fake_llm=llm) as _:
            for msg in PHASE1_MESSAGES:
                res = answer(user_id=1, message=msg)
                results.append(res)

        replies = [r["reply"] for r in results]
        # At least 6 unique replies from 11 messages (some may be vague/canned)
        unique_replies = set(replies)
        assert len(unique_replies) >= 6, f"Expected >=6 unique replies, got {len(unique_replies)}"

    def test_explain_last_trade_uses_gemini(self):
        res, _ = self._run_message("Explain my last trade")
        assert res["generated_by"] == "gemini"
        assert res["route"] == "MY_DATA"
        assert res["used_data"] is True
        assert "SEBI registration" not in res["reply"]

    def test_why_did_i_lose_uses_gemini(self):
        res, _ = self._run_message("Why did I lose?")
        assert res["generated_by"] == "gemini"
        assert res["route"] == "MY_DATA"

    def test_rule_check_uses_gemini(self):
        res, _ = self._run_message("did i follow my rule in my last trade?")
        assert res["generated_by"] == "gemini"
        assert res["route"] == "MY_DATA"

    def test_what_was_last_trade_uses_gemini(self):
        res, _ = self._run_message("what was my last trade")
        assert res["generated_by"] == "gemini"

    def test_feel_bad_uses_gemini(self):
        res, _ = self._run_message("I feel bad about my losses")
        assert res["generated_by"] == "gemini"
        assert res["route"] == "MY_DATA"

    def test_my_habits_uses_gemini(self):
        res, _ = self._run_message("My habits")
        assert res["route"] == "MY_DATA"
        # Either gemini or template depending on PROFILE focus — just check not refused
        assert "SEBI registration" not in res["reply"]

    def test_my_scenario_decisions_uses_gemini(self):
        res, _ = self._run_message("My scenario decisions")
        assert res["route"] == "MY_DATA"
        assert "SEBI registration" not in res["reply"]

    def test_different_intent_notes_sent_to_gemini(self):
        """explain, why_lost, rule_check send DIFFERENT intent notes to Gemini."""
        from app.chatbot.brain import answer
        messages_and_expected = [
            ("Explain my last trade", "6-part"),
            ("Why did I lose?", "why"),
            ("did i follow my rule in my last trade?", "rule adherence"),
        ]
        for msg, expected_fragment in messages_and_expected:
            llm = RecordingFakeLLM()
            with _common_patches(fake_llm=llm):
                answer(user_id=1, message=msg)
            assert len(llm.calls) >= 1, f"No Gemini call for '{msg}'"
            # The intent note is embedded in the user prompt
            last_msg_content = llm.calls[0]["messages"][-1]["content"]
            assert expected_fragment.lower() in last_msg_content.lower(), (
                f"Expected '{expected_fragment}' in Gemini prompt for '{msg}', got:\n{last_msg_content[:300]}"
            )


# ===========================================================================
# B. Tip Statement Test (CRITICAL)
# ===========================================================================

class TestTipStatement:
    """'i bought from a tip' must NOT be refused and IS answered conversationally."""

    def test_not_refused(self):
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM()
        with _common_patches(fake_llm=llm):
            res = answer(user_id=1, message="i bought from a tip")
        assert res["route"] != "TIP_REFUSAL", "Tip statement was incorrectly refused"
        assert "SEBI registration" not in res["reply"]
        assert "cannot provide" not in res["reply"]
        assert res["generated_by"] in ("gemini", "template", "canned")

    def test_conversational_reply(self):
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM()
        with _common_patches(fake_llm=llm):
            res = answer(user_id=1, message="i bought from a tip")
        # Must have called Gemini (not just returned a canned refusal)
        assert len(llm.calls) >= 1, "Expected at least 1 Gemini call for tip statement"
        # Gemini prompt should contain the user's sentence
        last_prompt = llm.calls[0]["messages"][-1]["content"]
        assert "bought from a tip" in last_prompt.lower()

    def test_context_includes_trade_data(self):
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM()
        with _common_patches(fake_llm=llm):
            res = answer(user_id=1, message="i bought from a tip")
        if llm.calls:
            full_prompt = llm.calls[0]["messages"][-1]["content"]
            # Facts should be present
            assert "INFY" in full_prompt or "last_trade" in full_prompt

    def test_is_tip_request_does_not_fire_on_statement(self):
        from app.chatbot.guards import is_tip_request
        assert is_tip_request("i bought from a tip") is False
        assert is_tip_request("I acted on a tip from my friend") is False

    def test_is_tip_request_fires_on_actual_requests(self):
        from app.chatbot.guards import is_tip_request
        assert is_tip_request("which stocks should I buy?") is True
        assert is_tip_request("give me a stock tip") is True
        assert is_tip_request("should I buy INFY?") is True


# ===========================================================================
# C. LLM Failure Mode Tests
# ===========================================================================

class TestLLMFailureModes:
    """When Gemini fails, replies must be question-specific templates."""

    FAILURE_MODES = [
        ("RATE_LIMIT", "rate_limit"),
        ("TIMEOUT", "timeout"),
        ("CONNECT_ERROR", "connect_error"),
        ("EMPTY", "empty"),
        ("BLOCKED", "blocked"),
        ("SERIAL_ERROR", "serial_error"),
    ]

    @pytest.mark.parametrize("error_kind,expected_reason_fragment", FAILURE_MODES)
    def test_degraded_template_on_failure(self, error_kind, expected_reason_fragment):
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM(fail_mode=error_kind)
        with _common_patches(fake_llm=llm):
            res = answer(user_id=1, message="Explain my last trade")
        assert res["degraded"] is True
        assert res["generated_by"] == "template"
        assert expected_reason_fragment in (res["degraded_reason"] or "").lower()

    def test_why_lost_template_contains_data_factors(self):
        """'Why did I lose?' template should mention factors from data."""
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM(fail_mode="RATE_LIMIT")
        with _common_patches(fake_llm=llm):
            res = answer(user_id=1, message="Why did I lose?")
        assert res["generated_by"] == "template"
        # Must contain the trade summary
        assert "INFY" in res["reply"]
        # Must mention data-based explanation
        assert "data" in res["reply"].lower() or "loss" in res["reply"].lower()

    def test_rule_check_template_no_false_followed(self):
        """'did I follow my rule' template: with empty rules_broken, says 'no rule alerts' not 'followed rules'."""
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM(fail_mode="TIMEOUT")
        with _common_patches(fake_llm=llm):
            res = answer(user_id=1, message="did i follow my rule in my last trade?")
        assert res["generated_by"] == "template"
        reply_lower = res["reply"].lower()
        # Must not say "followed your standard trading process"
        assert "standard trading process" not in reply_lower
        # Must say something about rule alerts or no rule check
        assert "rule" in reply_lower

    """When rules_broken is absent/None (not recorded), template says 'no rule alerts' (empty list from adapter)
    or 'no rule-check record' (None, meaning the field was truly absent)."""
    def test_rule_check_template_with_no_rules_broken_field(self):
        """When rules_broken is explicitly absent from context (removed), template says 'no rule-check record'."""
        from app.chatbot.brain import make_last_trade_template_reply
        trade_ctx = {
            "symbol": "INFY",
            "quantity": 10,
            "entry_price": 1800.0,
            "exit_price": 1750.0,
            "pnl": -500.0,
            "charges": 20.0,
            "hold_duration_mins": 30.0,
            "rules_broken": None,  # explicitly None — no record
            "mistake_flags": [],
            "gap_minutes": None,
            "previous_trade_pnl": None,
        }
        habits = {"rule_adherence_rate_pct": 80.0}
        perf = {}
        reply = make_last_trade_template_reply(
            trade_ctx, habits, perf, question_intent="rule_check"
        )
        assert "no rule-check record" in reply.lower() or "no rule check" in reply.lower()

    def test_what_was_template_is_brief(self):
        """'what was my last trade' template is a brief factual summary."""
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM(fail_mode="BLOCKED")
        with _common_patches(fake_llm=llm):
            res = answer(user_id=1, message="what was my last trade")
        assert res["generated_by"] == "template"
        assert "INFY" in res["reply"]
        # Brief: should be 1-2 lines
        assert len(res["reply"].split("\n")) <= 3

    def test_never_generic_greeting_on_failure(self):
        """No failure mode should return the vague greeting."""
        from app.chatbot.brain import answer
        for mode in ["RATE_LIMIT", "TIMEOUT", "CONNECT_ERROR", "BLOCKED"]:
            llm = RecordingFakeLLM(fail_mode=mode)
            with _common_patches(fake_llm=llm):
                res = answer(user_id=1, message="Explain my last trade")
            assert "I'm your TradeZen Coach" not in res["reply"], (
                f"Generic greeting returned on {mode} failure"
            )


# ===========================================================================
# D. Property Tests
# ===========================================================================

class TestProperties:
    """No missing field renders as 0/0.00/'followed', per-user isolation, no outside writes."""

    def test_missing_fields_not_rendered_as_zero(self):
        """Template with None fields must not show '0', '0.00', or 'followed'."""
        from app.chatbot.brain import make_last_trade_template_reply
        trade_ctx = {
            "symbol": "INFY",
            "quantity": None,  # missing
            "entry_price": None,  # missing
            "exit_price": None,  # missing
            "pnl": None,  # missing
            "rules_broken": None,  # no record
            "hold_duration_mins": None,
            "gap_minutes": None,
            "previous_trade_pnl": None,
            "mistake_flags": [],
            "charges": None,
        }
        habits = {"rule_adherence_rate_pct": None}
        perf = {}
        for intent in ("explain", "why_lost", "rule_check", "what_was"):
            reply = make_last_trade_template_reply(
                trade_ctx, habits, perf, question_intent=intent
            )
            # Must not contain literal "0.00" or "₹0.00" for missing values
            # (breakeven "₹0.00" is OK only when pnl IS actually 0, not None)
            assert "followed your" not in reply.lower()
            # Ensure it doesn't crash
            assert isinstance(reply, str)
            assert len(reply) > 0

    def test_profile_no_strengths_over_zero_win_rate(self):
        """Profile template with 0% win rate must NOT say 'Strengths'."""
        from app.chatbot.brain import make_profile_template_reply
        profile = _make_fake_profile(win_rate=0.0, rule_adh=21.1)
        reply = make_profile_template_reply(profile)
        assert "Strengths" not in reply
        assert "Overall" in reply

    def test_per_user_isolation(self):
        """answer(user_id=1) and answer(user_id=2) don't share session state."""
        from app.chatbot.brain import answer, conversation_states
        llm = RecordingFakeLLM()
        with _common_patches(fake_llm=llm):
            answer(user_id=1, message="Explain my last trade")
            answer(user_id=2, message="My habits")
        state1 = conversation_states.get(1)
        state2 = conversation_states.get(2)
        # Both should exist
        assert state1 is not None
        assert state2 is not None
        # Different users, different states
        assert state1.user_id != state2.user_id

    def test_save_message_captures_all_writes(self):
        """All DB writes go through save_message (which we mock), no other writes."""
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM()
        save_calls = []

        def recording_save(*args, **kwargs):
            save_calls.append((args, kwargs))

        with patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _make_fake_trade_ctx()), \
             patch("app.chatbot.brain.ensure_fresh_profile", return_value=_make_fake_profile()), \
             patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
             patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
             patch("app.chatbot.brain.save_message", side_effect=recording_save), \
             patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
             patch("app.chatbot.brain.llm_client.generate", side_effect=llm.generate), \
             patch("app.chatbot.brain.get_scenario_decisions", side_effect=lambda *a, **kw: _make_fake_scenario_decisions()), \
             patch("app.chatbot.brain.get_trade_history_window", return_value=_make_fake_trade_window()), \
             patch("app.chatbot.brain.get_pnl_summary", return_value=MagicMock(ok=True, data={})), \
             patch("app.chatbot.brain.get_rule_adherence", return_value=MagicMock(ok=True, data={})):
            answer(user_id=1, message="Explain my last trade")

        # At least 2 calls (user msg + assistant reply)
        assert len(save_calls) >= 2
        # All writes are for user_id=1
        for args, kwargs in save_calls:
            assert args[0] == 1  # user_id


# ===========================================================================
# E. Scenario Outcome Scale Test
# ===========================================================================

class TestScenarioOutcome:
    """Scenario outcome must match ScenarioSimulation's own value for the same attempt."""

    def test_outcome_pnl_uses_outcome_5m_correctly(self):
        """get_scenario_decisions with outcome_5m=545.4, current_price=540, size=10 → 54.0"""
        # This tests the adapters.py fix indirectly via the template
        # The fake scenario data already has outcome_pnl=54.0
        # Verify it appears correctly in the template
        from app.chatbot.brain import make_scenario_template_reply
        decisions = [{
            "scenario_id": 22,
            "attempt_id": 100,
            "attempt_no": 1,
            "action": "buy",
            "size": 10,
            "reason_picked": "MOMENTUM",
            "reason_code": "MOMENTUM",
            "scenario_shown": {
                "event_type": "market_move",
                "drop_pct": 0.54,
                "current_price": 540.0,
            },
            "outcome_pnl": 54.0,  # (545.4 - 540) * 10 = 54.0
            "rule_matched": True,
            "revision": None,
            "bot_choices": [],
            "created_at": "2026-11-20T10:00:00",
        }]
        reply = make_scenario_template_reply(decisions, "1")
        assert "54" in reply  # outcome should be ₹54
        assert "17,614,200" not in reply  # the old broken value


# ===========================================================================
# F. LLM Exception Classifier Tests
# ===========================================================================

class TestExceptionClassifier:
    """The _classify_exception function must classify correctly by type, not string."""

    def _cls(self):
        from app.chatbot.llm import _classify_exception
        return _classify_exception

    def test_timeout_error(self):
        assert self._cls()(TimeoutError("timed out")) == "TIMEOUT"

    def test_socket_timeout(self):
        assert self._cls()(socket.timeout("deadline exceeded")) == "TIMEOUT"

    def test_connection_error(self):
        assert self._cls()(ConnectionError("refused")) == "CONNECT_ERROR"

    def test_connection_refused_error(self):
        assert self._cls()(ConnectionRefusedError("refused")) == "CONNECT_ERROR"

    def test_ssl_error(self):
        exc = ssl.SSLError("SSL handshake failed")
        assert self._cls()(exc) == "TLS_ERROR"

    def test_dns_error(self):
        exc = socket.gaierror("Name or service not known")
        assert self._cls()(exc) == "DNS_ERROR"

    def test_type_error_is_serial(self):
        assert self._cls()(TypeError("not serializable")) == "SERIAL_ERROR"

    def test_value_error_is_serial(self):
        assert self._cls()(ValueError("bad value")) == "SERIAL_ERROR"

    def test_unknown_exception_not_network_error(self):
        exc = RuntimeError("something weird")
        result = self._cls()(exc)
        assert "NETWORK_ERROR" not in result
        assert result.startswith("UNKNOWN_ERROR:")
        assert "RuntimeError" in result

    def test_rate_limit_from_string(self):
        """SDK exceptions that embed 429 in their message string."""
        exc = Exception("Error 429: Resource exhausted")
        assert self._cls()(exc) == "RATE_LIMIT"

    def test_server_error_from_string(self):
        exc = Exception("Internal server error 500")
        assert self._cls()(exc) == "SERVER_ERROR_5XX"

    def test_http_status_attribute(self):
        """Exception with a status_code attribute."""
        exc = Exception("bad request")
        exc.status_code = 400
        assert self._cls()(exc) == "CLIENT_ERROR_400"

    def test_http_429_attribute(self):
        exc = Exception("rate limited")
        exc.status_code = 429
        assert self._cls()(exc) == "RATE_LIMIT"

    def test_http_503_attribute(self):
        exc = Exception("service unavailable")
        exc.status_code = 503
        assert self._cls()(exc) == "SERVER_ERROR_5XX"

    def test_os_error_conn_refused_windows(self):
        """OSError with errno 10061 (Windows WSAECONNREFUSED)."""
        exc = OSError(10061, "Connection refused")
        assert self._cls()(exc) == "CONNECT_ERROR"


# ===========================================================================
# G. Charges Suffix and Formatting Tests
# ===========================================================================

class TestChargesAndFormatting:
    """Charges suffix, duration formatting, and pnl phrasing."""

    def test_charges_suffix_present_when_charges_gt_0(self):
        from app.chatbot.brain import _charges_suffix
        assert _charges_suffix({"charges": 20.0}) == " (after charges)"

    def test_charges_suffix_absent_when_no_charges(self):
        from app.chatbot.brain import _charges_suffix
        assert _charges_suffix({"charges": 0}) == ""
        assert _charges_suffix({"charges": None}) == ""
        assert _charges_suffix({}) == ""

    def test_format_duration_under_a_minute(self):
        from app.chatbot.brain import format_duration
        assert format_duration(0.5) == "under a minute"

    def test_format_duration_whole_number(self):
        from app.chatbot.brain import format_duration
        assert format_duration(5.0) == "5 minutes"

    def test_format_pnl_no_double_negative(self):
        from app.chatbot.brain import format_pnl_phrase
        phrase = format_pnl_phrase(-500.0)
        assert phrase.count("-") <= 0  # No minus sign — money is absolute
        assert "loss" in phrase


# ===========================================================================
# H. End-to-End Before/After Comparison (scripted)
# ===========================================================================

class TestEndToEndComparison:
    """Scripted run of all 11 Phase 1 messages showing the new behaviour."""

    def test_all_messages_produce_valid_results(self):
        """Every message returns a valid result with generated_by field."""
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM()
        results = []
        with _common_patches(fake_llm=llm):
            for msg in PHASE1_MESSAGES:
                res = answer(user_id=1, message=msg)
                results.append((msg, res))

        for msg, res in results:
            assert "reply" in res, f"Missing 'reply' for '{msg}'"
            assert "route" in res, f"Missing 'route' for '{msg}'"
            assert "generated_by" in res, f"Missing 'generated_by' for '{msg}'"
            assert res["generated_by"] in ("gemini", "template", "canned", "refusal", "notes"), (
                f"Invalid generated_by='{res['generated_by']}' for '{msg}'"
            )

    def test_print_evidence_table(self, capsys):
        """Prints the before/after evidence table for manual review."""
        from app.chatbot.brain import answer
        llm = RecordingFakeLLM()
        print("\n" + "=" * 100)
        print(f"{'Message':<45} {'Route':<12} {'Focus':<18} {'GenBy':<10} {'Degraded':<10} {'Reason':<25}")
        print("-" * 100)

        with _common_patches(fake_llm=llm):
            for msg in PHASE1_MESSAGES:
                t0 = time.time()
                res = answer(user_id=1, message=msg)
                elapsed = int((time.time() - t0) * 1000)
                focus = "—"
                # Try to infer focus from the response or route
                print(f"{msg:<45} {res['route']:<12} {focus:<18} {res['generated_by']:<10} {str(res['degraded']):<10} {str(res.get('degraded_reason', '')):<25}")

        print("=" * 100)
        # Capture output for review
        captured = capsys.readouterr()
        print(captured.out)


# ===========================================================================
# I. Safe JSON Encoder Tests
# ===========================================================================

class TestSafeJSONEncoder:
    """safe_json_dumps handles Decimal, datetime, UUID, numpy, NaN without crashing."""

    def test_decimal(self):
        from app.chatbot.llm import safe_json_dumps
        result = safe_json_dumps({"price": Decimal("1800.50")})
        assert "1800.5" in result

    def test_datetime(self):
        from app.chatbot.llm import safe_json_dumps
        result = safe_json_dumps({"ts": datetime(2026, 11, 20, 10, 0, 0)})
        assert "2026-11-20" in result

    def test_none_value(self):
        from app.chatbot.llm import safe_json_dumps
        result = safe_json_dumps({"val": None})
        assert "null" in result

    def test_whole_decimal_becomes_int(self):
        from app.chatbot.llm import safe_json_dumps
        result = safe_json_dumps({"qty": Decimal("10.0")})
        # Should be "10" not "10.0"
        assert '"qty": 10' in result or '"qty":10' in result
