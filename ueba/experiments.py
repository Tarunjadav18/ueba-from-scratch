"""Threshold, signal-ablation, and multi-seed experiments for labelled demos."""
from __future__ import annotations

import gc
import tempfile
import time
from pathlib import Path

import pandas as pd

from .config import CONFIG
from .evaluate import evaluate
from .risk import fuse_risk


DEFAULT_THRESHOLDS = tuple(range(10, 101, 5))
ROBUSTNESS_SEEDS = (42, 7, 123, 2024, 99)
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


def evaluate_robustness(seeds: tuple[int, ...] = ROBUSTNESS_SEEDS,
                        threshold: float = CONFIG.alert_threshold,
                        learning_days: int | None = None) -> dict:
    """Retrain the full pipeline for each synthetic seed and summarize held-out results.

    Each run regenerates the synthetic organization, including membership,
    department/habit assignments, attack victims, and incident timing. It then
    retrains and scores both user-days and device-days for that organization.
    """
    from .generator import make_demo
    from .pipeline import run

    runs: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="ueba-robustness-") as temporary:
        for seed in seeds:
            started = time.perf_counter()
            print(f"[robustness] Scoring seed {seed}...", flush=True)
            events = make_demo(seed=seed)
            model_path = Path(temporary) / str(seed) / "user_model.joblib"
            _, user_scores, device_scores = run(
                events, learning_days=learning_days, model_path=model_path, force_retrain=True,
            )
            devices_for_eval = device_scores.rename(columns={"device": "user"})
            combined = pd.concat([user_scores, devices_for_eval], ignore_index=True, sort=False)
            metrics = evaluate(combined, threshold)
            experiments = evaluate_experiments(combined, threshold)
            runs.append({
                "seed": int(seed),
                "evaluation": metrics,
                "component_ablations": experiments.get("component_ablations", {}),
            })
            print(f"[robustness] Seed {seed}: F1={metrics.get('f1')} in {time.perf_counter() - started:.1f}s", flush=True)
            del events, user_scores, device_scores, devices_for_eval, combined
            gc.collect()

    metric_names = ("precision", "recall", "f1", "false_positive_rate", "roc_auc",
                    "pr_auc", "alerts_per_day")
    summary: dict[str, dict[str, float | None]] = {}
    for key in metric_names:
        values = [run["evaluation"].get(key) for run in runs]
        numeric = [float(value) for value in values if value is not None]
        summary[key] = {
            "mean": round(sum(numeric) / len(numeric), 4) if numeric else None,
            "min": round(min(numeric), 4) if numeric else None,
            "max": round(max(numeric), 4) if numeric else None,
        }
    ablation_names = sorted({
        name for run in runs for name in run["component_ablations"]
    })
    summary["ablation_f1"] = {
        name: round(sum(values) / len(values), 4)
        for name in ablation_names
        if (values := [run["component_ablations"][name]["f1"] for run in runs
                       if run["component_ablations"].get(name, {}).get("f1") is not None])
    }
    return {
        "status": "ok" if runs and all(run["evaluation"].get("status") == "ok" for run in runs) else "incomplete",
        "threshold": float(threshold),
        "seeds": [int(seed) for seed in seeds],
        "scope": "Combined held-out user-days and device-days. Each seed regenerates organization membership, departments, habits, attack victims, and timing before retraining the pipeline.",
        "summary": summary,
        "runs": runs,
    }
