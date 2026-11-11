"""Tests for SQLAlchemy models: User, UserProfile, and PriceBar."""
from datetime import datetime, timezone
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.user import User, UserProfile, default_trading_rules
from app.models.price_bar import PriceBar


def test_user_creation_and_profile_relationship(db_session):
    """Verifies User and UserProfile models with rules_json cascade correctly."""
    username = f"test_user_{int(datetime.now().timestamp() * 1000)}"
    user = User(username=username, email=f"{username}@example.com")
    profile = UserProfile(
        user=user,
        rules_json={
            "max_trades_per_day": 3,
            "max_risk_per_trade_pct": 1.5,
            "require_stop_loss": True
        }
    )
    db_session.add(user)
    db_session.commit()

    # Query back
    queried_user = db_session.query(User).filter_by(username=username).first()
    assert queried_user is not None
    assert queried_user.profile is not None
    assert queried_user.profile.rules_json["max_trades_per_day"] == 3
    assert queried_user.profile.rules_json["max_risk_per_trade_pct"] == 1.5
    assert queried_user.profile.rules_json["require_stop_loss"] is True

    # Cleanup
    db_session.delete(queried_user)
    db_session.commit()


def test_default_trading_rules():
    """Verifies default rules_json contains required rules for TradeZen."""
    rules = default_trading_rules()
    assert "max_trades_per_day" in rules
    assert "max_risk_per_trade_pct" in rules
    assert "require_stop_loss" in rules
    assert rules["max_risk_per_trade_pct"] == 2.0


def test_price_bar_model_fields_and_dict():
    """Verifies PriceBar model fields and to_dict representation."""
    now = datetime(2022, 3, 10, 10, 15, 0)
    bar = PriceBar(
        symbol="INFY",
        timestamp=now,
        open=1821.0,
        high=1821.1,
        low=1817.2,
        close=1818.0,
        volume=21359
    )
    d = bar.to_dict()
    assert d["symbol"] == "INFY"
    assert d["open"] == 1821.0
    assert d["high"] == 1821.1
    assert d["low"] == 1817.2
    assert d["close"] == 1818.0
    assert d["volume"] == 21359
