from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from ueba.generator import make_demo
from ueba.evaluate import evaluate
from ueba.ingest import load_events, normalize_events
from ueba.pipeline import run
from ueba.workspace import WorkspaceManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and analyze the UEBA demo organization.")
    parser.add_argument("--input", help="Optional CSV/JSON/JSONL/ZIP event export")
    parser.add_argument("--workspace", default="demo", help="Workspace name for saving this run")
    parser.add_argument("--output", default="data/reports", help="Folder for score and feature CSV exports")
    args = parser.parse_args()

    events = load_events(args.input) if args.input else normalize_events(make_demo())
    manager = WorkspaceManager()
    workspace_path = manager.create(args.workspace)
    raw, user_scores, device_scores = run(events, model_path=workspace_path / "models" / "user_model.joblib", force_retrain=True)
    output = Path(args.output) / args.workspace
    output.mkdir(parents=True, exist_ok=True)
    raw.to_csv(output / "events.csv", index=False)
    user_scores.to_csv(output / "user_day_scores.csv", index=False)
    device_scores.to_csv(output / "device_day_features.csv", index=False)
    raw.to_csv(workspace_path / "events.csv", index=False)
    user_scores.to_csv(workspace_path / "scores.csv", index=False)
    device_scores.to_csv(workspace_path / "device_scores.csv", index=False)
    metrics = evaluate(user_scores)
    (output / "evaluation.json").write_text(json.dumps(metrics, indent=2))
    summary = {
        "workspace": args.workspace,
        "events": len(raw),
        "users": int(user_scores["user"].nunique()),
        "user_days": len(user_scores),
        "alerts": int(user_scores["alert"].sum()),
        "monitoring_alerts": int((user_scores["alert"] & user_scores["analysis_mode"].eq("monitoring")).sum()),
        "learning_days": int(user_scores.loc[user_scores["analysis_mode"].eq("learning"), "date"].nunique()),
        "evaluation": metrics,
        "output": str(output.resolve()),
    }
    print(pd.Series(summary).to_string())
    print(f"\nTop alerts: {output / 'user_day_scores.csv'}")


if __name__ == "__main__":
    main()
