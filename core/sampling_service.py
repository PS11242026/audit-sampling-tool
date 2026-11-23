"""Sample lifecycle shared by the UI and the test suite: size calculation,
generation with derived seeds and dataset hashes, supersession with logged
justification, results capture and statistical evaluation (SA 530)."""

import json

import pandas as pd

from core import risk
from core.sampling import evaluate as ev
from core.sampling import select, sizes
from storage import auditlog, db


def population(engagement_id: int, category: str) -> pd.DataFrame:
    return risk.sampleable_txns(engagement_id, category)


def next_generation_no(engagement_id: int, category: str) -> int:
    row = db.query_one(
        "SELECT MAX(generation_no) AS g FROM samples WHERE engagement_id=? "
        "AND category=?", (engagement_id, category))
    return int(row["g"] or 0) + 1 if row else 1


def default_seed(master_seed: int, category: str, generation_no: int) -> int:
    return select.derive_seed(master_seed, category, generation_no)


def compute_size(method: str, pop: pd.DataFrame, params: dict) -> dict:
    """Suggested sample size for the chosen method and SA 530 parameters."""
    confidence = float(params.get("confidence", 0.95))
    if method == "mus":
        return sizes.mus_sample_size(
            book_value=float(pop["amount_abs"].sum()),
            tolerable_misstatement=float(params["tolerable"]),
            expected_misstatement=float(params.get("expected", 0.0)),
            confidence=confidence)
    return sizes.attribute_sample_size(
        confidence=confidence,
        tolerable_rate=float(params.get("tolerable_rate", 0.05)),
        expected_rate=float(params.get("expected_rate", 0.0)),
        population_size=int(len(pop)))


def generate(engagement_id: int, category: str, method: str, params: dict,
             user: dict, justification: str = "", seed=None) -> tuple:
    """Draw a sample and persist it. Any previous draft/final sample for the
    category is marked superseded (a justification is expected when that
    happens; the UI enforces it)."""
    eng = db.get_engagement(engagement_id)
    pop = population(engagement_id, category)
    if pop.empty:
        raise ValueError("no sampleable transactions in this population "
                         "(run the analysis first)")
    generation_no = next_generation_no(engagement_id, category)
    if seed is None:
        seed = default_seed(eng["master_seed"], category, generation_no)
    seed = int(seed)

    if method == "mus":
        selected, info = select.mus(pop, seed=seed, n=int(params["n"]))
    elif method == "stratified":
        selected, info = select.stratified(
            pop, n_total=int(params["n"]), seed=seed,
            n_bands=int(params.get("n_bands", 4)),
            allocation=params.get("allocation", "value"))
    elif method == "systematic":
        selected, info = select.systematic(pop, n=int(params["n"]), seed=seed)
    elif method == "random":
        selected, info = select.srs(pop, n=int(params["n"]), seed=seed,
                                    replace=bool(params.get("replace", False)))
    else:
        raise ValueError(f"unknown sampling method: {method}")

    payload = json.dumps({
        "params": params,
        "info": info,
        "population": {"count": int(len(pop)),
                       "book_value": float(pop["amount_abs"].sum())},
    }, default=str)
    dataset_sha = select.dataset_hash(pop)

    with db.connect() as con:
        con.execute(
            "UPDATE samples SET status='superseded' WHERE engagement_id=? "
            "AND category=? AND status IN ('draft','final')",
            (engagement_id, category))
        cur = con.execute(
            "INSERT INTO samples (engagement_id, category, method, "
            "params_json, seed, dataset_sha256, n_target, n_selected, "
            "generation_no, justification, status, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (engagement_id, category, method, payload, seed, dataset_sha,
             int(params.get("n", len(selected))), int(len(selected)),
             generation_no, justification, "draft",
             user.get("username", ""), db.now()))
        sample_id = cur.lastrowid
        rows = []
        for r in selected.itertuples(index=False):
            rows.append((sample_id, int(r.id), float(r.amount_abs),
                         1 if bool(getattr(r, "is_top_stratum", False)) else 0,
                         int(getattr(r, "times_selected", 1)),
                         int(getattr(r, "band", 0) or 0)))
        con.executemany(
            "INSERT INTO sample_items (sample_id, txn_id, book_value, "
            "is_top_stratum, times_selected, band) VALUES (?,?,?,?,?,?)",
            rows)

    auditlog.log(user, "GENERATE_SAMPLE", entity=f"sample:{sample_id}",
                 details={"category": category, "method": method,
                          "params": params, "seed": seed,
                          "generation_no": generation_no,
                          "n_selected": int(len(selected)),
                          "dataset_sha256": dataset_sha,
                          "justification": justification},
                 engagement_id=engagement_id)
    return sample_id, selected, info


def list_samples(engagement_id: int, include_superseded: bool = True) -> pd.DataFrame:
    sql = ("SELECT id, category, method, seed, n_target, n_selected, "
           "generation_no, status, created_by, created_at, justification "
           "FROM samples WHERE engagement_id=?")
    if not include_superseded:
        sql += " AND status != 'superseded'"
    return db.read_df(sql + " ORDER BY id DESC", (engagement_id,))


