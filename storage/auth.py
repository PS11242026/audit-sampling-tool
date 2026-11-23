"""User accounts, scrypt password hashing and Partner/Manager/Staff roles."""

import hashlib
import hmac
import os

from storage import db

ROLES = ("Staff", "Manager", "Partner")
_RANK = {"Staff": 1, "Manager": 2, "Partner": 3}

_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=64)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.scrypt(password.encode("utf-8"),
                        salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(dk.hex(), dk_hex)


def user_count() -> int:
    row = db.query_one("SELECT COUNT(*) AS c FROM users")
    return int(row["c"]) if row else 0


def create_user(username: str, password: str, role: str) -> int:
    username = (username or "").strip()
    if not username:
        raise ValueError("username is required")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password or "") < 8:
        raise ValueError("password must be at least 8 characters")
    if db.query_one("SELECT id FROM users WHERE username=?", (username,)):
        raise ValueError("username already exists")
    return db.execute(
        "INSERT INTO users (username, pw_hash, role, active, created_at) "
        "VALUES (?,?,?,1,?)",
        (username, hash_password(password), role, db.now()))


def authenticate(username: str, password: str):
    row = db.query_one(
        "SELECT * FROM users WHERE username=? AND active=1", ((username or "").strip(),))
    if row and verify_password(password or "", row["pw_hash"]):
        return {"id": row["id"], "username": row["username"], "role": row["role"]}
    return None


def list_users() -> list:
    return db.query("SELECT id, username, role, active, created_at FROM users "
                    "ORDER BY id")


def set_active(user_id: int, active: bool) -> None:
    db.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))


def has_role(user: dict, min_role: str) -> bool:
    if not user:
        return False
    return _RANK.get(user.get("role"), 0) >= _RANK[min_role]
