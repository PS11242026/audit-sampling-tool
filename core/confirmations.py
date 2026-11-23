"""SA 505 external (balance) confirmations.

Party-wise book balances from the SAP sheet (FBL5N/FBL1N-style customer or
vendor balance export) are matched against the balances confirmed in writing
by the external parties. Every book party is classified - Agreed, Exception
(SA 505(14): investigate; may be timing, dispute or misstatement), No
response (SA 505(12): perform alternative procedures) - and confirmations
that name a party absent from the books are flagged as a completeness
signal. Coverage and response statistics feed the working papers.

Sign convention: balances as they appear in the SAP local-currency export
(receivables debit-positive, payables credit-negative). Confirmed balances
are stored exactly as stated on the confirmations; if the party confirms
from its own perspective (the mirror image), set the area's sign setting to
'invert' and the reconciliation flips the confirmed amounts on the fly.
"""

import json
import re

import numpy as np
import pandas as pd

from core.importer import _to_str, mapping_collisions, parse_amount
from storage import db

AREAS = ["Trade receivables", "Trade payables", "Bank balances",
         "Loans & advances", "Other"]

# (canonical field, label, required) - mirrors importer.LEDGER_FIELDS/TB_FIELDS
BOOK_FIELDS = [
    ("party", "Party code (customer/vendor)", True),
    ("party_name", "Party name", False),
    ("balance", "Book balance (Rs)", True),
    ("gl_account", "Recon G/L account", False),
]

EXT_FIELDS = [
    ("party", "Party code (if quoted)", False),
    ("party_name", "Party name", True),
    ("balance", "Confirmed balance (Rs)", True),
    ("confirm_date", "Confirmation / statement date", False),
    ("reference", "Reference (letter / email)", False),
]

# party_name is guessed before party so that a bare "Customer Name" column is
# claimed by the name field, not substring-matched as the party code.
BOOK_GUESSES = {
    "party_name": ["customer name", "vendor name", "party name",
                   "name of party", "name 1", "name"],
    "party": ["customer code", "vendor code", "customer no", "vendor no",
              "party code", "bp code", "business partner", "customer",
              "vendor", "account", "party"],
    "balance": ["closing balance", "balance in local currency",
                "cumulative balance", "amount in local currency", "closing",
                "balance", "amount"],
    "gl_account": ["recon. acct", "recon account", "reconciliation account",
                   "g/l account", "gl account"],
}

EXT_GUESSES = {
    "party_name": ["party name", "name of party", "customer name",
                   "vendor name", "bank name", "name"],
    "party": ["party code", "customer code", "vendor code", "account no",
              "code"],
    "balance": ["confirmed balance", "balance confirmed",
                "balance as per confirmation", "amount confirmed",
                "closing balance", "balance", "amount"],
    "confirm_date": ["confirmation date", "statement date", "as on date",
                     "date"],
    "reference": ["reference", "letter no", "ref"],
}

ST_AGREED = "Agreed"
ST_EXCEPTION = "Exception"
ST_NO_RESPONSE = "No response"
ST_NOT_IN_BOOKS = "Not in books"
_STATUS_ORDER = [ST_EXCEPTION, ST_NO_RESPONSE, ST_NOT_IN_BOOKS, ST_AGREED]

CONCLUSIONS = [
    "Pending",
    "Agreed - no exception",
    "Difference reconciled (timing / in transit)",
    "Alternative procedures performed (SA 505.12)",
    "Misstatement - carry to evaluation",
    "Unresolved",
]

DEFAULT_SETTINGS = {
    "tolerance": 1.0,         # Rs; differences at or below this tie
    "ext_sign": "as_stated",  # or 'invert' (party confirms the mirror)
    "notes": "",
}

RECON_COLS = ["party", "party_name", "gl_account", "book_balance",
              "confirmed_balance", "difference", "status", "matched_by",
              "confirm_date", "reference", "party_key"]


# ------------------------------------------------------------- normalization

