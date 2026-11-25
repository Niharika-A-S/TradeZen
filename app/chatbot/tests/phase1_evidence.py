"""
Phase 1 Evidence Script for TradeZen Chatbot Debug-and-Redesign Prompt.

Runs the 11 test messages through the brain's answer() with a fake LLM that records
exactly what it receives, so we can inspect routing/branching without a real API call.
Prints ONLY: route, branch, generated_by, gemini_calls, degraded_reason, elapsed_ms.

Nothing personal is logged. No keys or values are printed.
"""
import sys
import time
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make package importable
_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

MESSAGES = [
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


# ---------------------------------------------------------------------------
# Fake LLM: records every call, returns a canned response
# ---------------------------------------------------------------------------
class FakeLLMRecorder:
    def __init__(self, text="[FAKE_GEMINI_RESPONSE]"):
        self.calls = []
        self._text = text

    def generate(self, system=None, messages=None, **kwargs):
        from app.chatbot.llm import LLMResult
        self.calls.append({
            "system_len": len(system or ""),
            "msg_count": len(messages or []),
            "last_user_len": len((messages or [{}])[-1].get("content", "")) if messages else 0,
        })
        return LLMResult(ok=True, text=self._text)

    def reset(self):
        self.calls = []


# ---------------------------------------------------------------------------
# Fake data helpers
# ---------------------------------------------------------------------------
def _fake_trade_ctx():
    class R:
        ok = True
        reason = None
        data = {
            "symbol": "TCS",
            "quantity": 10,
            "side": "SELL",
            "entry_price": 3619.21,
            "exit_price": 3615.59,
            "pnl": -56.20,
            "charges": 20.0,
            "net_realized_pnl": -56.20,
            "realized_pnl": -36.20,
            "hold_duration_mins": 45.0,
            "is_open": False,
            "rules_broken": [],
            "rules_followed": [],
            "mistake_flags": [],
            "has_closed_trades": True,
            "has_open_trade": False,
            "open_trade": None,
            "gap_minutes": 5.0,
            "previous_trade_pnl": -100.0,
        }
    return R()


def _fake_profile():
    return {
        "coverage": {"closed_trades_count": 10, "scenario_decisions_count": 5,
                     "sample_size_flag": "early sign", "scenario_sample_size_flag": "early sign"},
        "performance": {"all_time": {
            "win_rate_pct": 21.10, "avg_win": 400.0, "avg_loss": 500.0,
            "net": -1800.0, "expectancy": -120.0, "breakeven_win_rate_pct": 55.6
        }},
        "habits": {
            "user_median_size": 10.0,
            "rule_adherence_rate_pct": 21.10,
            "stop_loss_usage_pct": 60.0,
            "size_after_loss_vs_normal": 1.4,
            "user_median_hold_winners_mins": 30.0,
            "user_median_hold_losers_mins": 45.0,
        },
        "repeated_mistakes": [{"mistake_id": "revenge_trading", "count": 3, "last_timestamp": None}],
        "trend": {"status": "declining", "win_rate_delta": -5.0, "net_delta": -900.0, "rule_adherence_delta": -10.0},
    }


def _fake_scenario_decisions():
    class R:
        ok = True
        reason = None
        data = [
            {
                "scenario_id": 22,
                "attempt_id": 101,
                "attempt_no": 1,
                "action": "BUY",
                "size": 10,
                "reason_picked": "Market dip opportunity",
                "reason_code": "BUY_TIP",
                "scenario_shown": {"event_type": "dip", "drop_pct": 0.54, "current_price": 540.0},
                "outcome_pnl": 54.0,   # 10 units * 5.4 price diff = 54 (not 17M)
                "rule_matched": True,
                "revision": None,
                "bot_choices": [],
                "created_at": "2026-11-25T10:00:00",
            }
        ]
    return R()


def _fake_rule_adherence():
    class R:
        ok = True
        data = {}
        reason = None
    return R()


def _fake_trade_history():
    class R:
        ok = True
        reason = None
        data = [
            {"symbol": "TCS", "side": "SELL", "quantity": 10,
             "net_realized_pnl": -56.20, "realized_pnl": -36.20,
             "executed_at": "2026-11-25T10:30:00"}
        ]
    return R()


# ---------------------------------------------------------------------------
# Main evidence run
# ---------------------------------------------------------------------------
def run_evidence():
    from app.chatbot.brain import answer, conversation_states
    from app.chatbot.llm import LLMResult

    recorder = FakeLLMRecorder(text=(
        "This is a fake Gemini conversational reply to: {msg}. "
        "Your TCS trade showed a loss of ₹56.20 after charges."
    ))

    # Clear any session state between messages for a clean slate per-message test
    with open(os.devnull, "w") as devnull:
        pass  # silence

    print("\n" + "=" * 80)
    print("PHASE 1 EVIDENCE — Route / Branch / Generated-By per message (fake LLM)")
    print("=" * 80)

    # Patches applied for entire run
    with patch("app.chatbot.brain.get_last_trade_context", side_effect=lambda *a, **kw: _fake_trade_ctx()), \
         patch("app.chatbot.brain.ensure_fresh_profile", side_effect=lambda *a, **kw: _fake_profile()), \
         patch("app.chatbot.brain.get_trade_history_window", side_effect=lambda *a, **kw: _fake_trade_history()), \
         patch("app.chatbot.brain.get_scenario_decisions", side_effect=lambda *a, **kw: _fake_scenario_decisions()), \
         patch("app.chatbot.brain.get_rule_adherence", side_effect=lambda *a, **kw: _fake_rule_adherence()), \
         patch("app.chatbot.brain.rag_engine.get_chunk_by_file_id", return_value=None), \
         patch("app.chatbot.brain.rag_engine.retrieve", return_value=[]), \
         patch("app.chatbot.brain.rag_engine.search_notes", return_value=[]), \
         patch("app.chatbot.brain.save_message", return_value=None), \
         patch("app.chatbot.brain.should_append_coach_disclaimer", return_value=False), \
         patch("app.chatbot.brain.build_user_context_card",
               return_value="User Practice Card:\n• Win rate: 21.1%, Rule adherence: 21.1%"), \
         patch("app.chatbot.brain.llm_client") as mock_llm:

        mock_llm.generate = MagicMock(side_effect=recorder.generate)

        history = []
        for msg in MESSAGES:
            recorder.reset()
            t0 = time.monotonic()
            result = answer(user_id=1, message=msg, history=history)
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            route_str = result.get("route", "?")
            degraded = result.get("degraded", False)
            degraded_reason = result.get("degraded_reason") or "none"
            gem_calls = len(recorder.calls)
            generated_by = "template" if degraded else ("gemini" if gem_calls > 0 else "canned")

            # Determine branch
            focus = None
            if route_str == "MY_DATA":
                # Inspect the reply to guess focus
                r = result["reply"]
                if "scenario" in r.lower():
                    focus = "SCENARIO"
                elif "habit" in r.lower() or "win rate" in r.lower() or "adherence" in r.lower():
                    focus = "PROFILE"
                elif "trade" in r.lower() or "TCS" in r or "loss" in r.lower():
                    focus = "LAST_TRADE"
                else:
                    focus = "GENERAL_PERSONAL"

            branch = f"{route_str}/{focus}" if focus else route_str

            print(f"\nMSG: {msg!r}")
            print(f"  route={route_str}  branch={branch}  generated_by={generated_by}")
            print(f"  gemini_calls={gem_calls}  degraded_reason={degraded_reason}  elapsed_ms={elapsed_ms}ms")
            print(f"  reply_preview={result['reply'][:120].replace(chr(10), ' ')!r}")

            # Update history for next message
            history = history[-10:]
            history.append({"role": "user", "content": msg})
            history.append({"role": "assistant", "content": result["reply"][:200]})

    print("\n" + "=" * 80)
    print("PHASE 1 EVIDENCE — Root cause probes")
    print("=" * 80)

    # (a) Which line sends personal msgs to canned report
    print("\n(a) CANNED REPORT ROOT CAUSE:")
    print("  brain.py line 659: 'your standard trading process' fires when duration is known")
    print("  AND no quick-reentry pattern detected — no intelligence about the question asked.")
    print("  ACTUAL BUG: score_intent() assigns focus=LAST_TRADE for many diverse messages")
    print("  (lines 483-491: has_fp + any trade word => LAST_TRADE focus regardless of intent).")
    print("  Then lines 1131-1174 build the SAME 6-part prompt for all LAST_TRADE questions.")
    print("  'i bought from a tip' → has_fp=True (has 'I'), has_tv=True (buy word) → p_score=5 → MY_DATA/LAST_TRADE → trade report.")

    # (b) LLM exception classification
    print("\n(b) LLM ERROR CLASSIFICATION:")
    print("  llm.py lines 295-312: exception string scanning for '429', '500', 'timeout', TypeError.")
    print("  Any exception NOT matching those patterns falls through to NETWORK_ERROR (line 312).")
    print("  Bug: ConnectionError, SSLError, ProxyError, DNS failures all map to NETWORK_ERROR.")
    print("  Fix needed: classify by exception TYPE, not just string scanning.")

    # (c) TCS P&L charges
    print("\n(c) TCS TRADE P&L CHARGES:")
    print("  Trade data: entry=3619.21, exit=3615.59, qty=10.")
    print("  Price diff = -3.62/share * 10 = -36.20 (realized_pnl field).")
    print("  With charges=20.0: net_realized_pnl = -56.20 (net_realized_pnl field).")
    print("  get_last_trade_context (adapters.py line 679-684) uses net_realized_pnl if present.")
    print("  Template (brain.py line 549-555) uses pnl=trade_ctx['pnl'] = -56.20.")
    print("  BUT it never labels the reply 'after charges' — fix: add 'after charges' when charges field > 0.")

    # (d) Scenario outcome scale
    print("\n(d) SCENARIO OUTCOME SCALE:")
    print("  adapters.py line 909-919: outcome = diff * size_units.")
    print("  For scenario #22: drop_pct=0.54, current_price=540, outcome_5m not in fake.")
    print("  If size=1000 shares and diff=5.4, outcome = 5400 — not 17M.")
    print("  Bug: att.size field may store rupee-notional (e.g. 326 crore / 540 = 604000 units).")
    print("  Guard at line 913-915 caps at 10000 units, but 326cr/540 = 604k > 10000 so size_units=1.")
    print("  Real issue: the att.size field in ScenarioSimulation stores lot-value not share-count.")
    print("  ScenarioSimulation's own outcome must be read from outcome_5m directly, not recomputed.")

    # (e) Nudge timestamp
    print("\n(e) NUDGE TIMESTAMP SOURCE:")
    print("  api.py line 292-298: nudge created_at = exit_time from trade record (UTC DB timestamp).")
    print("  api.py line 309-313: rule violation nudge created_at = v['created_at'] (DB UTC timestamp).")
    print("  Frontend (ChatMessageItem.jsx line 15-16): appends 'Z' if no timezone marker.")
    print("  But if DB returns 'naive' string without Z, it's treated as UTC but could be IST.")
    print("  Also nudges are appended to messages[] AFTER current messages, but their created_at")
    print("  could be an older DB timestamp (e.g. trade happened at 02:50 UTC = 08:20 IST).")
    print("  Frontend uses created_at for display time, not insertion time → apparent time reversal.")
    print("  Fix: nudge should use wall-clock time of polling, not the event's DB timestamp for display.")


if __name__ == "__main__":
    run_evidence()
