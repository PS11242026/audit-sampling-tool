"""Transaction categorization: priority-ordered rules that map account codes
and narration keywords to audit categories (the populations for risk
assessment and sampling)."""

import pandas as pd

from storage import db

CAT_TRANS = "Electricity income - transmission charges"
CAT_WHEEL = "Electricity income - wheeling charges"
CAT_SPARES = "Spares & inventory adjustments"
CAT_DTAX = "Deferred tax entries"
CAT_ONEOFF = "New accounts / one-off items"
CAT_RM = "Repairs & maintenance"
CAT_CAPEX = "Capital expenditure / CWIP"
CAT_OI_FEES = "Other income - fees & services"
CAT_OI_INT = "Other income - interest"
CAT_OI_MISC = "Other income - miscellaneous"
CAT_EMP = "Employee costs"
CAT_OH = "Administrative overheads"
UNCATEGORIZED = "Uncategorized"

ALL_CATEGORIES = [
    CAT_TRANS, CAT_WHEEL, CAT_SPARES, CAT_DTAX, CAT_ONEOFF, CAT_RM, CAT_CAPEX,
    CAT_OI_FEES, CAT_OI_INT, CAT_OI_MISC, CAT_EMP, CAT_OH, UNCATEGORIZED,
]

# Normal balance side: income categories are credit-normal; everything else
# debit-normal. Entries on the abnormal side are flagged as contra items.
INCOME_CATEGORIES = {CAT_TRANS, CAT_WHEEL, CAT_OI_FEES, CAT_OI_INT, CAT_OI_MISC}

# (priority, field, match_type, pattern, category) - tuned to the demo chart
# of accounts; edit per engagement to match the client's actual codes.
DEFAULT_RULES = [
    (10, "account", "prefix", "61101", CAT_TRANS),
    (20, "account", "prefix", "61102", CAT_WHEEL),
    (30, "account", "prefix", "611", CAT_TRANS),
    (40, "account", "prefix", "621", CAT_OI_INT),
    (50, "account", "prefix", "622", CAT_OI_MISC),
    (60, "account", "prefix", "623", CAT_OI_FEES),
    (70, "account", "prefix", "626", CAT_OI_FEES),
    (80, "account", "prefix", "624", CAT_OI_MISC),
    (90, "account", "prefix", "625", CAT_OI_MISC),
    (95, "account", "prefix", "629", CAT_ONEOFF),
    (100, "account", "prefix", "711", CAT_RM),
    (110, "account", "prefix", "721", CAT_EMP),
    (120, "account", "prefix", "731", CAT_SPARES),
    (130, "account", "prefix", "741", CAT_DTAX),
    (140, "account", "prefix", "751", CAT_OH),
    (150, "account", "prefix", "151", CAT_CAPEX),
    (200, "narration", "contains", "transmission charge", CAT_TRANS),
    (210, "narration", "contains", "wheeling", CAT_WHEEL),
    (220, "narration", "contains", "repair", CAT_RM),
    (230, "narration", "contains", "maintenance", CAT_RM),
    (240, "narration", "contains", "salary", CAT_EMP),
    (250, "narration", "contains", "wages", CAT_EMP),
    (260, "narration", "contains", "interest", CAT_OI_INT),
    (270, "narration", "contains", "consultancy", CAT_OI_FEES),
    (280, "narration", "contains", "supervision", CAT_OI_FEES),
    (290, "narration", "contains", "scrap", CAT_OI_MISC),
    (300, "narration", "contains", "spares", CAT_SPARES),
    (310, "narration", "contains", "deferred tax", CAT_DTAX),
]


def ensure_default_rules(engagement_id: int) -> None:
    row = db.query_one(
        "SELECT COUNT(*) AS c FROM category_rules WHERE engagement_id=?",
        (engagement_id,))
    if row and row["c"] == 0:
        db.executemany(
            "INSERT INTO category_rules (engagement_id, priority, field, "
            "match_type, pattern, category, active) VALUES (?,?,?,?,?,?,1)",
            [(engagement_id, *r) for r in DEFAULT_RULES])


def load_rules(engagement_id: int) -> pd.DataFrame:
    return db.read_df(
        "SELECT id, priority, field, match_type, pattern, category, active "
        "FROM category_rules WHERE engagement_id=? ORDER BY priority, id",
        (engagement_id,))


def save_rules(engagement_id: int, rules: pd.DataFrame) -> None:
    """Replace the engagement's rule set with the edited grid."""
    with db.connect() as con:
        con.execute("DELETE FROM category_rules WHERE engagement_id=?",
                    (engagement_id,))
        for r in rules.itertuples(index=False):
            if not str(getattr(r, "pattern", "") or "").strip():
                continue
            con.execute(
                "INSERT INTO category_rules (engagement_id, priority, field, "
                "match_type, pattern, category, active) VALUES (?,?,?,?,?,?,?)",
                (engagement_id, int(getattr(r, "priority", 999) or 999),
                 str(r.field), str(r.match_type), str(r.pattern),
                 str(r.category), 1 if getattr(r, "active", 1) else 0))


def apply_rules(df: pd.DataFrame, rules: pd.DataFrame) -> pd.Series:
    """Return a category per row; first matching rule (by priority) wins."""
    cat = pd.Series(UNCATEGORIZED, index=df.index, dtype=object)
    acct = df["account"].astype(str).str.strip()
    narr = df["narration"].fillna("").astype(str).str.lower()
    for r in rules.itertuples(index=False):
        if not getattr(r, "active", 1):
            continue
        remaining = cat.eq(UNCATEGORIZED)
        if not remaining.any():
            break
        pattern = str(r.pattern)
        try:
            if r.field == "account":
                if r.match_type == "prefix":
                    m = acct.str.startswith(pattern)
                elif r.match_type == "range":
                    lo, _, hi = pattern.partition("-")
                    nums = pd.to_numeric(acct, errors="coerce")
                    m = nums.between(float(lo), float(hi))
                elif r.match_type == "regex":
                    m = acct.str.contains(pattern, regex=True, na=False)
                else:  # contains
                    m = acct.str.contains(pattern, case=False, regex=False,
                                          na=False)
            else:  # narration
                if r.match_type == "regex":
                    m = narr.str.contains(pattern, regex=True, na=False)
                else:
                    m = narr.str.contains(pattern.lower(), regex=False,
                                          na=False)
        except (ValueError, TypeError):
            continue  # malformed rule pattern - skip rather than fail the run
        cat[remaining & m.fillna(False)] = r.category
    return cat


def apply_to_engagement(engagement_id: int) -> dict:
    """Categorize the active ledger and persist the result."""
    imp = db.active_import(engagement_id, "ledger")
    if not imp:
        raise ValueError("no active ledger import for this engagement")
    txns = db.read_df(
        "SELECT id, account, narration FROM transactions "
        "WHERE engagement_id=? AND import_id=?", (engagement_id, imp["id"]))
    rules = load_rules(engagement_id)
    cats = apply_rules(txns, rules)
    db.executemany("UPDATE transactions SET category=? WHERE id=?",
                   list(zip(cats.tolist(), txns["id"].tolist())))
    counts = cats.value_counts().to_dict()
    return {"total": int(len(txns)),
            "uncategorized": int(counts.get(UNCATEGORIZED, 0)),
            "by_category": {str(k): int(v) for k, v in counts.items()}}
