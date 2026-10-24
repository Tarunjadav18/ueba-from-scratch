from __future__ import annotations

import numpy as np
import pandas as pd
from .config import CONFIG, Config


def fuse_risk(frame: pd.DataFrame, threshold: float = 45.0,
              previous_state: dict[str, tuple[float, str | None]] | None = None,
              cfg: Config = CONFIG) -> pd.DataFrame:
    """Fuse personal, peer, ML, and rule evidence into a bounded risk score."""
    out = frame.copy()
    # Missing layers start at zero; probabilistic OR keeps evidence interpretable.
    stat = out["stat_score"].clip(0, 1)
    peer = out.get("peer_score", pd.Series(0.0, index=out.index)).clip(0, 1)
    ml = out.get("ml_score", pd.Series(0.0, index=out.index)).clip(0, 1)
    rule = out["rule_score"].clip(0, 1)
    risk_probability = (1 - (1 - cfg.weight_statistics * stat)
                        * (1 - cfg.weight_peer * peer)
                        * (1 - cfg.weight_ml * ml) * (1 - rule))
    criticality = out.get("criticality", pd.Series(1.0, index=out.index)).fillna(1.0).clip(upper=1.3)
    out["daily_risk"] = (100 * (risk_probability * criticality).clip(upper=1.0)).round(1)
    accumulated = []
    crossed_sustained_threshold = []
    state = dict(previous_state or {})
    for _, group in out.sort_values(["user", "date"]).groupby("user", sort=False):
        entity = str(group.iloc[0]["user"])
        current, previous_date = state.get(entity, (0.0, None))
        for _, row in group.iterrows():
            previous_risk = current
            day = pd.Timestamp(row["date"])
            prior = pd.Timestamp(previous_date) if previous_date else None
            gap = 1 if prior is None else max(1, (day - prior).days)
            current *= 0.5 ** (gap / cfg.risk_half_life_days)
            current = min(100.0, current + max(0.0, float(row["daily_risk"]) - cfg.noise_floor))
            accumulated.append((row.name, round(current, 1)))
            crossed_sustained_threshold.append((row.name, previous_risk < cfg.sustained_risk_threshold
                                               <= current))
            previous_date = day.strftime("%Y-%m-%d")
        state[entity] = (current, previous_date)
    if accumulated:
        risk_by_index = dict(accumulated)
        out["accumulated_risk"] = [risk_by_index.get(i, 0.0) for i in out.index]
    else:
        out["accumulated_risk"] = 0.0
    monitoring = out.get("analysis_mode", pd.Series("monitoring", index=out.index)).eq("monitoring")
    out["alert"] = (out["daily_risk"] >= threshold) & monitoring
    crossed = dict(crossed_sustained_threshold)
    out["sustained_alert"] = pd.Series(crossed).reindex(out.index, fill_value=False) & monitoring & ~out["alert"]
    out["alert"] = out["alert"] | out["sustained_alert"]
    out["alert_reason"] = out.apply(
        lambda row: "; ".join(part for part in [row.get("explanation", ""),
            row.get("peer_explanation", ""), row.get("rule_names", "")]
            if part and part != "No earlier peer baseline yet."), axis=1
    )
    out.attrs["risk_state"] = state
    return out
