"""Generate a synthetic Kestrel Transmission-style FY2025-26 dataset in SAP export
format: ledger line items, trial balance and SERC tariff-order parameters.

Planted teaching artefacts (all intentional, see README):
  - Feb-2026 transmission billing +2% (monthly SERC variance exception)
  - Sep-2025 true-up credit of Rs 120 cr and Mar-2026 incentive of Rs 15 cr
  - two credit notes debited to transmission income (contra entries)
  - duplicate, round-sum and keyword-flagged R&M invoices; March spike
  - spares capitalization adjustments > performance materiality (Ind AS 16
    prior-qualification area) including one credit-side reversal
  - trial balance mismatch of Rs 500 in account 75103 (completeness check)

Run:  python demo/generate_demo_data.py
Writes demo/output/*.xlsx (gitignored). Deterministic (seeded).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260712
OUT_DIR = Path(__file__).resolve().parent / "output"

FY_START = date(2025, 4, 1)
FY_END = date(2026, 3, 31)
MONTHS = pd.period_range("2025-04", "2026-03", freq="M")

ATC = 48_000_000_000.0          # approved annual transmission charges (Rs)
WHEELING_ANNUAL = 240_000_000.0
TRUEUP = 1_200_000_000.0
INCENTIVE = 150_000_000.0

ACCOUNT_NAMES = {
    "61101": "Transmission charges - InSTS",
    "61102": "Wheeling charges",
    "62101": "Interest on fixed deposits",
    "62201": "Delayed payment surcharge",
    "62301": "Consultancy & supervision fees",
    "62401": "Sale of scrap",
    "62501": "Miscellaneous income",
    "62901": "One-time receipts",
    "71101": "R&M - Transmission lines",
    "71102": "R&M - Substations",
    "71103": "R&M - Civil & buildings",
    "71104": "R&M - Vehicles",
    "72101": "Salaries & allowances",
    "72102": "Staff welfare expenses",
    "73101": "Stores & spares consumed",
    "73102": "Spares capitalization adjustment",
    "74101": "Deferred tax adjustment",
    "75101": "Vehicle hire charges",
    "75102": "Printing & stationery",
    "75103": "Telephone & internet",
    "75104": "Travel & conveyance",
    "75105": "Security services",
    "75106": "Office electricity",
    "15101": "CWIP - Transmission projects",
}

USERS = ["APATIL", "RKULKARNI", "SDESHMUKH", "VJOSHI", "MGAIKWAD"]

rng = np.random.default_rng(SEED)
rows = []
_doc_counters = {"DR": 1800000000, "KR": 1900000000, "AB": 1000000000,
                 "SA": 1400000000}


def doc_no(doc_type):
    _doc_counters[doc_type] += 1
    return str(_doc_counters[doc_type])


def add(posting, doc_type, account, text, amount_signed, user=None):
    posting = pd.Timestamp(posting)
    rows.append({
        "Posting Date": posting,
        "Document Number": doc_no(doc_type),
        "Document Type": doc_type,
        "G/L Account": account,
        "G/L Account Name": ACCOUNT_NAMES[account],
        "Text": text,
        "Amount in local currency": round(float(amount_signed), 2),
        "User Name": user or str(rng.choice(USERS)),
        "Entry Date": posting + pd.Timedelta(days=int(rng.integers(0, 3))),
    })


def rand_day(period, spread_all_month=True):
    day = int(rng.integers(1, period.days_in_month + 1)) if spread_all_month \
        else period.days_in_month
    return date(period.year, period.month, day)


def month_end(period):
    return date(period.year, period.month, period.days_in_month)


# ---------------------------------------------------------------- income
# Transmission charges: ~30 InSTS beneficiaries billed monthly.
beneficiaries = (["Discom A"] + ["Discom B (North)", "Discom C (South)",
                               "Railways Traction"]
                 + [f"Open Access Consumer {i:02d}" for i in range(1, 27)])
shares = np.array([0.62, 0.08, 0.06, 0.04]
                  + list(np.full(26, 0.20 / 26)))
shares = shares / shares.sum()
monthly_pool = ATC / 12.0

for m in MONTHS:
    factor = 1.02 if (m.year, m.month) == (2026, 2) else 1.0  # planted +2%
    for benef, share in zip(beneficiaries, shares):
        amt = round(monthly_pool * share * factor, 0)
        add(month_end(m), "DR", "61101",
            f"Monthly transmission charges {m.strftime('%b %Y')} - {benef}",
            -amt, user="BILLING01")

add(date(2025, 9, 30), "DR", "61101",
    "True-up recovery as per SERC MYT Order Case No. 217 of 2024",
    -TRUEUP, user="BILLING01")
add(date(2026, 3, 31), "DR", "61101",
    "Transmission availability incentive FY2025-26", -INCENTIVE,
    user="BILLING01")
# contra: credit notes debited to income
add(date(2025, 11, 15), "DR", "61101",
    "Credit note - billing revision Open Access Consumer 07", 21_000_000)
add(date(2026, 1, 20), "DR", "61101",
    "Credit note - metering correction Open Access Consumer 12", 19_000_000)

# Wheeling: exactly 1/12 of approved value each month (clean control line)
for m in MONTHS:
    add(month_end(m), "DR", "61102",
        f"Wheeling charges {m.strftime('%b %Y')}",
        -WHEELING_ANNUAL / 12.0, user="BILLING01")

# Other income
for q_end, amt in [(date(2025, 6, 30), 32_000_000),
                   (date(2025, 9, 30), 30_500_000),
                   (date(2025, 12, 31), 33_000_000),
                   (date(2026, 3, 31), 31_500_000)]:
    add(q_end, "DR", "62101", "Interest on fixed deposits for the quarter",
        -amt, user="TREASURY1")
for m in MONTHS:
    add(rand_day(m), "DR", "62201",
        f"Delayed payment surcharge {m.strftime('%b %Y')}",
        -float(rng.uniform(800_000, 2_500_000)))
for _ in range(140):
    m = MONTHS[int(rng.integers(0, 12))]
    add(rand_day(m), "DR", "62301",
        f"Supervision/consultancy fees - deposit work {int(rng.integers(1000, 9999))}",
        -float(rng.lognormal(13.0, 0.9)))
for _ in range(45):
    m = MONTHS[int(rng.integers(0, 12))]
    add(rand_day(m), "DR", "62401",
        f"Sale of scrap - lot {int(rng.integers(100, 999))}",
        -float(rng.lognormal(12.2, 0.8)))
for _ in range(30):
    m = MONTHS[int(rng.integers(0, 12))]
    add(rand_day(m), "DR", "62501", "Miscellaneous receipts",
        -float(rng.lognormal(11.5, 0.9)))
add(date(2025, 12, 10), "DR", "62901",
    "Insurance claim received - substation fire damage", -35_000_000)
add(date(2026, 2, 14), "DR", "62901",
    "Liquidated damages recovered from contractor", -12_000_000)

# ---------------------------------------------------------------- expenses
# R&M: ~8,400 vendor invoices + planted anomalies + March spike
rm_accounts = (["71101"] * 45 + ["71102"] * 35 + ["71103"] * 12
               + ["71104"] * 8)
vendors = [f"M/s Vendor {i:02d} Engineering Works" for i in range(1, 61)]
works = ["tower painting", "insulator replacement", "oil filtration",
         "yard gravelling", "earthing repair", "fencing repair",
         "battery bank service", "AC repair", "panel overhaul",
         "vehicle service"]

def add_rm_invoice(m, amount=None, text=None):
    acct = rm_accounts[int(rng.integers(0, len(rm_accounts)))]
    vendor = vendors[int(rng.integers(0, len(vendors)))]
    work = works[int(rng.integers(0, len(works)))]
    amt = amount if amount is not None else \
        min(float(rng.lognormal(10.9, 1.1)), 5_000_000.0)
    add(rand_day(m), "KR", acct,
        text or f"R&M {work} - {vendor} Inv {int(rng.integers(10000, 99999))}",
        amt)

for _ in range(8000):
    add_rm_invoice(MONTHS[int(rng.integers(0, 12))])
for _ in range(400):                       # planted March spike
    add_rm_invoice(MONTHS[11])
for i in range(10):                        # planted round sums
    add_rm_invoice(MONTHS[int(rng.integers(0, 12))],
                   amount=float(rng.integers(5, 26)) * 100_000.0)
for amt in (24_000_000, 28_000_000, 31_000_000):   # large but < ISL cutoff
    add_rm_invoice(MONTHS[int(rng.integers(0, 12))], amount=float(amt))
add_rm_invoice(MONTHS[5], text="Adjustment entry - rectification of R&M booking")
add_rm_invoice(MONTHS[8], text="Provision for O&M written back")
add_rm_invoice(MONTHS[11], text="Suspense clearing - R&M")
# planted exact duplicates (same account/amount/date, new doc numbers)
dup_sources = [r for r in rows if r["G/L Account"].startswith("711")][:6]
for src in dup_sources:
    add(src["Posting Date"], "KR", src["G/L Account"],
        src["Text"] + " (resubmitted)", src["Amount in local currency"],
        user=src["User Name"])

# Employee costs: 40 offices x 12 months + welfare
offices = [f"O&M Division {i:02d}" for i in range(1, 41)]
office_base = rng.uniform(9_000_000, 13_000_000, size=40)
for m in MONTHS:
    for office, base in zip(offices, office_base):
        amt = base * float(rng.uniform(0.98, 1.02))
        add(date(m.year, m.month, min(28 + int(rng.integers(0, 3)),
                                      m.days_in_month)),
            "AB", "72101", f"Salary - {office} - {m.strftime('%b %Y')}",
            amt, user="PAYROLL01")
for _ in range(300):
    m = MONTHS[int(rng.integers(0, 12))]
    add(rand_day(m), "AB", "72102", "Staff welfare expenses",
        float(rng.lognormal(10.0, 0.8)))

# Spares (prior-year qualification area)
for m in MONTHS:
    add(month_end(m), "SA", "73101",
        f"Stores & spares consumed {m.strftime('%b %Y')}",
        float(rng.uniform(15_000_000, 21_000_000)))
add(date(2025, 6, 30), "SA", "73102",
    "Capital spares reclassified from inventory to PPE - Ind AS 16",
    420_000_000)
add(date(2025, 9, 30), "SA", "73102",
    "Capital spares reclassified from inventory to PPE - phase 2",
    250_000_000)
add(date(2026, 3, 31), "SA", "73102",
    "Reversal of spares capitalization - rectification", -160_000_000)

# Deferred tax (prior-year qualification area)
add(date(2026, 3, 31), "SA", "74101", "Deferred tax charge for the year",
    680_000_000)
add(date(2026, 3, 31), "SA", "74101",
    "Deferred tax - remeasurement adjustment", -90_000_000)

# Administrative overheads: ~15,000 small invoices
oh_accounts = ["75101", "75102", "75103", "75104", "75105", "75106"]
for _ in range(15_000):
    m = MONTHS[int(rng.integers(0, 12))]
    acct = oh_accounts[int(rng.integers(0, len(oh_accounts)))]
    add(rand_day(m), "KR", acct,
        f"{ACCOUNT_NAMES[acct]} - bill {int(rng.integers(1000, 99999))}",
        float(rng.lognormal(9.2, 0.9)))

# CWIP capitalizations (several exceed performance materiality)
projects = ["400kV GIS Substation Riverside", "220kV line bay extension Westfield",
            "132kV cable replacement Eastgate", "SCADA upgrade Phase II",
            "765kV series compensation Aurangabad"]
for _ in range(24):
    m = MONTHS[int(rng.integers(0, 12))]
    add(rand_day(m), "SA", "15101",
        f"Capitalization - {projects[int(rng.integers(0, len(projects)))]}",
        float(rng.uniform(50_000_000, 950_000_000)))

# ------------------------------------------------------------------ output
ledger = pd.DataFrame(rows)
ledger = ledger.sort_values(["Posting Date", "Document Number"]) \
    .reset_index(drop=True)

# Trial balance from the ledger (debit-positive convention)
amt = ledger["Amount in local currency"]
tb = ledger.assign(
    debit=np.where(amt > 0, amt, 0.0),
    credit=np.where(amt < 0, -amt, 0.0),
).groupby("G/L Account").agg(
    account_name=("G/L Account Name", "first"),
    debit=("debit", "sum"),
    credit=("credit", "sum"),
).reset_index().rename(columns={"G/L Account": "account"})
tb["opening"] = np.where(tb["account"] == "15101", 3_200_000_000.0, 0.0)
tb["closing"] = tb["opening"] + tb["debit"] - tb["credit"]
# planted TB mismatch of Rs 500 (completeness-check demo)
tb.loc[tb["account"] == "75103", "debit"] += 500.0
tb.loc[tb["account"] == "75103", "closing"] += 500.0
tb = tb[["account", "account_name", "opening", "debit", "credit", "closing"]]
tb.columns = ["Account Code", "Account Name", "Opening Balance",
              "Debit Total", "Credit Total", "Closing Balance"]

serc = pd.DataFrame([
    ("Approved annual transmission charges (ATC)", ATC),
    ("Approved annual wheeling income", WHEELING_ANNUAL),
    ("True-up adjustment recognised", TRUEUP),
    ("Incentive recognised", INCENTIVE),
    ("Variance threshold %", 1.0),
    ("Tariff order reference", "SERC Case No. 217 of 2024 (MYT Order)"),
], columns=["Parameter", "Value"])


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = OUT_DIR / "demo_sap_ledger_fy2026.xlsx"
    tb_path = OUT_DIR / "demo_trial_balance_fy2026.xlsx"
    serc_path = OUT_DIR / "demo_serc_order_fy2026.xlsx"
    ledger.to_excel(ledger_path, index=False, sheet_name="Sheet1")
    tb.to_excel(tb_path, index=False, sheet_name="TB")
    serc.to_excel(serc_path, index=False, sheet_name="SERC Parameters")

    income = -amt[amt < 0].sum()
    print(f"ledger rows      : {len(ledger):,}")
    print(f"total credits    : {income:,.0f}")
    print(f"total debits     : {amt[amt > 0].sum():,.0f}")
    print(f"transmission     : "
          f"{-amt[ledger['G/L Account'] == '61101'].sum():,.0f}")
    print(f"files written to : {OUT_DIR}")


if __name__ == "__main__":
    sys.exit(main())
