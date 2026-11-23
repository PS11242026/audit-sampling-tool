"""Step 2: ledger and trial balance import with column mapping (SAP preset)
and the ledger-vs-TB completeness reconciliation."""

import pandas as pd
import streamlit as st

from core import importer
from core.formatting import short_hash
from storage import auditlog, db
from ui.common import (active_import_banner, mapping_widget,
                       money_cols_config, read_upload_widget,
                       require_engagement)


def _ledger_tab(user, eng):
    active_import_banner(eng, "ledger", "ledger")
    up = st.file_uploader("Ledger file (Excel/CSV - SAP FAGLL03/FBL3N "
                          "style or any tabular export)",
                          type=["xlsx", "xlsm", "csv"], key="led_up")
    if not up:
        return
    content, raw = read_upload_widget(up, "led")

    st.markdown("**Column mapping** (auto-guessed from the SAP preset - "
                "adjust if needed)")
    mapping, missing = mapping_widget(raw, importer.LEDGER_FIELDS,
                                      importer.SAP_GUESSES, "led")
    sign = st.radio("Amount sign convention",
                    ["Debits positive / credits negative (SAP standard)",
                     "Credits positive / debits negative"],
                    horizontal=True, key="led_sign")
    tpl_name = st.text_input("Save this mapping as a reusable template "
                             "(optional name)", key="led_tpl")

    if st.button("Validate & import ledger", type="primary",
                 disabled=bool(missing)):
        clean, issues = importer.normalize_ledger(
            raw, mapping,
            "dr_pos" if sign.startswith("Debits") else "cr_pos")
        if issues["rows_imported"] == 0:
            st.error("No importable rows - check the mapping and header "
                     "row.")
            st.json(issues)
            return
        val = importer.validate_ledger(clean, eng["fy_start"], eng["fy_end"])
        sha = importer.file_sha256(content)
        importer.import_ledger(eng["id"], clean, up.name, sha, mapping,
                               user["username"])
        if tpl_name.strip():
            importer.save_mapping_template(tpl_name.strip(), "ledger",
                                           mapping, user["username"])
        auditlog.log(user, "IMPORT_LEDGER",
                     details={"filename": up.name, "sha256": sha,
                              "issues": issues, "validation": val},
                     engagement_id=eng["id"])
        st.success(f"Imported {issues['rows_imported']:,} rows "
                   f"(skipped {issues['footer_rows_skipped']} footer rows, "
                   f"excluded {issues['rows_excluded']}). File SHA-256 "
                   f"{short_hash(sha, 16)}... recorded in the audit trail.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Rows", f"{val['rows']:,}")
        c2.metric("Outside FY", val["out_of_fy"])
        c3.metric("Zero amounts", val["zero_amounts"])
        c4.metric("Duplicate doc numbers", val["duplicate_doc_numbers"])
        if issues["bad_amount_rows"] or issues["bad_date_rows"]:
            st.warning(f"Unparseable rows excluded - amounts at file rows "
                       f"{issues['bad_amount_rows']}, dates at "
                       f"{issues['bad_date_rows']} (first 20 shown; "
                       f"recorded in the audit trail).")
    elif missing:
        st.info("Map the required fields marked * to enable import: "
                + ", ".join(missing))


def _tb_tab(user, eng):
    active_import_banner(eng, "tb", "trial balance")
    up = st.file_uploader("Trial balance file (Excel/CSV)",
                          type=["xlsx", "xlsm", "csv"], key="tb_up")
    if not up:
        return
    content, raw = read_upload_widget(up, "tb")
    mapping, missing = mapping_widget(raw, importer.TB_FIELDS,
                                      importer.TB_GUESSES, "tb")

    warns = importer.tb_mapping_warnings(raw, mapping)
    for w in warns:
        st.warning(w)
    confirmed = True
    if warns:
        confirmed = st.checkbox("I've reviewed the mapping above - import "
                                "anyway", key="tb_confirm")

    if st.button("Import trial balance", type="primary",
                 disabled=bool(missing) or not confirmed):
        clean, issues = importer.normalize_tb(raw, mapping)
        if issues["rows_imported"] == 0:
            st.error("No importable rows - check the mapping.")
            return
        sha = importer.file_sha256(content)
        importer.import_tb(eng["id"], clean, up.name, sha, mapping,
                           user["username"])
        auditlog.log(user, "IMPORT_TB",
                     details={"filename": up.name, "sha256": sha,
                              "issues": issues},
                     engagement_id=eng["id"])
        st.success(f"Imported {issues['rows_imported']:,} TB rows.")


