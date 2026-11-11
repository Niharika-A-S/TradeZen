"""Rule Engine for TradeZen.

Provides:
1. Pre-trade check: warnings before order fill.
2. Post-trade detectors (separate, testable functions):
   - detect_rule_violations (risk %, stop loss, max trades, max loss)
   - detect_overtrading_after_loss (>=2 losses and >=5 trades in last 30 mins)
   - detect_revenge_trading (trade with >1.5x size within 10 mins of >2% loss)
   - detect_late_breakout_chase (BUY after 14:30 with 30-min price change >= +4%)
3. Alert persistence to database and WebSocket broadcast.
"""
from datetime import datetime, time, timedelta, timezone
import logging
from typing import List, Dict, Any, Optional, Union
import asyncio

from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func

from app.models.alert import Alert, AlertSeverity, AlertType
from app.models.paper import Order, Trade, Account, OrderSide, OrderType
from app.models.user import UserProfile
from app.models.price_bar import PriceBar
from app.clock.market_clock import MarketClock, get_bar

logger = logging.getLogger(__name__)


def calculate_risk(entry_price: float, stop_loss: Optional[float], quantity: int) -> float:
    """Calculates risk per trade in INR: abs(entry_price - stop_loss) * quantity."""
    if stop_loss is None or stop_loss <= 0:
        return 0.0
    return abs(entry_price - stop_loss) * quantity


def calculate_risk_pct(entry_price: float, stop_loss: Optional[float], quantity: int, capital: float) -> float:
    """Calculates risk per trade as a percentage of capital: (risk_in_inr / capital) * 100."""
    if capital <= 0:
        return 0.0
    risk_inr = calculate_risk(entry_price, stop_loss, quantity)
    return (risk_inr / capital) * 100.0


# ---------------------------------------------------------------------------
# 1. Pre-Trade Check
# ---------------------------------------------------------------------------

def pre_trade_check(
    user_id: int,
    symbol: str,
    side: str,
    quantity: int,
    entry_price: float,
    stop_loss: Optional[float],
    user_profile: Optional[UserProfile],
    account: Optional[Account],
    db: Session,
    clock: Optional[MarketClock] = None
) -> List[Dict[str, Any]]:
    """Evaluates proposed order against trading rules before fill, returning any warnings."""
    warnings = []
    if user_profile is None or not user_profile.rules_json:
        return warnings

    rules = user_profile.rules_json
    capital = account.initial_cash if (account and account.initial_cash) else (account.cash_balance if account else 10_00_000.0)

    # Rule: Require stop-loss
    if rules.get("require_stop_loss", False) and (stop_loss is None or stop_loss <= 0):
        warnings.append({
            "rule": "require_stop_loss",
            "severity": AlertSeverity.WARNING.value,
            "message": "Your trading rules require a stop-loss on every order."
        })

    # Rule: Max risk per trade %
    max_risk_pct = rules.get("max_risk_per_trade_pct")
    if max_risk_pct is not None and stop_loss is not None and stop_loss > 0:
        risk_inr = calculate_risk(entry_price, stop_loss, quantity)
        risk_pct = calculate_risk_pct(entry_price, stop_loss, quantity, capital)
        max_allowed_risk = capital * (max_risk_pct / 100.0)

        if risk_pct > max_risk_pct:
            warnings.append({
                "rule": "max_risk_per_trade_pct",
                "severity": AlertSeverity.WARNING.value,
                "message": (
                    f"Proposed trade risks {risk_pct:.2f}% (Rs {risk_inr:,.2f}), "
                    f"exceeding your rule limit of {max_risk_pct:.2f}% (Rs {max_allowed_risk:,.2f})."
                ),
                "risk_inr": round(risk_inr, 2),
                "risk_pct": round(risk_pct, 2),
                "max_allowed_risk": round(max_allowed_risk, 2)
            })

    # Rule: Max trades per day
    max_trades = rules.get("max_trades_per_day")
    if max_trades is not None:
        ref_dt = clock.current_time if clock else datetime.now(timezone.utc)
        today_date = ref_dt.date()
        today_start = datetime.combine(today_date, time.min)
        today_end = datetime.combine(today_date, time.max)
        today_count = db.query(func.count(Trade.id)).filter(
            Trade.user_id == user_id,
            Trade.executed_at >= today_start,
            Trade.executed_at <= today_end
        ).scalar()
        if today_count >= max_trades:
            warnings.append({
                "rule": "max_trades_per_day",
                "severity": AlertSeverity.WARNING.value,
                "message": f"Daily trade limit of {max_trades} reached ({today_count} executed for this session date)."
            })

    return warnings


