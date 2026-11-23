"""SERC tariff-order parameters and the regulated-revenue reconciliation.

Booked electricity income (from the categorized ledger) is compared month by
month with the expected billing under the SERC MYT order (default: 1/12 of
approved annual transmission charges), and a year-total tie-out is computed:
booked vs (approved ATC + wheeling + true-up +/- incentives).
"""

import json

import numpy as np
import pandas as pd

from core.categorizer import CAT_TRANS, CAT_WHEEL
from storage import db

DEFAULTS = {
    "control_period": "MYT Control Period FY2025-26 to FY2029-30",
    "tariff_order_ref": "",
    "approved_atc": 0.0,          # approved annual transmission charges (Rs)
    "approved_wheeling": 0.0,     # approved annual wheeling income (Rs)
    "trueup_adjustment": 0.0,     # true-up recognised in the year (Rs)
    "incentive": 0.0,             # incentive/(penalty) recognised (Rs)
    "monthly_basis": "equal",     # equal -> 1/12 of annual per month
    "variance_threshold_pct": 1.0,
    "notes": "",
}


def load(engagement_id: int) -> dict:
    row = db.query_one("SELECT data_json FROM serc_data WHERE engagement_id=?",
                       (engagement_id,))
    data = dict(DEFAULTS)
    if row:
        data.update(json.loads(row["data_json"]))
    return data


def save(engagement_id: int, data: dict, actor: str) -> None:
    db.execute(
        "INSERT INTO serc_data (engagement_id, data_json, updated_by, "
        "updated_at) VALUES (?,?,?,?) ON CONFLICT(engagement_id) DO UPDATE "
        "SET data_json=excluded.data_json, updated_by=excluded.updated_by, "
        "updated_at=excluded.updated_at",
        (engagement_id, json.dumps(data), actor, db.now()))


def _monthly_booked(txns: pd.DataFrame, category: str, fy_start: str,
                    fy_end: str) -> pd.Series:
    months = pd.period_range(pd.Timestamp(fy_start), pd.Timestamp(fy_end),
                             freq="M")
    t = txns[txns["category"] == category]
    if t.empty:
        return pd.Series(0.0, index=months)
    dates = pd.to_datetime(t["date"], errors="coerce")
    # credits are negative in the debit-positive convention, so income = -sum
    booked = (-t["amount_signed"].astype(float)).groupby(
        dates.dt.to_period("M")).sum()
    return booked.reindex(months, fill_value=0.0)


def _recon_table(booked: pd.Series, annual_expected: float,
                 threshold_pct: float) -> pd.DataFrame:
    expected = annual_expected / 12.0 if annual_expected else 0.0
    df = pd.DataFrame({
        "month": [str(m) for m in booked.index],
        "expected": expected,
        "booked": booked.to_numpy(dtype=float),
    })
    df["variance"] = df["booked"] - df["expected"]
    df["variance_pct"] = np.where(df["expected"] != 0,
                                  df["variance"] / df["expected"] * 100.0, 0.0)
    df["exception"] = np.abs(df["variance_pct"]) > float(threshold_pct)
    return df


def monthly_reconciliation(txns: pd.DataFrame, serc: dict, fy_start: str,
                           fy_end: str) -> pd.DataFrame:
    booked = _monthly_booked(txns, CAT_TRANS, fy_start, fy_end)
    return _recon_table(booked, float(serc.get("approved_atc") or 0),
                        float(serc.get("variance_threshold_pct") or 1.0))


def wheeling_reconciliation(txns: pd.DataFrame, serc: dict, fy_start: str,
                            fy_end: str) -> pd.DataFrame:
    booked = _monthly_booked(txns, CAT_WHEEL, fy_start, fy_end)
    return _recon_table(booked, float(serc.get("approved_wheeling") or 0),
                        float(serc.get("variance_threshold_pct") or 1.0))


def annual_tieout(txns: pd.DataFrame, serc: dict) -> dict:
    elec = txns[txns["category"].isin([CAT_TRANS, CAT_WHEEL])]
    booked_total = float(-elec["amount_signed"].astype(float).sum())
    expected_total = (float(serc.get("approved_atc") or 0)
                      + float(serc.get("approved_wheeling") or 0)
                      + float(serc.get("trueup_adjustment") or 0)
                      + float(serc.get("incentive") or 0))
    difference = booked_total - expected_total
    pct = difference / expected_total * 100.0 if expected_total else 0.0
    return {"expected_total": expected_total, "booked_total": booked_total,
            "difference": difference, "difference_pct": pct}
