"""SQLite persistence for the SaaS layer: users, projects, usage, audit.

SQLite (WAL mode) keeps self-hosting friction at zero; the schema is plain
SQL so a PostgreSQL swap is a connection-string change plus AUTOINCREMENT →
SERIAL. One connection per call (short-lived, thread-safe) — simulation
traffic dwarfs metadata traffic, so pooling is unnecessary here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path

from ...config import DATA_DIR

DB_PATH = DATA_DIR / "saas.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'field'
        CHECK (role IN ('manager', 'field', 'presales')),
    tier TEXT NOT NULL DEFAULT 'basic'
        CHECK (tier IN ('basic', 'pro', 'enterprise')),
    org_name TEXT NOT NULL DEFAULT '',
    logo_path TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'session' CHECK (kind IN ('session', 'api')),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'coverage',
    data_json TEXT NOT NULL DEFAULT '{}',
    share_token TEXT UNIQUE,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


from contextlib import contextmanager


@contextmanager
def _conn():
    """Short-lived connection: commit on success, rollback on error, and
    ALWAYS close - sqlite3's own context manager commits but never closes,
    which leaks file handles on GCs without prompt refcounting."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        # Migration: add the client-IP column to older audit_log tables.
        cols = {r[1] for r in c.execute("PRAGMA table_info(audit_log)").fetchall()}
        if "ip" not in cols:
            c.execute("ALTER TABLE audit_log ADD COLUMN ip TEXT")
    # The database holds password hashes, tokens and audit records — restrict
    # it to the owning account (OT/IT data-at-rest requirement).
    try:
        import os
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


# -------------------------------------------------------------- passwords
def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt),
                                 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt).split("$", 1)[1]
    return hmac.compare_digest(candidate, digest)


# ------------------------------------------------------------------ users
def create_user(email: str, password: str, name: str = "", role: str = "field",
                tier: str = "basic", org_name: str = "") -> dict:
    # Read back AFTER the with-block commits - a fresh connection cannot see
    # the row while the insert transaction is still open.
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO users (email, name, password_hash, role, tier, "
            "org_name, created_at) VALUES (?,?,?,?,?,?,?)",
            (email.lower().strip(), name, hash_password(password), role, tier,
             org_name, time.time()))
        new_id = cur.lastrowid
    return get_user(new_id)  # type: ignore[return-value]


def get_user(user_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email=?",
                        (email.lower().strip(),)).fetchone()
    return dict(row) if row else None


def org_exists(org_name: str) -> bool:
    """Whether any account already claims this organisation name.

    Tenancy is scoped on ``users.org_name``, so registration must not let a
    stranger join an existing tenant merely by typing its name (see
    ``routes_auth.register``).  Compared case-insensitively and trimmed, since
    "AcmeTelecom" and "acme telecom " must not be treated as different orgs.
    """
    name = (org_name or "").strip()
    if not name:
        return False
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM users WHERE TRIM(org_name) = ? COLLATE NOCASE "
            "LIMIT 1", (name,)).fetchone()
    return row is not None


def update_user(user_id: int, **fields) -> None:
    allowed = {"name", "role", "tier", "org_name", "logo_path"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    with _conn() as c:
        c.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                  (*sets.values(), user_id))


# ----------------------------------------------------------------- tokens
# Session tokens expire; long-lived API tokens (enterprise) do not, but both
# are revocable via revoke_token (logout / key rotation).
SESSION_TTL_S = 30 * 24 * 3600


def issue_token(user_id: int, kind: str = "session") -> str:
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute("INSERT INTO tokens (token, user_id, kind, created_at) "
                  "VALUES (?,?,?,?)", (token, user_id, kind, time.time()))
    return token


def user_for_token(token: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT u.*, t.kind AS token_kind, t.created_at AS token_created "
            "FROM users u JOIN tokens t ON t.user_id = u.id "
            "WHERE t.token=?", (token,)).fetchone()
    if row is None:
        return None
    user = dict(row)
    if (user.pop("token_kind") == "session"
            and time.time() - user.pop("token_created", 0) > SESSION_TTL_S):
        revoke_token(token)
        return None
    user.pop("token_created", None)
    return user


def revoke_token(token: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM tokens WHERE token=?", (token,))


# --------------------------------------------------------------- projects
def create_project(user_id: int, name: str, kind: str, data: dict) -> dict:
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO projects (user_id, name, kind, data_json, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?)",
            (user_id, name, kind, json.dumps(data), now, now))
        new_id = cur.lastrowid
    return get_project(new_id)  # type: ignore[return-value]


def get_project(project_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return _proj(row) if row else None


def get_project_by_share_token(token: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM projects WHERE share_token=?",
                        (token,)).fetchone()
    return _proj(row) if row else None


def list_projects(user_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM projects WHERE user_id=? "
                         "ORDER BY updated_at DESC", (user_id,)).fetchall()
    return [_proj(r) for r in rows]


def count_projects(user_id: int) -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM projects WHERE user_id=?",
                         (user_id,)).fetchone()[0]


def update_project(project_id: int, name: str | None = None,
                   data: dict | None = None) -> None:
    with _conn() as c:
        if name is not None:
            c.execute("UPDATE projects SET name=?, updated_at=? WHERE id=?",
                      (name, time.time(), project_id))
        if data is not None:
            c.execute("UPDATE projects SET data_json=?, updated_at=? WHERE id=?",
                      (json.dumps(data), time.time(), project_id))


def delete_project(project_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM projects WHERE id=?", (project_id,))


def share_project(project_id: int) -> str:
    token = secrets.token_urlsafe(12)
    with _conn() as c:
        c.execute("UPDATE projects SET share_token=? WHERE id=?",
                  (token, project_id))
    return token


def _proj(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d.pop("data_json") or "{}")
    return d


# -------------------------------------------------------------- audit log
def log_action(user_id: int | None, action: str, detail: str = "",
               ip: str | None = None) -> None:
    with _conn() as c:
        c.execute("INSERT INTO audit_log (user_id, action, detail, ip, ts) "
                  "VALUES (?,?,?,?,?)", (user_id, action, detail, ip, time.time()))


def list_audit(limit: int = 200, org_name: str | None = None) -> list[dict]:
    """Audit entries, TENANT-SCOPED: when org_name is given only that org's
    users' actions are returned - a manager must never see another tenant's
    emails or activity."""
    limit = min(max(limit, 1), 1000)
    with _conn() as c:
        if org_name is not None:
            rows = c.execute(
                "SELECT a.*, u.email FROM audit_log a JOIN users u "
                "ON u.id = a.user_id WHERE u.org_name = ? "
                "ORDER BY a.ts DESC LIMIT ?", (org_name, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT a.*, u.email FROM audit_log a LEFT JOIN users u "
                "ON u.id = a.user_id ORDER BY a.ts DESC LIMIT ?",
                (limit,)).fetchall()
    return [dict(r) for r in rows]


init_db()
