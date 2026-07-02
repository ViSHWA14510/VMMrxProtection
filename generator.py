"""
Supports two backends:
  - "worker"  : Cloudflare Worker (primary)
  - "vercel"  : Vercel + Upstash Redis (backup)
Each backend supports two modes: lksfy (shorten+protect) and direct (protect only).
"""

import os
import aiohttp

# ── Cloudflare Worker ──────────────────────────────────────────────────────────
WORKER_URL    = os.environ.get("WORKER_URL", "").rstrip("/")
ADMIN_SECRET  = os.environ.get("ADMIN_SECRET", "")

# ── Vercel ─────────────────────────────────────────────────────────────────────
SITE_URL      = os.environ.get("SITE_URL", "").rstrip("/")
ADMIN_KEY     = os.environ.get("ADMIN_KEY", "")

# ── Shared ─────────────────────────────────────────────────────────────────────
LKSFY_API_KEY = os.environ.get("LKSFY_API_KEY", "")

TIMEOUT = aiohttp.ClientTimeout(total=30)


# ══════════════════════════════════════════════════════════════════════════════
# CLOUDFLARE WORKER BACKEND
# ══════════════════════════════════════════════════════════════════════════════

async def _worker_create_link(destination: str) -> dict:
    """POST to Worker admin API → returns { id, protected_url }"""
    if not WORKER_URL or not ADMIN_SECRET:
        raise ValueError("WORKER_URL or ADMIN_SECRET is not set.")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(
            f"{WORKER_URL}/admin/api/links",
            json={"destination": destination},
            headers={"Content-Type": "application/json", "X-Admin-Secret": ADMIN_SECRET},
        ) as resp:
            data = await resp.json(content_type=None)
            if not resp.ok or data.get("status") != "ok":
                raise ValueError(data.get("message", f"Worker API error {resp.status}"))
            link_id = data["id"]
            return {
                "id": link_id,
                "protected_url": f"{WORKER_URL}/{link_id}",
            }


async def _shorten_lksfy(url: str, shortener_url: str = "", shortener_api: str = "") -> str:
    """Shorten a URL.

    If shortener_url/shortener_api are provided (a user's own manual shortener,
    configured via /shortner), that service is used. Otherwise falls back to
    the bot's global lksfy.com + LKSFY_API_KEY.

    Most shortener sites (GPLinks, ShrinkMe, lksfy, etc.) share the same
    GET /api?api=KEY&url=URL&format=json convention, returning
    {"status": "success", "shortenedUrl": "..."}.
    """
    base = (shortener_url or "https://lksfy.com").rstrip("/")
    api_key = shortener_api or LKSFY_API_KEY

    if not api_key:
        raise ValueError("No shortener API key set. Use /shortner to configure one.")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.get(
            f"{base}/api",
            params={"api": api_key, "url": url, "format": "json"},
        ) as resp:
            data = await resp.json(content_type=None)
            if not resp.ok or data.get("status") != "success":
                raise ValueError(data.get("message", f"Shortener API error {resp.status}"))
            return data["shortenedUrl"]


# ── Worker: lksfy mode ─────────────────────────────────────────────────────────
async def worker_generate_lksfy(url: str, shortener_url: str = "", shortener_api: str = "") -> dict:
    """lksfy shorten → Worker protect"""
    short_url = await _shorten_lksfy(url, shortener_url, shortener_api)
    worker    = await _worker_create_link(short_url)
    return {
        "short_url":           short_url,
        "protected_url":       worker["protected_url"],
        "short_protected_url": worker["protected_url"],
    }


# ── Worker: direct mode ────────────────────────────────────────────────────────
async def worker_generate_direct(url: str) -> dict:
    """Worker protect only (no shortener)"""
    worker = await _worker_create_link(url)
    return {
        "protected_url":       worker["protected_url"],
        "short_protected_url": worker["protected_url"],
        "original_url":        url,
    }


# ══════════════════════════════════════════════════════════════════════════════
# VERCEL BACKEND
# ══════════════════════════════════════════════════════════════════════════════

async def _vercel_post(endpoint: str, payload: dict) -> dict:
    """POST to Vercel API endpoint."""
    if not SITE_URL or not ADMIN_KEY:
        raise ValueError("SITE_URL or ADMIN_KEY is not set.")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(
            f"{SITE_URL}/api/{endpoint}",
            json=payload,
            headers={"Content-Type": "application/json", "x-admin-key": ADMIN_KEY},
        ) as resp:
            data = await resp.json(content_type=None)
            if not resp.ok or not data.get("success"):
                raise ValueError(data.get("error", f"Vercel API error {resp.status}"))
            return data


# ── Vercel: lksfy mode ─────────────────────────────────────────────────────────
async def vercel_generate_lksfy(url: str, shortener_url: str = "", shortener_api: str = "") -> dict:
    """lksfy shorten → Vercel protect (via /api/generate)"""
    payload = {"url": url}
    if shortener_url:
        payload["shortener_url"] = shortener_url
    if shortener_api:
        payload["shortener_api"] = shortener_api
    data = await _vercel_post("generate", payload)
    return {
        "short_url":           data.get("short_url", ""),
        "protected_url":       data.get("protected_url", ""),
        "short_protected_url": data.get("short_protected_url", data.get("protected_url", "")),
    }


# ── Vercel: direct mode ────────────────────────────────────────────────────────
async def vercel_generate_direct(url: str) -> dict:
    """Vercel protect only (via /api/direct)"""
    data = await _vercel_post("direct", {"url": url})
    return {
        "protected_url":       data.get("protected_url", ""),
        "short_protected_url": data.get("short_protected_url", data.get("protected_url", "")),
        "original_url":        url,
    }


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED ENTRY POINTS (called by bot.py)
# ══════════════════════════════════════════════════════════════════════════════

async def generate_lksfy_link(url: str, backend: str = "worker", shortener_url: str = "", shortener_api: str = "") -> dict:
    if backend == "vercel":
        return await vercel_generate_lksfy(url, shortener_url, shortener_api)
    return await worker_generate_lksfy(url, shortener_url, shortener_api)


async def generate_direct_link(url: str, backend: str = "worker") -> dict:
    if backend == "vercel":
        return await vercel_generate_direct(url)
    return await worker_generate_direct(url)
