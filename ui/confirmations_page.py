"""Step 8: SA 505 external balance confirmations - party-wise book balances
from the SAP export matched against the balances confirmed in writing by
customers, vendors and banks, with a per-party auditor conclusion."""

import re
from datetime import datetime

import streamlit as st

from core import confirmations
from core.formatting import inr
from core.importer import file_sha256
from storage import auditlog
from ui.common import (active_import_banner, mapping_widget,
                       read_upload_widget, require_engagement)

# side -> (label, fields, guesses, uploader prompt)
_SIDES = {
    "book": ("book balances", confirmations.BOOK_FIELDS,
             confirmations.BOOK_GUESSES,
             "Party-wise balances from SAP (FBL5N/FBL1N-style Excel/CSV; an "
             "open-item dump collapses to one balance per party)"),
    "ext": ("received confirmations", confirmations.EXT_FIELDS,
            confirmations.EXT_GUESSES,
            "Balances confirmed in writing by the external parties, "
            "tabulated one row per party (Excel/CSV)"),
}


def _slug(area: str) -> str:
    return re.sub(r"\W+", "_", area.lower()).strip("_")


def _upload_tab(user, eng, area, side):
    label, fields, guesses, prompt = _SIDES[side]
    key = f"conf_{side}_{_slug(area)}"
    active_import_banner(eng, confirmations.import_kind(side, area),
                         f"{area} {label}")
    up = st.file_uploader(prompt, type=["xlsx", "xlsm", "csv"],
                          key=f"{key}_up")
    if not up:
        return
    content, raw = read_upload_widget(up, key)
    st.markdown("**Column mapping** (auto-guessed - adjust if needed)")
    mapping, missing = mapping_widget(raw, fields, guesses, key)

    warns = confirmations.mapping_warnings(raw, mapping)
    for w in warns:
        st.warning(w)
    confirmed = True
    if warns:
        confirmed = st.checkbox("I've reviewed the mapping above - import "
                                "anyway", key=f"{key}_confirm")

    if st.button(f"Import {label}", type="primary",
                 disabled=bool(missing) or not confirmed, key=f"{key}_go"):
        normalize = (confirmations.normalize_book if side == "book"
                     else confirmations.normalize_ext)
        clean, issues = normalize(raw, mapping)
        if issues["rows_imported"] == 0:
            st.error("No importable rows - a row needs a party identifier "
                     "and a parseable balance. Check the mapping and header "
                     "row.")
            st.json(issues)
            return
        sha = file_sha256(content)
        confirmations.import_confirmation_sheet(
            eng["id"], area, side, clean, up.name, sha, mapping,
            user["username"])
        auditlog.log(user, f"IMPORT_CONF_{side.upper()}", entity=area,
                     details={"filename": up.name, "sha256": sha,
                              "issues": issues},
                     engagement_id=eng["id"])
        st.success(f"Imported {issues['rows_imported']:,} rows - "
                   f"{issues['distinct_parties']:,} parties, total "
                   f"{inr(issues['total_balance'])}. File SHA-256 recorded "
                   f"in the audit trail.")
        if issues["duplicate_party_rows"]:
            st.caption(f"{issues['duplicate_party_rows']:,} rows share a "
                       f"party with another row - they are summed to one "
                       f"balance per party when matching.")
    elif missing:
        st.info("Map the required fields marked * to enable import: "
                + ", ".join(missing))


