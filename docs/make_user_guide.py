"""Generate the compact end-to-end user guide PDF.

Run:  .venv\\Scripts\\python docs\\make_user_guide.py
Writes docs/Kestrel_Audit_Tool_User_Guide.pdf
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


class Guide(FPDF):
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
        self.set_auto_page_break(True, margin=16)
        self.alias_nb_pages()

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font(self.fam, "", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 5, "Kestrel Transmission Audit Tool - User Guide", align="R",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def footer(self):
        self.set_y(-13)
        self.set_font(self.fam, "", 7.5)
        self.set_text_color(130, 130, 130)
        self.cell(0, 5, f"v{__version__}  |  page {self.page_no()}/{{nb}}",
                  align="C")
        self.set_text_color(0, 0, 0)

    def h1(self, text):
        if self.get_y() > 245:
            self.add_page()
        self.set_font(self.fam, "B", 13)
        self.set_text_color(*BLUE)
        self.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(0.5)

    def h2(self, text):
        if self.get_y() > 255:
            self.add_page()
        self.set_font(self.fam, "B", 10.5)
        self.cell(0, 6.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def para(self, text, size=9.5):
        self.set_font(self.fam, "", size)
        self.multi_cell(0, 4.8, text)
        self.ln(1)

    def bullet(self, text, size=9.5):
        self.set_font(self.fam, "", size)
        self.set_x(self.l_margin + 3)
        self.multi_cell(self.epw - 3, 4.8, "-  " + text)

    def step(self, label, text):
        self.set_font(self.fam, "B", 9.5)
        self.multi_cell(0, 4.8, label)
        self.set_font(self.fam, "", 9.5)
        self.set_x(self.l_margin + 3)
        self.multi_cell(self.epw - 3, 4.8, text)
        self.ln(1.2)

    def table(self, headers, rows, widths):
        self.set_font(self.fam, "B", 8.5)
        self.set_fill_color(*BLUE)
        self.set_text_color(255, 255, 255)
        for w, h in zip(widths, headers):
            self.cell(w, 6, h, border=1, fill=True)
        self.ln()
        self.set_text_color(0, 0, 0)
        self.set_font(self.fam, "", 8.5)
        for row in rows:
            for w, val in zip(widths, row):
                self.cell(w, 5.5, str(val), border=1)
            self.ln()
        self.ln(2)

    def check(self, text):
        self.set_font(self.fam, "", 9.5)
        self.set_x(self.l_margin + 2)
        self.multi_cell(self.epw - 2, 5.4, "[  ]   " + text)


pdf = Guide()
pdf.add_page()

# ------------------------------------------------------------------ cover
pdf.ln(4)
pdf.set_font(pdf.fam, "B", 19)
pdf.set_text_color(*BLUE)
pdf.multi_cell(0, 9, "Audit Sampling & Risk Assessment Tool",
               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_font(pdf.fam, "B", 13)
pdf.multi_cell(0, 7, "User Guide - functions and step-by-step methodology",
               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)
pdf.set_font(pdf.fam, "", 9.5)
pdf.multi_cell(0, 5, f"Version {__version__}  |  {date.today().isoformat()}"
                     f"  |  Kestrel Transmission statutory audit",
               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(3)
pdf.para(
    "The tool implements a risk-based audit of a SERC-regulated transmission "
    "utility on your own machine: risk assessment per SA 315 (Revised), "
    "materiality per SA 320, statistically valid and fully reproducible "
    "audit sampling per SA 530, regulated-revenue cross-checks against the "
    "SERC MYT tariff order, and an append-only audit trail with exportable "
    "workpapers per SA 230. Revenue context: Ind AS 115 (electricity and "
    "contract income), Ind AS 109 (interest), Ind AS 16 (capital spares - "
    "prior-year qualification area). All data stays on this machine; the "
    "app serves only at http://localhost:8501.")
pdf.h1("The workflow at a glance")
pdf.para(
    "1  Engagement & materiality   ->   2  Data import   ->   "
    "3  Categorize   ->   4  Risk configuration   ->   5  Analysis run   ->  "
    " 6  Sampling   ->   7  SERC reconciliation   ->   8  Results & "
    "evaluation   ->   9  Reports & export   ->   10  Admin & audit trail")
pdf.para(
    "Golden rule: work top to bottom. Each step's output is the next "
    "step's input, and every action is logged with your user name in the "
    "SA 230 audit trail.")

# ---------------------------------------------------------- getting started
pdf.h1("1. Getting started")
pdf.bullet('Launch: double-click the Desktop shortcut "Kestrel Transmission Audit '
           'Tool" (or run_tool.bat in the project folder). The browser '
           "opens at http://localhost:8501.")
pdf.bullet("First run: the tool asks you to create the Partner "
           "(administrator) account. Add Manager/Staff colleagues later in "
           "step 11; passwords are stored as scrypt hashes locally.")
pdf.bullet("Practice safely first: generate the synthetic dataset with  "
           ".venv\\Scripts\\python demo\\generate_demo_data.py  and use the "
           "three files in demo\\output. The README lists every planted "
           "artefact and where it should surface - a self-check of the "
           "tool.")
pdf.bullet("Data location: data\\audit_tool.db (database) and "
           "data\\exports (archived reports). Back up by copying the data "
           "folder with the app closed. Never commit or email client "
           "data.")
pdf.ln(1)
pdf.h2("Roles")
pdf.table(
    ["Action", "Staff", "Manager", "Partner"],
    [["Import, categorize, analysis, first sample, results", "yes", "yes",
      "yes"],
     ["Materiality, risk config, SERC, regenerate/finalize", "-", "yes",
      "yes"],
     ["User administration, archive engagement", "-", "-", "yes"]],
    [104, 22, 22, 22])

# ------------------------------------------------------------ step by step
pdf.h1("2. Step-by-step methodology (end to end)")

pdf.step("Step 1 - Engagement & materiality (SA 320)",
         "Create the engagement (company, FY, control period). Note the "
         "engagement master seed shown in the caption - it is printed on "
         "every report and all sample seeds derive from it. Complete the "
         "materiality worksheet: pick a benchmark and percentage (guidance "
         "ranges shown), performance materiality % (default 75%) and the "
         "individually-significant item cutoff (0 = use PM). Save - a green "
         "banner confirms, and the three computed amounts appear. "
         "Duplicate engagement names are blocked; the sidebar shows every "
         "engagement as #id - name.")
pdf.step("Step 2 - Data import",
         "Ledger tab: upload the SAP export (Excel/CSV), choose sheet and "
         "header row, review the auto-guessed column mapping (date, "
         "document no., G/L account, amount are mandatory), confirm the "
         "sign convention (SAP = debits positive), then Validate & import. "
         "The file's SHA-256, skipped footer rows and unparseable rows are "
         "reported and logged. TB tab: upload the trial balance the same "
         "way. Then review the ledger-vs-TB reconciliation at the bottom - "
         "every account should tie within Rs 1; investigate any mismatch "
         "before relying on the ledger (completeness assertion).")
pdf.step("Step 3 - Categorize",
         "Rules map transactions to audit populations by account-code "
         "prefix/range/regex or narration keywords; first match by "
         "priority wins. Apply rules, then clear the Uncategorized bucket: "
         "select unmapped account codes, pick the category, and the tool "
         "creates the rules and re-applies. Proceed only at zero "
         "uncategorized items.")
pdf.step("Step 4 - Risk configuration (SA 315)",
         "Review the per-category assigned weights (1-10) pre-loaded for "
         "this engagement: electricity income 10, spares & deferred tax 9 "
         "(prior-year qualifications), R&M 8 with a hybrid cutoff, down to "
         "overheads 3. Set control strength, complexity, cutoffs "
         "(fixed Rs or % of PM) and the preferred sampling method. "
         "Thresholds: score >= 8 -> 100% verification (or hybrid where a "
         "cutoff exists); 4-8 -> stratified/MUS; below 4 -> small random "
         "sample. Every save requires a reason, which is logged (Manager+).")
pdf.step("Step 5 - Analysis run",
         "One click scores every population (your assigned weight "
         "prevails; the factor-computed score is shown alongside), splits "
         "each category into the 100% verification list and a sampling "
         "population, and stamps anomaly flags: DUPLICATE, ROUND, "
         "PERIOD_END, WEEKEND, KEYWORD, CONTRA (abnormal side - "
         "auto-routed to 100%), ZERO. Individually significant items "
         "(>= the SA 320 cutoff) always go to the 100% list. Review the "
         "population table, the 100% list and the flags before sampling.")
pdf.step("Step 6 - Sampling (SA 530)",
         "Per population: choose the method and confidence. MUS - enter "
         "tolerable and expected misstatement; the tool shows n, the "
         "reliability and expansion factors and the sampling interval "
         "(items >= the interval are top stratum, examined in full). "
         "Other methods - enter tolerable/expected deviation rates for an "
         "attribute-based n (finite-population corrected); stratified adds "
         "value bands and allocation. The seed is auto-derived from the "
         "master seed (Manager+ may set one manually, e.g. to re-draw a "
         "prior selection). Generate, review the selection, download the "
         "CSV if needed, and Mark final (Manager+). Re-generating "
         "supersedes the old sample and requires a typed justification - "
         "both are logged.")
pdf.step("Step 7 - SERC reconciliation",
         "Enter (or upload as a Parameter|Value file) the tariff-order "
         "figures: approved annual transmission charges, wheeling, "
         "true-up, incentive, and the monthly variance threshold. The tool "
         "compares booked electricity income by month against 1/12 of the "
         "approved value, flags breaches, and ties out the year: booked vs "
         "(order +/- true-up +/- incentive). Vouch flagged months to SERC "
         "billing statements, true-up orders and meter data.")
pdf.step("Step 8 - Balance confirmations (SA 505)",
         "Per area (trade receivables, trade payables, bank balances, "
         "loans & advances): import the party-wise SAP balance export "
         "(FBL5N/FBL1N style - open items collapse to one balance per "
         "party) and the balances confirmed in writing by the parties, "
         "each with flexible column mapping. The tool matches on party "
         "code (SAP leading zeros ignored), falling back to the normalized "
         "name, and classifies every party: Agreed (within the rupee "
         "tolerance), Exception (investigate per SA 505.14 - timing, "
         "dispute or misstatement), No response (alternative procedures "
         "per SA 505.12), or Not in books (a completeness signal). If "
         "parties confirm from their own perspective, switch the sign "
         "setting to Invert. Review coverage and response statistics, "
         "record a conclusion and remarks per party, and download the "
         "working-paper CSV; everything re-surfaces in the Excel pack.")
pdf.step("Step 9 - Results & evaluation",
         "Perform the testing outside the tool (vouching, recomputation, "
         "SERC cross-checks), then record outcomes: mark each sampled item "
         "Pass or Exception and enter the audited value where it differs "
         "(misstatement = book - audited). Enter in-app, or fill the "
         "sample tabs of the exported Excel pack and re-import it (a "
         "hidden _meta sheet maps tabs to samples). Run the evaluation: "
         "MUS gives the Stringer bound - most likely misstatement and the "
         "upper misstatement limit vs tolerable; other methods give ratio "
         "and difference projections plus the achieved upper deviation "
         "limit. Green = acceptable; red = extend procedures, seek "
         "adjustment, or reassess risk (SA 530.12-13).")
pdf.step("Step 10 - Reports & export",
         "Generate the Excel workpaper pack (cover & sign-off, "
         "materiality, risk matrix, 100% list, one tab per sample with the "
         "full parameter box - method, seed, interval, dataset SHA-256 - "
         "evaluation, SERC reconciliation, one tab per SA 505 confirmation "
         "area, exceptions, audit trail) and the PDF sampling memorandum "
         "(SA 315/320/530/230 narrative with conclusions and sign-off "
         "blocks). Copies are archived under data\\exports automatically; "
         "CSV extracts are available for the 100% list and the audit "
         "trail.")
pdf.step("Step 11 - Admin & audit trail",
         "Partner: add users, deactivate leavers. Everyone: filter and "
         "export the append-only audit trail - every import (with file "
         "hash), configuration change (with reason), sample generation "
         "(with seed), result entry and export is there. The application "
         "cannot update or delete trail rows.")

# ------------------------------------------------------- methodology ref
pdf.h1("3. Sampling methodology reference")
pdf.h2("Sample sizes")
pdf.bullet("Attribute (tests of controls): smallest n such that observing "
           "k or fewer deviations still supports 'true rate <= tolerable "
           "rate' at the chosen confidence - exact binomial, reproducing "
           "the published ICAI/AICPA tables.")
pdf.bullet("MUS (substantive):  n = ceiling( BV x RF / (TM - EM x EF) ),  "
           "interval J = BV / n. Worked example: BV 50,00,000, TM "
           "2,50,000, EM 50,000 at 95% -> n = 89, J ~ 56,180.")
pdf.table(
    ["Confidence", "RF (0 errors)", "Expansion factor",
     "Attribute n (5% tol, 0% exp)"],
    [["90%", "2.31", "1.5", "45"],
     ["95%", "3.00", "1.6", "59"],
     ["99%", "4.61", "1.9", "90"]],
    [40, 40, 45, 60])
pdf.h2("Selection and reproducibility")
pdf.bullet("Methods: simple random (with/without replacement), systematic "
           "(seeded random start; mind interval-pattern risk, SA 530 A13), "
           "stratified by value bands (top band censused when warranted), "
           "MUS fixed-interval over cumulative value (every item >= J is "
           "mathematically guaranteed selection).")
pdf.bullet("Reproducibility: numpy PCG64 generator; seed derived from the "
           "engagement master seed + category + generation number; "
           "canonical sort (date, document no., row id); population "
           "SHA-256 recorded. Same seed = identical selection, always "
           "re-derivable for the audit file.")
pdf.h2("Evaluation")
pdf.bullet("MUS Stringer bound: UML = top-stratum actual + "
           "sum(taintings) x J (projected) + RF0 x J (basic precision) + "
           "incremental allowance from ranked taintings. Conclude "
           "acceptable when UML <= tolerable misstatement; "
           "understatements are reported separately.")
pdf.bullet("Classical: ratio projection (error rate by value x population "
           "value) and difference projection (mean error x population "
           "count) - both shown.")
pdf.bullet("Attribute: achieved upper deviation limit vs tolerable rate. "
           "Note: a judgmental n of 30 with zero deviations supports only "
           "~9.5% at 95% confidence - the tool reports this honestly; use "
           "the computed n when you need a specific assurance level.")

# ------------------------------------------------------------- checklist
pdf.h1("4. End-to-end delivery checklist")
for item in [
    "Engagement created; master seed noted on file",
    "Materiality worksheet saved (benchmark, OM, PM, ISL cutoff)",
    "Ledger imported; SHA-256 logged; validation warnings resolved",
    "TB imported; ledger-vs-TB reconciliation clean or explained",
    "Zero uncategorized transactions",
    "Risk configuration reviewed; every change carries a logged reason",
    "Analysis run; strategies per population approved (Manager)",
    "100% list reviewed; anomaly flags dispositioned",
    "Samples generated and finalized; parameters and seeds on record",
    "SERC parameters from tariff order; monthly exceptions investigated; "
    "annual tie-out explained",
    "Testing performed; results recorded (in-app or Excel round-trip)",
    "Evaluations run; UML vs TM conclusions documented",
    "Excel workpaper pack generated and filed",
    "PDF sampling memorandum signed: Preparer / Reviewer / Partner",
    "Audit trail exported to the audit file",
    "data folder backed up to the firm's secure storage",
]:
    pdf.check(item)
pdf.ln(2)

# -------------------------------------------------------- troubleshooting
pdf.h1("5. Troubleshooting & good practice")
pdf.bullet('"Materiality not set yet" while you saved it: check the '
           "engagement #id in the sidebar - you may be on a different "
           "engagement. Materiality is per engagement.")
pdf.bullet('"Already exists" when creating an engagement: select the '
           "existing entry in the sidebar instead of re-creating it.")
pdf.bullet('"Expected misstatement too close to tolerable" (MUS): '
           "sampling is not appropriate at those parameters - lower the "
           "expectation with evidence, or extend substantive procedures.")
pdf.bullet("No Deploy button: by design. The app is local-only for client "
           "confidentiality; see README > Deployment & sharing for the "
           "trusted-LAN option.")
pdf.bullet("Regeneration discipline: never re-draw a sample to get a "
           '"nicer" selection - the justification and superseded sample '
           "remain in the audit trail, as they should.")
pdf.bullet("The tool computes and documents; the auditor concludes. "
           "Weights, parameters and final conclusions remain professional "
           "judgment under the SAs.")

out = Path(__file__).resolve().parent / \
    "Kestrel_Audit_Tool_User_Guide.pdf"
out.write_bytes(bytes(pdf.output()))
print(f"written: {out}  ({out.stat().st_size:,} bytes, "
      f"{pdf.pages_count} pages)")
