from __future__ import annotations

import pandas as pd
import streamlit as st

from ueba.auth import audit_entries, create_user, issue_token, list_tokens, list_users, revoke_token_hash
from ueba.workspace import WorkspaceManager


def render(ctx: dict) -> None:
    st.title("Administration")
    if ctx["session"]["role"] != "administrator":
        st.error("Administrator role required.")
        return
    st.subheader("Users and roles")
    users = list_users(ctx["db_path"])
    if users:
        st.dataframe(pd.DataFrame(users), use_container_width=True, hide_index=True)
    with st.form("create-user"):
        username = st.text_input("Username")
        password = st.text_input("Temporary password (12+ characters)", type="password")
        role = st.selectbox("Role", ["viewer", "analyst", "administrator"])
        submitted = st.form_submit_button("Create account")
        if submitted:
            try:
                create_user(ctx["db_path"], username, password, role, ctx["session"]["username"])
                st.success(f"Created {username} as {role}.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.subheader("Scoped API tokens")
    workspaces = WorkspaceManager(ctx["workspace_root"]).list()
    if workspaces:
        with st.form("create-token"):
            token_user = st.selectbox("Token owner", [u["username"] for u in users])
            workspace = st.selectbox("Workspace scope", [w["slug"] for w in workspaces])
            make = st.form_submit_button("Create token")
            if make:
                token = issue_token(ctx["db_path"], token_user, workspace)
                st.session_state["new_api_token"] = token
                st.rerun()
        if st.session_state.get("new_api_token"):
            st.warning("Copy this token now. The console stores only its SHA-256 hash.")
            st.code(st.session_state["new_api_token"])
            if st.button("Hide token"):
                st.session_state.pop("new_api_token", None)
                st.rerun()
    tokens = list_tokens(ctx["db_path"])
    if tokens:
        st.dataframe(pd.DataFrame([{**t, "token_hash": t["token_hash"][:12] + "…"} for t in tokens]),
                     use_container_width=True, hide_index=True)
        active = [t for t in tokens if not t["revoked_at"]]
        if active:
            token_by_hash = {t["token_hash"]: t for t in active}
            selected_hash = st.selectbox("Revoke token", list(token_by_hash),
                format_func=lambda h: f"{token_by_hash[h]['username']} · {token_by_hash[h]['workspace']} · {token_by_hash[h]['created_at']}")
            if st.button("Revoke selected token"):
                revoke_token_hash(ctx["db_path"], selected_hash, ctx["session"]["username"])
                st.success("Token revoked.")
                st.rerun()
    st.subheader("Audit log")
    records = audit_entries(ctx["db_path"])
    st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
