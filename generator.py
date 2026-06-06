"""
Calls the Cloudflare Worker admin API to create protected gateway links.
Optionally shortens via lksfy before protecting.
"""

import os
import aiohttp

WORKER_URL   = os.environ["WORKER_URL"].rstrip("/")   # e.g. https://your-worker.workers.dev
ADMIN_SECRET = os.environ["ADMIN_SECRET"]             # X-Admin-Secret header value
LKSFY_API_KEY = os.environ.get("LKSFY_API_KEY", "")  # Optional – required for /lksfy mode

WORKER_HEADERS = {
    "Content-Type": "application/json",
    "X-Admin-Secret": ADMIN_SECRET,
}

TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _create_worker_link(destination: str) -> dict:
    """
    Create a protected gateway link via the Cloudflare Worker admin API.
    Returns: { id, protected_url }
    """
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(
            f"{WORKER_URL}/admin/api/links",
            json={"destination": destination},
            headers=WORKER_HEADERS,
        ) as resp:
            data = await resp.json()
            if not resp.ok or data.get("status") != "ok":
                raise ValueError(data.get("message", f"Worker API error {resp.status}"))
            link_id = data["id"]
            return {
                "id": link_id,
                "protected_url": f"{WORKER_URL}/{link_id}",
            }


async def _shorten_lksfy(url: str) -> str:
    """
    Shorten a URL via lksfy API.
    Returns the shortened URL string.
    """
    if not LKSFY_API_KEY:
        raise ValueError("LKSFY_API_KEY is not set. Add it to your .env to use /lksfy mode.")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.get(
            "https://linkshortify.com/api?api=${os.environ.LKSFY_API_KEY}&url=${encodeURIComponent(url.trim())}",
            params={"api": LKSFY_API_KEY, "url": url, "format": "json"},
        ) as resp:
            data = await resp.json(content_type=None)
            if not resp.ok or data.get("status") != "success":
                raise ValueError(data.get("message", f"lksfy API error {resp.status}"))
            return data["shortenedUrl"]


async def generate_lksfy_link(url: str) -> dict:
    """
    Mode 1: shorten via lksfy, THEN wrap in Cloudflare Worker protection.
    Returns: { short_url, protected_url, short_protected_url }
    """
    short_url = await _shorten_lksfy(url)
    worker    = await _create_worker_link(short_url)
    return {
        "short_url":           short_url,
        "protected_url":       worker["protected_url"],
        "short_protected_url": worker["protected_url"],
    }


async def generate_direct_link(url: str) -> dict:
    """
    Mode 2: wrap original URL in Cloudflare Worker protection only (no shortener).
    Returns: { protected_url, original_url, short_protected_url }
    """
    worker = await _create_worker_link(url)
    return {
        "protected_url":       worker["protected_url"],
        "short_protected_url": worker["protected_url"],
        "original_url":        url,
    }
