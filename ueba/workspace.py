"""Isolated per-dataset workspaces, inbox processing, and lifecycle state."""
from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd

from .ingest import load_events


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    """Process-safe file lock on macOS/Linux so import and analysis do not overlap."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class WorkspaceManager:
    def __init__(self, root: str | Path | None = None):
        data_root = Path(os.environ.get("UEBA_DATA_DIR", "data"))
        self.root = Path(root) if root is not None else data_root / "workspaces"
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, learning_days: int = 30) -> Path:
        slug = _slug(name)
        path = self.root / slug
        path.mkdir(parents=True, exist_ok=True)
        for child in ("inbox", "failed", "processed", "models", "reports"):
            (path / child).mkdir(exist_ok=True)
        manifest = path / "workspace.json"
        if not manifest.exists():
            manifest.write_text(json.dumps({
                "name": name, "slug": slug, "created_at": datetime.now(timezone.utc).isoformat(),
                "learning_days": int(learning_days), "last_import_at": None,
                "last_analysis_at": None, "last_error": None,
            }, indent=2))
        return path

    def get(self, name: str) -> Path:
        path = self.root / _slug(name)
        if not path.exists():
            raise FileNotFoundError(f"Workspace '{name}' does not exist.")
        return path

    def list(self) -> list[dict]:
        rows = []
        for path in sorted(self.root.iterdir()):
            manifest = path / "workspace.json"
            if path.is_dir() and manifest.exists():
                rows.append(self.status(path.name))
        return rows

    def status(self, name: str) -> dict:
        path = self.get(name)
        info = json.loads((path / "workspace.json").read_text())
        event_file = path / "events.csv"
        if not event_file.exists() or event_file.stat().st_size == 0:
            state, days, events = "No data", 0, 0
        else:
            data = pd.read_csv(event_file, usecols=["timestamp"])
            events = len(data)
            timestamps = pd.to_datetime(data["timestamp"], errors="coerce", utc=True).dropna()
            days = int(timestamps.dt.date.nunique())
            span = (timestamps.max().date() - timestamps.min().date()).days if days else 0
            state = "Monitoring" if span >= int(info["learning_days"]) else "Learning"
        if state == "No data" and any((path / "inbox").iterdir()):
            state = "New data"
        return {**info, "state": state, "days": days, "events": events}

    def queue_file(self, workspace: str, source: str | Path) -> Path:
        path = self.get(workspace)
        incoming = Path(source)
        if not incoming.is_file():
            raise FileNotFoundError(incoming)
        target = path / "inbox" / incoming.name
        if target.exists():
            target = path / "inbox" / f"{incoming.stem}-{datetime.now().strftime('%Y%m%d%H%M%S')}{incoming.suffix}"
        shutil.copy2(incoming, target)
        return target

    def import_inbox(self, workspace: str) -> tuple[int, list[str], str | None]:
        path = self.get(workspace)
        imported = 0
        errors: list[str] = []
        earliest_changed: str | None = None
        with _lock(path / ".workspace.lock"):
            for source in sorted((path / "inbox").iterdir()):
                if not source.is_file() or source.name.endswith(".error.txt"):
                    continue
                try:
                    events = load_events(source)
                    if len(events):
                        changed = events["timestamp"].min().strftime("%Y-%m-%d")
                        earliest_changed = min(earliest_changed, changed) if earliest_changed else changed
                    target = path / "events.csv"
                    events.to_csv(target, mode="a" if target.exists() else "w", header=not target.exists(), index=False)
                    shutil.move(str(source), path / "processed" / source.name)
                    imported += len(events)
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                    errors.append(f"{source.name}: {reason}")
                    failed = path / "failed" / source.name
                    shutil.move(str(source), failed)
                    failed.with_suffix(failed.suffix + ".error.txt").write_text(reason)
            manifest_path = path / "workspace.json"
            manifest = json.loads(manifest_path.read_text())
            if imported:
                manifest["last_import_at"] = datetime.now(timezone.utc).isoformat()
            if errors:
                manifest["last_error"] = errors[-1]
            manifest_path.write_text(json.dumps(manifest, indent=2))
        return imported, errors, earliest_changed

    def read_events(self, workspace: str) -> pd.DataFrame:
        path = self.get(workspace)
        event_file = path / "events.csv"
        if not event_file.exists():
            return pd.DataFrame()
        return load_events(event_file)
