"""SA 315 risk assessment: factor-based scoring per category, configurable
100%-vs-sample thresholds, and the analysis run that splits every category
into (a) items for 100% verification and (b) a sampling population.

Strategy rules (configurable):
  final score >= full_min   -> FULL (or HYBRID when a category cutoff is set:
                               items >= cutoff are tested 100%, the remainder
                               is sampled by the preferred method)
  sample_min <= score < full_min -> SAMPLE (preferred method, MUS by default)
  score < sample_min        -> SAMPLE_LOW (small random sample, floor n)

Regardless of score, individually significant items (>= the SA 320 cutoff)
and abnormal-side (contra) entries are always routed to 100% verification.
"""

import copy
import json

import pandas as pd

from core import anomalies, materiality
from core.categorizer import (CAT_CAPEX, CAT_DTAX, CAT_EMP, CAT_OH,
                              CAT_OI_FEES, CAT_OI_INT, CAT_OI_MISC,
                              CAT_ONEOFF, CAT_RM, CAT_SPARES, CAT_TRANS,
                              CAT_WHEEL, INCOME_CATEGORIES, UNCATEGORIZED)
from storage import db

CONTROL_SCORES = {"Weak": 10, "Moderate": 6, "Strong": 2}
COMPLEXITY_SCORES = {"High": 10, "Medium": 6, "Low": 2}
METHODS = ["mus", "stratified", "systematic", "random", "full"]
CUTOFF_MODES = ["none", "amount", "pct_pm"]

DEFAULT_THRESHOLDS = {"full_min": 8.0, "sample_min": 4.0, "low_floor_n": 25}

DEFAULT_FACTOR_WEIGHTS = {
    "size": 2.0,
    "prior_qualification": 2.0,
    "regulatory": 1.5,
    "control": 1.5,
    "complexity": 1.0,
    "volume": 0.5,
    "new_oneoff": 1.5,
}


def _cat(manual_weight=None, control="Moderate", complexity="Medium",
         regulatory=False, prior_qualified=False, new_oneoff=False,
         cutoff_mode="none", cutoff_value=0.0, preferred_method="mus",
         notes=""):
    return {"manual_weight": manual_weight, "control": control,
            "complexity": complexity, "regulatory": regulatory,
            "prior_qualified": prior_qualified, "new_oneoff": new_oneoff,
            "cutoff_mode": cutoff_mode, "cutoff_value": cutoff_value,
            "preferred_method": preferred_method, "notes": notes}


# Default template per the engagement risk memorandum: prior-year
# qualifications (spares/Ind AS 16, R&M, deferred tax) and SERC-regulated
# revenue drive the weights.
DEFAULT_CATEGORY_SETTINGS = {
    CAT_TRANS: _cat(10, complexity="High", regulatory=True,
                    preferred_method="full",
                    notes="Regulated, formula-driven; verify 100% against "
                          "SERC tariff order and billing schedule"),
    CAT_WHEEL: _cat(10, complexity="High", regulatory=True,
                    preferred_method="full",
                    notes="Regulated; verify against approved wheeling rates"),
    CAT_SPARES: _cat(9, complexity="High", prior_qualified=True,
                     preferred_method="full",
                     notes="Prior-year qualification: Ind AS 16 spares "
                           "(inventory vs PPE classification)"),
    CAT_DTAX: _cat(9, complexity="High", prior_qualified=True,
                   preferred_method="full",
                   notes="Prior-year qualification area"),
    CAT_ONEOFF: _cat(9, complexity="High", new_oneoff=True,
                     preferred_method="full",
                     notes="New accounts / one-off items verified "
                           "individually"),
    CAT_RM: _cat(8, prior_qualified=True, cutoff_mode="pct_pm",
                 cutoff_value=25.0, preferred_method="mus",
                 notes="Prior-year dispute; significant items 100%, "
                       "remainder sampled (MUS)"),
    CAT_CAPEX: _cat(7, complexity="High", cutoff_mode="pct_pm",
                    cutoff_value=50.0, preferred_method="stratified",
                    notes="Compare with capital project approvals"),
    CAT_OI_FEES: _cat(6, preferred_method="stratified",
                      notes="Ind AS 115 recognition timing; top band 100%"),
    CAT_OI_INT: _cat(6, preferred_method="stratified",
                     notes="Ind AS 109; recompute interest on major deposits"),
    CAT_OI_MISC: _cat(5, preferred_method="stratified"),
    CAT_EMP: _cat(5, control="Strong", complexity="Low",
                  preferred_method="systematic",
                  notes="Routine, homogeneous; systematic sampling plus "
                        "monthly analytics"),
    CAT_OH: _cat(3, complexity="Low", preferred_method="random"),
    UNCATEGORIZED: _cat(9, complexity="High", new_oneoff=True,
                        preferred_method="full",
                        notes="Unmapped items are high risk until "
                              "classified"),
}


