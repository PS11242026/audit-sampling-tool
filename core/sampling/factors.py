"""Poisson reliability factors and expansion factors for audit sampling.

The reliability factor RF(C, k) is the value lambda solving

    sum_{i=0..k} exp(-lambda) * lambda^i / i!  =  1 - C

i.e. the upper limit of a Poisson mean such that observing k or fewer
errors still leaves (1 - C) probability. Computed exactly by bisection
(no scipy dependency) so the published AICPA/ICAI table values
(3.00, 4.75, 6.30 ... at 95% confidence) are reproduced within +/- 0.01.
"""

import math

# AICPA expansion factors for expected misstatement in MUS sizing,
# keyed by confidence level (1 - risk of incorrect acceptance).
EXPANSION_FACTORS = {
    0.50: 1.00, 0.63: 1.15, 0.70: 1.20, 0.75: 1.25,
    0.80: 1.30, 0.85: 1.40, 0.90: 1.50, 0.95: 1.60, 0.99: 1.90,
}


def poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) for X ~ Poisson(lam)."""
    if lam <= 0:
        return 1.0
    term = math.exp(-lam)
    total = term
    for i in range(1, int(k) + 1):
        term *= lam / i
        total += term
    return min(total, 1.0)


def reliability_factor(confidence: float, k: int = 0) -> float:
    """Poisson reliability factor for k expected/observed misstatements."""
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")
    if k < 0:
        raise ValueError("k must be >= 0")
    target = 1.0 - confidence
    lo, hi = 0.0, 8.0 + 2.0 * k
    while poisson_cdf(k, hi) > target:
        hi *= 2.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if poisson_cdf(k, mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def expansion_factor(confidence: float) -> float:
    """Expansion factor for expected misstatement (nearest table entry)."""
    key = min(EXPANSION_FACTORS, key=lambda c: abs(c - confidence))
    return EXPANSION_FACTORS[key]
