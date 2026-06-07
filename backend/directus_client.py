"""
K8S NetLab - Directus public data client.

Fetches experiment content from Directus when DIRECTUS_URL is set.
All reads use the public policy (no auth token needed for published items).
Falls back gracefully when Directus is unreachable.
"""

import logging
from typing import Optional

import httpx

from backend import config

logger = logging.getLogger(__name__)

_FIELDS_LIST = "slug,title,difficulty,duration,phase,sort_order"
_FIELDS_DETAIL = "slug,title,difficulty,duration,phase,background,content"


async def fetch_experiment_list() -> Optional[list[dict]]:
    """
    Return published network experiments sorted by sort_order.
    Each item: {id, title, difficulty, duration, phase}.
    Returns None if Directus is unavailable or not configured.
    """
    if not config.DIRECTUS_URL:
        return None
    url = f"{config.DIRECTUS_URL}/items/experiments"
    params = {
        "filter[status][_eq]": "published",
        "filter[category][_eq]": "network",
        "fields": _FIELDS_LIST,
        "sort": "sort_order",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
    except Exception as exc:
        logger.warning("Directus experiment list fetch failed: %s", exc)
        return None

    if resp.status_code != 200:
        logger.warning("Directus experiment list: HTTP %s", resp.status_code)
        return None

    items = resp.json().get("data", [])
    return [
        {
            "id": item["slug"],
            "title": item["title"],
            "difficulty": item["difficulty"],
            "duration": item["duration"],
            "phase": item["phase"],
        }
        for item in items
    ]


async def fetch_experiment_detail(slug: str) -> Optional[dict]:
    """
    Return full experiment content for the given slug.
    Returns None if not found or Directus is unavailable.
    """
    if not config.DIRECTUS_URL:
        return None
    url = f"{config.DIRECTUS_URL}/items/experiments"
    params = {
        "filter[slug][_eq]": slug,
        "filter[status][_eq]": "published",
        "filter[category][_eq]": "network",
        "fields": _FIELDS_DETAIL,
        "limit": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
    except Exception as exc:
        logger.warning("Directus experiment detail fetch failed (slug=%s): %s", slug, exc)
        return None

    if resp.status_code != 200:
        logger.warning("Directus experiment detail: HTTP %s (slug=%s)", resp.status_code, slug)
        return None

    items = resp.json().get("data", [])
    if not items:
        return None

    item = items[0]
    return {
        "id": item["slug"],
        "title": item["title"],
        "difficulty": item["difficulty"],
        "duration": item["duration"],
        "phase": item["phase"],
        "background": item.get("background", ""),
        "content": item.get("content", ""),
    }


async def directus_auth_login(username: str, password: str) -> Optional[str]:
    """
    Authenticate against Directus using email-based login.
    Email is derived as {username}@lab.cloudnetops.tech.
    Returns the Directus access token, or None on failure.
    """
    if not config.DIRECTUS_URL:
        return None
    email = f"{username}@lab.cloudnetops.tech"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{config.DIRECTUS_URL}/auth/login",
                json={"email": email, "password": password},
            )
    except Exception as exc:
        logger.warning("Directus auth/login network error: %s", exc)
        return None

    if resp.status_code != 200:
        return None

    return resp.json().get("data", {}).get("access_token")
