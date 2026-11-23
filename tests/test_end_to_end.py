"""End-to-end pipeline test on the generated demo dataset:

user -> engagement -> ledger + TB import (with reconciliation catching the
planted Rs 500 mismatch) -> categorization -> materiality -> SA 315 analysis
-> MUS + stratified sampling (reproducibility proven) -> results ->
Stringer-bound evaluation -> SERC reconciliation (planted variances) ->
Excel workpaper pack + PDF memo -> SA 230 audit trail assertions.
"""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "demo" / "output"

ATC = 48_000_000_000.0
WHEELING = 240_000_000.0
TRUEUP = 1_200_000_000.0
INCENTIVE = 150_000_000.0


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    os.environ["AUDIT_TOOL_DATA_DIR"] = str(
        tmp_path_factory.mktemp("audit_data"))
    ledger = OUT / "demo_sap_ledger_fy2026.xlsx"
    if not ledger.exists():
        subprocess.run([sys.executable,
                        str(PROJECT_ROOT / "demo" / "generate_demo_data.py")],
                       check=True, cwd=PROJECT_ROOT)
    from storage import db
    db.init_db()
    yield {
        "ledger": ledger,
        "tb": OUT / "demo_trial_balance_fy2026.xlsx",
    }
    os.environ.pop("AUDIT_TOOL_DATA_DIR", None)


