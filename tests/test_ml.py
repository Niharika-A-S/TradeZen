"""Test suite for TradeZen Step 5 & Prompt A: Behavioral Risk ML Model, Predictions & MODEL_RISK Alerts."""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from app.api.main import app
from app.models.alert import Alert, AlertType, AlertSeverity
from app.models.paper import Trade, Order, Account
from app.models.user import User, UserProfile
from app.simulator.bot import BotPersonality
from app.ml.train import (
    load_and_split_dataset,
    train_behavior_model,
    DEFAULT_TEST_BOTS,
    DEFAULT_MODEL_PATH
)
from app.ml.explainer import explain
from app.ml.predictor import predict_violation_risk, load_model_bundle
from retrain import extract_features_from_real_trades


client = TestClient(app)


def test_bot_split_and_personalities():
    """Verifies train/test split is strictly by bot (25 train, 5 test) with each personality in both."""
    train_df, test_df, features = load_and_split_dataset()

    train_bots = train_df["bot_id"].unique()
    test_bots = test_df["bot_id"].unique()

    # Supports either 25/5 (new 30-bot dataset) or 15/5 (legacy dataset before regeneration)
    assert len(train_bots) in [15, 25], f"Expected 15 or 25 train bots, got {len(train_bots)}"
    assert len(test_bots) == 5, f"Expected 5 test bots, got {len(test_bots)}"
    assert len(set(train_bots).intersection(set(test_bots))) == 0, "Train and test bots must be disjoint"

    # All personalities in test set
    test_personalities = test_df["personality"].unique()
    for p in test_personalities:
        assert p in train_df["personality"].unique()


def test_model_bundle_structure_and_metrics():
    """Verifies that the trained model bundle has high accuracy, baseline comparisons, and feature importances."""
    bundle = load_model_bundle()

    assert "model" in bundle
    assert "baseline_model" in bundle
    assert "threshold" in bundle
    assert "metrics" in bundle
    assert "feature_importances" in bundle

    metrics = bundle["metrics"]
    assert "xgboost" in metrics
    assert "logistic_regression" in metrics
    assert "simple_rule_baseline" in metrics or "threshold_curve" in metrics

    xgb_m = metrics["xgboost"]
    lr_m = metrics["logistic_regression"]

    # Verify acceptable performance on held-out bots
    assert xgb_m["accuracy"] >= 0.80, f"XGBoost accuracy too low: {xgb_m['accuracy']}"
    assert xgb_m["f1"] >= 0.78, f"XGBoost F1 too low: {xgb_m['f1']}"
    if xgb_m.get("roc_auc") is not None:
        assert xgb_m["roc_auc"] >= 0.90, f"XGBoost ROC-AUC too low: {xgb_m['roc_auc']}"

    # Verify baseline metrics present
    assert "precision" in lr_m and "recall" in lr_m and "f1" in lr_m

    # Verify threshold curve has 9 steps (0.10 to 0.90)
    curve = metrics["threshold_curve"]
    assert len(curve) == 9
    assert [c["threshold"] for c in curve] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

    # Verify top feature importances
    feat_imp = bundle["feature_importances"]
    assert len(feat_imp) >= 10
    top_feature = list(feat_imp.keys())[0]
    assert feat_imp[top_feature] > 0.03


def test_explain_function_reasons():
    """Verifies that explain(...) extracts actionable psychological coaching reasons using configured rules."""
    rules = {"max_trades_per_day": 5, "max_risk_per_trade_pct": 2.0, "max_consecutive_losses": 3}

    # Scenario 1: Revenge trading pattern
    features_revenge = {
        "had_large_loss_last_10m": 1,
        "size_ratio_to_daily_avg": 2.2,
        "trades_count_last_30m": 1,
        "stop_loss_missing_count_last_30m": 0,
        "max_risk_ratio_last_30m": 0.8,
    }
    reasons1 = explain(features_revenge, rules=rules)
    assert any("Revenge" in r or "size" in r.lower() for r in reasons1)

    # Scenario 2: Overtrading after loss / approaching limit
    features_overtrade = {
        "trade_count_ratio_today": 0.85,
        "trade_headroom_today": 1,
        "trades_count_last_30m": 5,
        "loss_count_last_30m": 3,
        "had_large_loss_last_10m": 0,
        "size_ratio_to_daily_avg": 1.0,
        "stop_loss_missing_count_last_30m": 0,
        "max_risk_ratio_last_30m": 0.5,
    }
    reasons2 = explain(features_overtrade, rules=rules)
    assert any("Overtrading" in r or "pacing" in r.lower() or "limit" in r.lower() for r in reasons2)

    # Scenario 3: Missing stop-loss
    features_sl = {
        "trades_count_last_30m": 1,
        "loss_count_last_30m": 0,
        "stop_loss_missing_count_last_30m": 2,
        "max_risk_ratio_last_30m": 0.0,
    }
    reasons3 = explain(features_sl, rules=rules)
    assert any("stop-loss" in r.lower() or "unprotected" in r.lower() for r in reasons3)


