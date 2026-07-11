"""
Link generator — wraps destination URLs with protection using your
VMMrxProtection Vercel deployment (api/direct.js). Optionally shortens
the URL first using a user-added shortener "site" (domain + API key)
before protecting it.
"""

import os
import aiohttp

# ── Vercel deployment (VMMrxProtection-main) ───────────────────────────────────
SITE_URL  = os.environ.get("SITE_URL", "").rstrip("/")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _vercel_protect(destination: str) -> dict:
    """POST to /api/direct -> returns { success, protected_url, short_protected_url, original_url }"""
    if not SITE_URL or not ADMIN_KEY:
        raise ValueError("SITE_URL or ADMIN_KEY is not set.")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(
            f"{SITE_URL}/api/direct",
            json={"url": destination},
            headers={"Content-Type": "application/json", "x-admin-key": ADMIN_KEY},
        ) as resp:
            data = await resp.json(content_type=None)
            if not resp.ok or not data.get("success"):
                raise ValueError(data.get("error", f"API error {resp.status}"))
            return data


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
    data = await _vercel_protect(url)
    return {
        "id":                   None,  # no delete support on this backend
        "protected_url":       data["protected_url"],
        "short_protected_url": data.get("short_protected_url") or data["protected_url"],
        "original_url":        url,
    }


async def generate_protected_link(url: str, site: dict | None = None) -> dict:
    """Protect a link, shortening it first via `site` if one is provided.

    `site` is a dict with 'domain' and 'api_key' keys (from db.get_default_site).
    Falls back to direct protection when no site is configured.
    """
    if site and site.get("domain") and site.get("api_key"):
        short_url = await shorten_with_site(url, site["domain"], site["api_key"])
        data = await _vercel_protect(short_url)
        return {
            "id":                   None,  # no delete support on this backend
            "short_url":           short_url,
            "protected_url":       data["protected_url"],
            "short_protected_url": data.get("short_protected_url") or data["protected_url"],
            "original_url":        url,
        }
    return await generate_direct_link(url)


async def delete_protected_link(link_id: str):
    """Not supported: the Vercel backend (api/direct.js + Upstash Redis)
    has no delete endpoint -- protected links are permanent once created."""
    raise NotImplementedError(
        "Removing links isn't supported by this backend yet -- "
        "there's no delete endpoint in the Vercel project."
    )
