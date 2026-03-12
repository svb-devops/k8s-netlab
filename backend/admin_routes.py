"""
K8S NetLab - Admin API Routes

Read-only observability endpoint for system administrators.
Protected by a static ADMIN_TOKEN sent as the X-Admin-Token request header.

Usage:
    curl -H "X-Admin-Token: <token>" http://localhost:8000/api/admin/status
"""

import asyncio
import logging
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from backend import config
from backend.auth import auth_manager
from backend.vm_tracker import vm_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _fetch_geo(ip: str) -> str:
    """Resolve IP to 'City, Country' via ipwho.is. Returns '' on any failure."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"https://ipwho.is/{ip}")
            d = r.json()
            if d.get("success"):
                parts = [p for p in [d.get("city"), d.get("country")] if p]
                return ", ".join(parts)
    except Exception:
        pass
    return ""


# ============================================================
# Auth Dependency
# ============================================================

def require_admin(x_admin_token: Optional[str] = Header(None)) -> None:
    """
    Verify the X-Admin-Token header.

    Uses secrets.compare_digest to prevent timing-based token enumeration.
    Returns 503 when ADMIN_TOKEN is not configured (fail-safe over fail-open).
    """
    if not config.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API not configured — set ADMIN_TOKEN in .env",
        )
    if not x_admin_token or not secrets.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing admin token",
        )


# ============================================================
# Response Models
# ============================================================

class VMDetail(BaseModel):
    vm_id: int
    owner: str
    created_at: str
    age_minutes: float


class SessionDetail(BaseModel):
    username: str
    is_admin: bool
    login_ip: Optional[str]
    login_location: Optional[str]       # e.g. "San Francisco, United States"
    login_time: str
    expires_at: str
    registered_at: Optional[str]
    current_experiment: Optional[str]   # e.g. "05" — set when user opens an experiment
    last_activity: Optional[str]        # ISO timestamp of last experiment page load
    vms: list[VMDetail]


class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str = Field(..., min_length=6, max_length=100)


class AdminStats(BaseModel):
    total_users: int
    active_sessions: int
    total_tracked_vms: int


class AdminStatusResponse(BaseModel):
    stats: AdminStats
    sessions: list[SessionDetail]


# ============================================================
# Routes
# ============================================================

@router.get(
    "/status",
    response_model=AdminStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin status dashboard",
    description=(
        "Returns active sessions enriched with per-user VM assignments and registration date. "
        "Requires X-Admin-Token header."
    ),
)
async def admin_status(
    _: None = Depends(require_admin),
) -> AdminStatusResponse:
    """
    Admin observability endpoint.

    Aggregates:
    - Active (non-expired) sessions with login IP and time
    - Per-user VM list with age
    - System-wide counts

    Returns:
        AdminStatusResponse with stats and enriched session list
    """
    # --- Load all data ---
    active_sessions = auth_manager.get_active_sessions()
    users_summary = auth_manager.get_users_summary()
    all_vms = vm_tracker.get_all_vms_with_details()

    # Resolve geolocation for all unique login IPs in parallel (2s timeout each)
    unique_ips = list({s.get("login_ip") for s in active_sessions if s.get("login_ip")})
    geo_results = await asyncio.gather(*[_fetch_geo(ip) for ip in unique_ips], return_exceptions=True)
    geo_map: dict[str, str] = {
        ip: (r if isinstance(r, str) else "")
        for ip, r in zip(unique_ips, geo_results)
    }

    # Index VMs by owner for O(1) lookup
    vms_by_owner: dict[str, list[VMDetail]] = {}
    for vm in all_vms:
        owner = vm["owner"]
        vms_by_owner.setdefault(owner, []).append(VMDetail(**vm))

    # Build enriched session list (most recent login first)
    sessions: list[SessionDetail] = [
        SessionDetail(
            username=s["username"],
            is_admin=s["username"] in config.ADMIN_USERNAMES,
            login_ip=s.get("login_ip"),
            login_location=geo_map.get(s.get("login_ip", ""), "") or None,
            login_time=s["created_at"],
            expires_at=s["expires_at"],
            registered_at=users_summary.get(s["username"], {}).get("created_at"),
            current_experiment=s.get("current_experiment"),
            last_activity=s.get("last_activity"),
            vms=vms_by_owner.get(s["username"], []),
        )
        for s in active_sessions
    ]
    sessions.sort(key=lambda s: s.login_time, reverse=True)

    stats = AdminStats(
        total_users=len(users_summary),
        active_sessions=len(sessions),
        total_tracked_vms=len(all_vms),
    )

    logger.info(
        f"Admin status queried: {stats.active_sessions} active sessions, "
        f"{stats.total_tracked_vms} tracked VMs"
    )

    return AdminStatusResponse(stats=stats, sessions=sessions)


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    summary="Reset a user's password (admin action, no old password required)",
)
async def reset_password(
    req: ResetPasswordRequest,
    _: None = Depends(require_admin),
) -> dict:
    """Force-reset any user's password without knowing the old one."""
    if not auth_manager.reset_password(req.username, req.new_password):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{req.username}' not found",
        )
    logger.info(f"Admin reset password for '{req.username}'")
    return {"success": True, "message": f"Password reset for '{req.username}'"}
