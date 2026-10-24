from __future__ import annotations

import streamlit as st


def render(ctx: dict) -> None:
    st.title("Live host monitor")
    devices = ctx["devices"]
    if devices.empty:
        st.info("No device telemetry yet. Start the endpoint agent or load the synthetic workspace.")
        return
    device = st.selectbox("Device", sorted(devices["device"].unique()))
    rows = devices[devices["device"].eq(device)].sort_values("date")
    st.line_chart(rows.set_index("date")[["daily_risk", "accumulated_risk"]])
    columns = [c for c in ["date", "device_cpu_avg", "device_cpu_max", "device_memory_avg", "device_disk_avg",
                           "device_network_connections", "device_bytes_out_mb", "daily_risk", "rule_ids", "alert_reason"] if c in rows]
    st.dataframe(rows[columns], use_container_width=True, hide_index=True)
