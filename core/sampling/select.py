"""Sample selection methods per SA 530: simple random (with/without
replacement), systematic, stratified by value bands, and monetary unit
sampling (MUS).

Every method takes an explicit integer seed and sorts the population into a
documented canonical order first, so any selection can be exactly regenerated
for the audit working papers. The RNG is numpy's PCG64 via
``numpy.random.default_rng(seed)``.
"""

import hashlib

import numpy as np
import pandas as pd

SORT_COLS = ["date", "doc_no", "row_id"]  # documented canonical population order


def canonical_sort(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in SORT_COLS if c in df.columns]
    out = df.sort_values(cols, kind="mergesort") if cols else df
    return out.reset_index(drop=True)


def dataset_hash(df: pd.DataFrame) -> str:
    """SHA-256 over identifying columns; ties a selection to its population."""
    cols = [c for c in ["row_id", "date", "doc_no", "account", "amount_abs"]
            if c in df.columns]
    if not cols:
        cols = list(df.columns)
    d = canonical_sort(df)
    payload = "\n".join("|".join(map(str, row))
                        for row in d[cols].itertuples(index=False))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_seed(master_seed, *parts) -> int:
    """Deterministic 32-bit seed derived from the engagement master seed."""
    text = "|".join(str(p) for p in (master_seed, *parts))
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big")


def srs(df: pd.DataFrame, n: int, seed: int, replace: bool = False):
    """Simple random sampling with or without replacement."""
    df = canonical_sort(df)
    pop = len(df)
    if pop == 0:
        raise ValueError("population is empty")
    if n <= 0:
        raise ValueError("sample size must be positive")
    census = False
    if not replace and n >= pop:
        n, census = pop, True
    rng = np.random.default_rng(seed)
    if replace:
        draws = rng.choice(pop, size=n, replace=True)
        counts = np.bincount(draws, minlength=pop)
        sel = np.flatnonzero(counts)
        out = df.iloc[sel].copy()
        out["times_selected"] = counts[sel]
    else:
        sel = np.sort(rng.choice(pop, size=n, replace=False))
        out = df.iloc[sel].copy()
        out["times_selected"] = 1
    info = {"method": "srs_wr" if replace else "srs", "seed": int(seed),
            "population": int(pop), "n_target": int(n),
            "n_selected": int(len(out)), "replace": replace, "census": census,
            "sort_order": SORT_COLS}
    return out, info


def systematic(df: pd.DataFrame, n: int, seed: int):
    """Systematic selection: fixed interval, seeded random start."""
    df = canonical_sort(df)
    pop = len(df)
    if pop == 0:
        raise ValueError("population is empty")
    n = min(int(n), pop)
    if n <= 0:
        raise ValueError("sample size must be positive")
    interval = pop // n
    rng = np.random.default_rng(seed)
    start = int(rng.integers(1, interval + 1))
    pos = (start - 1) + interval * np.arange(n)
    out = df.iloc[pos].copy()
    out["times_selected"] = 1
    info = {"method": "systematic", "seed": int(seed), "population": int(pop),
            "n_target": int(n), "n_selected": int(len(out)),
            "interval": int(interval), "random_start": int(start),
            "sort_order": SORT_COLS}
    return out, info


def mus(df: pd.DataFrame, seed: int, n: int | None = None,
        interval: float | None = None, amount_col: str = "amount_abs"):
    """Monetary unit sampling: fixed-interval selection over cumulative value.

    Items with book value >= the interval are mathematically guaranteed to be
    selected (top stratum) and are examined 100%.
    """
    df = canonical_sort(df)
    if len(df) == 0:
        raise ValueError("population is empty")
    amounts = df[amount_col].to_numpy(dtype=float)
    if (amounts <= 0).any():
        raise ValueError("MUS requires strictly positive amounts; "
                         "zero and contra items must be excluded first")
    cum = np.cumsum(amounts)
    bv = float(cum[-1])
    if n is not None and n > 0:
        j = bv / int(n)
    elif interval and interval > 0:
        j = float(interval)
    else:
        raise ValueError("provide a sample size n or a sampling interval")
    rng = np.random.default_rng(seed)
    start = float(rng.uniform(0.0, j))
    hits = np.arange(start, bv, j)
    idx = np.searchsorted(cum, hits, side="left")
    uniq, counts = np.unique(idx, return_counts=True)
    out = df.iloc[uniq].copy()
    out["times_selected"] = counts
    out["is_top_stratum"] = amounts[uniq] >= j
    info = {"method": "mus", "seed": int(seed), "population": int(len(df)),
            "book_value": bv, "interval": float(j),
            "random_start": float(start), "hits": int(len(hits)),
            "n_selected": int(len(out)),
            "top_stratum_items": int(out["is_top_stratum"].sum()),
            "sort_order": SORT_COLS}
    return out, info


