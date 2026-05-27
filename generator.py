"""
Calls the VMMrx Protection API endpoints to generate protected links.
"""

import os
import aiohttp
import asyncio

SITE_URL = os.environ["SITE_URL"].rstrip("/")   # e.g. https://vmmrx.vercel.app
ADMIN_KEY = os.environ["ADMIN_KEY"]

GENERATE_ENDPOINT = f"{SITE_URL}/api/generate"   # lksfy + protect
DIRECT_ENDPOINT   = f"{SITE_URL}/api/direct"     # protect only

HEADERS = {
    "Content-Type": "application/json",
    "x-admin-key": ADMIN_KEY,
}

TIMEOUT = aiohttp.ClientTimeout(total=30)


async def generate_lksfy_link(url: str) -> dict:
    """
    Mode 1: shorten via lksfy THEN wrap in Cloudflare protection.
    Returns: { short_url, protected_url }
    """
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(
            GENERATE_ENDPOINT,
            json={"url": url},
            headers=HEADERS,
        ) as resp:
            data = await resp.json()
            if not resp.ok or not data.get("success"):
                raise ValueError(data.get("error", f"API error {resp.status}"))
            return {
                "short_url": data["short_url"],
                "protected_url": data["protected_url"],
            }


async def generate_direct_link(url: str) -> dict:
    """
    Mode 2: wrap original URL in Cloudflare protection only (no shortener).
    Returns: { protected_url, original_url }
    """
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(
            DIRECT_ENDPOINT,
            json={"url": url},
            headers=HEADERS,
        ) as resp:
            data = await resp.json()
            if not resp.ok or not data.get("success"):
                raise ValueError(data.get("error", f"API error {resp.status}"))
            return {
                "protected_url": data["protected_url"],
                "original_url": data["original_url"],
            }