def default_config() -> dict:
    return {"thresholds": dict(DEFAULT_THRESHOLDS),
            "factor_weights": dict(DEFAULT_FACTOR_WEIGHTS),
            "categories": copy.deepcopy(DEFAULT_CATEGORY_SETTINGS)}


def ensure_default_config(engagement_id: int) -> None:
    if not db.query_one("SELECT engagement_id FROM risk_config WHERE "
                        "engagement_id=?", (engagement_id,)):
        db.execute("INSERT INTO risk_config (engagement_id, config_json, "
                   "updated_by, updated_at) VALUES (?,?,?,?)",
                   (engagement_id, json.dumps(default_config()), "system",
                    db.now()))


def load_config(engagement_id: int) -> dict:
    row = db.query_one("SELECT config_json FROM risk_config WHERE "
                       "engagement_id=?", (engagement_id,))
    cfg = json.loads(row["config_json"]) if row else default_config()
    base = default_config()
    for key in ("thresholds", "factor_weights"):
        merged = base[key]
        merged.update(cfg.get(key, {}))
        cfg[key] = merged
    cats = base["categories"]
    for name, settings in cfg.get("categories", {}).items():
        merged = dict(_cat())
        merged.update(cats.get(name, {}))
        merged.update(settings)
        cats[name] = merged
    cfg["categories"] = cats
    return cfg


def save_config(engagement_id: int, cfg: dict, actor: str) -> None:
    db.execute(
        "INSERT INTO risk_config (engagement_id, config_json, updated_by, "
        "updated_at) VALUES (?,?,?,?) ON CONFLICT(engagement_id) DO UPDATE "
        "SET config_json=excluded.config_json, updated_by=excluded.updated_by, "
        "updated_at=excluded.updated_at",
        (engagement_id, json.dumps(cfg), actor, db.now()))


# ------------------------------------------------------------------ scoring

def size_score(total_abs: float, pm: float) -> int:
    if pm <= 0:
        return 6
    ratio = total_abs / pm
    if ratio >= 1.0:
        return 10
    if ratio >= 0.5:
        return 8
    if ratio >= 0.1:
        return 6
    if ratio >= 0.02:
        return 4
    return 2


def volume_score(count: int) -> int:
    if count >= 5000:
        return 8
    if count >= 1000:
        return 6
    if count >= 100:
        return 4
    return 2


def computed_score(cat_cfg: dict, total_abs: float, count: int, pm: float,
                   factor_weights: dict):
    scores = {
        "size": size_score(total_abs, pm),
        "prior_qualification": 10 if cat_cfg.get("prior_qualified") else 0,
        "regulatory": 10 if cat_cfg.get("regulatory") else 0,
        "control": CONTROL_SCORES.get(cat_cfg.get("control"), 6),
        "complexity": COMPLEXITY_SCORES.get(cat_cfg.get("complexity"), 6),
        "volume": volume_score(count),
        "new_oneoff": 10 if cat_cfg.get("new_oneoff") else 0,
    }
    wsum = sum(float(factor_weights.get(f, 0)) for f in scores) or 1.0
    raw = sum(scores[f] * float(factor_weights.get(f, 0)) for f in scores) / wsum
    score = round(min(10.0, max(1.0, raw)), 2)
    breakdown = {f: {"score": scores[f],
                     "weight": float(factor_weights.get(f, 0))}
                 for f in scores}
    return score, breakdown


