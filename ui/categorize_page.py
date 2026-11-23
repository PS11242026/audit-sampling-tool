"""Step 3: transaction categorization - rules editor, apply, and quick
assignment of uncategorized account codes."""

import pandas as pd
import streamlit as st

from core import categorizer
from storage import auditlog, db
from ui.common import (money_cols_config, require_engagement, require_ledger,
                       require_role)


def render(user):
    st.header("3. Categorize transactions")
    eng = require_engagement()
    if not eng or not require_ledger(eng):
        return
    eid = eng["id"]

    st.subheader("Categorization rules")
    st.caption("First matching rule by priority wins. Fields: account "
               "(prefix/range/regex) or narration (contains/regex). Edit "
               "cells, add rows at the bottom, then save (Manager+).")
    rules = categorizer.load_rules(eid)
    edited = st.data_editor(
        rules, num_rows="dynamic", hide_index=True, key="rules_editor",
        column_config={
            "id": None,
            "priority": st.column_config.NumberColumn("priority", step=1),
            "field": st.column_config.SelectboxColumn(
                "field", options=["account", "narration"]),
            "match_type": st.column_config.SelectboxColumn(
                "match_type",
                options=["prefix", "contains", "regex", "range"]),
            "category": st.column_config.SelectboxColumn(
                "category", options=categorizer.ALL_CATEGORIES,
                width="large"),
            "active": st.column_config.CheckboxColumn("active"),
        })
    c1, c2 = st.columns(2)
    if c1.button("Save rules"):
        if require_role(user, "Manager", "Editing categorization rules"):
            categorizer.save_rules(eid, edited)
            auditlog.log(user, "SAVE_RULES",
                         details={"rules": int(len(edited))},
                         engagement_id=eid)
            st.success(f"Saved {len(edited)} rules.")
    if c2.button("Apply rules to ledger", type="primary"):
        summary = categorizer.apply_to_engagement(eid)
        auditlog.log(user, "CATEGORIZE", details=summary, engagement_id=eid)
        st.success(f"Categorized {summary['total']:,} transactions; "
                   f"{summary['uncategorized']:,} uncategorized.")

    txns = db.active_transactions(eid)
    if len(txns):
        st.subheader("Current distribution")
        dist = txns.groupby("category").agg(
            items=("id", "count"),
            value=("amount_abs", "sum")).reset_index().sort_values(
            "value", ascending=False)
        st.dataframe(dist, hide_index=True,
                     column_config=money_cols_config(dist, ["value"]))

        uncat = txns[txns["category"] == categorizer.UNCATEGORIZED]
        if len(uncat):
            st.subheader(f"Uncategorized: {len(uncat):,} transactions")
            accounts = uncat.groupby(["account", "account_name"]).agg(
                items=("id", "count"),
                value=("amount_abs", "sum")).reset_index()
            st.dataframe(accounts, hide_index=True,
                         column_config=money_cols_config(accounts, ["value"]))
            pick = st.multiselect(
                "Assign these account codes...",
                accounts["account"].tolist(), key="uncat_pick")
            target = st.selectbox("...to category",
                                  categorizer.ALL_CATEGORIES[:-1],
                                  key="uncat_target")
            if st.button("Create rules & re-apply") and pick:
                if require_role(user, "Manager", "Adding rules"):
                    add = pd.DataFrame(
                        [{"priority": 5, "field": "account",
                          "match_type": "prefix", "pattern": a,
                          "category": target, "active": 1} for a in pick])
                    categorizer.save_rules(
                        eid, pd.concat([categorizer.load_rules(eid), add],
                                       ignore_index=True))
                    summary = categorizer.apply_to_engagement(eid)
                    auditlog.log(user, "SAVE_RULES",
                                 details={"quick_assign": pick,
                                          "category": target},
                                 engagement_id=eid)
                    auditlog.log(user, "CATEGORIZE", details=summary,
                                 engagement_id=eid)
                    st.rerun()
        else:
            st.success("No uncategorized transactions - ready for the "
                       "analysis run (step 5).")
