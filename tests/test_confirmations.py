"""SA 505 balance confirmations: party-key normalization, book-vs-confirmed
matching and classification, coverage statistics, persistence, and the
step-8 page rendered against imported data."""

import os
from pathlib import Path

import pandas as pd
import pytest

from core import confirmations, importer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AREA = "Trade receivables"


def _frame(rows):
    """Canonical book/ext frame with every CONF column present."""
    cols = ["party", "party_name", "gl_account", "balance", "confirm_date",
            "reference"]
    return pd.DataFrame([{**dict.fromkeys(cols, ""), **r} for r in rows])


# ------------------------------------------------------------------ keys

def test_code_key_strips_sap_leading_zeros():
    assert confirmations.code_key("0000200012") == "200012"
    assert confirmations.code_key("200012") == "200012"
    assert confirmations.code_key("000") == "0"
    assert confirmations.code_key(None) == ""
    assert confirmations.code_key(" ab12 ") == "AB12"


def test_name_key_equivalences():
    assert (confirmations.name_key("M/s Tata & Sons Pvt. Ltd.")
            == confirmations.name_key("TATA AND SONS PVT LTD"))
    assert confirmations.name_key("  ") == ""
    assert (confirmations.name_key("Alpha-Beta (India)")
            == confirmations.name_key("ALPHA BETA INDIA"))


# ------------------------------------------------------------- normalize

def test_normalize_book_with_sap_columns_and_footer():
    raw = pd.DataFrame({
        "Customer": ["0000200012", "0000200012", "300055", None],
        "Customer Name": ["Alpha Traders", "Alpha Traders", "Bravo Supply",
                          None],
        "Closing Balance": ["60.000,00", "40.000,00", "50000.75", None],
        "Recon. Acct": ["230101", "230101", "230101", None],
    })
    mapping = importer.guess_mapping(raw.columns, confirmations.BOOK_GUESSES)
    assert mapping["party"] == "Customer"
    assert mapping["party_name"] == "Customer Name"
    assert mapping["balance"] == "Closing Balance"
    assert mapping["gl_account"] == "Recon. Acct"

    clean, issues = confirmations.normalize_book(raw, mapping)
    assert issues["rows_imported"] == 3
    assert issues["rows_skipped"] == 1            # footer row
    assert issues["distinct_parties"] == 2
    assert issues["duplicate_party_rows"] == 1    # open items, same party
    assert issues["total_balance"] == pytest.approx(150000.75)


def test_mapping_warnings_flag_collision_and_amount_shaped_codes():
    raw = pd.DataFrame({"col": ["1.234,56-", "-500", "77 000"]})
    mapping = {"party": "col", "balance": "col", "party_name": None,
               "gl_account": None}
    warns = confirmations.mapping_warnings(raw, mapping)
    assert any("same source column" in w for w in warns)
    assert any("party codes" in w for w in warns)
    clean_map = {"party": None, "party_name": None, "balance": "col",
                 "gl_account": None}
    assert confirmations.mapping_warnings(raw, clean_map) == []


# -------------------------------------------------------------- matching

def _book_four():
    return _frame([
        {"party": "0000200012", "party_name": "Alpha Traders",
         "balance": 100000.0},
        {"party": "300055", "party_name": "Bravo Supply",
         "balance": 50000.75},
        {"party": "400010", "party_name": "M/s Beta Industries",
         "balance": 75000.0},
        {"party": "500020", "party_name": "Delta Corp", "balance": 25000.0},
    ])


def _ext_four():
    return _frame([
        {"party": "200012", "party_name": "Alpha Traders",
         "balance": 100000.0, "confirm_date": "2026-03-31",
         "reference": "letter 1"},
        {"party": "300055", "party_name": "Bravo Supply",
         "balance": 50000.25},
        {"party": "", "party_name": "BETA INDUSTRIES", "balance": 74000.0},
        {"party": "", "party_name": "Zeta Ltd", "balance": 5000.0},
    ])


def test_match_classifies_all_four_ways():
    recon = confirmations.match_confirmations(_book_four(), _ext_four(),
                                              tolerance=1.0)
    by_party = recon.set_index("party")

    # code match, SAP leading zeros stripped
    a = by_party.loc["0000200012"]
    assert a["status"] == confirmations.ST_AGREED
    assert a["matched_by"] == "code"
    assert a["confirm_date"] == "2026-03-31"

    # difference of 0.50 is inside the Rs 1 tolerance
    assert by_party.loc["300055"]["status"] == confirmations.ST_AGREED

    # pass-2 name fallback: code on the books, none on the confirmation
    c = by_party.loc["400010"]
    assert c["status"] == confirmations.ST_EXCEPTION
    assert c["matched_by"] == "name"
    assert c["difference"] == pytest.approx(1000.0)

    assert by_party.loc["500020"]["status"] == confirmations.ST_NO_RESPONSE

    stranger = recon[recon["status"] == confirmations.ST_NOT_IN_BOOKS]
    assert stranger["party_name"].tolist() == ["Zeta Ltd"]

    # exceptions sort to the top of the working grid
    assert recon.iloc[0]["party"] == "400010"


