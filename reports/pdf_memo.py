"""PDF sampling memorandum (fpdf2): the SA 530 rationale narrative with
parameters, seeds, conclusions and sign-off blocks for the audit file."""

import json
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from core import materiality, serc, risk, sampling_service
from core.formatting import inr, short_hash
from core.version import APP_NAME, __version__
from storage import auditlog, db

_ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")
_ARIAL_B = Path(r"C:\Windows\Fonts\arialbd.ttf")

METHOD_LABELS = {
    "mus": "Monetary unit sampling",
    "stratified": "Stratified random sampling",
    "systematic": "Systematic selection",
    "random": "Simple random sampling",
    "full": "100% verification",
}

METHOD_RATIONALE = {
    "mus": ("Monetary unit sampling gives every rupee an equal chance of "
            "selection, so higher-value items carry proportionately higher "
            "inclusion probability, and every item at or above the sampling "
            "interval is examined in full. Appropriate for substantive "
            "testing where overstatement is the principal risk."),
    "stratified": ("The population was stratified by value bands so that "
                   "higher-value strata receive proportionately larger "
                   "allocations, reducing sampling risk for a given sample "
                   "size (SA 530 A8-A9)."),
    "systematic": ("Systematic selection with a seeded random start was "
                   "applied after considering whether the population is "
                   "structured such that the sampling interval could "
                   "coincide with a pattern (SA 530 A13)."),
    "random": ("Simple random selection gives every item an equal chance of "
               "selection and matches the assessed lower level of risk for "
               "this population."),
}

FRAMEWORK_TEXT = (
    "This memorandum documents the risk assessment and audit sampling "
    "approach for the engagement. Risks of material misstatement were "
    "identified and assessed at the assertion level per SA 315 (Revised); "
    "materiality and performance materiality were determined per SA 320; "
    "samples were designed, selected and will be evaluated per SA 530; and "
    "this memorandum, together with the Excel workpaper pack, forms part of "
    "the audit documentation per SA 230. Audit sampling is applied as "
    "defined in SA 530(5)(a): the application of audit procedures to less "
    "than 100% of items within a population of audit relevance such that "
    "all sampling units have a chance of selection. Electricity income is "
    "recognised per Ind AS 115 and cross-checked against the SERC MYT "
    "tariff order; interest income falls under Ind AS 109; the spares "
    "classification (inventory vs PPE under Ind AS 16), repairs and "
    "maintenance and deferred taxes are prior-year qualification areas and "
    "carry elevated risk weights. Categories at or above the 100% threshold "
    "are verified in full; individually significant items and abnormal-side "
    "entries are always verified in full irrespective of category strategy.")


