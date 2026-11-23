"""Excel workpaper pack (XlsxWriter).

Tabs: Cover & sign-off, Materiality, Populations & risk matrix, Risk
configuration, 100% verification list, one tab per active sample (with a
parameter box and blank testing columns), Evaluation, SERC reconciliation,
one tab per SA 505 confirmation area, Exceptions, Audit trail. A hidden
``_meta`` sheet maps sample tabs to sample ids so a completed workbook can
be re-imported for evaluation.
"""

import io
import re

import pandas as pd
import xlsxwriter

from core import (anomalies, confirmations, importer, materiality, serc,
                  risk, sampling_service)
from core.formatting import INR_XLSX_FMT, short_hash
from core.version import APP_NAME, __version__
from storage import auditlog, db

STANDARDS_LINES = [
    "Basis of preparation: risk assessment per SA 315 (Revised); materiality "
    "per SA 320; sampling design and evaluation per SA 530; this pack forms "
    "part of the audit documentation per SA 230.",
    "Audit sampling (SA 530(5)(a)): applying audit procedures to less than "
    "100% of items within a population of audit relevance such that all "
    "sampling units have a chance of selection.",
    "Revenue recognised per Ind AS 115; interest income per Ind AS 109; "
    "spares/PPE classification per Ind AS 16 (prior-year qualification "
    "area). Regulated income cross-checked against the SERC MYT tariff "
    "order.",
    "Selections are reproducible: numpy PCG64 generator with the documented "
    "seed, canonical sort order (date, document number, row id) and the "
    "population SHA-256 recorded per sample.",
]


def _safe_sheet_name(name: str, used: set) -> str:
    s = re.sub(r"[\[\]:*?/\\]", "", str(name)).strip()[:31] or "Sheet"
    base, i = s, 2
    while s.lower() in used:
        suffix = f"_{i}"
        s = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(s.lower())
    return s


class _Pack:
    def __init__(self, buf):
        self.wb = xlsxwriter.Workbook(buf, {"in_memory": True})
        wb = self.wb
        self.f_title = wb.add_format({"bold": True, "font_size": 14})
        self.f_h2 = wb.add_format({"bold": True, "font_size": 11,
                                   "font_color": "#1F4E78"})
        self.f_label = wb.add_format({"bold": True, "font_color": "#444444"})
        self.f_header = wb.add_format({"bold": True, "bg_color": "#1F4E78",
                                       "font_color": "#FFFFFF", "border": 1})
        self.f_money = wb.add_format({"num_format": INR_XLSX_FMT})
        self.f_wrap = wb.add_format({"text_wrap": True, "valign": "top"})
        self.f_bad = wb.add_format({"font_color": "#9C0006",
                                    "bg_color": "#FFC7CE"})

    def kv(self, ws, row, pairs, money_keys=()):
        for label, val in pairs:
            ws.write(row, 0, label, self.f_label)
            if isinstance(val, (int, float)) and not isinstance(val, bool) \
                    and label in money_keys:
                ws.write_number(row, 1, float(val), self.f_money)
            else:
                ws.write(row, 1, "" if val is None else val)
            row += 1
        return row + 1

    def table(self, ws, row, df, money_cols=(), bad_col=None):
        cols = list(df.columns)
        for c, colname in enumerate(cols):
            ws.write(row, c, str(colname), self.f_header)
        for r_off, tup in enumerate(df.itertuples(index=False), start=1):
            r = row + r_off
            bad = bool(bad_col and getattr(tup, bad_col, False))
            for c, val in enumerate(tup):
                col = cols[c]
                fmt = self.f_bad if bad else (
                    self.f_money if col in money_cols else None)
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    ws.write_blank(r, c, None, fmt)
                elif isinstance(val, bool):
                    ws.write_string(r, c, "Yes" if val else "No",
                                    fmt if bad else None)
                elif isinstance(val, (int, float)):
                    ws.write_number(r, c, float(val), fmt)
                else:
                    ws.write_string(r, c, str(val), fmt if bad else None)
        if len(df):
            ws.autofilter(row, 0, row + len(df), max(0, len(cols) - 1))
        return row + len(df) + 2


def _display_txns(df: pd.DataFrame, extra=()) -> pd.DataFrame:
    cols = ["date", "doc_no", "doc_type", "account", "account_name",
            "narration", "amount_abs", "side", "flags", "full_reason"]
    cols = [c for c in cols if c in df.columns] + list(extra)
    out = df[[c for c in cols if c in df.columns]].copy()
    for c in extra:
        if c not in out.columns:
            out[c] = ""
    return out


