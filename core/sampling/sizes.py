"""Sample size determination per SA 530.

Attribute sizes use the exact binomial distribution, which reproduces the
published AICPA/ICAI statistical sample size tables (e.g. 95% confidence,
5% tolerable rate, 0% expected -> 59). MUS sizes use the standard
reliability-factor formula.
"""

import math

from .factors import expansion_factor, reliability_factor


def _log_binom_pmf(i: int, n: int, p: float) -> float:
    return (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p))


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    k = min(int(k), n)
    return min(1.0, sum(math.exp(_log_binom_pmf(i, n, p)) for i in range(k + 1)))


def _smallest_n(k: int, tolerable_rate: float, confidence: float) -> int:
    """Smallest n such that observing <= k deviations still supports
    'true rate <= tolerable_rate' at the given confidence."""
    target = 1.0 - confidence
    hi = max(k + 1, int(math.ceil(reliability_factor(confidence, k) / tolerable_rate)))
    while binom_cdf(k, hi, tolerable_rate) > target:
        hi *= 2
        if hi > 10_000_000:
            raise ValueError("required sample size is impractically large")
    lo = k + 1
    while lo < hi:
        mid = (lo + hi) // 2
        if binom_cdf(k, mid, tolerable_rate) <= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def attribute_sample_size(confidence: float, tolerable_rate: float,
                          expected_rate: float = 0.0,
                          population_size: int | None = None) -> dict:
    """Attribute (tests of controls / compliance) sample size.

    Iterates over the number of deviations the plan can absorb (k) until the
    expected deviations in a sample of the resulting size do not exceed k --
    this is how the published tables are constructed.
    """
    if not 0.0 < tolerable_rate < 1.0:
        raise ValueError("tolerable rate must be between 0 and 1")
    if expected_rate < 0.0 or expected_rate >= tolerable_rate:
        raise ValueError("expected rate must be >= 0 and below the tolerable rate")
    for k in range(0, 2000):
        n = _smallest_n(k, tolerable_rate, confidence)
        if n * expected_rate <= k + 1e-9:
            out = {
                "n": n,
                "allowed_deviations": k,
                "confidence": confidence,
                "tolerable_rate": tolerable_rate,
                "expected_rate": expected_rate,
            }
            if population_size and population_size > 0:
                out["n_with_fpc"] = math.ceil(n / (1.0 + n / population_size))
            return out
    raise ValueError("could not determine a sample size; check the rates")


def mus_sample_size(book_value: float, tolerable_misstatement: float,
                    expected_misstatement: float = 0.0,
                    confidence: float = 0.95) -> dict:
    """Monetary unit sampling size: n = BV * RF / (TM - EM * EF)."""
    if book_value <= 0:
        raise ValueError("book value must be positive")
    if tolerable_misstatement <= 0:
        raise ValueError("tolerable misstatement must be positive")
    if expected_misstatement < 0:
        raise ValueError("expected misstatement cannot be negative")
    rf0 = reliability_factor(confidence, 0)
    ef = expansion_factor(confidence)
    denom = tolerable_misstatement - expected_misstatement * ef
    if denom <= 0:
        raise ValueError(
            "expected misstatement is too close to tolerable misstatement; "
            "sampling is not appropriate - extend substantive procedures instead")
    n = math.ceil(book_value * rf0 / denom)
    return {
        "n": n,
        "interval": book_value / n,
        "rf0": rf0,
        "expansion_factor": ef,
        "book_value": book_value,
        "tolerable_misstatement": tolerable_misstatement,
        "expected_misstatement": expected_misstatement,
        "confidence": confidence,
    }
