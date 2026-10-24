"""Periodic collector: import inbox data, incrementally score, update cases, notify."""
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .cases import sync_cases
from .feedback import verdict_sets
from .notify import send_alerts
from .pipeline import run
from .storage import audit
from .workspace import WorkspaceManager


class Collector:
    def __init__(self, root: str | Path = "data/workspaces", interval: int = 10):
        self.manager = WorkspaceManager(root)
        self.root = self.manager.root
        self.db_path = self.root.parent / "console.db"
        self.interval = interval

    def run_once(self) -> dict:
        report = {"at": datetime.now(timezone.utc).isoformat(), "workspaces": [], "errors": []}
        for item in self.manager.list():
            name = item["slug"]
            try:
                imported, errors, changed_from = self.manager.import_inbox(name)
                entry = {"workspace": name, "imported_events": imported, "errors": errors, "state": self.manager.status(name)["state"]}
                if imported:
                    events = self.manager.read_events(name)
                    workspace_path = self.manager.get(name)
                    scores_path = workspace_path / "scores.csv"
                    device_scores_path = workspace_path / "device_scores.csv"
                    previous = pd.read_csv(scores_path) if scores_path.exists() else None
                    previous_devices = pd.read_csv(device_scores_path) if device_scores_path.exists() else None
                    manifest = json.loads((workspace_path / "workspace.json").read_text())
                    benign, threats = verdict_sets(self.db_path, name)
                    _, scores, devices = run(
                        events,
                        benign_verdicts=benign,
                        threat_verdicts=threats,
                        learning_days=int(manifest["learning_days"]),
                        model_path=workspace_path / "models" / "user_model.joblib",
                        previous_scores=previous,
                        previous_device_scores=previous_devices,
                        changed_from=changed_from,
                    )
                    scores_tmp = scores_path.with_suffix(".csv.tmp")
                    device_tmp = device_scores_path.with_suffix(".csv.tmp")
                    scores.to_csv(scores_tmp, index=False)
                    devices.to_csv(device_tmp, index=False)
                    scores_tmp.replace(scores_path)
                    device_tmp.replace(device_scores_path)
                    open_alerts = scores[scores["alert"] | scores["sustained_alert"]]
                    cases_created = sync_cases(self.db_path, name, open_alerts)
                    device_alerts = devices[devices["alert"]].rename(columns={"device": "user"})
                    notify_rows = pd.concat([open_alerts, device_alerts], ignore_index=True, sort=False)
                    notifications = send_alerts(self.db_path, name, notify_rows)
                    manifest["last_analysis_at"] = datetime.now(timezone.utc).isoformat()
                    manifest["last_error"] = errors[-1] if errors else None
                    (workspace_path / "workspace.json").write_text(json.dumps(manifest, indent=2))
                    entry.update({
                        "events": len(events), "user_days": len(scores), "device_days": len(devices),
                        "alerts": len(open_alerts), "new_cases": cases_created,
                        "notification_attempts": len(notifications), "state": self.manager.status(name)["state"],
                    })
                    audit(self.db_path, "collector_analysis", "service", name,
                          f"imported={imported}; user_alerts={len(open_alerts)}; device_alerts={len(device_alerts)}")
                report["workspaces"].append(entry)
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                report["errors"].append({"workspace": name, "error": detail})
                try:
                    path = self.manager.get(name)
                    manifest_path = path / "workspace.json"
                    manifest = json.loads(manifest_path.read_text())
                    manifest["last_error"] = detail
                    manifest_path.write_text(json.dumps(manifest, indent=2))
                    (path / "service-error.log").write_text(traceback.format_exc())
                except Exception:
                    pass
        heartbeat = {"at": report["at"], "ok": not report["errors"], "workspaces": len(report["workspaces"]), "errors": report["errors"]}
        (self.root / "service.json").write_text(json.dumps(heartbeat, indent=2))
        return report

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(self.interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the UEBA inbox collector.")
    parser.add_argument("--root", default="data/workspaces")
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    service = Collector(args.root, args.interval)
    if args.once:
        print(json.dumps(service.run_once(), indent=2))
    else:
        service.run_forever()


if __name__ == "__main__":
    main()
