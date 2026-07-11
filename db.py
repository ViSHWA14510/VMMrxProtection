"""
MongoDB-based persistence for user authorization, admin management, and
user-added shortener sites.
"""

import os
import threading
from datetime import datetime, timezone

from pymongo import MongoClient, ReturnDocument

# ── Connection ────────────────────────────────────────────────────────────────
MONGO_URL = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL", "")
DB_NAME   = os.environ.get("MONGO_DB_NAME", "vmmrx_bot")

if not MONGO_URL:
    raise ValueError(
        "MONGODB_URI (or MONGO_URL) env var is not set — a MongoDB "
        "connection string is required."
    )

_client = MongoClient(MONGO_URL)
_db = _client[DB_NAME]

users_col    = _db["users"]
sites_col    = _db["sites"]
counters_col = _db["counters"]

_lock = threading.Lock()

# Admin IDs from env — comma-separated list of Telegram user IDs
_ADMIN_IDS: set[int] = set()
_raw = os.environ.get("ADMIN_IDS", "")
for _part in _raw.split(","):
    _part = _part.strip()
    if _part.isdigit():
        _ADMIN_IDS.add(int(_part))

# ── Init ──────────────────────────────────────────────────────────────────────

def init_db():
    """Create indexes. Mongo creates collections lazily on first insert."""
    users_col.create_index("user_id", unique=True)
    sites_col.create_index("user_id")
    sites_col.create_index("id", unique=True)

def _next_site_id() -> int:
    """Atomic auto-increment counter, mimicking SQLite's AUTOINCREMENT id
    so existing callback_data (e.g. 'site_view:123') keeps working."""
    with _lock:
        doc = counters_col.find_one_and_update(
            {"_id": "site_id"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc["seq"]

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

init_db()

# ── Admin ─────────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in _ADMIN_IDS

def get_admin_ids() -> list[int]:
    return list(_ADMIN_IDS)

# ── User CRUD ─────────────────────────────────────────────────────────────────

def save_user(user_id: int, username: str, full_name: str):
    """Upsert user record (does not change approved/pending status)."""
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {"username": username, "full_name": full_name},
            "$setOnInsert": {
                "approved": False,
                "pending": False,
                "created_at": _now_iso(),
            },
        },
        upsert=True,
    )

def add_pending_user(user_id: int, username: str, full_name: str):
    """Mark user as pending (if not already approved)."""
    existing = users_col.find_one({"user_id": user_id})
    already_approved = bool(existing and existing.get("approved"))
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "username": username,
                "full_name": full_name,
                "pending": not already_approved,
            },
            "$setOnInsert": {
                "approved": False,
                "created_at": _now_iso(),
            },
        },
        upsert=True,
    )

def approve_user(user_id: int):
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {"approved": True, "pending": False},
            "$setOnInsert": {
                "username": "",
                "full_name": "",
                "created_at": _now_iso(),
            },
        },
        upsert=True,
    )

def revoke_user(user_id: int):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"approved": False, "pending": False}},
    )

def is_approved(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    doc = users_col.find_one({"user_id": user_id})
    return bool(doc and doc.get("approved"))

def get_pending_users() -> list[dict]:
    docs = users_col.find({"pending": True, "approved": False})
    return [
        {"user_id": d["user_id"], "username": d.get("username", ""), "full_name": d.get("full_name", "")}
        for d in docs
    ]

def get_all_users() -> list[dict]:
    docs = users_col.find().sort("created_at", -1)
    return [
        {
            "user_id": d["user_id"],
            "username": d.get("username", ""),
            "full_name": d.get("full_name", ""),
            "approved": d.get("approved", False),
            "pending": d.get("pending", False),
        }
        for d in docs
    ]

def get_user_info(user_id: int) -> dict | None:
    d = users_col.find_one({"user_id": user_id})
    if not d:
        return None
    return {
        "user_id": d["user_id"],
        "username": d.get("username", ""),
        "full_name": d.get("full_name", ""),
        "approved": d.get("approved", False),
    }

# ── Sites (user-added shortener sites) ────────────────────────────────────────

def add_site(user_id: int, domain: str, api_key: str) -> int:
    """Add a new shortener site for a user. Returns the new site's id."""
    site_id = _next_site_id()
    sites_col.insert_one({
        "id": site_id,
        "user_id": user_id,
        "domain": domain.rstrip("/").strip(),
        "api_key": api_key.strip(),
        "links_count": 0,
        "created_at": _now_iso(),
    })
    return site_id

def _site_dict(d: dict) -> dict:
    return {
        "id": d["id"],
        "domain": d["domain"],
        "api_key": d["api_key"],
        "links_count": d.get("links_count", 0),
        "created_at": d.get("created_at", ""),
    }

def get_sites(user_id: int) -> list[dict]:
    """Returns all sites for a user, oldest first (index 1 = first/default site)."""
    docs = sites_col.find({"user_id": user_id}).sort("id", 1)
    return [_site_dict(d) for d in docs]

def get_site(site_id: int, user_id: int) -> dict | None:
    d = sites_col.find_one({"id": site_id, "user_id": user_id})
    return _site_dict(d) if d else None

def get_default_site(user_id: int) -> dict | None:
    """Returns the user's first-added site (used automatically when protecting links)."""
    d = sites_col.find_one({"user_id": user_id}, sort=[("id", 1)])
    return _site_dict(d) if d else None

def increment_site_links(site_id: int):
    sites_col.update_one({"id": site_id}, {"$inc": {"links_count": 1}})

def delete_site(site_id: int, user_id: int):
    sites_col.delete_one({"id": site_id, "user_id": user_id})
