"""Model explainability module for TradeZen (Step 5 & Prompt A).

Provides explain(features, rules) to translate behavioral metrics into human-readable
coaching reasons citing the active user's actual configured limits.
"""
from typing import Dict, Any, List, Optional


def explain(features: Dict[str, Any], rules: Optional[Dict[str, Any]] = None, top_n: int = 3) -> List[str]:
    """Generates prioritized, human-readable explanations of why a trader is flagged as high-risk.

    Args:
        features: Dictionary of behavioral features computed by build_features(...).
        rules: Optional dictionary of active user trading rules.
        top_n: Maximum number of explanation strings to return.

    Returns:
        List of strings detailing the primary psychological risk factors.
    """
    reasons: List[str] = []

    safe_rules = rules or {}
    max_trades = max(int(safe_rules.get("max_trades_per_day") or 5), 1)
    max_risk = max(float(safe_rules.get("max_risk_per_trade_pct") or 2.0), 0.1)
    max_cons_losses = max(int(safe_rules.get("max_consecutive_losses") or 3), 1)

    trades_30m = features.get("trades_count_last_30m", 0)
    loss_30m = features.get("loss_count_last_30m", 0)
    trade_ratio = features.get("trade_count_ratio_today", 0.0)
    trade_headroom = features.get("trade_headroom_today", max_trades)
    had_large_loss = features.get("had_large_loss_last_10m", 0)
    size_ratio = features.get("size_ratio_to_daily_avg", 1.0)
    sl_missing = features.get("stop_loss_missing_count_last_30m", 0)
    max_risk_ratio = features.get("max_risk_ratio_last_30m", 0.0)
    cons_loss_ratio = features.get("consecutive_losses_ratio", 0.0)
    cons_loss_headroom = features.get("consecutive_losses_headroom", max_cons_losses)
    drawdown_pct = features.get("max_drawdown_pct_today", 0.0)
    late_flag = features.get("late_trading_flag", 0)

    # 1. Revenge trading pattern
    if had_large_loss and size_ratio > 1.3:
        reasons.append(
            f"Revenge sizing detected: Trade size expanded to {size_ratio:.1f}x daily average within 10 minutes of a >{max_risk:.1f}% loss."
        )
    elif had_large_loss:
        reasons.append(f"Recent severe loss: A >{max_risk:.1f}% capital loss occurred in the last 10 minutes.")

    # 2. Overtrading / Approaching trade limit
    if trade_ratio >= 0.8:
        reasons.append(
            f"Overtrading warning: Approaching daily trade limit of {max_trades} ({trade_ratio*100:.0f}% used, {trade_headroom} remaining)."
        )
    elif trades_30m >= 4 and loss_30m >= 2:
        reasons.append(
            f"Elevated trading pace following losses: {loss_30m} losses in the last 30 minutes across {trades_30m} trades."
        )

    # 3. Missing stop-loss
    if sl_missing > 0:
        reasons.append(
            f"Unprotected entry: {sl_missing} order(s) entered without a mandatory stop-loss in the last 30 minutes."
        )

    # 4. Excessive risk
    if max_risk_ratio >= 1.0:
        calc_risk = round(max_risk_ratio * max_risk, 1)
        reasons.append(
            f"Excessive risk: Order risk reached {calc_risk:.1f}% of capital (rule limit is {max_risk:.1f}%)."
        )

    # 5. Consecutive losing streak
    if cons_loss_ratio >= 1.0 or cons_loss_headroom == 0:
        reasons.append(
            f"Losing streak ceiling reached: Consecutive losses reached configured limit of {max_cons_losses}."
        )

    # 6. Sizing escalation
    if size_ratio >= 1.6 and not (had_large_loss and size_ratio > 1.3):
        reasons.append(
            f"Size escalation: Recent position size is {size_ratio:.1f}x above your daily average."
        )

    # 7. Intraday drawdown
    if drawdown_pct >= 3.0:
        reasons.append(
            f"Intraday drawdown alert: Account has experienced a {drawdown_pct:.1f}% drawdown from today's peak."
        )

    # 8. Late session trading
    if late_flag == 1 and trades_30m > 0:
        reasons.append(
            "Late session trading: Entering new positions after 14:30 increases vulnerability to closing volatility."
        )

    # Fallback if no specific condition matched
    if not reasons:
        reasons.append("Composite behavioral risk elevated based on recent trade pacing and capital exposure.")

    return reasons[:top_n]
