"""
SQLite-based persistence for user authorization and admin management.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "vmmrx_bot.db")

# Admin IDs from env — comma-separated list of Telegram user IDs
_ADMIN_IDS: set[int] = set()
_raw = os.environ.get("ADMIN_IDS", "")
for _part in _raw.split(","):
    _part = _part.strip()
    if _part.isdigit():
        _ADMIN_IDS.add(int(_part))

_lock = threading.Lock()

# ── Init ──────────────────────────────────────────────────────────────────────

def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT    DEFAULT '',
                full_name TEXT    DEFAULT '',
                approved  INTEGER DEFAULT 0,
                pending   INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        con.commit()

@contextmanager
def _conn():
    with _lock:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

init_db()

# ── Admin ─────────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in _ADMIN_IDS

def get_admin_ids() -> list[int]:
    return list(_ADMIN_IDS)

# ── User CRUD ─────────────────────────────────────────────────────────────────

def save_user(user_id: int, username: str, full_name: str):
    """Upsert user record (does not change approved/pending status)."""
    with _conn() as con:
        con.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name
        """, (user_id, username, full_name))
        con.commit()

def add_pending_user(user_id: int, username: str, full_name: str):
    """Mark user as pending (if not already approved)."""
    with _conn() as con:
        con.execute("""
            INSERT INTO users (user_id, username, full_name, pending)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name,
                pending   = CASE WHEN approved = 1 THEN 0 ELSE 1 END
        """, (user_id, username, full_name))
        con.commit()

def approve_user(user_id: int):
    with _conn() as con:
        con.execute("""
            INSERT INTO users (user_id, approved, pending)
            VALUES (?, 1, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                approved = 1,
                pending  = 0
        """, (user_id,))
        con.commit()

def revoke_user(user_id: int):
    with _conn() as con:
        con.execute("""
            UPDATE users SET approved = 0, pending = 0
            WHERE user_id = ?
        """, (user_id,))
        con.commit()

def is_approved(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    with _conn() as con:
        row = con.execute(
            "SELECT approved FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row["approved"])

def get_pending_users() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT user_id, username, full_name FROM users WHERE pending = 1 AND approved = 0"
        ).fetchall()
        return [dict(r) for r in rows]

def get_all_users() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT user_id, username, full_name, approved, pending FROM users ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

def get_user_info(user_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT user_id, username, full_name, approved FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None
