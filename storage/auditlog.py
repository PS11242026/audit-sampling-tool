"""Append-only audit trail (SA 230 documentation).

Every analysis step, configuration change, import, sample generation and
export is recorded here. The application never updates or deletes rows in
audit_log.
"""

import json

import pandas as pd

from storage import db


def log(user, action: str, entity: str = "", details=None,
        engagement_id=None) -> None:
    username = user.get("username") if isinstance(user, dict) else str(user or "system")
    role = user.get("role") if isinstance(user, dict) else ""
    db.execute(
        "INSERT INTO audit_log (ts, user, role, engagement_id, action, entity, "
        "details_json) VALUES (?,?,?,?,?,?,?)",
        (db.now(), username, role, engagement_id, action, entity,
         json.dumps(details or {}, default=str)))


def fetch(engagement_id=None, action=None, limit: int = 2000) -> pd.DataFrame:
    sql = "SELECT id, ts, user, role, engagement_id, action, entity, details_json FROM audit_log"
    where, params = [], []
    if engagement_id:
        where.append("engagement_id=?")
        params.append(engagement_id)
    if action:
        where.append("action=?")
        params.append(action)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    return db.read_df(sql, tuple(params))
