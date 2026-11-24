"""User trading profile computation, caching, and fingerprinting for TradeZen Coach."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import statistics
import threading
import time
from typing import Dict, Any, Optional, List

from sqlalchemy import func

from .config import cfg
from .models import ChatUserProfile, get_db_session, init_db
from .adapters import (
    ToolResult,
    get_readonly_session,
    build_trade_facts,
    get_recent_trades,
    get_user_rules,
    get_recent_rule_violations,
    get_mistake_flags,
    get_scenario_decisions,
)

logger = logging.getLogger(__name__)

# Per-user reentrancy/build locks with timeout
_user_locks_lock = threading.Lock()
_user_locks: Dict[int, threading.Lock] = defaultdict(threading.Lock)


def _get_user_lock(user_id: int) -> threading.Lock:
    with _user_locks_lock:
        return _user_locks[user_id]


def fingerprint(user_id: int) -> str:
    """Computes a fast deterministic hash of user's activity.
    
    Reads cheap counts and latest IDs/timestamps of trades, scenario attempts,
    rule alerts, and mistake flags.
    Never raises.
    """
    try:
        trade_count = 0
        latest_trade_id = 0
        attempt_count = 0
        latest_attempt_id = 0
        alert_count = 0
        latest_alert_id = 0

        with get_readonly_session() as session:
            # 1. Trades
            try:
                from app.models.paper import Trade
                t_stats = session.query(
                    func.count(Trade.id),
                    func.max(Trade.id)
                ).filter(Trade.user_id == user_id).first()
                if t_stats:
                    trade_count = t_stats[0] or 0
                    latest_trade_id = t_stats[1] or 0
            except Exception:
                pass

            # 2. Scenario attempts
            try:
                from app.models.decision import Attempt
                a_stats = session.query(
                    func.count(Attempt.id),
                    func.max(Attempt.id)
                ).filter(Attempt.user_id == user_id).first()
                if a_stats:
                    attempt_count = a_stats[0] or 0
                    latest_attempt_id = a_stats[1] or 0
            except Exception:
                pass

            # 3. Alerts
            try:
                from app.models.alert import Alert
                al_stats = session.query(
                    func.count(Alert.id),
                    func.max(Alert.id)
                ).filter(Alert.user_id == user_id).first()
                if al_stats:
                    alert_count = al_stats[0] or 0
                    latest_alert_id = al_stats[1] or 0
            except Exception:
                pass

        raw_key = (
            f"u:{user_id}|t:{trade_count}:{latest_trade_id}|"
            f"a:{attempt_count}:{latest_attempt_id}|"
            f"al:{alert_count}:{latest_alert_id}"
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    except Exception as exc:
        logger.warning("fingerprint calculation failed for user %s: %s", user_id, exc)
        return f"fallback_fp_{user_id}"


def build_profile(user_id: int) -> Dict[str, Any]:
    """Builds a complete, privacy-compliant user profile from database records.
    
    Contains 6 sections:
    (1) coverage & sample flags
    (2) performance: all-time vs latest window vs prior window
    (3) habits relative to user's OWN medians
    (4) scenario behaviour
    (5) repeated mistakes linked to knowledge file IDs
    (6) trend vs previous_profile
    
    Never stores free-text user content. Never raises.
    """
    min_sample = getattr(cfg, "COACH_MIN_SAMPLE_SIZE", 5)
    window_n = getattr(cfg, "COACH_TRADE_WINDOW_N", 20)

    # Initialize empty profile structure
    profile: Dict[str, Any] = {
        "coverage": {
            "trades_count": 0,
            "closed_trades_count": 0,
            "scenario_decisions_count": 0,
            "sessions_count": 0,
            "first_activity": None,
            "last_activity": None,
            "sample_size_flag": "early sign",
            "scenario_sample_size_flag": "early sign"
        },
        "performance": {
            "all_time": build_trade_facts([]),
            "latest_window": build_trade_facts([]),
            "prior_window": build_trade_facts([])
        },
        "habits": {
            "user_median_size": 0.0,
            "size_after_loss_vs_normal": 1.0,
            "user_median_hold_winners_mins": 0.0,
            "user_median_hold_losers_mins": 0.0,
            "hold_time_winners_vs_losers": 1.0,
            "trades_per_day": 0.0,
            "worst_time_of_day": None,
            "stop_loss_usage_pct": 0.0,
            "rule_adherence_rate_pct": 100.0,
            "loss_streak_behavior": {
                "trades_after_streak": 0,
                "streak_size_ratio": 1.0
            }
        },
        "scenario_behavior": {
            "by_action": {},
            "by_reason": {},
            "revisions_count": 0,
            "revisions_improved_share": 0.0,
            "closest_bot": None
        },
        "repeated_mistakes": [],
        "trend": None
    }

    try:
        with get_readonly_session() as session:
            # ---------------------------------------------------------------
            # 1. Trades & Orders
            # ---------------------------------------------------------------
            trades = []
            orders = []
            try:
                from app.models.paper import Trade, Order
                trades = (
                    session.query(Trade)
                    .filter(Trade.user_id == user_id)
                    .order_by(Trade.executed_at.asc(), Trade.id.asc())
                    .all()
                )
                orders = (
                    session.query(Order)
                    .filter(Order.user_id == user_id)
                    .all()
                )
            except Exception as e_tr:
                logger.debug("Trades/Orders read error for user %s: %s", user_id, e_tr)

            # ---------------------------------------------------------------
            # 2. Scenario Attempts & Decisions
            # ---------------------------------------------------------------
            attempts = []
            scenarios = []
            bot_decisions = []
            try:
                from app.models.decision import Attempt, BotDecision
                from app.models.scenario import Scenario
                attempts = (
                    session.query(Attempt)
                    .filter(Attempt.user_id == user_id)
                    .order_by(Attempt.created_at.asc())
                    .all()
                )
                scenario_ids = list({a.scenario_id for a in attempts})
                if scenario_ids:
                    scenarios = (
                        session.query(Scenario)
                        .filter(Scenario.id.in_(scenario_ids))
                        .all()
                    )
                    bot_decisions = (
                        session.query(BotDecision)
                        .filter(BotDecision.scenario_id.in_(scenario_ids))
                        .all()
                    )
            except Exception as e_att:
                logger.debug("Scenario read error for user %s: %s", user_id, e_att)

            # ---------------------------------------------------------------
            # 3. Alerts & Rules
            # ---------------------------------------------------------------
            alerts = []
            try:
                from app.models.alert import Alert
                alerts = (
                    session.query(Alert)
                    .filter(Alert.user_id == user_id)
                    .order_by(Alert.created_at.asc())
                    .all()
                )
            except Exception as e_al:
                logger.debug("Alerts read error for user %s: %s", user_id, e_al)

            # -------------------------------------------------------------------
            # Process Coverage Section
            # -------------------------------------------------------------------
            total_trades = len(trades)
            closed_trades = [
                t for t in trades
                if getattr(t, "realized_pnl", 0.0) != 0.0 or getattr(t, "net_realized_pnl", 0.0) != 0.0 or t.side == "SELL"
            ]
            closed_count = len(closed_trades)
            attempts_count = len(attempts)

            active_dates = set()
            activity_timestamps = []
            for t in trades:
                if t.executed_at:
                    active_dates.add(t.executed_at.date().isoformat())
                    activity_timestamps.append(t.executed_at)
            for a in attempts:
                if a.created_at:
                    active_dates.add(a.created_at.date().isoformat())
                    activity_timestamps.append(a.created_at)

            first_act = min(activity_timestamps).isoformat() if activity_timestamps else None
            last_act = max(activity_timestamps).isoformat() if activity_timestamps else None

            profile["coverage"] = {
                "trades_count": total_trades,
                "closed_trades_count": closed_count,
                "scenario_decisions_count": attempts_count,
                "sessions_count": len(active_dates),
                "first_activity": first_act,
                "last_activity": last_act,
                "sample_size_flag": "adequate" if closed_count >= min_sample else "early sign",
                "scenario_sample_size_flag": "adequate" if attempts_count >= min_sample else "early sign"
            }

            # -------------------------------------------------------------------
            # Process Performance Section (build_trade_facts)
            # -------------------------------------------------------------------
            closed_dicts = [t.to_dict() for t in closed_trades]
            # Most recent trades first for windows
            rev_closed = list(reversed(closed_dicts))
            profile["performance"]["all_time"] = build_trade_facts(closed_dicts)
            profile["performance"]["latest_window"] = build_trade_facts(rev_closed[:window_n])
            profile["performance"]["prior_window"] = build_trade_facts(rev_closed[window_n:2 * window_n])

            # -------------------------------------------------------------------
            # Process Habits Section
            # -------------------------------------------------------------------
            quantities = [t.quantity for t in trades if getattr(t, "quantity", None) is not None]
            median_size = round(statistics.median(quantities), 2) if quantities else 0.0
            profile["habits"]["user_median_size"] = median_size

            # Hold times for winners vs losers
            winner_holds = []
            loser_holds = []
            sizes_after_loss = []
            consecutive_losses = 0
            streak_trades_sizes = []

            # Map buy entries for hold time calculation
            buy_entries = [t for t in trades if t.side == "BUY"]

            # Track hourly P&L for worst_time_of_day
            hourly_pnl = defaultdict(float)

            for i, ct in enumerate(closed_trades):
                pnl = float(
                    ct.net_realized_pnl
                    if getattr(ct, "net_realized_pnl", None) is not None
                    else ct.realized_pnl
                )
                # Find matching prior entry
                prior_entry = next(
                    (b for b in reversed(buy_entries) if b.symbol == ct.symbol and b.executed_at <= ct.executed_at and b.id != ct.id),
                    None
                )
                hold_mins = 0.0
                if prior_entry and ct.executed_at and prior_entry.executed_at:
                    hold_mins = max(0.0, (ct.executed_at - prior_entry.executed_at).total_seconds() / 60.0)

                if pnl > 0:
                    winner_holds.append(hold_mins)
                elif pnl < 0:
                    loser_holds.append(hold_mins)

                # Hour of day
                if ct.executed_at:
                    hour_key = f"{ct.executed_at.hour:02d}:00"
                    hourly_pnl[hour_key] += pnl

                # Consecutive loss streak and size after loss check
                if i > 0:
                    prev_ct = closed_trades[i - 1]
                    prev_pnl = float(
                        prev_ct.net_realized_pnl
                        if getattr(prev_ct, "net_realized_pnl", None) is not None
                        else prev_ct.realized_pnl
                    )
                    if prev_pnl < 0:
                        if ct.executed_at and prev_ct.executed_at:
                            gap_mins = (ct.executed_at - prev_ct.executed_at).total_seconds() / 60.0
                            if gap_mins <= getattr(cfg, "COACH_QUICK_REENTRY_MINS", 15):
                                sizes_after_loss.append(ct.quantity)

                    if prev_pnl < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= 2:
                            streak_trades_sizes.append(ct.quantity)
                    else:
                        consecutive_losses = 0

            med_win_hold = round(statistics.median(winner_holds), 1) if winner_holds else 0.0
            med_loss_hold = round(statistics.median(loser_holds), 1) if loser_holds else 0.0
            profile["habits"]["user_median_hold_winners_mins"] = med_win_hold
            profile["habits"]["user_median_hold_losers_mins"] = med_loss_hold
            if med_loss_hold > 0:
                profile["habits"]["hold_time_winners_vs_losers"] = round(med_win_hold / med_loss_hold, 2)

            if sizes_after_loss and median_size > 0:
                med_after_loss = statistics.median(sizes_after_loss)
                profile["habits"]["size_after_loss_vs_normal"] = round(med_after_loss / median_size, 2)

            days_count = max(len(active_dates), 1)
            profile["habits"]["trades_per_day"] = round(total_trades / days_count, 1)

            # Worst time of day
            if hourly_pnl:
                worst_h = min(hourly_pnl.items(), key=lambda kv: kv[1])
                if worst_h[1] < 0:
                    profile["habits"]["worst_time_of_day"] = worst_h[0]

            # Stop-loss usage %
            if orders:
                sl_orders = [o for o in orders if getattr(o, "stop_loss", None) is not None and o.stop_loss > 0]
                profile["habits"]["stop_loss_usage_pct"] = round((len(sl_orders) / len(orders)) * 100.0, 1)

            # Rule adherence rate %
            rule_violation_alerts = [
                a for a in alerts
                if any(k in (a.alert_type or "").upper() for k in ("RULE", "MAX", "EXCEEDED", "REVENGE", "OVERTRADING"))
            ]
            if total_trades > 0:
                viol_count = min(len(rule_violation_alerts), total_trades)
                adherence = max(0.0, round(((total_trades - viol_count) / total_trades) * 100.0, 1))
                profile["habits"]["rule_adherence_rate_pct"] = adherence

            # Loss streak behaviour
            streak_size_ratio = 1.0
            if streak_trades_sizes and median_size > 0:
                streak_size_ratio = round(statistics.median(streak_trades_sizes) / median_size, 2)
            profile["habits"]["loss_streak_behavior"] = {
                "trades_after_streak": len(streak_trades_sizes),
                "streak_size_ratio": streak_size_ratio
            }

            # -------------------------------------------------------------------
            # Process Scenario Behaviour Section
            # -------------------------------------------------------------------
            by_action = defaultdict(lambda: {"count": 0, "total_outcome": 0.0, "matching_rule_count": 0})
            by_reason = defaultdict(lambda: {"count": 0, "total_outcome": 0.0, "matching_rule_count": 0})

            revisions_count = 0
            revisions_improved = 0

            # Map first attempt by scenario_id
            first_attempts = {}
            for att in attempts:
                if att.attempt_no == 1:
                    first_attempts[att.scenario_id] = att

            scenario_map = {s.id: s for s in scenarios}
            for att in attempts:
                action_key = (att.action or "unknown").lower()
                reason_key = (att.reason_code or att.reason or "unknown").lower()

                # Outcome from scenario prices or attribute
                fake_outcome = 0.0
                if getattr(att, "outcome_pnl", None) is not None:
                    fake_outcome = float(att.outcome_pnl)
                else:
                    scn = scenario_map.get(att.scenario_id)
                    if scn and getattr(scn, "outcome_5m", None) is not None and getattr(scn, "current_price", None) is not None:
                        diff = float(scn.outcome_5m) - float(scn.current_price)
                        if action_key == "buy":
                            fake_outcome = diff * float(att.size or 1.0)
                        elif action_key in ("sell", "short"):
                            fake_outcome = -diff * float(att.size or 1.0)

                by_action[action_key]["count"] += 1
                by_action[action_key]["total_outcome"] += fake_outcome
                by_action[action_key]["matching_rule_count"] += 1

                by_reason[reason_key]["count"] += 1
                by_reason[reason_key]["total_outcome"] += fake_outcome
                by_reason[reason_key]["matching_rule_count"] += 1

                if att.attempt_no > 1:
                    revisions_count += 1
                    first_att = first_attempts.get(att.scenario_id)
                    if first_att:
                        first_outcome = getattr(first_att, "outcome_pnl", 0.0) or 0.0
                        if fake_outcome > first_outcome:
                            revisions_improved += 1

            action_summary = {}
            for act, data in by_action.items():
                cnt = data["count"]
                action_summary[act] = {
                    "count": cnt,
                    "avg_outcome": round(data["total_outcome"] / cnt, 2) if cnt > 0 else 0.0,
                    "matching_rule_share": round((data["matching_rule_count"] / cnt) * 100.0, 1) if cnt > 0 else 0.0
                }

            reason_summary = {}
            for rsn, data in by_reason.items():
                cnt = data["count"]
                reason_summary[rsn] = {
                    "count": cnt,
                    "avg_outcome": round(data["total_outcome"] / cnt, 2) if cnt > 0 else 0.0,
                    "matching_rule_share": round((data["matching_rule_count"] / cnt) * 100.0, 1) if cnt > 0 else 0.0
                }

            # Closest bot match
            bot_matches = defaultdict(int)
            bot_totals = defaultdict(int)
            for att in attempts:
                matched_bots = [b for b in bot_decisions if b.scenario_id == att.scenario_id]
                for b in matched_bots:
                    bot_totals[b.bot_name] += 1
                    if (b.action or "").lower() == (att.action or "").lower():
                        bot_matches[b.bot_name] += 1

            closest_bot = None
            if bot_totals:
                bot_scores = {b: (bot_matches[b] / bot_totals[b]) for b in bot_totals if bot_totals[b] > 0}
                if bot_scores:
                    best_match = max(bot_scores.items(), key=lambda kv: kv[1])
                    closest_bot = {
                        "name": best_match[0],
                        "agreement_pct": round(best_match[1] * 100.0, 1)
                    }

            profile["scenario_behavior"] = {
                "by_action": action_summary,
                "by_reason": reason_summary,
                "revisions_count": revisions_count,
                "revisions_improved_share": round((revisions_improved / revisions_count) * 100.0, 1) if revisions_count > 0 else 0.0,
                "closest_bot": closest_bot
            }

            # -------------------------------------------------------------------
            # Process Repeated Mistakes Section
            # -------------------------------------------------------------------
            mistake_map = defaultdict(lambda: {"count": 0, "last_timestamp": None, "explanation": ""})
            for a in alerts:
                atype = (a.alert_type or "").upper()
                m_id = None
                if "REVENGE" in atype:
                    m_id = "revenge_trading"
                elif "OVERTRADING" in atype:
                    m_id = "overtrading"
                elif "STOP_LOSS" in atype:
                    m_id = "stop_loss_discipline"
                elif "MAX_DAILY_LOSS" in atype or "DRAWDOWN" in atype:
                    m_id = "daily_loss_limit"

                if m_id:
                    mistake_map[m_id]["count"] += 1
                    t_str = a.created_at.isoformat() if a.created_at else None
                    mistake_map[m_id]["last_timestamp"] = t_str
                    if a.message:
                        mistake_map[m_id]["explanation"] = a.message

            repeated_mistakes = []
            for m_id, m_info in mistake_map.items():
                repeated_mistakes.append({
                    "mistake_id": m_id,
                    "knowledge_file_id": m_id,
                    "count": m_info["count"],
                    "last_timestamp": m_info["last_timestamp"],
                    "explanation": m_info["explanation"]
                })
            repeated_mistakes.sort(key=lambda x: x["count"], reverse=True)
            profile["repeated_mistakes"] = repeated_mistakes

    except Exception as exc:
        logger.warning("build_profile calculation error for user %s: %s", user_id, exc)

    return profile


def ensure_fresh_profile(user_id: int) -> Dict[str, Any]:
    """Ensures profile is fresh according to user's activity fingerprint.
    
    Locks per-user with ~4s timeout. Stale profile returned if lock times out.
    Saves previous_profile upon updating.
    Never raises.
    """
    init_db()
    current_fp = fingerprint(user_id)

    # 1. Quick check without lock
    db = get_db_session()
    stale_profile = None
    try:
        existing_row = db.query(ChatUserProfile).filter(ChatUserProfile.user_id == user_id).first()
        if existing_row:
            stale_profile = existing_row.profile or {}
            if existing_row.fingerprint == current_fp:
                return stale_profile
    except Exception as exc:
        logger.warning("ensure_fresh_profile read error for user %s: %s", user_id, exc)
    finally:
        db.close()

    # 2. Acquire per-user lock with ~4s timeout
    user_lock = _get_user_lock(user_id)
    lock_timeout = getattr(cfg, "COACH_LOCK_TIMEOUT_SECONDS", 4.0)
    acquired = user_lock.acquire(timeout=lock_timeout)
    if not acquired:
        logger.warning("Profile lock timeout (%.1fs) for user %s, returning stale profile.", lock_timeout, user_id)
        return (stale_profile if stale_profile is not None else build_profile(user_id))

    try:
        # Re-check under lock
        db = get_db_session()
        try:
            row = db.query(ChatUserProfile).filter(ChatUserProfile.user_id == user_id).first()
            if row and row.fingerprint == current_fp:
                return row.profile or {}

            # Build fresh profile
            new_prof = build_profile(user_id)

            # Trend vs previous_profile
            prev_prof = row.profile if row and row.profile else None
            min_sample = getattr(cfg, "COACH_MIN_SAMPLE_SIZE", 5)
            trend_data = None
            if prev_prof:
                prev_cov = prev_prof.get("coverage", {}).get("closed_trades_count", 0)
                curr_cov = new_prof.get("coverage", {}).get("closed_trades_count", 0)
                if prev_cov >= min_sample and curr_cov >= min_sample:
                    curr_perf = new_prof.get("performance", {}).get("all_time", {})
                    prev_perf = prev_prof.get("performance", {}).get("all_time", {})
                    wr_delta = round(curr_perf.get("win_rate_pct", 0.0) - prev_perf.get("win_rate_pct", 0.0), 2)
                    net_delta = round(curr_perf.get("net", 0.0) - prev_perf.get("net", 0.0), 2)
                    adh_delta = round(
                        new_prof.get("habits", {}).get("rule_adherence_rate_pct", 100.0)
                        - prev_prof.get("habits", {}).get("rule_adherence_rate_pct", 100.0),
                        1
                    )
                    trend_status = "stable"
                    if wr_delta > 5.0 or net_delta > 0:
                        trend_status = "improving"
                    elif wr_delta < -5.0 or net_delta < 0:
                        trend_status = "declining"

                    trend_data = {
                        "win_rate_delta": wr_delta,
                        "net_delta": net_delta,
                        "rule_adherence_delta": adh_delta,
                        "status": trend_status
                    }
            new_prof["trend"] = trend_data

            # Upsert into chat_user_profile
            if row:
                row.previous_profile = row.profile
                row.profile = new_prof
                row.fingerprint = current_fp
                row.updated_at = datetime.now(timezone.utc)
            else:
                row = ChatUserProfile(
                    user_id=user_id,
                    profile=new_prof,
                    previous_profile=None,
                    fingerprint=current_fp,
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(row)
            db.commit()
            return new_prof
        except Exception as write_err:
            db.rollback()
            logger.warning("ensure_fresh_profile write error for user %s: %s", user_id, write_err)
            return (row.profile if row else build_profile(user_id))
        finally:
            db.close()
    finally:
        user_lock.release()


def get_profile_summary(user_id: int, focus: Optional[str] = None) -> str:
    """Builds a compact summary (~600 tokens) of user's profile for LLM prompt context."""
    try:
        prof = ensure_fresh_profile(user_id)
        cov = prof.get("coverage", {})
        perf = prof.get("performance", {}).get("all_time", {})
        habits = prof.get("habits", {})
        mistakes = prof.get("repeated_mistakes", [])
        scenarios = prof.get("scenario_behavior", {})
        trend = prof.get("trend")

        lines = [
            f"User Practice Profile Summary (Sample Flag: {cov.get('sample_size_flag', 'early sign')}):",
            f"- Total Closed Trades: {cov.get('closed_trades_count', 0)}, Sessions: {cov.get('sessions_count', 0)}",
            f"- All-Time Performance: Win Rate {perf.get('win_rate_pct', 0.0)}%, Net ₹{perf.get('net', 0.0):,.2f}, Expectancy ₹{perf.get('expectancy', 0.0):,.2f}, Break-Even {perf.get('breakeven_win_rate_pct', 0.0)}%",
            f"- Habit Benchmarks: Median Size {habits.get('user_median_size', 0.0)}, Post-Loss Size Multiplier {habits.get('size_after_loss_vs_normal', 1.0)}x, Stop-Loss Usage {habits.get('stop_loss_usage_pct', 0.0)}%, Rule Adherence {habits.get('rule_adherence_rate_pct', 100.0)}%",
            f"- Hold Times: Winners {habits.get('user_median_hold_winners_mins', 0.0)} mins vs Losers {habits.get('user_median_hold_losers_mins', 0.0)} mins"
        ]

        if mistakes:
            top_m = [f"{m['mistake_id']} (x{m['count']})" for m in mistakes[:2]]
            lines.append(f"- Top Repeated Habits: {', '.join(top_m)}")

        if scenarios.get("by_action"):
            lines.append(f"- Scenario Practice: {cov.get('scenario_decisions_count', 0)} attempts across {len(scenarios['by_action'])} action types. Revisions: {scenarios.get('revisions_count', 0)}")
            if scenarios.get("closest_bot"):
                bot = scenarios["closest_bot"]
                lines.append(f"- Closest Bot Archetype: {bot.get('name')} ({bot.get('agreement_pct')}%)")

        if trend:
            lines.append(f"- Trend vs Prior Window: {trend.get('status')} (Win rate delta: {trend.get('win_rate_delta')}%, Net delta: ₹{trend.get('net_delta', 0.0):,.2f})")

        if focus == "LAST_TRADE":
            lines.append("- Context Focus: Explaining the most recent trade against user's median size and hold habits.")
        elif focus == "SCENARIO":
            lines.append("- Context Focus: Reviewing simulation decisions and reason-outcome alignments.")
        elif focus == "PROFILE":
            lines.append("- Context Focus: Emphasizing strengths, top repeated habits, and one practice focus.")

        return "\n".join(lines)
    except Exception as exc:
        logger.warning("get_profile_summary failed for user %s: %s", user_id, exc)
        return "User Profile: Early signs (insufficient trade history)."
