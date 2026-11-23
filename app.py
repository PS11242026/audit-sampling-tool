"""Audit Sampling & Risk Assessment Tool - Kestrel Transmission.

Streamlit entry point: authentication gate, engagement switcher and the
guided eleven-step workflow (SA 315 risk assessment -> SA 530 sampling ->
SA 505 balance confirmations -> SA 230 documentation, with SERC
regulated-revenue cross-checks).

Run:  streamlit run app.py   (or run_tool.bat)
"""

import streamlit as st

from core import demo

demo.prepare_environment()          # demo: temp DB, before any DB use

from core.version import APP_SHORT, __version__  # noqa: E402
from storage import auditlog, db  # noqa: E402
from ui import (admin_page, analysis_page, categorize_page,  # noqa: E402
                confirmations_page, engagement_page, evaluation_page,
                import_page, login_page, serc_page, reports_page, risk_page,
                sampling_page)

st.set_page_config(page_title=APP_SHORT, page_icon="📊", layout="wide")


@st.cache_resource(show_spinner="Preparing the demo engagement…")
def _boot(data_dir_key: str) -> bool:
    # Keyed on the data dir so a changed AUDIT_TOOL_DATA_DIR re-initializes
    # (no leading underscore: Streamlit excludes those args from the key).
    db.init_db()
    if demo.is_demo():
        demo.seed_if_empty()
    return True


_boot(str(db.data_dir()))

if "user" not in st.session_state:
    login_page.render()
    st.stop()

user = st.session_state["user"]

STEPS = {
    "1. Engagement & materiality": engagement_page,
    "2. Data import": import_page,
    "3. Categorize": categorize_page,
    "4. Risk configuration": risk_page,
    "5. Analysis run": analysis_page,
    "6. Sampling": sampling_page,
    "7. SERC reconciliation": serc_page,
    "8. Balance confirmations": confirmations_page,
    "9. Results & evaluation": evaluation_page,
    "10. Reports & export": reports_page,
    "11. Admin & audit trail": admin_page,
}

with st.sidebar:
    st.title(APP_SHORT)
    st.caption(f"Signed in as **{user['username']}** ({user['role']})")
    if st.button("Sign out"):
        auditlog.log(user, "LOGOUT")
        for key in ("user", "engagement_id", "view_sample_id",
                    "pack_bytes", "pack_name", "memo_bytes", "memo_name"):
            st.session_state.pop(key, None)
        st.rerun()

    engagements = db.list_engagements()
    if engagements:
        ids = [e["id"] for e in engagements]
        names = {e["id"]: f"#{e['id']} - {e['name']}" for e in engagements}
        current = st.session_state.get("engagement_id")
        idx = ids.index(current) if current in ids else 0
        chosen = st.selectbox("Engagement", ids, index=idx,
                              format_func=lambda i: names[i])
        st.session_state["engagement_id"] = chosen
    else:
        st.info("No engagements yet - create one in step 1.")

    step = st.radio("Workflow", list(STEPS), label_visibility="collapsed")
    if demo.is_demo():
        with st.expander("📥 Sample input files"):
            st.caption("Synthetic SAP-style exports - try importing them "
                       "into a new engagement.")
            for label, path in demo.sample_files().items():
                st.download_button(label, path.read_bytes(),
                                   file_name=path.name, key=f"dl_{path.name}")
        st.caption(f"v{__version__} | public demo | synthetic data, "
                   f"fictional utility")
    else:
        st.caption(f"v{__version__} | SA 315 - SA 530 - SA 230 | data stays "
                   f"on this machine")

STEPS[step].render(user)
