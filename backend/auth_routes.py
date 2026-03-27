"""
K8S NetLab - Authentication API Routes

User registration, login, and session management.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.auth import auth_manager
from backend.config import SESSION_COOKIE_SECURE
from backend.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Create auth router
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ============================================================
# Request/Response Models
# ============================================================

class RegisterRequest(BaseModel):
    """User registration request."""
    username: str = Field(..., min_length=3, max_length=20, pattern="^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=6, max_length=72)  # bcrypt max is 72 bytes


class LoginRequest(BaseModel):
    """User login request."""
    username: str
    password: str


class AuthResponse(BaseModel):
    """Authentication response."""
    success: bool
    message: str
    username: Optional[str] = None
    is_admin: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    """Change-password request."""
    old_password: str = Field(..., min_length=1, max_length=72)  # bcrypt max is 72 bytes
    new_password: str = Field(..., min_length=6, max_length=72)  # bcrypt max is 72 bytes


def _normalize_ip(ip: str) -> str:
    """Strip IPv6-mapped IPv4 prefix so ::ffff:1.2.3.4 → 1.2.3.4."""
    if ip and ip.startswith("::ffff:"):
        return ip[7:]
    return ip


# ============================================================
# Auth Routes
# ============================================================

@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user"
)
async def register(request: RegisterRequest) -> AuthResponse:
    """
    Register a new user.

    Args:
        request: Username and password

    Returns:
        AuthResponse with registration status
    """
    try:
        success = auth_manager.register_user(
            username=request.username,
            password=request.password
        )

        if success:
            return AuthResponse(
                success=True,
                message="User registered successfully",
                username=request.username
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Login"
)
async def login(credentials: LoginRequest, response: Response, request: Request) -> AuthResponse:
    """
    Login with username and password.

    Sets a session cookie on successful login.

    Args:
        request: Username and password
        response: FastAPI response (for setting cookie)

    Returns:
        AuthResponse with login status
    """
    try:
        # Rate limit: 5 failed login attempts per IP per 60 seconds.
        # Only failed attempts count — successful logins do not exhaust the quota.
        client_ip = _normalize_ip(request.client.host if request.client else "unknown")
        rl_key = f"login:{client_ip}"
        if rate_limiter.is_over_limit(rl_key, max_requests=5, window_seconds=60):
            wait = rate_limiter.retry_after(rl_key, window_seconds=60)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"登录尝试过于频繁，请 {wait} 秒后重试",
                headers={"Retry-After": str(wait)},
            )

        # Verify credentials — record attempt only on failure
        if not auth_manager.verify_credentials(credentials.username, credentials.password):
            rate_limiter.record(rl_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )

        # Create session (record login IP for admin observability)
        token = auth_manager.create_session(credentials.username, login_ip=client_ip)

        # Set session cookie
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            secure=SESSION_COOKIE_SECURE,
            max_age=86400,  # 24 hours
            samesite="lax"
        )

        return AuthResponse(
            success=True,
            message="Login successful",
            username=credentials.username
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )


@router.post(
    "/logout",
    response_model=AuthResponse,
    summary="Logout"
)
async def logout(
    response: Response,
    session_token: Optional[str] = Cookie(None)
) -> AuthResponse:
    """
    Logout and delete session.

    Args:
        response: FastAPI response (for clearing cookie)
        session_token: Session token from cookie

    Returns:
        AuthResponse with logout status
    """
    try:
        if session_token:
            auth_manager.delete_session(session_token)

        # Clear session cookie — attributes must match the original set_cookie call
        # so the browser properly removes the HttpOnly cookie.
        response.delete_cookie(
            key="session_token",
            httponly=True,
            secure=SESSION_COOKIE_SECURE,
            samesite="lax",
        )

        return AuthResponse(
            success=True,
            message="Logged out successfully"
        )

    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed"
        )


@router.get(
    "/me",
    response_model=AuthResponse,
    summary="Get current user"
)
async def get_current_user(
    session_token: Optional[str] = Cookie(None)
) -> AuthResponse:
    """
    Get currently logged-in user.

    Args:
        session_token: Session token from cookie

    Returns:
        AuthResponse with current username
    """
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    username = auth_manager.verify_session(session_token)

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session"
        )

    return AuthResponse(
        success=True,
        message="Authenticated",
        username=username,
        is_admin=auth_manager.is_admin(username),
    )


@router.post(
    "/change-password",
    response_model=AuthResponse,
    summary="Change current user's password"
)
async def change_password(
    req: ChangePasswordRequest,
    session_token: Optional[str] = Cookie(None),
) -> AuthResponse:
    """
    Change the logged-in user's password.

    Requires the current password for verification.
    """
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    username = auth_manager.verify_session(session_token)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    if not auth_manager.change_password(username, req.old_password, req.new_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")

    logger.info(f"Password changed via API for '{username}'")
    return AuthResponse(success=True, message="密码已修改", username=username)