def get_sample(sample_id: int):
    row = db.query_one("SELECT * FROM samples WHERE id=?", (sample_id,))
    if row:
        row["payload"] = json.loads(row["params_json"])
    return row


def get_sample_items(sample_id: int) -> pd.DataFrame:
    return db.read_df(
        "SELECT si.id AS item_id, si.txn_id, t.date, t.doc_no, t.account, "
        "t.account_name, t.narration, si.book_value, si.is_top_stratum, "
        "si.times_selected, si.band, si.result, si.audited_value, "
        "si.misstatement, si.wp_ref, si.remarks "
        "FROM sample_items si JOIN transactions t ON t.id = si.txn_id "
        "WHERE si.sample_id=? ORDER BY si.id", (sample_id,))


def set_status(sample_id: int, status: str, user: dict) -> None:
    db.execute("UPDATE samples SET status=? WHERE id=?", (status, sample_id))
    s = db.query_one("SELECT engagement_id, category FROM samples WHERE id=?",
                     (sample_id,))
    auditlog.log(user, "SAMPLE_STATUS", entity=f"sample:{sample_id}",
                 details={"status": status, "category": s["category"]},
                 engagement_id=s["engagement_id"])


def save_results(sample_id: int, results: pd.DataFrame, user: dict) -> int:
    """Persist testing results. Expects columns item_id, result,
    audited_value, wp_ref, remarks (book_value used for misstatement)."""
    updates = []
    for r in results.itertuples(index=False):
        book = float(getattr(r, "book_value", 0) or 0)
        audited = getattr(r, "audited_value", None)
        audited = book if audited is None or pd.isna(audited) else float(audited)
        updates.append((str(getattr(r, "result", "") or ""), audited,
                        book - audited, str(getattr(r, "wp_ref", "") or ""),
                        str(getattr(r, "remarks", "") or ""),
                        user.get("username", ""), db.now(),
                        int(r.item_id)))
    db.executemany(
        "UPDATE sample_items SET result=?, audited_value=?, misstatement=?, "
        "wp_ref=?, remarks=?, tested_by=?, tested_at=? WHERE id=?", updates)
    s = db.query_one("SELECT engagement_id, category FROM samples WHERE id=?",
                     (sample_id,))
    auditlog.log(user, "SAVE_RESULTS", entity=f"sample:{sample_id}",
                 details={"items": len(updates), "category": s["category"]},
                 engagement_id=s["engagement_id"])
    return len(updates)


def evaluate_sample(sample_id: int, user: dict) -> dict:
    s = get_sample(sample_id)
    if not s:
        raise ValueError("sample not found")
    payload = s["payload"]
    params = payload.get("params", {})
    info = payload.get("info", {})
    popstats = payload.get("population", {})
    items = get_sample_items(sample_id)
    if items.empty:
        raise ValueError("sample has no items")

    df = items.copy()
    df["audited_value"] = df["audited_value"].fillna(df["book_value"])
    df["is_top_stratum"] = df["is_top_stratum"].astype(bool)
    confidence = float(params.get("confidence", 0.95))

    if s["method"] == "mus":
        results = ev.mus_evaluate(
            df, interval=float(info["interval"]), confidence=confidence,
            tolerable_misstatement=float(params.get("tolerable", 0)))
    else:
        sample_book = float(df["book_value"].sum())
        sample_err = float((df["book_value"] - df["audited_value"]).sum())
        deviations = int(df["result"].astype(str).str.lower()
                         .eq("exception").sum())
        results = {
            "confidence": confidence,
            "items_tested": int(len(df)),
            "sample_book_value": sample_book,
            "sample_misstatement": sample_err,
            "ratio_projection": ev.ratio_projection(
                float(popstats.get("book_value", 0)), sample_book, sample_err),
            "difference_projection": ev.difference_projection(
                int(popstats.get("count", 0)), int(len(df)), sample_err),
            "attribute": ev.attribute_evaluate(
                int(len(df)), deviations, confidence,
                float(params.get("tolerable_rate", 0.05))),
        }
        tol = params.get("tolerable")
        if tol:
            worst = max(abs(results["ratio_projection"]),
                        abs(results["difference_projection"]))
            results["tolerable_misstatement"] = float(tol)
            results["acceptable"] = bool(worst <= float(tol))

    db.execute(
        "INSERT INTO evaluations (sample_id, method, params_json, "
        "results_json, created_by, created_at) VALUES (?,?,?,?,?,?)",
        (sample_id, s["method"], json.dumps(params),
         json.dumps(results, default=str), user.get("username", ""),
         db.now()))
    auditlog.log(user, "EVALUATE_SAMPLE", entity=f"sample:{sample_id}",
                 details={"category": s["category"],
                          "method": s["method"],
                          "acceptable": results.get(
                              "acceptable",
                              results.get("attribute", {}).get("acceptable"))},
                 engagement_id=s["engagement_id"])
    return results


def latest_evaluation(sample_id: int):
    row = db.query_one(
        "SELECT * FROM evaluations WHERE sample_id=? ORDER BY id DESC LIMIT 1",
        (sample_id,))
    if row:
        row["results"] = json.loads(row["results_json"])
    return row
