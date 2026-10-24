from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA_ROOT = Path(os.environ.get("UEBA_DATA_DIR", str(ROOT / "data"))).resolve()
WORKSPACE_ROOT = DATA_ROOT / "workspaces"
DB_PATH = DATA_ROOT / "console.db"

from ueba.auth import authenticate, create_user, has_users, require_role
from ueba.cases import sync_cases
from ueba.evaluate import evaluate
from ueba.generator import make_demo
from ueba.ingest import normalize_events
from ueba.pipeline import run
from ueba.workspace import WorkspaceManager
from dashboard.views import activity, admin, alerts, cases, host, investigate, logs, overview, performance, sources

st.set_page_config(page_title="UEBA Console", page_icon="🔎", layout="wide")


def _login_gate() -> dict | None:
    st.title("UEBA Console")
    if not has_users(DB_PATH):
        st.subheader("Create the first administrator")
        st.caption("This password protects the local console and its security logs. It is never stored in plain text.")
        with st.form("initial-admin"):
            username = st.text_input("Administrator username", value="admin")
            password = st.text_input("Password (at least 12 characters)", type="password")
            confirm = st.text_input("Confirm password", type="password")
            create = st.form_submit_button("Create administrator", type="primary")
            if create:
                if password != confirm:
                    st.error("The passwords do not match.")
                else:
                    try:
                        create_user(DB_PATH, username, password, "administrator")
                        st.success("Administrator created. Sign in to continue.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        return None
    session = st.session_state.get("ueba_session")
    if session:
        try:
            require_role(session, "viewer")
            return session
        except PermissionError:
            st.session_state.pop("ueba_session", None)
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Sign in", type="primary")
        if submit:
            try:
                st.session_state["ueba_session"] = authenticate(DB_PATH, username, password)
                st.rerun()
            except PermissionError as exc:
                st.error(str(exc))
    return None


@st.cache_data(show_spinner="Generating the compact synthetic demo and analyzing 45 days of behavior…")
def _demo_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Keep the hosted console within Render's 512 MB free-instance memory cap.
    # The CLI pipeline still uses make_demo() defaults for the full experiment.
    return run(normalize_events(make_demo(users=12, days=45)))


def _load_workspace(name: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    manager = WorkspaceManager(WORKSPACE_ROOT)
    status = manager.status(name)
    path = manager.get(name)
    events = manager.read_events(name)
    score_file = path / "scores.csv"
    device_file = path / "device_scores.csv"
    scores = pd.read_csv(score_file) if score_file.exists() else pd.DataFrame()
    devices = pd.read_csv(device_file) if device_file.exists() else pd.DataFrame()
    if not events.empty:
        events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True, errors="coerce")
    return events, scores, devices, status["state"]


session = _login_gate()
if session is None:
    st.stop()

with st.sidebar:
    st.markdown(f"**{session['username']}** · {session['role']}")
    if st.button("Sign out"):
        st.session_state.pop("ueba_session", None)
        st.rerun()
    manager = WorkspaceManager(WORKSPACE_ROOT)
    workspaces = manager.list()
    workspace_names = [w["slug"] for w in workspaces]
    choices = ["synthetic-demo", *workspace_names]
    selected_workspace = st.selectbox("Workspace", choices, index=0)
    pages = ["Overview", "Alerts", "Cases", "Investigate entity", "User activity", "Model performance",
             "Live host monitor", "Log explorer", "Data sources"]
    if session["role"] == "administrator":
        pages.append("Administration")
    page = st.radio("Console", pages, label_visibility="collapsed")

if selected_workspace == "synthetic-demo":
    events, scores, devices = _demo_data()
    state = "Synthetic demo"
    metrics = evaluate(scores) if "label" in scores else {}
    sync_cases(DB_PATH, selected_workspace, scores[scores["alert"] | scores["sustained_alert"]])
else:
    try:
        events, scores, devices, state = _load_workspace(selected_workspace)
        metrics = evaluate(scores) if not scores.empty and "label" in scores and scores["label"].astype(int).nunique() > 1 else {}
    except Exception as exc:
        st.error(f"Could not open workspace: {exc}")
        st.stop()

context = {
    "workspace": selected_workspace,
    "workspace_root": WORKSPACE_ROOT,
    "db_path": DB_PATH,
    "heartbeat": WORKSPACE_ROOT / "service.json",
    "events": events,
    "scores": scores,
    "devices": devices,
    "state": state,
    "metrics": metrics,
    "session": session,
    "feature_columns": [c for c in scores.columns if c in {
        "auth_success", "auth_failures", "fail_then_success", "auth_unique_ips", "new_countries",
        "off_hours_events", "rare_hour_events", "impossible_travel", "unique_hosts", "new_hosts",
        "access_files", "sensitive_files", "access_commands", "new_file_paths", "access_denied",
        "usb_events", "usb_new_devices", "usb_files_copied", "usb_bytes_mb", "admin_events",
        "admin_first_use", "admin_as_other", "shared_folder_events", "new_shared_folders", "admin_share_events",
        "print_jobs", "print_pages", "confidential_print_pages", "off_hours_print_jobs", "powershell_events",
        "suspicious_powershell", "network_connections", "new_domains", "new_subdomains", "bytes_out_mb",
        "bytes_in_mb", "cloud_upload_mb", "resource_avg_cpu", "cpu_hours_above_85", "resource_avg_memory",
        "resource_avg_disk", "distinct_ports", "auth_unique_countries", "sensitive_bytes_mb", "web_requests",
        "blocked_requests", "blocked_sites", "hacking_site_visits", "new_web_categories", "downloads",
        "executable_downloads",
    }],
}

renderers = {
    "Overview": overview.render,
    "Alerts": alerts.render,
    "Cases": cases.render,
    "Investigate entity": investigate.render,
    "User activity": activity.render,
    "Model performance": performance.render,
    "Live host monitor": host.render,
    "Log explorer": logs.render,
    "Data sources": sources.render,
    "Administration": admin.render,
}
renderers[page](context)
