from __future__ import annotations

import streamlit as st


def render(ctx: dict) -> None:
    scores = ctx["scores"]
    st.title("Alerts")
    if scores.empty:
        st.info("No scored user-days yet.")
        return
    alerts = scores[scores["alert"] | scores["sustained_alert"]].copy()
    if alerts.empty:
        st.success("There are no alerts at this threshold.")
        return
    c1, c2 = st.columns(2)
    departments = sorted(alerts["department"].dropna().unique())
    selected = c1.multiselect("Department", departments, default=departments)
    minimum = c2.slider("Minimum risk", 0, 100, 0)
    alerts = alerts[alerts["department"].isin(selected) & (alerts["daily_risk"] >= minimum)]
    alerts = alerts.sort_values(["daily_risk", "date"], ascending=[False, False])
    st.dataframe(alerts[["date", "user", "department", "daily_risk", "accumulated_risk", "rule_ids", "rule_techniques", "alert_reason"]],
                 use_container_width=True, hide_index=True)
    if not alerts.empty:
        chosen = st.selectbox("Inspect alert", alerts.index,
                              format_func=lambda i: f"{alerts.at[i, 'user']} · {alerts.at[i, 'date']} · risk {alerts.at[i, 'daily_risk']:.1f}")
        row = alerts.loc[chosen]
        st.markdown(f"**Why it was raised:** {row['alert_reason']}")
        st.caption(f"Statistical {row['stat_score']:.2f} · peer {row['peer_score']:.2f} · ML {row['ml_score']:.2f} · rule {row['rule_score']:.2f}")
        if row.get("rule_ids"):
            st.caption(f"Rule IDs: {row['rule_ids']} · ATT&CK: {row['rule_techniques']}")
        st.session_state["selected_entity"] = str(row["user"])
        st.session_state["selected_date"] = str(row["date"])
