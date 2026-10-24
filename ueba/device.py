"""Incremental device-day analysis with 19 features and D01-D05 rules."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CONFIG
from .detectors import add_device_rule_signals
from .features import DEVICE_FEATURES
from .ml import MLEnsemble
from .profiles import score_against_profile
from .risk import fuse_risk


def score_device_days(frame: pd.DataFrame, *, learning_days: int = 30,
                      model_path: str | Path | None = None,
                      previous_scores: pd.DataFrame | None = None,
                      changed_from: str | None = None,
                      force_retrain: bool = False) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy().sort_values(["device", "date"]).reset_index(drop=True)
    dates = pd.to_datetime(result["date"])
    first_day = dates.min()
    learning_end = first_day + pd.Timedelta(days=learning_days)
    learning_complete = dates.max() >= learning_end
    fingerprint = {"start": first_day.strftime("%Y-%m-%d"), "end": learning_end.strftime("%Y-%m-%d"),
                   "features": DEVICE_FEATURES, "learning_days": learning_days,
                   "seed": CONFIG.random_seed, "trees": CONFIG.iforest_trees, "neighbors": CONFIG.lof_neighbors,
                   "autoencoder_layers": CONFIG.autoencoder_layers,
                   "autoencoder_max_iter": CONFIG.autoencoder_max_iter}
    model = None
    if model_path and learning_complete and not force_retrain:
        target = Path(model_path)
        meta = target.with_suffix(".json")
        if target.exists() and meta.exists():
            try:
                if json.loads(meta.read_text()) == fingerprint:
                    model = MLEnsemble.load(target)
            except (OSError, ValueError, TypeError, EOFError):
                model = None
    train_mask = dates < learning_end
    if model is None and learning_complete and int(train_mask.sum()) >= 8:
        model = MLEnsemble(CONFIG.random_seed, CONFIG.iforest_trees, CONFIG.lof_neighbors,
                           CONFIG.autoencoder_layers, CONFIG.autoencoder_max_iter)
        model.fit(result.loc[train_mask, DEVICE_FEATURES])
        if model_path:
            target = Path(model_path)
            model.save(target)
            target.with_suffix(".json").write_text(json.dumps(fingerprint, indent=2))

    existing = previous_scores.copy() if previous_scores is not None else pd.DataFrame()
    changed_from = str(changed_from or (existing["date"].max() if not existing.empty else result["date"].min()))
    if not existing.empty and changed_from < str(learning_end.date()):
        existing = pd.DataFrame()
        if model_path:
            Path(model_path).unlink(missing_ok=True)
            Path(model_path).with_suffix(".json").unlink(missing_ok=True)
            model = None
            if learning_complete and int(train_mask.sum()) >= 8:
                model = MLEnsemble(CONFIG.random_seed, CONFIG.iforest_trees, CONFIG.lof_neighbors,
                                   CONFIG.autoencoder_layers, CONFIG.autoencoder_max_iter)
                model.fit(result.loc[train_mask, DEVICE_FEATURES])
                model.save(model_path)
                Path(model_path).with_suffix(".json").write_text(json.dumps(fingerprint, indent=2))
    kept = existing[pd.to_datetime(existing["date"]).dt.strftime("%Y-%m-%d") < changed_from].copy() if not existing.empty else pd.DataFrame()
    accepted: set[tuple[str, str]] = set()
    risk_state: dict[str, tuple[float, str | None]] = {}
    if not kept.empty:
        if "accepted_for_learning" in kept:
            accepted = {(str(r.device), str(r.date)) for r in kept.itertuples() if bool(r.accepted_for_learning)}
        for device, group in kept.sort_values("date").groupby("device"):
            last = group.iloc[-1]
            risk_state[str(device)] = (float(last.get("accumulated_risk", 0)), str(last["date"]))
    monitor_mask = ~train_mask
    ml_scores = model.score(result.loc[monitor_mask, DEVICE_FEATURES]) if model is not None and monitor_mask.any() else pd.DataFrame()
    key_to_index = {(str(r.device), str(r.date)): i for i, r in result[["device", "date"]].iterrows()}
    output = [kept] if not kept.empty else []
    for day in [day for day in sorted(result["date"].unique()) if str(day) >= changed_from]:
        ids = list(result.index[result["date"].eq(day)])
        today = result.loc[ids].copy()
        history_by_device: dict[str, list[int]] = {}
        for key, index in key_to_index.items():
            if key in accepted and key[1] < str(day):
                history_by_device.setdefault(key[0], []).append(index)
        statistical: list[float] = []
        explanations: list[str] = []
        for index, row in today.iterrows():
            hist = history_by_device.get(str(row["device"]), [])[-CONFIG.history_days:]
            if len(hist) >= CONFIG.minimum_history_days:
                score, explanation = score_against_profile(result.loc[index, DEVICE_FEATURES], result.loc[hist, DEVICE_FEATURES])
                statistical.append(score)
                explanations.append(explanation)
            else:
                statistical.append(0.0)
                explanations.append("Not enough accepted device history to establish a baseline.")
        today["stat_score"] = statistical
        today["explanation"] = explanations
        today["peer_score"] = 0.0
        today["peer_explanation"] = ""
        today["analysis_mode"] = "learning" if pd.Timestamp(day) < learning_end else "monitoring"
        today["ml_score"] = 0.0
        if not ml_scores.empty:
            for column in ml_scores.columns:
                today[column] = ml_scores[column].reindex(today.index).fillna(0.0)
        today["criticality"] = np.where(today["device"].str.startswith("server"),
                                        dict(CONFIG.criticality).get("IT-Admin", 1.3), 1.0)
        today = add_device_rule_signals(today)
        risk_input = fuse_risk(today.rename(columns={"device": "user"}), CONFIG.alert_threshold,
                               risk_state, CONFIG)
        risk_state = risk_input.attrs.get("risk_state", risk_state)
        today = risk_input.rename(columns={"user": "device"})
        for _, row in today.iterrows():
            key = (str(row["device"]), str(row["date"]))
            if float(row["daily_risk"]) < CONFIG.quarantine_risk and float(row["rule_score"]) < 0.2:
                accepted.add(key)
        today["accepted_for_learning"] = [(str(row.device), str(row.date)) in accepted for row in today.itertuples()]
        output.append(today)
    return pd.concat(output).sort_values(["device", "date"]).reset_index(drop=True) if output else pd.DataFrame()
