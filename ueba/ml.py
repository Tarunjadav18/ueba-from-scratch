"""Unsupervised anomaly ensemble trained on an initial normal-behavior window."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd


class MLEnsemble:
    """Isolation Forest, novelty LOF, and a small reconstruction autoencoder."""

    def __init__(self, seed: int = 42, trees: int = 300, neighbors: int = 25,
                 autoencoder_layers: tuple[int, ...] = (16, 6, 16), autoencoder_max_iter: int = 800):
        self.seed = seed
        self.trees = trees
        self.neighbors = neighbors
        self.autoencoder_layers = autoencoder_layers
        self.autoencoder_max_iter = autoencoder_max_iter
        self.models: dict[str, object] = {}
        self.scaler = None
        self.calibration: dict[str, tuple[float, float]] = {}
        self.columns: list[str] = []

    def fit(self, values: pd.DataFrame) -> "MLEnsemble":
        # Avoid joblib's unreliable macOS physical-core probe in managed shells.
        os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")
        from sklearn.ensemble import IsolationForest
        from sklearn.neighbors import LocalOutlierFactor
        from sklearn.neural_network import MLPRegressor
        from sklearn.preprocessing import StandardScaler

        clean = values.replace([np.inf, -np.inf], np.nan).fillna(0).astype(float)
        self.columns = list(clean.columns)
        self.scaler = StandardScaler()
        scaled = self.scaler.fit_transform(clean)
        if len(clean) < 8:
            raise ValueError("The unsupervised ensemble needs at least eight learning rows.")
        self.models = {
            "iforest": IsolationForest(n_estimators=self.trees, random_state=self.seed, contamination="auto", n_jobs=1),
            "lof": LocalOutlierFactor(n_neighbors=max(2, min(self.neighbors, len(clean) - 1)), novelty=True),
            "autoencoder": MLPRegressor(hidden_layer_sizes=self.autoencoder_layers, activation="tanh", solver="adam",
                                         max_iter=self.autoencoder_max_iter, random_state=self.seed, early_stopping=True,
                                         validation_fraction=0.15, alpha=1e-3),
        }
        self.models["iforest"].fit(scaled)
        self.models["lof"].fit(scaled)
        self.models["autoencoder"].fit(scaled, scaled)
        raw = self._raw_scaled(scaled)
        for name, scores in raw.items():
            median = float(np.median(scores))
            q99 = float(np.quantile(scores, 0.99))
            self.calibration[name] = (median, max(q99 - median, 1e-9))
        return self

    def _raw_scaled(self, scaled: np.ndarray) -> dict[str, np.ndarray]:
        reconstruction = self.models["autoencoder"].predict(scaled)
        return {
            "iforest": -self.models["iforest"].score_samples(scaled),
            "lof": -self.models["lof"].score_samples(scaled),
            "autoencoder": np.mean((scaled - reconstruction) ** 2, axis=1),
        }

    def score(self, values: pd.DataFrame) -> pd.DataFrame:
        if self.scaler is None:
            raise RuntimeError("Call fit() before score().")
        clean = values.reindex(columns=self.columns).replace([np.inf, -np.inf], np.nan).fillna(0).astype(float)
        raw = self._raw_scaled(self.scaler.transform(clean))
        out: dict[str, np.ndarray] = {}
        for name, scores in raw.items():
            median, spread = self.calibration[name]
            normalized = (scores - median) / spread
            out[f"ml_{name}"] = np.clip((normalized - 1.0) / 3.0, 0.0, 1.0)
        result = pd.DataFrame(out, index=values.index)
        result["ml_score"] = result.mean(axis=1)
        return result

    def save(self, path: str | Path) -> None:
        import joblib
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        joblib.dump(self, temporary)
        temporary.replace(target)

    @classmethod
    def load(cls, path: str | Path) -> "MLEnsemble":
        import joblib
        model = joblib.load(path)
        if not isinstance(model, cls):
            raise TypeError("Saved model file is not a UEBA MLEnsemble.")
        return model