def test_stats_coverage_and_values():
    recon = confirmations.match_confirmations(_book_four(), _ext_four(),
                                              tolerance=1.0)
    stats = confirmations.confirmation_stats(recon, tolerance=1.0)
    assert stats["parties"] == 4
    assert stats["responses"] == 3
    assert stats["agreed"] == 2
    assert stats["exceptions"] == 1
    assert stats["no_response"] == 1
    assert stats["not_in_books"] == 1
    assert stats["exception_value"] == pytest.approx(1000.0)
    assert stats["book_total_abs"] == pytest.approx(250000.75)
    assert stats["covered_value_abs"] == pytest.approx(225000.75)
    assert stats["no_response_value_abs"] == pytest.approx(25000.0)
    assert stats["response_rate_pct"] == pytest.approx(75.0)
    assert stats["mirror_hint"] is False


def test_open_items_collapse_to_one_balance_per_party():
    book = _frame([
        {"party": "0000200012", "party_name": "Alpha", "balance": 60000.0},
        {"party": "200012", "party_name": "Alpha", "balance": 40000.0},
    ])
    ext = _frame([{"party": "200012", "party_name": "Alpha",
                   "balance": 100000.0}])
    recon = confirmations.match_confirmations(book, ext)
    assert len(recon) == 1
    assert recon.iloc[0]["book_balance"] == pytest.approx(100000.0)
    assert recon.iloc[0]["status"] == confirmations.ST_AGREED


def test_mirror_image_confirmations_and_invert():
    book = _frame([
        {"party": "V1", "party_name": "Vendor One", "balance": -80000.0},
        {"party": "V2", "party_name": "Vendor Two", "balance": -60000.0},
    ])
    ext = _frame([
        {"party": "V1", "party_name": "Vendor One", "balance": 80000.0},
        {"party": "V2", "party_name": "Vendor Two", "balance": 60000.0},
    ])
    as_stated = confirmations.match_confirmations(book, ext,
                                                  ext_sign="as_stated")
    stats = confirmations.confirmation_stats(as_stated)
    assert stats["exceptions"] == 2
    assert stats["mirror_hint"] is True

    inverted = confirmations.match_confirmations(book, ext,
                                                 ext_sign="invert")
    stats_inv = confirmations.confirmation_stats(inverted)
    assert stats_inv["agreed"] == 2
    assert stats_inv["mirror_hint"] is False


def test_empty_population_stats():
    stats = confirmations.confirmation_stats(pd.DataFrame())
    assert stats["parties"] == 0
    assert stats["mirror_hint"] is False
    empty = confirmations.match_confirmations(_frame([]), _frame([]))
    assert len(empty) == 0


# ----------------------------------------------------------- persistence

@pytest.fixture()
def eid(tmp_path):
    os.environ["AUDIT_TOOL_DATA_DIR"] = str(tmp_path)
    from storage import db
    db.init_db()
    engagement = db.create_engagement("Conf Test", "Kestrel Transmission",
                                      "2025-04-01", "2026-03-31", "MYT",
                                      "tester")
    yield engagement
    os.environ.pop("AUDIT_TOOL_DATA_DIR", None)


def test_import_activate_replace_and_round_trip(eid):
    from storage import db
    mapping = {"party": "p", "party_name": "n", "balance": "b",
               "gl_account": None}
    raw1 = pd.DataFrame({"p": ["0000200012", "300055"],
                         "n": ["Alpha", "Bravo"],
                         "b": ["100000", "50000.75"]})
    clean1, _ = confirmations.normalize_book(raw1, mapping)
    imp1 = confirmations.import_confirmation_sheet(
        eid, AREA, "book", clean1, "book_v1.xlsx", "sha-1", mapping,
        "tester")

    book, ext = confirmations.active_frames(eid, AREA)
    assert len(book) == 2 and len(ext) == 0
    assert book["balance"].sum() == pytest.approx(150000.75)

    raw2 = pd.DataFrame({"p": ["0000200012"], "n": ["Alpha"],
                         "b": ["99000"]})
    clean2, _ = confirmations.normalize_book(raw2, mapping)
    imp2 = confirmations.import_confirmation_sheet(
        eid, AREA, "book", clean2, "book_v2.xlsx", "sha-2", mapping,
        "tester")
    assert imp2 > imp1
    active = db.active_import(eid, confirmations.import_kind("book", AREA))
    assert active["id"] == imp2
    replaced = db.query_one("SELECT status FROM imports WHERE id=?", (imp1,))
    assert replaced["status"] == "replaced"
    book, _ = confirmations.active_frames(eid, AREA)
    assert len(book) == 1

    assert confirmations.areas_with_data(eid) == [AREA]


