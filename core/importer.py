"""Ledger / trial balance import: flexible column mapping with an SAP preset,
robust amount parsing (SAP trailing-sign negatives, Indian and European
number formats, bracketed negatives), validation, and ledger-vs-trial-balance
reconciliation.

Internal sign convention: debit positive / credit negative (as in SAP local
currency exports). ``sign_convention='cr_pos'`` inverts a file that carries
credits as positive.
"""

import hashlib
import io
import json
import math
import re

import numpy as np
import pandas as pd

from storage import db

# (canonical field, label, required)
LEDGER_FIELDS = [
    ("date", "Posting date", True),
    ("doc_no", "Document number", True),
    ("account", "G/L account", True),
    ("amount", "Amount (signed)", True),
    ("narration", "Text / narration", False),
    ("account_name", "G/L account name", False),
    ("doc_type", "Document type", False),
    ("sap_user", "User name", False),
    ("entry_date", "Entry date", False),
]

TB_FIELDS = [
    ("account", "Account code", True),
    ("account_name", "Account name", False),
    ("opening", "Opening balance", False),
    ("debit", "Debit total", False),
    ("credit", "Credit total", False),
    ("closing", "Closing balance", False),
]

# Column-name candidates for the SAP preset (FAGLL03 / FBL3N style exports).
SAP_GUESSES = {
    "date": ["posting date", "pstng date", "postg date", "posting dt", "date"],
    "doc_no": ["document number", "documentno", "document no", "doc. no.",
               "doc no", "voucher no", "voucher number"],
    "account": ["g/l account", "gl account", "g/l acct", "account code",
                "account"],
    "amount": ["amount in local currency", "amount in lc", "amt in loc.cur.",
               "local currency amount", "amount (inr)", "amount"],
    "narration": ["text", "item text", "narration", "description",
                  "particulars"],
    "account_name": ["g/l account name", "account name", "gl name"],
    "doc_type": ["document type", "doc. type", "doc type", "type"],
    "sap_user": ["user name", "username", "user"],
    "entry_date": ["entry date", "entered on", "created on"],
}

TB_GUESSES = {
    "account": ["account code", "g/l account", "gl account", "gl code",
                "account"],
    "account_name": ["account name", "g/l account name", "gl name",
                     "description"],
    "opening": ["opening balance", "opening", "op bal"],
    "debit": ["debit total", "total debit", "debit", "dr"],
    "credit": ["credit total", "total credit", "credit", "cr"],
    "closing": ["closing balance", "closing", "cl bal", "balance"],
}


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sheet_names(content: bytes, filename: str) -> list:
    if filename.lower().endswith(".csv"):
        return []
    xl = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    return list(xl.sheet_names)


