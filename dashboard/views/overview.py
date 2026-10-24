from __future__ import annotations

import pandas as pd
import streamlit as st

from ueba.cases import list_cases


def render(ctx: dict) -> None:
    events, scores, devices = ctx["events"], ctx["scores"], ctx["devices"]
    st.title("Overview")
    st.caption(f"Workspace: {ctx['workspace']} · state: {ctx['state']}")
    alerts = scores[scores["alert"] | scores["sustained_alert"]] if not scores.empty else scores
    cases = list_cases(ctx["db_path"], ctx["workspace"])
    cols = st.columns(5)
    cols[0].metric("Events", f"{len(events):,}")
    cols[1].metric("Users", f"{scores['user'].nunique() if not scores.empty else 0:,}")
    cols[2].metric("Devices", f"{devices['device'].nunique() if not devices.empty else 0:,}")
    cols[3].metric("Alerts", f"{len(alerts):,}")
    cols[4].metric("Open cases", sum(c["status"] != "closed" for c in cases))
    if scores.empty:
        st.info("No scores yet. The collector processes new workspace data after it arrives.")
        return
    daily = alerts.groupby("date").size().rename("alerts").to_frame()
    st.subheader("Alert volume")
    st.line_chart(daily)
    left, right = st.columns(2)
    with left:
        st.subheader("Highest-risk user-days")
        st.dataframe(alerts.sort_values("daily_risk", ascending=False)[
            ["date", "user", "department", "daily_risk", "rule_ids", "alert_reason"]
        ].head(15), use_container_width=True, hide_index=True)
    with right:
        st.subheader("Risk by department")
        if "department" in scores:
            st.bar_chart(scores.groupby("department")["daily_risk"].mean().sort_values(ascending=False))
    if "rule_techniques" in alerts and not alerts.empty:
        st.subheader("ATT&CK techniques in current alerts")
        techniques = alerts["rule_techniques"].fillna("").str.split("; ").explode()
        techniques = techniques[techniques.ne("")].value_counts().rename("alerts").to_frame()
        st.dataframe(techniques, use_container_width=True)
    if ctx.get("metrics") and ctx["metrics"].get("status") == "ok":
        st.caption(f"Synthetic/labelled evaluation: F1 {ctx['metrics']['f1']:.3f}, "
                   f"precision {ctx['metrics']['precision']:.3f}, recall {ctx['metrics']['recall']:.3f}. "
                   "Only interpret these when the workspace includes ground-truth labels.")
