"""Transaction analyzer: anomaly flags for unusual items (SA 315 / SA 240).

Codes stamped into transactions.flags (semicolon separated):
  DUPLICATE   same account + amount + date as another entry
  ROUND       round-sum amount at/above the threshold (exact lakh multiples)
  PERIOD_END  posted within the last N days of the financial year
  WEEKEND     posted on a Saturday/Sunday
  KEYWORD     narration contains a sensitive keyword
  CONTRA      entry on the abnormal side for its category
  ZERO        zero-amount entry (excluded from sampling populations)
"""

import numpy as np
import pandas as pd

KEYWORDS = ["suspense", "adjust", "reversal", "rectif", "write back",
            "write-back", "written back", "provision"]

DEFAULT_ROUND_THRESHOLD = 100_000.0
DEFAULT_PERIOD_END_DAYS = 7


def stamp_flags(df: pd.DataFrame, fy_end: str,
                income_categories=None,
                round_threshold: float = DEFAULT_ROUND_THRESHOLD,
                period_end_days: int = DEFAULT_PERIOD_END_DAYS) -> pd.Series:
    n = len(df)
    if n == 0:
        return pd.Series([], dtype=object)
    amounts = df["amount_abs"].astype(float)
    dates = pd.to_datetime(df["date"], errors="coerce")
    narr = df["narration"].fillna("").astype(str).str.lower()

    checks = []
    dup = df.duplicated(subset=["account", "amount_abs", "date"], keep=False) \
        & amounts.gt(0)
    checks.append((dup, "DUPLICATE"))

    round_mask = amounts.ge(round_threshold) & (amounts % 100_000 == 0)
    checks.append((round_mask, "ROUND"))

    pe_start = pd.Timestamp(fy_end) - pd.Timedelta(days=period_end_days)
    checks.append((dates.ge(pe_start), "PERIOD_END"))

    checks.append((dates.dt.dayofweek.ge(5), "WEEKEND"))

    kw_pattern = "|".join(KEYWORDS)
    checks.append((narr.str.contains(kw_pattern, regex=True, na=False),
                   "KEYWORD"))

    if income_categories is not None and "category" in df.columns and \
            "side" in df.columns:
        cat = df["category"].astype(str)
        side = df["side"].astype(str)
        is_income = cat.isin(set(income_categories))
        nonzero = amounts.gt(0)
        contra = (is_income & side.eq("D") & nonzero) | \
                 (~is_income & side.eq("C") & nonzero)
        checks.append((contra, "CONTRA"))

    checks.append((amounts.eq(0), "ZERO"))

    flags = pd.Series("", index=df.index, dtype=object)
    for mask, code in checks:
        mask = pd.Series(mask, index=df.index).fillna(False).astype(bool)
        flags = flags + np.where(mask, code + ";", "")
    return flags.str.rstrip(";")


def summarize(flags: pd.Series) -> pd.DataFrame:
    """Counts per anomaly code."""
    if flags is None or len(flags) == 0:
        return pd.DataFrame(columns=["flag", "count"])
    exploded = flags.fillna("").astype(str).str.split(";").explode()
    exploded = exploded[exploded != ""]
    out = exploded.value_counts().rename_axis("flag").reset_index(name="count")
    return out
