import math

import pytest

from core.sampling.sizes import attribute_sample_size, binom_cdf, mus_sample_size


def test_attribute_matches_published_table_zero_expected():
    # 95% confidence, 5% tolerable, 0% expected -> 59 (published table value)
    assert attribute_sample_size(0.95, 0.05, 0.0)["n"] == 59


def test_attribute_90_10_0():
    assert attribute_sample_size(0.90, 0.10, 0.0)["n"] == 22


def test_attribute_95_5_1():
    # 95% confidence, 5% tolerable, 1% expected -> 93 (published table value)
    res = attribute_sample_size(0.95, 0.05, 0.01)
    assert res["n"] == 93
    assert res["allowed_deviations"] == 1


def test_attribute_fpc():
    res = attribute_sample_size(0.95, 0.05, 0.0, population_size=500)
    assert res["n_with_fpc"] == math.ceil(59 / (1 + 59 / 500))


def test_attribute_invalid():
    with pytest.raises(ValueError):
        attribute_sample_size(0.95, 0.05, 0.05)
    with pytest.raises(ValueError):
        attribute_sample_size(0.95, 0.0, 0.0)


def test_binom_cdf_boundary():
    # (1 - 0.05)^59 just below 0.05, ^58 just above
    assert binom_cdf(0, 59, 0.05) < 0.05
    assert binom_cdf(0, 58, 0.05) > 0.05


def test_mus_worked_example():
    # BV 50,00,000; TM 2,50,000; EM 50,000; 95% -> n = 89
    res = mus_sample_size(5_000_000, 250_000, 50_000, 0.95)
    assert res["n"] == 89
    assert res["interval"] == pytest.approx(5_000_000 / 89)


def test_mus_expected_too_high():
    with pytest.raises(ValueError):
        # EM x EF (40,000 x 1.6 = 64,000) exceeds TM 50,000
        mus_sample_size(1_000_000, 50_000, 40_000, 0.95)