def _matching_tab(user, eng, area):
    eid = eng["id"]
    key = f"conf_match_{_slug(area)}"
    book, ext = confirmations.active_frames(eid, area)
    if not len(book):
        st.info("Import the party-wise SAP book balances for this area "
                "first (previous tabs) - received confirmations are matched "
                "against them.")
        return
    if not len(ext):
        st.warning("No received confirmations imported yet - every party "
                   "below shows as 'No response'. Use this view to chase "
                   "outstanding confirmations, and import replies on the "
                   "second tab as they arrive.")

    settings = confirmations.load_settings(eid, area)
    c1, c2 = st.columns([1, 2])
    tolerance = c1.number_input(
        "Matching tolerance (Rs)", min_value=0.0,
        value=float(settings.get("tolerance", 1.0)), step=1.0,
        key=f"{key}_tol",
        help="Differences at or below this are treated as agreed "
             "(rounding).")
    sign_labels = {"as_stated": "As stated on the confirmations",
                   "invert": "Invert (parties confirm the mirror image)"}
    current = settings.get("ext_sign", "as_stated")
    chosen = c2.radio(
        "Confirmed balance sign", list(sign_labels.values()),
        index=list(sign_labels).index(current) if current in sign_labels
        else 0,
        horizontal=True, key=f"{key}_sign",
        help="A party that confirms 'you owe us Rs X' states the mirror "
             "image of a payable carried as -X in the books - Invert flips "
             "the confirmed amounts so they compare like for like.")
    ext_sign = ("invert" if chosen == sign_labels["invert"] else "as_stated")

    recon = confirmations.match_confirmations(book, ext, tolerance, ext_sign)
    stats = confirmations.confirmation_stats(recon, tolerance)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Parties in books", stats["parties"])
    m2.metric("Responses", stats["responses"],
              help="Share of book parties with a confirmation received")
    m3.metric("Agreed", stats["agreed"])
    m4.metric("Exceptions", stats["exceptions"])
    m5.metric("No response", stats["no_response"])
    v1, v2, v3 = st.columns(3)
    v1.metric("Value coverage", f"{stats['coverage_pct']:.1f}%",
              help=f"{inr(stats['covered_value_abs'])} of "
                   f"{inr(stats['book_total_abs'])} (absolute book value) "
                   f"is covered by a received confirmation; response rate "
                   f"{stats['response_rate_pct']:.0f}% of parties")
    v2.metric("Exception value", inr(stats["exception_value"]))
    v3.metric("Unconfirmed value (no response)",
              inr(stats["no_response_value_abs"]))

    if stats["mirror_hint"] and ext_sign == "as_stated":
        st.warning("Most exceptions cancel against the book balance almost "
                   "exactly - the parties appear to confirm from their own "
                   "perspective (the mirror image). Switch 'Confirmed "
                   "balance sign' to Invert and re-check before treating "
                   "these as differences.")
    if stats["not_in_books"]:
        st.warning(f"{stats['not_in_books']} confirmation(s) name a party "
                   f"with no balance in the books (status 'Not in books') - "
                   f"a completeness signal: check for unrecorded balances "
                   f"or a party carried under a different code.")

    table = confirmations.attach_assessments(
        recon, confirmations.load_assessments(eid, area))
    st.caption("Record a conclusion per party: investigate each exception "
               "(SA 505.14 - timing, dispute or misstatement) and perform "
               "alternative procedures for non-responses (SA 505.12). "
               "Misstatements carry to Results & evaluation.")
    edited = st.data_editor(
        table, hide_index=True, key=f"{key}_edit",
        column_order=[c for c in table.columns if c != "party_key"],
        column_config={
            "party": st.column_config.TextColumn(disabled=True),
            "party_name": st.column_config.TextColumn(disabled=True,
                                                      width="medium"),
            "gl_account": st.column_config.TextColumn(disabled=True),
            "book_balance": st.column_config.NumberColumn(
                disabled=True, format="localized"),
            "confirmed_balance": st.column_config.NumberColumn(
                disabled=True, format="localized"),
            "difference": st.column_config.NumberColumn(
                disabled=True, format="localized"),
            "status": st.column_config.TextColumn(disabled=True),
            "matched_by": st.column_config.TextColumn(disabled=True,
                                                      width="small"),
            "confirm_date": st.column_config.TextColumn(disabled=True),
            "reference": st.column_config.TextColumn(disabled=True),
            "conclusion": st.column_config.SelectboxColumn(
                options=confirmations.CONCLUSIONS),
            "remarks": st.column_config.TextColumn(width="large"),
        })

    c_save, c_dl = st.columns(2)
    if c_save.button("Save conclusions & settings", type="primary",
                     key=f"{key}_save"):
        n = confirmations.save_assessments(
            eid, area, edited.to_dict("records"), user["username"])
        confirmations.save_settings(
            eid, area,
            {**settings, "tolerance": float(tolerance),
             "ext_sign": ext_sign},
            user["username"])
        auditlog.log(user, "CONF_ASSESS", entity=area,
                     details={"parties": n, "tolerance": float(tolerance),
                              "ext_sign": ext_sign,
                              "stats": {k: stats[k] for k in
                                        ("parties", "responses", "agreed",
                                         "exceptions", "no_response",
                                         "not_in_books")}},
                     engagement_id=eid)
        st.success(f"Saved conclusions for {n} parties.")
    c_dl.download_button(
        "Download working paper (CSV)",
        edited.drop(columns=["party_key"]).to_csv(index=False)
        .encode("utf-8-sig"),
        file_name=f"confirmations_{_slug(area)}_"
                  f"{datetime.now():%Y%m%d_%H%M%S}.csv",
        mime="text/csv", key=f"{key}_dl")


def render(user):
    st.header("8. Balance confirmations (SA 505)")
    eng = require_engagement()
    if not eng:
        return
    area = st.selectbox("Confirmation area", confirmations.AREAS,
                        key="conf_area")
    tab_book, tab_ext, tab_match = st.tabs(
        ["Book balances (SAP)", "Confirmations received",
         "Matching & conclusions"])
    with tab_book:
        _upload_tab(user, eng, area, "book")
    with tab_ext:
        _upload_tab(user, eng, area, "ext")
    with tab_match:
        _matching_tab(user, eng, area)
