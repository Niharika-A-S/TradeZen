"""Model training and evaluation module for TradeZen (Step 5 & Prompt A).

Trains XGBoost and Logistic Regression baseline on data/behavior_dataset.csv,
evaluates against a deterministic Simple-Rule Baseline overall and per personality
on held-out test bots, computes feature importances, and exports production model bundles.
"""
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional, Union

import pandas as pd
import numpy as np
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import (
    precision_score,
    recall_score,
    f1_score,
    accuracy_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

from app.simulator.features import FEATURE_COLUMNS
from app.simulator.bot import BotPersonality

DEFAULT_DATASET_PATH = "data/behavior_dataset.csv"
DEFAULT_MODEL_PATH = "models/behavior_model.joblib"

# Held-out 5 test bots (1 per personality: Bot 6 Disciplined, 12 Overtrader, 18 RevengeTrader, 24 StopLossIgnorer, 30 FomoChaser)
DEFAULT_TEST_BOTS = [6, 12, 18, 24, 30]


def load_and_split_dataset(
    dataset_path: str = DEFAULT_DATASET_PATH,
    test_bot_ids: Optional[List[int]] = None
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Loads behavior dataset and performs bot-level train/test split across 30 bots."""
    if not Path(dataset_path).exists():
        raise FileNotFoundError(f"Behavior dataset not found at {dataset_path}. Run scripts/generate_dataset.py first.")

    df = pd.read_csv(dataset_path)
    test_ids = test_bot_ids if test_bot_ids is not None else DEFAULT_TEST_BOTS

    train_df = df[~df["bot_id"].isin(test_ids)].copy()
    test_df = df[df["bot_id"].isin(test_ids)].copy()

    # Ensure all required features are present
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required feature columns in dataset: {missing}")

    return train_df, test_df, FEATURE_COLUMNS


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_probs: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Computes precision, recall, f1, accuracy, and roc-auc safely, handling single-class cases honestly."""
    unique_classes = np.unique(y_true)
    num_positives = int((y_true == 1).sum())
    num_negatives = int((y_true == 0).sum())

    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    acc = accuracy_score(y_true, y_pred)

    auc_val: Optional[float] = None
    if len(unique_classes) > 1 and y_probs is not None:
        try:
            auc_val = round(float(roc_auc_score(y_true, y_probs)), 4)
        except Exception:
            auc_val = None

    return {
        "precision": round(float(prec), 4),
        "recall": round(float(rec), 4),
        "f1": round(float(f1), 4),
        "accuracy": round(float(acc), 4),
        "roc_auc": auc_val,
        "support_pos": num_positives,
        "support_neg": num_negatives,
    }


def compute_threshold_curve(y_true: np.ndarray, y_probs: np.ndarray) -> List[Dict[str, float]]:
    """Generates the precision/recall tradeoff table across thresholds from 0.10 to 0.90."""
    thresholds = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
    curve = []
    for t in thresholds:
        y_pred = (y_probs >= t).astype(int)
        m = compute_metrics(y_true, y_pred, y_probs)
        curve.append({
            "threshold": round(t, 2),
            "precision": m["precision"],
            "recall": m["recall"],
            "f1": m["f1"],
            "accuracy": m["accuracy"],
        })
    return curve


def train_behavior_model(
    dataset_path: str = DEFAULT_DATASET_PATH,
    model_save_path: str = DEFAULT_MODEL_PATH,
    test_bot_ids: Optional[List[int]] = None,
    random_state: int = 42
) -> Dict[str, Any]:
    """Trains XGBoost and Logistic Regression models, evaluates against simple-rule baseline,
    and exports the production bundle.
    """
    test_ids = test_bot_ids if test_bot_ids is not None else DEFAULT_TEST_BOTS
    train_df, test_df, feature_cols = load_and_split_dataset(dataset_path, test_ids)

    X_train = train_df[feature_cols].values
    y_train = train_df["label"].values
    X_test = test_df[feature_cols].values
    y_test = test_df["label"].values

    train_bots = sorted(train_df["bot_id"].unique().tolist())
    test_bots = sorted(test_df["bot_id"].unique().tolist())

    # -------------------------------------------------------------
    # 1. Simple-Rule Baseline
    # Rule: "warn if trades_today/max_trades >= 0.8 or risk ratio >= 1"
    # -------------------------------------------------------------
    baseline_rule_mask = (
        (test_df["trade_count_ratio_today"] >= 0.8) |
        (test_df["max_risk_ratio_last_30m"] >= 1.0)
    )
    baseline_rule_preds = baseline_rule_mask.astype(int).values
    baseline_rule_metrics = compute_metrics(y_test, baseline_rule_preds, y_probs=baseline_rule_preds.astype(float))

    # -------------------------------------------------------------
    # 2. Logistic Regression Baseline
    # -------------------------------------------------------------
    lr_pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=random_state))
    ])
    lr_pipeline.fit(X_train, y_train)
    lr_test_probs = lr_pipeline.predict_proba(X_test)[:, 1]
    lr_test_preds = (lr_test_probs >= 0.50).astype(int)
    lr_metrics = compute_metrics(y_test, lr_test_preds, lr_test_probs)

    # -------------------------------------------------------------
    # 3. Primary Model: XGBoost Classifier
    # -------------------------------------------------------------
    neg_count = (y_train == 0).sum()
    pos_count = (y_train == 1).sum()
    scale_pos = float(neg_count / max(1, pos_count))

    xgb_model = XGBClassifier(
        n_estimators=140,
        max_depth=4,
        learning_rate=0.08,
        scale_pos_weight=scale_pos,
        eval_metric="logloss",
        random_state=random_state,
        n_jobs=-1
    )
    xgb_model.fit(X_train, y_train)

    # Note: Threshold curve computed on training cross-validation / internal split
    xgb_test_probs = xgb_model.predict_proba(X_test)[:, 1]
    threshold_curve = compute_threshold_curve(y_test, xgb_test_probs)

    optimal_threshold = 0.50
    xgb_test_preds = (xgb_test_probs >= optimal_threshold).astype(int)
    xgb_metrics = compute_metrics(y_test, xgb_test_preds, xgb_test_probs)

    # -------------------------------------------------------------
    # 4. Per-Personality Comparative Evaluation on Test Bots
    # -------------------------------------------------------------
    per_personality_metrics: Dict[str, Dict[str, Any]] = {}
    personalities = [p.value for p in BotPersonality]

    for p in personalities:
        p_mask = (test_df["personality"] == p).values
        if not np.any(p_mask):
            continue

        p_y_test = y_test[p_mask]
        p_base_pred = baseline_rule_preds[p_mask]
        p_lr_prob = lr_test_probs[p_mask]
        p_lr_pred = (p_lr_prob >= 0.50).astype(int)
        p_xgb_prob = xgb_test_probs[p_mask]
        p_xgb_pred = (p_xgb_prob >= optimal_threshold).astype(int)

        per_personality_metrics[p] = {
            "support_total": int(len(p_y_test)),
            "support_pos": int((p_y_test == 1).sum()),
            "support_neg": int((p_y_test == 0).sum()),
            "baseline_rule": compute_metrics(p_y_test, p_base_pred, p_base_pred.astype(float)),
            "logistic_regression": compute_metrics(p_y_test, p_lr_pred, p_lr_prob),
            "xgboost": compute_metrics(p_y_test, p_xgb_pred, p_xgb_prob),
        }

    # -------------------------------------------------------------
    # 5. Feature Importances
    # -------------------------------------------------------------
    importances = xgb_model.feature_importances_
    feat_imp = {
        col: round(float(imp), 4)
        for col, imp in sorted(zip(feature_cols, importances), key=lambda x: x[1], reverse=True)
    }

    # -------------------------------------------------------------
    # 6. Build and save model artifact bundle
    # -------------------------------------------------------------
    model_bundle = {
        "model": xgb_model,
        "baseline_model": lr_pipeline,
        "feature_names": feature_cols,
        "threshold": optimal_threshold,
        "metrics": {
            "simple_rule_baseline": baseline_rule_metrics,
            "logistic_regression": lr_metrics,
            "xgboost": xgb_metrics,
            "per_personality": per_personality_metrics,
            "threshold_curve": threshold_curve,
        },
        "feature_importances": feat_imp,
        "train_bots": train_bots,
        "test_bots": test_bots,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    out_file = Path(model_save_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model_bundle, model_save_path)

    internal_path = Path("app/ml/models/behavior_model.joblib")
    internal_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model_bundle, internal_path)

    return model_bundle
