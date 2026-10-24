from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from ueba.ingest import load_events
from ueba.workspace import WorkspaceManager


def render(ctx: dict) -> None:
    st.title("Data sources")
    if ctx["session"]["role"] != "administrator":
        st.info("An administrator manages data imports and workspace settings.")
        return
    manager = WorkspaceManager(ctx["workspace_root"])
    existing = manager.list()
    st.subheader("Workspaces")
    if existing:
        st.dataframe(pd.DataFrame([{k: w.get(k) for k in ("name", "slug", "state", "days", "events", "last_import_at", "last_analysis_at", "last_error")} for w in existing]),
                     use_container_width=True, hide_index=True)
    with st.form("new-workspace"):
        name = st.text_input("New workspace name")
        learning_days = st.number_input("Learning days", min_value=5, max_value=90, value=30)
        create = st.form_submit_button("Create workspace")
        if create:
            if not name.strip():
                st.error("Enter a workspace name.")
            else:
                manager.create(name, int(learning_days))
                st.success(f"Created {name}.")
                st.rerun()
    st.subheader("Import an event export")
    if not existing:
        st.info("Create a workspace above before importing event data.")
        return
    target = st.selectbox("Target workspace", [w["slug"] for w in existing])
    uploaded = st.file_uploader("CSV, JSON, JSONL, or ZIP export", type=["csv", "json", "jsonl", "zip"])
    if uploaded:
        with tempfile.TemporaryDirectory(prefix="ueba-upload-") as directory:
            source = Path(directory) / uploaded.name
            source.write_bytes(uploaded.getvalue())
            try:
                normalized = load_events(source)
                st.caption(f"Detected {len(normalized):,} normalized events. Preview and field mapping:")
                st.dataframe(normalized.head(30), use_container_width=True, hide_index=True)
                if st.button("Queue this file for collection", type="primary"):
                    manager.queue_file(target, source)
                    st.success("Queued. The collector imports and scores it on its next pass.")
            except Exception as exc:
                st.error(f"Could not read this export: {exc}")
    if ctx["heartbeat"].exists():
        st.caption(f"Collector heartbeat: {ctx['heartbeat'].read_text()[:1000]}")
