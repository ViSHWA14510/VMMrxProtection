"""
Link generator — wraps destination URLs with Cloudflare Worker protection.
Optionally shortens the URL first using a user-added shortener "site"
(domain + API key) before protecting it. The Vercel backend has been removed.
"""

import os
import aiohttp

# ── Cloudflare Worker ──────────────────────────────────────────────────────────
WORKER_URL    = os.environ.get("WORKER_URL", "").rstrip("/")
ADMIN_SECRET  = os.environ.get("ADMIN_SECRET", "")

TIMEOUT = aiohttp.ClientTimeout(total=30)


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


async def _worker_delete_link(link_id: str):
    """DELETE a protected link from the Worker (deactivates/removes it)."""
    if not WORKER_URL or not ADMIN_SECRET:
        raise ValueError("WORKER_URL or ADMIN_SECRET is not set.")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.delete(
            f"{WORKER_URL}/admin/api/links/{link_id}",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        ) as resp:
            if resp.status not in (200, 204):
                data = await resp.json(content_type=None)
                raise ValueError(data.get("message", f"Worker API error {resp.status}"))


async def shorten_with_site(url: str, domain: str, api_key: str) -> str:
    """Shorten a URL using a user-added shortener site.

    Most shortener sites (GPLinks, ShrinkMe, Arolinks, etc.) share the same
    GET /api?api=KEY&url=URL&format=json convention, returning
    {"status": "success", "shortenedUrl": "..."}.
    """
    if not domain or not api_key:
        raise ValueError("Shortener site is not configured.")

    base = domain.rstrip("/")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.get(
            f"{base}/api",
            params={"api": api_key, "url": url, "format": "json"},
        ) as resp:
            data = await resp.json(content_type=None)
            if not resp.ok or data.get("status") != "success":
                raise ValueError(data.get("message", f"Shortener API error {resp.status}"))
            return data["shortenedUrl"]


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED ENTRY POINTS (called by bot.py)
# ══════════════════════════════════════════════════════════════════════════════

async def generate_direct_link(url: str) -> dict:
    """Protect a link directly (no shortener)."""
    worker = await _worker_create_link(url)
    return {
        "id":                   worker["id"],
        "protected_url":       worker["protected_url"],
        "short_protected_url": worker["protected_url"],
        "original_url":        url,
    }


async def generate_protected_link(url: str, site: dict | None = None) -> dict:
    """Protect a link, shortening it first via `site` if one is provided.

    `site` is a dict with 'domain' and 'api_key' keys (from db.get_default_site).
    Falls back to direct protection when no site is configured.
    """
    if site and site.get("domain") and site.get("api_key"):
        short_url = await shorten_with_site(url, site["domain"], site["api_key"])
        worker = await _worker_create_link(short_url)
        return {
            "id":                   worker["id"],
            "short_url":           short_url,
            "protected_url":       worker["protected_url"],
            "short_protected_url": worker["protected_url"],
            "original_url":        url,
        }
    return await generate_direct_link(url)


async def delete_protected_link(link_id: str):
    """Remove a previously protected link from the Worker."""
    await _worker_delete_link(link_id)
