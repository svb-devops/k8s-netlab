"""
K8S NetLab - FastAPI Routes

RESTful API endpoints for VM management.
All routes use vm_manager functions and return standardized JSON responses.
"""

import asyncio
import functools
import logging
from typing import Any, Dict, List, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend import config
from backend.auth_deps import get_current_user
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.proxmox_api import connect_proxmox
from backend.rate_limiter import rate_limiter
from backend.task_registry import register as register_task
from backend.vm_manager import (
    NoAvailableVMId,
    SystemCapacityExceeded,
    VMQuotaExceeded,
    VMRateLimited,
    create_vm,
    delete_vm,
    list_vms,
    provision_vm_for_user,
)
from backend.vm_tracker import vm_tracker


def _get_lab_session_repo() -> LabSessionRepository:
    return LabSessionRepository()

logger = logging.getLogger(__name__)

# Create API router
router = APIRouter(prefix="/api", tags=["vms"])


# ============================================================
# Request/Response Models
# ============================================================

class CreateVMRequest(BaseModel):
    """Request model for VM creation."""

    vm_id: Optional[int] = Field(
        None,
        description="VM ID (100-999999). If not provided, will auto-assign.",
        ge=100,
        le=999999
    )
    # template_id is server-controlled (from config.VM_TEMPLATE_ID).
    # Clients must NOT specify it — removing it from the request model
    # ensures a single source of truth and prevents client-side drift.

    model_config = ConfigDict(json_schema_extra={"example": {"vm_id": 500}})