def generate_workpaper_pack(engagement_id: int, user: dict) -> bytes:
    eng = db.get_engagement(engagement_id)
    if not eng:
        raise ValueError("engagement not found")
    mat = materiality.load(engagement_id)
    pops = risk.get_populations(engagement_id)
    full = risk.full_list_txns(engagement_id)
    txns = db.active_transactions(engagement_id)
    tb = db.active_trial_balance(engagement_id)
    serc_data = serc.load(engagement_id)
    cfg = risk.load_config(engagement_id)
    samples = sampling_service.list_samples(engagement_id)
    active_samples = samples[samples["status"] != "superseded"] \
        if len(samples) else samples

    buf = io.BytesIO()
    p = _Pack(buf)
    used = set()

    # ------------------------------------------------------------- cover
    ws = p.wb.add_worksheet(_safe_sheet_name("Cover", used))
    ws.set_column(0, 0, 36)
    ws.set_column(1, 1, 90)
    ws.write(0, 0, APP_NAME, p.f_title)
    row = p.kv(ws, 2, [
        ("Engagement", eng["name"]),
        ("Company", eng["company"]),
        ("Financial year", f"{eng['fy_start']} to {eng['fy_end']}"),
        ("Regulatory context", eng.get("control_period") or ""),
        ("Master seed (engagement)", eng["master_seed"]),
        ("Tool version", __version__),
        ("Workpaper generated at", db.now()),
        ("Generated by", f"{user.get('username','')} ({user.get('role','')})"),
    ])
    ws.write(row, 0, "Framework", p.f_h2)
    row += 1
    for line in STANDARDS_LINES:
        ws.write(row, 1, line, p.f_wrap)
        ws.set_row(row, 30)
        row += 1
    row += 1
    ws.write(row, 0, "Sign-off", p.f_h2)
    row += 1
    for who in ("Prepared by (Staff/Manager)", "Reviewed by (Manager)",
                "Approved by (Partner)"):
        ws.write(row, 0, who, p.f_label)
        ws.write(row, 1, "Name: ______________________  Signature: "
                         "______________  Date: ____________")
        row += 1

    # -------------------------------------------------------- materiality
    ws = p.wb.add_worksheet(_safe_sheet_name("Materiality", used))
    ws.set_column(0, 0, 36)
    ws.set_column(1, 1, 40)
    ws.write(0, 0, "SA 320 materiality worksheet", p.f_h2)
    if mat:
        money = {"Benchmark amount", "Overall materiality",
                 "Performance materiality",
                 "Individually significant item cutoff"}
        p.kv(ws, 2, [
            ("Benchmark", mat.get("benchmark")),
            ("Benchmark amount", mat.get("benchmark_amount")),
            ("Percentage applied", f"{mat.get('percent')}%"),
            ("Overall materiality", mat.get("overall")),
            ("Performance materiality %", f"{mat.get('pm_percent')}%"),
            ("Performance materiality", mat.get("performance")),
            ("Individually significant item cutoff", mat.get("isl_cutoff")),
            ("Notes", mat.get("notes")),
            ("Set by / at", f"{mat.get('updated_by')} / {mat.get('updated_at')}"),
        ], money_keys=money)
    else:
        ws.write(2, 0, "Materiality has not been set.", p.f_bad)

    # -------------------------------------------------------- populations
    ws = p.wb.add_worksheet(_safe_sheet_name("Populations", used))
    ws.write(0, 0, "Population summary and risk matrix (SA 315)", p.f_h2)
    if len(pops):
        view = pops[["category", "txn_count", "total_abs", "computed_score",
                     "manual_weight", "final_score", "strategy",
                     "cutoff_used", "full_count", "full_value",
                     "sample_count", "sample_value"]].rename(columns={
            "category": "Category", "txn_count": "Items",
            "total_abs": "Total value", "computed_score": "Computed score",
            "manual_weight": "Assigned weight", "final_score": "Final score",
            "strategy": "Strategy", "cutoff_used": "Cutoff",
            "full_count": "100% items", "full_value": "100% value",
            "sample_count": "Sampleable items",
            "sample_value": "Sampleable value"})
        p.table(ws, 2, view, money_cols={"Total value", "Cutoff",
                                         "100% value", "Sampleable value"})
        ws.set_column(0, 0, 42)
        ws.set_column(1, 11, 16)
    else:
        ws.write(2, 0, "Run the analysis to build populations.", p.f_bad)

    # ------------------------------------------------------- risk config
    ws = p.wb.add_worksheet(_safe_sheet_name("Risk config", used))
    ws.write(0, 0, "Risk configuration", p.f_h2)
    th = cfg["thresholds"]
    row = p.kv(ws, 2, [
        ("100% verification at score >=", th["full_min"]),
        ("Sampling (stratified/MUS) at score >=", th["sample_min"]),
        ("Low-risk random sample floor n", th["low_floor_n"]),
        ("Factor weights", ", ".join(
            f"{k}={v}" for k, v in cfg["factor_weights"].items())),
    ])
    cat_rows = []
    for name, s in cfg["categories"].items():
        cat_rows.append({
            "Category": name, "Assigned weight": s.get("manual_weight"),
            "Control": s.get("control"), "Complexity": s.get("complexity"),
            "Regulatory": bool(s.get("regulatory")),
            "Prior qualification": bool(s.get("prior_qualified")),
            "New/one-off": bool(s.get("new_oneoff")),
            "Cutoff mode": s.get("cutoff_mode"),
            "Cutoff value": s.get("cutoff_value"),
            "Preferred method": s.get("preferred_method"),
            "Notes": s.get("notes")})
    p.table(ws, row, pd.DataFrame(cat_rows))
    ws.set_column(0, 0, 42)
    ws.set_column(10, 10, 60)

    # ---------------------------------------------------------- 100% list
    ws = p.wb.add_worksheet(_safe_sheet_name("100pc verification", used))
    ws.write(0, 0, "Transactions for 100% verification", p.f_h2)
    if len(full):
        view = _display_txns(full, extra=("Result", "Audited value",
                                          "W-P ref", "Remarks"))
        view = view.assign(category=full["category"])
        p.table(ws, 2, view, money_cols={"amount_abs", "Audited value"})
        ws.set_column(5, 5, 60)
        ws.freeze_panes(3, 0)
    else:
        ws.write(2, 0, "No items flagged yet - run the analysis.", p.f_bad)

    # -------------------------------------------------------- sample tabs
    meta_rows = []
    for s in (active_samples.itertuples(index=False)
              if len(active_samples) else []):
        detail = sampling_service.get_sample(int(s.id))
        payload = detail["payload"]
        params, info = payload.get("params", {}), payload.get("info", {})
        popstats = payload.get("population", {})
        items = sampling_service.get_sample_items(int(s.id))
        name = _safe_sheet_name(f"S{s.id} {s.category}", used)
        ws = p.wb.add_worksheet(name)
        ws.write(0, 0, f"Sample S{s.id} - {s.category}", p.f_h2)
        pairs = [
            ("Method", s.method), ("Status", s.status),
            ("Generation", s.generation_no), ("Seed", s.seed),
            ("Population items / book value",
             f"{popstats.get('count')} / {popstats.get('book_value'):,.0f}"),
            ("Population SHA-256", short_hash(detail["dataset_sha256"], 20)),
            ("Confidence", params.get("confidence")),
            ("Tolerable misstatement", params.get("tolerable", "")),
            ("Expected misstatement", params.get("expected", "")),
            ("Sampling interval", info.get("interval", "")),
            ("Random start", info.get("random_start", "")),
            ("Selected items", s.n_selected),
            ("Sort order", ", ".join(info.get("sort_order", []))),
            ("Created by / at", f"{s.created_by} / {s.created_at}"),
            ("Justification (regeneration)", s.justification or "-"),
        ]
        row = p.kv(ws, 2, pairs)
        header_row = row
        meta_rows.append({"sample_id": int(s.id), "sheet": name,
                          "header_row": header_row})
        if len(items):
            view = items[["item_id", "txn_id", "date", "doc_no", "account",
                          "narration", "book_value", "is_top_stratum",
                          "times_selected", "band", "result",
                          "audited_value", "wp_ref", "remarks"]].copy()
            p.table(ws, header_row, view, money_cols={"book_value",
                                                      "audited_value"})
        ws.set_column(0, 0, 30)
        ws.set_column(1, 1, 44)
        ws.set_column(5, 5, 56)
        ws.freeze_panes(header_row + 1, 0)

    # -------------------------------------------------------------- meta
    ws = p.wb.add_worksheet("_meta")
    p.table(ws, 0, pd.DataFrame(meta_rows if meta_rows else
                                [{"sample_id": "", "sheet": "",
                                  "header_row": ""}]))
    ws.hide()

    # --------------------------------------------------------- evaluation
    ws = p.wb.add_worksheet(_safe_sheet_name("Evaluation", used))
    ws.write(0, 0, "Sample evaluation and projection (SA 530)", p.f_h2)
    evals = db.read_df(
        "SELECT e.sample_id, s.category, s.method, e.results_json, "
        "e.created_by, e.created_at FROM evaluations e "
        "JOIN (SELECT sample_id, MAX(id) AS mid FROM evaluations GROUP BY "
        "sample_id) x ON x.mid = e.id "
        "JOIN samples s ON s.id = e.sample_id "
        "WHERE s.engagement_id=? AND s.status != 'superseded'",
        (engagement_id,))
    if len(evals):
        import json as _json
        rows = []
        for e in evals.itertuples(index=False):
            r = _json.loads(e.results_json)
            attr = r.get("attribute", {})
            rows.append({
                "Sample": f"S{e.sample_id}", "Category": e.category,
                "Method": e.method,
                "Projected (MUS/most likely)": r.get(
                    "most_likely_misstatement"),
                "Upper misstatement limit": r.get("upper_misstatement_limit"),
                "Ratio projection": r.get("ratio_projection"),
                "Difference projection": r.get("difference_projection"),
                "Deviation rate": attr.get("sample_rate"),
                "Achieved upper deviation limit": attr.get(
                    "achieved_upper_limit"),
                "Tolerable": r.get("tolerable_misstatement",
                                   attr.get("tolerable_rate")),
                "Acceptable": r.get("acceptable", attr.get("acceptable")),
                "Evaluated by / at": f"{e.created_by} / {e.created_at}",
            })
        p.table(ws, 2, pd.DataFrame(rows),
                money_cols={"Projected (MUS/most likely)",
                            "Upper misstatement limit", "Ratio projection",
                            "Difference projection"})
        ws.set_column(0, 12, 20)
    else:
        ws.write(2, 0, "No evaluations recorded yet.")

    # --------------------------------------------------------------- SERC
    ws = p.wb.add_worksheet(_safe_sheet_name("SERC recon", used))
    ws.write(0, 0, "Regulated revenue vs SERC tariff order", p.f_h2)
    row = p.kv(ws, 2, [
        ("Control period", serc_data.get("control_period")),
        ("Tariff order reference", serc_data.get("tariff_order_ref")),
        ("Approved annual transmission charges", serc_data.get("approved_atc")),
        ("Approved annual wheeling income", serc_data.get("approved_wheeling")),
        ("True-up adjustment recognised", serc_data.get("trueup_adjustment")),
        ("Incentive recognised", serc_data.get("incentive")),
        ("Variance threshold %", serc_data.get("variance_threshold_pct")),
    ], money_keys={"Approved annual transmission charges",
                   "Approved annual wheeling income",
                   "True-up adjustment recognised", "Incentive recognised"})
    if len(txns):
        monthly = serc.monthly_reconciliation(txns, serc_data,
                                              eng["fy_start"], eng["fy_end"])
        ws.write(row, 0, "Monthly transmission charges", p.f_h2)
        row = p.table(ws, row + 1, monthly,
                      money_cols={"expected", "booked", "variance"},
                      bad_col="exception")
        wheel = serc.wheeling_reconciliation(txns, serc_data,
                                             eng["fy_start"], eng["fy_end"])
        ws.write(row, 0, "Monthly wheeling charges", p.f_h2)
        row = p.table(ws, row + 1, wheel,
                      money_cols={"expected", "booked", "variance"},
                      bad_col="exception")
        annual = serc.annual_tieout(txns, serc_data)
        ws.write(row, 0, "Annual tie-out", p.f_h2)
        p.kv(ws, row + 1, [
            ("Expected electricity income (order +/- adjustments)",
             annual["expected_total"]),
            ("Booked electricity income", annual["booked_total"]),
            ("Difference", annual["difference"]),
            ("Difference %", f"{annual['difference_pct']:.3f}%"),
        ], money_keys={"Expected electricity income (order +/- adjustments)",
                       "Booked electricity income", "Difference"})
    ws.set_column(0, 0, 46)
    ws.set_column(1, 6, 20)

    # ------------------------------------------- confirmations (SA 505)
    for area in confirmations.areas_with_data(engagement_id):
        book, ext = confirmations.active_frames(engagement_id, area)
        settings = confirmations.load_settings(engagement_id, area)
        recon = confirmations.match_confirmations(
            book, ext, settings["tolerance"], settings["ext_sign"])
        recon = confirmations.attach_assessments(
            recon, confirmations.load_assessments(engagement_id, area))
        stats = confirmations.confirmation_stats(recon,
                                                 settings["tolerance"])
        ws = p.wb.add_worksheet(_safe_sheet_name(f"Conf {area}", used))
        ws.write(0, 0, f"External confirmations (SA 505) - {area}", p.f_h2)
        row = p.kv(ws, 2, [
            ("Parties in books", stats["parties"]),
            ("Responses received",
             f"{stats['responses']} "
             f"({stats['response_rate_pct']:.0f}% of parties)"),
            ("Agreed / exceptions / no response",
             f"{stats['agreed']} / {stats['exceptions']} / "
             f"{stats['no_response']}"),
            ("Confirmations not in books", stats["not_in_books"]),
            ("Value coverage", f"{stats['coverage_pct']:.1f}%"),
            ("Exception value", stats["exception_value"]),
            ("Unconfirmed value (no response)",
             stats["no_response_value_abs"]),
            ("Matching tolerance (Rs)", settings["tolerance"]),
            ("Confirmed balance sign", settings["ext_sign"]),
        ], money_keys={"Exception value",
                       "Unconfirmed value (no response)"})
        if len(recon):
            p.table(ws, row, recon.drop(columns=["party_key"]),
                    money_cols={"book_balance", "confirmed_balance",
                                "difference"})
            ws.freeze_panes(row + 1, 0)
        ws.set_column(0, 1, 34)
        ws.set_column(10, 11, 44)

    # --------------------------------------------------------- exceptions
    ws = p.wb.add_worksheet(_safe_sheet_name("Exceptions", used))
    ws.write(0, 0, "Anomalies and exceptions", p.f_h2)
    row = 2
    if len(txns):
        summ = anomalies.summarize(txns["flags"])
        if len(summ):
            row = p.table(ws, row, summ)
        flagged = txns[txns["flags"].astype(str).ne("")]
        if len(flagged):
            ws.write(row, 0, "Flagged transactions", p.f_h2)
            row = p.table(ws, row + 1, _display_txns(flagged),
                          money_cols={"amount_abs"})
    if len(tb) and len(txns):
        recon = importer.tb_reconcile(txns, tb)
        mism = recon[~recon["ok"]]
        if len(mism):
            ws.write(row, 0, "Ledger vs trial balance mismatches", p.f_h2)
            row = p.table(ws, row + 1, mism,
                          money_cols={"tb_movement", "ledger_net",
                                      "difference"})
    ws.set_column(0, 0, 24)
    ws.set_column(5, 5, 56)

    # -------------------------------------------------------- audit trail
    ws = p.wb.add_worksheet(_safe_sheet_name("Audit trail", used))
    ws.write(0, 0, "Audit trail extract (SA 230)", p.f_h2)
    trail = auditlog.fetch(engagement_id=engagement_id, limit=5000)
    if len(trail):
        p.table(ws, 2, trail)
        ws.set_column(1, 1, 20)
        ws.set_column(6, 7, 60)

    p.wb.close()
    content = buf.getvalue()
    auditlog.log(user, "EXPORT_EXCEL_PACK",
                 details={"bytes": len(content)},
                 engagement_id=engagement_id)
    return content


def read_results_workbook(content: bytes) -> dict:
    """Parse a completed workpaper pack; returns {sample_id: results df}."""
    xl = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    if "_meta" not in xl.sheet_names:
        raise ValueError("not a workpaper pack generated by this tool "
                         "(_meta sheet missing)")
    meta = xl.parse("_meta")
    out = {}
    for r in meta.itertuples(index=False):
        try:
            sample_id = int(r.sample_id)
        except (TypeError, ValueError):
            continue
        if r.sheet not in xl.sheet_names:
            continue
        df = xl.parse(r.sheet, header=int(r.header_row))
        needed = {"item_id", "book_value"}
        if not needed.issubset(set(df.columns)):
            continue
        for c in ("result", "audited_value", "wp_ref", "remarks"):
            if c not in df.columns:
                df[c] = None
        out[sample_id] = df[["item_id", "book_value", "result",
                             "audited_value", "wp_ref", "remarks"]]
    return out