# ---------------------------------------------------------------------------
# 2. Post-Trade Detectors (Separate, Testable Functions)
# ---------------------------------------------------------------------------

def detect_rule_violations(
    trade: Trade,
    order: Optional[Order],
    user_profile: Optional[UserProfile],
    capital: float,
    today_trades: Optional[List[Trade]] = None
) -> List[Dict[str, Any]]:
    """Detector for user-configured rules:
    - max_risk_per_trade_pct
    - require_stop_loss
    - max_trades_per_day
    - max_consecutive_losses
    """
    alerts = []
    if user_profile is None or not user_profile.rules_json:
        return alerts

    rules = user_profile.rules_json

    # 1. Check max_risk_per_trade_pct
    max_risk_pct = rules.get("max_risk_per_trade_pct")
    stop_loss = order.stop_loss if order else None
    if max_risk_pct is not None and stop_loss is not None and stop_loss > 0:
        risk_inr = calculate_risk(trade.price, stop_loss, trade.quantity)
        risk_pct = calculate_risk_pct(trade.price, stop_loss, trade.quantity, capital)
        max_allowed_risk = capital * (max_risk_pct / 100.0)

        if risk_pct > max_risk_pct:
            alerts.append({
                "alert_type": AlertType.MAX_RISK_EXCEEDED.value,
                "severity": AlertSeverity.CRITICAL.value,
                "message": (
                    f"Risk rule violated: Trade risked {risk_pct:.2f}% (Rs {risk_inr:,.2f}) "
                    f"against capital Rs {capital:,.2f} (Limit: {max_risk_pct:.2f}% / Rs {max_allowed_risk:,.2f})."
                ),
                "context_json": {
                    "rule": "max_risk_per_trade_pct",
                    "trade_id": trade.id,
                    "order_id": order.id if order else None,
                    "symbol": trade.symbol,
                    "entry_price": trade.price,
                    "stop_loss": stop_loss,
                    "quantity": trade.quantity,
                    "risk_inr": round(risk_inr, 2),
                    "risk_pct": round(risk_pct, 2),
                    "capital": round(capital, 2),
                    "limit_pct": max_risk_pct,
                    "max_allowed_risk": round(max_allowed_risk, 2)
                }
            })

    # 2. Check require_stop_loss
    if rules.get("require_stop_loss", False) and (stop_loss is None or stop_loss <= 0):
        alerts.append({
            "alert_type": AlertType.REQUIRE_STOP_LOSS.value,
            "severity": AlertSeverity.WARNING.value,
            "message": f"Stop-loss rule violated: Trade on {trade.symbol} executed without a defined stop-loss.",
            "context_json": {
                "rule": "require_stop_loss",
                "trade_id": trade.id,
                "symbol": trade.symbol
            }
        })

    # 3. Check max_trades_per_day
    max_trades = rules.get("max_trades_per_day")
    if max_trades is not None and today_trades is not None:
        if len(today_trades) > max_trades:
            alerts.append({
                "alert_type": AlertType.MAX_TRADES_EXCEEDED.value,
                "severity": AlertSeverity.WARNING.value,
                "message": f"Daily trade limit exceeded: {len(today_trades)} trades executed today (Limit: {max_trades}).",
                "context_json": {
                    "rule": "max_trades_per_day",
                    "trade_id": trade.id,
                    "today_trade_count": len(today_trades),
                    "limit": max_trades
                }
            })

    # 4. Check max_consecutive_losses
    max_cons_losses = rules.get("max_consecutive_losses")
    if max_cons_losses is not None and today_trades:
        cons_losses = 0
        for t in reversed(today_trades):
            if t.realized_pnl < 0:
                cons_losses += 1
            elif t.realized_pnl > 0:
                break
        if cons_losses >= max_cons_losses:
            alerts.append({
                "alert_type": AlertType.RULE_VIOLATION.value,
                "severity": AlertSeverity.WARNING.value,
                "message": f"Consecutive loss limit reached: {cons_losses} consecutive losing trades today.",
                "context_json": {
                    "rule": "max_consecutive_losses",
                    "consecutive_losses": cons_losses,
                    "limit": max_cons_losses
                }
            })

    return alerts