def auto_band_boundaries(amounts, n_bands: int = 4) -> list:
    """Cut points that give bands of roughly equal cumulative value."""
    a = np.sort(np.asarray(amounts, dtype=float))
    if len(a) == 0:
        return []
    cum = np.cumsum(a)
    total = cum[-1]
    bounds = []
    for i in range(1, max(2, int(n_bands))):
        target = total * i / n_bands
        pos = min(int(np.searchsorted(cum, target)), len(a) - 1)
        bounds.append(float(a[pos]))
    return sorted(set(bounds))


def _allocate(n_total: int, weights, caps, min_each: int = 1) -> np.ndarray:
    """Cap-aware proportional allocation of n_total across bands."""
    weights = np.asarray(weights, dtype=float)
    caps = np.asarray(caps, dtype=int)
    k = len(caps)
    alloc = np.zeros(k, dtype=int)
    n_total = int(min(n_total, caps.sum()))
    if n_total <= 0:
        return alloc
    nonempty = caps > 0
    if min_each and n_total >= int(nonempty.sum()):
        alloc[nonempty] = np.minimum(min_each, caps[nonempty])
    while alloc.sum() < n_total:
        room = caps - alloc
        w = np.where(room > 0, np.maximum(weights, 1e-12), 0.0)
        if w.sum() <= 0:
            break
        remaining = n_total - int(alloc.sum())
        raw = remaining * w / w.sum()
        add = np.minimum(np.floor(raw).astype(int), room)
        if add.sum() == 0:
            for i in np.argsort(-w):
                if alloc.sum() >= n_total:
                    break
                if room[i] > 0:
                    alloc[i] += 1
            continue
        alloc += add
    return alloc


def stratified(df: pd.DataFrame, n_total: int, seed: int,
               amount_col: str = "amount_abs", boundaries: list | None = None,
               n_bands: int = 4, allocation: str = "value"):
    """Stratified random sampling by value bands.

    Bands are defined by ascending boundary amounts (auto-computed for roughly
    equal cumulative value if not supplied). Allocation of the total sample is
    proportional to band value (default) or band count; selection within each
    band is simple random with a seed derived from the master seed.
    """
    df = canonical_sort(df)
    if len(df) == 0:
        raise ValueError("population is empty")
    amounts = df[amount_col].to_numpy(dtype=float)
    if boundaries is None:
        boundaries = auto_band_boundaries(amounts, n_bands)
    boundaries = sorted(float(b) for b in boundaries)
    band = np.searchsorted(np.asarray(boundaries), amounts, side="right")
    nb = len(boundaries) + 1
    counts = np.bincount(band, minlength=nb)
    values = np.bincount(band, weights=amounts, minlength=nb)
    weights = values if allocation == "value" else counts.astype(float)
    alloc = _allocate(n_total, weights, counts)
    picks = []
    per_band = []
    for b in range(nb):
        idx_b = np.flatnonzero(band == b)
        take = int(alloc[b])
        if take >= len(idx_b) and len(idx_b) > 0:
            chosen = idx_b
        elif take > 0:
            rng = np.random.default_rng(derive_seed(seed, "band", b))
            chosen = np.sort(rng.choice(idx_b, size=take, replace=False))
        else:
            chosen = np.array([], dtype=int)
        if len(chosen):
            picks.append(chosen)
        lo = boundaries[b - 1] if b > 0 else 0.0
        hi = boundaries[b] if b < len(boundaries) else None
        per_band.append({"band": b + 1, "from": lo, "to": hi,
                         "items": int(counts[b]), "value": float(values[b]),
                         "selected": int(len(chosen)),
                         "census": bool(len(idx_b) > 0 and take >= len(idx_b))})
    sel = np.sort(np.concatenate(picks)) if picks else np.array([], dtype=int)
    out = df.iloc[sel].copy()
    out["band"] = band[sel] + 1
    out["times_selected"] = 1
    info = {"method": "stratified", "seed": int(seed),
            "population": int(len(df)), "n_target": int(n_total),
            "n_selected": int(len(out)), "boundaries": boundaries,
            "allocation": allocation, "per_band": per_band,
            "sort_order": SORT_COLS}
    return out, info
