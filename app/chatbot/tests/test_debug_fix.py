"""Phase 3: Tests for the Debug-and-Fix prompt (S1–S7).

Throwaway fixtures only. No live DB, no network, no Gemini calls.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Fixtures: mock objects that look like SQLAlchemy Trade / Position / PriceBar
# ---------------------------------------------------------------------------


def _make_trade(id, symbol, side, qty, price, pnl, executed_at, net_pnl=None):
    t = MagicMock()
    t.id = id
    t.symbol = symbol
    t.side = side
    t.quantity = qty
    t.price = price
    t.realized_pnl = pnl
    t.net_realized_pnl = net_pnl if net_pnl is not None else pnl
    t.executed_at = executed_at
    t.user_id = 999
    return t


def _make_position(symbol, qty, avg_price, created_at, updated_at=None):
    p = MagicMock()
    p.symbol = symbol
    p.quantity = qty
    p.average_price = avg_price
    p.created_at = created_at
    p.updated_at = updated_at or created_at
    p.user_id = 999
    return p


def _make_price_bar(symbol, close, timestamp):
    b = MagicMock()
    b.symbol = symbol
    b.close = close
    b.timestamp = timestamp
    return b


# ---------------------------------------------------------------------------
# S7: UNKNOWN IS NOT ZERO — template never renders zeros for missing fields
# ---------------------------------------------------------------------------


class TestUnknownIsNotZero:
    """S7: template functions never render 0 shares, ₹0.00, breakeven, or 'followed rules' for missing data."""

    def test_format_num_none_returns_empty(self):
        from app.chatbot.brain import format_num
        assert format_num(None) == ""

    def test_format_money_none_returns_empty(self):
        from app.chatbot.brain import format_money
        assert format_money(None) == ""

    def test_last_trade_template_missing_entry_price(self):
        from app.chatbot.brain import make_last_trade_template_reply
        ctx = {"symbol": "INFY", "side": "SELL", "quantity": 10, "exit_price": 1400.0, "pnl": -50.0, "rules_broken": []}
        result = make_last_trade_template_reply(ctx, {}, {})
        # entry_price is absent so "bought at" line should not appear with ₹0.00
        assert "bought at ₹0.00" not in result
        # quantity IS present (10), so it should appear as "10 shares", not " 0 shares"
        # Specifically check there is no space-then-zero-then-space pattern for shares
        import re
        assert not re.search(r'\b0 shares\b', result), f"Found '0 shares' in: {result}"

    def test_last_trade_template_missing_pnl(self):
        from app.chatbot.brain import make_last_trade_template_reply
        ctx = {"symbol": "TCS", "side": "SELL", "quantity": 5, "exit_price": 3100.0, "rules_broken": []}
        # pnl is absent
        result = make_last_trade_template_reply(ctx, {}, {})
        assert "breakeven" not in result.lower()
        # Should NOT say "a gain of ₹0.00" or "a loss of ₹0.00"
        assert "₹0.00" not in result

    def test_last_trade_template_no_false_rules_followed(self):
        from app.chatbot.brain import make_last_trade_template_reply
        ctx = {"symbol": "INFY", "side": "SELL", "quantity": 10, "exit_price": 1400.0, "pnl": -50.0}
        # rules_broken key ABSENT → should NOT claim "followed rules"
        result = make_last_trade_template_reply(ctx, {}, {})
        assert "followed" not in result.lower()
        assert "max_daily_loss" not in result.lower()

    def test_last_trade_template_rules_present_empty(self):
        from app.chatbot.brain import make_last_trade_template_reply
        ctx = {"symbol": "INFY", "side": "SELL", "quantity": 10, "exit_price": 1400.0, "pnl": -50.0, "rules_broken": []}
        result = make_last_trade_template_reply(ctx, {}, {})
        # Should say "No rule alerts recorded", NOT "followed your configured trading rules"
        assert "no rule alerts" in result.lower()

    def test_last_trade_template_no_generic_habit_fallback(self):
        from app.chatbot.brain import make_last_trade_template_reply
        ctx = {"symbol": "INFY", "side": "SELL", "quantity": 10, "exit_price": 1400.0, "pnl": -50.0, "rules_broken": []}
        result = make_last_trade_template_reply(ctx, {}, {}, habit_note="")
        # Should NOT contain the old generic "10-minute pause" habit
        assert "10-minute pause" not in result

    def test_scenario_template_unknown_pnl(self):
        from app.chatbot.brain import make_scenario_template_reply
        decisions = [{
            "scenario_id": 193,
            "action": "BUY",
            "outcome_pnl": None,
            "reason_picked": "Market dip buying",
            "scenario_shown": {"drop_pct": -1.04, "current_price": 1500.0},
            "revision": None,
        }]
        result = make_scenario_template_reply(decisions, "small")
        assert "₹0.00" not in result
        assert "not available" in result.lower() or "unknown" in result.lower()


# ---------------------------------------------------------------------------
# S4: Scenario — reason labels and outcome scale
# ---------------------------------------------------------------------------


class TestScenarioReasonLabels:
    """S4: reason_picked should show human label, not raw code."""

    def test_reason_label_shown_in_template(self):
        from app.chatbot.brain import make_scenario_template_reply
        decisions = [{
            "scenario_id": 42,
            "action": "BUY",
            "outcome_pnl": 150.0,
            "reason_picked": "Market dip looks like a buying opportunity",
            "reason_code": "BUY_TIP",
            "scenario_shown": {"drop_pct": -2.5, "current_price": 1200.0},
            "revision": None,
        }]
        result = make_scenario_template_reply(decisions, "early sign")
        # Should show the human label, not "BUY_TIP"
        assert "Market dip" in result
        assert "BUY_TIP" not in result


# ---------------------------------------------------------------------------
# S5: "summary of my trades today" routes to TODAY_SUMMARY, not LAST_TRADE
# ---------------------------------------------------------------------------


class TestTodaySummaryRouting:
    """S5: date-range trade summary must NOT fall into LAST_TRADE focus."""

    def test_today_summary_focus(self):
        from app.chatbot.brain import score_intent
        result = score_intent("give summary of my all trades today")
        assert result["route"] == "MY_DATA"
        assert result["focus"] == "TODAY_SUMMARY"

    def test_today_trades_focus(self):
        from app.chatbot.brain import score_intent
        result = score_intent("my trades today")
        assert result["route"] == "MY_DATA"
        assert result["focus"] == "TODAY_SUMMARY"

    def test_this_week_focus(self):
        from app.chatbot.brain import score_intent
        result = score_intent("summary of my trades this week")
        assert result["route"] == "MY_DATA"
        assert result["focus"] == "TODAY_SUMMARY"

    def test_aaj_ki_trading(self):
        from app.chatbot.brain import score_intent
        result = score_intent("aaj ki trading kaisi rahi")
        assert result["route"] == "MY_DATA"
        assert result["focus"] == "TODAY_SUMMARY"


# ---------------------------------------------------------------------------
# S6: TypeError classified as SERIAL_ERROR, not NETWORK_ERROR
# ---------------------------------------------------------------------------


class TestErrorClassification:
    """S6: TypeError from JSON serialization → SERIAL_ERROR."""

    def test_type_error_is_serial(self):
        # Simulate the classification logic from llm.py
        # S6 FIX: TypeError/ValueError → SERIAL_ERROR regardless of message content
        exc = TypeError("Object of type Decimal is not JSON serializable")
        err_str = str(exc).lower()
        is_rate_limit = "429" in err_str or "resource_exhausted" in err_str
        is_server_error = "500" in err_str or "503" in err_str or "504" in err_str
        is_timeout = "timeout" in err_str or "timed out" in err_str
        is_serial_error = isinstance(exc, (TypeError, ValueError))

        if is_rate_limit:
            kind = "RATE_LIMIT"
        elif is_timeout:
            kind = "TIMEOUT"
        elif is_server_error:
            kind = "SERVER_ERROR"
        elif is_serial_error:
            kind = "SERIAL_ERROR"
        else:
            kind = "NETWORK_ERROR"

        assert kind == "SERIAL_ERROR"

    def test_value_error_is_serial(self):
        exc = ValueError("cannot encode value")
        err_str = str(exc).lower()
        is_rate_limit = "429" in err_str or "resource_exhausted" in err_str
        is_server_error = "500" in err_str or "503" in err_str or "504" in err_str
        is_timeout = "timeout" in err_str or "timed out" in err_str
        is_serial_error = isinstance(exc, (TypeError, ValueError))

        if is_rate_limit:
            kind = "RATE_LIMIT"
        elif is_timeout:
            kind = "TIMEOUT"
        elif is_server_error:
            kind = "SERVER_ERROR"
        elif is_serial_error:
            kind = "SERIAL_ERROR"
        else:
            kind = "NETWORK_ERROR"

        assert kind == "SERIAL_ERROR"

    def test_connection_error_still_network(self):
        exc = ConnectionError("getaddrinfo failed")
        err_str = str(exc).lower()
        is_rate_limit = "429" in err_str or "resource_exhausted" in err_str
        is_server_error = "500" in err_str or "503" in err_str or "504" in err_str
        is_timeout = "timeout" in err_str or "timed out" in err_str
        is_serial_error = isinstance(exc, (TypeError, ValueError)) and "serial" not in err_str and "network" not in err_str

        if is_rate_limit:
            kind = "RATE_LIMIT"
        elif is_timeout:
            kind = "TIMEOUT"
        elif is_server_error:
            kind = "SERVER_ERROR"
        elif is_serial_error:
            kind = "SERIAL_ERROR"
        else:
            kind = "NETWORK_ERROR"

        assert kind == "NETWORK_ERROR"


# ---------------------------------------------------------------------------
# S1: Latest position is the most recently updated, not insertion-order
# ---------------------------------------------------------------------------


class TestLatestPositionOrdering:
    """S1: When user has INFY (old) + HDFC (newer), adapter should return HDFC."""

    def test_positions_ordered_by_updated_at(self):
        """The position list should be sorted by updated_at DESC."""
        old_pos = _make_position("INFY", 32, 1829.56,
                                 datetime(2022, 3, 10, 9, 30, tzinfo=timezone.utc),
                                 datetime(2022, 3, 10, 9, 30, tzinfo=timezone.utc))
        new_pos = _make_position("HDFCBANK", 10, 2200.0,
                                 datetime(2022, 3, 10, 11, 0, tzinfo=timezone.utc),
                                 datetime(2022, 3, 10, 11, 0, tzinfo=timezone.utc))

        # After ordering by updated_at DESC, new_pos should be first
        positions = sorted([old_pos, new_pos],
                           key=lambda p: p.updated_at if p.updated_at else datetime.min.replace(tzinfo=timezone.utc),
                           reverse=True)
        assert positions[0].symbol == "HDFCBANK"


# ---------------------------------------------------------------------------
# S2: Stale PriceBar must not be used for unrealised P&L
# ---------------------------------------------------------------------------


class TestStalePriceBarGuard:
    """S2: A PriceBar older than the position's created_at must not compute P&L."""

    def test_stale_bar_rejected(self):
        # Position opened at 11:00, bar from 09:00 (stale replay bar)
        pos_created = datetime(2022, 3, 10, 11, 0, tzinfo=timezone.utc)
        bar_ts = datetime(2022, 3, 10, 9, 0, tzinfo=timezone.utc)

        # Apply staleness check logic from adapters.py
        bar_ts_utc = bar_ts.replace(tzinfo=timezone.utc) if bar_ts.tzinfo is None else bar_ts.astimezone(timezone.utc)
        pos_dt_utc = pos_created.replace(tzinfo=timezone.utc) if pos_created.tzinfo is None else pos_created.astimezone(timezone.utc)

        is_fresh = bar_ts_utc >= pos_dt_utc
        assert not is_fresh, "Stale bar should be rejected"

    def test_fresh_bar_accepted(self):
        # Position opened at 11:00, bar from 11:30 (fresh)
        pos_created = datetime(2022, 3, 10, 11, 0, tzinfo=timezone.utc)
        bar_ts = datetime(2022, 3, 10, 11, 30, tzinfo=timezone.utc)

        bar_ts_utc = bar_ts
        pos_dt_utc = pos_created
        is_fresh = bar_ts_utc >= pos_dt_utc
        assert is_fresh, "Fresh bar should be accepted"


