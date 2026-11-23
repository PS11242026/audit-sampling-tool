"""Step 6: sample generation per population - live SA 530 size calculation,
seeds derived from the engagement master seed, logged regeneration with
justification, CSV export of selections."""

import streamlit as st

from core import materiality, risk, sampling_service
from core.formatting import inr, short_hash
from storage import db
from ui.common import (money_cols_config, money_metric, require_engagement,
                       require_role, sampling_methodology_pdf)

_METHOD_LABELS = {
    "mus": "Monetary unit sampling (MUS)",
    "stratified": "Stratified by value bands",
    "systematic": "Systematic (fixed interval, random start)",
    "random": "Simple random",
}


def render(user):
    st.header("6. Sampling (SA 530)")
    eng = require_engagement()
    if not eng:
        return
    eid = eng["id"]
    pops = risk.get_populations(eid)
    if not len(pops):
        st.warning("Run the analysis first (step 5).")
        return
    stale = risk.analysis_stale(eid)
    if stale:
        st.error(f"Categorization has changed since the last analysis run "
                 f"({stale['run_ts']}), so these populations no longer "
                 f"match the ledger. Re-run the analysis (step 5) before "
                 f"generating samples; samples drawn from the previous run "
                 f"should be regenerated with a justification.")
        _samples_section(user, eid)
        return
    sampling_methodology_pdf(eid, user)
    cand = pops[(pops["sample_count"] > 0) & (pops["strategy"] != "FULL")]
    if not len(cand):
        st.info("No sampling populations - every category is under 100% "
                "verification.")
        return

    labels = {r.category: (f"{r.category}  |  {r.strategy}, "
                           f"{r.sample_count:,} items, {inr(r.sample_value)}")
              for r in cand.itertuples(index=False)}
    category = st.selectbox("Population", list(labels),
                            format_func=lambda c: labels[c])
    pop_row = cand[cand["category"] == category].iloc[0]
    pop = sampling_service.population(eid, category)
    mat = materiality.load(eid)
    pm = float(mat["performance"]) if mat else 0.0
    cfg = risk.load_config(eid)
    floor_n = int(cfg["thresholds"]["low_floor_n"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sampleable items", f"{len(pop):,}")
    with c2:
        money_metric("Book value", float(pop["amount_abs"].sum()))
    c3.metric("Strategy", pop_row["strategy"])
    c4.metric("Risk score", f"{pop_row['final_score']:g}")

    existing = sampling_service.list_samples(eid)
    mine = existing[existing["category"] == category] if len(existing) \
        else existing
    active_exists = len(mine) and \
        mine["status"].isin(["draft", "final"]).any()

    st.subheader("Parameters")
    methods = list(_METHOD_LABELS)
    preferred = cfg["categories"].get(category, {}).get("preferred_method",
                                                        "mus")
    method = st.selectbox("Selection method", methods,
                          index=methods.index(preferred)
                          if preferred in methods else 0,
                          format_func=lambda m: _METHOD_LABELS[m])
    confidence = st.selectbox("Confidence level", [0.90, 0.95, 0.99],
                              index=1, format_func=lambda c: f"{c:.0%}")
    params = {"confidence": confidence}
    suggested = floor_n

    if method == "mus":
        c1, c2 = st.columns(2)
        tolerable = c1.number_input(
            "Tolerable misstatement (Rs)", min_value=1.0,
            value=float(pm or 1_000_000.0), step=1_000_000.0, format="%.0f",
            help="Defaults to performance materiality (SA 320).")
        expected = c2.number_input(
            "Expected misstatement (Rs)", min_value=0.0, value=0.0,
            step=100_000.0, format="%.0f",
            help="From prior-year findings or preliminary tests.")
        params.update({"tolerable": tolerable, "expected": expected})
        try:
            calc = sampling_service.compute_size("mus", pop, params)
            suggested = calc["n"]
            st.info(f"Computed n = **{calc['n']}** | reliability factor "
                    f"{calc['rf0']:.2f}, expansion factor "
                    f"{calc['expansion_factor']}, sampling interval "
                    f"{inr(calc['interval'])}.  Formula: n = BV x RF / "
                    f"(TM - EM x EF); items >= the interval are examined "
                    f"100% (top stratum).")
        except ValueError as e:
            st.error(str(e))
    else:
        c1, c2 = st.columns(2)
        tol_rate = c1.number_input("Tolerable deviation rate (%)", 0.5, 50.0,
                                   10.0, 0.5) / 100.0
        exp_rate = c2.number_input("Expected deviation rate (%)", 0.0, 20.0,
                                   0.0, 0.25) / 100.0
        params.update({"tolerable_rate": tol_rate,
                       "expected_rate": exp_rate})
        try:
            calc = sampling_service.compute_size(method, pop, params)
            suggested = calc.get("n_with_fpc", calc["n"])
            st.info(f"Attribute-based n = **{calc['n']}**"
                    + (f" ({calc['n_with_fpc']} with finite population "
                       f"correction)" if "n_with_fpc" in calc else "")
                    + f", allowing {calc['allowed_deviations']} "
                      f"deviation(s).")
        except ValueError as e:
            st.error(str(e))
        if method == "stratified":
            c3, c4 = st.columns(2)
            params["n_bands"] = int(c3.slider("Value bands", 2, 6, 4))
            params["allocation"] = c4.radio(
                "Allocation across bands", ["value", "count"],
                horizontal=True,
                help="Proportional to band value gives high-value bands "
                     "larger allocations (SA 530 A8-A9).")
        if method == "random":
            params["replace"] = st.checkbox("With replacement", value=False)
        if method == "systematic":
            st.caption("Caution (SA 530 A13): confirm the population is not "
                       "ordered with a period matching the interval.")

    if pop_row["strategy"] == "SAMPLE_LOW":
        suggested = max(int(suggested), floor_n)
    n = st.number_input("Sample size n", min_value=1,
                        max_value=int(len(pop)),
                        value=int(min(max(int(suggested), 1), len(pop))))
    params["n"] = int(n)

    default_seed = sampling_service.default_seed(
        eng["master_seed"], category,
        sampling_service.next_generation_no(eid, category))
    custom_seed = 0
    if user.get("role") in ("Manager", "Partner"):
        custom_seed = int(st.number_input(
            f"Seed (0 = auto-derived: {default_seed})", min_value=0,
            value=0, help="Auto seeds derive from the engagement master "
                          "seed, category and generation number - fully "
                          "reproducible. Enter a prior seed to re-draw an "
                          "identical selection."))
    else:
        st.caption(f"Seed (auto-derived from master seed): {default_seed}")

    justification = ""
    if active_exists:
        st.warning("An active sample already exists for this population. "
                   "Generating a new one supersedes it (Manager+) and the "
                   "justification below is recorded in the audit trail.")
        justification = st.text_input("Justification for regeneration")

    if st.button("Generate sample", type="primary"):
        if active_exists:
            if not require_role(user, "Manager", "Regenerating a sample"):
                return
            if not justification.strip():
                st.error("A justification is required to supersede an "
                         "existing sample.")
                return
        try:
            sid, sel, info = sampling_service.generate(
                eid, category, method, params, user,
                justification=justification.strip(),
                seed=(custom_seed or None))
            st.session_state["view_sample_id"] = sid
            st.rerun()
        except ValueError as e:
            st.error(str(e))

    _samples_section(user, eid)


def _samples_section(user, eid):
    st.subheader("Samples in this engagement")
    existing = sampling_service.list_samples(eid)
    if not len(existing):
        st.info("No samples generated yet.")
        return
    st.dataframe(existing, hide_index=True)
    ids = existing["id"].tolist()
    default_idx = ids.index(st.session_state.get("view_sample_id")) \
        if st.session_state.get("view_sample_id") in ids else 0
    sid = st.selectbox("View sample", ids, index=default_idx,
                       format_func=lambda i: f"S{i}")
    detail = sampling_service.get_sample(int(sid))
    info = detail["payload"].get("info", {})
    popstats = detail["payload"].get("population", {})
    st.caption(
        f"S{sid} **{detail['category']}** | {detail['method']} | status "
        f"**{detail['status']}** | generation {detail['generation_no']} | "
        f"seed **{detail['seed']}** | population "
        f"{popstats.get('count'):,} items / "
        f"{inr(popstats.get('book_value'))} | SHA-256 "
        f"{short_hash(detail['dataset_sha256'], 16)}... | interval "
        f"{inr(info.get('interval')) if info.get('interval') else '-'} | "
        f"created {detail['created_at']} by {detail['created_by']}"
        + (f" | justification: {detail['justification']}"
           if detail["justification"] else ""))
    items = sampling_service.get_sample_items(int(sid))
    st.dataframe(items.head(1000), hide_index=True,
                 column_config=money_cols_config(
                     items, ["book_value", "audited_value", "misstatement"]))
    st.download_button(
        "Download selection (CSV)",
        items.to_csv(index=False).encode("utf-8"),
        file_name=f"sample_S{sid}_{detail['category'][:20]}.csv",
        mime="text/csv")
    if detail["status"] == "draft" and st.button("Mark final",
                                                 key=f"fin_{sid}"):
        if require_role(user, "Manager", "Finalizing a sample"):
            sampling_service.set_status(int(sid), "final", user)
            st.rerun()
