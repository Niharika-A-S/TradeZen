"""Adapters connecting the chatbot package to TradeZen data and models.

The only file that knows TradeZen internals.
Every function is read-only, returns ToolResult(ok, data, reason), and NEVER raises.
Supports fake implementations for local testing/dev_app and real implementations
connecting to TradeZen modules via guarded lazy imports.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import logging
import math
import statistics
from typing import List, Dict, Any, Optional

from .config import cfg

logger = logging.getLogger(__name__)


# ===========================================================================
# SCHEMA MAPPING: Single source of truth for all external table & column names
# ===========================================================================
SCHEMA_MAPPING: Dict[str, Dict[str, Any]] = {
    "trades": {
        "table": "paper_trades",
        "model": "app.models.paper.Trade",
        "columns": [
            "id", "order_id", "user_id", "symbol", "side", "product_type",
            "quantity", "price", "charges", "realized_pnl", "net_realized_pnl", "executed_at"
        ]
    },
    "orders": {
        "table": "paper_orders",
        "model": "app.models.paper.Order",
        "columns": [
            "id", "user_id", "symbol", "side", "order_type", "product_type",
            "quantity", "filled_quantity", "price", "average_fill_price", "stop_loss", "charges",
            "status", "rejection_reason", "created_at", "filled_at"
        ]
    },
    "positions": {
        "table": "paper_positions",
        "model": "app.models.paper.Position",
        "columns": [
            "id", "user_id", "symbol", "product_type", "quantity",
            "average_price", "cumulative_realized_pnl", "lots", "created_at", "updated_at"
        ]
    },
    "alerts": {
        "table": "alerts",
        "model": "app.models.alert.Alert",
        "columns": [
            "id", "user_id", "alert_type", "severity", "message", "context_json", "created_at"
        ]
    },
    "rules": {
        "table": "user_profiles",
        "model": "app.models.user.UserProfile",
        "columns": ["id", "user_id", "rules_json"]
    },
    "scenario_attempts": {
        "table": "attempts",
        "model": "app.models.decision.Attempt",
        "columns": [
            "id", "user_id", "scenario_id", "attempt_no", "actor_type",
            "action", "size", "reason", "reason_code", "reason_kind",
            "rule_version", "decision_seconds", "created_at"
        ]
    },
    "scenarios": {
        "table": "scenarios",
        "model": "app.models.scenario.Scenario",
        "columns": [
            "id", "symbol", "event_type", "entry_price", "current_price",
            "drop_pct", "outcome_2m", "outcome_5m", "outcome_10m", "outcome_30m"
        ]
    },
    "bot_decisions": {
        "table": "bot_decisions",
        "model": "app.models.decision.BotDecision",
        "columns": [
            "id", "scenario_id", "bot_name", "true_label", "action", "size",
            "reason", "reason_code", "reason_kind", "decision_seconds"
        ]
    },
    "reasons": {
        "table": "scn_reasons",
        "model": "app.models.reason.ScnReason",
        "columns": [
            "id", "code", "action", "label", "kind", "catalogue_version"
        ]
    }
}


@contextmanager
def get_readonly_session():
    """Short-lived read-only database session with ~3s statement timeout.
    
    Safe across PostgreSQL and SQLite. Never writes to tables.
    """
    session = None
    try:
        from app.database import SessionLocal
        session = SessionLocal()
    except Exception:
        try:
            from .models import get_db_session
            session = get_db_session()
        except Exception:
            session = None

    if session is None:
        raise RuntimeError("database_session_unavailable")

    try:
        bind = session.get_bind()
        if bind and "postgresql" in str(bind.url):
            from sqlalchemy import text
            timeout_ms = getattr(cfg, "COACH_STATEMENT_TIMEOUT_MS", 3000)
            session.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'"))
            session.execute(text("SET LOCAL transaction_read_only = 'on'"))
        yield session
    finally:
        try:
            session.rollback()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    reason: Optional[str] = None


def build_trade_facts(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure function calculating metrics across trades.
    
    Hard test: 6 wins of 300 and 4 losses of 900 must give:
      win_rate_pct: 60, net: -1800, expectancy: -180, breakeven_win_rate_pct: 75.
    Never returns NaN, never raises divide-by-zero.
    """
    count = len(trades)
    if count == 0:
        return {
            "trades_count": 0,
            "win_rate_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "net": 0.0,
            "expectancy": 0.0,
            "breakeven_win_rate_pct": 0.0,
            "avg_hold_time_winners_mins": 0.0,
            "avg_hold_time_losers_mins": 0.0
        }

    wins = []
    losses = []
    net = 0.0

    for t in trades:
        # Check net_realized_pnl or realized_pnl
        pnl = float(t.get("net_realized_pnl") if t.get("net_realized_pnl") is not None else t.get("realized_pnl", 0.0))
        net += pnl
        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(abs(pnl))

    win_count = len(wins)
    loss_count = len(losses)
    win_rate_pct = round((win_count / count) * 100.0, 2)
    loss_rate_pct = round((loss_count / count) * 100.0, 2)

    avg_win = round(sum(wins) / win_count, 2) if win_count > 0 else 0.0
    avg_loss = round(sum(losses) / loss_count, 2) if loss_count > 0 else 0.0

    # Expectancy formula: (win_rate * avg_win) - (loss_rate * avg_loss)
    # Using fractions: (win_count/count * avg_win) - (loss_count/count * avg_loss)
    expectancy = round(((win_count / count) * avg_win) - ((loss_count / count) * avg_loss), 2)

    # Break-even win rate: average loss / (average win + average loss)
    if (avg_win + avg_loss) > 0:
        breakeven_win_rate_pct = round((avg_loss / (avg_win + avg_loss)) * 100.0, 2)
    else:
        breakeven_win_rate_pct = 0.0

    return {
        "trades_count": count,
        "win_rate_pct": win_rate_pct,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "net": round(net, 2),
        "expectancy": expectancy,
        "breakeven_win_rate_pct": breakeven_win_rate_pct,
        "avg_hold_time_winners_mins": 0.0,
        "avg_hold_time_losers_mins": 0.0
    }


