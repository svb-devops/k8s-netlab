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


async def _fetch_category_list(category: str) -> Optional[list[dict]]:
    """
    Return published experiments collection items filtered by category,
    sorted by sort_order. Each item: {id, title, difficulty, duration, phase}.
    Returns None if Directus is unavailable or not configured.
    """
    if not config.DIRECTUS_URL:
        return None
    url = f"{config.DIRECTUS_URL}/items/experiments"
    params = {
        "filter[status][_eq]": "published",
        "filter[category][_eq]": category,
        "fields": _FIELDS_LIST,
        "sort": "sort_order",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
    except Exception as exc:
        logger.warning("Directus %s list fetch failed: %s", category, exc)
        return None

    if resp.status_code != 200:
        logger.warning("Directus %s list: HTTP %s", category, resp.status_code)
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


async def _fetch_category_detail(category: str, slug: str) -> Optional[dict]:
    """
    Return full content for the given slug within the given category.
    Returns None if not found or Directus is unavailable.
    """
    if not config.DIRECTUS_URL:
        return None
    url = f"{config.DIRECTUS_URL}/items/experiments"
    params = {
        "filter[slug][_eq]": slug,
        "filter[status][_eq]": "published",
        "filter[category][_eq]": category,
        "fields": _FIELDS_DETAIL,
        "limit": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
    except Exception as exc:
        logger.warning("Directus %s detail fetch failed (slug=%s): %s", category, slug, exc)
        return None

    if resp.status_code != 200:
        logger.warning("Directus %s detail: HTTP %s (slug=%s)", category, resp.status_code, slug)
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


async def fetch_experiment_list() -> Optional[list[dict]]:
    """Return published network experiments. See _fetch_category_list."""
    return await _fetch_category_list("network")


async def fetch_experiment_detail(slug: str) -> Optional[dict]:
    """Return a published network experiment's content. See _fetch_category_detail."""
    return await _fetch_category_detail("network", slug)


async def fetch_deployment_list() -> Optional[list[dict]]:
    """Return published deployment cases. See _fetch_category_list."""
    return await _fetch_category_list("deployment")


async def fetch_deployment_detail(slug: str) -> Optional[dict]:
    """Return a published deployment case's content. See _fetch_category_detail."""
    return await _fetch_category_detail("deployment", slug)


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

    token: Optional[str] = resp.json().get("data", {}).get("access_token")
    return token