def test_settings_and_assessments_round_trip(eid):
    settings = confirmations.load_settings(eid, AREA)
    assert settings == confirmations.DEFAULT_SETTINGS

    confirmations.save_settings(eid, AREA,
                                {"tolerance": 5.0, "ext_sign": "invert",
                                 "notes": "payables confirm mirror"},
                                "tester")
    loaded = confirmations.load_settings(eid, AREA)
    assert loaded["tolerance"] == 5.0
    assert loaded["ext_sign"] == "invert"

    recon = confirmations.match_confirmations(_book_four(), _ext_four())
    records = recon.assign(conclusion="Agreed - no exception",
                           remarks="ok").to_dict("records")
    n = confirmations.save_assessments(eid, AREA, records, "tester")
    assert n == len(recon)

    merged = confirmations.attach_assessments(
        recon, confirmations.load_assessments(eid, AREA))
    assert (merged["conclusion"] == "Agreed - no exception").all()
    assert (merged["remarks"] == "ok").all()

    # upsert: change one party's conclusion only
    one = [{"party_key": recon.iloc[0]["party_key"],
            "conclusion": "Misstatement - carry to evaluation",
            "remarks": "difference confirmed as billing error"}]
    confirmations.save_assessments(eid, AREA, one, "tester")
    merged = confirmations.attach_assessments(
        recon, confirmations.load_assessments(eid, AREA))
    assert (merged.iloc[0]["conclusion"]
            == "Misstatement - carry to evaluation")


def test_workpaper_pack_gets_a_confirmation_sheet(eid):
    import io

    from reports import excel_pack

    mapping = {"party": "p", "party_name": "n", "balance": "b",
               "gl_account": None}
    raw = pd.DataFrame({"p": ["0000200012"], "n": ["Alpha Traders"],
                        "b": ["100000"]})
    clean, _ = confirmations.normalize_book(raw, mapping)
    confirmations.import_confirmation_sheet(eid, AREA, "book", clean,
                                            "book.xlsx", "sha-b", mapping,
                                            "tester")

    content = excel_pack.generate_workpaper_pack(
        eid, {"username": "tester", "role": "Partner"})
    xl = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    sheet = [s for s in xl.sheet_names if s.startswith("Conf ")]
    assert sheet, xl.sheet_names
    body = xl.parse(sheet[0], header=None)
    text = body.fillna("").astype(str).to_numpy().ravel()
    assert any("Parties in books" in t for t in text)
    assert any("Alpha Traders" in t for t in text)


def test_confirmations_page_renders_matching_grid(eid):
    """Step 8 end-to-end in AppTest: with a book and an ext sheet imported,
    the matching tab must render its statistics and working grid."""
    from streamlit.testing.v1 import AppTest
    from storage import auth

    auth.create_user("confsmoke", "password1", "Partner")
    user = auth.authenticate("confsmoke", "password1")

    mapping = {"party": "p", "party_name": "n", "balance": "b",
               "gl_account": None}
    book_raw = pd.DataFrame({"p": ["0000200012", "300055"],
                             "n": ["Alpha Traders", "Bravo Supply"],
                             "b": ["100000", "50000"]})
    clean, _ = confirmations.normalize_book(book_raw, mapping)
    confirmations.import_confirmation_sheet(eid, AREA, "book", clean,
                                            "book.xlsx", "sha-b", mapping,
                                            "tester")
    ext_raw = pd.DataFrame({"p": ["200012"], "n": ["Alpha Traders"],
                            "b": ["100000"]})
    clean_e, _ = confirmations.normalize_ext(ext_raw, mapping)
    confirmations.import_confirmation_sheet(eid, AREA, "ext", clean_e,
                                            "ext.xlsx", "sha-e", mapping,
                                            "tester")

    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
    at.session_state["user"] = user
    at.session_state["engagement_id"] = eid
    at.run(timeout=60)
    assert not at.exception
    at.radio[0].set_value("8. Balance confirmations")
    at.run(timeout=120)
    assert not at.exception, at.exception

    labels = {m.label: str(m.value) for m in at.metric}
    assert labels.get("Parties in books") == "2"
    assert labels.get("Responses") == "1"
    assert labels.get("Agreed") == "1"
    assert labels.get("No response") == "1"
