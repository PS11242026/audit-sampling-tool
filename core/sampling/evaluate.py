"""Sample evaluation per SA 530: projection of misstatements to the population.

- MUS: Stringer-bound style upper misstatement limit for overstatements
  (projected misstatement + basic precision + incremental allowance),
  understatements reported separately.
- Classical samples: ratio and difference projections.
- Attribute samples: achieved upper deviation limit (exact binomial).
"""

import pandas as pd

from .factors import reliability_factor
from .sizes import binom_cdf


def mus_evaluate(sample: pd.DataFrame, interval: float, confidence: float,
                 tolerable_misstatement: float,
                 book_col: str = "book_value",
                 audited_col: str = "audited_value",
                 top_col: str = "is_top_stratum") -> dict:
    df = sample
    book = df[book_col].astype(float)
    audited = df[audited_col].astype(float)
    mis = book - audited  # overstatement positive
    if top_col in df.columns:
        top = df[top_col].astype(bool)
    else:
        top = pd.Series(False, index=df.index)
    lower = ~top

    top_over = float(mis[top & (mis > 0)].sum())
    top_under = float(-mis[top & (mis < 0)].sum())

    over_mask = lower & (mis > 0) & (book > 0)
    taints = (mis[over_mask] / book[over_mask]).clip(upper=1.0)
    projected_over = float((taints * interval).sum())

    under_mask = lower & (mis < 0) & (book > 0)
    under_taints = -mis[under_mask] / book[under_mask]
    projected_under = float((under_taints * interval).sum())

    rf0 = reliability_factor(confidence, 0)
    basic_precision = rf0 * interval

    incremental = 0.0
    rf_prev = rf0
    for rank, t in enumerate(sorted(taints.tolist(), reverse=True), start=1):
        rf_i = reliability_factor(confidence, rank)
        incremental += t * interval * (rf_i - rf_prev - 1.0)
        rf_prev = rf_i

    uml = top_over + projected_over + basic_precision + incremental
    most_likely = (top_over - top_under) + projected_over - projected_under
    return {
        "interval": float(interval),
        "confidence": float(confidence),
        "rf0": rf0,
        "items_tested": int(len(df)),
        "errors_lower_over": int(over_mask.sum()),
        "errors_lower_under": int(under_mask.sum()),
        "top_stratum_over": top_over,
        "top_stratum_under": top_under,
        "projected_over": projected_over,
        "projected_under": projected_under,
        "basic_precision": basic_precision,
        "incremental_allowance": incremental,
        "upper_misstatement_limit": uml,
        "most_likely_misstatement": most_likely,
        "tolerable_misstatement": float(tolerable_misstatement),
        "acceptable": bool(uml <= tolerable_misstatement),
    }


def ratio_projection(population_book: float, sample_book: float,
                     sample_misstatement: float) -> float:
    """Projected misstatement = sample error rate (by value) x population value."""
    if not sample_book:
        return 0.0
    return float(sample_misstatement / sample_book * population_book)


def difference_projection(population_count: int, sample_count: int,
                          sample_misstatement: float) -> float:
    """Projected misstatement = mean error per item x population count."""
    if not sample_count:
        return 0.0
    return float(sample_misstatement / sample_count * population_count)


def attribute_evaluate(n: int, deviations: int, confidence: float,
                       tolerable_rate: float) -> dict:
    """Achieved upper deviation limit: the largest population rate consistent
    with the observed deviations at the given confidence (exact binomial)."""
    if n <= 0:
        raise ValueError("sample size must be positive")
    k = int(deviations)
    target = 1.0 - confidence
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if binom_cdf(k, n, mid) > target:
            lo = mid
        else:
            hi = mid
    achieved = hi
    return {"n": int(n), "deviations": k, "sample_rate": k / n,
            "achieved_upper_limit": achieved,
            "tolerable_rate": float(tolerable_rate),
            "confidence": float(confidence),
            "acceptable": bool(achieved <= tolerable_rate)}
