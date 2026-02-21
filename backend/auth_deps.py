"""
K8S NetLab - Authentication Dependencies

FastAPI dependencies for route protection.
"""

from typing import Optional

from fastapi import Cookie, HTTPException, status

from backend.auth import auth_manager


async def get_current_user(
    session_token: Optional[str] = Cookie(None)
) -> str:
    """
    Get current authenticated user from session cookie.

    This is a FastAPI dependency that can be used to protect routes.

    Args:
        session_token: Session token from cookie

    Returns:
        Username of authenticated user

    Raises:
        HTTPException: If not authenticated or session invalid
    """
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please login."
        )

    username = auth_manager.verify_session(session_token)

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please login again."
        )

    return username


async def get_current_user_optional(
    session_token: Optional[str] = Cookie(None)
) -> Optional[str]:
    """
    Get current user if authenticated, None otherwise.

    This is useful for routes that work both with and without authentication.

    Args:
        session_token: Session token from cookie

    Returns:
        Username if authenticated, None otherwise
    """
    if not session_token:
        return None

    return auth_manager.verify_session(session_token)
