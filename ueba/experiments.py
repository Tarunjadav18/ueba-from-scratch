"""Threshold and signal-ablation experiments on already-scored, labelled days."""
from __future__ import annotations

import pandas as pd

from .config import CONFIG
from .evaluate import evaluate
from .risk import fuse_risk


DEFAULT_THRESHOLDS = tuple(range(10, 101, 5))
ABLATIONS = {
    "full_model": (),
    "without_personal_statistics": ("stat_score",),
    "without_peer_profile": ("peer_score",),
    "without_ml_ensemble": ("ml_score",),
    "without_rules": ("rule_score",),
    "rules_only": ("stat_score", "peer_score", "ml_score"),
}


def evaluate_experiments(scores: pd.DataFrame, threshold: float = CONFIG.alert_threshold,
                         thresholds: tuple[int, ...] = DEFAULT_THRESHOLDS) -> dict:
    """Compare alert cutoffs and risk-signal ablations without retraining models."""
    baseline = evaluate(scores, threshold)
    if baseline.get("status") != "ok":
        return {"status": baseline.get("status", "not_evaluated"),
                "threshold_sweep": {}, "component_ablations": {}}

    threshold_sweep = {
        str(cut): evaluate(scores, float(cut))
        for cut in thresholds
    }
    component_ablations = {}
    for name, removed in ABLATIONS.items():
        counterfactual = scores.copy()
        for column in removed:
            if column in counterfactual:
                counterfactual[column] = 0.0
        rescored = fuse_risk(counterfactual, threshold=threshold)
        component_ablations[name] = evaluate(rescored, threshold)

    return {
        "status": "ok",
        "threshold_sweep": threshold_sweep,
        "component_ablations": component_ablations,
        "ablation_threshold": float(threshold),
        "note": "Ablations remove one risk signal from fusion on the same held-out scores; they do not retrain models.",
    }