def detect_overtrading_after_loss(
    trades: List[Trade],
    window_minutes: int = 30,
    min_losses: int = 2,
    min_trades: int = 5,
    reference_time: Optional[datetime] = None
) -> Optional[Dict[str, Any]]:
    """Detector for OVERTRADING_AFTER_LOSS:
    Triggered when >= 2 losing trades and >= 5 total trades occur within the last 30 minutes.
    """
    if not trades or len(trades) < min_trades:
        return None

    ref_time = reference_time or trades[-1].executed_at
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)

    window_start = ref_time - timedelta(minutes=window_minutes)

    # Filter trades in the rolling 30-minute window
    window_trades = []
    for t in trades:
        t_time = t.executed_at
        if t_time.tzinfo is None:
            t_time = t_time.replace(tzinfo=timezone.utc)
        if window_start <= t_time <= ref_time:
            window_trades.append(t)

    if len(window_trades) < min_trades:
        return None

    losing_trades = [t for t in window_trades if t.realized_pnl < 0]
    if len(losing_trades) >= min_losses:
        return {
            "alert_type": AlertType.OVERTRADING_AFTER_LOSS.value,
            "severity": AlertSeverity.CRITICAL.value,
            "message": (
                f"OVERTRADING AFTER LOSS DETECTED: {len(window_trades)} trades executed in the last "
                f"{window_minutes} minutes, including {len(losing_trades)} losing trades. Step away from the screen."
            ),
            "context_json": {
                "window_minutes": window_minutes,
                "total_trades": len(window_trades),
                "losing_trades_count": len(losing_trades),
                "losing_trade_ids": [t.id for t in losing_trades],
                "all_window_trade_ids": [t.id for t in window_trades]
            }
        }
    return None


