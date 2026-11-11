from sqlalchemy import Column, BigInteger, String, DateTime, Float, UniqueConstraint, Index
from app.database import Base


class PriceBar(Base):
    """1-minute OHLCV historical price bar model."""
    __tablename__ = "price_bars"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uq_price_bars_symbol_timestamp"),
        Index("ix_price_bars_symbol_timestamp", "symbol", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<PriceBar {self.symbol} {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
            f"O={self.open:.2f} H={self.high:.2f} L={self.low:.2f} C={self.close:.2f} V={self.volume}>"
        )

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat() if hasattr(self.timestamp, "isoformat") else str(self.timestamp),
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": int(self.volume),
        }
