from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from ueba.evaluate import evaluate
from ueba.experiments import evaluate_experiments


def render(ctx: dict) -> None:
    st.title("Model performance")
    scores = ctx["scores"]
    if scores.empty:
        st.info("No model scores yet.")
        return
    threshold = st.slider("What-if alert threshold", 0, 100, 45)
    metrics = evaluate(scores, threshold)
    if metrics.get("status") != "ok":
        st.info(metrics.get("status"))
        return
    cols = st.columns(5)
    for col, label, key in zip(cols, ["Precision", "Recall", "F1", "ROC-AUC", "PR-AUC"],
                               ["precision", "recall", "f1", "roc_auc", "pr_auc"]):
        value = metrics.get(key)
        col.metric(label, "—" if value is None else f"{value:.3f}")
    st.caption(f"{metrics['alerts_per_day']:.2f} alerts/day · {metrics['false_positive_rate']:.3%} false-positive rate · "
               f"{metrics['attack_scenarios_detected']} planted scenarios detected. Use this only for labelled demo data.")
    if scores["label"].astype(int).nunique() < 2:
        st.info("This workspace has no mixed ground-truth labels. Threshold-free performance metrics are unavailable.")
        return
    experiments = evaluate_experiments(scores, threshold=threshold)
    rows = []
    for cut, result in experiments["threshold_sweep"].items():
        rows.append({"threshold": cut, "precision": result["precision"], "recall": result["recall"],
                     "F1": result["f1"], "alerts/day": result["alerts_per_day"]})
    st.subheader("Threshold trade-off")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.subheader(f"Signal ablation at threshold {threshold}")
    ablations = []
    for variant, result in experiments["component_ablations"].items():
        ablations.append({"variant": variant, "precision": result["precision"],
                          "recall": result["recall"], "F1": result["f1"],
                          "false positives": result["false_positive"],
                          "alerts/day": result["alerts_per_day"]})
    st.dataframe(pd.DataFrame(ablations), use_container_width=True, hide_index=True)
    st.caption(experiments["note"])

    report_path = Path(ctx["workspace_root"]).parent / "reports" / ctx["workspace"] / "robustness.json"
    if report_path.exists():
        robustness = json.loads(report_path.read_text())
        st.subheader("Robustness across synthetic seeds")
        rows = []
        for result in robustness.get("runs", []):
            values = result.get("evaluation", {})
            rows.append({"seed": result.get("seed"), "precision": values.get("precision"),
                         "recall": values.get("recall"), "F1": values.get("f1"),
                         "PR-AUC": values.get("pr_auc"), "false-positive rate": values.get("false_positive_rate"),
                         "alerts/day": values.get("alerts_per_day")})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(robustness.get("scope", "Synthetic seed results."))
    else:
        st.info("To add the five-seed robustness table here, run `python run_pipeline.py --robustness` locally for this workspace.")