def detect_revenge_trading(
    current_trade: Trade,
    previous_trades: List[Trade],
    capital: float,
    window_minutes: int = 10,
    loss_threshold_pct: float = 2.0,
    size_multiplier: float = 1.5,
    current_order: Optional[Order] = None
) -> Optional[Dict[str, Any]]:
    """Detector for REVENGE_TRADING:
    Triggered when within 10 minutes of a loss greater than 2% of capital,
    a new trade is entered with bigger size (>1.5x previous size or bigger risk).
    """
    if not previous_trades or capital <= 0:
        return None

    curr_time = current_trade.executed_at
    if curr_time.tzinfo is None:
        curr_time = curr_time.replace(tzinfo=timezone.utc)

    window_start = curr_time - timedelta(minutes=window_minutes)
    loss_threshold_inr = capital * (loss_threshold_pct / 100.0)

    # Check for recent big losses
    for prev_trade in reversed(previous_trades):
        prev_time = prev_trade.executed_at
        if prev_time.tzinfo is None:
            prev_time = prev_time.replace(tzinfo=timezone.utc)

        if prev_time < window_start:
            break

        # Check if previous trade had loss > 2% capital
        if prev_trade.realized_pnl < 0 and abs(prev_trade.realized_pnl) >= loss_threshold_inr:
            loss_pct = (abs(prev_trade.realized_pnl) / capital) * 100.0

            # Condition: Bigger size (>1.5x) or bigger risk
            size_increased = current_trade.quantity > (prev_trade.quantity * size_multiplier)

            current_risk = calculate_risk(current_trade.price, current_order.stop_loss if current_order else None, current_trade.quantity)
            prev_risk = abs(prev_trade.realized_pnl)
            risk_increased = current_risk > (prev_risk * size_multiplier)

            if size_increased or risk_increased:
                return {
                    "alert_type": AlertType.REVENGE_TRADING.value,
                    "severity": AlertSeverity.CRITICAL.value,
                    "message": (
                        f"REVENGE TRADING DETECTED: Within {window_minutes} minutes of a {loss_pct:.2f}% loss "
                        f"(Rs {abs(prev_trade.realized_pnl):,.2f}), new trade on {current_trade.symbol} "
                        f"was placed with {current_trade.quantity} qty (>1.5x previous size of {prev_trade.quantity})."
                    ),
                    "context_json": {
                        "triggering_loss_trade_id": prev_trade.id,
                        "loss_inr": round(abs(prev_trade.realized_pnl), 2),
                        "loss_pct": round(loss_pct, 2),
                        "previous_quantity": prev_trade.quantity,
                        "current_quantity": current_trade.quantity,
                        "current_trade_id": current_trade.id,
                        "window_minutes": window_minutes
                    }
                }

    return None


def detect_late_breakout_chase(
    symbol: str,
    side: str,
    current_time: datetime,
    db: Session,
    threshold_time: time = time(14, 30),
    min_surge_pct: float = 4.0
) -> Optional[Dict[str, Any]]:
    """Detector for LATE_BREAKOUT_CHASE:
    Triggered on BUY orders after 14:30 when 30-minute price change is >= +4%.
    """
    if side.upper() != OrderSide.BUY.value:
        return None

    # Check time >= 14:30
    if current_time.time() < threshold_time:
        return None

    sym = symbol.strip().upper()

    # Query current price bar
    cur_bar = get_bar(sym, current_time, session=db, allow_nearest=True)
    if not cur_bar:
        return None

    # Query bar 30 minutes ago
    past_time = current_time - timedelta(minutes=30)
    past_bar = get_bar(sym, past_time, session=db, allow_nearest=True)
    if not past_bar or past_bar.close <= 0:
        return None

    # Calculate 30-minute price surge %
    surge_pct = ((cur_bar.close - past_bar.close) / past_bar.close) * 100.0

    if surge_pct >= min_surge_pct:
        return {
            "alert_type": AlertType.LATE_BREAKOUT_CHASE.value,
            "severity": AlertSeverity.WARNING.value,
            "message": (
                f"LATE BREAKOUT CHASE DETECTED: BUY placed after 14:30 on {sym} following a "
                f"+{surge_pct:.2f}% price rise in the last 30 minutes (Rs {past_bar.close:.2f} -> Rs {cur_bar.close:.2f})."
            ),
            "context_json": {
                "symbol": sym,
                "current_time": current_time.strftime("%H:%M:%S"),
                "surge_pct": round(surge_pct, 2),
                "price_30_min_ago": round(past_bar.close, 2),
                "current_price": round(cur_bar.close, 2)
            }
        }

    return None


# ---------------------------------------------------------------------------
# 3. Post-Trade Alert Coordinator
# ---------------------------------------------------------------------------

