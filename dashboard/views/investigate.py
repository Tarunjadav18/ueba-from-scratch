from __future__ import annotations

import pandas as pd
import streamlit as st


def render(ctx: dict) -> None:
    scores = ctx["scores"]
    st.title("Investigate entity")
    if scores.empty:
        st.info("No user-day profiles yet.")
        return
    users = sorted(scores["user"].unique())
    default = st.session_state.get("selected_entity")
    entity = st.selectbox("User", users, index=users.index(default) if default in users else 0)
    rows = scores[scores["user"].eq(entity)].sort_values("date")
    st.line_chart(rows.set_index("date")[["daily_risk", "accumulated_risk"]])
    feature = st.selectbox("Feature", [c for c in ctx["feature_columns"] if c in rows])
    learning = rows[rows["analysis_mode"].eq("learning")]
    median = float(learning[feature].median()) if not learning.empty else 0.0
    current = rows.iloc[-1]
    st.metric("Latest value vs learning median", f"{current[feature]:.2f}", delta=f"median {median:.2f}")
    st.dataframe(rows[["date", feature, "stat_score", "peer_score", "ml_score", "daily_risk", "alert_reason"]],
                 use_container_width=True, hide_index=True)
