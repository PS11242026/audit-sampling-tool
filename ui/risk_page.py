"""Step 4: SA 315 risk configuration - thresholds, factor weights and
per-category settings, with every change logged with a reason."""

import json

import pandas as pd
import streamlit as st

from core import risk
from storage import auditlog
from ui.common import require_engagement, require_role

_CAT_COLS = ["category", "manual_weight", "control", "complexity",
             "regulatory", "prior_qualified", "new_oneoff", "cutoff_mode",
             "cutoff_value", "preferred_method", "notes"]


def render(user):
    st.header("4. Risk configuration (SA 315)")
    eng = require_engagement()
    if not eng:
        return
    eid = eng["id"]
    cfg = risk.load_config(eid)

    st.subheader("Strategy thresholds")
    st.caption("Assigned weight >= the 100% threshold routes the category "
               "to full verification (or hybrid when a cutoff is set - "
               "items at/above the cutoff 100%, the rest sampled). Between "
               "the thresholds: stratified/MUS sampling. Below: small "
               "random sample.")
    th = cfg["thresholds"]
    c1, c2, c3 = st.columns(3)
    full_min = c1.number_input("100% verification at score >=", 1.0, 10.0,
                               float(th["full_min"]), 0.5)
    sample_min = c2.number_input("Sampling at score >=", 1.0, 10.0,
                                 float(th["sample_min"]), 0.5)
    floor_n = c3.number_input("Low-risk random sample floor n", 5, 500,
                              int(th["low_floor_n"]), 5)

    with st.expander("Factor weights for the computed score"):
        fw = dict(cfg["factor_weights"])
        cols = st.columns(4)
        for i, (k, v) in enumerate(fw.items()):
            fw[k] = cols[i % 4].number_input(k, 0.0, 10.0, float(v), 0.5,
                                             key=f"fw_{k}")
        st.caption("The computed score is the weighted average of factor "
                   "scores (size vs PM, prior qualification, regulatory, "
                   "control strength, complexity, volume, new/one-off), "
                   "scaled 1-10. It is shown alongside the assigned weight; "
                   "the assigned weight prevails when set.")

    st.subheader("Category settings")
    rows = [{"category": name, **{k: s.get(k) for k in _CAT_COLS[1:]}}
            for name, s in cfg["categories"].items()]
    df = pd.DataFrame(rows)[_CAT_COLS]
    edited = st.data_editor(
        df, hide_index=True, num_rows="fixed", key="risk_editor",
        column_config={
            "category": st.column_config.TextColumn("category",
                                                    disabled=True,
                                                    width="large"),
            "manual_weight": st.column_config.NumberColumn(
                "assigned weight (1-10)", min_value=1.0, max_value=10.0,
                step=0.5),
            "control": st.column_config.SelectboxColumn(
                "control", options=list(risk.CONTROL_SCORES)),
            "complexity": st.column_config.SelectboxColumn(
                "complexity", options=list(risk.COMPLEXITY_SCORES)),
            "regulatory": st.column_config.CheckboxColumn("regulatory"),
            "prior_qualified": st.column_config.CheckboxColumn(
                "prior qualification"),
            "new_oneoff": st.column_config.CheckboxColumn("new/one-off"),
            "cutoff_mode": st.column_config.SelectboxColumn(
                "cutoff mode", options=risk.CUTOFF_MODES),
            "cutoff_value": st.column_config.NumberColumn(
                "cutoff value (Rs or % of PM)"),
            "preferred_method": st.column_config.SelectboxColumn(
                "preferred method", options=risk.METHODS),
            "notes": st.column_config.TextColumn("notes", width="large"),
        })

    reason = st.text_input("Reason for change (recorded in the audit trail)")
    c1, c2 = st.columns(2)
    if c1.button("Save risk configuration", type="primary"):
        if require_role(user, "Manager", "Changing the risk configuration"):
            if not reason.strip():
                st.error("A reason is required - it is part of the SA 230 "
                         "documentation.")
            else:
                new_cfg = json.loads(json.dumps(cfg))
                new_cfg["thresholds"] = {"full_min": full_min,
                                         "sample_min": sample_min,
                                         "low_floor_n": int(floor_n)}
                new_cfg["factor_weights"] = fw
                changed = []
                for r in edited.to_dict("records"):
                    name = r.pop("category")
                    old = new_cfg["categories"].get(name, {})
                    merged = dict(old)
                    merged.update({k: (None if pd.isna(v) else v)
                                   if not isinstance(v, str) else v
                                   for k, v in r.items()})
                    for flag in ("regulatory", "prior_qualified",
                                 "new_oneoff"):
                        merged[flag] = bool(merged.get(flag))
                    if json.dumps(merged, sort_keys=True, default=str) != \
                            json.dumps(old, sort_keys=True, default=str):
                        changed.append(name)
                    new_cfg["categories"][name] = merged
                risk.save_config(eid, new_cfg, user["username"])
                auditlog.log(user, "RISK_CONFIG",
                             details={"reason": reason.strip(),
                                      "changed_categories": changed,
                                      "thresholds": new_cfg["thresholds"]},
                             engagement_id=eid)
                changed_txt = ", ".join(changed) or \
                    "none (thresholds/weights only)"
                st.success(f"Saved. Changed categories: {changed_txt}. "
                           f"Re-run the analysis (step 5) to apply.")
    if c2.button("Reset to default template"):
        if require_role(user, "Manager", "Resetting the risk configuration"):
            risk.save_config(eid, risk.default_config(), user["username"])
            auditlog.log(user, "RISK_CONFIG",
                         details={"reason": "reset to default template"},
                         engagement_id=eid)
            st.rerun()
