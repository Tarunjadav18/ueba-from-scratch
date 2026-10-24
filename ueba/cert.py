"""Adapter for CERT r4.2 event CSVs; message and file contents are never read."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from .ingest import normalize_events


def _column(frame: pd.DataFrame, *names: str) -> pd.Series:
    normalized = {"".join(ch for ch in str(col).lower() if ch.isalnum()): col for col in frame.columns}
    for name in names:
        key = "".join(ch for ch in name.lower() if ch.isalnum())
        if key in normalized:
            return frame[normalized[key]]
    return pd.Series("", index=frame.index, dtype="object")


def _read_rows(path: Path, max_rows: int | None, family: str | None = None) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    allowed = {
        "logon": {"id", "date", "user", "pc", "activity"},
        "device": {"id", "date", "user", "pc", "activity"},
        "file": {"id", "date", "user", "pc", "filename", "activity"},
        "http": {"id", "date", "user", "pc", "url"},
        "email": {"id", "date", "user", "pc", "size", "attachments"},
        "ldap": {"user_id", "user", "username", "department", "functional_unit", "business_unit"},
    }
    usecols = None
    if family in allowed:
        wanted = {"".join(ch for ch in value if ch.isalnum()) for value in allowed[family]}
        usecols = lambda col: "".join(ch for ch in str(col).lower() if ch.isalnum()) in wanted
    return pd.read_csv(path, nrows=max_rows, low_memory=False, usecols=usecols)


def _ldap_departments(root: Path, max_rows: int | None) -> dict[str, str]:
    files = sorted(path for path in root.rglob("*.csv") if "ldap" in str(path.parent).lower())
    mapping: dict[str, str] = {}
    for path in files:
        frame = _read_rows(path, max_rows, "ldap")
        users = _column(frame, "user_id", "user", "username")
        departments = _column(frame, "department", "functional_unit", "business_unit")
        for user, department in zip(users, departments):
            user, department = str(user).strip().lower(), str(department).strip()
            if user and user != "nan" and department and department != "nan":
                mapping[user] = department
    return mapping


def _event_rows(root: Path, kind: str, max_rows: int | None,
                departments: dict[str, str]) -> pd.DataFrame:
    frame = _read_rows(root / f"{kind}.csv", max_rows, kind)
    if frame.empty:
        return pd.DataFrame()
    user = _column(frame, "user", "username", "user_id").fillna("").astype(str).str.strip().str.lower()
    pc = _column(frame, "pc", "computer", "device").fillna("").astype(str).str.strip().str.lower()
    timestamp = _column(frame, "date", "timestamp", "time")
    action = _column(frame, "activity", "action", "event_type").fillna("").astype(str).str.strip()
    event_id = _column(frame, "id", "event_id")
    out = pd.DataFrame({
        "timestamp": timestamp, "user": user, "device": pc, "host": pc,
        "department": user.map(departments).fillna("Unknown"), "event_id": event_id,
        "count": 1, "label": 0, "scenario": "", "has_ground_truth": False,
        "result": "success",
    }, index=frame.index)

    if kind == "logon":
        keep = ~action.str.lower().str.contains("logoff|logout", regex=True)
        out = out.loc[keep].copy()
        out["event_type"] = "auth"
        out["result"] = action.loc[keep].str.lower().map(
            lambda value: "failure" if "fail" in value or "denied" in value else "success")
    elif kind == "device":
        out["event_type"] = "usb"
        out["usb_device"] = "external-storage"
        out["command"] = action
    elif kind == "file":
        filename = _column(frame, "filename", "file_name", "path").fillna("").astype(str)
        out["event_type"] = "access"
        out["file_name"] = filename
        out["command"] = action
        # The action/type field is metadata. No document bytes or message bodies are opened.
        out["is_sensitive"] = filename.str.lower().str.contains(
            r"payroll|finance|confidential|secret|executive", regex=True)
    elif kind == "http":
        urls = _column(frame, "url", "domain").fillna("").astype(str)
        domains = urls.map(lambda value: (urlsplit(value if "://" in value else "https://" + value).hostname or "").lower())
        out["event_type"] = "web"
        out["domain"] = domains
        # Store the hostname only; omit URL paths, queries, and the source's content field.
        out["url"] = domains.map(lambda value: f"https://{value}/" if value else "")
    elif kind == "email":
        sizes = pd.to_numeric(_column(frame, "size", "bytes", "message_size"), errors="coerce").fillna(0)
        attachments = pd.to_numeric(_column(frame, "attachments", "attachment_count"), errors="coerce").fillna(0)
        out["event_type"] = "network"
        out["category"] = "email-metadata"
        out["bytes_out"] = sizes
        out["count"] = 1 + attachments.clip(lower=0)
    else:
        raise ValueError(f"Unsupported CERT event family: {kind}")
    return out


def load_cert_directory(path: str | Path, *, max_rows_per_file: int | None = 100_000,
                        label_intervals: str | Path | None = None) -> pd.DataFrame:
    """Convert CERT r4.2 logon/device/file/http/email CSVs to canonical UEBA events.

    ``max_rows_per_file`` defaults to a 100,000-row sample so large CERT HTTP
    logs do not unexpectedly exhaust a laptop. Pass ``None`` to read every row.
    Optional ``label_intervals`` must be a CSV with ``user``, ``start`` and
    ``end`` columns (and optionally ``scenario``); its intervals are applied
    only after event conversion and are never passed into detector features.
    """
    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"CERT data directory not found: {root}")
    departments = _ldap_departments(root, max_rows_per_file)
    frames = [
        _event_rows(root, family, max_rows_per_file, departments)
        for family in ("logon", "device", "file", "http", "email")
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise ValueError("No supported CERT CSV files found (expected logon/device/file/http/email.csv).")
    events = pd.concat(frames, ignore_index=True, sort=False)

    if label_intervals is not None:
        intervals = pd.read_csv(label_intervals, low_memory=False)
        interval_user = _column(intervals, "user", "user_id", "username").astype(str).str.strip().str.lower()
        starts = pd.to_datetime(_column(intervals, "start", "start_date"), errors="coerce", utc=True)
        ends = pd.to_datetime(_column(intervals, "end", "end_date"), errors="coerce", utc=True)
        scenarios = _column(intervals, "scenario", "threat").astype(str)
        event_user = events["user"].astype(str).str.lower()
        event_time = pd.to_datetime(events["timestamp"], errors="coerce", utc=True)
        events["has_ground_truth"] = True
        for user, start, end, scenario in zip(interval_user, starts, ends, scenarios):
            if pd.isna(start) or pd.isna(end) or not user:
                continue
            matched = event_user.eq(user) & event_time.between(start, end, inclusive="both")
            events.loc[matched, "label"] = 1
            events.loc[matched, "scenario"] = scenario
    return normalize_events(events)
