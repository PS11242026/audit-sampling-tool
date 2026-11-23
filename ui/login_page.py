"""Sign-in page; on first run, creates the Partner (administrator) account."""

import streamlit as st

from core import demo
from core.version import APP_NAME
from storage import auditlog, auth


def render():
    st.title(APP_NAME)
    st.caption("Risk assessment per SA 315 | audit sampling per SA 530 | "
               "documentation per SA 230 | SERC regulated-revenue "
               "cross-checks")

    if demo.is_demo():
        st.info("**Public demo** - Kestrel Transmission is a fictional "
                "utility and every ledger line is synthetic (with planted "
                "audit exceptions to find). Work is shared with other "
                "visitors and resets when the app restarts. Please don't "
                "upload real client data.")
        if st.button("Enter the demo as Partner", type="primary"):
            username, password, _role = demo.DEMO_USER
            user = auth.authenticate(username, password)
            if user:
                st.session_state["user"] = user
                auditlog.log(user, "LOGIN")
                st.rerun()
            else:
                st.error("The demo account is unavailable - the app will "
                         "reset on its next restart.")
        return

    if auth.user_count() == 0:
        st.info("First run - create the Partner (administrator) account. "
                "Passwords are stored as scrypt hashes in the local "
                "database.")
        with st.form("first_admin"):
            u = st.text_input("Username")
            p1 = st.text_input("Password (min 8 characters)",
                               type="password")
            p2 = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create Partner account",
                                     type="primary"):
                try:
                    if p1 != p2:
                        raise ValueError("passwords do not match")
                    auth.create_user(u, p1, "Partner")
                    user = auth.authenticate(u, p1)
                    st.session_state["user"] = user
                    auditlog.log(user, "CREATE_USER",
                                 details={"username": u, "role": "Partner",
                                          "first_run": True})
                    auditlog.log(user, "LOGIN")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        return

    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            user = auth.authenticate(u, p)
            if user:
                st.session_state["user"] = user
                auditlog.log(user, "LOGIN")
                st.rerun()
            else:
                auditlog.log(u or "?", "LOGIN_FAILED")
                st.error("Invalid credentials or inactive account.")
