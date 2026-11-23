"""Generate the combined Technical & Operating Manual PDF.

Part A explains how the tool works internally (data flow, risk scoring,
sample-size math, selection/reproducibility, evaluation, SERC recon,
storage, architecture) with worked numbers. Part B is the step-by-step
operating guide. Regenerate after tool changes to keep it in sync.

Run:  .venv\\Scripts\\python docs\\make_manual.py
Writes docs/Kestrel_Audit_Tool_Manual.pdf
"""

import sys
from datetime import date
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.version import __version__  # noqa: E402

_ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")
_ARIAL_B = Path(r"C:\Windows\Fonts\arialbd.ttf")

BLUE = (31, 78, 120)
GREY = (90, 90, 90)


class Manual(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.fam = "Helvetica"
        try:
            if _ARIAL.exists():
                self.add_font("Ar", "", str(_ARIAL))
                self.add_font("Ar", "B",
                              str(_ARIAL_B if _ARIAL_B.exists() else _ARIAL))
                self.fam = "Ar"
        except Exception:
            pass
        self.set_auto_page_break(True, margin=15)
        self.alias_nb_pages()
        self._part = ""

    # --- infrastructure -------------------------------------------------
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font(self.fam, "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 5, f"Kestrel Transmission Audit Tool - Technical & Operating "
                        f"Manual   |   {self._part}", align="R",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(210, 210, 210)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin,
                  self.get_y())
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font(self.fam, "", 7.5)
        self.set_text_color(*GREY)
        self.cell(0, 5, f"v{__version__}   |   generated "
                        f"{date.today().isoformat()}   |   page "
                        f"{self.page_no()}/{{nb}}", align="C")
        self.set_text_color(0, 0, 0)

    def _reset_x(self):
        self.set_x(self.l_margin)

    # --- content helpers ------------------------------------------------
    def part_title(self, text, subtitle=""):
        self.add_page()
        self._part = text.split(":")[0]
        self.ln(2)
        self.set_fill_color(*BLUE)
        self.set_text_color(255, 255, 255)
        self.set_font(self.fam, "B", 15)
        self.cell(0, 12, "  " + text, fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(2)
        if subtitle:
            self.set_font(self.fam, "", 9.5)
            self.set_text_color(*GREY)
            self.multi_cell(0, 4.8, subtitle, new_x=XPos.LMARGIN,
                            new_y=YPos.NEXT)
            self.set_text_color(0, 0, 0)
            self.ln(2)

    def h1(self, text):
        if self.get_y() > 244:
            self.add_page()
        self._reset_x()
        self.set_font(self.fam, "B", 12.5)
        self.set_text_color(*BLUE)
        self.cell(0, 7.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(0.5)

    def h2(self, text):
        if self.get_y() > 252:
            self.add_page()
        self._reset_x()
        self.set_font(self.fam, "B", 10.5)
        self.cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def para(self, text, size=9.5):
        self._reset_x()
        self.set_font(self.fam, "", size)
        self.multi_cell(0, 4.7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def bullet(self, text, size=9.5):
        self._reset_x()
        self.set_font(self.fam, "", size)
        self.set_x(self.l_margin + 3)
        self.multi_cell(self.epw - 3, 4.7, "-  " + text,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def numbered(self, n, text, size=9.5):
        self._reset_x()
        self.set_font(self.fam, "", size)
        self.set_x(self.l_margin + 3)
        self.multi_cell(self.epw - 3, 4.7, f"{n}.  {text}",
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def step(self, label, text):
        if self.get_y() > 250:
            self.add_page()
        self._reset_x()
        self.set_font(self.fam, "B", 9.8)
        self.set_text_color(*BLUE)
        self.multi_cell(0, 4.8, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.set_font(self.fam, "", 9.5)
        self.set_x(self.l_margin + 3)
        self.multi_cell(self.epw - 3, 4.7, text, new_x=XPos.LMARGIN,
                        new_y=YPos.NEXT)
        self.ln(1.4)

    def formula(self, lines):
        self._reset_x()
        if self.get_y() > 250:
            self.add_page()
        self.set_fill_color(244, 246, 249)
        self.set_draw_color(210, 216, 224)
        self.set_font("Courier", "", 8.7)
        self.set_x(self.l_margin + 2)
        body = "\n".join(lines)
        self.multi_cell(self.epw - 4, 4.6, body, border=1, fill=True,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1.5)

    def table(self, headers, rows, widths, fs=8.3):
        self._reset_x()
        self.set_font(self.fam, "B", fs)
        self.set_fill_color(*BLUE)
        self.set_text_color(255, 255, 255)
        for w, h in zip(widths, headers):
            self.cell(w, 6, h, border=1, fill=True, align="L")
        self.ln()
        self.set_text_color(0, 0, 0)
        self.set_font(self.fam, "", fs)
        fill = False
        for row in rows:
            self.set_fill_color(238, 241, 246)
            for w, val in zip(widths, row):
                self.cell(w, 5.4, " " + str(val), border=1, fill=fill)
            self.ln()
            fill = not fill
        self.ln(2)

    def check(self, text):
        self._reset_x()
        self.set_font(self.fam, "", 9.3)
        self.set_x(self.l_margin + 2)
        self.multi_cell(self.epw - 2, 5.2, "[  ]   " + text,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)


pdf = Manual()

# ============================================================ cover page
pdf.add_page()
pdf.ln(18)
pdf.set_font(pdf.fam, "B", 22)
pdf.set_text_color(*BLUE)
pdf.multi_cell(0, 10, "Audit Sampling & Risk Assessment Tool",
               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_font(pdf.fam, "B", 14)
pdf.set_text_color(0, 0, 0)
pdf.multi_cell(0, 8, "Technical & Operating Manual", new_x=XPos.LMARGIN,
               new_y=YPos.NEXT)
pdf.ln(2)
pdf.set_font(pdf.fam, "", 10)
pdf.set_text_color(*GREY)
pdf.multi_cell(0, 5.5, f"Version {__version__}   |   "
                       f"{date.today().isoformat()}   |   Kestrel Transmission "
                       f"(Kestrel) statutory audit", new_x=XPos.LMARGIN,
               new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)
pdf.ln(8)
pdf.set_font(pdf.fam, "", 10)
pdf.multi_cell(0, 5.2,
               "This manual has two parts. Part A explains HOW THE TOOL "
               "WORKS - the data flow and the exact logic behind risk "
               "scoring, sample sizes, selection, reproducibility and "
               "evaluation, with worked numbers you can reproduce by hand. "
               "Part B is the STEP-BY-STEP OPERATING GUIDE for running an "
               "engagement end to end. Read Part A once to own the "
               "methodology; keep Part B beside you while you work.",
               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(6)
pdf.set_font(pdf.fam, "B", 11)
pdf.cell(0, 7, "Contents", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_font(pdf.fam, "", 9.5)
for line in [
    "Part A - How the tool works",
    "    A1  The big picture: what it turns inputs into",
    "    A2  Where your data lives (storage model)",
    "    A3  Reading the ledger (import & normalization)",
    "    A4  Turning transactions into populations (categorization)",
    "    A5  Scoring risk (SA 315) - the formula, worked",
    "    A6  Deciding 100% vs sample",
    "    A7  How big a sample (SA 530) - attribute & MUS, worked",
    "    A8  Which items, and why it is reproducible",
    "    A9  Evaluating results (Stringer bound), worked",
    "    A10 SERC regulated-revenue reconciliation",
    "    A11 The audit trail and why it is trustworthy",
    "    A12 Architecture map & how correctness is proven",
    "Part B - Operating the tool, step by step",
    "    Getting started, the ten steps, checklist, troubleshooting",
]:
    pdf.set_x(pdf.l_margin + 2)
    pdf.multi_cell(0, 5.0, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

# ==================================================================== PART A
pdf.part_title(
    "Part A - How the tool works",
    "The tool is a small, local pipeline. It never sends data anywhere; it "
    "reads your ledger, applies your professional judgment as parameters, "
    "and produces defensible, reproducible selections and conclusions. This "
    "part opens the engine so you can explain every number in it.")

pdf.h1("A1. The big picture")
pdf.para(
    "Think of the tool as a factory line with eight stations. Each station "
    "takes the previous station's output and adds one thing. Nothing is "
    "hidden: every parameter is one you set, and every result is recomputed "
    "from the stored data on demand.")
pdf.formula([
    "Ledger + Trial balance",
    "      |  (A3 import & normalize, reconcile to TB)",
    "      v",
    "Categorized transactions            <- your rules (A4)",
    "      |  (A5 score each category's risk, SA 315)",
    "      v",
    "Risk scores per population",
    "      |  (A6 split by strategy thresholds)",
    "      +--> 100% verification list (large / risky / contra items)",
    "      +--> sampling populations",
    "                |  (A7 size, A8 select - seeded & reproducible)",
    "                v",
    "          Selected sample items",
    "                |  (you test them; A9 evaluate & project)",
    "                v",
    "          Conclusion: projected misstatement vs tolerable",
    "",
    "SERC tariff order --> (A10) --> regulated-revenue exceptions",
    "Every action above is written to the audit trail (A11).",
])
pdf.para(
    "The guiding principle is separation of judgment from arithmetic: you "
    "supply the judgment (materiality, risk weights, tolerable error, "
    "confidence); the tool supplies only the arithmetic and the "
    "documentation, exactly and repeatably.")

pdf.h1("A2. Where your data lives")
pdf.para(
    "Everything is stored in one file on your machine: "
    "data\\audit_tool.db, a SQLite database. There is no server and no "
    "cloud. Back it up by copying the data folder while the app is closed. "
    "The main tables:")
pdf.table(
    ["Table", "What it holds"],
    [["engagements", "one row per audit (name, FY, control period, master "
      "seed)"],
     ["transactions", "every imported ledger line, with category and "
      "anomaly flags"],
     ["trial_balance", "imported TB used for the completeness reconciliation"],
     ["materiality / risk_config", "your SA 320 figures and SA 315 settings"],
     ["populations", "the analysis-run output: score & strategy per "
      "category"],
     ["samples / sample_items", "each drawn sample, its parameters, and the "
      "selected items + your results"],
     ["evaluations", "the projection/conclusion computed for each sample"],
     ["serc_data", "the tariff-order parameters"],
     ["audit_log", "append-only record of every action (A11)"]],
    [46, 138])

pdf.h1("A3. Reading the ledger (import & normalization)")
pdf.para(
    "SAP and similar exports are messy, so the importer does five things "
    "before it trusts a single number:")
pdf.numbered(1, "Column mapping. It guesses which columns are the posting "
                "date, document number, G/L account, amount, narration, "
                "etc. (the SAP FAGLL03/FBL3N presets), and lets you correct "
                "the guess. You can save a mapping as a reusable template.")
pdf.numbered(2, "Amount parsing. It understands SAP trailing-sign negatives "
                "(1.234,56-), European grouping (1.234,56), Indian grouping "
                "(1,23,456.78) and bracketed negatives ((5,000)). Anything "
                "it cannot parse is listed, not silently dropped.")
pdf.numbered(3, "Sign convention. Internally it uses debit-positive / "
                "credit-negative (the SAP local-currency convention). Income "
                "therefore appears as negative amounts; the tool flips the "
                "sign when it reports income. You confirm the convention at "
                "import.")
pdf.numbered(4, "Validation. It reports rows outside the financial year, "
                "zero amounts, duplicate document numbers, and footer/total "
                "rows it skipped - all recorded in the audit trail with the "
                "file's SHA-256 fingerprint.")
pdf.numbered(5, "Ledger-vs-TB reconciliation. For every account it compares "
                "the sum of ledger movements with the trial-balance movement "
                "(debit - credit, or closing - opening). Any account that "
                "does not tie within Rs 1 is surfaced as a completeness "
                "exception - this is how the planted Rs 500 mismatch in the "
                "demo is caught.")

pdf.h1("A4. Turning transactions into populations (categorization)")
pdf.para(
    "Audit sampling needs homogeneous populations. The categorizer assigns "
    "each transaction to an audit category using an ordered list of rules. "
    "A rule matches on the account code (prefix, numeric range or regex) or "
    "on narration keywords. Rules are tried in priority order and the first "
    "match wins; anything unmatched lands in 'Uncategorized', which you must "
    "clear before analysis. Categories are the populations everything "
    "downstream works on: Electricity income (transmission / wheeling), "
    "R&M, spares, deferred tax, other income, employee costs, overheads, "
    "capital expenditure, and one-offs.")

pdf.h1("A5. Scoring risk (SA 315) - the formula, worked")
pdf.para(
    "For each category the tool computes a risk score from seven factors. "
    "Each factor is scored 0-10, then combined as a weighted average and "
    "clamped to the 1-10 range:")
pdf.formula([
    "               sum( factor_score[i] x factor_weight[i] )",
    "computed = -------------------------------------------------",
    "                       sum( factor_weight[i] )",
])
pdf.para("The seven factors and how each is scored:")
pdf.table(
    ["Factor", "How it is scored", "Default wt"],
    [["Size", "category value vs performance materiality (bucketed 2-10)",
      "2.0"],
     ["Prior qualification", "10 if a prior-year qualification area, else 0",
      "2.0"],
     ["Regulatory", "10 if formula/tariff-driven, else 0", "1.5"],
     ["Control strength", "Weak 10 / Moderate 6 / Strong 2", "1.5"],
     ["Complexity", "High 10 / Medium 6 / Low 2", "1.0"],
     ["Volume", "more, less homogeneous items score higher (2-8)", "0.5"],
     ["New / one-off", "10 if new account or one-off, else 0", "1.5"]],
    [42, 118, 24])
pdf.h2("Worked example - Repairs & maintenance")
pdf.para(
    "R&M is a prior-year qualification area with weak-to-moderate controls "
    "and a very large number of invoices. With the default factor scores "
    "(size 10 because the population exceeds performance materiality, prior "
    "qualification 10, regulatory 0, control 6, complexity 6, volume 8, "
    "new/one-off 0):")
pdf.formula([
    "weighted sum = 10x2.0 + 10x2.0 + 0x1.5 + 6x1.5 + 6x1.0"
    " + 8x0.5 + 0x1.5",
    "             = 20 + 20 + 0 + 9 + 6 + 4 + 0  =  59",
    "sum of weights = 2.0+2.0+1.5+1.5+1.0+0.5+1.5 = 10.0",
    "computed score = 59 / 10.0 = 5.9",
])
pdf.para(
    "The tool also lets you assign a weight directly. R&M carries an "
    "assigned weight of 8 (reflecting the prior-year dispute), and the "
    "assigned weight prevails over the computed one, so the final score is "
    "8.0. The computed 5.9 is still shown beside it, so a reviewer sees both "
    "the model's view and your judgment. You may override any factor, weight "
    "or the assigned weight - but every change requires a reason that is "
    "logged.")

pdf.h1("A6. Deciding 100% vs sample")
pdf.para(
    "The final score maps to a strategy through two configurable "
    "thresholds (defaults shown). This is the SA 530 idea that high-value "
    "or high-risk items are examined in full while the rest are sampled:")
pdf.table(
    ["Final score", "Strategy", "Meaning"],
    [["score >= 8", "FULL (or HYBRID)", "verify the whole category 100%; "
      "HYBRID if a cutoff is set - items above it 100%, the rest sampled"],
     ["4 <= score < 8", "SAMPLE", "sample by the preferred method (MUS or "
      "stratified)"],
     ["score < 4", "SAMPLE_LOW", "small random sample at the floor size"]],
    [30, 40, 114])
pdf.para(
    "Three escalations override the strategy and force an item to the 100% "
    "list regardless of its category's score: (a) any item at or above the "
    "individually-significant cutoff from the SA 320 worksheet; (b) any "
    "abnormal-side 'contra' entry (e.g. a debit posted to an income "
    "account - like the credit notes planted in the demo); and (c) in a "
    "HYBRID category, any item above the category cutoff. The output is two "
    "lists: everything to verify in full, and the leftover sampling "
    "population per category.")

pdf.h1("A7. How big a sample (SA 530) - attribute & MUS, worked")
pdf.h2("Attribute sampling (tests of controls / occurrence)")
pdf.para(
    "The tool finds the smallest sample size n such that, if you see no "
    "more than the planned number of deviations, the true deviation rate "
    "still sits at or below your tolerable rate at the chosen confidence. "
    "It uses the exact binomial distribution, which reproduces the "
    "published ICAI/AICPA tables. For 95% confidence, 5% tolerable, 0% "
    "expected:")
pdf.formula([
    "find smallest n with  (1 - 0.05)^n <= 1 - 0.95 = 0.05",
    "0.95^58 = 0.0511  (> 0.05, not enough)",
    "0.95^59 = 0.0485  (<= 0.05, sufficient)   ->   n = 59",
])
pdf.h2("Monetary unit sampling (substantive tests of value)")
pdf.para(
    "MUS gives every rupee an equal chance of selection, so larger items "
    "are proportionately more likely to be picked. The size uses a Poisson "
    "reliability factor (RF) and an expansion factor (EF):")
pdf.formula([
    "         BV x RF                              BV",
    "n = ceil(---------------)          interval J = ----",
    "         TM - EM x EF                            n",
    "",
    "BV = population book value   TM = tolerable misstatement",
    "EM = expected misstatement   RF,EF depend on confidence",
])
pdf.para("Worked example at 95% confidence (RF = 3.00, EF = 1.6):")
pdf.formula([
    "BV = 50,00,000   TM = 2,50,000   EM = 50,000",
    "n = ceil( 50,00,000 x 3.00 / (2,50,000 - 50,000 x 1.6) )",
    "  = ceil( 1,50,00,000 / (2,50,000 - 80,000) )",
    "  = ceil( 1,50,00,000 / 1,70,000 ) = ceil(88.2) = 89",
    "interval J = 50,00,000 / 89 = ~56,180",
])
pdf.para(
    "The reliability factors themselves (3.00 at 0 errors, 4.75 at 1, 6.30 "
    "at 2, for 95%) are not looked up from a hard-coded table - the tool "
    "solves the Poisson equation for them, so they are exact and match the "
    "published figures. If expected misstatement is too close to tolerable "
    "(EM x EF >= TM), the tool refuses to size a sample and tells you to "
    "extend substantive procedures instead - sampling would not be valid "
    "there.")

pdf.h1("A8. Which items, and why it is reproducible")
pdf.para(
    "Reproducibility is what makes a computer-drawn sample defensible in "
    "the file: anyone can re-run it and get the identical selection. The "
    "tool guarantees this with four devices:")
pdf.bullet("Canonical sort. Before selecting, the population is always "
           "sorted the same way: by date, then document number, then import "
           "row id. Selection is deterministic given that order.")
pdf.bullet("Derived seed. Each engagement gets one random master seed at "
           "creation. Every sample's seed is derived from it as "
           "seed = first 4 bytes of SHA-256(master seed | category | "
           "generation number). So the seed is fixed, documented, and "
           "different for each category and re-draw.")
pdf.bullet("Named generator. Selection uses numpy's PCG64 generator "
           "(default_rng(seed)); the same seed yields the same draws on any "
           "machine.")
pdf.bullet("Dataset fingerprint. A SHA-256 hash of the population's "
           "identifying columns is stored with the sample, so you can prove "
           "the selection belongs to that exact population.")
pdf.h2("How MUS actually picks items")
pdf.para(
    "The tool lays every rupee end to end (a cumulative total), picks a "
    "random start between 0 and the interval J, then steps in fixed jumps "
    "of J and selects whichever transaction each landing point falls in. "
    "Because any item whose value is at least J spans a whole interval, it "
    "must contain a landing point - so every item >= J is mathematically "
    "guaranteed to be selected (the 'top stratum', examined 100%). Smaller "
    "items are selected in proportion to their size. Zero and negative "
    "(contra) items cannot take part and are split off for separate review.")

pdf.h1("A9. Evaluating results (Stringer bound), worked")
pdf.para(
    "After you test the selected items and enter the audited value for any "
    "that are wrong, the tool projects the error to the whole population. "
    "For MUS it computes an upper misstatement limit (UML) - the "
    "conservative Stringer bound - and compares it with tolerable "
    "misstatement. UML has four parts:")
pdf.formula([
    "taint of an item   t = (book - audited) / book",
    "projected error    = sum( t ) x interval J",
    "basic precision    = RF(0 errors) x J",
    "incremental        = sum over ranked taints of",
    "  allowance          t x J x (RF_next - RF_prev - 1)",
    "top-stratum actual = real misstatement in items examined 100%",
    "",
    "UML = top-stratum actual + projected + basic precision",
    "      + incremental allowance",
])
pdf.para(
    "Worked example. A sample has three lower-stratum items with book "
    "values 1,000 / 2,000 / 3,000 audited at 500 / 1,600 / 3,000, plus one "
    "top-stratum item of 50,000 audited at 49,000; interval J = 10,000, "
    "95% confidence (RF0 = 3.00, RF1 = 4.75, RF2 = 6.30):")
pdf.formula([
    "taints: 500/1000 = 0.5,  400/2000 = 0.2,  0/3000 = 0",
    "projected      = (0.5 + 0.2) x 10,000            = 7,000",
    "top-stratum    = 50,000 - 49,000                 = 1,000",
    "basic precision= 3.00 x 10,000                   = 30,000",
    "incremental    = 0.5x10,000x(4.75-3.00-1)  = 3,750",
    "               + 0.2x10,000x(6.30-4.75-1)  = 1,100  = 4,850",
    "UML = 1,000 + 7,000 + 30,000 + 4,850       = 42,850",
])
pdf.para(
    "If tolerable misstatement is, say, 60,000, then UML 42,850 <= 60,000 "
    "and the population is accepted at 95% confidence. If UML exceeded "
    "tolerable, the tool flags it red - extend procedures, seek an "
    "adjustment, or reassess risk (SA 530.12-13). Understatements are "
    "reported separately so they are never netted off. For non-MUS samples "
    "the tool instead shows the ratio projection (error rate by value x "
    "population value) and the difference projection (mean error x item "
    "count), plus the achieved upper deviation limit for attribute tests.")

pdf.h1("A10. SERC regulated-revenue reconciliation")
pdf.para(
    "Electricity income is formula-driven by the SERC MYT order, so it is "
    "cross-checked rather than merely sampled. You enter the approved "
    "annual transmission charges, wheeling, true-up and incentive. The tool "
    "then:")
pdf.formula([
    "monthly expected  = approved annual charges / 12",
    "monthly variance% = (booked - expected) / expected x 100",
    "flag month if |variance%| > your threshold (default 1%)",
    "",
    "annual tie-out:",
    "  expected = ATC + wheeling + true-up + incentive",
    "  difference = booked electricity income - expected",
])
pdf.para(
    "Flagged months (in the demo: the +2% February billing, the September "
    "true-up and the March incentive) are carried to the exceptions list "
    "for you to vouch against SERC billing statements, true-up orders and "
    "meter data. The wheeling line, billed at a clean 1/12, should show no "
    "exceptions - a control check on the reconciliation itself.")

pdf.h1("A11. The audit trail and why it is trustworthy")
pdf.para(
    "Every meaningful action - login, import (with file hash), "
    "categorization, each risk-config change (with your typed reason), each "
    "sample generation (with method, parameters and seed), results entry, "
    "evaluation and export - is written to the audit_log table with your "
    "user name, role and a timestamp. The application has no code path that "
    "updates or deletes those rows; it can only append. That is what lets "
    "the workpaper pack carry a complete, tamper-evident trail satisfying "
    "SA 230, and it is why a superseded (re-drawn) sample and its "
    "justification remain visible rather than disappearing.")

pdf.h1("A12. Architecture map & how correctness is proven")
pdf.para("If you ever hand this to an IT reviewer, the code is organized "
         "by responsibility:")
pdf.table(
    ["Location", "Responsibility"],
    [["app.py", "login gate, engagement switcher, workflow router"],
     ["core/sampling/", "the maths: factors (Poisson RF), sizes (binomial "
      "& MUS), select, evaluate"],
     ["core/", "importer, categorizer, materiality, risk engine, anomalies, "
      "serc, sampling_service"],
     ["storage/", "db (SQLite schema), auth (scrypt passwords), auditlog "
      "(append-only)"],
     ["reports/", "excel_pack (workpaper pack), pdf_memo (memorandum)"],
     ["ui/", "one module per workflow step"],
     ["tests/", "38 automated tests"]],
    [34, 150])
pdf.para(
    "Correctness is not asserted, it is tested. The 38 tests check the "
    "reliability factors against the published tables, the attribute sizes "
    "(59 / 22 / 93), the MUS worked example (n = 89), that the same seed "
    "reproduces the identical selection for every method, that every MUS "
    "item >= the interval is selected, that stratification exactly "
    "partitions the population, that SAP number formats parse correctly, "
    "that the TB reconciliation catches a planted mismatch, that the "
    "Stringer arithmetic matches the hand calculation above, and a full "
    "end-to-end run on the demo data through both reports - plus a UI smoke "
    "test that every screen renders. You can re-run them any time with "
    ".venv\\Scripts\\python -m pytest tests -q.")

# ==================================================================== PART B
pdf.part_title(
    "Part B - Operating the tool, step by step",
    "Keep this part open while you work. Each step's output feeds the next, "
    "so work top to bottom. Roles: Staff can import, categorize, run the "
    "analysis, draw the first sample and record results; Manager+ sets "
    "materiality, risk configuration and SERC parameters and can regenerate "
    "or finalize samples; Partner manages users and can archive an "
    "engagement.")

pdf.h1("Getting started")
pdf.bullet('Launch the app: double-click the Desktop shortcut "Kestrel Transmission '
           'Audit Tool" (or run_tool.bat). Your browser opens at '
           "http://localhost:8501. There is no Deploy button by design - "
           "the app is deliberately local so client data never leaves this "
           "machine.")
pdf.bullet("First run only: create the Partner (administrator) account when "
           "prompted. Add colleagues later in step 11.")
pdf.bullet("Practice first on the demo data: run  .venv\\Scripts\\python "
           "demo\\generate_demo_data.py  and import the three files it "
           "writes to demo\\output. The README lists every planted issue "
           "and where it should appear - a built-in self-check.")

pdf.h1("The eleven steps")
pdf.step("Step 1 - Engagement & materiality (SA 320)",
         "Create the engagement (company, financial year, control period). "
         "Note the engagement master seed in the caption - it anchors every "
         "sample seed and is printed on every report. Fill the materiality "
         "worksheet: benchmark and percentage, performance materiality % "
         "(default 75%), and the individually-significant cutoff (0 = use "
         "performance materiality). Save; a green banner confirms and the "
         "three amounts appear. Duplicate engagement names are blocked, and "
         "the sidebar lists engagements as #id - name so you always know "
         "which one you are on.")
pdf.step("Step 2 - Data import",
         "Ledger tab: upload the SAP export, pick sheet and header row, "
         "check the auto-guessed column mapping (date, document number, G/L "
         "account and amount are mandatory), confirm the sign convention "
         "(SAP = debits positive), then Validate & import. The file hash "
         "and any skipped or unparseable rows are reported and logged. TB "
         "tab: import the trial balance the same way. Then read the "
         "ledger-vs-TB reconciliation at the bottom - every account should "
         "tie within Rs 1; investigate any mismatch before you rely on the "
         "ledger.")
pdf.step("Step 3 - Categorize",
         "Review and edit the mapping rules (account prefix/range/regex or "
         "narration keywords; first match by priority wins), click Apply, "
         "then clear the Uncategorized bucket by assigning any unmapped "
         "account codes to a category. Proceed only when nothing is "
         "uncategorized.")
pdf.step("Step 4 - Risk configuration (SA 315)",
         "Review the pre-loaded assigned weights (electricity income 10, "
         "spares & deferred tax 9, R&M 8, down to overheads 3) and the "
         "control/complexity factors, cutoffs and preferred methods. Adjust "
         "the 100%/sample thresholds if needed. Every save needs a reason, "
         "which is logged (Manager+).")
pdf.step("Step 5 - Analysis run",
         "Click once. The tool scores every population, splits the 100% "
         "list from the sampling populations, and stamps anomaly flags "
         "(duplicates, round sums, period-end, weekend, keywords, contra, "
         "zero). Review the population table, the 100% list and the flags "
         "before sampling.")
pdf.step("Step 6 - Sampling (SA 530)",
         "For each sampling population, pick the method and confidence and "
         "enter tolerable/expected error; the tool shows the computed size "
         "and (for MUS) the interval. Generate, review the selection, "
         "download the CSV if wanted, and Mark final (Manager+). Re-drawing "
         "supersedes the previous sample and requires a typed justification "
         "- both are kept in the trail.")
pdf.step("Step 7 - SERC reconciliation",
         "Enter (or upload as a Parameter | Value file) the approved "
         "transmission charges, wheeling, true-up, incentive and the "
         "variance threshold. Review the monthly variances and the annual "
         "tie-out; vouch every flagged month to SERC billing records, "
         "true-up orders and meter data.")
pdf.step("Step 8 - Balance confirmations (SA 505)",
         "Per area (receivables, payables, banks, loans & advances): import "
         "the party-wise SAP balance export and the balances the parties "
         "confirmed in writing, check the matching (party code first, "
         "normalized name as fallback; set Invert if parties confirm the "
         "mirror image), then work the grid: exceptions per SA 505.14, "
         "alternative procedures for non-responses per SA 505.12, and "
         "'Not in books' rows as completeness signals. Record a conclusion "
         "per party and download the working-paper CSV.")
pdf.step("Step 9 - Results & evaluation",
         "Do the actual testing outside the tool, then record each item as "
         "Pass or Exception with the audited value where it differs - either "
         "in the in-app grid or by filling the sample tabs of the exported "
         "Excel pack and re-importing it. Run the evaluation to get the "
         "projection and the accept/reject conclusion (green = within "
         "tolerable, red = act).")
pdf.step("Step 10 - Reports & export",
         "Generate the Excel workpaper pack (cover & sign-off, materiality, "
         "risk matrix, 100% list, a tab per sample with its full parameter "
         "box, evaluation, SERC recon, a tab per confirmation area, "
         "exceptions, audit trail) and the PDF sampling memorandum. Copies "
         "are archived automatically under data\\exports; CSV extracts are "
         "available too.")
pdf.step("Step 11 - Admin & audit trail",
         "Partner: add or deactivate users. Everyone: filter and export the "
         "append-only audit trail into the audit file.")

pdf.h1("End-to-end delivery checklist")
for item in [
    "Engagement created; master seed noted on file",
    "Materiality saved (benchmark, overall, performance, ISL cutoff)",
    "Ledger imported; file hash logged; validation warnings resolved",
    "TB imported; ledger-vs-TB reconciliation clean or explained",
    "Zero uncategorized transactions",
    "Risk configuration reviewed; every change carries a logged reason",
    "Analysis run; per-population strategies approved (Manager)",
    "100% list reviewed; anomaly flags dispositioned",
    "Samples generated and finalized; parameters and seeds on record",
    "SERC parameters entered; monthly exceptions and annual tie-out "
    "investigated",
    "Balance confirmations matched; exceptions investigated and "
    "non-responses covered by alternative procedures (SA 505)",
    "Testing performed; results recorded (in-app or Excel round-trip)",
    "Evaluations run; projection vs tolerable documented",
    "Excel workpaper pack generated and filed",
    "PDF memorandum signed: Preparer / Reviewer / Partner",
    "Audit trail exported to the audit file",
    "data folder backed up to secure firm storage",
]:
    pdf.check(item)
pdf.ln(1)

pdf.h1("Troubleshooting & good practice")
pdf.bullet('"Materiality not set yet" although you saved it: you are "'
           "probably on a different engagement - check the #id in the "
           "sidebar. Materiality is per engagement.")
pdf.bullet('"Already exists" when creating an engagement: select the '
           "existing one in the sidebar rather than re-creating it.")
pdf.bullet('MUS says expected is too close to tolerable: sampling is not '
           "valid at those parameters - lower the expectation with evidence "
           "or extend substantive procedures.")
pdf.bullet("Never re-draw a sample just to get a 'nicer' selection - the "
           "old sample and your justification stay in the trail, as they "
           "should.")
pdf.bullet("The tool computes and documents; you conclude. Weights, "
           "parameters and final judgments remain yours under the Standards "
           "on Auditing.")

out = Path(__file__).resolve().parent / "Kestrel_Audit_Tool_Manual.pdf"
out.write_bytes(bytes(pdf.output()))
print(f"written: {out}  ({out.stat().st_size:,} bytes, "
      f"{pdf.pages_count} pages)")