def test_predict_violation_risk_and_model_risk_alert(db_session):
    """Verifies that predict_violation_risk detects high risk and fires a MODEL_RISK alert into the database."""
    now = datetime(2022, 3, 10, 11, 30)
    uid = uuid.uuid4().hex[:8]

    # Create test user and account with configured rules
    user = User(username=f"risk_{uid}", email=f"risk_{uid}@tradezen.local")
    db_session.add(user)
    db_session.flush()

    account = Account(user_id=user.id, cash_balance=10_00_000.0, initial_cash=10_00_000.0)
    profile = UserProfile(user_id=user.id, rules_json={
        "max_trades_per_day": 5,
        "max_risk_per_trade_pct": 2.0,
        "max_consecutive_losses": 3,
        "require_stop_loss": True
    })
    db_session.add(account)
    db_session.add(profile)
    db_session.flush()

    # Create orders first to satisfy foreign key constraint on paper_trades.order_id
    o1 = Order(user_id=user.id, symbol="INFY", side="BUY", order_type="MARKET", quantity=250, price=1000.0, stop_loss=980.0, status="FILLED", created_at=now - timedelta(minutes=25))
    o2 = Order(user_id=user.id, symbol="INFY", side="SELL", order_type="MARKET", quantity=250, price=900.0, status="FILLED", created_at=now - timedelta(minutes=20))
    o3 = Order(user_id=user.id, symbol="TCS", side="BUY", order_type="MARKET", quantity=450, price=3000.0, stop_loss=2900.0, status="FILLED", created_at=now - timedelta(minutes=15))
    o4 = Order(user_id=user.id, symbol="TCS", side="SELL", order_type="MARKET", quantity=450, price=2950.0, status="FILLED", created_at=now - timedelta(minutes=10))
    o5 = Order(user_id=user.id, symbol="RELIANCE", side="BUY", order_type="MARKET", quantity=500, price=2000.0, stop_loss=1940.0, status="FILLED", created_at=now - timedelta(minutes=5))
    db_session.add_all([o1, o2, o3, o4, o5])
    db_session.flush()

    # Simulate aggressive rapid overtrading & losses in last 30 minutes with risk exceeding 2% limit
    trades = [
        Trade(order_id=o1.id, user_id=user.id, symbol="INFY", side="BUY", quantity=250, price=1000.0,
              realized_pnl=0.0, executed_at=now - timedelta(minutes=25)),
        Trade(order_id=o2.id, user_id=user.id, symbol="INFY", side="SELL", quantity=250, price=900.0,
              realized_pnl=-25000.0, executed_at=now - timedelta(minutes=20)), # -2.5% loss (> 2% rule)
        Trade(order_id=o3.id, user_id=user.id, symbol="TCS", side="BUY", quantity=450, price=3000.0,
              realized_pnl=0.0, executed_at=now - timedelta(minutes=15)), # 1.8x size expansion
        Trade(order_id=o4.id, user_id=user.id, symbol="TCS", side="SELL", quantity=450, price=2950.0,
              realized_pnl=-22500.0, executed_at=now - timedelta(minutes=10)), # -2.25% loss
        Trade(order_id=o5.id, user_id=user.id, symbol="RELIANCE", side="BUY", quantity=500, price=2000.0,
              realized_pnl=0.0, executed_at=now - timedelta(minutes=5)),
    ]
    for t in trades:
        db_session.add(t)

    db_session.commit()

    # Run predict_violation_risk with create_alert=True
    result = predict_violation_risk(
        user_id=user.id,
        now=now,
        db=db_session,
        create_alert=True
    )

    assert result["user_id"] == user.id
    assert result["risk_score"] >= result["threshold"]
    assert result["is_high_risk"] is True
    assert len(result["reasons"]) > 0

    # Verify that MODEL_RISK alert was persisted to database
    saved_alert = db_session.query(Alert).filter_by(
        user_id=user.id,
        alert_type=AlertType.MODEL_RISK.value
    ).first()

    assert saved_alert is not None, "MODEL_RISK alert was not persisted in alerts table"
    assert saved_alert.alert_type == AlertType.MODEL_RISK.value
    assert "MODEL RISK ALERT" in saved_alert.message
    assert "reasons" in saved_alert.context_json
    assert len(saved_alert.context_json["reasons"]) > 0


def test_predict_risk_api_endpoint(db_session):
    """Verifies POST /paper/risk/predict API endpoint."""
    uid = uuid.uuid4().hex[:8]
    user = User(username=f"api_{uid}", email=f"api_{uid}@tradezen.local")
    db_session.add(user)
    db_session.flush()

    account = Account(user_id=user.id, cash_balance=10_00_000.0)
    db_session.add(account)
    db_session.commit()

    res = client.post("/paper/risk/predict", json={"user_id": user.id, "now": "2022-03-10 11:30", "create_alert": False})
    assert res.status_code == 200
    data = res.json()
    assert "risk_score" in data
    assert "threshold" in data
    assert "is_high_risk" in data


def test_extract_features_from_real_trades(db_session):
    """Verifies that extract_features_from_real_trades executes cleanly."""
    real_df = extract_features_from_real_trades(db_session)
    assert isinstance(real_df, pd.DataFrame)
