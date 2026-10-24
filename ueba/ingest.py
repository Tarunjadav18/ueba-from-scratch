from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .sources import read_source

REQUIRED_COLUMNS = {"timestamp"}
STRING_FIELDS = (
    "user", "device", "event_type", "department", "result", "source_ip", "country", "city",
    "host", "domain", "url", "category", "file_name", "share_name", "usb_device", "command", "scenario",
)
NUMERIC_FIELDS = (
    "count", "bytes_out", "bytes_in", "resource_pct", "memory_pct", "disk_pct", "port",
    "pages", "event_id", "label", "device_label", "duration_seconds",
)
DEFAULTS = {
    "user": "unknown-user", "device": "unknown-device", "event_type": "",
    "department": "Unknown", "result": "unknown", "count": 1, "bytes_out": 0.0,
    "bytes_in": 0.0, "resource_pct": 0.0, "memory_pct": 0.0, "disk_pct": 0.0,
    "port": 0, "pages": 0, "lat": None, "lon": None, "label": 0, "device_label": 0,
    "duration_seconds": 900.0, "target_user": "",
    "source_ip": "", "country": "", "city": "", "host": "", "domain": "", "scenario": "",
    "url": "", "category": "", "file_name": "", "share_name": "", "usb_device": "",
    "command": "", "event_id": 0, "blocked": False, "is_sensitive": False,
    "is_admin": False, "executable": False,
    "has_ground_truth": False,
}


def _infer_type(row: pd.Series) -> str:
    explicit = str(row.get("event_type", "")).strip().lower()
    aliases = {
        "authentication": "auth", "login": "auth", "logon": "auth",
        "system_access": "access", "file": "access", "file_access": "access",
        "network_flow": "network", "resource_usage": "resource", "web_proxy": "web",
        "proxy": "web", "usb_device": "usb", "powershell_script": "powershell",
    }
    if explicit and explicit not in {"nan", "none", "unknown"}:
        return aliases.get(explicit, explicit)
    text = " ".join(str(row.get(key, "")) for key in ("event_id", "event_name", "provider", "message", "command")).lower()
    event_id = str(row.get("event_id", ""))
    if event_id in {"4624", "4625", "4627", "4768", "4769", "4771"} or "logon" in text or "login" in text:
        return "auth"
    if event_id in {"4663", "4656", "4660"} or "file" in text or "object access" in text:
        return "access"
    if event_id in {"6416", "2003"} or "usb" in text or "removable" in text:
        return "usb"
    if event_id in {"4672", "4648"} or "privilege" in text or "sudo" in text:
        return "admin"
    if event_id in {"5140", "5145"} or "share" in text:
        return "share"
    if event_id == "307" or "print" in text:
        return "print"
    if event_id in {"4103", "4104", "800"} or "powershell" in text:
        return "powershell"
    if any(row.get(key) not in (None, "", 0) for key in ("url", "domain", "blocked", "category")):
        return "web"
    if any(row.get(key) not in (None, "", 0) for key in ("bytes_out", "bytes_in", "port", "source_ip")):
        return "network"
    if any(row.get(key) not in (None, "", 0) for key in ("resource_pct", "memory_pct", "disk_pct")):
        return "resource"
    return "unknown"


