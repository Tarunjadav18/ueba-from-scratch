"""Build the compact, pre-scored synthetic snapshot used by the hosted dashboard."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ueba.generator import make_demo
from ueba.ingest import normalize_events
from ueba.pipeline import run


def main() -> None:
    events, user_scores, device_scores = run(
        normalize_events(make_demo(users=12, days=45))
    )
    destination = ROOT / "dashboard" / "demo_data"
    destination.mkdir(parents=True, exist_ok=True)
    for name, frame in (
        ("events.csv.gz", events),
        ("user_scores.csv.gz", user_scores),
        ("device_scores.csv.gz", device_scores),
    ):
        frame.to_csv(destination / name, index=False, compression="gzip")
    print(
        f"Wrote {len(events):,} events, {len(user_scores):,} user-days, "
        f"and {len(device_scores):,} device-days to {destination}"
    )


if __name__ == "__main__":
    main()
