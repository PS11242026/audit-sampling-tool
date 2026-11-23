"""Step 11: user administration (Partner only) and the audit trail viewer."""

import pandas as pd
import streamlit as st

from core import demo
from storage import auditlog, auth
from ui.common import require_role


def render(user):
    st.header("11. Admin & audit trail")
    tab_users, tab_trail = st.tabs(["Users", "Audit trail"])

    with tab_users:
        users = pd.DataFrame(auth.list_users())
        st.dataframe(users, hide_index=True)
        if demo.is_demo():
            st.info("Adding and deactivating users is disabled in the "
                    "public demo so the shared account stays usable.")
        elif auth.has_role(user, "Partner"):
            with st.form("add_user"):
                st.markdown("**Add user**")
                c1, c2, c3 = st.columns(3)
                u = c1.text_input("Username")
                p = c2.text_input("Initial password (min 8 chars)",
                                  type="password")
                role = c3.selectbox("Role", list(auth.ROLES), index=0)
                if st.form_submit_button("Create user"):
                    try:
                        auth.create_user(u, p, role)
                        auditlog.log(user, "CREATE_USER",
                                     details={"username": u, "role": role})
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
            if len(users):
                c1, c2 = st.columns(2)
                target = c1.selectbox(
                    "Activate / deactivate",
                    users["username"].tolist())
                row = users[users["username"] == target].iloc[0]
                new_state = not bool(row["active"])
                if c2.button(("Reactivate " if new_state else "Deactivate ")
                             + target):
                    if target == user["username"]:
                        st.error("You cannot deactivate your own account.")
                    else:
                        auth.set_active(int(row["id"]), new_state)
                        auditlog.log(user, "SET_USER_ACTIVE",
                                     details={"username": target,
                                              "active": new_state})
                        st.rerun()
        else:
            st.caption("User administration requires the Partner role.")

    with tab_trail:
        st.caption("Append-only log of every action (SA 230). The "
                   "application has no code path that updates or deletes "
                   "these rows.")
        c1, c2 = st.columns(2)
        scope = c1.selectbox("Scope", ["Current engagement",
                                       "All engagements"])
        action = c2.text_input("Filter by action (exact, optional)",
                               placeholder="e.g. GENERATE_SAMPLE")
        eid = st.session_state.get("engagement_id") \
            if scope == "Current engagement" else None
        trail = auditlog.fetch(engagement_id=eid,
                               action=action.strip() or None, limit=2000)
        st.dataframe(trail, hide_index=True)
        if len(trail):
            st.download_button(
                "Download shown entries (CSV)",
                trail.to_csv(index=False).encode("utf-8"),
                file_name="audit_trail.csv", mime="text/csv")
