"""Alert delivery to configured generic webhooks or SMTP mail."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from .storage import connect


def _previous_risk(db_path: str | Path, key: str) -> float | None:
    with connect(db_path) as con:
        row = con.execute("SELECT detail FROM notification_log WHERE alert_key=? AND status='sent'", (key,)).fetchone()
    if not row:
        return None
    try:
        return float(json.loads(row[0]).get("risk", 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _record(db_path: str | Path, key: str, channel: str, status: str, risk: float, detail: str) -> None:
    with connect(db_path) as con:
        con.execute("INSERT OR REPLACE INTO notification_log(alert_key,sent_at,channel,status,detail) VALUES(?,?,?,?,?)",
                    (key, datetime.now(timezone.utc).isoformat(), channel, status,
                     json.dumps({"risk": risk, "detail": detail[:1000]})))


def send_alerts(db_path: str | Path, workspace: str, alerts: pd.DataFrame) -> list[dict]:
    webhook = os.environ.get("UEBA_WEBHOOK_URL", "").strip()
    mail_host = os.environ.get("UEBA_SMTP_HOST", "").strip()
    mail_to = os.environ.get("UEBA_ALERT_EMAIL", "").strip()
    channels = []
    if webhook:
        channels.append(("webhook", webhook))
    if mail_host and mail_to:
        channels.append(("email", mail_to))
    if alerts.empty or not channels:
        return []
    outcomes = []
    for row in alerts.to_dict("records"):
        entity, day = str(row.get("user", row.get("device", "unknown"))), str(row["date"])
        key = f"{workspace}|{entity}|{day}"
        risk = float(row.get("daily_risk", 0))
        previous = _previous_risk(db_path, key)
        if previous is not None and risk <= previous:
            continue
        payload = {
            "workspace": workspace, "entity": entity, "date": day,
            "risk": risk, "escalated_from": previous,
            "reason": str(row.get("alert_reason", "")),
            "rule_ids": str(row.get("rule_ids", "")),
        }
        for channel, destination in channels:
            try:
                if channel == "webhook":
                    request = urllib.request.Request(destination, data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(request, timeout=8) as response:
                        detail = f"HTTP {response.status}"
                else:
                    message = EmailMessage()
                    message["Subject"] = f"UEBA alert: {entity} risk {risk:.1f}"
                    message["From"] = os.environ.get("UEBA_SMTP_FROM", os.environ.get("UEBA_SMTP_USER", "ueba@localhost"))
                    message["To"] = destination
                    message.set_content(json.dumps(payload, indent=2))
                    context = ssl.create_default_context()
                    port = int(os.environ.get("UEBA_SMTP_PORT", "465"))
                    with smtplib.SMTP_SSL(mail_host, port, context=context, timeout=8) as server:
                        username = os.environ.get("UEBA_SMTP_USER", "")
                        password = os.environ.get("UEBA_SMTP_PASSWORD", "")
                        if username:
                            server.login(username, password)
                        server.send_message(message)
                    detail = "email accepted by SMTP server"
                _record(db_path, key, channel, "sent", risk, detail)
                outcomes.append({"key": key, "channel": channel, "status": "sent", "detail": detail})
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                _record(db_path, key, channel, "failed", risk, detail)
                outcomes.append({"key": key, "channel": channel, "status": "failed", "detail": detail})
    return outcomes
