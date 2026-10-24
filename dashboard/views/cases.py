from __future__ import annotations

import streamlit as st

from ueba.auth import require_role
from ueba.cases import close_case, list_cases, update_case


def render(ctx: dict) -> None:
    st.title("Cases")
    cases = list_cases(ctx["db_path"], ctx["workspace"])
    if not cases:
        st.info("No cases yet. The collector groups alerts for an entity within seven days.")
        return
    statuses = ["open", "in_progress", "closed"]
    for case in cases:
        with st.expander(f"{case['entity']} · {case['start_date']} to {case['end_date']} · {case['status']} · {case['alert_count']} alert(s)"):
            st.write(f"Assignee: {case['assignee'] or 'Unassigned'} · Verdict: {case['verdict'] or 'Pending'}")
            for note in case["notes"]:
                st.caption(f"{note['at']} · {note['username']}: {note['note']}")
            if ctx["session"]["role"] in {"analyst", "administrator"}:
                require_role(ctx["session"], "analyst")
                with st.form(f"case-{case['id']}"):
                    assignee = st.text_input("Assignee", value=case["assignee"])
                    status = st.selectbox("Status", statuses, index=statuses.index(case["status"]))
                    note = st.text_area("Add an investigation note")
                    save = st.form_submit_button("Save case")
                    if save:
                        update_case(ctx["db_path"], case["id"], ctx["session"]["username"],
                                    status=status, assignee=assignee, note=note)
                        st.rerun()
                if case["status"] != "closed":
                    verdict = st.selectbox("Close as", ["benign", "threat"], key=f"verdict-{case['id']}")
                    if st.button("Close case and record verdict", key=f"close-{case['id']}"):
                        close_case(ctx["db_path"], case["id"], ctx["workspace"],
                                   ctx["session"]["username"], verdict)
                        st.rerun()