def read_table(content: bytes, filename: str, sheet=None,
               header_row: int = 0) -> pd.DataFrame:
    if filename.lower().endswith(".csv"):
        df = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                df = pd.read_csv(io.BytesIO(content), header=header_row,
                                 dtype=object, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            raise ValueError("could not decode the CSV file")
    else:
        df = pd.read_excel(io.BytesIO(content),
                           sheet_name=sheet if sheet else 0,
                           header=header_row, dtype=object,
                           engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def guess_mapping(columns, guesses=SAP_GUESSES) -> dict:
    normalized = {str(c).strip().lower(): c for c in columns}
    mapping = {}
    for field, candidates in guesses.items():
        found = None
        for cand in candidates:              # exact match first
            if cand in normalized:
                found = normalized[cand]
                break
        if not found:                        # then substring match
            for cand in candidates:
                for norm, orig in normalized.items():
                    if cand in norm and orig not in mapping.values():
                        found = orig
                        break
                if found:
                    break
        mapping[field] = found
    return mapping


_CURRENCY_RE = re.compile(r"(?i)(rs\.?|inr|₹)")
_EURO_GROUPED = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")
_DECIMAL_COMMA = re.compile(r"^\d+,\d{1,2}$")


def parse_amount(value):
    """Parse '1.234,56-' (SAP), '1,23,456.78' (Indian), '(5,000)', '12345.67-'
    and plain numbers. Returns float or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "none", "null", "-"}:
        return None
    neg = False
    if s.endswith("-"):
        neg, s = True, s[:-1].strip()
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s.startswith("-"):
        neg, s = True, s[1:].strip()
    s = _CURRENCY_RE.sub("", s).replace(" ", "").replace(" ", "")
    if _EURO_GROUPED.match(s):
        s = s.replace(".", "").replace(",", ".")
    elif _DECIMAL_COMMA.match(s):
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _to_str(series: pd.Series) -> pd.Series:
    def conv(v):
        if v is None:
            return ""
        if isinstance(v, float):
            if math.isnan(v):
                return ""
            if v.is_integer():
                return str(int(v))
        s = str(v).strip()
        if s.lower() in ("nan", "none", "nat"):
            return ""
        if s.endswith(".0"):
            s = s[:-2]
        return s
    return series.map(conv)


def normalize_ledger(raw: pd.DataFrame, mapping: dict,
                     sign_convention: str = "dr_pos"):
    """Return (clean canonical DataFrame, issues dict)."""
    n = len(raw)

    def col(field):
        name = mapping.get(field)
        if name and name in raw.columns:
            return raw[name]
        return pd.Series([None] * n, index=raw.index)

    amount = col("amount").map(parse_amount)
    doc_no = _to_str(col("doc_no"))
    account = _to_str(col("account"))
    footer = amount.isna() & doc_no.eq("") & account.eq("")
    dates = pd.to_datetime(col("date"), errors="coerce", dayfirst=True)
    good = amount.notna() & dates.notna() & ~footer

    issues = {
        "rows_in_file": int(n),
        "footer_rows_skipped": int(footer.sum()),
        "bad_amount_rows": [int(i) + 2 for i in
                            raw.index[amount.isna() & ~footer][:20]],
        "bad_date_rows": [int(i) + 2 for i in
                          raw.index[dates.isna() & amount.notna()
                                    & ~footer][:20]],
        "rows_excluded": int((~good & ~footer).sum()),
        "rows_imported": int(good.sum()),
    }

    signed = amount.astype(float)
    if sign_convention == "cr_pos":
        signed = -signed
    entry = pd.to_datetime(col("entry_date"), errors="coerce", dayfirst=True)

    full = pd.DataFrame({
        "date": dates.dt.strftime("%Y-%m-%d"),
        "doc_no": doc_no,
        "doc_type": _to_str(col("doc_type")),
        "account": account,
        "account_name": _to_str(col("account_name")),
        "narration": _to_str(col("narration")),
        "amount_signed": signed,
        "entry_date": entry.dt.strftime("%Y-%m-%d"),
        "sap_user": _to_str(col("sap_user")),
    })
    clean = full[good].reset_index(drop=True)
    clean["entry_date"] = clean["entry_date"].fillna("")
    clean["amount_abs"] = clean["amount_signed"].abs()
    clean["side"] = np.where(clean["amount_signed"] >= 0, "D", "C")
    clean.insert(0, "row_id", range(len(clean)))
    return clean, issues


def validate_ledger(clean: pd.DataFrame, fy_start: str, fy_end: str) -> dict:
    dates = pd.to_datetime(clean["date"], errors="coerce")
    in_fy = dates.between(pd.Timestamp(fy_start), pd.Timestamp(fy_end))
    named = clean["doc_no"].ne("")
    dup_docs = clean.loc[named].duplicated(subset=["doc_no"], keep=False)
    return {
        "rows": int(len(clean)),
        "out_of_fy": int((~in_fy).sum()),
        "zero_amounts": int(clean["amount_abs"].eq(0).sum()),
        "duplicate_doc_numbers": int(dup_docs.sum()),
        "sum_signed": float(clean["amount_signed"].sum()),
        "sum_abs": float(clean["amount_abs"].sum()),
        "date_min": str(dates.min().date()) if len(clean) else "",
        "date_max": str(dates.max().date()) if len(clean) else "",
    }


TXN_COLS = ["row_id", "date", "doc_no", "doc_type", "account", "account_name",
            "narration", "amount_signed", "amount_abs", "side", "sap_user",
            "entry_date"]


def import_ledger(engagement_id: int, clean: pd.DataFrame, filename: str,
                  sha256: str, mapping: dict, actor: str) -> int:
    """Persist a normalized ledger as the active import (previous active
    ledger imports are marked replaced; their rows are retained for the
    audit trail)."""
    with db.connect() as con:
        con.execute(
            "UPDATE imports SET status='replaced' WHERE engagement_id=? AND "
            "kind='ledger' AND status='active'", (engagement_id,))
        cur = con.execute(
            "INSERT INTO imports (engagement_id, kind, filename, sha256, "
            "rows, mapping_json, status, imported_by, imported_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (engagement_id, "ledger", filename, sha256, int(len(clean)),
             json.dumps(mapping), "active", actor, db.now()))
        import_id = cur.lastrowid
        out = clean[TXN_COLS].copy()
        out.insert(0, "import_id", import_id)
        out.insert(0, "engagement_id", engagement_id)
        out["category"] = "Uncategorized"
        out["flags"] = ""
        out["full_reason"] = ""
        out.to_sql("transactions", con, if_exists="append", index=False)
    return import_id


def normalize_tb(raw: pd.DataFrame, mapping: dict):
    n = len(raw)

    def col(field):
        name = mapping.get(field)
        if name and name in raw.columns:
            return raw[name]
        return pd.Series([None] * n, index=raw.index)

    account = _to_str(col("account"))
    out = pd.DataFrame({
        "account": account,
        "account_name": _to_str(col("account_name")),
        "opening": col("opening").map(parse_amount),
        "debit": col("debit").map(parse_amount),
        "credit": col("credit").map(parse_amount),
        "closing": col("closing").map(parse_amount),
    })
    keep = out["account"].ne("")
    issues = {"rows_in_file": int(n), "rows_skipped": int((~keep).sum()),
              "rows_imported": int(keep.sum())}
    clean = out[keep].reset_index(drop=True)
    for c in ("opening", "debit", "credit", "closing"):
        clean[c] = clean[c].fillna(0.0).astype(float)
    # Sanity signals for a mis-mapped file (recorded in the audit trail and
    # surfaced in the UI): account codes that are actually amounts, or debit
    # and credit sourced from one column (so every movement collapses to 0).
    acct = clean["account"]
    issues["distinct_accounts"] = int(acct.nunique())
    issues["account_amountish_share"] = (
        float((acct.str.contains(r"[.\s]") | acct.str.startswith("-")).mean())
        if len(acct) else 0.0)
    issues["debit_equals_credit_all"] = bool(
        len(clean) and clean["debit"].equals(clean["credit"]))
    issues["amounts_all_zero"] = bool(
        len(clean) and not clean[["opening", "debit", "credit",
                                  "closing"]].abs().to_numpy().any())
    return clean, issues


def mapping_collisions(mapping: dict) -> dict:
    """Source columns that more than one canonical field is mapped to,
    as ``{column: [fields, ...]}`` - a strong sign of a wrong mapping."""
    by_col: dict = {}
    for field, col in mapping.items():
        if col:
            by_col.setdefault(col, []).append(field)
    return {col: fields for col, fields in by_col.items() if len(fields) > 1}


def tb_mapping_warnings(raw: pd.DataFrame, mapping: dict) -> list:
    """Human-readable warnings about a trial-balance mapping that would break
    the ledger-vs-TB reconciliation (returned before the import is committed)."""
    warns = []
    collisions = mapping_collisions(mapping)
    if collisions:
        pretty = "; ".join(f"'{col}' -> {', '.join(fields)}"
                           for col, fields in collisions.items())
        warns.append(
            "Several trial-balance fields are mapped to the same source "
            "column (" + pretty + "). Account codes and amounts must come "
            "from different columns - fix the header row or the mapping, "
            "otherwise the reconciliation cannot tie.")
    # Reconciliation needs a per-account movement: either Debit and/or Credit,
    # or a Closing balance (movement = closing - opening). Without one of those
    # every TB movement is zero and no account can ever reconcile.
    amount_fields = ("opening", "debit", "credit", "closing")
    has_drcr = bool(mapping.get("debit") or mapping.get("credit"))
    has_closing = bool(mapping.get("closing"))
    if not any(mapping.get(f) for f in amount_fields):
        warns.append(
            "No balance or movement column is mapped (Opening / Debit / "
            "Credit / Closing are all unmapped). Map the trial balance's "
            "Debit and Credit columns, or its Closing balance - otherwise "
            "every account's movement is zero and nothing will reconcile.")
    elif not has_drcr and not has_closing:
        warns.append(
            "The mapped amount columns cannot produce an account movement. "
            "Map Debit and/or Credit, or a Closing balance column.")
    acct_col = mapping.get("account")
    if acct_col and acct_col in raw.columns:
        acct = _to_str(raw[acct_col])
        acct = acct[acct.ne("")]
        if len(acct) and (acct.str.contains(r"[.\s]")
                          | acct.str.startswith("-")).mean() > 0.5:
            warns.append(
                "The column mapped to 'Account code' looks like amounts rather "
                "than G/L account numbers (most values contain decimals, "
                "spaces or a leading minus). Map 'Account code' to the column "
                "that holds the account numbers.")
    return warns


def import_tb(engagement_id: int, clean: pd.DataFrame, filename: str,
              sha256: str, mapping: dict, actor: str) -> int:
    with db.connect() as con:
        con.execute(
            "UPDATE imports SET status='replaced' WHERE engagement_id=? AND "
            "kind='tb' AND status='active'", (engagement_id,))
        cur = con.execute(
            "INSERT INTO imports (engagement_id, kind, filename, sha256, "
            "rows, mapping_json, status, imported_by, imported_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (engagement_id, "tb", filename, sha256, int(len(clean)),
             json.dumps(mapping), "active", actor, db.now()))
        import_id = cur.lastrowid
        out = clean[["account", "account_name", "opening", "debit", "credit",
                     "closing"]].copy()
        out.insert(0, "import_id", import_id)
        out.insert(0, "engagement_id", engagement_id)
        out.to_sql("trial_balance", con, if_exists="append", index=False)
    return import_id


def tb_reconcile(txn_df: pd.DataFrame, tb_df: pd.DataFrame,
                 tol: float = 1.0) -> pd.DataFrame:
    """Completeness check: per-account ledger net movement vs TB movement
    (debit - credit, falling back to closing - opening)."""
    led = txn_df.groupby("account")["amount_signed"].sum().rename("ledger_net")
    t = tb_df.copy()
    has_drcr = (t["debit"].abs().sum() + t["credit"].abs().sum()) > 0
    if has_drcr:
        t["tb_movement"] = t["debit"] - t["credit"]
    else:
        t["tb_movement"] = t["closing"] - t["opening"]
    tbm = t.groupby("account").agg(
        account_name=("account_name", "first"),
        tb_movement=("tb_movement", "sum"))
    j = tbm.join(led, how="outer")
    # Presence per side (before filling gaps with 0) - so the UI can tell a
    # genuine mismatch from an account that only exists on one side.
    j["in_tb"] = j["tb_movement"].notna()
    j["in_ledger"] = j["ledger_net"].notna()
    j["account_name"] = j["account_name"].fillna("")
    for c in ("tb_movement", "ledger_net"):
        j[c] = j[c].fillna(0.0)
    j["difference"] = j["ledger_net"] - j["tb_movement"]
    j["ok"] = j["difference"].abs() <= tol
    j = j.reset_index()
    return j.reindex(j["difference"].abs().sort_values(ascending=False).index)


def reconcile_stats(recon: pd.DataFrame) -> dict:
    """Coverage of a ``tb_reconcile`` result: how many accounts appear on both
    sides and whether the matched ones tie. ``matched_accounts == 0`` means the
    ledger and TB share no account codes - almost always a mapping problem."""
    keys = ("ledger_accounts", "tb_accounts", "matched_accounts", "matched_ok",
            "matched_mismatch", "ledger_only", "tb_only")
    if not len(recon):
        return dict.fromkeys(keys, 0)
    in_l, in_t, ok = recon["in_ledger"], recon["in_tb"], recon["ok"]
    matched = in_l & in_t
    return {
        "ledger_accounts": int(in_l.sum()),
        "tb_accounts": int(in_t.sum()),
        "matched_accounts": int(matched.sum()),
        "matched_ok": int((matched & ok).sum()),
        "matched_mismatch": int((matched & ~ok).sum()),
        "ledger_only": int((in_l & ~in_t).sum()),
        "tb_only": int((in_t & ~in_l).sum()),
    }


def save_mapping_template(name: str, kind: str, mapping: dict,
                          actor: str) -> None:
    db.execute(
        "INSERT INTO mapping_templates (name, kind, mapping_json, created_by, "
        "created_at) VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
        "mapping_json=excluded.mapping_json, kind=excluded.kind",
        (name, kind, json.dumps(mapping), actor, db.now()))


def list_mapping_templates(kind: str) -> list:
    rows = db.query("SELECT name, mapping_json FROM mapping_templates WHERE "
                    "kind=? ORDER BY name", (kind,))
    return [{"name": r["name"], "mapping": json.loads(r["mapping_json"])}
            for r in rows]