def code_key(value) -> str:
    """Canonical party-code key: SAP pads codes with leading zeros, so
    '0000200012' and '200012' must collide."""
    s = str(value or "").strip().upper()
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return s


def name_key(value) -> str:
    """Canonical party-name key: casefold, 'M/s' prefix and '&'/'and'
    equivalence, punctuation and spacing ignored."""
    s = str(value or "").strip().casefold()
    s = re.sub(r"^m/s\.?\s*", "", s)
    s = s.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", s)


def _party_keys(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["_code_k"] = d["party"].map(code_key)
    d["_name_k"] = d["party_name"].map(name_key)
    d["party_key"] = np.where(d["_code_k"] != "", "c:" + d["_code_k"],
                              np.where(d["_name_k"] != "",
                                       "n:" + d["_name_k"], ""))
    return d[d["party_key"] != ""]


def _normalize(raw: pd.DataFrame, mapping: dict, fields) -> tuple:
    n = len(raw)

    def col(field):
        name = mapping.get(field)
        if name and name in raw.columns:
            return raw[name]
        return pd.Series([None] * n, index=raw.index)

    out = pd.DataFrame({
        "party": _to_str(col("party")),
        "party_name": _to_str(col("party_name")),
        "gl_account": _to_str(col("gl_account")),
        "balance": col("balance").map(parse_amount),
    })
    if any(f == "confirm_date" for f, _, _ in fields):
        parsed = pd.to_datetime(col("confirm_date"), errors="coerce",
                                dayfirst=True)
        out["confirm_date"] = np.where(parsed.notna(),
                                       parsed.dt.strftime("%Y-%m-%d"),
                                       _to_str(col("confirm_date")))
        out["reference"] = _to_str(col("reference"))
    else:
        out["confirm_date"] = ""
        out["reference"] = ""

    keep = (out["party"].ne("") | out["party_name"].ne("")) \
        & out["balance"].notna()
    clean = out[keep].reset_index(drop=True)
    clean["balance"] = clean["balance"].astype(float)
    keyed = _party_keys(clean)
    issues = {
        "rows_in_file": int(n),
        "rows_skipped": int((~keep).sum()),
        "rows_imported": int(keep.sum()),
        "distinct_parties": int(keyed["party_key"].nunique()),
        "duplicate_party_rows": int(len(keyed)
                                    - keyed["party_key"].nunique()),
        "total_balance": float(clean["balance"].sum()),
    }
    return clean, issues


def normalize_book(raw: pd.DataFrame, mapping: dict):
    """(clean canonical book-balance frame, issues dict)."""
    return _normalize(raw, mapping, BOOK_FIELDS)


def normalize_ext(raw: pd.DataFrame, mapping: dict):
    """(clean canonical received-confirmations frame, issues dict)."""
    return _normalize(raw, mapping, EXT_FIELDS)


def mapping_warnings(raw: pd.DataFrame, mapping: dict) -> list:
    """Warnings for a mapping that would break the matching (mirrors
    importer.tb_mapping_warnings)."""
    warns = []
    collisions = mapping_collisions(mapping)
    if collisions:
        pretty = "; ".join(f"'{col}' -> {', '.join(fields)}"
                           for col, fields in collisions.items())
        warns.append(
            "Several fields are mapped to the same source column (" + pretty
            + "). Party identifiers and balances must come from different "
            "columns - fix the header row or the mapping, otherwise the "
            "matching cannot work.")
    party_col = mapping.get("party")
    if party_col and party_col in raw.columns:
        p = _to_str(raw[party_col])
        p = p[p.ne("")]
        if len(p) and (p.str.contains(r"[.\s]")
                       | p.str.startswith("-")).mean() > 0.5:
            warns.append(
                "The column mapped to 'Party code' looks like amounts rather "
                "than customer/vendor codes (most values contain decimals, "
                "spaces or a leading minus). Map it to the column that holds "
                "the party codes.")
    return warns


# ------------------------------------------------------------------ matching

def _aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """One row per party_key: balances summed (an open-item dump collapses
    to the party balance), identifiers kept from the first row."""
    keyed = _party_keys(df)
    if keyed.empty:
        return pd.DataFrame(columns=["party_key", "party", "party_name",
                                     "gl_account", "balance", "confirm_date",
                                     "reference", "_name_k"])
    g = keyed.groupby("party_key", sort=False).agg(
        party=("party", "first"),
        party_name=("party_name", "first"),
        gl_account=("gl_account", "first"),
        balance=("balance", "sum"),
        confirm_date=("confirm_date", "first"),
        reference=("reference", "first"),
        _name_k=("_name_k", "first"),
    ).reset_index()
    return g


def match_confirmations(book: pd.DataFrame, ext: pd.DataFrame,
                        tolerance: float = 1.0,
                        ext_sign: str = "as_stated") -> pd.DataFrame:
    """Match book parties to received confirmations and classify each row.

    Pass 1 matches on the party key (code, with SAP leading zeros stripped;
    or the normalized name when there is no code). Pass 2 matches the
    leftovers on the normalized name, only where the name is unambiguous on
    both sides. Confirmed amounts are flipped when ``ext_sign='invert'``.
    """
    b = _aggregate(book) if len(book) else _aggregate(
        pd.DataFrame(columns=["party", "party_name", "gl_account", "balance",
                              "confirm_date", "reference"]))
    e = _aggregate(ext) if len(ext) else _aggregate(
        pd.DataFrame(columns=["party", "party_name", "gl_account", "balance",
                              "confirm_date", "reference"]))
    if ext_sign == "invert":
        e = e.assign(balance=-e["balance"])

    pairs = {}                                 # book party_key -> ext row idx
    ekeys = {k: i for i, k in enumerate(e["party_key"])}
    for i, k in enumerate(b["party_key"]):
        if k in ekeys:
            pairs[k] = (ekeys[k], "code" if k.startswith("c:") else "name")

    # pass 2: unmatched-by-key rows, unambiguous normalized-name equality
    used_e = {i for i, _ in pairs.values()}
    b_left = b[~b["party_key"].isin(pairs)]
    e_left = e[~e.index.isin(used_e)]
    b_names = b_left[b_left["_name_k"] != ""].groupby("_name_k")
    e_names = e_left[e_left["_name_k"] != ""].groupby("_name_k")
    b_uni = {k: g.index[0] for k, g in b_names if len(g) == 1}
    e_uni = {k: g.index[0] for k, g in e_names if len(g) == 1}
    for nk, bi in b_uni.items():
        if nk in e_uni:
            pairs[b.loc[bi, "party_key"]] = (e_uni[nk], "name")

    rows = []
    used_e = {i for i, _ in pairs.values()}
    for bi in b.index:
        key = b.loc[bi, "party_key"]
        r = {"party": b.loc[bi, "party"],
             "party_name": b.loc[bi, "party_name"],
             "gl_account": b.loc[bi, "gl_account"],
             "book_balance": float(b.loc[bi, "balance"]),
             "confirmed_balance": np.nan, "difference": np.nan,
             "status": ST_NO_RESPONSE, "matched_by": "",
             "confirm_date": "", "reference": "", "party_key": key}
        if key in pairs:
            ei, how = pairs[key]
            conf = float(e.loc[ei, "balance"])
            diff = r["book_balance"] - conf
            r.update({
                "confirmed_balance": conf, "difference": diff,
                "matched_by": how,
                "confirm_date": e.loc[ei, "confirm_date"],
                "reference": e.loc[ei, "reference"],
                "status": ST_AGREED if abs(diff) <= float(tolerance)
                else ST_EXCEPTION,
            })
        rows.append(r)
    for ei in e.index:
        if ei in used_e:
            continue
        rows.append({
            "party": e.loc[ei, "party"], "party_name": e.loc[ei, "party_name"],
            "gl_account": "", "book_balance": np.nan,
            "confirmed_balance": float(e.loc[ei, "balance"]),
            "difference": np.nan, "status": ST_NOT_IN_BOOKS, "matched_by": "",
            "confirm_date": e.loc[ei, "confirm_date"],
            "reference": e.loc[ei, "reference"],
            "party_key": e.loc[ei, "party_key"]})

    recon = pd.DataFrame(rows, columns=RECON_COLS)
    if recon.empty:
        return recon
    rank = recon["status"].map({s: i for i, s in enumerate(_STATUS_ORDER)})
    size = recon["difference"].abs() \
        .fillna(recon["book_balance"].abs()) \
        .fillna(recon["confirmed_balance"].abs()).fillna(0.0)
    order = (rank * 1.0 - size / (size.max() + 1.0)) if len(size) else rank
    return recon.iloc[np.argsort(order.to_numpy(), kind="stable")] \
        .reset_index(drop=True)


def confirmation_stats(recon: pd.DataFrame, tolerance: float = 1.0) -> dict:
    """Coverage, response and exception statistics for a matching result."""
    keys = ("parties", "responses", "agreed", "exceptions", "no_response",
            "not_in_books", "book_total_abs", "covered_value_abs",
            "coverage_pct", "response_rate_pct", "exception_value",
            "no_response_value_abs", "mirror_hint")
    if not len(recon):
        out = dict.fromkeys(keys, 0)
        out["mirror_hint"] = False
        return out
    in_books = recon["status"] != ST_NOT_IN_BOOKS
    matched = recon["confirmed_balance"].notna() & in_books
    exceptions = recon["status"] == ST_EXCEPTION
    no_resp = recon["status"] == ST_NO_RESPONSE
    book_abs = recon["book_balance"].abs()
    total = float(book_abs[in_books].sum())
    covered = float(book_abs[matched].sum())
    # A run of exceptions where book + confirmed nets to ~0 usually means the
    # party confirmed from its own perspective - suggest the 'invert' setting.
    mirror = matched & exceptions & (
        (recon["book_balance"] + recon["confirmed_balance"]).abs()
        <= float(tolerance))
    n_exc = int(exceptions.sum())
    return {
        "parties": int(in_books.sum()),
        "responses": int(matched.sum()),
        "agreed": int((recon["status"] == ST_AGREED).sum()),
        "exceptions": n_exc,
        "no_response": int(no_resp.sum()),
        "not_in_books": int((~in_books).sum()),
        "book_total_abs": total,
        "covered_value_abs": covered,
        "coverage_pct": covered / total * 100.0 if total else 0.0,
        "response_rate_pct": (float(matched.sum()) / float(in_books.sum())
                              * 100.0 if in_books.sum() else 0.0),
        "exception_value": float(recon.loc[exceptions, "difference"]
                                 .abs().sum()),
        "no_response_value_abs": float(book_abs[no_resp].sum()),
        "mirror_hint": bool(int(mirror.sum()) >= 2
                            and mirror.sum() > n_exc / 2),
    }


# --------------------------------------------------------------- persistence

def import_kind(side: str, area: str) -> str:
    """The imports.kind value for one side of one area, e.g.
    'conf_book|Trade receivables'."""
    return f"conf_{side}|{area}"


CONF_COLS = ["party", "party_name", "gl_account", "balance", "confirm_date",
             "reference"]


def import_confirmation_sheet(engagement_id: int, area: str, side: str,
                              clean: pd.DataFrame, filename: str, sha256: str,
                              mapping: dict, actor: str) -> int:
    """Persist a normalized book/ext sheet as the active import for the area
    (previous active import of the same kind is marked replaced; its rows are
    retained for the audit trail)."""
    if side not in ("book", "ext"):
        raise ValueError("side must be 'book' or 'ext'")
    kind = import_kind(side, area)
    with db.connect() as con:
        con.execute(
            "UPDATE imports SET status='replaced' WHERE engagement_id=? AND "
            "kind=? AND status='active'", (engagement_id, kind))
        cur = con.execute(
            "INSERT INTO imports (engagement_id, kind, filename, sha256, "
            "rows, mapping_json, status, imported_by, imported_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (engagement_id, kind, filename, sha256, int(len(clean)),
             json.dumps(mapping), "active", actor, db.now()))
        import_id = cur.lastrowid
        out = clean[CONF_COLS].copy()
        out.insert(0, "side", side)
        out.insert(0, "area", area)
        out.insert(0, "import_id", import_id)
        out.insert(0, "engagement_id", engagement_id)
        out.to_sql("conf_balances", con, if_exists="append", index=False)
    return import_id


