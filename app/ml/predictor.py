"""Prediction module for TradeZen (Step 5 & Prompt A).

Provides predict_violation_risk(user_id, now) that extracts features using the
same build_features function, scores the user using the trained XGBoost model,
and broadcasts a MODEL_RISK alert if risk exceeds threshold.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging
import asyncio

import joblib
import numpy as np
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.alert import Alert, AlertType, AlertSeverity
from app.models.paper import Trade, Order, Account
from app.models.user import UserProfile
from app.simulator.features import build_features, FEATURE_COLUMNS, _normalize_dt
from app.ml.explainer import explain

logger = logging.getLogger(__name__)

# Cached model bundle
_CACHED_MODEL_BUNDLE: Optional[Dict[str, Any]] = None
DEFAULT_MODEL_PATHS = [
    "models/behavior_model.joblib",
    "app/ml/models/behavior_model.joblib",
]


def load_model_bundle(model_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads and caches the trained behavior model bundle.
    
    Validates that the model bundle feature schema matches FEATURE_COLUMNS.
    Does not silently fall back to an incompatible model.
    """
    global _CACHED_MODEL_BUNDLE
    if _CACHED_MODEL_BUNDLE is not None and model_path is None:
        return _CACHED_MODEL_BUNDLE

    target_paths = [model_path] if model_path else DEFAULT_MODEL_PATHS
    for p in target_paths:
        if p and Path(p).exists():
            bundle = joblib.load(p)
            bundle_features = bundle.get("feature_names", [])
            if bundle_features and bundle_features != FEATURE_COLUMNS:
                raise ValueError(
                    f"Model feature mismatch in '{p}': bundle has {len(bundle_features)} features, "
                    f"expected {len(FEATURE_COLUMNS)} features. Model must be retrained."
                )
            _CACHED_MODEL_BUNDLE = bundle
            return _CACHED_MODEL_BUNDLE

    raise FileNotFoundError(
        f"No trained model bundle found. Looked in: {target_paths}. Run scripts/train_model.py first."
    )


def predict_violation_risk(
    user_id: int,
    now: Optional[datetime] = None,
    db: Optional[Session] = None,
    create_alert: bool = True,
    capital_override: Optional[float] = None,
    model_path: Optional[str] = None
) -> Dict[str, Any]:
    """Predicts the probability that the user is about to break a rule.
    
    Calls the SAME build_features function as dataset generation using active user rules.
    If risk >= threshold, creates a MODEL_RISK alert with personalized explanation reasons.
    """
    close_db_on_exit = False
    session = db
    if session is None:
        session = SessionLocal()
        close_db_on_exit = True

    try:
        cur_time = _normalize_dt(now) if now is not None else datetime.now().replace(tzinfo=None)
        today_date = cur_time.date()

        # 1. Fetch capital and active user rules
        account = session.query(Account).filter_by(user_id=user_id).first()
        if capital_override is not None:
            capital = capital_override
        elif account and account.initial_cash:
            capital = account.initial_cash
        elif account:
            capital = account.cash_balance
        else:
            capital = 10_00_000.0

        profile = session.query(UserProfile).filter_by(user_id=user_id).first()
        user_rules = profile.rules_json if (profile and profile.rules_json) else {}

        # 2. Fetch today's executed trades and orders for this user
        all_user_trades = session.query(Trade).filter(
            Trade.user_id == user_id
        ).order_by(Trade.executed_at.asc()).all()

        trades = [
            t for t in all_user_trades
            if _normalize_dt(t.executed_at).date() == today_date
            and _normalize_dt(t.executed_at) <= cur_time
        ]

        all_user_orders = session.query(Order).filter(
            Order.user_id == user_id
        ).order_by(Order.created_at.asc()).all()

        orders = [
            o for o in all_user_orders
            if o.created_at
            and _normalize_dt(o.created_at).date() == today_date
            and _normalize_dt(o.created_at) <= cur_time
        ]

        # 3. Call the SAME build_features function passing user rules
        features = build_features(
            trades_today=trades,
            orders_today=orders,
            current_time=cur_time,
            capital=capital,
            rules=user_rules
        )

        # 4. Load model and predict
        bundle = load_model_bundle(model_path)
        feature_names = bundle.get("feature_names", FEATURE_COLUMNS)
        model = bundle["model"]
        threshold = bundle.get("threshold", 0.50)

        feature_vector = np.array([[features[col] for col in feature_names]])
        prob = float(model.predict_proba(feature_vector)[0, 1])
        is_high_risk = bool(prob >= threshold)

        # 5. Generate reasons using user's configured rules
        reasons = explain(features, rules=user_rules) if is_high_risk else []

        persisted_alert: Optional[Alert] = None
        if is_high_risk and create_alert:
            severity = AlertSeverity.CRITICAL.value if prob >= 0.80 else AlertSeverity.WARNING.value
            reason_text = " | ".join(reasons)
            msg = (
                f"MODEL RISK ALERT ({prob*100:.1f}% risk): Imminent behavioral violation predicted. "
                f"Reasons: {reason_text}"
            )
            persisted_alert = Alert(
                user_id=user_id,
                alert_type=AlertType.MODEL_RISK.value,
                severity=severity,
                message=msg,
                context_json={
                    "risk_score": round(prob, 4),
                    "threshold": round(threshold, 4),
                    "reasons": reasons,
                    "features": features,
                    "evaluated_at": cur_time.isoformat()
                },
                created_at=cur_time
            )
            session.add(persisted_alert)
            session.commit()
            session.refresh(persisted_alert)

            # Broadcast alert to WebSocket listeners
            try:
                from app.api.websocket import broadcast_alert
                alert_dict = persisted_alert.to_dict()
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(broadcast_alert(alert_dict))
                except RuntimeError:
                    asyncio.run(broadcast_alert(alert_dict))
            except Exception as e:
                logger.debug(f"WebSocket broadcast skipped or unavailable: {e}")

        return {
            "user_id": user_id,
            "risk_score": round(prob, 4),
            "threshold": round(threshold, 4),
            "is_high_risk": is_high_risk,
            "reasons": reasons,
            "features": features,
            "alert": persisted_alert.to_dict() if persisted_alert else None
        }

    finally:
        if close_db_on_exit:
            session.close()
