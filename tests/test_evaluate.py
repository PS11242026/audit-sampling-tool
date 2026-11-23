import pandas as pd
import pytest

from core.sampling.evaluate import (attribute_evaluate, difference_projection,
                                    mus_evaluate, ratio_projection)
from core.sampling.factors import reliability_factor


def test_mus_evaluate_stringer_bound():
    sample = pd.DataFrame({
        "book_value":    [1000.0, 2000.0, 3000.0, 50000.0],
        "audited_value": [500.0, 1600.0, 3000.0, 49000.0],
        "is_top_stratum": [False, False, False, True],
    })
    j = 10_000.0
    res = mus_evaluate(sample, interval=j, confidence=0.95,
                       tolerable_misstatement=60_000.0)

    # taintings 0.5 and 0.2 -> projected overstatement 7,000
    assert res["projected_over"] == pytest.approx(7000.0)
    assert res["top_stratum_over"] == pytest.approx(1000.0)

    rf0 = reliability_factor(0.95, 0)
    rf1 = reliability_factor(0.95, 1)
    rf2 = reliability_factor(0.95, 2)
    expected_bp = rf0 * j
    expected_ia = 0.5 * j * (rf1 - rf0 - 1) + 0.2 * j * (rf2 - rf1 - 1)
    assert res["basic_precision"] == pytest.approx(expected_bp)
    assert res["incremental_allowance"] == pytest.approx(expected_ia)
    assert res["upper_misstatement_limit"] == pytest.approx(
        1000.0 + 7000.0 + expected_bp + expected_ia)
    # sanity vs hand-computed table figure (~42.8k) and conclusion
    assert 42_000 < res["upper_misstatement_limit"] < 43_500
    assert res["most_likely_misstatement"] == pytest.approx(8000.0)
    assert res["acceptable"] is True


def test_mus_evaluate_understatement_reported_separately():
    sample = pd.DataFrame({
        "book_value":    [1000.0, 2000.0],
        "audited_value": [1500.0, 2000.0],
        "is_top_stratum": [False, False],
    })
    res = mus_evaluate(sample, interval=5000.0, confidence=0.95,
                       tolerable_misstatement=50_000.0)
    assert res["projected_under"] == pytest.approx(0.5 * 5000.0)
    assert res["projected_over"] == 0.0
    assert res["most_likely_misstatement"] == pytest.approx(-2500.0)


def test_mus_taint_capped_at_100_percent():
    sample = pd.DataFrame({
        "book_value":    [1000.0],
        "audited_value": [-500.0],   # misstatement 1,500 > book value
        "is_top_stratum": [False],
    })
    res = mus_evaluate(sample, interval=5000.0, confidence=0.95,
                       tolerable_misstatement=50_000.0)
    assert res["projected_over"] == pytest.approx(5000.0)  # taint capped at 1.0


def test_ratio_and_difference_projection():
    assert ratio_projection(1_000_000, 100_000, 5_000) == pytest.approx(50_000)
    assert difference_projection(2000, 100, 5_000) == pytest.approx(100_000)
    assert ratio_projection(1_000_000, 0, 5_000) == 0.0


def test_attribute_evaluate():
    ok = attribute_evaluate(59, 0, 0.95, 0.05)
    assert ok["achieved_upper_limit"] == pytest.approx(1 - 0.05 ** (1 / 59), abs=1e-6)
    assert ok["acceptable"] is True
    bad = attribute_evaluate(59, 1, 0.95, 0.05)
    assert bad["acceptable"] is False
    assert bad["achieved_upper_limit"] > 0.05
