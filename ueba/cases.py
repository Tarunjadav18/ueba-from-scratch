"""Case grouping, analyst notes, closures, and time-limited alert suppression."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .storage import audit, connect


def _case_id(workspace: str, entity: str, first_day: str) -> str:
    digest = hashlib.sha1(f"{workspace}|{entity}|{first_day}".encode()).hexdigest()[:12]
    return f"case-{digest}"


def sync_cases(db_path: str | Path, workspace: str, alerts: pd.DataFrame, gap_days: int = 7) -> int:
    """Group alerts for an entity when the next alert is within gap_days."""
    if alerts.empty:
        return 0
    created = 0
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as con:
        for entity, group in alerts.sort_values("date").groupby("user"):
            rows = list(group.to_dict("records"))
            buckets: list[list[dict]] = []
            for row in rows:
                day = pd.Timestamp(row["date"]).date()
                if not buckets or (day - pd.Timestamp(buckets[-1][-1]["date"]).date()).days > gap_days:
                    buckets.append([row])
                else:
                    buckets[-1].append(row)
            for bucket in buckets:
                first = str(bucket[0]["date"])
                last = str(bucket[-1]["date"])
                case_id = _case_id(workspace, str(entity), first)
                exists = con.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
                if not exists:
                    con.execute("INSERT INTO cases(id,workspace,entity,start_date,end_date,updated_at) VALUES(?,?,?,?,?,?)",
                                (case_id, workspace, str(entity), first, last, now))
                    created += 1
                else:
                    con.execute("UPDATE cases SET end_date=?,updated_at=? WHERE id=?", (last, now, case_id))
                for row in bucket:
                    alert_key = f"{entity}|{row['date']}"
                    con.execute("INSERT OR IGNORE INTO case_alerts(case_id,alert_key) VALUES(?,?)", (case_id, alert_key))
    return created


def list_cases(db_path: str | Path, workspace: str, status: str | None = None) -> list[dict]:
    with connect(db_path) as con:
        query = "SELECT * FROM cases WHERE workspace=?"
        params: list = [workspace]
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY updated_at DESC"
        cases = [dict(r) for r in con.execute(query, params).fetchall()]
        for case in cases:
            case["alert_count"] = con.execute("SELECT COUNT(*) FROM case_alerts WHERE case_id=?", (case["id"],)).fetchone()[0]
            case["notes"] = [dict(n) for n in con.execute("SELECT at,username,note FROM case_notes WHERE case_id=? ORDER BY id", (case["id"],)).fetchall()]
    return cases


def update_case(db_path: str | Path, case_id: str, username: str, *, status: str | None = None,
                assignee: str | None = None, note: str = "") -> None:
    if status is not None and status not in {"open", "in_progress", "closed"}:
        raise ValueError("Case status must be open, in_progress, or closed.")
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as con:
        if status is not None:
            con.execute("UPDATE cases SET status=?,updated_at=? WHERE id=?", (status, now, case_id))
        if assignee is not None:
            con.execute("UPDATE cases SET assignee=?,updated_at=? WHERE id=?", (assignee, now, case_id))
        if note.strip():
            con.execute("INSERT INTO case_notes(case_id,at,username,note) VALUES(?,?,?,?)",
                        (case_id, now, username, note.strip()[:4000]))
    audit(db_path, "case_updated", username, detail=f"case_id={case_id}; status={status or ''}; assignee={assignee or ''}")


def close_case(db_path: str | Path, case_id: str, workspace: str, username: str,
               verdict: str, note: str = "") -> None:
    if verdict not in {"benign", "threat"}:
        raise ValueError("A case verdict must be benign or threat.")
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as con:
        case = con.execute("SELECT * FROM cases WHERE id=? AND workspace=?", (case_id, workspace)).fetchone()
        if case is None:
            raise KeyError(case_id)
        alert_keys = [r[0] for r in con.execute("SELECT alert_key FROM case_alerts WHERE case_id=?", (case_id,)).fetchall()]
        con.execute("UPDATE cases SET status='closed',verdict=?,updated_at=? WHERE id=?", (verdict, now, case_id))
        if note.strip():
            con.execute("INSERT INTO case_notes(case_id,at,username,note) VALUES(?,?,?,?)", (case_id, now, username, note.strip()[:4000]))
        for key in alert_keys:
            entity, day = key.rsplit("|", 1)
            con.execute("INSERT OR REPLACE INTO feedback(workspace,entity,date,verdict,note,username,at) VALUES(?,?,?,?,?,?,?)",
                        (workspace, entity, day, verdict, note.strip(), username, now))
    audit(db_path, "case_closed", username, workspace, f"case_id={case_id}; verdict={verdict}")


def suppress(db_path: str | Path, workspace: str, entity: str, alert_type: str,
             reason: str, expires_on: str, username: str) -> int:
    if not reason.strip():
        raise ValueError("A reason is required for suppression.")
    expiry = date.fromisoformat(expires_on)
    if expiry <= date.today():
        raise ValueError("Suppression expiry must be a future date.")
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as con:
        cursor = con.execute("INSERT INTO suppressions(workspace,entity,alert_type,reason,expires_on,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                             (workspace, entity, alert_type, reason.strip(), expiry.isoformat(), username, now))
        identifier = int(cursor.lastrowid)
    audit(db_path, "alert_suppressed", username, workspace, f"id={identifier}; entity={entity}; type={alert_type}; until={expires_on}")
    return identifier


def active_suppressions(db_path: str | Path, workspace: str, entity: str, alert_type: str) -> list[dict]:
    today = date.today().isoformat()
    with connect(db_path) as con:
        rows = con.execute("""SELECT * FROM suppressions WHERE lifted_at IS NULL AND expires_on>=?
            AND workspace IN (?, '*') AND entity IN (?, '*') AND alert_type IN (?, '*')""",
                           (today, workspace, entity, alert_type)).fetchall()
    return [dict(row) for row in rows]


def lift_suppression(db_path: str | Path, identifier: int, username: str, workspace: str = "") -> None:
    with connect(db_path) as con:
        con.execute("UPDATE suppressions SET lifted_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), identifier))
    audit(db_path, "suppression_lifted", username, workspace, f"id={identifier}")
