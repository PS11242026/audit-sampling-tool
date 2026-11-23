"""Step 5: the analysis run - scores every population, splits 100% items
from sampling populations, stamps anomaly flags."""

import streamlit as st

from core import anomalies, materiality, risk
from storage import auditlog, db
from ui.common import (money_cols_config, money_metric, require_engagement,
                       require_ledger, sampling_methodology_pdf)

_POP_VIEW = {
    "category": "Category", "txn_count": "Items", "total_abs": "Total value",
    "computed_score": "Computed", "manual_weight": "Assigned",
    "final_score": "Final score", "strategy": "Strategy",
    "cutoff_used": "Cutoff", "full_count": "100% items",
    "full_value": "100% value", "sample_count": "Sampleable",
    "sample_value": "Sampleable value",
}


def render(user):
    st.header("5. Analysis run")
    eng = require_engagement()
    if not eng or not require_ledger(eng):
        return
    eid = eng["id"]
    if not materiality.load(eid):
        st.warning("Set materiality first (step 1).")
        return

    if st.button("Run analysis", type="primary"):
        try:
            summary = risk.run_analysis(eid, user["username"])
            auditlog.log(user, "RUN_ANALYSIS", details=summary,
                         engagement_id=eid)
            st.success(f"Analysed {summary['transactions']:,} transactions "
                       f"across {summary['populations']} populations; "
                       f"{summary['full_items']:,} items routed to 100% "
                       f"verification.")
        except ValueError as e:
            st.error(str(e))

    pops = risk.get_populations(eid)
    if not len(pops):
        st.info("Not yet run. The analysis applies the risk configuration, "
                "stamps anomaly flags, and routes items to 100% "
                "verification or sampling populations.")
        return

    stale = risk.analysis_stale(eid)
    if stale:
        moved = "; ".join(
            f"{c['category']}: {c['items_at_run']:,} -> {c['items_now']:,}"
            for c in stale["changed"][:6])
        st.error(f"Stale analysis: categorization has changed since this "
                 f"run ({stale['run_ts']}). Items per category then vs now "
                 f"- {moved}. Re-run the analysis; until then these "
                 f"populations, the 100% list and any sample drawn from "
                 f"them do not reflect the ledger.")

    view = pops[list(_POP_VIEW)].rename(columns=_POP_VIEW)
    st.dataframe(view, hide_index=True, column_config=money_cols_config(
        view, ["Total value", "Cutoff", "100% value", "Sampleable value"]))
    st.caption("Strategies - FULL: whole category verified 100%. HYBRID: "
               "items at/above the category cutoff 100%, remainder sampled. "
               "SAMPLE / SAMPLE_LOW: sampled by the preferred method. "
               "Individually significant and contra items are always 100% "
               "regardless of strategy.")

    sampling_methodology_pdf(eid, user)

    full = risk.full_list_txns(eid)
    c1, c2, c3 = st.columns(3)
    c1.metric("Items for 100% verification", f"{len(full):,}")
    with c2:
        money_metric("Value under 100% verification",
                     float(full["amount_abs"].sum()) if len(full) else 0)
    with c3:
        money_metric("Value in sampling populations",
                     float(pops["sample_value"].sum()))

    with st.expander(f"100% verification list ({len(full):,} items - "
                     f"first 500 shown; full list in the Excel pack)"):
        show = full.head(500)[["date", "doc_no", "account", "account_name",
                               "narration", "amount_abs", "category",
                               "flags", "full_reason"]]
        st.dataframe(show, hide_index=True,
                     column_config=money_cols_config(show, ["amount_abs"]))

    txns = db.active_transactions(eid)
    summ = anomalies.summarize(txns["flags"])
    if len(summ):
        st.subheader("Anomaly flags (transaction analyzer)")
        st.dataframe(summ, hide_index=True)
        flagged = txns[txns["flags"].astype(str).ne("")]
        with st.expander(f"Flagged transactions ({len(flagged):,} - first "
                         f"500 shown)"):
            show = flagged.head(500)[["date", "doc_no", "account",
                                      "narration", "amount_abs", "side",
                                      "category", "flags"]]
            st.dataframe(show, hide_index=True,
                         column_config=money_cols_config(show,
                                                         ["amount_abs"]))
        st.caption("DUPLICATE same account+amount+date | ROUND lakh "
                   "multiples above threshold | PERIOD_END last week of FY "
                   "| WEEKEND | KEYWORD sensitive narration | CONTRA "
                   "abnormal side (auto-routed to 100%) | ZERO excluded "
                   "from sampling.")
