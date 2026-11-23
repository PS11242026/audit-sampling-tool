"""Staleness detection for the analysis run.

Guards the failure mode where re-categorizing after an analysis run leaves
the stored populations (and everything built on them - the 100% list,
samples, reports) describing categories that no longer exist. Reported on
the FY2026 engagement: doc 100306835 stayed in a 228k-item 'Uncategorized'
population on the Analysis page even after account rules were added and
re-applied, because the analysis was never re-run.
"""

import pandas as pd

from core import risk


def _pops(rows):
    return pd.DataFrame(
        [{"run_ts": "2026-07-17T17:06:12", "category": c,
          "txn_count": n, "total_abs": v} for c, n, v in rows])


def _txns(rows):
    out = []
    for c, n, v in rows:
        out += [{"category": c, "amount_abs": v / n}] * n
    return pd.DataFrame(out)


def test_matching_snapshot_is_not_stale(monkeypatch):
    rows = [("Repairs & maintenance", 4, 200.0), ("Uncategorized", 2, 50.0)]
    monkeypatch.setattr(risk, "get_populations", lambda eid: _pops(rows))
    monkeypatch.setattr(risk.db, "active_transactions",
                        lambda eid: _txns(rows))
    assert risk.analysis_stale(1) is None


def test_recategorized_ledger_is_stale(monkeypatch):
    monkeypatch.setattr(risk, "get_populations", lambda eid: _pops(
        [("Uncategorized", 5, 500.0), ("Repairs & maintenance", 1, 20.0)]))
    monkeypatch.setattr(risk.db, "active_transactions", lambda eid: _txns(
        [("Repairs & maintenance", 6, 520.0)]))
    stale = risk.analysis_stale(1)
    assert stale is not None
    assert stale["run_ts"] == "2026-07-17T17:06:12"
    changed = {c["category"]: (c["items_at_run"], c["items_now"])
               for c in stale["changed"]}
    assert changed == {"Uncategorized": (5, 0),
                       "Repairs & maintenance": (1, 6)}


def test_value_drift_with_equal_counts_is_stale(monkeypatch):
    """Two categories swapping equal item counts still shifts value."""
    monkeypatch.setattr(risk, "get_populations", lambda eid: _pops(
        [("A", 2, 100.0), ("B", 2, 900.0)]))
    monkeypatch.setattr(risk.db, "active_transactions", lambda eid: _txns(
        [("A", 2, 900.0), ("B", 2, 100.0)]))
    assert risk.analysis_stale(1) is not None


def test_no_run_yet_is_not_stale(monkeypatch):
    monkeypatch.setattr(risk, "get_populations",
                        lambda eid: pd.DataFrame())
    assert risk.analysis_stale(1) is None