def evaluate_and_persist_alerts(
    trade: Trade,
    order: Optional[Order],
    user_id: int,
    db: Session,
    clock: Optional[MarketClock] = None,
    capital_override: Optional[float] = None
) -> List[Alert]:
    """Runs all detectors for an executed trade, saves alerts to DB, and broadcasts via WebSocket."""
    user_profile = db.query(UserProfile).filter_by(user_id=user_id).first()
    account = db.query(Account).filter_by(user_id=user_id).first()

    if capital_override is not None:
        capital = capital_override
    elif account is not None and account.initial_cash:
        capital = account.initial_cash
    elif account is not None:
        capital = account.cash_balance
    else:
        capital = 10_00_000.0

    cur_time = clock.current_time if clock else trade.executed_at
    session_date = cur_time.date()
    day_start = datetime.combine(session_date, time.min)
    day_end = datetime.combine(session_date, time.max)

    # Fetch trades for this user on the current session date
    today_trades = db.query(Trade).filter(
        Trade.user_id == user_id,
        Trade.executed_at >= day_start,
        Trade.executed_at <= day_end
    ).order_by(Trade.executed_at.asc()).all()
    previous_trades = [t for t in today_trades if t.id != trade.id]

    candidate_alerts: List[Dict[str, Any]] = []

    # 1. Rule violations
    rule_alerts = detect_rule_violations(trade, order, user_profile, capital, today_trades)
    candidate_alerts.extend(rule_alerts)

    # 2. Overtrading after loss
    overtrading_alert = detect_overtrading_after_loss(today_trades, reference_time=cur_time)
    if overtrading_alert:
        candidate_alerts.append(overtrading_alert)

    # 3. Revenge trading
    revenge_alert = detect_revenge_trading(trade, previous_trades, capital, current_order=order)
    if revenge_alert:
        candidate_alerts.append(revenge_alert)

    # 4. Late breakout chase
    breakout_alert = detect_late_breakout_chase(trade.symbol, trade.side, cur_time, db)
    if breakout_alert:
        candidate_alerts.append(breakout_alert)

    # 5. Model risk prediction (Step 5)
    try:
        from app.ml.predictor import predict_violation_risk
        risk_res = predict_violation_risk(
            user_id=user_id,
            now=cur_time,
            db=db,
            create_alert=False,
            capital_override=capital
        )
        if risk_res.get("is_high_risk"):
            prob = risk_res["risk_score"]
            reasons = risk_res.get("reasons", [])
            reason_text = " | ".join(reasons)
            candidate_alerts.append({
                "alert_type": AlertType.MODEL_RISK.value,
                "severity": AlertSeverity.CRITICAL.value if prob >= 0.80 else AlertSeverity.WARNING.value,
                "message": f"MODEL RISK ALERT ({prob*100:.1f}% risk): Imminent behavioral violation predicted. Reasons: {reason_text}",
                "context_json": {
                    "risk_score": prob,
                    "threshold": risk_res.get("threshold", 0.50),
                    "reasons": reasons,
                    "features": risk_res.get("features", {}),
                    "evaluated_at": cur_time.isoformat()
                }
            })
    except Exception as e:
        logger.debug("Model risk prediction skipped: %s", e)

    persisted_alerts: List[Alert] = []
    for cand in candidate_alerts:
        alert = Alert(
            user_id=user_id,
            alert_type=cand["alert_type"],
            severity=cand["severity"],
            message=cand["message"],
            context_json=cand["context_json"],
            created_at=cur_time if cur_time.tzinfo else cur_time.replace(tzinfo=timezone.utc)
        )
        db.add(alert)
        persisted_alerts.append(alert)

    if persisted_alerts:
        db.commit()
        for a in persisted_alerts:
            db.refresh(a)

        # Broadcast via WebSocket if active event loop
        try:
            from app.api.websocket import alert_manager
            try:
                loop = asyncio.get_running_loop()
                for a in persisted_alerts:
                    loop.create_task(alert_manager.broadcast_alert(user_id, a.to_dict()))
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("WebSocket broadcast skipped or failed: %s", e)

    return persisted_alerts