def active_frames(engagement_id: int, area: str):
    """(book frame, ext frame) for the area's active imports; empty frames
    when nothing is imported yet."""
    frames = []
    for side in ("book", "ext"):
        imp = db.active_import(engagement_id, import_kind(side, area))
        if imp:
            frames.append(db.read_df(
                "SELECT party, party_name, gl_account, balance, confirm_date,"
                " reference FROM conf_balances WHERE import_id=?",
                (imp["id"],)))
        else:
            frames.append(pd.DataFrame(columns=CONF_COLS))
    return frames[0], frames[1]


def load_settings(engagement_id: int, area: str) -> dict:
    row = db.query_one(
        "SELECT data_json FROM conf_settings WHERE engagement_id=? AND "
        "area=?", (engagement_id, area))
    data = dict(DEFAULT_SETTINGS)
    if row:
        data.update(json.loads(row["data_json"]))
    return data


def save_settings(engagement_id: int, area: str, data: dict,
                  actor: str) -> None:
    db.execute(
        "INSERT INTO conf_settings (engagement_id, area, data_json, "
        "updated_by, updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(engagement_id, area) DO UPDATE SET "
        "data_json=excluded.data_json, updated_by=excluded.updated_by, "
        "updated_at=excluded.updated_at",
        (engagement_id, area, json.dumps(data), actor, db.now()))