class VMResponse(BaseModel):
    """Response model for VM operations."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    model_config = ConfigDict(json_schema_extra={"example": {"success": True, "data": {"vm_id": 500, "name": "k8s-lab-500", "cores": 4, "memory_mb": 8192}, "error": None}})


class VMListResponse(BaseModel):
    """Response model for VM list."""

    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


# ============================================================
# API Routes
# ============================================================

@router.post(
    "/vms/create",
    response_model=VMResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new VM",
    description="Clone a template and create a new VM with configured resources"
)
async def api_create_vm(
    request: CreateVMRequest,
    current_user: str = Depends(get_current_user)
) -> VMResponse:
    """
    Create a new VM by cloning a template.

    Args:
        request: VM creation parameters (vm_id optional, template_id required)
        current_user: Current authenticated user (injected by auth dependency)

    Returns:
        VMResponse with created VM details

    Raises:
        HTTPException: If creation fails or not authenticated
    """
    try:
        # Validate explicit vm_id against the configured range (pure request
        # validation — stays in the route layer, not part of the shared
        # provisioning core).
        vm_id: Optional[int] = None
        if request.vm_id is not None:
            if not (config.VM_ID_MIN <= request.vm_id <= config.VM_ID_MAX):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"vm_id must be in range {config.VM_ID_MIN}–{config.VM_ID_MAX}",
                )
            vm_id = request.vm_id

        # provision_vm_for_user does reconcile -> quota -> rate-limit -> assign ->
        # create_vm -> track_vm (shared with LabGen's auto-provisioning path).
        # Pass this module's own vm_tracker/rate_limiter/list_vms/create_vm/config
        # references through explicitly so `patch("backend.api_routes.X", ...)`
        # in existing tests keeps intercepting them exactly as before.
        loop = asyncio.get_running_loop()
        provision_call = functools.partial(
            provision_vm_for_user,
            current_user,
            vm_id,
            _config=config,
            _vm_tracker=vm_tracker,
            _rate_limiter=rate_limiter,
            _list_vms=list_vms,
            _create_vm=create_vm,
        )
        try:
            data = await asyncio.wait_for(
                register_task(loop.run_in_executor(None, provision_call)),
                timeout=360,
            )
        except asyncio.TimeoutError:
            logger.error(f"API: VM creation timed out after 360s (user='{current_user}')")
            raise HTTPException(status_code=504, detail="VM creation timed out")
        except VMQuotaExceeded as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"已达到每用户 VM 配额上限（{e.limit} 个）。"
                    f"当前已有 {e.current_count} 个 VM，请先删除现有 VM 再创建新的。"
                ),
            )
        except SystemCapacityExceeded as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"实验环境当前已满员（{e.current_count}/{e.limit} 个）。"
                    "请稍候，当有同学完成实验并释放环境后即可创建。"
                ),
            )
        except VMRateLimited as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"VM 创建过于频繁，请 {e.retry_after // 60} 分钟后重试",
                headers={"Retry-After": str(e.retry_after)},
            )
        except NoAvailableVMId as e:
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=str(e),
            )
        except RuntimeError as e:
            logger.error(f"API: VM creation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            )

        logger.info(f"API: VM {data.get('vm_id')} created successfully by '{current_user}'")
        return VMResponse(success=True, data=data, error=None)

    except ValueError as e:
        logger.error(f"API: Invalid input: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(f"API: Unexpected error creating VM: {e}", exc_info=True)
        detail = str(e) if config.APP_DEBUG else "Internal server error"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )


@router.delete(
    "/vms/{vm_id}",
    response_model=VMResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a VM",
    description="Stop and delete a VM"
)
async def api_delete_vm(
    vm_id: int = Path(..., ge=100, le=999999, description="VM ID to delete"),
    force: bool = Query(True, description="Force-stop VM before deletion"),
    current_user: str = Depends(get_current_user)
) -> VMResponse:
    """
    Delete a VM.

    Args:
        vm_id: ID of the VM to delete
        force: If True, force-stop the VM before deletion
        current_user: Current authenticated user (injected by auth dependency)

    Returns:
        VMResponse with deletion status

    Raises:
        HTTPException: If deletion fails, not authenticated, or not owner
    """
    try:
        # Check if user owns this VM
        if not vm_tracker.is_owner(vm_id, current_user):
            owner = vm_tracker.get_vm_owner(vm_id)
            logger.warning(f"API: User '{current_user}' tried to delete VM {vm_id} owned by '{owner}'")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this VM"
            )

        # Block deletion if VM is in use by an active LabGen lab session
        lab_session_repo = _get_lab_session_repo()
        if lab_session_repo.has_active_session_for_vm(str(vm_id)):
            logger.warning(f"API: User '{current_user}' tried to delete VM {vm_id} with active lab session")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="VM is in use by an active lab session and cannot be deleted"
            )

        logger.info(f"API: User '{current_user}' deleting VM {vm_id} (force={force})")

        # Delete VM using vm_manager (run in thread — blocks while polling Proxmox)
        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                register_task(loop.run_in_executor(None, lambda: delete_vm(vm_id=vm_id, force=force))),
                timeout=120,
            )
        except asyncio.TimeoutError:
            logger.error(f"API: VM {vm_id} deletion timed out after 120s")
            raise HTTPException(status_code=504, detail="VM deletion timed out")

        if result['success']:
            logger.info(f"API: VM {vm_id} deleted successfully")
            # Untrack VM
            vm_tracker.untrack_vm(vm_id)
            return VMResponse(**result)
        else:
            logger.error(f"API: VM deletion failed: {result['error']}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result['error']
            )

    except ValueError as e:
        logger.error(f"API: Invalid VM ID: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(f"API: Unexpected error deleting VM {vm_id}: {e}", exc_info=True)
        detail = str(e) if config.APP_DEBUG else "Internal server error"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )


@router.get(
    "/vms",
    response_model=VMListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all VMs",
    description="Get a list of all VMs on the Proxmox node"
)
async def api_list_vms(
    current_user: str = Depends(get_current_user)
) -> VMListResponse:
    """
    List user's VMs.

    Returns:
        VMListResponse with list of current user's VMs

    Raises:
        HTTPException: If listing fails or not authenticated
    """
    try:
        logger.info(f"API: Listing VMs for user '{current_user}'")

        # List all VMs using vm_manager (run in thread — blocks on Proxmox network call)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, list_vms)

        if result['success']:
            # Filter VMs to only show user's VMs
            all_vms = result['data']
            user_vm_ids = set(vm_tracker.get_user_vms(current_user))

            # Auto-claim orphaned VMs (VMs without owner)
            # This handles pre-existing VMs or VMs created outside the system
            for vm in all_vms:
                vm_id = vm['vmid']

                # Skip template VMs and the configured template ID
                if vm.get('template') or vm_id == config.VM_TEMPLATE_ID:
                    continue

                # If VM has no owner, assign it to current user (only if quota allows)
                owner = vm_tracker.get_vm_owner(vm_id)
                if owner is None:
                    if len(user_vm_ids) >= config.MAX_VMS_PER_USER:
                        logger.warning(
                            f"Auto-claim skipped: VM {vm_id} orphaned but user '{current_user}' "
                            f"is at quota ({len(user_vm_ids)}/{config.MAX_VMS_PER_USER})"
                        )
                    else:
                        logger.info(f"Auto-claiming orphaned VM {vm_id} for user '{current_user}'")
                        vm_tracker.track_vm(vm_id, owner=current_user)
                        user_vm_ids.add(vm_id)

            # Only include VMs owned by current user
            user_vms = [vm for vm in all_vms if vm['vmid'] in user_vm_ids]

            logger.info(f"API: Found {len(user_vms)} VMs for user '{current_user}' (total: {len(all_vms)})")

            return VMListResponse(
                success=True,
                data=user_vms,
                error=None
            )
        else:
            logger.error(f"API: VM listing failed: {result['error']}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result['error']
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.critical(f"API: Unexpected error listing VMs: {e}", exc_info=True)
        detail = str(e) if config.APP_DEBUG else "Internal server error"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )


@router.get(
    "/vms/{vm_id}/status",
    response_model=VMResponse,
    status_code=status.HTTP_200_OK,
    summary="Get VM status",
    description="Get the current status of a specific VM"
)
async def api_get_vm_status(
    vm_id: int = Path(..., ge=100, le=999999, description="VM ID"),
    current_user: str = Depends(get_current_user),
) -> VMResponse:
    """
    Get VM status.

    Args:
        vm_id: ID of the VM
        current_user: Authenticated user (injected by dependency)

    Returns:
        VMResponse with VM status details

    Raises:
        HTTPException: If VM not found, not owned by user, or status retrieval fails
    """
    # Ownership check — only VM owner may query status
    owner = vm_tracker.get_vm_owner(vm_id)
    if owner != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden"
        )

    try:
        logger.info(f"API: Getting status for VM {vm_id}")

        # Connect to Proxmox and get VM status (run in thread — blocking network I/O)
        def _fetch_status() -> dict:
            px = connect_proxmox()
            return cast(dict, px.nodes(config.PROXMOX_NODE).qemu(vm_id).status.current.get())

        loop = asyncio.get_running_loop()
        status_data = await loop.run_in_executor(None, _fetch_status)

        logger.info(f"API: VM {vm_id} status retrieved: {status_data.get('status')}")

        return VMResponse(
            success=True,
            data={
                "vm_id": vm_id,
                "status": status_data.get("status"),
                "uptime": status_data.get("uptime", 0),
                "cpu": status_data.get("cpu", 0),
                "mem": status_data.get("mem", 0),
                "maxmem": status_data.get("maxmem", 0),
                "cpus": status_data.get("cpus", 0),
                "name": status_data.get("name", ""),
            },
            error=None
        )

    except Exception as e:
        logger.error(f"API: Failed to get VM {vm_id} status: {e}")

        # Check if VM doesn't exist
        if "does not exist" in str(e).lower() or "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"VM {vm_id} not found"
            )

        detail = f"Failed to get VM status: {str(e)}" if config.APP_DEBUG else "Internal server error"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )


@router.head("/health", include_in_schema=False)
async def api_health_head() -> Response:
    """HEAD handler for monitoring tools (e.g. UptimeRobot) that use HEAD instead of GET."""
    return Response(status_code=status.HTTP_200_OK)


def _check_labgen_session_health() -> Dict[str, Any]:
    """Read-only scan of lab session and data file state.

    Returns counts and warnings. Never exposes user-identifiable data or secrets.
    """
    try:
        from pathlib import Path as _Path
        import json as _json
        from backend.labgen.lab_session_repository import LabSessionRepository
        from backend.labgen.models import LabSessionStatus

        repo = LabSessionRepository()
        sessions = repo.list_all()

        active_statuses = {LabSessionStatus.LAB_ACTIVE}
        failed_statuses = {LabSessionStatus.LAB_START_FAILED, LabSessionStatus.LAB_CLEANUP_FAILED}

        active_count = sum(1 for s in sessions if s.lab_session_status in active_statuses)
        failed_count = sum(1 for s in sessions if s.lab_session_status in failed_statuses)

        data_dir = _Path("data")
        tainted_count = 0
        tainted_path = data_dir / "tainted_vms.json"
        if tainted_path.exists():
            try:
                tainted = _json.loads(tainted_path.read_text())
                tainted_count = len(tainted) if isinstance(tainted, dict) else 0
            except Exception:
                pass

        warnings: list[str] = []

        diffs_path = data_dir / "lab_review_diffs.json"
        diffs_size_mb: float = 0.0
        if diffs_path.exists():
            diffs_size_mb = round(diffs_path.stat().st_size / 1024 / 1024, 2)
            if diffs_size_mb >= 1.0:
                warnings.append(f"lab_review_diffs.json is {diffs_size_mb}MB — run DataRetentionService cleanup")

        drafts_path = data_dir / "lab_drafts.json"
        zombie_count = 0
        if drafts_path.exists():
            try:
                from backend.labgen.data_retention import DataRetentionService, _age_days
                raw = _json.loads(drafts_path.read_text())
                drafts = raw if isinstance(raw, list) else list(raw.values())
                zombie_count = sum(
                    1 for d in drafts
                    if d.get("publish_status") == "draft"
                    and not d.get("rehearsal_completed")
                    and _age_days(d.get("updated_at") or d.get("created_at")) >= 30
                )
                if zombie_count > 0:
                    warnings.append(f"{zombie_count} zombie draft(s) older than 30 days")
            except Exception:
                pass

        if failed_count > 0:
            warnings.append(f"{failed_count} session(s) need admin recovery (LAB_START_FAILED/LAB_CLEANUP_FAILED)")
        if tainted_count > 0:
            warnings.append(f"{tainted_count} tainted VM(s) — students blocked until resolved")

        return {
            "status": "degraded" if warnings else "ok",
            "active_session_count": active_count,
            "failed_terminal_session_count": failed_count,
            "tainted_vm_count": tainted_count,
            "lab_review_diffs_size_mb": diffs_size_mb,
            "zombie_draft_count": zombie_count,
            "session_ttl_minutes": config.LABGEN_LAB_SESSION_TTL_MINUTES,
            "warnings": warnings,
        }
    except Exception as exc:
        logger.warning("labgen_session_health check failed: %s", exc)
        return {"status": "unknown", "error": "health check failed"}


_EMAIL_FAILURE_ALERT_THRESHOLD = 3


def _check_email_health() -> Dict[str, Any]:
    """Aggregate recent Resend send failures for /api/health.

    Only exposes a count, never raw failure entries (which may embed
    recipient addresses in the failure reason string).
    """
    try:
        import json as _json
        from datetime import datetime, timedelta, timezone

        from backend.email_client import _FAILURE_LOG

        if not _FAILURE_LOG.exists():
            return {"status": "ok", "failures_last_24h": 0, "warnings": []}

        raw = _json.loads(_FAILURE_LOG.read_text())
        failures = raw.get("failures", []) if isinstance(raw, dict) else []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_count = 0
        for entry in failures:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (KeyError, ValueError, TypeError):
                continue
            if ts >= cutoff:
                recent_count += 1

        warnings: list[str] = []
        if recent_count >= _EMAIL_FAILURE_ALERT_THRESHOLD:
            warnings.append(
                f"{recent_count} Resend email send failure(s) in last 24h — "
                "check RESEND_API_KEY/quota"
            )

        return {
            "status": "degraded" if warnings else "ok",
            "failures_last_24h": recent_count,
            "warnings": warnings,
        }
    except Exception as exc:
        logger.warning("email_health check failed: %s", exc)
        return {"status": "unknown", "error": "health check failed"}


def _check_verifier_credentials_health() -> Dict[str, Any]:
    """Check verifier credential store for configured exempt/staging VMs.

    Returns a dict suitable for embedding in the health response.
    Never exposes credential content — only presence.
    """
    try:
        from backend.labgen.verifier_credentials import VerifierCredentialStore
        store = VerifierCredentialStore(config.LABGEN_VERIFIER_CREDENTIAL_ROOT)
        root_exists = store.credential_root_exists

        vm_ids = [
            str(v).strip()
            for v in config.VM_CLEANUP_EXEMPT_IDS
            if str(v).strip().isdigit()
        ]

        vm_status: Dict[str, Any] = {}
        missing: list[str] = []
        for vm_id in vm_ids:
            present = store.exists(vm_id)
            vm_status[vm_id] = {"credentials_present": present}
            if not present:
                missing.append(vm_id)

        return {
            "status": "degraded" if missing else "ok",
            "credential_root_exists": root_exists,
            "exempt_vms": vm_status,
            "missing_credentials": missing,
        }
    except Exception as exc:
        logger.warning("verifier_credentials_health check failed: %s", exc)
        return {"status": "unknown", "error": "health check failed"}


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Check if the API and Proxmox connection are healthy"
)
async def api_health_check() -> Dict[str, Any]:
    """
    Health check endpoint.

    Returns:
        dict: Health status with Proxmox connection info and LabGen credential status
    """
    loop = asyncio.get_running_loop()

    proxmox_ok = False
    proxmox_error: Optional[str] = None
    try:
        await loop.run_in_executor(None, connect_proxmox)
        proxmox_ok = True
    except Exception as e:
        logger.error(f"Proxmox health check failed: {e}")
        proxmox_error = "Proxmox connection failed"

    labgen_health = await loop.run_in_executor(None, _check_verifier_credentials_health)
    session_health = await loop.run_in_executor(None, _check_labgen_session_health)
    email_health = await loop.run_in_executor(None, _check_email_health)

    if not proxmox_ok:
        return {
            "status": "unhealthy",
            "error": proxmox_error,
            "proxmox": {"connected": False},
            "labgen": labgen_health,
            "sessions": session_health,
            "email": email_health,
        }

    return {
        "status": "healthy",
        "proxmox": {"connected": True},
        "labgen": labgen_health,
        "sessions": session_health,
        "email": email_health,
    }


@router.get(
    "/quota",
    status_code=status.HTTP_200_OK,
    summary="Get VM quota",
    description="Get current user's VM quota usage and system-wide limits"
)
async def api_get_quota(
    current_user: str = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Return quota usage for the current user and the system.

    Returns:
        dict with user and system quota details
    """
    user_count = len(vm_tracker.get_user_vms(current_user))
    total_count = len(vm_tracker.get_all_tracked_vms())
    return {
        "user": {
            "current": user_count,
            "max": config.MAX_VMS_PER_USER,
            "available": max(0, config.MAX_VMS_PER_USER - user_count),
        },
        "system": {
            "current": total_count,
            "max": config.MAX_TOTAL_VMS,
            "available": max(0, config.MAX_TOTAL_VMS - total_count),
        },
    }
