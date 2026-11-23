"""Ledger-vs-TB reconciliation coverage and mapping-sanity checks.

Guards the "OK ties" signal on the Data import page against the failure mode
where a mis-mapped trial balance (account codes mapped to an amount column)
silently reports nothing as reconciled.
"""

import pandas as pd

from core import importer


def _ledger(accounts_amounts):
    """Minimal transactions frame: {account: net_signed_amount}."""
    rows = [{"account": a, "amount_signed": v, "narration": ""}
            for a, v in accounts_amounts.items()]
    return pd.DataFrame(rows)


def _tb_from_ledger(net_by_account):
    """A well-mapped TB whose movement matches the ledger net per account."""
    return pd.DataFrame([{
        "account": a, "account_name": "",
        "opening": 0.0, "debit": max(v, 0.0), "credit": max(-v, 0.0),
        "closing": v,
    } for a, v in net_by_account.items()])


def test_reconcile_ties_and_flags_the_one_mismatch():
    led = {"440010": 1000.0, "440020": -2500.0, "440030": 700.0}
    txns = _ledger(led)
    tb = _tb_from_ledger(led)
    tb.loc[tb["account"] == "440020", "credit"] += 500.0   # planted break

    recon = importer.tb_reconcile(txns, tb)
    stats = importer.reconcile_stats(recon)
    assert stats["matched_accounts"] == 3
    assert stats["matched_mismatch"] == 1
    bad = recon[recon["in_ledger"] & recon["in_tb"] & ~recon["ok"]]
    assert bad["account"].tolist() == ["440020"]
    assert abs(abs(float(bad["difference"].iloc[0])) - 500.0) < 1e-6


def test_zero_overlap_is_detectable():
    """The reported bug: TB 'account' column holds amounts, so no ledger
    account matches and reconcile_stats must report zero coverage."""
    txns = _ledger({"440010": 1000.0, "440020": 2000.0})
    tb = _tb_from_ledger({"-1927717885.09": 5.0, "1 INR": 1.0})
    stats = importer.reconcile_stats(importer.tb_reconcile(txns, tb))
    assert stats["ledger_accounts"] == 2
    assert stats["matched_accounts"] == 0
    assert stats["ledger_only"] == 2


def test_reconcile_stats_empty():
    assert importer.reconcile_stats(pd.DataFrame())["matched_accounts"] == 0


def test_mapping_collisions():
    m = {"account": "A", "account_name": "A", "debit": "B", "credit": "B",
         "opening": None, "closing": "C"}
    coll = importer.mapping_collisions(m)
    assert coll == {"A": ["account", "account_name"], "B": ["debit", "credit"]}


def test_tb_mapping_warnings_flags_amounts_in_account_column():
    raw = pd.DataFrame({"FY 2025 1-12": ["1 INR", "-1927717885.09", "6000"]})
    mapping = {"account": "FY 2025 1-12", "debit": "FY 2025 1-12",
               "account_name": None, "opening": None, "credit": None,
               "closing": None}
    warns = importer.tb_mapping_warnings(raw, mapping)
    assert len(warns) == 2                       # collision + amount-shaped
    assert any("same source column" in w for w in warns)
    assert any("look" in w.lower() for w in warns)


def test_tb_mapping_warnings_silent_on_clean_mapping():
    raw = pd.DataFrame({"code": ["440010", "440020"],
                        "bal": ["1000", "2000"]})
    mapping = {"account": "code", "closing": "bal", "account_name": None,
               "opening": None, "debit": None, "credit": None}
    assert importer.tb_mapping_warnings(raw, mapping) == []


def test_normalize_tb_reports_degenerate_signals():
    raw = pd.DataFrame({"col": ["1 INR", "-1927717885.09", "6000"]})
    mapping = {f: "col" for f in
               ("account", "account_name", "opening", "debit", "credit",
                "closing")}
    _, issues = importer.normalize_tb(raw, mapping)
    assert issues["debit_equals_credit_all"] is True
    assert issues["account_amountish_share"] > 0.5


def _tb_map(**over):
    m = {f: None for f in ("account", "account_name", "opening", "debit",
                           "credit", "closing")}
    m.update(over)
    return m


def test_tb_mapping_warnings_flags_no_amount_columns():
    """The reported case: account + name mapped, every amount column left
    unmapped -> reconciliation can never tie."""
    raw = pd.DataFrame({"GL": ["440010", "440050"],
                        "Particular": ["a", "b"],
                        "Closing Balance": ["100", "200"]})
    warns = importer.tb_mapping_warnings(
        raw, _tb_map(account="GL", account_name="Particular"))
    assert any("No balance or movement column is mapped" in w for w in warns)


def test_tb_mapping_warnings_accepts_sufficient_amount_mappings():
    raw = pd.DataFrame({"GL": ["440010"], "Bal": ["100"], "Dr": ["100"]})
    # closing-only is a valid balance-style TB (movement = closing - opening)
    assert importer.tb_mapping_warnings(
        raw, _tb_map(account="GL", closing="Bal")) == []
    # debit-only is enough to produce a movement
    assert importer.tb_mapping_warnings(
        raw, _tb_map(account="GL", debit="Dr")) == []


def test_tb_mapping_warnings_flags_movement_that_cannot_compute():
    raw = pd.DataFrame({"GL": ["440010"], "Open": ["100"]})
    warns = importer.tb_mapping_warnings(
        raw, _tb_map(account="GL", opening="Open"))
    assert any("cannot produce an account movement" in w for w in warns)


def test_normalize_tb_flags_all_zero_amounts():
    raw = pd.DataFrame({"GL": ["440010", "440050"],
                        "Particular": ["a", "b"]})
    _, issues = importer.normalize_tb(
        raw, _tb_map(account="GL", account_name="Particular"))
    assert issues["amounts_all_zero"] is True
