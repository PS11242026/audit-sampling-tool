"""Step 7: SERC tariff-order parameters and the regulated revenue
reconciliation (monthly + annual tie-out)."""

import numpy as np
import streamlit as st

from core import importer, serc
from core.formatting import inr
from storage import auditlog, db
from ui.common import money_cols_config, require_engagement, require_role


def _parse_param_file(up):
    raw = importer.read_table(up.getvalue(), up.name)
    if len(raw.columns) < 2:
        return {}
    found = {}
    for r in raw.itertuples(index=False):
        label = str(r[0]).lower()
        value = r[1]
        num = importer.parse_amount(value)
        if "transmission" in label and num is not None:
            found["approved_atc"] = num
        elif "wheeling" in label and num is not None:
            found["approved_wheeling"] = num
        elif "true" in label and num is not None:
            found["trueup_adjustment"] = num
        elif "incentive" in label and num is not None:
            found["incentive"] = num
        elif "threshold" in label and num is not None:
            found["variance_threshold_pct"] = num
        elif "order" in label or "reference" in label:
            found["tariff_order_ref"] = str(value)
    return found


def render(user):
    st.header("7. SERC reconciliation (regulated revenue)")
    eng = require_engagement()
    if not eng:
        return
    eid = eng["id"]
    data = serc.load(eid)

    up = st.file_uploader("Optional: upload tariff-order parameters "
                          "(Excel/CSV with Parameter | Value columns)",
                          type=["xlsx", "xlsm", "csv"], key="serc_up")
    if up:
        found = _parse_param_file(up)
        if found:
            data.update(found)
            st.info("Pre-filled from file: "
                    + ", ".join(f"{k} = {v:,.0f}" if isinstance(v, float)
                                else f"{k} = {v}" for k, v in found.items())
                    + ". Review and save below.")
        else:
            st.warning("No recognisable parameters found in the file.")

    with st.form("serc_form"):
        c1, c2 = st.columns(2)
        control_period = c1.text_input("Control period",
                                       value=data["control_period"])
        order_ref = c2.text_input("Tariff order reference",
                                  value=data["tariff_order_ref"])
        c3, c4 = st.columns(2)
        atc = c3.number_input("Approved annual transmission charges (Rs)",
                              min_value=0.0,
                              value=float(data["approved_atc"]),
                              step=100_000_000.0, format="%.0f")
        wheeling = c4.number_input("Approved annual wheeling income (Rs)",
                                   min_value=0.0,
                                   value=float(data["approved_wheeling"]),
                                   step=10_000_000.0, format="%.0f")
        c5, c6, c7 = st.columns(3)
        trueup = c5.number_input("True-up recognised (Rs, +/-)",
                                 value=float(data["trueup_adjustment"]),
                                 step=10_000_000.0, format="%.0f")
        incentive = c6.number_input("Incentive/(penalty) recognised (Rs)",
                                    value=float(data["incentive"]),
                                    step=1_000_000.0, format="%.0f")
        threshold = c7.number_input("Monthly variance threshold (%)",
                                    min_value=0.1, max_value=25.0,
                                    value=float(
                                        data["variance_threshold_pct"]),
                                    step=0.1)
        notes = st.text_input("Notes", value=data.get("notes", ""))
        if st.form_submit_button("Save SERC parameters", type="primary"):
            if require_role(user, "Manager", "Saving SERC parameters"):
                data.update({
                    "control_period": control_period,
                    "tariff_order_ref": order_ref, "approved_atc": atc,
                    "approved_wheeling": wheeling,
                    "trueup_adjustment": trueup, "incentive": incentive,
                    "variance_threshold_pct": threshold, "notes": notes})
                serc.save(eid, data, user["username"])
                auditlog.log(user, "SET_SERC", details=data,
                             engagement_id=eid)
                st.rerun()

    txns = db.active_transactions(eid)
    if not len(txns) or not (txns["category"].astype(str)
                             .str.startswith("Electricity income").any()):
        st.info("Import and categorize the ledger to see the "
                "reconciliation (booked electricity income is taken from "
                "the categorized transactions).")
        return
    if not float(data["approved_atc"]):
        st.info("Enter the approved annual transmission charges to run the "
                "reconciliation.")
        return

    st.subheader("Monthly transmission charges vs 1/12 of approved ATC")
    monthly = serc.monthly_reconciliation(txns, data, eng["fy_start"],
                                          eng["fy_end"])
    show = monthly.copy()
    show["status"] = np.where(show["exception"], "EXCEPTION", "ok")
    st.dataframe(show, hide_index=True, column_config=money_cols_config(
        show, ["expected", "booked", "variance"]))
    n_exc = int(monthly["exception"].sum())
    if n_exc:
        st.warning(f"{n_exc} month(s) breach the "
                   f"{data['variance_threshold_pct']}% threshold - vouch "
                   f"against SERC billing statements, true-up orders and "
                   f"meter data; carried to the Exceptions sheet of the "
                   f"workpaper pack.")

    if float(data["approved_wheeling"]):
        st.subheader("Monthly wheeling charges vs 1/12 of approved value")
        wheel = serc.wheeling_reconciliation(txns, data, eng["fy_start"],
                                             eng["fy_end"])
        wshow = wheel.copy()
        wshow["status"] = np.where(wshow["exception"], "EXCEPTION", "ok")
        st.dataframe(wshow, hide_index=True,
                     column_config=money_cols_config(
                         wshow, ["expected", "booked", "variance"]))

    st.subheader("Annual tie-out")
    annual = serc.annual_tieout(txns, data)
    c1, c2, c3 = st.columns(3)
    c1.metric("Expected (order +/- adjustments)",
              inr(annual["expected_total"]))
    c2.metric("Booked electricity income", inr(annual["booked_total"]))
    c3.metric("Difference",
              f"{inr(annual['difference'])} "
              f"({annual['difference_pct']:.3f}%)")
