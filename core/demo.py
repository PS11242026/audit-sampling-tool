"""Public demo mode (e.g. Streamlit Community Cloud).

Enabled by AUDIT_TOOL_DEMO=1. The tool then keeps its database in a temp
directory and, on first boot, seeds one engagement on the synthetic
Kestrel Transmission dataset (demo/generate_demo_data.py): ledger and trial
balance imported, transactions categorized, materiality set, SA 315
analysis run and SERC tariff parameters entered, so every step has data.
"""

import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_USER = ("demo", "demo-audit-2026", "Partner")


def is_demo() -> bool:
    return os.environ.get("AUDIT_TOOL_DEMO", "").strip().lower() in {
        "1", "true", "yes", "on"}


def prepare_environment() -> None:
    """Point the database at a temp dir. Call before any database access."""
    if is_demo():
        os.environ.setdefault(
            "AUDIT_TOOL_DATA_DIR",
            str(Path(tempfile.gettempdir()) / "audit-tool-demo"))


def sample_files() -> dict[str, Path]:
    """Generate (once) and return the synthetic SAP-style input files."""
    from demo import generate_demo_data as gen

    out = gen.OUT_DIR
    files = {
        "Ledger (SAP FAGLL03 style)": out / "demo_sap_ledger_fy2026.xlsx",
        "Trial balance": out / "demo_trial_balance_fy2026.xlsx",
        "SERC tariff-order parameters": out / "demo_serc_order_fy2026.xlsx",
    }
    if not all(p.exists() for p in files.values()):
        gen.main()
    return files


def seed_if_empty() -> bool:
    """Create the demo user and a fully prepared engagement, once."""
    from core import categorizer, importer, materiality, risk, serc
    from storage import auditlog, auth, db

    db.init_db()
    if auth.user_count():
        return False
    username, password, role = DEMO_USER
    auth.create_user(username, password, role)
    user = auth.authenticate(username, password)

    eid = db.create_engagement(
        "Kestrel Transmission FY2026 Audit (demo)", "Kestrel Transmission Ltd",
        "2025-04-01", "2026-03-31",
        "MYT Control Period FY2025-26 to FY2029-30", username)
    categorizer.ensure_default_rules(eid)
    risk.ensure_default_config(eid)

    files = sample_files()
    ledger = files["Ledger (SAP FAGLL03 style)"]
    content = ledger.read_bytes()
    raw = importer.read_table(content, ledger.name)
    mapping = importer.guess_mapping(raw.columns)
    clean, _ = importer.normalize_ledger(raw, mapping)
    importer.import_ledger(eid, clean, ledger.name,
                           importer.file_sha256(content), mapping, username)

    tb = files["Trial balance"]
    tb_content = tb.read_bytes()
    tb_raw = importer.read_table(tb_content, tb.name)
    tb_map = importer.guess_mapping(tb_raw.columns, importer.TB_GUESSES)
    tb_clean, _ = importer.normalize_tb(tb_raw, tb_map)
    importer.import_tb(eid, tb_clean, tb.name,
                       importer.file_sha256(tb_content), tb_map, username)

    categorizer.apply_to_engagement(eid)
    m = materiality.compute(50_000_000_000, 0.5, 75)
    materiality.save(eid, {
        "benchmark": "Total revenue", "benchmark_amount": 50_000_000_000,
        "percent": 0.5, "overall": m["overall"], "pm_percent": 75,
        "performance": m["performance"], "isl_cutoff": m["performance"],
        "notes": "Demo engagement"}, username)
    risk.run_analysis(eid, username)

    data = serc.load(eid)
    data.update({"approved_atc": 48_000_000_000.0,
                 "approved_wheeling": 240_000_000.0,
                 "trueup_adjustment": 1_200_000_000.0,
                 "incentive": 150_000_000.0, "variance_threshold_pct": 1.0,
                 "tariff_order_ref": "SERC Case No. 217 of 2024 (fictional)"})
    serc.save(eid, data, username)
    auditlog.log(user, "DEMO_SEED", engagement_id=eid)
    return True
