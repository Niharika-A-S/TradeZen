"""Feature extraction module for TradeZen.

Provides build_features(...) to construct behavioral risk features for a 30-minute window
or arbitrary evaluation timestamp.
Used by the simulator in Step 4 and by predict_violation_risk in Step 5.
"""
from datetime import datetime, timedelta, time, timezone
from typing import List, Dict, Any, Optional, Union

from app.models.paper import Trade, Order
from app.rules.rule_engine import calculate_risk_pct

FEATURE_COLUMNS = [
    "trades_count_last_30m",
    "trade_count_ratio_today",
    "trade_headroom_today",
    "loss_count_last_30m",
    "win_count_last_30m",
    "consecutive_losses_ratio",
    "consecutive_losses_headroom",
    "win_rate_today",
    "pnl_last_30m",
    "total_pnl_today",
    "pnl_pct_capital_today",
    "max_drawdown_pct_today",
    "avg_trade_size_last_30m",
    "max_trade_size_last_30m",
    "size_ratio_to_daily_avg",
    "time_since_last_trade_min",
    "time_since_last_loss_min",
    "had_large_loss_last_10m",
    "stop_loss_missing_count_last_30m",
    "avg_risk_ratio_last_30m",
    "max_risk_ratio_last_30m",
    "late_trading_flag",
    "window_idx",
]


