"""Shared UI helpers: engagement/ledger guards, role gates, formatting,
and the upload / column-mapping widgets used by the import-style pages."""

from datetime import datetime

import streamlit as st

from core import importer
from core.formatting import inr, short_hash
from storage import auth, db


def current_engagement():
    eid = st.session_state.get("engagement_id")
    return db.get_engagement(eid) if eid else None


def require_engagement():
    eng = current_engagement()
    if not eng:
        st.warning("Create or select an engagement first (step 1).")
    return eng


def require_ledger(eng):
    imp = db.active_import(eng["id"], "ledger")
    if not imp:
        st.warning("Import a general ledger first (step 2).")
    return imp


def require_role(user, min_role: str, action_label: str) -> bool:
    if not auth.has_role(user, min_role):
        st.error(f"{action_label} requires the {min_role} role or above "
                 f"(you are signed in as {user.get('role')}).")
        return False
    return True


def money_metric(label: str, value) -> None:
    st.metric(label, inr(value))


def active_import_banner(eng, kind: str, label: str):
    """Green banner describing the active import of *kind* (or nothing);
    returns the import row so the caller knows whether one exists."""
    imp = db.active_import(eng["id"], kind)
    if imp:
        st.success(f"Active {label}: **{imp['filename']}** "
                   f"({imp['rows']:,} rows, SHA-256 "
                   f"{short_hash(imp['sha256'], 16)}..., imported "
                   f"{imp['imported_at']} by {imp['imported_by']})")
    return imp


def read_upload_widget(up, key_prefix: str):
    """Sheet/header-row pickers plus a preview for an uploaded tabular file;
    returns (raw bytes, DataFrame as read)."""
    content = up.getvalue()
    sheets = importer.sheet_names(content, up.name)
    sheet = st.selectbox("Sheet", sheets, key=f"{key_prefix}_sheet") \
        if sheets else None
    header_row = int(st.number_input("Header row (1-based)", 1, 50, 1,
                                     key=f"{key_prefix}_hdr")) - 1
    raw = importer.read_table(content, up.name, sheet, header_row)
    st.caption(f"{len(raw):,} rows read from **{up.name}**")
    st.dataframe(raw.head(8))
    return content, raw


def mapping_widget(raw, fields, guesses, key_prefix: str):
    """Column-mapping selectboxes for (field, label, required) triples;
    returns (mapping dict, labels of unmapped required fields)."""
    options = ["- not mapped -"] + [str(c) for c in raw.columns]
    base = importer.guess_mapping(raw.columns, guesses)
    mapping = {}
    grid = st.columns(3)
    for i, (field, label, required) in enumerate(fields):
        with grid[i % 3]:
            default = base.get(field)
            idx = options.index(default) if default in options else 0
            chosen = st.selectbox(label + (" *" if required else ""),
                                  options, index=idx,
                                  key=f"{key_prefix}_{field}")
            mapping[field] = None if chosen == "- not mapped -" else chosen
    missing = [label for f, label, req in fields if req and not mapping[f]]
    return mapping, missing


def money_cols_config(df, cols):
    """st.dataframe column_config that formats money columns with grouping."""
    return {c: st.column_config.NumberColumn(c, format="localized")
            for c in cols if c in df.columns}


def sampling_methodology_pdf(eid: int, user: dict) -> None:
    """Shared 'Sampling methodology (SA 530)' generate/download block, used on
    the analysis-run page (step 5) and the sampling page (step 6). Documents
    how the analysis run splits populations and how each sample is sized and
    selected. Requires the analysis to have been run (populations exist)."""
    from reports import sampling_logic          # lazy: keeps common.py light

    st.subheader("Sampling methodology (SA 530)")
    st.caption("Downloadable note: how the analysis run splits each population "
               "into 100% and sampled items, the sample-size formulas and "
               "reference factors, the seeded selection algorithms, and the "
               "sampling plans on record for this engagement.")
    if st.button("Generate methodology PDF", key="samplogic_gen"):
        content = sampling_logic.generate_sampling_logic(eid, user)
        name = f"sampling_methodology_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        folder = db.data_dir() / "exports" / f"engagement_{eid}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        st.session_state["samplogic_bytes"] = content
        st.session_state["samplogic_name"] = name
        st.success(f"Generated ({len(content) / 1024:.0f} KB); archived under "
                   f"exports/engagement_{eid}/.")
    if st.session_state.get("samplogic_bytes"):
        st.download_button(
            "Download " + st.session_state["samplogic_name"],
            st.session_state["samplogic_bytes"],
            file_name=st.session_state["samplogic_name"],
            mime="application/pdf", key="samplogic_dl")
