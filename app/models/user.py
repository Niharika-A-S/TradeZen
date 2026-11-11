from datetime import datetime, timezone
from typing import Dict, Any
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.database import Base


def default_trading_rules() -> Dict[str, Any]:
    """Default trading rules stored in user_profiles.rules_json."""
    return {
        "max_trades_per_day": 5,
        "max_risk_per_trade_pct": 2.0,
        "max_daily_loss": 5000.0,
        "max_consecutive_losses": 3,
        "require_stop_loss": True,
        "intraday_cutoff_time": "15:15",
    }


class User(Base):
    """User account model."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)
    display_name = Column(String(100), default="Trader", nullable=True)
    is_active = Column(Boolean, default=True, nullable=True)
    current_season = Column(Integer, default=1, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    profile = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )
    rules = relationship("Rule", back_populates="user", cascade="all, delete-orphan")
    attempts = relationship("Attempt", back_populates="user", cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} username='{self.username}'>"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserProfile(Base):
    """User profile model containing behavioural rules and trading limits."""
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True
    )
    rules_json = Column(JSON, default=default_trading_rules, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    user = relationship("User", back_populates="profile")

    def __repr__(self) -> str:
        return f"<UserProfile id={self.id} user_id={self.user_id}>"