def render(user):
    st.header("2. Data import")
    eng = require_engagement()
    if not eng:
        return

    tab_ledger, tab_tb = st.tabs(["General ledger", "Trial balance"])
    with tab_ledger:
        _ledger_tab(user, eng)
    with tab_tb:
        _tb_tab(user, eng)

    txns = db.active_transactions(eng["id"])
    tb = db.active_trial_balance(eng["id"])
    if len(txns) and len(tb):
        st.subheader("Ledger vs trial balance reconciliation "
                     "(completeness check)")
        recon = importer.tb_reconcile(txns, tb)
        stats = importer.reconcile_stats(recon)
        c1, c2, c3 = st.columns(3)
        c1.metric("Ledger accounts", stats["ledger_accounts"])
        c2.metric("Matched to TB", stats["matched_accounts"])
        c3.metric("Not reconciling", stats["matched_mismatch"])

        if stats["matched_accounts"] == 0:
            st.error(
                f"None of the {stats['ledger_accounts']} ledger accounts were "
                f"found among the {stats['tb_accounts']} trial-balance "
                f"accounts, so nothing can tie. The 'Account code' columns are "
                f"almost certainly mapped to the wrong field - re-import the "
                f"trial balance on the **Trial balance** tab above and map "
                f"'Account code' to the column holding the G/L account numbers "
                f"(not amounts).")
            peek = pd.DataFrame({
                "ledger account (sample)": pd.Series(
                    sorted(txns["account"].unique())[:8]),
                "TB 'account' (sample)": pd.Series(
                    list(tb["account"].unique())[:8]),
            })
            st.caption("What the two sides currently look like:")
            st.dataframe(peek, hide_index=True)
        else:
            matched = recon[recon["in_ledger"] & recon["in_tb"]].copy()
            no_movement = (stats["matched_ok"] == 0
                           and matched["tb_movement"].abs().sum() == 0)
            mism = matched[~matched["ok"]]
            if no_movement:
                st.error(
                    "Every account matches by code, but the trial balance "
                    "carries no movement (all balances are zero) - so nothing "
                    "can tie. The amount columns were not mapped: re-import the "
                    "trial balance on the **Trial balance** tab above and map "
                    "its Debit and Credit columns, or its Opening and Closing "
                    "balances.")
            elif len(mism):
                st.error(f"{len(mism)} of {stats['matched_accounts']} matched "
                         f"account(s) do not reconcile - resolve before "
                         f"relying on the ledger for sampling.")
            else:
                st.success("Every matched account's ledger movement ties to "
                           "the trial balance (within Rs 1).")

            # "ok" is a computed check, not a control to tick - render it as a
            # plain status so it doesn't look like a clickable box.
            matched["status"] = matched["ok"].map(
                lambda v: "OK - ties" if v else "off")
            show = matched.sort_values("ok")[[
                "account", "account_name", "tb_movement", "ledger_net",
                "difference", "status"]]
            st.dataframe(show, hide_index=True, column_config=money_cols_config(
                show, ["tb_movement", "ledger_net", "difference"]))
            st.caption("This reconciliation is a check that recomputes on its "
                       "own - there is no box to tick. Clear any 'off' rows "
                       "(usually by fixing a column mapping above), then use "
                       "the workflow list in the sidebar to move to step 3.")
            if stats["ledger_only"]:
                st.warning(f"{stats['ledger_only']} ledger account(s) are not "
                           f"present in the trial balance - a possible "
                           f"completeness gap worth checking.")