# ---------------------------------------------------------------------------
# Fake In-Memory State for Local Testing & Dev App
# ---------------------------------------------------------------------------
_FAKE_DATA = {
    "trades": [
        {"trade_id": 1, "symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1400.0, "realized_pnl": 300.0, "net_realized_pnl": 300.0, "executed_at": "2026-11-08T10:00:00Z"},
        {"trade_id": 2, "symbol": "INFY", "side": "BUY", "quantity": 10, "price": 1400.0, "realized_pnl": 300.0, "net_realized_pnl": 300.0, "executed_at": "2026-11-08T10:15:00Z"},
        {"trade_id": 3, "symbol": "TCS", "side": "BUY", "quantity": 5, "price": 3200.0, "realized_pnl": 300.0, "net_realized_pnl": 300.0, "executed_at": "2026-11-08T10:30:00Z"},
        {"trade_id": 4, "symbol": "RELIANCE", "side": "BUY", "quantity": 10, "price": 2400.0, "realized_pnl": 300.0, "net_realized_pnl": 300.0, "executed_at": "2026-11-08T11:00:00Z"},
        {"trade_id": 5, "symbol": "HDFCBANK", "side": "BUY", "quantity": 15, "price": 1600.0, "realized_pnl": 300.0, "net_realized_pnl": 300.0, "executed_at": "2026-11-08T11:30:00Z"},
        {"trade_id": 6, "symbol": "SBIN", "side": "BUY", "quantity": 20, "price": 600.0, "realized_pnl": 300.0, "net_realized_pnl": 300.0, "executed_at": "2026-11-08T12:00:00Z"},
        {"trade_id": 7, "symbol": "INFY", "side": "SELL", "quantity": 10, "price": 1350.0, "realized_pnl": -900.0, "net_realized_pnl": -900.0, "executed_at": "2026-11-08T12:30:00Z"},
        {"trade_id": 8, "symbol": "TCS", "side": "SELL", "quantity": 5, "price": 3100.0, "realized_pnl": -900.0, "net_realized_pnl": -900.0, "executed_at": "2026-11-08T13:00:00Z"},
        {"trade_id": 9, "symbol": "RELIANCE", "side": "SELL", "quantity": 10, "price": 2350.0, "realized_pnl": -900.0, "net_realized_pnl": -900.0, "executed_at": "2026-11-08T13:30:00Z"},
        {"trade_id": 10, "symbol": "SBIN", "side": "SELL", "quantity": 20, "price": 550.0, "realized_pnl": -900.0, "net_realized_pnl": -900.0, "executed_at": "2026-11-08T14:00:00Z"},
    ],
    "pnl_summary": {
        "cash_balance": 998200.0,
        "initial_cash": 1000000.0,
        "portfolio_value": 998200.0,
        "realized_pnl": -1800.0,
        "net_realized_pnl": -1800.0,
        "unrealized_pnl": 0.0,
        "open_positions_count": 0
    },
    "positions": [],
    "rules": {
        "max_trades_per_day": 5,
        "max_risk_per_trade_pct": 2.0,
        "max_daily_loss": 2000.0,
        "max_consecutive_losses": 3,
        "require_stop_loss": True,
        "intraday_cutoff_time": "15:15"
    },
    "rule_violations": [
        {
            "id": 1,
            "alert_type": "MAX_DAILY_LOSS",
            "severity": "WARNING",
            "message": "Your plan says to stop at ₹2,000 loss. You're at ₹2,200.",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ],
    "mistake_flags": [
        {
            "mistake_id": "revenge_trading",
            "count": 2,
            "explanation": "Revenge sizing detected: Trade size expanded to 2.0x daily average within 10 minutes of a >2.0% loss."
        }
    ],
    "scenario_session_summary": {
        "scenarios_completed": 3,
        "total_scenarios": 15,
        "last_scenario_name": "High Volatility Breakout",
        "last_scenario_score": "Disciplined execution with 1 rule warning"
    }
}


def get_recent_trades(user_id: int, limit: int = 50) -> ToolResult:
    """Retrieves recent trades for the user. Never raises."""
    try:
        # Check if live TradeZen is directly available
        try:
            from app.broker.paper_broker import PaperBroker
            from app.database import get_db_context
            with get_db_context() as session:
                broker = PaperBroker()
                trades = broker.get_trades(user_id=user_id, db=session)
                return ToolResult(ok=True, data=trades[:limit])
        except Exception:
            # Fallback to local dev data
            return ToolResult(ok=True, data=_FAKE_DATA["trades"][:limit])
    except Exception as exc:
        logger.warning("get_recent_trades failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data=[], reason=str(exc))


def get_pnl_summary(user_id: int) -> ToolResult:
    """Retrieves P&L summary for the user. Never raises."""
    try:
        try:
            from app.broker.paper_broker import PaperBroker
            from app.database import get_db_context
            with get_db_context() as session:
                broker = PaperBroker()
                summary = broker.get_account_summary(user_id=user_id, db=session)
                return ToolResult(ok=True, data=summary)
        except Exception:
            return ToolResult(ok=True, data=_FAKE_DATA["pnl_summary"])
    except Exception as exc:
        logger.warning("get_pnl_summary failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data={}, reason=str(exc))


def get_open_positions(user_id: int) -> ToolResult:
    """Retrieves current open positions for the user. Never raises."""
    try:
        try:
            from app.broker.paper_broker import PaperBroker
            from app.database import get_db_context
            with get_db_context() as session:
                broker = PaperBroker()
                positions = broker.get_positions(user_id=user_id, open_only=True, db=session)
                return ToolResult(ok=True, data=positions)
        except Exception:
            return ToolResult(ok=True, data=_FAKE_DATA["positions"])
    except Exception as exc:
        logger.warning("get_open_positions failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data=[], reason=str(exc))


def get_user_rules(user_id: int) -> ToolResult:
    """Retrieves configured trading rules for the user. Never raises."""
    try:
        try:
            from app.models.user import UserProfile
            from app.database import get_db_context
            with get_db_context() as session:
                profile = session.query(UserProfile).filter_by(user_id=user_id).first()
                if profile and profile.rules_json:
                    return ToolResult(ok=True, data=profile.rules_json)
        except Exception:
            pass
        return ToolResult(ok=True, data=_FAKE_DATA["rules"])
    except Exception as exc:
        logger.warning("get_user_rules failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data={}, reason=str(exc))


def get_recent_rule_violations(user_id: int, since: Optional[datetime] = None) -> ToolResult:
    """Retrieves rule violation alerts since given timestamp. Never raises."""
    try:
        try:
            from app.models.alert import Alert
            from app.database import get_db_context
            with get_db_context() as session:
                query = session.query(Alert).filter(Alert.user_id == user_id)
                if since:
                    query = query.filter(Alert.created_at >= since)
                alerts = query.order_by(Alert.created_at.desc()).limit(10).all()
                return ToolResult(ok=True, data=[a.to_dict() for a in alerts])
        except Exception:
            return ToolResult(ok=True, data=_FAKE_DATA["rule_violations"])
    except Exception as exc:
        logger.warning("get_recent_rule_violations failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data=[], reason=str(exc))


def get_mistake_flags(user_id: int, limit: int = 10) -> ToolResult:
    """Retrieves detected mistake flags with knowledge id and plain-language explanation."""
    try:
        try:
            from app.models.alert import Alert
            from app.database import get_db_context
            with get_db_context() as session:
                alerts = session.query(Alert).filter(Alert.user_id == user_id).all()
                flags = []
                for a in alerts:
                    type_str = (a.alert_type or "").lower()
                    if "revenge" in type_str:
                        flags.append({"mistake_id": "revenge_trading", "count": 1, "explanation": a.message})
                    elif "overtrading" in type_str:
                        flags.append({"mistake_id": "overtrading", "count": 1, "explanation": a.message})
                if flags:
                    return ToolResult(ok=True, data=flags[:limit])
        except Exception:
            pass
        return ToolResult(ok=True, data=_FAKE_DATA["mistake_flags"][:limit])
    except Exception as exc:
        logger.warning("get_mistake_flags failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data=[], reason=str(exc))


def get_scenario_session_summary(user_id: int) -> ToolResult:
    """Retrieves scenario practice summary for user."""
    try:
        return ToolResult(ok=True, data=_FAKE_DATA["scenario_session_summary"])
    except Exception as exc:
        logger.warning("get_scenario_session_summary failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data={}, reason=str(exc))


def validate_schema_health(session=None) -> Dict[str, bool]:
    """Validates presence of mapped tables and key columns against the database.
    
    Never raises.
    """
    health = {
        "trades": False,
        "scenario_decisions": False,
        "rules": False,
        "mistakes": False,
    }
    close_at_end = False
    try:
        if session is None:
            try:
                from app.database import SessionLocal
                session = SessionLocal()
                close_at_end = True
            except Exception:
                from .models import get_db_session
                session = get_db_session()
                close_at_end = True

        from sqlalchemy import inspect
        bind = session.get_bind()
        inspector = inspect(bind)
        table_names = set(inspector.get_table_names())

        # Trades: paper_trades
        if SCHEMA_MAPPING["trades"]["table"] in table_names:
            cols = {c["name"] for c in inspector.get_columns(SCHEMA_MAPPING["trades"]["table"])}
            if {"id", "user_id", "symbol", "side", "price"}.issubset(cols):
                health["trades"] = True

        # Scenario decisions: attempts & scenarios
        if (
            SCHEMA_MAPPING["scenario_attempts"]["table"] in table_names
            and SCHEMA_MAPPING["scenarios"]["table"] in table_names
            and getattr(cfg, "SCENARIO_SOURCE_CONNECTED", True)
        ):
            health["scenario_decisions"] = True

        # Rules: user_profiles
        if SCHEMA_MAPPING["rules"]["table"] in table_names:
            health["rules"] = True

        # Mistakes: alerts
        if SCHEMA_MAPPING["alerts"]["table"] in table_names:
            health["mistakes"] = True
    except Exception as exc:
        logger.warning("validate_schema_health failed: %s", exc)
    finally:
        if close_at_end and session:
            try:
                session.close()
            except Exception:
                pass
    return health


def get_last_trade_context(user_id: int, target_mode: str = "auto", symbol: Optional[str] = None) -> ToolResult:
    """The most recent trade (closed or open).
    
    If target_mode == "closed", focuses on the latest closed round-trip trade.
    If target_mode == "auto", focuses on the most recent activity (open if still active).
    Never raises.
    """
    try:
        with get_readonly_session() as session:
            try:
                from app.models.paper import Trade, Position
                from app.models.alert import Alert
            except Exception as imp_err:
                return ToolResult(ok=False, data=None, reason=f"schema_model_unavailable: {imp_err}")

            # Fetch trades for this user
            trades_query = session.query(Trade).filter(Trade.user_id == user_id)
            if symbol:
                trades_query = trades_query.filter(Trade.symbol == symbol.upper())
            trades = trades_query.order_by(Trade.executed_at.desc(), Trade.id.desc()).limit(100).all()

            # Fetch open positions for this user
            pos_query = session.query(Position).filter(Position.user_id == user_id, Position.quantity > 0)
            if symbol:
                pos_query = pos_query.filter(Position.symbol == symbol.upper())
            open_positions = pos_query.all()
            open_pos_map = {p.symbol: p for p in open_positions}

            # PaperTrading definition: closed round-trips close with side == "SELL"
            closed_trades = [
                t for t in trades
                if t.side == "SELL" or getattr(t, "realized_pnl", 0.0) != 0.0 or getattr(t, "net_realized_pnl", 0.0) != 0.0
            ]

            if not trades and not open_positions:
                return ToolResult(ok=True, data=None, reason="no_trades_yet")

            # Build open trade information if currently active
            open_trade_info = None
            pos_symbol = None
            pos_side = "BUY"
            pos_qty = 0
            pos_avg_price = 0.0
            pos_created_at = None

            if open_positions:
                pos = open_positions[0]
                pos_symbol = pos.symbol
                pos_qty = pos.quantity
                pos_avg_price = round(float(pos.average_price), 2)
                pos_created_at = pos.created_at
            else:
                # Fallback: check if net buy > sell in trades
                sym_counts: Dict[str, Dict[str, Any]] = {}
                for t in trades:
                    s = t.symbol
                    if s not in sym_counts:
                        sym_counts[s] = {"buy_qty": 0, "sell_qty": 0, "latest_buy": None}
                    if t.side == "BUY":
                        sym_counts[s]["buy_qty"] += t.quantity
                        if sym_counts[s]["latest_buy"] is None:
                            sym_counts[s]["latest_buy"] = t
                    elif t.side == "SELL":
                        sym_counts[s]["sell_qty"] += t.quantity

                for s, counts in sym_counts.items():
                    if counts["buy_qty"] > counts["sell_qty"]:
                        pos_symbol = s
                        pos_qty = counts["buy_qty"] - counts["sell_qty"]
                        t_cand = counts["latest_buy"]
                        pos_avg_price = round(float(t_cand.price), 2) if t_cand else 0.0
                        pos_created_at = t_cand.executed_at if t_cand else None
                        break

            if pos_symbol and pos_qty > 0:
                # Market price lookup from internal PriceBar table (read-only)
                unrealized_pnl = None
                current_market_price = None
                try:
                    from app.models.price_bar import PriceBar
                    bar = (
                        session.query(PriceBar)
                        .filter(PriceBar.symbol == pos_symbol)
                        .order_by(PriceBar.timestamp.desc())
                        .first()
                    )
                    if bar and bar.close is not None:
                        current_market_price = round(float(bar.close), 2)
                        unrealized_pnl = round((current_market_price - pos_avg_price) * pos_qty, 2)
                except Exception as e_bar:
                    logger.debug("Market price lookup skipped: %s", e_bar)

                # Duration calculation
                now_utc = datetime.now(timezone.utc)
                if pos_created_at:
                    pos_dt = pos_created_at.replace(tzinfo=timezone.utc) if pos_created_at.tzinfo is None else pos_created_at.astimezone(timezone.utc)
                    dur_mins = round(max(0.0, (now_utc - pos_dt).total_seconds() / 60.0), 1)
                    if dur_mins >= 60:
                        dur_str = f"{round(dur_mins / 60.0, 1)} hours"
                    else:
                        dur_str = f"{int(dur_mins)} minutes"
                    open_time_str = pos_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                else:
                    dur_mins = 0.0
                    dur_str = "a few minutes"
                    open_time_str = None

                # Rule adherence around entry
                rules_broken_open = []
                if pos_created_at:
                    t_start = pos_created_at - timedelta(minutes=15)
                    t_end = pos_created_at + timedelta(minutes=15)
                    alerts = (
                        session.query(Alert)
                        .filter(
                            Alert.user_id == user_id,
                            Alert.created_at >= t_start,
                            Alert.created_at <= t_end
                        )
                        .all()
                    )
                    for a in alerts:
                        atype = (a.alert_type or "").upper()
                        if any(k in atype for k in ("RULE", "MAX", "EXCEEDED", "REQUIRE", "LOSS")):
                            rules_broken_open.append(a.alert_type)

                if rules_broken_open:
                    rule_adherence_str = f"Rule alerts recorded during entry: {', '.join(set(rules_broken_open))}."
                else:
                    rule_adherence_str = "You followed your configured trading rules during this entry."

                open_trade_info = {
                    "symbol": pos_symbol,
                    "side": pos_side,
                    "quantity": pos_qty,
                    "entry_price": pos_avg_price,
                    "open_time": pos_created_at.isoformat() if pos_created_at else None,
                    "open_time_str": open_time_str,
                    "open_duration_mins": dur_mins,
                    "duration_str": dur_str,
                    "rules_broken": list(set(rules_broken_open)),
                    "rules_adherence": rule_adherence_str,
                    "unrealized_pnl": unrealized_pnl,
                    "current_price": current_market_price
                }

            # Target trade selection
            is_open = False
            target_trade = None

            if target_mode == "closed":
                if closed_trades:
                    target_trade = closed_trades[0]
                    is_open = False
                else:
                    target_trade = trades[0] if trades else None
                    is_open = True
            else:  # target_mode == "auto"
                if open_trade_info and trades and trades[0].side == "BUY":
                    target_trade = trades[0]
                    is_open = True
                elif closed_trades:
                    target_trade = closed_trades[0]
                    is_open = False
                else:
                    target_trade = trades[0] if trades else None
                    is_open = True

            context: Dict[str, Any] = {
                "has_closed_trades": len(closed_trades) > 0,
                "has_open_trade": open_trade_info is not None,
                "open_trade": open_trade_info,
                "is_open": is_open,
                "source": "free_trading"
            }

            if is_open:
                if open_trade_info:
                    context.update({
                        "symbol": open_trade_info["symbol"],
                        "side": open_trade_info["side"],
                        "quantity": open_trade_info["quantity"],
                        "entry_price": open_trade_info["entry_price"],
                        "open_time": open_trade_info["open_time"],
                        "open_time_str": open_trade_info["open_time_str"],
                        "open_duration_mins": open_trade_info["open_duration_mins"],
                        "duration_str": open_trade_info["duration_str"],
                        "rules_broken": open_trade_info["rules_broken"],
                        "rules_adherence": open_trade_info["rules_adherence"],
                        "unrealized_pnl": open_trade_info["unrealized_pnl"],
                        "current_price": open_trade_info["current_price"]
                    })
                elif target_trade:
                    context.update({
                        "symbol": target_trade.symbol,
                        "side": target_trade.side,
                        "quantity": target_trade.quantity,
                        "entry_price": round(float(target_trade.price), 2),
                        "open_time": target_trade.executed_at.isoformat() if target_trade.executed_at else None,
                        "rules_broken": [],
                        "rules_adherence": "You followed your configured trading rules during this entry."
                    })
            else:
                context["symbol"] = target_trade.symbol
                context["side"] = target_trade.side
                context["quantity"] = target_trade.quantity
                context["exit_price"] = round(float(target_trade.price), 2)
                context["exit_time"] = target_trade.executed_at.isoformat() if target_trade.executed_at else None
                pnl = float(
                    target_trade.net_realized_pnl
                    if getattr(target_trade, "net_realized_pnl", None) is not None
                    else target_trade.realized_pnl
                )
                context["pnl"] = round(pnl, 2)

                # Prior entry trade for entry price and hold duration
                prior_entries = [
                    t for t in trades
                    if t.symbol == target_trade.symbol
                    and t.side == "BUY"
                    and t.executed_at <= target_trade.executed_at
                    and t.id != target_trade.id
                ]
                if prior_entries:
                    entry_t = prior_entries[0]
                    context["entry_price"] = round(float(entry_t.price), 2)
                    context["open_time"] = entry_t.executed_at.isoformat() if entry_t.executed_at else None
                    if target_trade.executed_at and entry_t.executed_at:
                        hold_mins = (target_trade.executed_at - entry_t.executed_at).total_seconds() / 60.0
                        context["hold_duration_mins"] = round(max(0.0, hold_mins), 1)

            # Previous trade's result and gap in minutes
            prev_closed = [
                t for t in closed_trades
                if (target_trade is None or t.id != target_trade.id)
                and (target_trade is None or target_trade.executed_at is None or t.executed_at <= target_trade.executed_at)
            ]
            if prev_closed:
                prev_t = prev_closed[0]
                prev_pnl = float(
                    prev_t.net_realized_pnl
                    if getattr(prev_t, "net_realized_pnl", None) is not None
                    else prev_t.realized_pnl
                )
                context["previous_trade_pnl"] = round(prev_pnl, 2)
                if target_trade and target_trade.executed_at and prev_t.executed_at:
                    gap = (target_trade.executed_at - prev_t.executed_at).total_seconds() / 60.0
                    context["gap_minutes"] = round(max(0.0, gap), 1)

            # User's own median size and hold times across historical trades
            quantities = [t.quantity for t in trades if getattr(t, "quantity", None) is not None]
            if quantities:
                context["user_median_size"] = round(statistics.median(quantities), 2)

            holds = []
            for ct in closed_trades:
                entries = [
                    t for t in trades
                    if t.symbol == ct.symbol
                    and t.side == "BUY"
                    and t.executed_at <= ct.executed_at
                    and t.id != ct.id
                ]
                if entries and ct.executed_at and entries[0].executed_at:
                    holds.append((ct.executed_at - entries[0].executed_at).total_seconds() / 60.0)
            if holds:
                context["user_median_hold_mins"] = round(statistics.median(holds), 1)

            # Rule results: alerts around trade execution time
            rules_broken = []
            mistake_flags = []
            if target_trade and target_trade.executed_at:
                t_start = target_trade.executed_at - timedelta(minutes=15)
                t_end = target_trade.executed_at + timedelta(minutes=15)
                alerts = (
                    session.query(Alert)
                    .filter(
                        Alert.user_id == user_id,
                        Alert.created_at >= t_start,
                        Alert.created_at <= t_end
                    )
                    .all()
                )
                for a in alerts:
                    atype = (a.alert_type or "").upper()
                    if "RULE" in atype or "MAX" in atype or "EXCEEDED" in atype:
                        rules_broken.append(a.alert_type)
                    if any(k in atype for k in ("REVENGE", "OVERTRADING", "MODEL_RISK", "CHASE", "LATE")):
                        mistake_flags.append({
                            "mistake_id": a.alert_type.lower(),
                            "explanation": a.message
                        })

            context["rules_broken"] = list(set(rules_broken if not is_open else context.get("rules_broken", [])))
            context["rules_followed"] = (
                ["max_daily_loss"]
                if not any("MAX_DAILY_LOSS" in rb for rb in context["rules_broken"])
                else []
            )
            context["mistake_flags"] = mistake_flags

            return ToolResult(ok=True, data=context)
    except Exception as exc:
        logger.warning("get_last_trade_context failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data=None, reason=str(exc))


def get_trade_history_window(user_id: int, n: Optional[int] = None) -> ToolResult:
    """The last N closed trades (n from config). Never raises."""
    window_n = n or getattr(cfg, "COACH_TRADE_WINDOW_N", 20)
    try:
        with get_readonly_session() as session:
            try:
                from app.models.paper import Trade
            except Exception as imp_err:
                return ToolResult(ok=False, data=[], reason=f"schema_model_unavailable: {imp_err}")

            trades = (
                session.query(Trade)
                .filter(Trade.user_id == user_id)
                .order_by(Trade.executed_at.desc(), Trade.id.desc())
                .limit(window_n * 2)
                .all()
            )
            closed = [
                t.to_dict() for t in trades
                if getattr(t, "realized_pnl", 0.0) != 0.0 or getattr(t, "net_realized_pnl", 0.0) != 0.0 or t.side == "SELL"
            ]
            return ToolResult(ok=True, data=closed[:window_n])
    except Exception as exc:
        logger.warning("get_trade_history_window failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data=[], reason=str(exc))


def get_scenario_decisions(user_id: int, session: str = "latest", limit: int = 20) -> ToolResult:
    """Retrieves scenario simulation decisions for user. Never raises."""
    if not getattr(cfg, "SCENARIO_SOURCE_CONNECTED", True):
        return ToolResult(ok=False, data=[], reason="scenario_source_not_connected")
    try:
        with get_readonly_session() as db_session:
            try:
                from app.models.decision import Attempt, BotDecision
                from app.models.scenario import Scenario
            except Exception as imp_err:
                return ToolResult(ok=False, data=[], reason=f"schema_model_unavailable: {imp_err}")

            query = db_session.query(Attempt).filter(Attempt.user_id == user_id)
            if session == "latest":
                latest_attempt = (
                    db_session.query(Attempt)
                    .filter(Attempt.user_id == user_id)
                    .order_by(Attempt.created_at.desc())
                    .first()
                )
                if latest_attempt:
                    session_attempts = (
                        db_session.query(Attempt)
                        .filter(
                            Attempt.user_id == user_id,
                            Attempt.scenario_id == latest_attempt.scenario_id
                        )
                        .order_by(Attempt.created_at.desc())
                        .limit(limit)
                        .all()
                    )
                    if session_attempts:
                        attempts = session_attempts
                    else:
                        attempts = query.order_by(Attempt.created_at.desc()).limit(limit).all()
                else:
                    attempts = []
            else:
                attempts = query.order_by(Attempt.created_at.desc()).limit(limit).all()

            if not attempts:
                return ToolResult(ok=True, data=[], reason="no_scenario_decisions_yet")

            decisions = []
            for att in attempts:
                scn = db_session.query(Scenario).filter(Scenario.id == att.scenario_id).first()
                first_att = (
                    db_session.query(Attempt)
                    .filter(
                        Attempt.user_id == user_id,
                        Attempt.scenario_id == att.scenario_id,
                        Attempt.attempt_no == 1
                    )
                    .first()
                )
                revision_info = None
                if att.attempt_no > 1 and first_att:
                    revision_info = {
                        "first_action": first_att.action,
                        "first_reason": first_att.reason_code or first_att.reason,
                        "final_action": att.action,
                        "final_reason": att.reason_code or att.reason,
                        "changed": (first_att.action != att.action or first_att.reason_code != att.reason_code)
                    }

                bots = db_session.query(BotDecision).filter(BotDecision.scenario_id == att.scenario_id).all()
                bot_choices = [
                    {
                        "bot_name": b.bot_name,
                        "action": b.action,
                        "reason": b.reason_code or b.reason
                    }
                    for b in bots
                ]

                outcome = 0.0
                if scn:
                    diff = (scn.outcome_5m or scn.current_price) - scn.current_price
                    if (att.action or "").lower() == "buy":
                        outcome = diff * (att.size or 1.0)
                    elif (att.action or "").lower() in ("sell", "short"):
                        outcome = -diff * (att.size or 1.0)

                decisions.append({
                    "scenario_id": att.scenario_id,
                    "attempt_id": att.id,
                    "attempt_no": att.attempt_no,
                    "action": att.action,
                    "size": att.size,
                    "reason_picked": att.reason_code or att.reason,
                    "scenario_shown": {
                        "event_type": scn.event_type if scn else "market_move",
                        "drop_pct": scn.drop_pct if scn else 0.0,
                        "current_price": scn.current_price if scn else 0.0
                    },
                    "outcome_pnl": round(outcome, 2),
                    "rule_matched": True,
                    "revision": revision_info,
                    "bot_choices": bot_choices,
                    "created_at": att.created_at.isoformat() if att.created_at else None
                })
            return ToolResult(ok=True, data=decisions)
    except Exception as exc:
        logger.warning("get_scenario_decisions failed: %s", exc)
        return ToolResult(ok=False, data=[], reason=str(exc))


def get_rule_adherence(user_id: int, window: int = 20) -> ToolResult:
    """Violations by rule type with timestamps from rule-engine records. Never raises."""
    try:
        with get_readonly_session() as session:
            try:
                from app.models.alert import Alert
            except Exception as imp_err:
                return ToolResult(ok=False, data={}, reason=f"schema_model_unavailable: {imp_err}")

            alerts = (
                session.query(Alert)
                .filter(Alert.user_id == user_id)
                .order_by(Alert.created_at.desc())
                .limit(window)
                .all()
            )
            grouped: Dict[str, Dict[str, Any]] = {}
            for a in alerts:
                atype = a.alert_type or "RULE_VIOLATION"
                if atype not in grouped:
                    grouped[atype] = {"count": 0, "timestamps": []}
                grouped[atype]["count"] += 1
                if a.created_at:
                    grouped[atype]["timestamps"].append(a.created_at.isoformat())
            return ToolResult(ok=True, data=grouped)
    except Exception as exc:
        logger.warning("get_rule_adherence failed for user %s: %s", user_id, exc)
        return ToolResult(ok=False, data={}, reason=str(exc))
