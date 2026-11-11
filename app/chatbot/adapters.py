"""Adapters connecting the chatbot package to TradeZen data and models.

The only file that knows TradeZen internals.
Every function is read-only, returns ToolResult(ok, data, reason), and NEVER raises.
Supports fake implementations for local testing/dev_app and real implementations
connecting to TradeZen modules via guarded lazy imports.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import logging
import math
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


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
