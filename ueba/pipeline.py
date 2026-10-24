from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CONFIG
from .device import score_device_days
from .detectors import add_rule_signals
from .features import USER_FEATURES, WEB_FEATURES, daily_features
from .generator import make_demo
from .ingest import normalize_events
from .ml import MLEnsemble
from .profiles import score_against_profile
from .risk import fuse_risk


def _model_fingerprint(start: pd.Timestamp, end: pd.Timestamp, columns: list[str], learn_days: int) -> dict:
    return {
        "start": start.strftime("%Y-%m-%d"), "training_end": end.strftime("%Y-%m-%d"),
        "features": columns, "learning_days": learn_days,
        "seed": CONFIG.random_seed, "iforest_trees": CONFIG.iforest_trees,
        "lof_neighbors": CONFIG.lof_neighbors, "autoencoder_layers": CONFIG.autoencoder_layers,
        "autoencoder_max_iter": CONFIG.autoencoder_max_iter,
    }


def run(events: pd.DataFrame | None = None, *,
        benign_verdicts: set[tuple[str, str]] | None = None,
        threat_verdicts: set[tuple[str, str]] | None = None,
        learning_days: int | None = None,
        model_path: str | Path | None = None,
        previous_scores: pd.DataFrame | None = None,
        previous_device_scores: pd.DataFrame | None = None,
        changed_from: str | None = None,
        force_retrain: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run causal batch or incremental analysis and preserve accepted-day decisions.

    Labels never enter profile fitting or model training. They remain in output
    solely to evaluate the synthetic demo; analyst verdicts affect quarantine.
    """
    normalized = normalize_events(events if events is not None else make_demo())
    user, device = daily_features(normalized)
    if user.empty:
        return normalized, user, device
    benign_verdicts = benign_verdicts or set()
    threat_verdicts = threat_verdicts or set()
    learn_days = int(learning_days or CONFIG.learning_days)
    dates = pd.to_datetime(user["date"])
    first_day = dates.min()
    learning_end = first_day + pd.Timedelta(days=learn_days)
    learning_complete = dates.max() >= learning_end
    training_mask = dates < learning_end
    has_web = normalized["event_type"].eq("web").any()
    feature_columns = USER_FEATURES + (WEB_FEATURES if has_web else [])
    fingerprint = _model_fingerprint(first_day, learning_end, feature_columns, learn_days)
    model: MLEnsemble | None = None

    if model_path is not None:
        model_file = Path(model_path)
        metadata_file = model_file.with_suffix(".json")
        if learning_complete and model_file.exists() and metadata_file.exists() and not force_retrain:
            try:
                if json.loads(metadata_file.read_text()) == fingerprint:
                    model = MLEnsemble.load(model_file)
            except (OSError, ValueError, TypeError, EOFError):
                model = None
    if model is None and learning_complete and int(training_mask.sum()) >= 8:
        model = MLEnsemble(CONFIG.random_seed, CONFIG.iforest_trees, CONFIG.lof_neighbors,
                           CONFIG.autoencoder_layers, CONFIG.autoencoder_max_iter)
        # The train mask is based only on time. Ground-truth labels are never read here.
        model.fit(user.loc[training_mask, feature_columns])
        if model_path is not None:
            model.save(model_path)
            Path(model_path).with_suffix(".json").write_text(json.dumps(fingerprint, indent=2))

    existing = previous_scores.copy() if previous_scores is not None else pd.DataFrame()
    if changed_from is None and not existing.empty:
        old_keys = set(zip(existing["user"].astype(str), existing["date"].astype(str)))
        new_dates = [day for entity, day in zip(user["user"].astype(str), user["date"].astype(str))
                     if (entity, day) not in old_keys]
        changed_from = min(new_dates) if new_dates else str(user["date"].max())
    changed_from = str(changed_from or user["date"].min())
    if not existing.empty and changed_from < str(learning_end.date()):
        # A change to the training window invalidates the saved baseline model.
        if model_path is not None and Path(model_path).exists():
            Path(model_path).unlink()
            Path(model_path).with_suffix(".json").unlink(missing_ok=True)
        return run(normalized, benign_verdicts=benign_verdicts, threat_verdicts=threat_verdicts,
                   learning_days=learn_days, model_path=model_path, force_retrain=True)

    kept = existing[pd.to_datetime(existing["date"]).dt.strftime("%Y-%m-%d") < changed_from].copy() if not existing.empty else pd.DataFrame()
    accepted: dict[tuple[str, str], bool] = {}
    risk_state: dict[str, tuple[float, str | None]] = {}
    if not kept.empty:
        if "accepted_for_learning" in kept:
            accepted.update({(str(r.user), str(r.date)): bool(r.accepted_for_learning) for r in kept.itertuples()})
        else:
            accepted.update({(str(r.user), str(r.date)): float(r.daily_risk) < CONFIG.quarantine_risk and not bool(r.rule_score)
                             for r in kept.itertuples()})
        for entity, group in kept.sort_values("date").groupby("user"):
            last = group.iloc[-1]
            risk_state[str(entity)] = (float(last.get("accumulated_risk", 0)), str(last["date"]))

    monitor_mask = ~training_mask
    ml_scores = model.score(user.loc[monitor_mask, feature_columns]) if model is not None and monitor_mask.any() else pd.DataFrame()
    output_days: list[pd.DataFrame] = [kept] if not kept.empty else []
    sorted_days = [day for day in sorted(user["date"].unique()) if str(day) >= changed_from]
    index_by_key = {(str(r.user), str(r.date)): i for i, r in user[["user", "date"]].iterrows()}
    for day in sorted_days:
        indices = list(user.index[user["date"].eq(day)])
        today = user.loc[indices].copy()
        personal_history: dict[str, list[int]] = {}
        peer_history: dict[str, list[int]] = {}
        for key, index in index_by_key.items():
            if accepted.get(key, False) and key[1] < str(day):
                personal_history.setdefault(str(user.at[index, "user"]), []).append(index)
                peer_history.setdefault(str(user.at[index, "department"]), []).append(index)
        stat_scores: list[float] = []
        explanations: list[str] = []
        peer_scores: list[float] = []
        peer_explanations: list[str] = []
        for index, row in today.iterrows():
            personal = personal_history.get(str(row["user"]), [])[-CONFIG.history_days:]
            if len(personal) >= CONFIG.minimum_history_days:
                score, reason = score_against_profile(user.loc[index, feature_columns], user.loc[personal, feature_columns])
                stat_scores.append(score)
                explanations.append(reason)
            else:
                stat_scores.append(0.0)
                explanations.append("Not enough accepted personal history to establish a baseline.")
            peers = peer_history.get(str(row["department"]), [])
            if len(peers) >= CONFIG.minimum_history_days:
                score, reason = score_against_profile(user.loc[index, feature_columns], user.loc[peers, feature_columns])
                peer_scores.append(score)
                peer_explanations.append(reason.replace("median", f"{row['department']} peer median"))
            else:
                peer_scores.append(0.0)
                peer_explanations.append("No earlier peer baseline yet.")
        today["stat_score"] = stat_scores
        today["explanation"] = explanations
        today["peer_score"] = peer_scores
        today["peer_explanation"] = peer_explanations
        today["analysis_mode"] = "learning" if pd.Timestamp(day) < learning_end else "monitoring"
        today["ml_score"] = 0.0
        if not ml_scores.empty:
            for column in ml_scores.columns:
                today[column] = ml_scores[column].reindex(today.index).fillna(0.0)
        department_criticality = today["department"].map(dict(CONFIG.criticality)).fillna(1.0)
        administrator_criticality = np.maximum(department_criticality, 1.3)
        today["criticality"] = np.where(today["admin_events"] > 0, administrator_criticality,
                                        department_criticality)
        today = add_rule_signals(today)
        today = fuse_risk(today, CONFIG.alert_threshold, risk_state, CONFIG)
        risk_state = today.attrs.get("risk_state", risk_state)
        for index, row in today.iterrows():
            key = (str(row["user"]), str(row["date"]))
            if key in threat_verdicts:
                accepted[key] = False
            elif key in benign_verdicts:
                accepted[key] = True
            else:
                accepted[key] = float(row["daily_risk"]) < CONFIG.quarantine_risk and float(row["rule_score"]) < 0.2
        today["accepted_for_learning"] = [accepted[(str(r.user), str(r.date))] for r in today.itertuples()]
        output_days.append(today)
    scores = pd.concat(output_days).sort_values(["user", "date"]).reset_index(drop=True) if output_days else pd.DataFrame()
    device_model_path = Path(model_path).with_name("device_model.joblib") if model_path is not None else None
    device_scores = score_device_days(device, learning_days=learn_days, model_path=device_model_path,
                                      previous_scores=previous_device_scores, changed_from=changed_from,
                                      force_retrain=force_retrain)
    return normalized, scores, device_scores


def ensure_demo_file(path: str | Path) -> Path:
    target = Path(path)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        make_demo().to_csv(target, index=False)
    return target