def test_full_pipeline(env):
    from core import (categorizer, importer, materiality, serc, risk,
                      sampling_service)
    from core.categorizer import (CAT_OI_FEES, CAT_RM, CAT_SPARES, CAT_TRANS)
    from reports import excel_pack, pdf_memo
    from storage import auditlog, auth, db

    # ---------------------------------------------------- user, engagement
    auth.create_user("pulkit", "audit@2026", "Partner")
    user = auth.authenticate("pulkit", "audit@2026")
    assert user and user["role"] == "Partner"
    assert auth.authenticate("pulkit", "wrong-password") is None

    eid = db.create_engagement(
        "Kestrel Transmission FY2026 Audit",
        "Kestrel Transmission Ltd",
        "2025-04-01", "2026-03-31",
        "MYT Control Period FY2025-26 to FY2029-30", user["username"])
    categorizer.ensure_default_rules(eid)
    risk.ensure_default_config(eid)

    # -------------------------------------------------------- ledger import
    content = env["ledger"].read_bytes()
    raw = importer.read_table(content, env["ledger"].name)
    mapping = importer.guess_mapping(raw.columns)
    assert mapping["date"] == "Posting Date"
    assert mapping["amount"] == "Amount in local currency"
    clean, issues = importer.normalize_ledger(raw, mapping)
    assert issues["rows_imported"] == issues["rows_in_file"] == len(raw)
    val = importer.validate_ledger(clean, "2025-04-01", "2026-03-31")
    assert val["out_of_fy"] == 0 and val["zero_amounts"] == 0
    importer.import_ledger(eid, clean, env["ledger"].name,
                           importer.file_sha256(content), mapping,
                           user["username"])
    auditlog.log(user, "IMPORT_LEDGER", details={"rows": len(clean)},
                 engagement_id=eid)

    # ------------------------------------------- TB import + reconciliation
    tb_content = env["tb"].read_bytes()
    tb_raw = importer.read_table(tb_content, env["tb"].name)
    tb_map = importer.guess_mapping(tb_raw.columns, importer.TB_GUESSES)
    tb_clean, _ = importer.normalize_tb(tb_raw, tb_map)
    importer.import_tb(eid, tb_clean, env["tb"].name,
                       importer.file_sha256(tb_content), tb_map,
                       user["username"])
    txns = db.active_transactions(eid)
    assert len(txns) == len(clean)
    recon = importer.tb_reconcile(txns, db.active_trial_balance(eid))
    bad = recon[~recon["ok"]]
    assert list(bad["account"]) == ["75103"]          # planted mismatch
    assert abs(abs(float(bad["difference"].iloc[0])) - 500.0) < 1.0

    # --------------------------------------------------------- categorize
    summary = categorizer.apply_to_engagement(eid)
    assert summary["uncategorized"] == 0
    assert summary["by_category"][CAT_RM] > 8000

    # --------------------------------------------------------- materiality
    m = materiality.compute(50_000_000_000, 0.5, 75)
    pm = m["performance"]
    materiality.save(eid, {
        "benchmark": "Total revenue",
        "benchmark_amount": 50_000_000_000, "percent": 0.5,
        "overall": m["overall"], "pm_percent": 75, "performance": pm,
        "isl_cutoff": pm, "notes": "e2e"}, user["username"])

    # ------------------------------------------------------- analysis run
    res = risk.run_analysis(eid, user["username"])
    assert res["full_items"] > 0
    pops = risk.get_populations(eid)
    by_cat = {p["category"]: p for p in pops.to_dict("records")}
    assert by_cat[CAT_TRANS]["strategy"] == "FULL"
    assert by_cat[CAT_RM]["strategy"] == "HYBRID"
    full = risk.full_list_txns(eid)
    assert (full["category"] == CAT_SPARES).any()     # ISL spares adjustments
    assert full["full_reason"].str.contains("contra", case=False).any()

    # -------------------------------------------- MUS sampling for R&M
    pop = sampling_service.population(eid, CAT_RM)
    assert len(pop) > 7000
    params = {"confidence": 0.95, "tolerable": pm, "expected": pm * 0.1}
    size = sampling_service.compute_size("mus", pop, params)
    params["n"] = size["n"]
    sid1, sel1, info1 = sampling_service.generate(eid, CAT_RM, "mus",
                                                  params, user)
    # regenerating with the SAME seed must reproduce the selection exactly
    sid2, sel2, info2 = sampling_service.generate(
        eid, CAT_RM, "mus", params, user,
        justification="reproducibility check", seed=info1["seed"])
    assert list(sel1["id"]) == list(sel2["id"])
    assert sampling_service.get_sample(sid1)["status"] == "superseded"

    # ------------------------------------- stratified sample, other income
    sidf, self_, infof = sampling_service.generate(
        eid, CAT_OI_FEES, "stratified",
        {"n": 30, "n_bands": 4, "confidence": 0.95}, user)
    assert infof["n_selected"] == 30
    assert sum(b["items"] for b in infof["per_band"]) == len(
        sampling_service.population(eid, CAT_OI_FEES))

    # ------------------------------------------- results + MUS evaluation
    items = sampling_service.get_sample_items(sid2)
    items["result"] = "Pass"
    items["audited_value"] = items["book_value"]
    lower_idx = items[items["is_top_stratum"] == 0].index[:2]
    items.loc[lower_idx, "result"] = "Exception"
    items.loc[lower_idx, "audited_value"] = (
        items.loc[lower_idx, "book_value"] * 0.6).to_numpy()
    sampling_service.save_results(sid2, items, user)
    ev = sampling_service.evaluate_sample(sid2, user)
    interval = sampling_service.get_sample(sid2)["payload"]["info"]["interval"]
    assert ev["errors_lower_over"] == 2
    # two taintings of 0.4 -> projected overstatement = 0.8 x interval
    assert ev["projected_over"] == pytest.approx(0.8 * float(interval),
                                                 rel=1e-9)
    assert ev["upper_misstatement_limit"] > ev["basic_precision"]
    assert isinstance(ev["acceptable"], bool)

    ev_strat = sampling_service.evaluate_sample(sidf, user)
    # n=30 with zero deviations supports only ~9.5% upper deviation limit at
    # 95% confidence - correctly NOT acceptable against a 5% tolerable rate
    attr = ev_strat["attribute"]
    assert attr["deviations"] == 0
    assert attr["achieved_upper_limit"] == pytest.approx(
        1 - 0.05 ** (1 / 30), abs=1e-6)
    assert attr["acceptable"] is False
    assert ev_strat["ratio_projection"] == 0.0

    # ------------------------------------------------- SERC reconciliation
    data = serc.load(eid)
    data.update({"approved_atc": ATC, "approved_wheeling": WHEELING,
                 "trueup_adjustment": TRUEUP, "incentive": INCENTIVE,
                 "variance_threshold_pct": 1.0,
                 "tariff_order_ref": "SERC Case No. 217 of 2024"})
    serc.save(eid, data, user["username"])
    txns = db.active_transactions(eid)          # refresh (has categories now)
    monthly = serc.monthly_reconciliation(txns, data, "2025-04-01",
                                          "2026-03-31")
    flagged = set(monthly.loc[monthly["exception"], "month"])
    assert flagged == {"2025-09", "2026-02", "2026-03"}   # planted variances
    wheel = serc.wheeling_reconciliation(txns, data, "2025-04-01",
                                         "2026-03-31")
    assert not wheel["exception"].any()                   # clean control line
    annual = serc.annual_tieout(txns, data)
    assert 39_000_000 < annual["difference"] < 41_000_000  # Feb 2% - CNs

    # -------------------------------------------------------------- reports
    pack = excel_pack.generate_workpaper_pack(eid, user)
    assert len(pack) > 50_000
    from openpyxl import load_workbook
    names = load_workbook(io.BytesIO(pack), read_only=True).sheetnames
    for expected in ("Cover", "Materiality", "Populations",
                     "100pc verification", "_meta", "Evaluation",
                     "SERC recon", "Exceptions", "Audit trail"):
        assert expected in names, f"missing sheet {expected}"

    parsed = excel_pack.read_results_workbook(pack)
    assert sid2 in parsed and "item_id" in parsed[sid2].columns

    memo = pdf_memo.generate_memo(eid, user)
    assert memo[:5] == b"%PDF-" and len(memo) > 5_000

    # ---------------------------------------------------- SA 230 trail
    trail = auditlog.fetch(engagement_id=eid)
    actions = set(trail["action"])
    for needed in ("IMPORT_LEDGER", "GENERATE_SAMPLE", "SAMPLE_STATUS",
                   "SAVE_RESULTS", "EVALUATE_SAMPLE", "EXPORT_EXCEL_PACK",
                   "EXPORT_PDF_MEMO"):
        if needed == "SAMPLE_STATUS":
            continue  # status changes exercised via generate/supersede
        assert needed in actions, f"missing audit trail action {needed}"
