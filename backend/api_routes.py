"""
K8S NetLab - FastAPI Routes

RESTful API endpoints for VM management.
All routes use vm_manager functions and return standardized JSON responses.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field

from backend import config
from backend.auth_deps import get_current_user
from backend.proxmox_api import connect_proxmox
from backend.rate_limiter import rate_limiter
from backend.task_registry import register as register_task
from backend.vm_manager import create_vm, delete_vm, list_vms
from backend.vm_tracker import vm_tracker

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
# Helper Functions
# ============================================================

def _find_available_vm_id() -> int:
    """
    Find the next available VM ID for auto-assignment.

    Scans VM IDs from config.VM_ID_MIN to config.VM_ID_MAX (inclusive)
    and returns the first available ID.

    Returns:
        int: Available VM ID within the configured range

    Raises:
        HTTPException: If no available IDs found
    """
    result = list_vms()
    if not result['success']:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list VMs: {result['error']}"
        )

    existing_ids = {vm['vmid'] for vm in result['data']}

    for vm_id in range(config.VM_ID_MIN, config.VM_ID_MAX + 1):
        if vm_id not in existing_ids:
            return vm_id

    raise HTTPException(
        status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
        detail=f"No available VM IDs in range {config.VM_ID_MIN}-{config.VM_ID_MAX}"
    )


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
        # Quota check: per-user and system-wide limits
        user_vm_count = len(vm_tracker.get_user_vms(current_user))
        if user_vm_count >= config.MAX_VMS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"已达到每用户 VM 配额上限（{config.MAX_VMS_PER_USER} 个）。"
                    f"当前已有 {user_vm_count} 个 VM，请先删除现有 VM 再创建新的。"
                ),
            )
        total_vm_count = len(vm_tracker.get_all_tracked_vms())
        if total_vm_count >= config.MAX_TOTAL_VMS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"实验环境当前已满员（{total_vm_count}/{config.MAX_TOTAL_VMS} 个）。"
                    "请稍候，当有同学完成实验并释放环境后即可创建。"
                ),
            )

        # Rate limit: 3 VM creations per user per hour
        if not rate_limiter.is_allowed(f"create_vm:{current_user}", max_requests=3, window_seconds=3600):
            wait = rate_limiter.retry_after(f"create_vm:{current_user}", window_seconds=3600)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"VM 创建过于频繁，请 {wait // 60} 分钟后重试",
                headers={"Retry-After": str(wait)},
            )

        # Validate or auto-assign VM ID
        if request.vm_id is not None:
            if not (config.VM_ID_MIN <= request.vm_id <= config.VM_ID_MAX):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"vm_id must be in range {config.VM_ID_MIN}–{config.VM_ID_MAX}",
                )
            vm_id = request.vm_id
        else:
            vm_id = _find_available_vm_id()

        logger.info(f"API: User '{current_user}' creating VM {vm_id} from template {config.VM_TEMPLATE_ID}")

        # Create VM using vm_manager (run in thread — blocks up to 300s polling Proxmox)
        loop = asyncio.get_running_loop()
        result = await register_task(loop.run_in_executor(None, create_vm, vm_id, config.VM_TEMPLATE_ID))

        if result['success']:
            logger.info(f"API: VM {vm_id} created successfully by '{current_user}'")
            # Track VM for auto-cleanup with owner
            vm_tracker.track_vm(vm_id, owner=current_user)
            return VMResponse(**result)
        else:
            logger.error(f"API: VM creation failed: {result['error']}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result['error']
            )

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
                detail=f"You don't have permission to delete this VM (owned by {owner})"
            )

        logger.info(f"API: User '{current_user}' deleting VM {vm_id} (force={force})")

        # Delete VM using vm_manager (run in thread — blocks while polling Proxmox)
        loop = asyncio.get_running_loop()
        result = await register_task(loop.run_in_executor(None, lambda: delete_vm(vm_id=vm_id, force=force)))

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

        # List all VMs using vm_manager
        result = list_vms()

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
            detail="You do not own this VM"
        )

    try:
        logger.info(f"API: Getting status for VM {vm_id}")

        # Connect to Proxmox and get VM status
        proxmox = connect_proxmox()
        node = proxmox.nodes(config.PROXMOX_NODE)

        # Get VM current status
        status_data = node.qemu(vm_id).status.current.get()

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
        dict: Health status with Proxmox connection info
    """
    try:
        # Test Proxmox connection
        proxmox = connect_proxmox()
        version_info = proxmox.version.get()

        return {
            "status": "healthy",
            "proxmox": {"connected": True}
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
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
