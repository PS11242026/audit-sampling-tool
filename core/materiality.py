"""SA 320 materiality worksheet: overall materiality -> performance
materiality -> individually-significant-item cutoff."""

from storage import db

BENCHMARKS = ["Total revenue", "Profit before tax", "Total assets",
              "Net worth", "Total expenses"]

# Typical benchmark percentage ranges shown as guidance in the UI.
GUIDANCE = {
    "Total revenue": "0.5% - 1%",
    "Profit before tax": "5% - 10%",
    "Total assets": "1% - 2%",
    "Net worth": "2% - 5%",
    "Total expenses": "0.5% - 1%",
}


def compute(benchmark_amount: float, percent: float,
            pm_percent: float = 75.0) -> dict:
    overall = float(benchmark_amount) * float(percent) / 100.0
    performance = overall * float(pm_percent) / 100.0
    return {"overall": overall, "performance": performance}


def save(engagement_id: int, values: dict, actor: str) -> None:
    db.execute(
        "INSERT INTO materiality (engagement_id, benchmark, benchmark_amount, "
        "percent, overall, pm_percent, performance, isl_cutoff, notes, "
        "updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(engagement_id) DO UPDATE SET benchmark=excluded.benchmark, "
        "benchmark_amount=excluded.benchmark_amount, percent=excluded.percent, "
        "overall=excluded.overall, pm_percent=excluded.pm_percent, "
        "performance=excluded.performance, isl_cutoff=excluded.isl_cutoff, "
        "notes=excluded.notes, updated_by=excluded.updated_by, "
        "updated_at=excluded.updated_at",
        (engagement_id, values.get("benchmark"),
         float(values.get("benchmark_amount") or 0),
         float(values.get("percent") or 0),
         float(values.get("overall") or 0),
         float(values.get("pm_percent") or 0),
         float(values.get("performance") or 0),
         float(values.get("isl_cutoff") or 0),
         values.get("notes", ""), actor, db.now()))


def load(engagement_id: int):
    return db.query_one("SELECT * FROM materiality WHERE engagement_id=?",
                        (engagement_id,))
