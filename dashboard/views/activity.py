from __future__ import annotations

import streamlit as st

from ueba.activity import activity_story, website_summary


def render(ctx: dict) -> None:
    st.title("User activity")
    if ctx["events"].empty or ctx["scores"].empty:
        st.info("Activity details will appear after events are imported and scored.")
        return
    users = sorted(ctx["scores"]["user"].unique())
    default_user = st.session_state.get("selected_entity")
    user = st.selectbox("User", users, index=users.index(default_user) if default_user in users else 0)
    user_scores = ctx["scores"][ctx["scores"]["user"].eq(user)].sort_values("date")
    day_options = list(user_scores["date"].astype(str))
    default_day = st.session_state.get("selected_date")
    day = st.selectbox("Day", day_options, index=day_options.index(default_day) if default_day in day_options else len(day_options) - 1)
    row = user_scores[user_scores["date"].astype(str).eq(day)].iloc[0]
    if row["alert"]:
        st.warning(f"Risk {row['daily_risk']:.1f}: {row['alert_reason']}")
    old_events = ctx["events"][(ctx["events"]["user"].eq(user)) & (ctx["events"]["timestamp"].dt.strftime("%Y-%m-%d") < day)]
    previous_domains = set(old_events[old_events["event_type"].eq("web")]["domain"].dropna())
    websites = website_summary(ctx["events"], user, day, previous_domains)
    if not websites.empty:
        st.subheader("Websites")
        st.dataframe(websites, use_container_width=True, hide_index=True)
    st.subheader("Chronological activity")
    for event in activity_story(ctx["events"], user, day, row["alert_reason"] if row["alert"] else ""):
        marker = "🚩" if event["flagged"] else "•"
        st.write(f"{marker} **{event['time']}** — {event['text']}")
    event_types = sorted(ctx["events"][ctx["events"]["user"].eq(user)]["event_type"].unique())
    st.caption("Event families present: " + ", ".join(event_types))