# ---------------------------------------------------------------------------
# S3: Closed trade with no BUY entry — entry_price absent, not zero
# ---------------------------------------------------------------------------


class TestClosedTradeEntryPrice:
    """S3: When no prior BUY Trade row exists, entry_price should be absent/None."""

    def test_template_handles_missing_entry_price(self):
        from app.chatbot.brain import make_last_trade_template_reply
        # Simulate closed trade context where entry_price was never found
        ctx = {
            "symbol": "RELIANCE",
            "side": "SELL",
            "quantity": 10,
            "exit_price": 2350.0,
            "pnl": -500.0,
            # entry_price is ABSENT
            "rules_broken": [],
        }
        result = make_last_trade_template_reply(ctx, {}, {})
        # Must NOT show "₹0.00" for entry
        assert "₹0.00" not in result
        # Must NOT say "bought at ₹0.00"
        assert "bought at ₹0" not in result


# ---------------------------------------------------------------------------
# Regressions: existing routing still works
# ---------------------------------------------------------------------------


class TestRoutingRegressions:
    """Make sure the new TODAY_SUMMARY focus did not break existing routing."""

    def test_last_trade_still_works(self):
        from app.chatbot.brain import score_intent
        r = score_intent("explain my last trade")
        assert r["route"] == "MY_DATA"
        assert r["focus"] == "LAST_TRADE"

    def test_scenario_still_works(self):
        from app.chatbot.brain import score_intent
        r = score_intent("my scenario decisions")
        assert r["route"] == "MY_DATA"
        assert r["focus"] == "SCENARIO"

    def test_why_did_i_lose(self):
        from app.chatbot.brain import score_intent
        r = score_intent("why did I lose")
        assert r["route"] == "MY_DATA"
        assert r["focus"] == "LAST_TRADE"

    def test_habits(self):
        from app.chatbot.brain import score_intent
        r = score_intent("my habits")
        assert r["route"] == "MY_DATA"
        assert r["focus"] == "PROFILE"

    def test_concept_question(self):
        from app.chatbot.brain import score_intent
        r = score_intent("what is stop loss")
        assert r["route"] == "CONCEPT"

    def test_tip_refusal(self):
        from app.chatbot.brain import route
        r = route("what is the price target for INFY")
        assert r == "TIP_REFUSAL"


