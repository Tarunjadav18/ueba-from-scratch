from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Central operational and analytics settings."""

    history_days: int = 45
    minimum_history_days: int = 5
    learning_days: int = 30
    z_threshold: float = 3.0
    alert_threshold: float = 45.0
    noise_floor: float = 15.0
    risk_half_life_days: float = 3.0
    quarantine_risk: float = 60.0
    sustained_risk_threshold: float = 60.0
    weight_statistics: float = 0.28
    weight_peer: float = 0.10
    weight_ml: float = 0.30
    max_impossible_travel_kmh: float = 900.0
    criticality: tuple[tuple[str, float], ...] = (
        ("IT-Admin", 1.3), ("Finance", 1.2), ("Management", 1.2), ("HR", 1.1),
    )
    iforest_trees: int = 300
    lof_neighbors: int = 25
    autoencoder_layers: tuple[int, ...] = (16, 6, 16)
    autoencoder_max_iter: int = 800
    random_seed: int = 42


CONFIG = Config()
