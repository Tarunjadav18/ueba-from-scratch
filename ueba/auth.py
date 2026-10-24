"""Password, role, session, and workspace-scoped API-token primitives."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .storage import audit, connect

ROLES = {"viewer": 1, "analyst": 2, "administrator": 3}
ITERATIONS = 310_000
MAX_FAILURES = 5
LOCK_MINUTES = 15


def _password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)


def create_user(db_path: str | Path, username: str, password: str, role: str = "viewer", actor: str = "") -> None:
    username = username.strip().lower()
    if role not in ROLES:
        raise ValueError("Role must be viewer, analyst, or administrator.")
    if len(password) < 12:
        raise ValueError("Use a password with at least 12 characters.")
    salt = secrets.token_bytes(16)
    digest = _password(password, salt)
    with connect(db_path) as con:
        con.execute("INSERT INTO users(username,salt,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                    (username, salt, digest, role, datetime.now(timezone.utc).isoformat()))
    audit(db_path, "user_created", actor or username, detail=f"username={username}; role={role}")


def has_users(db_path: str | Path) -> bool:
    with connect(db_path) as con:
        return con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def authenticate(db_path: str | Path, username: str, password: str, workspace: str = "") -> dict:
    """Verify credentials with generic errors and temporary lockout."""
    username = username.strip().lower()
    now = datetime.now(timezone.utc)
    invalid = False
    result = None
    with connect(db_path) as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            # Perform comparable work so unknown usernames do not get an instant response.
            _password(password, b"ueba-static-salt")
            invalid = True
        elif row["locked_until"]:
            until = datetime.fromisoformat(row["locked_until"])
            if until > now:
                invalid = True
        if row is not None and not invalid:
            candidate = _password(password, row["salt"])
            if not hmac.compare_digest(candidate, row["password_hash"]):
                failures = int(row["failures"]) + 1
                locked_until = (now + timedelta(minutes=LOCK_MINUTES)).isoformat() if failures >= MAX_FAILURES else None
                con.execute("UPDATE users SET failures=?, locked_until=? WHERE username=?", (failures, locked_until, username))
                con.commit()
                invalid = True
            else:
                con.execute("UPDATE users SET failures=0, locked_until=NULL WHERE username=?", (username,))
                result = {"username": username, "role": row["role"], "expires_at": (now + timedelta(hours=8)).isoformat()}
    if invalid:
        audit(db_path, "login_failed", username, workspace)
        raise PermissionError("Sign-in failed.")
    audit(db_path, "login_succeeded", username, workspace)
    return result


def require_role(session: dict, role: str) -> None:
    if role not in ROLES or ROLES.get(session.get("role"), 0) < ROLES[role]:
        raise PermissionError("Your role is not allowed to perform that action.")
    if datetime.fromisoformat(session["expires_at"]) <= datetime.now(timezone.utc):
        raise PermissionError("Your session has expired. Sign in again.")


def issue_token(db_path: str | Path, username: str, workspace: str) -> str:
    token = "ueba_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect(db_path) as con:
        con.execute("INSERT INTO api_tokens(token_hash,username,workspace,created_at) VALUES(?,?,?,?)",
                    (digest, username, workspace, datetime.now(timezone.utc).isoformat()))
    audit(db_path, "api_token_created", username, workspace)
    return token


def verify_token(db_path: str | Path, token: str, workspace: str) -> str:
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect(db_path) as con:
        row = con.execute("SELECT username,workspace FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL", (digest,)).fetchone()
    if row is None or row["workspace"] != workspace:
        raise PermissionError("Invalid API token.")
    return str(row["username"])


def revoke_token(db_path: str | Path, token: str, username: str) -> None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect(db_path) as con:
        con.execute("UPDATE api_tokens SET revoked_at=? WHERE token_hash=?", (datetime.now(timezone.utc).isoformat(), digest))
    audit(db_path, "api_token_revoked", username)


def revoke_token_hash(db_path: str | Path, token_hash: str, username: str) -> None:
    with connect(db_path) as con:
        con.execute("UPDATE api_tokens SET revoked_at=? WHERE token_hash=?",
                    (datetime.now(timezone.utc).isoformat(), token_hash))
    audit(db_path, "api_token_revoked", username)


def list_users(db_path: str | Path) -> list[dict]:
    with connect(db_path) as con:
        rows = con.execute("SELECT username,role,created_at,failures,locked_until FROM users ORDER BY username").fetchall()
    return [dict(row) for row in rows]


def list_tokens(db_path: str | Path) -> list[dict]:
    with connect(db_path) as con:
        rows = con.execute("SELECT token_hash,username,workspace,created_at,revoked_at FROM api_tokens ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def audit_entries(db_path: str | Path, limit: int = 250) -> list[dict]:
    with connect(db_path) as con:
        rows = con.execute("SELECT at,username,action,workspace,detail FROM audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
    return [dict(row) for row in rows]


def change_password(db_path: str | Path, username: str, password: str) -> None:
    if len(password) < 12:
        raise ValueError("Use a password with at least 12 characters.")
    salt = secrets.token_bytes(16)
    digest = _password(password, salt)
    with connect(db_path) as con:
        con.execute("UPDATE users SET salt=?,password_hash=?,failures=0,locked_until=NULL WHERE username=?",
                    (salt, digest, username.strip().lower()))
    audit(db_path, "password_changed", username)
