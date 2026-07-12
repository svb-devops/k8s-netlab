"""
K8S NetLab - Authentication API Routes

User registration, login, and session management.
"""

import asyncio
import logging
import re
from typing import Any, Coroutine, Optional

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.auth import auth_manager
from backend.config import SESSION_COOKIE_SECURE
from backend.directus_client import directus_auth_login
from backend.auth_directus import verify_directus_token
from backend.email_client import send_verification_email
from backend.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Create auth router
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Strong references for fire-and-forget background tasks (asyncio.create_task
# alone doesn't keep the Task alive against GC before it completes).
_background_tasks: set[asyncio.Task] = set()


def _fire(coro: Coroutine[Any, Any, None]) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _send_verification_email_background(username: str, email: str, code: str) -> None:
    sent = await send_verification_email(email, code)
    if not sent:
        logger.warning(f"Resend verification email failed for '{username}'")


# ============================================================
# Request/Response Models
# ============================================================

_EMAIL_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class RegisterRequest(BaseModel):
    """User registration request."""
    username: str = Field(..., min_length=3, max_length=20, pattern="^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=6, max_length=72)  # bcrypt max is 72 bytes
    email: EmailStr = Field(..., max_length=254)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("email must be a string")
        normalized = v.strip().lower()
        if _EMAIL_CONTROL_RE.search(normalized):
            raise ValueError("email contains invalid characters")
        return normalized


class LoginRequest(BaseModel):
    """User login request."""
    username: str = Field(..., min_length=3, max_length=20, pattern="^[a-zA-Z0-9_-]+$")
    password: str


class AuthResponse(BaseModel):
    """Authentication response."""
    success: bool
    message: str
    username: Optional[str] = None
    is_admin: Optional[bool] = None
    verification_required: bool = False


class ChangePasswordRequest(BaseModel):
    """Change-password request."""
    old_password: str = Field(..., min_length=1, max_length=72)  # bcrypt max is 72 bytes
    new_password: str = Field(..., min_length=6, max_length=72)  # bcrypt max is 72 bytes


class VerifyEmailRequest(BaseModel):
    """Registration email verification request."""
    username: str = Field(..., min_length=3, max_length=20, pattern="^[a-zA-Z0-9_-]+$")
    code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")


class ResendVerificationRequest(BaseModel):
    """Resend registration verification code request."""
    username: str = Field(..., min_length=3, max_length=20, pattern="^[a-zA-Z0-9_-]+$")


def _normalize_ip(ip: str) -> str:
    """Strip IPv6-mapped IPv4 prefix so ::ffff:1.2.3.4 → 1.2.3.4."""
    if ip and ip.startswith("::ffff:"):
        return ip[7:]
    return ip


# IPs that are trusted to forward the real client IP via headers.
# Only loopback addresses qualify — Cloudflare Tunnel connects from 127.0.0.1.
_TRUSTED_PROXY_IPS = frozenset({"127.0.0.1", "::1"})


def _get_client_ip(request) -> str:
    """Extract the real client IP, respecting Cloudflare/proxy headers only from trusted proxies.

    When the direct TCP connection comes from a trusted proxy (loopback), read the
    real IP from Cloudflare or standard forwarding headers.  Otherwise the direct
    connection IP is used as-is — accepting forwarded headers from untrusted sources
    would allow any client to spoof their IP and bypass rate limiting.

    Header priority (trusted proxy only):
        1. CF-Connecting-IP  — set by Cloudflare Tunnel
        2. X-Forwarded-For   — first entry in the chain
        3. X-Real-IP         — set by some reverse proxies
        4. request.client.host — direct connection fallback
    """
    if request.client is None:
        return "unknown"

    direct = request.client.host or ""

    if direct in _TRUSTED_PROXY_IPS:
        cf = request.headers.get("CF-Connecting-IP", "").strip()
        if cf:
            return _normalize_ip(cf)
        xff = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if xff:
            return _normalize_ip(xff)
        xri = request.headers.get("X-Real-IP", "").strip()
        if xri:
            return _normalize_ip(xri)

    return _normalize_ip(direct) if direct else "unknown"


# ============================================================
# Auth Routes
# ============================================================

@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user"
)
async def register(http_request: Request, request: RegisterRequest) -> AuthResponse:
    """
    Register a new user.

    Args:
        http_request: FastAPI request (for IP-based rate limiting)
        request: Username and password

    Returns:
        AuthResponse with registration status
    """
    try:
        # Rate limit: 3 registration attempts per IP per 60 seconds.
        # bcrypt cost (~250ms/hash) makes this endpoint a CPU-exhaustion target without limiting.
        client_ip = _get_client_ip(http_request)
        rl_key = f"register:{client_ip}"
        if rate_limiter.is_over_limit(rl_key, max_requests=3, window_seconds=60):
            wait = rate_limiter.retry_after(rl_key, window_seconds=60)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"注册请求过于频繁，请 {wait} 秒后重试",
                headers={"Retry-After": str(wait)},
            )

        # Record this attempt unconditionally — failed attempts (username already exists)
        # must also consume a rate-limit slot to prevent username enumeration via unlimited probing.
        rate_limiter.record(rl_key)

        success = auth_manager.register_user(
            username=request.username,
            password=request.password,
            email=request.email,
        )

        if success:
            verification_required = not auth_manager.is_email_verified(request.username)
            if verification_required:
                code = auth_manager.generate_verification_code(request.username)
                if code:
                    sent = await send_verification_email(request.email, code)
                    if not sent:
                        logger.warning(
                            f"Verification email send failed for '{request.username}' "
                            "(user can retry via /api/auth/resend-verification)"
                        )
            return AuthResponse(
                success=True,
                message=(
                    "验证码已发送至邮箱，请查收" if verification_required
                    else "User registered successfully"
                ),
                username=request.username,
                verification_required=verification_required,
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
        client_ip = _get_client_ip(request)
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

        if not auth_manager.is_email_verified(credentials.username):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="请先验证邮箱后再登录",
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
            samesite="strict"
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


_VERIFY_FAILURE_MESSAGES = {
    "not_found": "用户不存在",
    "too_many_attempts": "验证码错误次数过多，请重新发送验证码",
    "expired": "验证码已过期，请重新发送",
    "invalid_code": "验证码错误",
}


@router.post(
    "/verify-email",
    response_model=AuthResponse,
    summary="Verify registration email code"
)
async def verify_email(http_request: Request, request: VerifyEmailRequest) -> AuthResponse:
    """
    Verify the 6-digit code sent to the user's email during registration.

    Max 5 attempts per code before it must be resent via /resend-verification.
    Also IP rate-limited — the per-code attempt counter alone doesn't stop an
    attacker from probing many different (possibly fabricated) usernames.
    """
    client_ip = _get_client_ip(http_request)
    rl_key = f"verify-email:{client_ip}"
    if rate_limiter.is_over_limit(rl_key, max_requests=10, window_seconds=60):
        wait = rate_limiter.retry_after(rl_key, window_seconds=60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"请求过于频繁，请 {wait} 秒后重试",
            headers={"Retry-After": str(wait)},
        )
    rate_limiter.record(rl_key)

    result = auth_manager.verify_email(request.username, request.code)

    if not result["success"]:
        message = _VERIFY_FAILURE_MESSAGES.get(result["reason"], "验证失败")
        if result["reason"] == "invalid_code":
            message = f"{message}，剩余 {result['attempts_remaining']} 次机会"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return AuthResponse(success=True, message="邮箱验证成功，请登录", username=request.username)


@router.post(
    "/resend-verification",
    response_model=AuthResponse,
    summary="Resend registration verification code"
)
async def resend_verification(http_request: Request, request: ResendVerificationRequest) -> AuthResponse:
    """
    Resend a fresh verification code. Rate-limited per username (stop bombing one
    account) and per IP (stop cycling through many usernames to run up email sends).

    Always returns success (even for unknown usernames) to avoid leaking account existence.
    """
    client_ip = _get_client_ip(http_request)
    ip_rl_key = f"resend-verification-ip:{client_ip}"
    if rate_limiter.is_over_limit(ip_rl_key, max_requests=5, window_seconds=60):
        wait = rate_limiter.retry_after(ip_rl_key, window_seconds=60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"请求过于频繁，请 {wait} 秒后重试",
            headers={"Retry-After": str(wait)},
        )
    rate_limiter.record(ip_rl_key)

    rl_key = f"resend-verification:{request.username}"
    if rate_limiter.is_over_limit(rl_key, max_requests=1, window_seconds=60):
        wait = rate_limiter.retry_after(rl_key, window_seconds=60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"请 {wait} 秒后重试",
            headers={"Retry-After": str(wait)},
        )
    rate_limiter.record(rl_key)

    code = auth_manager.generate_verification_code(request.username)
    if code:
        email = auth_manager.get_user_email(request.username)
        if email:
            # Fired in the background, not awaited: awaiting the real Resend
            # HTTP call here would make response latency depend on whether
            # the username exists (network round-trip vs. instant), leaking
            # exactly the account-existence signal this endpoint is designed
            # to hide behind its always-success response.
            _fire(_send_verification_email_background(request.username, email, code))

    return AuthResponse(success=True, message="如账号存在，验证码已发送", username=request.username)


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
            samesite="strict",
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


@router.post(
    "/directus-login",
    response_model=AuthResponse,
    summary="Login via Directus credentials"
)
async def directus_login(
    credentials: LoginRequest,
    response: Response,
    request: Request,
) -> AuthResponse:
    """
    Login using Directus account credentials.

    Authenticates against Directus (email = {username}@lab.cloudnetops.tech),
    then issues a local session cookie so the rest of the platform works
    identically to a regular login.

    Args:
        credentials: username + password
        response: FastAPI response (for setting cookie)
        request: FastAPI request (for rate limiting)

    Returns:
        AuthResponse with login status
    """
    try:
        client_ip = _get_client_ip(request)
        rl_key = f"login:{client_ip}"
        if rate_limiter.is_over_limit(rl_key, max_requests=5, window_seconds=60):
            wait = rate_limiter.retry_after(rl_key, window_seconds=60)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"登录尝试过于频繁，请 {wait} 秒后重试",
                headers={"Retry-After": str(wait)},
            )

        # Authenticate against Directus
        token = await directus_auth_login(credentials.username, credentials.password)
        if not token:
            rate_limiter.record(rl_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Directus 账号或密码错误",
            )

        # Verify token to get canonical username and role
        result = await verify_directus_token(token)
        if not result:
            rate_limiter.record(rl_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Directus 认证失败",
            )
        username, is_admin = result

        # Issue a local session so the frontend cookie flow is unchanged
        session_token = auth_manager.create_session(username, login_ip=client_ip)
        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=SESSION_COOKIE_SECURE,
            max_age=86400,
            samesite="strict",
        )

        return AuthResponse(
            success=True,
            message="Directus 登录成功",
            username=username,
            is_admin=is_admin,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Directus login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登录失败",
        )
