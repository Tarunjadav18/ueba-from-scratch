from __future__ import annotations

import streamlit as st


def render(ctx: dict) -> None:
    st.title("Log explorer")
    events = ctx["events"]
    if events.empty:
        st.info("No raw events are loaded in this workspace.")
        return
    types = sorted(events["event_type"].fillna("unknown").unique())
    users = sorted(events["user"].fillna("unknown").unique())
    c1, c2, c3 = st.columns(3)
    kind = c1.selectbox("Event family", ["All", *types])
    user = c2.selectbox("User", ["All", *users])
    days = sorted(events["timestamp"].dt.strftime("%Y-%m-%d").unique())
    day = c3.selectbox("Date", ["All", *days])
    filtered = events
    if kind != "All":
        filtered = filtered[filtered["event_type"].eq(kind)]
    if user != "All":
        filtered = filtered[filtered["user"].eq(user)]
    if day != "All":
        filtered = filtered[filtered["timestamp"].dt.strftime("%Y-%m-%d").eq(day)]
    st.write(f"{len(filtered):,} matching events")
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.download_button("Download filtered CSV", filtered.to_csv(index=False).encode(),
                       file_name="ueba-events.csv", mime="text/csv")
