"""Step 10: generate and download the deliverables - Excel workpaper pack,
PDF sampling memorandum, CSV extracts. Copies are archived under
data/exports/ with timestamps."""

from datetime import datetime

import streamlit as st

from core import risk
from reports import excel_pack, pdf_memo
from storage import auditlog, db
from ui.common import require_engagement


def _archive(eng_id: int, filename: str, content: bytes) -> str:
    folder = db.data_dir() / "exports" / f"engagement_{eng_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_bytes(content)
    return str(path)


def render(user):
    st.header("10. Reports & export")
    eng = require_engagement()
    if not eng:
        return
    eid = eng["id"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    stale = risk.analysis_stale(eid)
    if stale:
        st.error(f"Categorization has changed since the last analysis run "
                 f"({stale['run_ts']}). The populations, risk matrix and "
                 f"100% list in these deliverables would not reflect the "
                 f"ledger - re-run the analysis (step 5) first.")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Excel workpaper pack")
        st.caption("Cover & sign-off, materiality, populations & risk "
                   "matrix, 100% list, one tab per sample with parameter "
                   "box and testing columns, evaluation, SERC "
                   "reconciliation, balance confirmations (SA 505), "
                   "exceptions, audit trail. Re-importable after testing "
                   "(step 9).")
        if st.button("Generate Excel pack", type="primary"):
            content = excel_pack.generate_workpaper_pack(eid, user)
            name = f"workpaper_pack_{ts}.xlsx"
            path = _archive(eid, name, content)
            st.session_state["pack_bytes"] = content
            st.session_state["pack_name"] = name
            st.success(f"Generated ({len(content)/1024:.0f} KB); archived "
                       f"at {path}")
        if st.session_state.get("pack_bytes"):
            st.download_button(
                "Download " + st.session_state["pack_name"],
                st.session_state["pack_bytes"],
                file_name=st.session_state["pack_name"],
                mime="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet")

    with c2:
        st.subheader("PDF sampling memorandum")
        st.caption("SA 315/320/530/230 narrative: methods, parameters, "
                   "seeds, SERC tie-out, conclusions, sign-off blocks.")
        if st.button("Generate PDF memo", type="primary"):
            content = pdf_memo.generate_memo(eid, user)
            name = f"sampling_memo_{ts}.pdf"
            path = _archive(eid, name, content)
            st.session_state["memo_bytes"] = content
            st.session_state["memo_name"] = name
            st.success(f"Generated ({len(content)/1024:.0f} KB); archived "
                       f"at {path}")
        if st.session_state.get("memo_bytes"):
            st.download_button(
                "Download " + st.session_state["memo_name"],
                st.session_state["memo_bytes"],
                file_name=st.session_state["memo_name"],
                mime="application/pdf")

    st.subheader("CSV extracts")
    c3, c4 = st.columns(2)
    with c3:
        full = risk.full_list_txns(eid)
        if len(full):
            st.download_button(
                f"100% verification list ({len(full):,} items)",
                full.to_csv(index=False).encode("utf-8"),
                file_name=f"full_verification_list_{ts}.csv",
                mime="text/csv")
    with c4:
        trail = auditlog.fetch(engagement_id=eid, limit=100000)
        if len(trail):
            st.download_button(
                f"Audit trail ({len(trail):,} entries)",
                trail.to_csv(index=False).encode("utf-8"),
                file_name=f"audit_trail_{ts}.csv", mime="text/csv")

    folder = db.data_dir() / "exports" / f"engagement_{eid}"
    if folder.exists():
        files = sorted(folder.glob("*"), reverse=True)
        if files:
            st.subheader("Previously archived exports")
            for f in files[:20]:
                st.caption(f"{f.name}  ({f.stat().st_size/1024:.0f} KB)")
