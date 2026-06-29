"""
K8S NetLab - Authentication Dependencies

FastAPI dependencies for route protection.
Supports both Directus JWT (Bearer header) and legacy session cookie,
allowing zero-downtime migration to Directus auth.
"""

from typing import Optional

from fastapi import Cookie, Header, HTTPException, status

from backend.auth import auth_manager
from backend.auth_directus import verify_directus_token


async def get_current_user(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
) -> str:
    """
    Resolve the current authenticated user.

    Checks in priority order:
    1. Authorization: Bearer <directus_token>  (new Directus auth)
    2. session_token cookie                     (legacy JSON-file auth)

    Returns the username string.
    Raises HTTP 401 if neither credential is present or valid.
    """
    # 1. Directus Bearer token
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        result = await verify_directus_token(token)
        if result:
            username, _ = result
            return username
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Directus token.",
        )

    # 2. Legacy session cookie
    if session_token:
        legacy_user = auth_manager.verify_session(session_token)
        if legacy_user:
            return legacy_user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please login again.",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Please login.",
    )


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
) -> Optional[str]:
    """
    Get current user if authenticated, None otherwise.
    Checks Bearer token first, then session cookie.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        result = await verify_directus_token(token)
        if result:
            return result[0]
        return None

    if session_token:
        return auth_manager.verify_session(session_token)

    return None