def _normalize_dt(dt: datetime) -> datetime:
    """Ensures datetime is timezone-naive for uniform arithmetic comparisons without wall-clock shift."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def build_features(
    trades_today: List[Trade],
    orders_today: Optional[List[Order]] = None,
    current_time: Optional[datetime] = None,
    capital: float = 10_00_000.0,
    rules: Optional[Dict[str, Any]] = None,
    window_idx: Optional[int] = None
) -> Dict[str, Union[int, float]]:
    """Builds the dictionary of behavioral features for a user/bot at current_time.
    
    All rule-dependent features are normalized relative to the user's configured rules,
    clipped at 2.0 to guard against out-of-range inputs, and protected against division by zero.

    Args:
        trades_today: List of all trades executed today up to current_time.
        orders_today: Optional list of orders placed today up to current_time.
        current_time: The evaluation timestamp. If None, uses executed_at of last trade or now.
        capital: Account initial capital for risk/pnl percentage calculations.
        rules: Optional dictionary of user trading rules (max_trades_per_day, max_risk_per_trade_pct, etc.).
        window_idx: Optional 0-11 index representing 30m window of the trading day.
        
    Returns:
        Dict mapping each feature name in FEATURE_COLUMNS to its numeric value.
    """
    if current_time is None:
        if trades_today:
            current_time = trades_today[-1].executed_at
        else:
            current_time = datetime.now()

    ref_time = _normalize_dt(current_time)
    start_30m = ref_time - timedelta(minutes=30)
    start_10m = ref_time - timedelta(minutes=10)

    # Extract user rules with safe positive bounds
    safe_rules = rules or {}
    max_trades = max(int(safe_rules.get("max_trades_per_day") or 5), 1)
    max_risk_pct = max(float(safe_rules.get("max_risk_per_trade_pct") or 2.0), 0.1)
    max_cons_losses = max(int(safe_rules.get("max_consecutive_losses") or 3), 1)

    # 1. Filter trades executed today up to ref_time
    valid_trades = [
        t for t in trades_today
        if _normalize_dt(t.executed_at) <= ref_time
    ]
    # Trades in rolling 30-minute window
    trades_30m = [
        t for t in valid_trades
        if _normalize_dt(t.executed_at) >= start_30m
    ]

    # Closed trades (SELL trades with realized_pnl)
    closed_today = [t for t in valid_trades if getattr(t, "realized_pnl", 0.0) != 0.0 or t.side == "SELL"]
    closed_30m = [t for t in trades_30m if getattr(t, "realized_pnl", 0.0) != 0.0 or t.side == "SELL"]

    # Trade counts and normalized relative rule metrics
    trades_count_today = len(valid_trades)
    trades_count_last_30m = len(trades_30m)
    trade_count_ratio_today = round(min(trades_count_today / max_trades, 2.0), 3)
    trade_headroom_today = max(0, max_trades - trades_count_today)

    # Loss / Win counts in rolling 30m window
    loss_count_last_30m = len([t for t in closed_30m if getattr(t, "realized_pnl", 0.0) < 0])
    win_count_last_30m = len([t for t in closed_30m if getattr(t, "realized_pnl", 0.0) > 0])
    win_count_today = len([t for t in closed_today if getattr(t, "realized_pnl", 0.0) > 0])

    # Consecutive losses and normalized streak metrics
    consecutive_losses = 0
    for t in reversed(closed_today):
        if getattr(t, "realized_pnl", 0.0) < 0:
            consecutive_losses += 1
        elif getattr(t, "realized_pnl", 0.0) > 0:
            break

    consecutive_losses_ratio = round(min(consecutive_losses / max_cons_losses, 2.0), 3)
    consecutive_losses_headroom = max(0, max_cons_losses - consecutive_losses)

    # Win rate
    total_closed = len(closed_today)
    win_rate_today = round(win_count_today / total_closed, 3) if total_closed > 0 else 0.5

    # PnL metrics
    total_pnl_today = round(sum(getattr(t, "realized_pnl", 0.0) for t in closed_today), 2)
    pnl_last_30m = round(sum(getattr(t, "realized_pnl", 0.0) for t in closed_30m), 2)
    pnl_pct_capital_today = round((total_pnl_today / capital) * 100.0, 3) if capital > 0 else 0.0

    # Max intraday drawdown from peak
    peak_pnl = 0.0
    running_pnl = 0.0
    max_dd_inr = 0.0
    for t in closed_today:
        running_pnl += getattr(t, "realized_pnl", 0.0)
        if running_pnl > peak_pnl:
            peak_pnl = running_pnl
        dd = peak_pnl - running_pnl
        if dd > max_dd_inr:
            max_dd_inr = dd
    max_drawdown_pct_today = round((max_dd_inr / capital) * 100.0, 3) if capital > 0 else 0.0

    # Trade sizes
    sizes_30m = [t.quantity for t in trades_30m]
    sizes_today = [t.quantity for t in valid_trades]
    avg_trade_size_last_30m = round(sum(sizes_30m) / len(sizes_30m), 1) if sizes_30m else 0.0
    max_trade_size_last_30m = max(sizes_30m, default=0)
    avg_trade_size_today = sum(sizes_today) / len(sizes_today) if sizes_today else 0.0
    raw_size_ratio = avg_trade_size_last_30m / avg_trade_size_today if avg_trade_size_today > 0 else 1.0
    size_ratio_to_daily_avg = round(min(raw_size_ratio, 2.0), 2)

    # Recency metrics
    if valid_trades:
        last_trade_dt = _normalize_dt(valid_trades[-1].executed_at)
        time_since_last_trade_min = round(max(0.0, (ref_time - last_trade_dt).total_seconds() / 60.0), 1)
    else:
        time_since_last_trade_min = 180.0
    time_since_last_trade_min = min(180.0, time_since_last_trade_min)

    losses_today = [t for t in closed_today if getattr(t, "realized_pnl", 0.0) < 0]
    if losses_today:
        last_loss_dt = _normalize_dt(losses_today[-1].executed_at)
        time_since_last_loss_min = round(max(0.0, (ref_time - last_loss_dt).total_seconds() / 60.0), 1)
    else:
        time_since_last_loss_min = 180.0
    time_since_last_loss_min = min(180.0, time_since_last_loss_min)

    # Large loss in last 10 minutes relative to configured max_risk_per_trade_pct
    loss_threshold = capital * (max_risk_pct / 100.0)
    had_large_loss_last_10m = 1 if any(
        getattr(t, "realized_pnl", 0.0) < 0
        and abs(getattr(t, "realized_pnl", 0.0)) >= loss_threshold
        and _normalize_dt(t.executed_at) >= start_10m
        for t in closed_today
    ) else 0

    # Order/Risk metrics normalized relative to configured max_risk_per_trade_pct
    stop_loss_missing_count_last_30m = 0
    risk_pcts_30m: List[float] = []

    if orders_today:
        orders_30m = [
            o for o in orders_today
            if o.created_at and start_30m <= _normalize_dt(o.created_at) <= ref_time
        ]
        for o in orders_30m:
            if o.stop_loss is None or o.stop_loss <= 0:
                stop_loss_missing_count_last_30m += 1
            else:
                order_price = getattr(o, "price", None) or 1000.0
                r_pct = calculate_risk_pct(order_price, o.stop_loss, o.quantity, capital)
                risk_pcts_30m.append(r_pct)

    avg_risk_pct_last_30m = sum(risk_pcts_30m) / len(risk_pcts_30m) if risk_pcts_30m else 0.0
    max_risk_pct_last_30m = max(risk_pcts_30m, default=0.0)

    # Ratios relative to user's max_risk_per_trade_pct, clipped at 2.0
    avg_risk_ratio_last_30m = round(min(avg_risk_pct_last_30m / max_risk_pct, 2.0), 3)
    max_risk_ratio_last_30m = round(min(max_risk_pct_last_30m / max_risk_pct, 2.0), 3)

    # Late trading flag (after 14:30)
    late_trading_flag = 1 if ref_time.time() >= time(14, 30) else 0

    # Window index (0 to 11 for market hours 09:15 to 15:15)
    if window_idx is None:
        market_open_minutes = 9 * 60 + 15
        cur_minutes = ref_time.hour * 60 + ref_time.minute
        elapsed_m = max(0, cur_minutes - market_open_minutes)
        window_idx = min(11, max(0, elapsed_m // 30))

    return {
        "trades_count_last_30m": trades_count_last_30m,
        "trade_count_ratio_today": trade_count_ratio_today,
        "trade_headroom_today": trade_headroom_today,
        "loss_count_last_30m": loss_count_last_30m,
        "win_count_last_30m": win_count_last_30m,
        "consecutive_losses_ratio": consecutive_losses_ratio,
        "consecutive_losses_headroom": consecutive_losses_headroom,
        "win_rate_today": win_rate_today,
        "pnl_last_30m": pnl_last_30m,
        "total_pnl_today": total_pnl_today,
        "pnl_pct_capital_today": pnl_pct_capital_today,
        "max_drawdown_pct_today": max_drawdown_pct_today,
        "avg_trade_size_last_30m": avg_trade_size_last_30m,
        "max_trade_size_last_30m": max_trade_size_last_30m,
        "size_ratio_to_daily_avg": size_ratio_to_daily_avg,
        "time_since_last_trade_min": time_since_last_trade_min,
        "time_since_last_loss_min": time_since_last_loss_min,
        "had_large_loss_last_10m": had_large_loss_last_10m,
        "stop_loss_missing_count_last_30m": stop_loss_missing_count_last_30m,
        "avg_risk_ratio_last_30m": avg_risk_ratio_last_30m,
        "max_risk_ratio_last_30m": max_risk_ratio_last_30m,
        "late_trading_flag": late_trading_flag,
        "window_idx": window_idx,
    }