def resolve_cutoff(cat_cfg: dict, pm: float):
    mode = cat_cfg.get("cutoff_mode", "none")
    value = float(cat_cfg.get("cutoff_value") or 0)
    if mode == "amount" and value > 0:
        return value
    if mode == "pct_pm" and value > 0 and pm > 0:
        return pm * value / 100.0
    return None


def _append_reason(reasons: pd.Series, mask, text: str) -> pd.Series:
    mask = pd.Series(mask, index=reasons.index).fillna(False).astype(bool)
    add = reasons[mask].where(reasons[mask].eq(""), reasons[mask] + "; ") + text
    reasons.loc[mask] = add
    return reasons


# ------------------------------------------------------------- analysis run

def run_analysis(engagement_id: int, actor: str) -> dict:
    eng = db.get_engagement(engagement_id)
    if not eng:
        raise ValueError("engagement not found")
    mat = materiality.load(engagement_id)
    if not mat or not (mat.get("overall") or 0) > 0:
        raise ValueError("Set materiality before running the analysis "
                         "(SA 320 worksheet on the Engagement page)")
    txns = db.active_transactions(engagement_id)
    if txns.empty:
        raise ValueError("Import a ledger before running the analysis")

    cfg = load_config(engagement_id)
    pm = float(mat.get("performance") or 0) or float(mat["overall"]) * 0.75
    isl = float(mat.get("isl_cutoff") or 0) or pm
    th = cfg["thresholds"]

    txns = txns.reset_index(drop=True)
    txns["flags"] = anomalies.stamp_flags(txns, eng["fy_end"],
                                          income_categories=INCOME_CATEGORIES)
    full_reason = pd.Series("", index=txns.index, dtype=object)
    run_ts = db.now()
    pops = []

    for category, g in txns.groupby("category", sort=False):
        cat_cfg = cfg["categories"].get(category, _cat())
        total_abs = float(g["amount_abs"].sum())
        count = int(len(g))
        comp, breakdown = computed_score(cat_cfg, total_abs, count, pm,
                                         cfg["factor_weights"])
        mw = cat_cfg.get("manual_weight")
        final = float(mw) if mw is not None else comp
        cutoff = resolve_cutoff(cat_cfg, pm)

        if final >= float(th["full_min"]):
            hybrid = cutoff is not None and \
                cat_cfg.get("preferred_method") != "full"
            strategy = "HYBRID" if hybrid else "FULL"
        elif final >= float(th["sample_min"]):
            strategy = "SAMPLE"
        else:
            strategy = "SAMPLE_LOW"

        reasons = pd.Series("", index=g.index, dtype=object)
        if strategy == "FULL":
            reasons[:] = (f"Category designated 100% verification "
                          f"(risk score {final:g})")
        elif strategy == "HYBRID":
            reasons = _append_reason(
                reasons, g["amount_abs"] >= cutoff,
                f"Above category cutoff ({cutoff:,.0f})")
        reasons = _append_reason(reasons, g["amount_abs"] >= isl,
                                 "Individually significant item")
        contra = g["flags"].astype(str).str.contains("CONTRA", regex=False)
        reasons = _append_reason(reasons, contra,
                                 "Abnormal-side (contra) entry")

        full_mask = reasons.ne("")
        sampleable = (~full_mask) & g["amount_abs"].gt(0)
        pops.append((engagement_id, run_ts, category, count, total_abs,
                     float(g["amount_signed"].sum()), comp,
                     mw if mw is not None else None, final,
                     json.dumps(breakdown), strategy,
                     cutoff if cutoff is not None else 0.0,
                     int(full_mask.sum()),
                     float(g.loc[full_mask, "amount_abs"].sum()),
                     int(sampleable.sum()),
                     float(g.loc[sampleable, "amount_abs"].sum())))
        full_reason.loc[g.index] = reasons

    db.executemany(
        "UPDATE transactions SET flags=?, full_reason=? WHERE id=?",
        list(zip(txns["flags"].tolist(), full_reason.tolist(),
                 txns["id"].tolist())))
    with db.connect() as con:
        con.execute("DELETE FROM populations WHERE engagement_id=?",
                    (engagement_id,))
        con.executemany(
            "INSERT INTO populations (engagement_id, run_ts, category, "
            "txn_count, total_abs, total_signed, computed_score, "
            "manual_weight, final_score, breakdown_json, strategy, "
            "cutoff_used, full_count, full_value, sample_count, sample_value) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pops)

    n_full = int(full_reason.ne("").sum())
    summary = {
        "run_ts": run_ts,
        "populations": len(pops),
        "transactions": int(len(txns)),
        "full_items": n_full,
        "full_value": float(txns.loc[full_reason.ne(""), "amount_abs"].sum()),
        "performance_materiality": pm,
        "isl_cutoff": isl,
    }
    return summary


def get_populations(engagement_id: int) -> pd.DataFrame:
    return db.read_df(
        "SELECT * FROM populations WHERE engagement_id=? "
        "ORDER BY final_score DESC, total_abs DESC", (engagement_id,))


def analysis_stale(engagement_id: int):
    """How the ledger has drifted from the last analysis run: None when
    there is no run or the stored populations still match the active
    transactions, else {"run_ts", "changed": [{category, items_at_run,
    items_now}, ...]}.

    Re-categorizing (or re-importing) after a run leaves the populations,
    the 100% routing stamped on transactions, and any sample drawn from
    them describing a ledger that no longer exists - callers should demand
    a fresh run before relying on any of those.
    """
    pops = get_populations(engagement_id)
    if not len(pops):
        return None
    txns = db.active_transactions(engagement_id)
    if len(txns):
        cur = txns.groupby("category")["amount_abs"].agg(["count", "sum"])
        cur_n = cur["count"].to_dict()
        cur_v = cur["sum"].to_dict()
    else:
        cur_n, cur_v = {}, {}
    snap_n = dict(zip(pops["category"], pops["txn_count"]))
    snap_v = dict(zip(pops["category"], pops["total_abs"]))
    changed = [
        {"category": c,
         "items_at_run": int(snap_n.get(c, 0)),
         "items_now": int(cur_n.get(c, 0))}
        for c in sorted(set(snap_n) | set(cur_n))
        if int(snap_n.get(c, 0)) != int(cur_n.get(c, 0))
        or abs(float(snap_v.get(c, 0.0)) - float(cur_v.get(c, 0.0))) > 0.01]
    if not changed:
        return None
    return {"run_ts": str(pops["run_ts"].iloc[0]), "changed": changed}


def sampleable_txns(engagement_id: int, category: str) -> pd.DataFrame:
    imp = db.active_import(engagement_id, "ledger")
    if not imp:
        return pd.DataFrame()
    return db.read_df(
        "SELECT * FROM transactions WHERE engagement_id=? AND import_id=? "
        "AND category=? AND full_reason='' AND amount_abs>0",
        (engagement_id, imp["id"], category))


def full_list_txns(engagement_id: int) -> pd.DataFrame:
    imp = db.active_import(engagement_id, "ledger")
    if not imp:
        return pd.DataFrame()
    return db.read_df(
        "SELECT * FROM transactions WHERE engagement_id=? AND import_id=? "
        "AND full_reason != '' ORDER BY amount_abs DESC",
        (engagement_id, imp["id"]))