class _Memo(FPDF):
    def __init__(self, engagement,
                 doc_title="Risk Assessment & Sampling Memorandum"):
        super().__init__(format="A4")
        self.eng = engagement
        self.doc_title = doc_title
        self.family_name = "Helvetica"
        self.uni = False
        try:
            if _ARIAL.exists():
                self.add_font("Ar", "", str(_ARIAL))
                self.add_font("Ar", "B",
                              str(_ARIAL_B if _ARIAL_B.exists() else _ARIAL))
                self.family_name, self.uni = "Ar", True
        except Exception:
            pass
        self.set_auto_page_break(True, margin=18)

    def tx(self, s) -> str:
        s = "" if s is None else str(s)
        return s if self.uni else \
            s.encode("latin-1", "replace").decode("latin-1")

    def header(self):
        self.set_font(self.family_name, "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, self.tx(f"{self.eng['company']} - {self.doc_title}"),
                  align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self):
        self.set_y(-14)
        self.set_font(self.family_name, "", 7.5)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, self.tx(
            f"{APP_NAME} v{__version__} | engagement master seed "
            f"{self.eng['master_seed']} | page {self.page_no()}/{{nb}}"),
            align="C")
        self.set_text_color(0, 0, 0)

    def h1(self, text):
        self.set_font(self.family_name, "B", 12)
        self.cell(0, 8, self.tx(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def h2(self, text):
        self.set_font(self.family_name, "B", 10.5)
        self.cell(0, 7, self.tx(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def para(self, text, size=9.5):
        self.set_font(self.family_name, "", size)
        self.multi_cell(0, 5, self.tx(text))
        self.ln(1)

    def kv(self, pairs):
        for k, v in pairs:
            self.set_font(self.family_name, "B", 9)
            self.cell(72, 5.5, self.tx(k))
            self.set_font(self.family_name, "", 9)
            self.multi_cell(0, 5.5, self.tx(v),
                            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def table(self, headers, rows, widths):
        self.set_font(self.family_name, "B", 8.5)
        self.set_fill_color(31, 78, 120)
        self.set_text_color(255, 255, 255)
        for w, h in zip(widths, headers):
            self.cell(w, 6, self.tx(h), border=1, fill=True)
        self.ln()
        self.set_text_color(0, 0, 0)
        self.set_font(self.family_name, "", 8.5)
        for row in rows:
            for w, val in zip(widths, row):
                self.cell(w, 6, self.tx(str(val))[:46], border=1)
            self.ln()
        self.ln(2)


def generate_memo(engagement_id: int, user: dict) -> bytes:
    eng = db.get_engagement(engagement_id)
    if not eng:
        raise ValueError("engagement not found")
    mat = materiality.load(engagement_id)
    pops = risk.get_populations(engagement_id)
    serc_data = serc.load(engagement_id)
    txns = db.active_transactions(engagement_id)
    samples = sampling_service.list_samples(engagement_id)
    active = samples[samples["status"] != "superseded"] \
        if len(samples) else samples

    pdf = _Memo(eng)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font(pdf.family_name, "B", 14)
    pdf.multi_cell(0, 7, pdf.tx("Risk Assessment and Audit Sampling "
                                "Memorandum"))
    pdf.ln(2)
    pdf.kv([
        ("Engagement", eng["name"]),
        ("Company", eng["company"]),
        ("Financial year", f"{eng['fy_start']} to {eng['fy_end']}"),
        ("Regulatory context", eng.get("control_period") or "-"),
        ("Prepared with", f"{APP_NAME} v{__version__}"),
        ("Generated at / by", f"{db.now()} / {user.get('username', '')} "
                              f"({user.get('role', '')})"),
    ])

    pdf.h1("1. Framework and approach")
    pdf.para(FRAMEWORK_TEXT)

    pdf.h1("2. Materiality (SA 320)")
    if mat:
        pdf.kv([
            ("Benchmark", f"{mat.get('benchmark')} "
                          f"({inr(mat.get('benchmark_amount'))}) at "
                          f"{mat.get('percent')}%"),
            ("Overall materiality", inr(mat.get("overall"))),
            ("Performance materiality",
             f"{inr(mat.get('performance'))} ({mat.get('pm_percent')}% of "
             f"overall)"),
            ("Individually significant cutoff", inr(mat.get("isl_cutoff"))),
        ])
    else:
        pdf.para("Materiality has not been recorded yet.")

    pdf.h1("3. Risk assessment by population (SA 315)")
    if len(pops):
        rows = [(p.category, f"{p.final_score:g}", p.strategy,
                 f"{p.txn_count:,}", inr(p.total_abs),
                 f"{p.full_count:,}", f"{p.sample_count:,}")
                for p in pops.itertuples(index=False)]
        pdf.table(["Population", "Score", "Strategy", "Items", "Value",
                   "100% items", "Sampled pop."],
                  rows, [52, 12, 22, 16, 34, 20, 22])
    else:
        pdf.para("The analysis run has not been performed yet.")

    pdf.h1("4. Sampling plans (SA 530)")
    if len(active):
        for s in active.itertuples(index=False):
            detail = sampling_service.get_sample(int(s.id))
            payload = detail["payload"]
            params = payload.get("params", {})
            info = payload.get("info", {})
            popstats = payload.get("population", {})
            pdf.h2(f"S{s.id} - {s.category}")
            pairs = [
                ("Method", METHOD_LABELS.get(s.method, s.method)),
                ("Population", f"{popstats.get('count'):,} items, "
                               f"{inr(popstats.get('book_value'))}"),
                ("Sample size", f"{s.n_selected} items selected "
                                f"(generation {s.generation_no}, "
                                f"status {s.status})"),
                ("Seed / algorithm", f"{s.seed} / numpy PCG64, canonical "
                                     f"sort: date, doc no, row id"),
                ("Population SHA-256", short_hash(detail["dataset_sha256"],
                                                  20)),
            ]
            if s.method == "mus":
                pairs += [
                    ("Confidence", f"{float(params.get('confidence', 0.95)) * 100:.0f}%"),
                    ("Tolerable / expected misstatement",
                     f"{inr(params.get('tolerable'))} / "
                     f"{inr(params.get('expected', 0))}"),
                    ("Sampling interval", inr(info.get("interval"))),
                ]
            if s.justification:
                pairs.append(("Regeneration justification", s.justification))
            pdf.kv(pairs)
            pdf.para(METHOD_RATIONALE.get(s.method, ""))
    else:
        pdf.para("No samples have been generated yet.")

    pdf.h1("5. Regulated revenue vs SERC tariff order")
    if len(txns):
        annual = serc.annual_tieout(txns, serc_data)
        monthly = serc.monthly_reconciliation(txns, serc_data,
                                              eng["fy_start"], eng["fy_end"])
        flagged = monthly[monthly["exception"]]
        months = ", ".join(flagged["month"].tolist()) if len(flagged) else \
            "none"
        pdf.para(
            f"Booked electricity income {inr(annual['booked_total'])} vs "
            f"expected {inr(annual['expected_total'])} per the tariff order "
            f"including true-up and incentives; difference "
            f"{inr(annual['difference'])} "
            f"({annual['difference_pct']:.3f}%). Monthly variances above the "
            f"{serc_data.get('variance_threshold_pct')}% threshold: {months}. "
            f"Flagged months are carried to the exceptions list for "
            f"resolution against SERC billing records and meter data.")
    else:
        pdf.para("Ledger not yet imported.")

    pdf.h1("6. Evaluation and conclusions")
    evals = db.read_df(
        "SELECT e.sample_id, s.category, s.method, e.results_json "
        "FROM evaluations e "
        "JOIN (SELECT sample_id, MAX(id) AS mid FROM evaluations "
        "GROUP BY sample_id) x ON x.mid = e.id "
        "JOIN samples s ON s.id = e.sample_id "
        "WHERE s.engagement_id=? AND s.status != 'superseded'",
        (engagement_id,))
    if len(evals):
        for e in evals.itertuples(index=False):
            r = json.loads(e.results_json)
            if e.method == "mus":
                verdict = ("within" if r.get("acceptable")
                           else "EXCEEDS") + " tolerable misstatement"
                pdf.para(
                    f"S{e.sample_id} ({e.category}): most likely "
                    f"misstatement {inr(r.get('most_likely_misstatement'))}; "
                    f"upper misstatement limit "
                    f"{inr(r.get('upper_misstatement_limit'))} vs tolerable "
                    f"{inr(r.get('tolerable_misstatement'))} - {verdict}.")
            else:
                attr = r.get("attribute", {})
                pdf.para(
                    f"S{e.sample_id} ({e.category}): ratio projection "
                    f"{inr(r.get('ratio_projection'))}, difference "
                    f"projection {inr(r.get('difference_projection'))}; "
                    f"deviation rate {attr.get('sample_rate', 0):.2%}, "
                    f"achieved upper limit "
                    f"{attr.get('achieved_upper_limit', 0):.2%} vs tolerable "
                    f"{attr.get('tolerable_rate', 0):.2%}.")
    else:
        pdf.para("Samples not yet evaluated. Record testing results in the "
                 "tool (or re-import the completed Excel pack) and run the "
                 "evaluation before concluding.")

    pdf.h1("7. Sign-off")
    for who in ("Prepared by (Staff/Manager)", "Reviewed by (Manager)",
                "Approved by (Partner)"):
        pdf.para(f"{who}:  Name ____________________  Signature "
                 f"____________________  Date ____________", size=9.5)

    content = bytes(pdf.output())
    auditlog.log(user, "EXPORT_PDF_MEMO", details={"bytes": len(content)},
                 engagement_id=engagement_id)
    return content
