"""CLI script to train and evaluate the TradeZen behavioral risk model (Prompt A)."""
import time
import pandas as pd
from app.ml.train import train_behavior_model


def main():
    print("=" * 75)
    print("TradeZen Prompt A: Behavioral Risk Model Training & 3-Way Comparative Evaluation")
    print("=" * 75)

    t0 = time.time()
    bundle = train_behavior_model()
    t1 = time.time()

    print(f"\nModel training and evaluation completed in {t1 - t0:.2f} seconds.")
    print(f"Train Bots: {len(bundle['train_bots'])} bots ({bundle['train_bots']})")
    print(f"Test Bots : {len(bundle['test_bots'])} held-out bots ({bundle['test_bots']})")

    # 1. Overall Model Comparison Table
    print("\n" + "=" * 75)
    print("1. OVERALL COMPARISON ON HELD-OUT BOTS (25 Train Bots / 5 Test Bots)")
    print("=" * 75)
    srb_m = bundle["metrics"]["simple_rule_baseline"]
    lr_m = bundle["metrics"]["logistic_regression"]
    xgb_m = bundle["metrics"]["xgboost"]

    def _fmt_auc(val):
        return f"{val:.4f}" if val is not None else "N/A"

    metrics_df = pd.DataFrame([
        {
            "Model": "Simple-Rule Baseline",
            "Precision": f"{srb_m['precision']*100:.2f}%",
            "Recall": f"{srb_m['recall']*100:.2f}%",
            "F1-Score": f"{srb_m['f1']*100:.2f}%",
            "Accuracy": f"{srb_m['accuracy']*100:.2f}%",
            "ROC-AUC": _fmt_auc(srb_m['roc_auc']),
        },
        {
            "Model": "Logistic Regression",
            "Precision": f"{lr_m['precision']*100:.2f}%",
            "Recall": f"{lr_m['recall']*100:.2f}%",
            "F1-Score": f"{lr_m['f1']*100:.2f}%",
            "Accuracy": f"{lr_m['accuracy']*100:.2f}%",
            "ROC-AUC": _fmt_auc(lr_m['roc_auc']),
        },
        {
            "Model": "XGBoost (Primary ML)",
            "Precision": f"{xgb_m['precision']*100:.2f}%",
            "Recall": f"{xgb_m['recall']*100:.2f}%",
            "F1-Score": f"{xgb_m['f1']*100:.2f}%",
            "Accuracy": f"{xgb_m['accuracy']*100:.2f}%",
            "ROC-AUC": _fmt_auc(xgb_m['roc_auc']),
        }
    ])
    print(metrics_df.to_string(index=False))

    # 2. Per-Personality Comparative Evaluation Table
    print("\n" + "=" * 75)
    print("2. PER-PERSONALITY COMPARATIVE EVALUATION (Held-out Test Bots)")
    print("=" * 75)
    per_p = bundle["metrics"]["per_personality"]
    p_rows = []
    for p_name, data in per_p.items():
        s_pos = data["support_pos"]
        s_neg = data["support_neg"]
        base = data["baseline_rule"]
        lr = data["logistic_regression"]
        xgb = data["xgboost"]

        p_rows.append({
            "Personality": p_name,
            "Support (+/-)": f"{s_pos}/{s_neg}",
            "Rule F1": f"{base['f1']*100:.1f}%",
            "LR F1": f"{lr['f1']*100:.1f}%",
            "XGB F1": f"{xgb['f1']*100:.1f}%",
            "Rule AUC": _fmt_auc(base['roc_auc']),
            "LR AUC": _fmt_auc(lr['roc_auc']),
            "XGB AUC": _fmt_auc(xgb['roc_auc']),
        })
    p_df = pd.DataFrame(p_rows)
    print(p_df.to_string(index=False))

    # 3. Top Feature Importances
    print("\n" + "=" * 75)
    print("3. TOP 10 BEHAVIORAL FEATURE IMPORTANCES (XGBoost)")
    print("=" * 75)
    for i, (col, imp) in enumerate(list(bundle["feature_importances"].items())[:10], 1):
        bar = "#" * int(imp * 40)
        print(f"  {i:2d}. {col:32s} {imp:6.4f}  {bar}")
    print("=" * 75)


if __name__ == "__main__":
    main()
