import math

import pytest

from core.sampling.factors import expansion_factor, poisson_cdf, reliability_factor

# Published AICPA/ICAI sampling-table values (rounded to 2 dp).
PUBLISHED_RF = [
    (0.95, 0, 3.00),
    (0.95, 1, 4.75),
    (0.95, 2, 6.30),
    (0.95, 3, 7.76),
    (0.90, 0, 2.30),
    (0.90, 1, 3.89),
    (0.99, 0, 4.61),
]


@pytest.mark.parametrize("confidence,k,expected", PUBLISHED_RF)
def test_reliability_factors_match_published_tables(confidence, k, expected):
    assert reliability_factor(confidence, k) == pytest.approx(expected, abs=0.01)


def test_reliability_factor_is_poisson_inverse():
    lam = reliability_factor(0.95, 2)
    assert poisson_cdf(2, lam) == pytest.approx(0.05, abs=1e-9)


def test_poisson_cdf_zero_errors():
    assert poisson_cdf(0, 3.0) == pytest.approx(math.exp(-3.0))


def test_expansion_factors():
    assert expansion_factor(0.95) == 1.6
    assert expansion_factor(0.90) == 1.5
    assert expansion_factor(0.99) == 1.9


def test_invalid_inputs():
    with pytest.raises(ValueError):
        reliability_factor(1.5, 0)
    with pytest.raises(ValueError):
        reliability_factor(0.95, -1)
