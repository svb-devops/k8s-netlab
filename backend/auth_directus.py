"""
K8S NetLab - Directus JWT verification.

Provides token verification against the Directus /users/me endpoint,
with an in-memory TTL cache to minimise per-request latency.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import httpx

from backend import config

logger = logging.getLogger(__name__)

# ── cache ─────────────────────────────────────────────────────────────────────

@dataclass
class _CacheEntry:
    username: str
    email: str
    is_admin: bool
    expires_at: float


_cache: Dict[str, _CacheEntry] = {}
_cache_lock = asyncio.Lock()

# ── public API ─────────────────────────────────────────────────────────────────


async def verify_directus_token(token: str) -> Optional[Tuple[str, bool]]:
    """
    Verify a Directus access token and return (username, is_admin).

    Returns None if the token is invalid or Directus is unreachable.
    Caches valid results for DIRECTUS_TOKEN_CACHE_TTL seconds.
    """
    if not config.DIRECTUS_URL:
        return None

    now = time.monotonic()

    async with _cache_lock:
        entry = _cache.get(token)
        if entry and entry.expires_at > now:
            return entry.username, entry.is_admin

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{config.DIRECTUS_URL}/users/me",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "first_name,email,role.name"},
            )
    except Exception as exc:
        logger.warning("Directus token check failed (network): %s", exc)
        return None

    if resp.status_code != 200:
        return None

    data = resp.json().get("data", {})
    first_name = data.get("first_name", "")
    email = data.get("email", "")
    role_name = (data.get("role") or {}).get("name", "")
    is_admin = role_name == "Administrator"

    # Use first_name as username (set during user import); fall back to email prefix.
    username = first_name or email.split("@")[0]
    if not username:
        return None

    entry = _CacheEntry(
        username=username,
        email=email,
        is_admin=is_admin,
        expires_at=now + config.DIRECTUS_TOKEN_CACHE_TTL,
    )
    async with _cache_lock:
        _cache[token] = entry

    return username, is_admin


def evict_token(token: str) -> None:
    """Remove a token from the cache (e.g. on logout)."""
    _cache.pop(token, None)
