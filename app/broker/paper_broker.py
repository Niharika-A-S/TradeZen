"""Paper-trading brokerage engine for TradeZen.

Handles fake-money accounts, orders (MARKET with slippage, LIMIT),
position management with average pricing, charges (flat Rs 20),
realized & unrealized P&L tracking, intraday (MIS) square-off at 15:15,
and short-selling / insufficient funds prevention.
"""
from datetime import datetime, time, timezone
import logging
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func, desc

from app.database import SessionLocal
from app.models.price_bar import PriceBar
from app.models.paper import (
    Account,
    Order,
    Trade,
    Position,
    OrderSide,
    OrderType,
    ProductType,
    OrderStatus,
    INITIAL_PAPER_CASH,
    ORDER_CHARGES,
    SLIPPAGE_RATE,
)
from app.models.user import User, UserProfile
from app.clock.market_clock import MarketClock, get_price

logger = logging.getLogger(__name__)

DEFAULT_INTRADAY_CUTOFF = time(15, 15)


class PaperBroker:
    def __init__(self, clock: Optional[MarketClock] = None):
        self.clock = clock

    def set_clock(self, clock: MarketClock):
        self.clock = clock

    def get_or_create_account(self, user_id: int, db: Session) -> Account:
        """Retrieves or creates the paper trading account for a user with 10L cash."""
        account = db.query(Account).filter_by(user_id=user_id).first()
        if not account:
            account = Account(
                user_id=user_id,
                cash_balance=INITIAL_PAPER_CASH,
                initial_cash=INITIAL_PAPER_CASH
            )
            db.add(account)
            db.commit()
            db.refresh(account)
        return account

    def get_current_market_price(self, symbol: str, db: Session) -> float:
        """Retrieves current market price for symbol using market clock or latest DB bar."""
        sym = symbol.strip().upper()
        if self.clock is not None:
            quote = self.clock.get_current_price(sym, session=db)
            return float(quote.close)

        stmt = (
            select(PriceBar)
            .where(PriceBar.symbol == sym)
            .order_by(desc(PriceBar.timestamp))
            .limit(1)
        )
        bar = db.execute(stmt).scalar_one_or_none()
        if bar is not None:
            return float(bar.close)

        raise KeyError(f"No price data available for symbol '{sym}'")

    def calculate_slippage_price(self, side: str, market_price: float) -> float:
        """Applies 0.05% slippage in the unfavorable direction for MARKET orders.
        
        - BUY: pays more (+0.05%)
        - SELL: receives less (-0.05%)
        """
        if side.upper() == OrderSide.BUY.value:
            return round(market_price * (1.0 + SLIPPAGE_RATE), 2)
        else:
            return round(market_price * (1.0 - SLIPPAGE_RATE), 2)

    def place_order(
        self,
        user_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        price: Optional[float] = None,
        product_type: str = "MIS",
        stop_loss: Optional[float] = None,
        apply_slippage: bool = True,
        execution_price: Optional[float] = None,
        db: Optional[Session] = None
    ) -> Order:
        """Places and processes a paper order.
        
        Rejects orders that:
        - Exceed available cash (BUY)
        - Exceed owned quantity (SELL - no short selling)
        """
        sym = symbol.strip().upper()
        side_norm = side.strip().upper()
        otype_norm = order_type.strip().upper()
        ptype_norm = product_type.strip().upper()

        if quantity <= 0:
            raise ValueError("Order quantity must be greater than 0.")

        def _execute(session: Session) -> Order:
            account = self.get_or_create_account(user_id, session)

            order = Order(
                user_id=user_id,
                symbol=sym,
                side=side_norm,
                order_type=otype_norm,
                product_type=ptype_norm,
                quantity=quantity,
                price=price,
                stop_loss=stop_loss,
                status=OrderStatus.PENDING.value,
                created_at=self.clock.current_time if self.clock else datetime.now(timezone.utc)
            )
            session.add(order)
            session.flush()

            # Determine market price to evaluate
            if execution_price is not None:
                current_price = execution_price
            else:
                try:
                    current_price = self.get_current_market_price(sym, session)
                except Exception as e:
                    order.status = OrderStatus.REJECTED.value
                    order.rejection_reason = f"Price lookup failed: {str(e)}"
                    session.commit()
                    return order

            # Validation 1: SELL (No short selling allowed)
            if side_norm == OrderSide.SELL.value:
                pos = session.query(Position).filter_by(
                    user_id=user_id,
                    symbol=sym,
                    product_type=ptype_norm
                ).first()
                owned_qty = pos.quantity if pos else 0
                if owned_qty < quantity:
                    order.status = OrderStatus.REJECTED.value
                    order.rejection_reason = f"No short selling allowed: owned {owned_qty}, requested {quantity}"
                    session.commit()
                    logger.warning("Order %d rejected: %s", order.id, order.rejection_reason)
                    return order

            # Determine fill price
            if otype_norm == OrderType.MARKET.value:
                if execution_price is not None:
                    fill_price = execution_price
                elif apply_slippage:
                    fill_price = self.calculate_slippage_price(side_norm, current_price)
                else:
                    fill_price = current_price
                should_fill = True
            elif otype_norm == OrderType.LIMIT.value:
                if execution_price is not None:
                    fill_price = execution_price
                    should_fill = True
                else:
                    # Check limit condition against current price
                    if side_norm == OrderSide.BUY.value and current_price <= price:
                        fill_price = price
                        should_fill = True
                    elif side_norm == OrderSide.SELL.value and current_price >= price:
                        fill_price = price
                        should_fill = True
                    else:
                        should_fill = False
            else:
                order.status = OrderStatus.REJECTED.value
                order.rejection_reason = f"Unknown order type: {otype_norm}"
                session.commit()
                return order

            # Validation 2: BUY (Check available cash)
            if should_fill and side_norm == OrderSide.BUY.value:
                required_funds = (quantity * fill_price) + ORDER_CHARGES
                if account.cash_balance < required_funds:
                    order.status = OrderStatus.REJECTED.value
                    order.rejection_reason = (
                        f"Insufficient funds: required Rs {required_funds:,.2f}, "
                        f"available Rs {account.cash_balance:,.2f}"
                    )
                    session.commit()
                    logger.warning("Order %d rejected: %s", order.id, order.rejection_reason)
                    return order

            if should_fill:
                self._fill_order(order, fill_price, account, session)
            else:
                session.commit()

            return order

        if db is not None:
            return _execute(db)
        with SessionLocal() as session:
            return _execute(session)

    def _fill_order(self, order: Order, fill_price: float, account: Account, db: Session):
        """Executes fill logic, position adjustments, trade record, and cash balance updates."""
        user_id = order.user_id
        symbol = order.symbol
        quantity = order.quantity
        side = order.side
        product_type = order.product_type
        charges = ORDER_CHARGES
        exec_time = self.clock.current_time if self.clock else datetime.now(timezone.utc)

        position = db.query(Position).filter_by(
            user_id=user_id,
            symbol=symbol,
            product_type=product_type
        ).first()

        if not position:
            position = Position(
                user_id=user_id,
                symbol=symbol,
                product_type=product_type,
                quantity=0,
                average_price=0.0,
                cumulative_realized_pnl=0.0
            )
            db.add(position)
            db.flush()

        gross_realized_pnl = 0.0
        net_realized_pnl = -charges

        if side == OrderSide.BUY.value:
            # Append lot for FIFO realized P&L matching
            lots = list(position.lots or [])
            lots.append({"quantity": quantity, "price": fill_price})
            position.lots = lots

            total_cost = (quantity * fill_price) + charges
            account.cash_balance -= total_cost

            # Update average price: (old_qty * old_avg + new_qty * fill_price) / total_qty
            if position.quantity > 0:
                new_avg = ((position.quantity * position.average_price) + (quantity * fill_price)) / (position.quantity + quantity)
                position.average_price = round(new_avg, 4)
                position.quantity += quantity
            else:
                position.quantity = quantity
                position.average_price = round(fill_price, 4)

        elif side == OrderSide.SELL.value:
            # FIFO lot matching for realized P&L
            lots = list(position.lots or [])
            remaining_to_sell = quantity
            gross_realized_pnl = 0.0
            updated_lots = []

            for lot in lots:
                if remaining_to_sell > 0:
                    lot_qty = lot["quantity"]
                    lot_price = lot["price"]
                    matched_qty = min(remaining_to_sell, lot_qty)
                    gross_realized_pnl += (fill_price - lot_price) * matched_qty
                    remaining_to_sell -= matched_qty
                    leftover_qty = lot_qty - matched_qty
                    if leftover_qty > 0:
                        updated_lots.append({"quantity": leftover_qty, "price": lot_price})
                else:
                    updated_lots.append(lot)

            # Fallback if lots were empty
            if not lots and position.quantity > 0:
                gross_realized_pnl = (fill_price - position.average_price) * quantity

            position.lots = updated_lots
            net_realized_pnl = gross_realized_pnl - charges
            cash_received = (fill_price * quantity) - charges
            account.cash_balance += cash_received

            position.quantity -= quantity
            position.cumulative_realized_pnl += gross_realized_pnl
            if position.quantity == 0:
                position.average_price = 0.0
                position.lots = []

        # Mark order filled
        order.status = OrderStatus.FILLED.value
        order.filled_quantity = quantity
        order.average_fill_price = fill_price
        order.charges = charges
        order.filled_at = exec_time

        # Create trade record
        trade = Trade(
            order_id=order.id,
            user_id=user_id,
            symbol=symbol,
            side=side,
            product_type=product_type,
            quantity=quantity,
            price=fill_price,
            charges=charges,
            realized_pnl=gross_realized_pnl,
            net_realized_pnl=net_realized_pnl,
            executed_at=exec_time
        )
        db.add(trade)
        db.commit()
        db.refresh(order)
        logger.info("Order %d FILLED: %s %d %s @ %.2f (Gross PnL: %.2f)", order.id, side, quantity, symbol, fill_price, gross_realized_pnl)

        # Trigger rule engine detectors and persist any generated alerts
        from app.rules.rule_engine import evaluate_and_persist_alerts
        alerts = evaluate_and_persist_alerts(trade, order, user_id, db, clock=self.clock)
        order.generated_alerts = alerts

    def cancel_order(self, order_id: int, user_id: int, db: Session) -> Order:
        """Cancels a pending order."""
        order = db.query(Order).filter_by(id=order_id, user_id=user_id).first()
        if not order:
            raise KeyError(f"Order #{order_id} not found.")

        if order.status != OrderStatus.PENDING.value:
            raise ValueError(f"Cannot cancel order with status '{order.status}'. Only PENDING orders can be cancelled.")

        order.status = OrderStatus.CANCELLED.value
        order.cancelled_at = self.clock.current_time if self.clock else datetime.now(timezone.utc)
        db.commit()
        db.refresh(order)
        return order

    def process_pending_orders(self, db: Session) -> List[Order]:
        """Scans and fills pending limit orders if current market price meets condition."""
        pending_orders = db.query(Order).filter_by(status=OrderStatus.PENDING.value).all()
        filled = []
        for order in pending_orders:
            try:
                cur_price = self.get_current_market_price(order.symbol, db)
            except Exception:
                continue

            should_fill = False
            if order.side == OrderSide.BUY.value and cur_price <= order.price:
                should_fill = True
            elif order.side == OrderSide.SELL.value and cur_price >= order.price:
                should_fill = True

            if should_fill:
                account = self.get_or_create_account(order.user_id, db)
                self._fill_order(order, order.price, account, db)
                filled.append(order)

        return filled

    def auto_square_off_intraday(
        self,
        user_id: Optional[int] = None,
        cutoff_time: Optional[time] = None,
        db: Optional[Session] = None
    ) -> List[Order]:
        """Automatically squares off all open MIS positions at or after cutoff time (default 15:15)."""
        cutoff = cutoff_time or DEFAULT_INTRADAY_CUTOFF
        cur_dt = self.clock.current_time if self.clock else datetime.now()

        # Check user profile rule if available
        def _check_and_square(session: Session) -> List[Order]:
            query = session.query(Position).filter(
                Position.product_type == ProductType.MIS.value,
                Position.quantity > 0
            )
            if user_id is not None:
                query = query.filter(Position.user_id == user_id)

            open_mis = query.all()
            squared_orders = []

            for pos in open_mis:
                # Check user profile cutoff if configured
                user_cutoff = cutoff
                profile = session.query(UserProfile).filter_by(user_id=pos.user_id).first()
                if profile and profile.rules_json and "intraday_cutoff_time" in profile.rules_json:
                    try:
                        h, m = map(int, profile.rules_json["intraday_cutoff_time"].split(":"))
                        user_cutoff = time(h, m)
                    except Exception:
                        pass

                if cur_dt.time() >= user_cutoff:
                    logger.info("Auto-squaring off MIS position: %s %d units for user %d", pos.symbol, pos.quantity, pos.user_id)
                    order = self.place_order(
                        user_id=pos.user_id,
                        symbol=pos.symbol,
                        side=OrderSide.SELL.value,
                        order_type=OrderType.MARKET.value,
                        quantity=pos.quantity,
                        product_type=ProductType.MIS.value,
                        apply_slippage=True,
                        db=session
                    )
                    squared_orders.append(order)

            return squared_orders

        if db is not None:
            return _check_and_square(db)
        with SessionLocal() as session:
            return _check_and_square(session)

    def get_positions(self, user_id: int, open_only: bool = True, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """Retrieves user positions with current price and unrealized P&L."""
        def _get(session: Session) -> List[Dict[str, Any]]:
            query = session.query(Position).filter_by(user_id=user_id)
            if open_only:
                query = query.filter(Position.quantity > 0)
            positions = query.all()

            results = []
            for p in positions:
                try:
                    cur_p = self.get_current_market_price(p.symbol, session)
                except Exception:
                    cur_p = p.average_price
                results.append(p.to_dict(current_price=cur_p))
            return results

        if db is not None:
            return _get(db)
        with SessionLocal() as session:
            return _get(session)

    def get_account_summary(self, user_id: int, db: Optional[Session] = None) -> Dict[str, Any]:
        """Calculates cash balance, realized P&L, unrealized P&L, and total portfolio value."""
        def _summary(session: Session) -> Dict[str, Any]:
            account = self.get_or_create_account(user_id, session)

            # Sum realized P&L from trades
            realized_gross = session.query(func.coalesce(func.sum(Trade.realized_pnl), 0.0)).filter_by(user_id=user_id).scalar()
            total_charges = session.query(func.coalesce(func.sum(Trade.charges), 0.0)).filter_by(user_id=user_id).scalar()
            realized_net = realized_gross - total_charges

            # Calculate unrealized P&L and holdings value across open positions
            open_positions = session.query(Position).filter(
                Position.user_id == user_id,
                Position.quantity > 0
            ).all()

            unrealized_pnl = 0.0
            holdings_value = 0.0
            for pos in open_positions:
                try:
                    cur_p = self.get_current_market_price(pos.symbol, session)
                except Exception:
                    cur_p = pos.average_price
                unrealized_pnl += (cur_p - pos.average_price) * pos.quantity
                holdings_value += cur_p * pos.quantity

            portfolio_value = account.cash_balance + holdings_value

            return {
                "user_id": user_id,
                "cash_balance": round(account.cash_balance, 2),
                "initial_cash": round(account.initial_cash, 2),
                "holdings_value": round(holdings_value, 2),
                "portfolio_value": round(portfolio_value, 2),
                "realized_pnl": round(realized_gross, 2),
                "net_realized_pnl": round(realized_net, 2),
                "total_charges": round(total_charges, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "open_positions_count": len(open_positions)
            }

        if db is not None:
            return _summary(db)
        with SessionLocal() as session:
            return _summary(session)

    def get_trades(self, user_id: int, symbol: Optional[str] = None, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """Retrieves trade execution history for a user."""
        def _get(session: Session) -> List[Dict[str, Any]]:
            query = session.query(Trade).filter_by(user_id=user_id).order_by(Trade.executed_at.desc())
            if symbol:
                query = query.filter_by(symbol=symbol.strip().upper())
            return [t.to_dict() for t in query.all()]

        if db is not None:
            return _get(db)
        with SessionLocal() as session:
            return _get(session)
