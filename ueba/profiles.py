from __future__ import annotations

import numpy as np
import pandas as pd


def robust_profile(values: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return column-wise median and robust scale, including an IQR-tail term."""
    med = values.median()
    mad = (values - med).abs().median() * 1.4826
    p95_tail = (values.quantile(0.95) - med) / 1.645
    floor = pd.Series(1.0, index=values.columns)
    scale = pd.concat([mad, p95_tail, floor], axis=1).max(axis=1)
    return med, scale


def score_against_profile(current: pd.Series, history: pd.DataFrame) -> tuple[float, str]:
    """Return a bounded three-largest-deviation score and its plain-language reason."""
    med, scale = robust_profile(history.astype(float))
    z = ((current.astype(float) - med) / scale).sort_values(ascending=False)
    positive = z.clip(lower=0)
    top = positive.iloc[:3].to_numpy()
    top = np.pad(top, (0, max(0, 3 - len(top))))
    score = float(np.clip(1.0 - np.exp(-(top[0] + 0.5 * top[1] + 0.25 * top[2]) / 4.0), 0, 1))
    feature = str(z.index[0])
    explanation = f"{feature}: {float(current[feature]):.1f} today vs {float(med[feature]):.1f} median ({max(float(z.iloc[0]), 0):.1f} robust spreads above normal)."
    return score, explanation


def deviations_by_entity(frame: pd.DataFrame, key: str, columns: list[str], min_history: int = 5) -> pd.DataFrame:
    """Score each day from that entity's earlier observations only."""
    result = frame.copy()
    result["stat_score"] = 0.0
    result["top_deviation"] = "No prior baseline"
    result["explanation"] = "Not enough earlier days to establish a baseline."
    for entity, indices in result.groupby(key, sort=False).groups.items():
        indices = list(indices)
        for position, index in enumerate(indices):
            history_indices = indices[max(0, position - 45):position]
            if len(history_indices) < min_history:
                continue
            history = result.loc[history_indices, columns].astype(float)
            current = result.loc[index, columns].astype(float)
            med, scale = robust_profile(history)
            z = (current - med) / scale
            ordered = z.sort_values(ascending=False)
            positive = ordered.clip(lower=0)
            largest = float(positive.iloc[0])
            second = float(positive.iloc[1]) if len(positive) > 1 else 0.0
            third = float(positive.iloc[2]) if len(positive) > 2 else 0.0
            score = 1.0 - np.exp(-(largest + 0.5 * second + 0.25 * third) / 4.0)
            feature = str(ordered.index[0])
            typical = float(med[feature])
            observed = float(current[feature])
            result.at[index, "stat_score"] = float(np.clip(score, 0, 1))
            result.at[index, "top_deviation"] = feature
            result.at[index, "explanation"] = (
                f"{feature}: {observed:.1f} today vs {typical:.1f} personal median "
                f"({largest:.1f} robust spreads above normal)."
            )
    return result


def peer_deviations(frame: pd.DataFrame, columns: list[str], min_history: int = 5) -> pd.DataFrame:
    """Score each user-day against earlier days from the same department."""
    result = frame.copy()
    result["peer_score"] = 0.0
    result["peer_explanation"] = "No earlier peer baseline yet."
    for (department, day), current in result.groupby(["department", "date"], sort=True):
        prior = result[(result["department"] == department) & (result["date"] < day)]
        if len(prior) < min_history:
            continue
        history = prior[columns].astype(float)
        med, scale = robust_profile(history)
        z = (current[columns].astype(float) - med) / scale
        positive = np.clip(z.to_numpy(), 0, None)
        ordered = np.sort(positive, axis=1)[:, ::-1]
        while ordered.shape[1] < 3:
            ordered = np.pad(ordered, ((0, 0), (0, 3 - ordered.shape[1])))
        scores = 1.0 - np.exp(-(ordered[:, 0] + 0.5 * ordered[:, 1] + 0.25 * ordered[:, 2]) / 4.0)
        top_indices = np.argmax(positive, axis=1)
        explanations = [f"{columns[int(i)]} is unusual compared with earlier {department} peer-days." for i in top_indices]
        result.loc[current.index, "peer_score"] = np.clip(scores, 0, 1)
        result.loc[current.index, "peer_explanation"] = explanations
    return result
