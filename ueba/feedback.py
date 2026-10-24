from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .storage import audit, connect


def record(db_path: str | Path, workspace: str, entity: str, date: str, verdict: str,
           note: str = "", username: str = "analyst") -> None:
    if verdict not in {"benign", "threat"}:
        raise ValueError("verdict must be benign or threat")
    at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as con:
        con.execute("INSERT OR REPLACE INTO feedback(workspace,entity,date,verdict,note,username,at) VALUES(?,?,?,?,?,?,?)",
                    (workspace, entity, str(date), verdict, note, username, at))
    audit(db_path, "verdict_recorded", username, workspace, f"entity={entity}; date={date}; verdict={verdict}")


def verdict_sets(db_path: str | Path, workspace: str) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    with connect(db_path) as con:
        rows = con.execute("SELECT entity,date,verdict FROM feedback WHERE workspace=?", (workspace,)).fetchall()
    benign = {(r["entity"], r["date"]) for r in rows if r["verdict"] == "benign"}
    threat = {(r["entity"], r["date"]) for r in rows if r["verdict"] == "threat"}
    return benign, threat
