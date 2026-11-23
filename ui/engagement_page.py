"""Step 1: engagement setup and the SA 320 materiality worksheet."""

from datetime import date

import streamlit as st

from core import categorizer, materiality, risk
from core.formatting import inr
from storage import auditlog, db
from ui.common import current_engagement, money_metric, require_role


def render(user):
    st.header("1. Engagement & materiality")

    flash = st.session_state.pop("eng_flash", None)
    if flash:
        st.success(flash)

    engagements = db.list_engagements()
    with st.expander("Create new engagement",
                     expanded=(len(engagements) == 0)):
        with st.form("new_eng"):
            name = st.text_input(
                "Engagement name", value="Kestrel Transmission FY2026 Statutory Audit",
                key="ne_name")
            company = st.text_input(
                "Company",
                value="Kestrel Transmission Ltd",
                key="ne_company")
            c1, c2 = st.columns(2)
            fy_start = c1.date_input("FY start", value=date(2025, 4, 1),
                                     key="ne_fy_start")
            fy_end = c2.date_input("FY end", value=date(2026, 3, 31),
                                   key="ne_fy_end")
            control = st.text_input(
                "Regulatory context",
                value="SERC MYT Control Period FY2025-26 to FY2029-30",
                key="ne_control")
            if st.form_submit_button("Create engagement", type="primary"):
                open_names = {e["name"].strip().lower()
                              for e in db.list_engagements()}
                if not name.strip():
                    st.error("Engagement name is required.")
                elif name.strip().lower() in open_names:
                    st.error(
                        f'An open engagement named "{name.strip()}" already '
                        f"exists - select it in the sidebar (entries show "
                        f"their #id), or choose a different name. Nothing "
                        f"was created.")
                else:
                    eid = db.create_engagement(
                        name.strip(), company, fy_start.isoformat(),
                        fy_end.isoformat(), control, user["username"])
                    categorizer.ensure_default_rules(eid)
                    risk.ensure_default_config(eid)
                    auditlog.log(user, "CREATE_ENGAGEMENT",
                                 details={"name": name.strip(),
                                          "company": company,
                                          "fy": f"{fy_start} to {fy_end}"},
                                 engagement_id=eid)
                    st.session_state["engagement_id"] = eid
                    st.session_state["eng_flash"] = (
                        f'Engagement #{eid} "{name.strip()}" created and '
                        f"selected. Next: set materiality below, then "
                        f"import data (step 2).")
                    st.rerun()

    eng = current_engagement()
    if not eng:
        st.info("Create an engagement to begin, or select one in the "
                "sidebar.")
        return

    st.subheader(eng["name"])
    st.caption(
        f"{eng['company']} | FY {eng['fy_start']} to {eng['fy_end']} | "
        f"{eng.get('control_period') or ''} | engagement master seed "
        f"**{eng['master_seed']}** (printed on every report; all sample "
        f"seeds derive from it)")

    st.subheader("Materiality worksheet (SA 320)")
    mat = materiality.load(eng["id"]) or {}
    with st.form("mat_form"):
        c1, c2, c3 = st.columns(3)
        benchmark = c1.selectbox(
            "Benchmark", materiality.BENCHMARKS,
            index=materiality.BENCHMARKS.index(mat["benchmark"])
            if mat.get("benchmark") in materiality.BENCHMARKS else 0)
        amount = c2.number_input(
            "Benchmark amount (Rs)", min_value=0.0,
            value=float(mat.get("benchmark_amount") or 0.0),
            step=10_000_000.0, format="%.0f")
        percent = c3.number_input(
            "Percentage applied (%)", min_value=0.0, max_value=25.0,
            value=float(mat.get("percent") or 0.5), step=0.05,
            help="Typical ranges - " + "; ".join(
                f"{k}: {v}" for k, v in materiality.GUIDANCE.items()))
        c4, c5, c6 = st.columns(3)
        pm_pct = c4.number_input(
            "Performance materiality (% of overall)", min_value=10.0,
            max_value=100.0, value=float(mat.get("pm_percent") or 75.0),
            step=5.0)
        isl = c5.number_input(
            "Individually significant item cutoff (Rs, 0 = use PM)",
            min_value=0.0, value=float(mat.get("isl_cutoff") or 0.0),
            step=1_000_000.0, format="%.0f")
        notes = c6.text_input("Notes", value=mat.get("notes") or "")
        if st.form_submit_button("Save materiality", type="primary"):
            if require_role(user, "Manager", "Setting materiality"):
                calc = materiality.compute(amount, percent, pm_pct)
                values = {
                    "benchmark": benchmark, "benchmark_amount": amount,
                    "percent": percent, "overall": calc["overall"],
                    "pm_percent": pm_pct,
                    "performance": calc["performance"],
                    "isl_cutoff": isl or calc["performance"],
                    "notes": notes,
                }
                materiality.save(eng["id"], values, user["username"])
                auditlog.log(user, "SET_MATERIALITY", details=values,
                             engagement_id=eng["id"])
                st.session_state["eng_flash"] = (
                    f"Materiality saved for engagement #{eng['id']}: "
                    f"overall {inr(calc['overall'])}, performance "
                    f"{inr(calc['performance'])}.")
                st.rerun()

    mat = materiality.load(eng["id"])
    if mat:
        c1, c2, c3 = st.columns(3)
        with c1:
            money_metric("Overall materiality", mat["overall"])
        with c2:
            money_metric("Performance materiality", mat["performance"])
        with c3:
            money_metric("Individually significant cutoff",
                         mat["isl_cutoff"])
        st.caption(f"Set by {mat.get('updated_by')} at "
                   f"{mat.get('updated_at')}. Items at or above the cutoff "
                   f"are always verified 100% regardless of category "
                   f"strategy. Overall = benchmark x %; performance "
                   f"materiality = overall x {mat.get('pm_percent')}%.")
    else:
        st.info(f"Materiality not set yet for engagement #{eng['id']} - "
                f"required before the analysis run. Example: Total revenue "
                f"{inr(50_000_000_000)} at 0.5% gives overall materiality "
                f"{inr(250_000_000)}.")

    with st.expander("Danger zone: archive this engagement"):
        st.caption("Archiving removes the engagement from the sidebar; all "
                   "its data and audit-trail entries remain in the "
                   "database. Partner only.")
        confirm = st.checkbox(
            f'Yes, archive engagement #{eng["id"]} "{eng["name"]}"',
            key=f"arch_confirm_{eng['id']}")
        if st.button("Archive engagement", disabled=not confirm,
                     key=f"arch_btn_{eng['id']}"):
            if require_role(user, "Partner", "Archiving an engagement"):
                db.set_engagement_status(eng["id"], "archived")
                auditlog.log(user, "ARCHIVE_ENGAGEMENT",
                             details={"name": eng["name"]},
                             engagement_id=eng["id"])
                st.session_state.pop("engagement_id", None)
                st.session_state["eng_flash"] = (
                    f"Engagement #{eng['id']} archived.")
                st.rerun()