def normalize_events(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize event exports to the shared multi-source schema."""
    data = frame.copy()
    data.columns = [str(c).strip().lower() for c in data.columns]
    # Common source names map into the canonical schema. Preserve explicitly
    # supplied canonical columns when both forms are present.
    for source, target in (("username", "user"), ("hostname", "device"), ("computer", "device"),
                           ("status", "result"), ("outcome", "result"), ("time", "timestamp")):
        if target not in data and source in data:
            data = data.rename(columns={source: target})
    if "has_ground_truth" not in data:
        data["has_ground_truth"] = "label" in data and data["label"].notna().any()
    missing = REQUIRED_COLUMNS - set(data.columns)
    if missing:
        raise ValueError(f"Missing required event columns: {', '.join(sorted(missing))}")
    for field, default in DEFAULTS.items():
        if field not in data:
            data[field] = default
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce", utc=True)
    data = data.dropna(subset=["timestamp"])
    for field in STRING_FIELDS:
        data[field] = data[field].fillna("").astype(str).str.strip()
    for field in NUMERIC_FIELDS:
        data[field] = pd.to_numeric(data[field], errors="coerce")
    data[list(NUMERIC_FIELDS)] = data[list(NUMERIC_FIELDS)].fillna(0)
    for field in ("lat", "lon"):
        if field not in data:
            data[field] = np.nan
        else:
            data[field] = pd.to_numeric(data[field], errors="coerce")
    for field in ("blocked", "is_sensitive", "is_admin", "executable", "has_ground_truth"):
        data[field] = data[field].map(lambda x: str(x).strip().lower() in {"1", "true", "yes", "blocked", "deny"} if not isinstance(x, bool) else x)
    data["event_type"] = data.apply(_infer_type, axis=1)
    data["user"] = data["user"].str.replace(r"^.*\\", "", regex=True).str.lower()
    data["user"] = data["user"].replace("", "unknown-user")
    data["device"] = data["device"].replace("", "unknown-device").str.lower()
    data["department"] = data["department"].replace("", "Unknown")
    data["domain"] = data["domain"].str.lower().str.replace(r"^www\.", "", regex=True)
    data["host"] = data["host"].str.lower()
    # Normalize common Windows and Unix outcomes without discarding the raw event fields.
    data["result"] = data["result"].str.lower().replace({
        "4624": "success", "4625": "failure", "logon success": "success",
        "logon failure": "failure", "allowed": "success", "tcp_denied": "blocked",
    })
    data = data.drop_duplicates(subset=["timestamp", "event_type", "user", "device", "result", "file_name", "url", "count"])
    canonical = ["timestamp", "event_type", "user", "device", "department", "result", "count",
                 "source_ip", "country", "city", "host", "domain", "url", "category", "event_id",
                 "command", "target_user", "file_name", "share_name", "usb_device", "scenario", "bytes_out",
                 "bytes_in", "resource_pct", "memory_pct", "disk_pct", "port", "pages", "lat", "lon",
                 "label", "device_label", "duration_seconds", "blocked", "is_sensitive", "is_admin", "executable",
                 "has_ground_truth"]
    return data[canonical].sort_values("timestamp").reset_index(drop=True)


def parse_linux_auth(path: str | Path, device: str = "linux-host") -> pd.DataFrame:
    """Parse common sshd/PAM auth.log lines into normalized auth events."""
    source = Path(path)
    records = []
    pattern = re.compile(r"^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}).*?(?:sshd|sudo|pam).*?(Accepted|Failed|failure|session opened|session closed).*?(?:for (?:invalid user )?([\w.-]+))?.*?(?:from ([\d.]+))?", re.I)
    year = pd.Timestamp.now(tz="UTC").year
    for line in source.read_text(errors="replace").splitlines():
        match = pattern.search(line)
        if not match:
            continue
        when, outcome, user, ip = match.groups()
        timestamp = pd.to_datetime(f"{year} {when}", format="%Y %b %d %H:%M:%S", errors="coerce", utc=True)
        if pd.isna(timestamp) or not user:
            continue
        result = "success" if outcome.lower().startswith(("accepted", "session opened")) else "failure"
        records.append({"timestamp": timestamp, "event_type": "auth", "user": user,
                        "device": device, "result": result, "source_ip": ip or "", "count": 1})
    if not records:
        return normalize_events(pd.DataFrame(columns=sorted(REQUIRED_COLUMNS)))
    return normalize_events(pd.DataFrame(records))


def load_events(path: str | Path) -> pd.DataFrame:
    """Read supported export files and normalize them."""
    frame, _ = read_source(path)
    return normalize_events(frame)
