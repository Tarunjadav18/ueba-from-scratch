"""Input-file readers and automatic column mapping for common log exports."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

SYNONYMS: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "datetime", "date", "timecreated", "eventtime", "created_at"),
    "event_type": ("event_type", "eventtype", "type", "log_type", "stream"),
    "user": ("user", "username", "account", "targetusername", "subjectusername", "user_name", "principal"),
    "device": ("device", "hostname", "computer", "computername", "workstation", "sourcehost"),
    "host": ("host", "destinationhost", "targethostname", "server", "remotehost"),
    "department": ("department", "dept", "business_unit", "ou"),
    "result": ("result", "status", "action", "outcome", "logonresult"),
    "source_ip": ("source_ip", "src_ip", "ipaddress", "ip_address", "clientip", "sourceaddress"),
    "country": ("country", "country_code", "geo_country"),
    "city": ("city", "location_city"),
    "domain": ("domain", "website", "site", "destination_domain", "fqdn"),
    "url": ("url", "uri", "request_url", "full_url"),
    "category": ("category", "site_category", "web_category"),
    "event_id": ("event_id", "eventid", "id", "eventcode"),
    "command": ("command", "commandline", "processcommandline", "scriptblocktext"),
    "file_name": ("file_name", "filename", "objectname", "path", "targetfilename"),
    "bytes_out": ("bytes_out", "sent_bytes", "bytes_sent", "outbound_bytes", "upload_bytes"),
    "bytes_in": ("bytes_in", "received_bytes", "bytes_received", "inbound_bytes", "download_bytes"),
    "count": ("count", "event_count", "pages", "records"),
    "resource_pct": ("resource_pct", "cpu_percent", "cpu", "cpu_pct", "processor_load"),
}


def map_columns(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Map common vendor/export names to canonical fields; return chosen mapping."""
    data = frame.copy()
    original = {str(col): "".join(ch for ch in str(col).strip().lower() if ch.isalnum() or ch == "_") for col in data.columns}
    norm_to_original = {v: k for k, v in original.items()}
    mapping: dict[str, str] = {}
    for canonical, names in SYNONYMS.items():
        candidates = {"".join(ch for ch in n if ch.isalnum() or ch == "_") for n in names}
        found = next((norm_to_original[n] for n in candidates if n in norm_to_original), None)
        if found is not None and canonical not in data:
            mapping[found] = canonical
    data = data.rename(columns=mapping)
    if "device" not in data and "host" in data:
        data["device"] = data["host"]
    # Windows Security exports often omit a type column but include event IDs.
    if "event_type" not in data and "event_id" in data:
        data["event_type"] = ""
    if "event_type" not in data:
        data["event_type"] = ""
    return data, {old: new for old, new in mapping.items()}


def _load_one(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".jsonl":
        return pd.read_json(path, lines=True)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return pd.DataFrame(payload if isinstance(payload, list) else payload.get("events", []))
    raise ValueError(f"Unsupported file type: {suffix or '(no extension)'}")


def read_source(path: str | Path) -> tuple[pd.DataFrame, dict[str, str]]:
    """Read CSV, JSON, JSONL, or a ZIP containing supported exports."""
    source = Path(path)
    if source.suffix.lower() == ".zip":
        frames = []
        mappings: dict[str, str] = {}
        with zipfile.ZipFile(source) as archive:
            for name in archive.namelist():
                suffix = Path(name).suffix.lower()
                if suffix not in {".csv", ".json", ".jsonl"}:
                    continue
                import io
                with archive.open(name) as stream:
                    if suffix == ".csv":
                        frame = pd.read_csv(io.BytesIO(stream.read()))
                    elif suffix == ".jsonl":
                        frame = pd.read_json(io.BytesIO(stream.read()), lines=True)
                    else:
                        payload = json.loads(stream.read().decode("utf-8"))
                        frame = pd.DataFrame(payload if isinstance(payload, list) else payload.get("events", []))
                frame, selected = map_columns(frame)
                mappings.update(selected)
                frames.append(frame)
        if not frames:
            raise ValueError("ZIP contains no CSV, JSON, or JSONL files.")
        return pd.concat(frames, ignore_index=True, sort=False), mappings
    frame, mapping = map_columns(_load_one(source))
    return frame, mapping
