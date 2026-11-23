"""Public demo mode: temp storage, seeded engagement, one-click sign-in, and
every workflow step renders without raising."""

import os

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_ui_smoke import STEPS


@pytest.fixture()
def demo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_TOOL_DEMO", "1")
    monkeypatch.setenv("AUDIT_TOOL_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path


def test_is_demo_flag(monkeypatch):
    from core import demo
    monkeypatch.setenv("AUDIT_TOOL_DEMO", "true")
    assert demo.is_demo()
    monkeypatch.setenv("AUDIT_TOOL_DEMO", "0")
    assert not demo.is_demo()


def test_prepare_environment_uses_temp_dir(monkeypatch):
    import tempfile

    from core import demo
    monkeypatch.setenv("AUDIT_TOOL_DEMO", "1")
    monkeypatch.delenv("AUDIT_TOOL_DATA_DIR", raising=False)
    demo.prepare_environment()
    assert os.environ["AUDIT_TOOL_DATA_DIR"].startswith(tempfile.gettempdir())


def test_seed_builds_ready_engagement_once(demo_env):
    from core import demo, risk
    from storage import auth, db
    assert demo.seed_if_empty() is True
    assert auth.authenticate(*demo.DEMO_USER[:2]) is not None
    (eng,) = db.list_engagements()
    assert len(db.active_transactions(eng["id"])) > 10_000
    assert len(risk.get_populations(eng["id"])) > 0
    assert demo.seed_if_empty() is False


def test_demo_walkthrough_every_step(demo_env):
    at = AppTest.from_file("../app.py", default_timeout=180).run()
    assert not at.exception
    assert not [t for t in at.text_input if t.label == "Password"]
    at.button[0].click().run()
    assert not at.exception
    for step in STEPS:
        at.sidebar.radio[0].set_value(step).run()
        assert not at.exception, (step, at.exception[0].message)
