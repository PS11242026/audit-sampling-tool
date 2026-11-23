import numpy as np
import pandas as pd
import pytest

from core.sampling import select


def make_pop(n=1000, seed=7):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "row_id": np.arange(n),
        "date": (pd.Timestamp("2025-04-01")
                 + pd.to_timedelta(rng.integers(0, 360, n), unit="D")),
        "doc_no": [f"DOC{i:06d}" for i in range(n)],
        "account": "71101",
        "amount_abs": np.round(rng.lognormal(10, 1, n), 2),
    })


def test_srs_reproducible_and_unique():
    pop = make_pop()
    s1, i1 = select.srs(pop, 60, seed=12345)
    s2, i2 = select.srs(pop, 60, seed=12345)
    assert list(s1["row_id"]) == list(s2["row_id"])
    assert len(s1) == 60 == i1["n_selected"]
    assert s1["row_id"].is_unique
    s3, _ = select.srs(pop, 60, seed=54321)
    assert list(s3["row_id"]) != list(s1["row_id"])


def test_srs_with_replacement_counts():
    pop = make_pop(50)
    s, info = select.srs(pop, 80, seed=1, replace=True)
    assert int(s["times_selected"].sum()) == 80
    assert info["replace"] is True


def test_srs_census_when_n_exceeds_population():
    pop = make_pop(30)
    s, info = select.srs(pop, 100, seed=1)
    assert len(s) == 30
    assert info["census"] is True


def test_systematic_interval_and_count():
    pop = make_pop(1000)
    s, info = select.systematic(pop, 50, seed=99)
    assert len(s) == 50
    assert info["interval"] == 20
    assert 1 <= info["random_start"] <= 20
    s2, _ = select.systematic(pop, 50, seed=99)
    assert list(s2["row_id"]) == list(s["row_id"])


def test_mus_selects_all_top_stratum_and_reproduces():
    pop = make_pop(500, seed=3)
    # plant three very large items that must exceed any interval
    big_ids = [10, 200, 499]
    pop.loc[pop["row_id"].isin(big_ids), "amount_abs"] = pop["amount_abs"].sum()
    s1, i1 = select.mus(pop, seed=777, n=40)
    s2, _ = select.mus(pop, seed=777, n=40)
    assert list(s1["row_id"]) == list(s2["row_id"])
    for rid in big_ids:
        assert rid in set(s1["row_id"])
    top = s1[s1["is_top_stratum"]]
    assert set(big_ids).issubset(set(top["row_id"]))
    assert int(s1["times_selected"].sum()) == i1["hits"] == 40
    # every selected lower-stratum item selected exactly once
    lower = s1[~s1["is_top_stratum"]]
    assert (lower["times_selected"] == 1).all()


def test_mus_rejects_nonpositive_amounts():
    pop = make_pop(10)
    pop.loc[0, "amount_abs"] = 0.0
    with pytest.raises(ValueError):
        select.mus(pop, seed=1, n=5)


def test_stratified_partition_and_allocation():
    pop = make_pop(800, seed=11)
    s, info = select.stratified(pop, 60, seed=42, n_bands=4)
    assert len(s) == 60 == info["n_selected"]
    assert s["row_id"].is_unique
    per_band = info["per_band"]
    assert sum(b["items"] for b in per_band) == 800
    assert sum(b["selected"] for b in per_band) == 60
    for b in per_band:
        assert b["selected"] <= b["items"]
    s2, _ = select.stratified(pop, 60, seed=42, n_bands=4)
    assert list(s2["row_id"]) == list(s["row_id"])


def test_stratified_census_band():
    pop = make_pop(100, seed=5)
    # one giant item forms its own top band and must be censused
    pop.loc[pop["row_id"] == 7, "amount_abs"] = 1e12
    s, info = select.stratified(pop, 20, seed=8, n_bands=4)
    assert 7 in set(s["row_id"])


def test_dataset_hash_stable_under_row_order():
    pop = make_pop(200)
    shuffled = pop.sample(frac=1.0, random_state=1)
    assert select.dataset_hash(pop) == select.dataset_hash(shuffled)
    changed = pop.copy()
    changed.loc[0, "amount_abs"] += 0.01
    assert select.dataset_hash(changed) != select.dataset_hash(pop)


def test_derive_seed_deterministic():
    a = select.derive_seed(123, "Repairs", 1)
    b = select.derive_seed(123, "Repairs", 1)
    c = select.derive_seed(123, "Repairs", 2)
    assert a == b != c
    assert 0 <= a < 2 ** 32
