"""SQLite persistence: engagements, imported data, samples and the audit log.

The database lives in <project>/data/audit_tool.db (override the folder with
the AUDIT_TOOL_DATA_DIR environment variable, used by the test suite).
"""

import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  pw_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('Staff','Manager','Partner')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS engagements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  company TEXT NOT NULL,
  fy_start TEXT NOT NULL,
  fy_end TEXT NOT NULL,
  control_period TEXT,
  master_seed INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materiality (
  engagement_id INTEGER PRIMARY KEY REFERENCES engagements(id),
  benchmark TEXT,
  benchmark_amount REAL,
  percent REAL,
  overall REAL,
  pm_percent REAL,
  performance REAL,
  isl_cutoff REAL,
  notes TEXT DEFAULT '',
  updated_by TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  kind TEXT NOT NULL,
  filename TEXT,
  sha256 TEXT,
  rows INTEGER,
  mapping_json TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  imported_by TEXT,
  imported_at TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  import_id INTEGER NOT NULL REFERENCES imports(id),
  row_id INTEGER NOT NULL,
  date TEXT,
  doc_no TEXT,
  doc_type TEXT,
  account TEXT,
  account_name TEXT,
  narration TEXT,
  amount_signed REAL NOT NULL,
  amount_abs REAL NOT NULL,
  side TEXT,
  sap_user TEXT,
  entry_date TEXT,
  category TEXT DEFAULT 'Uncategorized',
  flags TEXT DEFAULT '',
  full_reason TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_txn_eng ON transactions(engagement_id, import_id, category);
CREATE TABLE IF NOT EXISTS trial_balance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  import_id INTEGER NOT NULL REFERENCES imports(id),
  account TEXT,
  account_name TEXT,
  opening REAL DEFAULT 0,
  debit REAL DEFAULT 0,
  credit REAL DEFAULT 0,
  closing REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS category_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  priority INTEGER NOT NULL,
  field TEXT NOT NULL,
  match_type TEXT NOT NULL,
  pattern TEXT NOT NULL,
  category TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS risk_config (
  engagement_id INTEGER PRIMARY KEY REFERENCES engagements(id),
  config_json TEXT NOT NULL,
  updated_by TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS populations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  run_ts TEXT NOT NULL,
  category TEXT NOT NULL,
  txn_count INTEGER,
  total_abs REAL,
  total_signed REAL,
  computed_score REAL,
  manual_weight REAL,
  final_score REAL,
  breakdown_json TEXT,
  strategy TEXT,
  cutoff_used REAL,
  full_count INTEGER,
  full_value REAL,
  sample_count INTEGER,
  sample_value REAL
);
CREATE TABLE IF NOT EXISTS samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  category TEXT NOT NULL,
  method TEXT NOT NULL,
  params_json TEXT NOT NULL,
  seed INTEGER NOT NULL,
  dataset_sha256 TEXT,
  n_target INTEGER,
  n_selected INTEGER,
  generation_no INTEGER NOT NULL DEFAULT 1,
  justification TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  created_by TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS sample_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_id INTEGER NOT NULL REFERENCES samples(id),
  txn_id INTEGER NOT NULL REFERENCES transactions(id),
  book_value REAL NOT NULL,
  is_top_stratum INTEGER DEFAULT 0,
  times_selected INTEGER DEFAULT 1,
  band INTEGER,
  result TEXT DEFAULT '',
  audited_value REAL,
  misstatement REAL,
  wp_ref TEXT DEFAULT '',
  remarks TEXT DEFAULT '',
  tested_by TEXT,
  tested_at TEXT
);
CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_id INTEGER NOT NULL REFERENCES samples(id),
  method TEXT NOT NULL,
  params_json TEXT,
  results_json TEXT,
  created_by TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS serc_data (
  engagement_id INTEGER PRIMARY KEY REFERENCES engagements(id),
  data_json TEXT NOT NULL,
  updated_by TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS conf_balances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  import_id INTEGER NOT NULL REFERENCES imports(id),
  area TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('book','ext')),
  party TEXT DEFAULT '',
  party_name TEXT DEFAULT '',
  gl_account TEXT DEFAULT '',
  balance REAL NOT NULL,
  confirm_date TEXT DEFAULT '',
  reference TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_conf_bal ON conf_balances(engagement_id, import_id);
CREATE TABLE IF NOT EXISTS conf_settings (
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  area TEXT NOT NULL,
  data_json TEXT NOT NULL,
  updated_by TEXT,
  updated_at TEXT,
  PRIMARY KEY (engagement_id, area)
);
CREATE TABLE IF NOT EXISTS conf_assessments (
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  area TEXT NOT NULL,
  party_key TEXT NOT NULL,
  conclusion TEXT NOT NULL DEFAULT 'Pending',
  remarks TEXT DEFAULT '',
  updated_by TEXT,
  updated_at TEXT,
  PRIMARY KEY (engagement_id, area, party_key)
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  user TEXT,
  role TEXT,
  engagement_id INTEGER,
  action TEXT NOT NULL,
  entity TEXT DEFAULT '',
  details_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS mapping_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'ledger',
  mapping_json TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT
);
"""


def data_dir() -> Path:
    return Path(os.environ.get("AUDIT_TOOL_DATA_DIR", PROJECT_ROOT / "data"))


def db_path() -> Path:
    return data_dir() / "audit_tool.db"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    data_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path()), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


def query(sql: str, params=()) -> list:
    with connect() as con:
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_one(sql: str, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=()) -> int:
    with connect() as con:
        cur = con.execute(sql, params)
        return cur.lastrowid


def executemany(sql: str, seq) -> None:
    with connect() as con:
        con.executemany(sql, seq)


def read_df(sql: str, params=()) -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query(sql, con, params=params)


def write_df(df: pd.DataFrame, table: str) -> None:
    with connect() as con:
        df.to_sql(table, con, if_exists="append", index=False)


# ---------------------------------------------------------------- engagements

def create_engagement(name: str, company: str, fy_start: str, fy_end: str,
                      control_period: str, created_by: str) -> int:
    return execute(
        "INSERT INTO engagements (name, company, fy_start, fy_end, "
        "control_period, master_seed, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (name, company, fy_start, fy_end, control_period,
         secrets.randbits(31), created_by, now()))


def list_engagements(status: str = "open") -> list:
    if status == "all":
        return query("SELECT * FROM engagements ORDER BY id DESC")
    return query("SELECT * FROM engagements WHERE status=? ORDER BY id DESC",
                 (status,))


def set_engagement_status(engagement_id: int, status: str) -> None:
    execute("UPDATE engagements SET status=? WHERE id=?",
            (status, engagement_id))


def get_engagement(engagement_id: int):
    return query_one("SELECT * FROM engagements WHERE id=?", (engagement_id,))


def active_import(engagement_id: int, kind: str):
    return query_one(
        "SELECT * FROM imports WHERE engagement_id=? AND kind=? AND status='active' "
        "ORDER BY id DESC LIMIT 1", (engagement_id, kind))


def active_transactions(engagement_id: int) -> pd.DataFrame:
    imp = active_import(engagement_id, "ledger")
    if not imp:
        return pd.DataFrame()
    return read_df(
        "SELECT * FROM transactions WHERE engagement_id=? AND import_id=?",
        (engagement_id, imp["id"]))


def active_trial_balance(engagement_id: int) -> pd.DataFrame:
    imp = active_import(engagement_id, "tb")
    if not imp:
        return pd.DataFrame()
    return read_df(
        "SELECT * FROM trial_balance WHERE engagement_id=? AND import_id=?",
        (engagement_id, imp["id"]))
