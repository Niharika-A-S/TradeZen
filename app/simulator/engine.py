"""Simulation Engine for TradeZen bot traders and behavior dataset generation."""
import random
import time
from datetime import datetime, date, timedelta, time as dtime, timezone
from typing import List, Dict, Any, Optional, Tuple, Callable
import logging

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.price_bar import PriceBar
from app.models.alert import AlertType, AlertSeverity
from app.models.paper import Order, Trade, OrderSide, OrderType
from app.models.user import UserProfile
from app.rules.rule_engine import (
    calculate_risk,
    calculate_risk_pct,
    detect_rule_violations,
    detect_overtrading_after_loss,
    detect_revenge_trading,
)
from app.simulator.bot import BotConfig, BotPersonality, create_default_bots
from app.simulator.features import build_features, FEATURE_COLUMNS

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ['INFY', 'RELIANCE', 'TCS', 'HDFCBANK', 'SBIN']


class MockUserProfile:
    """Mock user profile providing user-defined rules for rule engine detectors."""
    def __init__(self, rules: Dict[str, Any]):
        self.rules_json = rules


class SimulationEngine:
    """High-performance in-memory simulation engine for bot traders."""

    def __init__(self, session: Optional[Session] = None):
        self.session = session
        self.bars_by_date: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        self.symbols: List[str] = []
        self.dates: List[str] = []

    def load_market_data(self, session: Optional[Session] = None) -> None:
        """Loads all price bars from the database and structures them in memory by date and symbol."""
        db = session or self.session
        if db is None:
            raise ValueError("A database session is required to load market data.")

        logger.info("Loading price bars from database...")
        query = db.query(
            PriceBar.symbol,
            PriceBar.timestamp,
            PriceBar.open,
            PriceBar.high,
            PriceBar.low,
            PriceBar.close,
            PriceBar.volume
        ).order_by(PriceBar.timestamp.asc())

        df = pd.read_sql(query.statement, db.bind)
        df['date'] = df['timestamp'].dt.strftime('%Y-%m-%d')

        self.dates = sorted(df['date'].unique())
        self.symbols = sorted(df['symbol'].unique())

        self.bars_by_date = {}
        for date_val, group in df.groupby('date'):
            self.bars_by_date[date_val] = {
                sym: sym_group.sort_values('timestamp').to_dict('records')
                for sym, sym_group in group.groupby('symbol')
            }
        logger.info(f"Loaded {len(df)} price bars across {len(self.dates)} dates and {len(self.symbols)} symbols.")

    def run_simulation(
        self,
        dates: Optional[List[str]] = None,
        bots: Optional[List[BotConfig]] = None,
        random_seed: int = 42
    ) -> pd.DataFrame:
        """Runs the simulation for the specified bots and dates, returning the behavior dataset DataFrame."""
        if not self.bars_by_date:
            self.load_market_data()

        sim_dates = dates if dates is not None else self.dates
        sim_bots = bots if bots is not None else create_default_bots(seed=random_seed)

        random.seed(random_seed)
        all_rows: List[Dict[str, Any]] = []
        trade_id_seq = 1

        for bot_cfg in sim_bots:
            b_id = bot_cfg.bot_id
            b_name = bot_cfg.name
            personality = bot_cfg.personality.value if hasattr(bot_cfg.personality, 'value') else str(bot_cfg.personality)
            capital = bot_cfg.initial_capital
            user_profile = MockUserProfile(bot_cfg.rules)

            bot_max_trades = int(bot_cfg.rules.get("max_trades_per_day", 5))
            bot_max_risk_pct = float(bot_cfg.rules.get("max_risk_per_trade_pct", 2.0))

            for d_str in sim_dates:
                day_data = self.bars_by_date.get(d_str)
                if not day_data or "INFY" not in day_data or len(day_data["INFY"]) < 360:
                    continue

                day_start = day_data["INFY"][0]["timestamp"]
                today_trades: List[Trade] = []
                today_orders: List[Order] = []
                alerts_by_window: Dict[int, List[str]] = {w: [] for w in range(12)}
                active_position: Optional[Dict[str, Any]] = None
                consecutive_losses = 0
                revenge_until: Optional[datetime] = None
                last_loss_trade: Optional[Trade] = None

                # Pre-index bars by minute for O(1) timestamp access
                bars_by_minute = {sym: {b["timestamp"]: b for b in day_data.get(sym, [])} for sym in self.symbols}
                base_time = day_start

                # 360 trading minutes (09:15 to 15:15)
                for m in range(360):
                    current_time = base_time + timedelta(minutes=m)
                    window_idx = min(11, m // 30)

                    # -------------------------------------------------------
                    # 1. Manage Active Position Exit
                    # -------------------------------------------------------
                    if active_position is not None:
                        pos_sym = active_position["symbol"]
                        cur_bar = bars_by_minute.get(pos_sym, {}).get(current_time)

                        if cur_bar:
                            exit_price = None
                            exit_reason = None

                            # Check stop loss hit
                            if active_position["stop_loss"] is not None and cur_bar["low"] <= active_position["stop_loss"]:
                                exit_price = min(cur_bar["open"], active_position["stop_loss"])
                                exit_reason = "STOP_LOSS"
                            # Check take profit hit
                            elif active_position["take_profit"] is not None and cur_bar["high"] >= active_position["take_profit"]:
                                exit_price = max(cur_bar["open"], active_position["take_profit"])
                                exit_reason = "TAKE_PROFIT"
                            # Check holding time or 15:15 intraday square-off
                            elif m >= 359 or (m - active_position["entry_m"]) >= active_position["max_hold"]:
                                exit_price = cur_bar["close"]
                                exit_reason = "TIME_OR_CUTOFF"

                            if exit_price is not None:
                                trade_id_seq += 1
                                gross_pnl = (exit_price - active_position["entry_price"]) * active_position["quantity"]
                                net_pnl = gross_pnl - 40.0  # Rs 20 buy + Rs 20 sell charges
                                sell_trade = Trade(
                                    id=trade_id_seq,
                                    user_id=b_id,
                                    symbol=pos_sym,
                                    side="SELL",
                                    quantity=active_position["quantity"],
                                    price=exit_price,
                                    charges=20.0,
                                    executed_at=current_time
                                )
                                sell_trade.realized_pnl = round(net_pnl, 2)
                                today_trades.append(sell_trade)

                                # Update loss streak & revenge trigger
                                if net_pnl < 0:
                                    consecutive_losses += 1
                                    last_loss_trade = sell_trade
                                    # Loss >= configured max risk % activates revenge window
                                    loss_trig = capital * (bot_max_risk_pct / 100.0)
                                    if abs(net_pnl) >= loss_trig:
                                        revenge_until = current_time + timedelta(minutes=10)
                                else:
                                    consecutive_losses = 0

                                # Check Overtrading after loss detector
                                ot_alert = detect_overtrading_after_loss(today_trades, reference_time=current_time)
                                if ot_alert:
                                    alerts_by_window[window_idx].append(ot_alert["alert_type"])

                                active_position = None

                    # -------------------------------------------------------
                    # 2. Trade Entry Decision (if flat and before 15:10)
                    # -------------------------------------------------------
                    if active_position is None and m < 355:
                        should_enter = False
                        entry_symbol = random.choice(self.symbols)
                        cur_bar = bars_by_minute.get(entry_symbol, {}).get(current_time)
                        if not cur_bar:
                            continue
                        elif cur_bar["close"] <= 0:
                            continue
                            
                        # Entry price with 0.05% slippage
                        entry_price = round(cur_bar["close"] * 1.0005, 2)
                        stop_loss = None
                        take_profit = None
                        quantity = 100
                        max_hold = 20

                        # === Personality Card Logic ===
                        if personality == BotPersonality.DISCIPLINED.value:
                            # Strict adherence: respects configured max_trades_per_day
                            if len([t for t in today_trades if t.side == "BUY"]) < bot_max_trades:
                                if random.random() < 0.02:
                                    should_enter = True
                                    stop_loss = round(entry_price * 0.99, 2)  # 1% stop loss
                                    risk_per_share = max(1.0, entry_price - stop_loss)
                                    target_risk = capital * (min(bot_max_risk_pct, 1.5) / 100.0)
                                    quantity = max(1, int(target_risk / risk_per_share))
                                    take_profit = round(entry_price * 1.015, 2)  # 1.5% target
                                    max_hold = random.randint(15, 30)

                        elif personality == BotPersonality.OVERTRADER.value:
                            # Trades more after losses, ignores max trades limit
                            recent_30m_losses = len([
                                t for t in today_trades
                                if getattr(t, 'realized_pnl', 0.0) < 0 and (current_time - t.executed_at).total_seconds() <= 1800
                            ])
                            trade_prob = min(0.35, 0.025 * (1.0 + 1.8 * recent_30m_losses))
                            if random.random() < trade_prob:
                                should_enter = True
                                size_mult = 1.0 + (0.35 * recent_30m_losses)
                                risk_pct = bot_max_risk_pct * size_mult
                                stop_loss = round(entry_price * 0.99, 2)
                                risk_per_share = max(1.0, entry_price - stop_loss)
                                target_risk = capital * (risk_pct / 100.0)
                                quantity = max(1, int(target_risk / risk_per_share))
                                take_profit = round(entry_price * 1.008, 2)
                                max_hold = random.randint(3, 10)

                        elif personality == BotPersonality.REVENGE_TRADER.value:
                            # Re-enters fast with bigger size after big loss
                            is_revenge = revenge_until is not None and current_time <= revenge_until
                            trade_prob = 0.45 if is_revenge else 0.025
                            if random.random() < trade_prob:
                                should_enter = True
                                if is_revenge and last_loss_trade:
                                    quantity = int(last_loss_trade.quantity * random.uniform(1.8, 2.5))
                                    target_risk_pct = bot_max_risk_pct * random.uniform(1.5, 2.5)
                                    target_risk = capital * (target_risk_pct / 100.0)
                                    stop_loss = round(entry_price - (target_risk / max(1, quantity)), 2)
                                    take_profit = round(entry_price * 1.025, 2)
                                    max_hold = random.randint(5, 15)
                                else:
                                    risk_pct = bot_max_risk_pct * random.uniform(1.1, 1.4)
                                    target_risk = capital * (risk_pct / 100.0)
                                    stop_loss = round(entry_price * 0.985, 2)
                                    risk_per_share = max(1.0, entry_price - stop_loss)
                                    quantity = max(1, int(target_risk / risk_per_share))
                                    take_profit = round(entry_price * 1.02, 2)
                                    max_hold = random.randint(8, 20)

                        elif personality == BotPersonality.STOP_LOSS_IGNORER.value:
                            # Skips stop-loss or sets excessively wide stop-loss
                            if random.random() < 0.025:
                                should_enter = True
                                if random.random() < 0.60:
                                    stop_loss = None
                                    quantity = int(capital * 0.15 / entry_price)
                                    take_profit = round(entry_price * 1.02, 2)
                                    max_hold = random.randint(30, 60)
                                else:
                                    risk_pct = bot_max_risk_pct * random.uniform(1.8, 3.0)
                                    stop_loss = round(entry_price * 0.96, 2)
                                    risk_per_share = max(1.0, entry_price - stop_loss)
                                    target_risk = capital * (risk_pct / 100.0)
                                    quantity = max(1, int(target_risk / risk_per_share))
                                    take_profit = round(entry_price * 1.02, 2)
                                    max_hold = random.randint(25, 50)

                        elif personality == BotPersonality.FOMO_CHASER.value:
                            # FOMO Chaser: Buys after a 30-min price run-up >= 3.0%
                            fomo_found = False
                            if m >= 30:
                                for sym in self.symbols:
                                    past_b = bars_by_minute.get(sym, {}).get(current_time - timedelta(minutes=30))
                                    sym_cur_b = bars_by_minute.get(sym, {}).get(current_time)
                                    if past_b and sym_cur_b and past_b["close"] > 0:
                                        surge = ((sym_cur_b["close"] - past_b["close"]) / past_b["close"]) * 100.0
                                        if surge >= 3.0:
                                            fomo_found = True
                                            entry_symbol = sym
                                            cur_bar = sym_cur_b
                                            entry_price = round(cur_bar["close"] * 1.0005, 2)
                                            break

                            if fomo_found:
                                # High inclination to chase price surge
                                if random.random() < 0.65:
                                    should_enter = True
                                    risk_pct = bot_max_risk_pct * random.uniform(1.0, 1.5)
                                    stop_loss = round(entry_price * 0.985, 2)
                                    risk_per_share = max(1.0, entry_price - stop_loss)
                                    target_risk = capital * (risk_pct / 100.0)
                                    quantity = max(1, int(target_risk / risk_per_share))
                                    take_profit = round(entry_price * 1.015, 2)
                                    max_hold = random.randint(10, 30)
                            else:
                                if random.random() < 0.015:
                                    should_enter = True
                                    risk_pct = bot_max_risk_pct
                                    stop_loss = round(entry_price * 0.99, 2)
                                    risk_per_share = max(1.0, entry_price - stop_loss)
                                    target_risk = capital * (risk_pct / 100.0)
                                    quantity = max(1, int(target_risk / risk_per_share))
                                    take_profit = round(entry_price * 1.02, 2)
                                    max_hold = random.randint(15, 30)

                        # Execute BUY entry trade
                        if should_enter:
                            trade_id_seq += 1
                            buy_order = Order(
                                id=trade_id_seq,
                                user_id=b_id,
                                symbol=entry_symbol,
                                side="BUY",
                                order_type="MARKET",
                                quantity=quantity,
                                stop_loss=stop_loss,
                                status="FILLED",
                                created_at=current_time
                            )
                            buy_trade = Trade(
                                id=trade_id_seq,
                                order_id=buy_order.id,
                                user_id=b_id,
                                symbol=entry_symbol,
                                side="BUY",
                                quantity=quantity,
                                price=entry_price,
                                charges=20.0,
                                realized_pnl=0.0,
                                executed_at=current_time
                            )
                            today_orders.append(buy_order)
                            today_trades.append(buy_trade)

                            active_position = {
                                "symbol": entry_symbol,
                                "entry_m": m,
                                "entry_time": current_time,
                                "entry_price": entry_price,
                                "quantity": quantity,
                                "stop_loss": stop_loss,
                                "take_profit": take_profit,
                                "max_hold": max_hold
                            }

                            # Evaluate post-trade detectors on BUY
                            entry_trades = [t for t in today_trades if t.side == "BUY"]
                            rule_alerts = detect_rule_violations(
                                buy_trade, buy_order, user_profile, capital, entry_trades
                            )
                            for a in rule_alerts:
                                alerts_by_window[window_idx].append(a["alert_type"])

                            prev_trades = [t for t in today_trades if t.id != buy_trade.id]
                            rev_alert = detect_revenge_trading(
                                buy_trade, prev_trades, capital, window_minutes=10, current_order=buy_order
                            )
                            if rev_alert:
                                alerts_by_window[window_idx].append(rev_alert["alert_type"])

                            if m >= 315:
                                past_bar = bars_by_minute.get(entry_symbol, {}).get(current_time - timedelta(minutes=30))
                                if past_bar and past_bar["close"] > 0:
                                    surge = ((cur_bar["close"] - past_bar["close"]) / past_bar["close"]) * 100.0
                                    if surge >= 4.0:
                                        alerts_by_window[window_idx].append(AlertType.LATE_BREAKOUT_CHASE.value)

                # -------------------------------------------------------
                # 3. Construct 12 Window Records at End of Day
                # -------------------------------------------------------
                for w in range(12):
                    w_start_time = day_start + timedelta(minutes=w * 30)
                    w_end_time = day_start + timedelta(minutes=(w + 1) * 30)

                    # Trades and orders executed today up to window end
                    trades_up_to_w = [t for t in today_trades if t.executed_at < w_end_time]
                    orders_up_to_w = [o for o in today_orders if o.created_at and o.created_at < w_end_time]

                    features = build_features(
                        trades_today=trades_up_to_w,
                        orders_today=orders_up_to_w,
                        current_time=w_end_time,
                        capital=capital,
                        rules=bot_cfg.rules,
                        window_idx=w
                    )

                    w_alerts = list(set(alerts_by_window[w]))
                    label = 1 if len(w_alerts) > 0 else 0
                    v_str = ",".join(w_alerts) if w_alerts else "NONE"

                    row = {
                        "bot_id": b_id,
                        "bot_name": b_name,
                        "personality": personality,
                        "date": d_str,
                        "window_idx": w,
                        "window_start": w_start_time.strftime("%H:%M:%S"),
                        "window_end": w_end_time.strftime("%H:%M:%S"),
                        **features,
                        "violation_types": v_str,
                        "label": label,
                    }
                    all_rows.append(row)

        return pd.DataFrame(all_rows)
