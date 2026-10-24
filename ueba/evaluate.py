"""Evaluation helpers: labels are used only after scoring, never for detection."""
from __future__ import annotations

import pandas as pd


def evaluate(scores: pd.DataFrame, threshold: float = 45.0) -> dict:
    if scores.empty or "label" not in scores:
        return {"status": "No labelled days available."}
    if "has_ground_truth" in scores and not scores["has_ground_truth"].fillna(False).astype(bool).any():
        return {"status": "No ground-truth labels supplied; metrics were not calculated."}
    monitor = scores[scores["analysis_mode"].eq("monitoring")].copy()
    if monitor.empty:
        return {"status": "Still in the learning window; no held-out monitoring days to score."}
    truth = monitor["label"].astype(int).to_numpy()
    risk = monitor["daily_risk"].astype(float).to_numpy()
    predicted = risk >= threshold
    predicted_series = pd.Series(predicted, index=monitor.index)
    tp = int(((truth == 1) & predicted).sum())
    fp = int(((truth == 0) & predicted).sum())
    fn = int(((truth == 1) & ~predicted).sum())
    tn = int(((truth == 0) & ~predicted).sum())
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    roc_auc = pr_auc = None
    if len(set(truth)) == 2:
        from sklearn.metrics import average_precision_score, roc_auc_score
        roc_auc = float(roc_auc_score(truth, risk))
        pr_auc = float(average_precision_score(truth, risk))
    scenario = {}
    if "scenario" in monitor:
        for name, group in monitor[monitor["label"].astype(int).eq(1)].groupby("scenario"):
            scenario[str(name)] = {
                "malicious_user_days": int(len(group)),
                "detected_user_days": int(predicted_series.reindex(group.index, fill_value=False).sum()),
                "detected_users": int(group.loc[predicted_series.reindex(group.index, fill_value=False), "user"].nunique()),
            }
    alerts_per_day = float(predicted.sum() / max(1, monitor["date"].nunique()))
    detected = monitor["label"].astype(int).eq(1) & predicted_series
    detected_scenarios = int(monitor.loc[detected, "scenario"].nunique()) if "scenario" in monitor else int(monitor.loc[detected, "user"].nunique())
    return {
        "status": "ok", "threshold": float(threshold), "monitoring_user_days": int(len(monitor)),
        "attack_scenarios_detected": detected_scenarios,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "roc_auc": round(roc_auc, 4) if roc_auc is not None else None,
        "pr_auc": round(pr_auc, 4) if pr_auc is not None else None,
        "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
        "false_positive_rate": round(fp / max(1, fp + tn), 6),
        "alerts_per_day": round(alerts_per_day, 3), "by_scenario": scenario,
    }