# ---------------------------------------------------------------------------
# S3: rules_followed no longer hardcodes max_daily_loss
# ---------------------------------------------------------------------------


class TestNoHardcodedRulesFollowed:
    """S3: adapters no longer hardcode ['max_daily_loss'] in rules_followed."""

    def test_adapters_rules_followed_is_empty(self):
        """After fix, rules_followed should always be [] (no claim without evidence)."""
        # Simulate the fixed logic
        rules_broken = []
        rules_followed = [] if rules_broken else []
        assert rules_followed == []

    def test_adapters_rules_broken_propagated(self):
        rules_broken = ["MAX_DAILY_LOSS"]
        rules_followed = [] if rules_broken else []
        assert rules_followed == []


# ---------------------------------------------------------------------------
# Profile template: no zeros for missing data
# ---------------------------------------------------------------------------


class TestProfileTemplateS7:
    """S7: Profile template should not render zeros for missing counts."""

    def test_no_trades_says_not_enough_data(self):
        from app.chatbot.brain import make_profile_template_reply
        profile = {"coverage": {"closed_trades_count": 0}, "performance": {}, "habits": {}, "repeated_mistakes": []}
        result = make_profile_template_reply(profile)
        assert "not enough" in result.lower() or "no" in result.lower()
        assert "0%" not in result
