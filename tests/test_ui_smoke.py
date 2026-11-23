"""UI smoke test: executes app.py in-process via streamlit.testing.AppTest,
signs in, loads a demo engagement end-to-end, then renders every workflow
step and asserts no page raises."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "demo" / "output"

STEPS = [
    "1. Engagement & materiality",
    "2. Data import",
    "3. Categorize",
    "4. Risk configuration",
    "5. Analysis run",
    "6. Sampling",
    "7. SERC reconciliation",
    "8. Balance confirmations",
    "9. Results & evaluation",
    "10. Reports & export",
    "11. Admin & audit trail",
]


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    os.environ["AUDIT_TOOL_DATA_DIR"] = str(
        tmp_path_factory.mktemp("ui_smoke_data"))
    ledger = OUT / "demo_sap_ledger_fy2026.xlsx"
    if not ledger.exists():
        subprocess.run([sys.executable,
                        str(PROJECT_ROOT / "demo" / "generate_demo_data.py")],
                       check=True, cwd=PROJECT_ROOT)

    from core import (categorizer, importer, materiality, serc, risk,
                      sampling_service)
    from core.categorizer import CAT_RM
    from storage import auth, db

    db.init_db()
    auth.create_user("smoke", "password1", "Partner")
    user = auth.authenticate("smoke", "password1")
    eid = db.create_engagement("UI Smoke", "Kestrel Transmission", "2025-04-01",
                               "2026-03-31", "MYT", "smoke")
    categorizer.ensure_default_rules(eid)
    risk.ensure_default_config(eid)

    content = ledger.read_bytes()
    raw = importer.read_table(content, ledger.name)
    mapping = importer.guess_mapping(raw.columns)
    clean, _ = importer.normalize_ledger(raw, mapping)
    importer.import_ledger(eid, clean, ledger.name,
                           importer.file_sha256(content), mapping, "smoke")
    tb_file = OUT / "demo_trial_balance_fy2026.xlsx"
    tb_raw = importer.read_table(tb_file.read_bytes(), tb_file.name)
    tb_map = importer.guess_mapping(tb_raw.columns, importer.TB_GUESSES)
    tb_clean, _ = importer.normalize_tb(tb_raw, tb_map)
    importer.import_tb(eid, tb_clean, tb_file.name, "x", tb_map, "smoke")

    categorizer.apply_to_engagement(eid)
    m = materiality.compute(50_000_000_000, 0.5, 75)
    materiality.save(eid, {"benchmark": "Total revenue",
                           "benchmark_amount": 50_000_000_000,
                           "percent": 0.5, "overall": m["overall"],
                           "pm_percent": 75,
                           "performance": m["performance"],
                           "isl_cutoff": m["performance"], "notes": ""},
                     "smoke")
    risk.run_analysis(eid, "smoke")
    data = serc.load(eid)
    data.update({"approved_atc": 48_000_000_000.0,
                 "approved_wheeling": 240_000_000.0,
                 "trueup_adjustment": 1_200_000_000.0,
                 "incentive": 150_000_000.0})
    serc.save(eid, data, "smoke")
    pm = m["performance"]
    sampling_service.generate(
        eid, CAT_RM, "mus",
        {"n": 25, "confidence": 0.95, "tolerable": pm, "expected": 0.0},
        user)
    yield {"user": user, "eid": eid}
    os.environ.pop("AUDIT_TOOL_DATA_DIR", None)


def test_login_page_renders_first_run_or_login():
    # no session user -> the login page must render without exceptions
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
    at.run(timeout=30)
    assert not at.exception


def test_all_steps_render(loaded):
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
    at.session_state["user"] = loaded["user"]
    at.session_state["engagement_id"] = loaded["eid"]
    at.run(timeout=60)
    assert not at.exception, at.exception
    for step in STEPS:
        at.radio[0].set_value(step)
        at.run(timeout=120)
        assert not at.exception, f"{step} raised: {at.exception}"


def test_duplicate_engagement_guard(tmp_path_factory):
    """Clicking Create twice with the same name must create exactly one
    engagement, show a success flash the first time and an error the
    second (regression for the silent-duplicate defect)."""
    os.environ["AUDIT_TOOL_DATA_DIR"] = str(
        tmp_path_factory.mktemp("dup_guard_data"))
    from storage import auth, db
    db.init_db()
    auth.create_user("dupguard", "password1", "Partner")
    user = auth.authenticate("dupguard", "password1")

    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
    at.session_state["user"] = user
    at.run(timeout=60)
    assert not at.exception

    def submit_create():
        btns = [b for b in at.button
                if "Create engagement" in (b.label or "")]
        assert btns, "Create engagement submit button not found"
        btns[0].click()
        at.run(timeout=60)

    at.text_input(key="ne_name").set_value("Dup Guard Engagement")
    submit_create()
    assert not at.exception
    assert len(db.list_engagements("all")) == 1
    assert any("created and selected" in str(s.value) for s in at.success)

    at.text_input(key="ne_name").set_value("Dup Guard Engagement")
    submit_create()
    assert len(db.list_engagements("all")) == 1   # duplicate blocked
    assert any("already exists" in str(e.value) for e in at.error)
    os.environ.pop("AUDIT_TOOL_DATA_DIR", None)
