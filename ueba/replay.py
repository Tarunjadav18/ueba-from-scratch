"""Replay a dataset through a workspace inbox as an initial history and daily feed."""
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

import pandas as pd

from .generator import make_demo
from .ingest import load_events, normalize_events
from .workspace import WorkspaceManager


def _queue(manager: WorkspaceManager, workspace: str, frame: pd.DataFrame, name: str) -> None:
    with tempfile.TemporaryDirectory(prefix="ueba-replay-") as directory:
        source = Path(directory) / name
        frame.to_json(source, orient="records", date_format="iso")
        manager.queue_file(workspace, source)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay demo or uploaded events into a workspace inbox.")
    parser.add_argument("--workspace", default="live-demo")
    parser.add_argument("--input", help="CSV/JSON/JSONL/ZIP dataset; default is the synthetic organization")
    parser.add_argument("--seconds-per-day", type=float, default=8)
    parser.add_argument("--labels", action="store_true", help="Retain synthetic ground-truth labels for evaluation")
    parser.add_argument("--learning-days", type=int, default=30)
    parser.add_argument("--root", help="Workspace root (default: UEBA_DATA_DIR/workspaces)")
    args = parser.parse_args()
    events = load_events(args.input) if args.input else normalize_events(make_demo())
    if not args.labels:
        events["label"] = 0
        events["scenario"] = ""
    events["date"] = events["timestamp"].dt.strftime("%Y-%m-%d")
    days = sorted(events["date"].unique())
    if not days:
        parser.error("The selected dataset has no valid event dates.")
    manager = WorkspaceManager(args.root)
    manager.create(args.workspace, learning_days=args.learning_days)
    initial_days = days[:args.learning_days]
    initial = events[events["date"].isin(initial_days)].drop(columns=["date"])
    _queue(manager, args.workspace, initial, "replay-history.json")
    print(f"Queued {len(initial)} history events across {len(initial_days)} days to workspace '{args.workspace}'.")
    for day in days[args.learning_days:]:
        daily = events[events["date"].eq(day)].drop(columns=["date"])
        _queue(manager, args.workspace, daily, f"replay-{day}.json")
        print(f"Queued {day}: {len(daily)} events")
        time.sleep(max(0, args.seconds_per_day))


if __name__ == "__main__":
    main()