def load_assessments(engagement_id: int, area: str) -> dict:
    """{party_key: {'conclusion': ..., 'remarks': ...}}"""
    rows = db.query(
        "SELECT party_key, conclusion, remarks FROM conf_assessments "
        "WHERE engagement_id=? AND area=?", (engagement_id, area))
    return {r["party_key"]: {"conclusion": r["conclusion"],
                             "remarks": r["remarks"]} for r in rows}


def save_assessments(engagement_id: int, area: str, records,
                     actor: str) -> int:
    """Upsert per-party auditor conclusions; records is an iterable of dicts
    with party_key / conclusion / remarks. Returns rows written."""
    ts = db.now()
    payload = [(engagement_id, area, r["party_key"],
                r.get("conclusion") or CONCLUSIONS[0],
                r.get("remarks") or "", actor, ts)
               for r in records if r.get("party_key")]
    db.executemany(
        "INSERT INTO conf_assessments (engagement_id, area, party_key, "
        "conclusion, remarks, updated_by, updated_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(engagement_id, area, party_key) DO UPDATE SET "
        "conclusion=excluded.conclusion, remarks=excluded.remarks, "
        "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        payload)
    return len(payload)


def attach_assessments(recon: pd.DataFrame, assessments: dict) -> pd.DataFrame:
    """Merge saved conclusions/remarks onto a matching result."""
    out = recon.copy()
    out["conclusion"] = out["party_key"].map(
        lambda k: assessments.get(k, {}).get("conclusion", CONCLUSIONS[0]))
    out["remarks"] = out["party_key"].map(
        lambda k: assessments.get(k, {}).get("remarks", ""))
    return out


def areas_with_data(engagement_id: int) -> list:
    """Areas where at least one confirmation sheet is imported (drives the
    workpaper pack)."""
    rows = db.query(
        "SELECT DISTINCT kind FROM imports WHERE engagement_id=? AND "
        "status='active' AND kind LIKE 'conf_%'", (engagement_id,))
    found = {r["kind"].split("|", 1)[1] for r in rows if "|" in r["kind"]}
    return [a for a in AREAS if a in found]
