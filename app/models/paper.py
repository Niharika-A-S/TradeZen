"""SQLAlchemy models for Paper Trading Engine: Account, Order, Trade, and Position."""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Float,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Index,
    JSON
)
from sqlalchemy.orm import relationship

from app.database import Base

INITIAL_PAPER_CASH = 10_00_000.0  # 10,00,000 INR (10 Lakhs)
ORDER_CHARGES = 20.0              # Flat Rs 20 per executed order
SLIPPAGE_RATE = 0.0005            # 0.05% adverse slippage on MARKET orders


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class ProductType(str, Enum):
    MIS = "MIS"  # Margin Intraday Square-off
    CNC = "CNC"  # Cash & Carry / Delivery


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Account(Base):
    """Paper trading account holding fake cash balance."""
    __tablename__ = "paper_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    cash_balance = Column(Float, default=INITIAL_PAPER_CASH, nullable=False)
    initial_cash = Column(Float, default=INITIAL_PAPER_CASH, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    user = relationship("User", backref="account")

    def __repr__(self) -> str:
        return f"<Account user_id={self.user_id} cash={self.cash_balance:.2f}>"

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "cash_balance": round(self.cash_balance, 2),
            "initial_cash": round(self.initial_cash, 2),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Order(Base):
    """Order placed in paper brokerage."""
    __tablename__ = "paper_orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)           # BUY / SELL
    order_type = Column(String(10), nullable=False)     # MARKET / LIMIT
    product_type = Column(String(10), default="MIS", nullable=False) # MIS / CNC
    quantity = Column(Integer, nullable=False)
    filled_quantity = Column(Integer, default=0, nullable=False)
    price = Column(Float, nullable=True)                # Limit price
    average_fill_price = Column(Float, nullable=True)   # Actual execution price
    stop_loss = Column(Float, nullable=True)            # Optional stop-loss price
    charges = Column(Float, default=0.0, nullable=False)
    status = Column(String(20), default="PENDING", nullable=False, index=True) # PENDING, FILLED, CANCELLED, REJECTED
    rejection_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    filled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    trades = relationship("Trade", back_populates="order", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id} {self.side} {self.quantity} {self.symbol} "
            f"type={self.order_type} status={self.status} fill_price={self.average_fill_price}>"
        )

    def to_dict(self):
        return {
            "order_id": self.id,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "product_type": self.product_type,
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "price": self.price,
            "average_fill_price": round(self.average_fill_price, 2) if self.average_fill_price is not None else None,
            "stop_loss": self.stop_loss,
            "charges": round(self.charges, 2),
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
        }


class Trade(Base):
    """Execution trade record generated when an order fills."""
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    product_type = Column(String(10), default="MIS", nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    charges = Column(Float, default=ORDER_CHARGES, nullable=False)
    realized_pnl = Column(Float, default=0.0, nullable=False) # Realized P&L from this trade (gross)
    net_realized_pnl = Column(Float, default=0.0, nullable=False) # Realized P&L minus charges
    executed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    order = relationship("Order", back_populates="trades")

    def __repr__(self) -> str:
        return (
            f"<Trade id={self.id} order_id={self.order_id} {self.side} "
            f"{self.quantity} {self.symbol} @ {self.price:.2f} PnL={self.realized_pnl:.2f}>"
        )

    def to_dict(self):
        return {
            "trade_id": self.id,
            "order_id": self.order_id,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "side": self.side,
            "product_type": self.product_type,
            "quantity": self.quantity,
            "price": round(self.price, 2),
            "charges": round(self.charges, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "net_realized_pnl": round(self.net_realized_pnl, 2),
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }


class Position(Base):
    """Aggregated trading position per symbol and product type."""
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    product_type = Column(String(10), default="MIS", nullable=False) # MIS / CNC
    quantity = Column(Integer, default=0, nullable=False)            # Net open quantity
    average_price = Column(Float, default=0.0, nullable=False)       # Weighted average entry price
    cumulative_realized_pnl = Column(Float, default=0.0, nullable=False)
    lots = Column(JSON, default=list, nullable=False)                # FIFO buy lots: [{"quantity": int, "price": float}]
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        Index("ix_user_symbol_product", "user_id", "symbol", "product_type", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<Position user={self.user_id} {self.symbol} {self.product_type} "
            f"qty={self.quantity} avg_price={self.average_price:.2f} pnl={self.cumulative_realized_pnl:.2f}>"
        )

    def to_dict(self, current_price: Optional[float] = None):
        unrealized_pnl = 0.0
        cur_p = current_price if current_price is not None else self.average_price
        if self.quantity > 0:
            unrealized_pnl = (cur_p - self.average_price) * self.quantity

        return {
            "position_id": self.id,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "product_type": self.product_type,
            "quantity": self.quantity,
            "average_price": round(self.average_price, 2),
            "current_price": round(cur_p, 2) if current_price is not None else None,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "realized_pnl": round(self.cumulative_realized_pnl, 2),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
