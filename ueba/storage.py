"""Small SQLite store for accounts, analyst workflow, tokens, and audit history."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 username TEXT PRIMARY KEY, salt BLOB NOT NULL, password_hash BLOB NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('viewer','analyst','administrator')),
 failures INTEGER NOT NULL DEFAULT 0, locked_until TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tokens (
 token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, workspace TEXT NOT NULL,
 created_at TEXT NOT NULL, revoked_at TEXT, FOREIGN KEY(username) REFERENCES users(username)
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, username TEXT,
 action TEXT NOT NULL, workspace TEXT, detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cases (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, entity TEXT NOT NULL,
 start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
 assignee TEXT NOT NULL DEFAULT '', verdict TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_alerts (
 case_id TEXT NOT NULL, alert_key TEXT NOT NULL, PRIMARY KEY(case_id, alert_key),
 FOREIGN KEY(case_id) REFERENCES cases(id)
);
CREATE TABLE IF NOT EXISTS case_notes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
 at TEXT NOT NULL, username TEXT NOT NULL, note TEXT NOT NULL,
 FOREIGN KEY(case_id) REFERENCES cases(id)
);
CREATE TABLE IF NOT EXISTS feedback (
 workspace TEXT NOT NULL, entity TEXT NOT NULL, date TEXT NOT NULL,
 verdict TEXT NOT NULL CHECK(verdict IN ('benign','threat')), note TEXT NOT NULL DEFAULT '',
 username TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(workspace, entity, date)
);
CREATE TABLE IF NOT EXISTS suppressions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, workspace TEXT NOT NULL DEFAULT '*',
 entity TEXT NOT NULL DEFAULT '*', alert_type TEXT NOT NULL, reason TEXT NOT NULL,
 expires_on TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, lifted_at TEXT
);
CREATE TABLE IF NOT EXISTS notification_log (
 alert_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL, channel TEXT NOT NULL,
 status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def audit(path: str | Path, action: str, username: str = "", workspace: str = "", detail: str = "") -> None:
    from datetime import datetime, timezone
    with connect(path) as con:
        con.execute("INSERT INTO audit_log(at,username,action,workspace,detail) VALUES(?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), username, action, workspace, detail[:2000]))
