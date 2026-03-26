"""
K8S NetLab - VM Lifecycle Manager

Creates, deletes, and lists VMs on Proxmox VE.
Each operation uses SmartLogger for structured logging and reporting.
"""

import logging
import time
from typing import Any, Dict

from proxmoxer.core import ResourceException

from backend import config
from backend.proxmox_api import connect_proxmox
from backend.smart_logger import SmartLogger

logger = logging.getLogger(__name__)

# Valid VM ID range per Proxmox (100-999999)
VM_ID_MIN = 100
VM_ID_MAX = 999999


def _validate_vm_id(vm_id: int) -> None:
    """
    Validate that a VM ID is within the allowed Proxmox range.

    Args:
        vm_id: The VM ID to validate

    Raises:
        ValueError: If vm_id is outside 100-999999
    """
    if not isinstance(vm_id, int):
        raise ValueError(f"VM ID must be an integer, got: {type(vm_id).__name__}")
    if not VM_ID_MIN <= vm_id <= VM_ID_MAX:
        raise ValueError(f"Invalid VM ID: {vm_id}. Must be {VM_ID_MIN}-{VM_ID_MAX}")


def _delete_orphan_vm(vm_id: int, node: Any, slog: SmartLogger) -> None:
    """
    Best-effort cleanup: delete a VM that was cloned but whose creation failed.
    Errors are logged but not re-raised so they never mask the original failure.
    """
    slog.warning(f"Rolling back: deleting orphaned VM {vm_id}")
    try:
        vm = node.qemu(vm_id)
        try:
            # VM may be starting if Step 4 raised; try to stop it first
            vm.status.stop.post()
        except Exception:
            pass  # already stopped — that's fine
        vm.delete()
        slog.warning(f"Orphaned VM {vm_id} deleted (rollback complete)")
    except Exception as cleanup_err:
        slog.error(f"Rollback failed for VM {vm_id}: {cleanup_err}", cleanup_err)


def create_vm(vm_id: int, template_id: int) -> Dict[str, Any]:
    """
    Create a new VM by cloning a template, configuring resources, and starting it.

    Steps: validate -> clone template -> configure CPU/RAM -> start VM.
    On partial failure (clone succeeded but a later step failed), automatically
    deletes the orphaned VM to prevent untracked VMs in Proxmox.

    Args:
        vm_id: ID for the new VM (100-999999)
        template_id: Template VM ID to clone from

    Returns:
        dict: {'success': bool, 'data': dict or None, 'error': str or None}

    Raises:
        ValueError: If vm_id or template_id is invalid
    """
    _validate_vm_id(vm_id)
    _validate_vm_id(template_id)

    slog = SmartLogger(f"create_vm_{vm_id}")
    slog.info(f"Creating VM {vm_id} from template {template_id}")

    clone_completed = False
    node: Any = None

    try:
        proxmox = connect_proxmox()
        node = proxmox.nodes(config.PROXMOX_NODE)

        # Step 1: Clone template
        slog.info("Cloning template", {"template_id": template_id, "new_id": vm_id})
        clone_task_id = node.qemu(template_id).clone.post(
            newid=vm_id,
            name=f"k8s-lab-{vm_id}",
            full=0,  # linked clone: seconds instead of minutes (shares base-xxx-disk)
        )
        slog.info(f"Clone task started: {clone_task_id}")

        # Wait for clone task to complete
        slog.info("Waiting for clone task to complete...")
        max_wait = 60   # linked clone completes in seconds, 60s is ample
        wait_interval = 2  # seconds
        for i in range(max_wait // wait_interval):
            # Check task status
            task_status = node.tasks(clone_task_id).status.get()
            status = task_status.get('status')

            if status == 'stopped':
                exitstatus = task_status.get('exitstatus')
                if exitstatus == 'OK':
                    elapsed = (i + 1) * wait_interval
                    slog.success(f"Clone task completed successfully after {elapsed}s")
                    break
                else:
                    raise RuntimeError(f"Clone task failed with status: {exitstatus}")

            time.sleep(wait_interval)
        else:
            raise RuntimeError(f"Clone task did not complete within {max_wait}s")

        # VM now exists in Proxmox; subsequent failures must trigger rollback
        clone_completed = True

        # Step 2: Add VM to pool immediately (enables pool-scoped permissions)
        slog.info(f"Adding VM to pool '{config.PROXMOX_POOL}'")
        proxmox.pools(config.PROXMOX_POOL).put(vms=str(vm_id))
        slog.success(f"VM {vm_id} added to pool '{config.PROXMOX_POOL}'")

        # Step 3: Configure VM resources
        slog.info("Configuring VM resources", {
            "cores": config.VM_CORES,
            "memory_mb": config.VM_MEMORY_MB,
        })
        node.qemu(vm_id).config.put(
            cores=config.VM_CORES,
            memory=config.VM_MEMORY_MB,
        )
        slog.success(f"VM {vm_id} configured: {config.VM_CORES} cores, {config.VM_MEMORY_MB}MB RAM")

        # Step 4: Start VM
        slog.info("Starting VM")
        node.qemu(vm_id).status.start.post()
        slog.success(f"VM {vm_id} started")

        data = {
            "vm_id": vm_id,
            "name": f"k8s-lab-{vm_id}",
            "template_id": template_id,
            "cores": config.VM_CORES,
            "memory_mb": config.VM_MEMORY_MB,
            "clone_task": clone_task_id,
        }
        return {"success": True, "data": data, "error": None}

    except (ConnectionError, ResourceException) as e:
        slog.error(f"VM creation failed: {e}", e)
        if clone_completed and node is not None:
            _delete_orphan_vm(vm_id, node, slog)
        return {"success": False, "data": None, "error": str(e)}
    except Exception as e:
        slog.error(f"Unexpected error creating VM {vm_id}: {e}", e)
        if clone_completed and node is not None:
            _delete_orphan_vm(vm_id, node, slog)
        return {"success": False, "data": None, "error": str(e)}
    finally:
        slog.generate_report()


def delete_vm(vm_id: int, force: bool = False) -> Dict[str, Any]:
    """
    Stop (if running) and delete a VM.

    Args:
        vm_id: ID of the VM to delete (100-999999)
        force: If True, force-stop the VM before deletion

    Returns:
        dict: {'success': bool, 'data': dict or None, 'error': str or None}

    Raises:
        ValueError: If vm_id is invalid
    """
    _validate_vm_id(vm_id)

    slog = SmartLogger(f"delete_vm_{vm_id}")
    slog.info(f"Deleting VM {vm_id} (force={force})")

    try:
        proxmox = connect_proxmox()
        node = proxmox.nodes(config.PROXMOX_NODE)
        vm = node.qemu(vm_id)

        # Step 1: Check VM status and stop if running
        status_data = vm.status.current.get()
        vm_status = status_data.get("status", "unknown")
        slog.info(f"VM {vm_id} current status: {vm_status}")

        if vm_status == "running":
            if force:
                slog.info("Force-stopping VM")
                vm.status.stop.post()
            else:
                slog.info("Gracefully shutting down VM")
                vm.status.shutdown.post()
            slog.info(f"VM {vm_id} stop requested, waiting for VM to stop...")

            # Wait for VM to stop
            max_wait = 60  # seconds
            wait_interval = 2  # seconds
            for i in range(max_wait // wait_interval):
                status_data = vm.status.current.get()
                current_status = status_data.get("status", "unknown")
                if current_status == "stopped":
                    elapsed = (i + 1) * wait_interval
                    slog.success(f"VM {vm_id} stopped after {elapsed}s")
                    break
                time.sleep(wait_interval)
            else:
                raise RuntimeError(f"VM {vm_id} did not stop within {max_wait}s")

        # Step 2: Delete VM
        slog.info("Deleting VM")
        vm.delete()
        slog.success(f"VM {vm_id} deleted")

        return {
            "success": True,
            "data": {"vm_id": vm_id, "previous_status": vm_status},
            "error": None,
        }

    except (ConnectionError, ResourceException) as e:
        slog.error(f"VM deletion failed: {e}", e)
        return {"success": False, "data": None, "error": str(e)}
    except Exception as e:
        slog.error(f"Unexpected error deleting VM {vm_id}: {e}", e)
        return {"success": False, "data": None, "error": str(e)}
    finally:
        slog.generate_report()


def start_vm(vm_id: int) -> Dict[str, Any]:
    """
    Start a stopped VM.

    Args:
        vm_id: ID of the VM to start

    Returns:
        dict: {'success': bool, 'data': dict or None, 'error': str or None}

    Raises:
        ValueError: If vm_id is invalid
    """
    _validate_vm_id(vm_id)

    slog = SmartLogger(f"start_vm_{vm_id}")
    slog.info(f"Starting VM {vm_id}")

    try:
        proxmox = connect_proxmox()
        node = proxmox.nodes(config.PROXMOX_NODE)
        vm = node.qemu(vm_id)

        # Check current status
        status_data = vm.status.current.get()
        vm_status = status_data.get("status", "unknown")
        slog.info(f"VM {vm_id} current status: {vm_status}")

        if vm_status == "running":
            slog.info("VM is already running")
            return {
                "success": True,
                "data": {"vm_id": vm_id, "status": "running", "message": "VM already running"},
                "error": None,
            }

        # Start VM
        slog.info("Starting VM")
        vm.status.start.post()

        # Wait for VM to start
        max_wait = 60  # seconds
        wait_interval = 2  # seconds
        for i in range(max_wait // wait_interval):
            status_data = vm.status.current.get()
            current_status = status_data.get("status", "unknown")
            if current_status == "running":
                elapsed = (i + 1) * wait_interval
                slog.success(f"VM {vm_id} started after {elapsed}s")
                break
            time.sleep(wait_interval)
        else:
            raise RuntimeError(f"VM {vm_id} did not start within {max_wait}s")

        return {
            "success": True,
            "data": {"vm_id": vm_id, "status": "running"},
            "error": None,
        }

    except (ConnectionError, ResourceException) as e:
        slog.error(f"VM start failed: {e}", e)
        return {"success": False, "data": None, "error": str(e)}
    except Exception as e:
        slog.error(f"Unexpected error starting VM {vm_id}: {e}", e)
        return {"success": False, "data": None, "error": str(e)}
    finally:
        slog.generate_report()


def list_vms() -> Dict[str, Any]:
    """
    List all VMs on the configured Proxmox node.

    Returns:
        dict: {'success': bool, 'data': list or None, 'error': str or None}
    """
    slog = SmartLogger("list_vms")
    slog.info(f"Listing VMs on node '{config.PROXMOX_NODE}'")

    try:
        proxmox = connect_proxmox()
        vms = proxmox.nodes(config.PROXMOX_NODE).qemu.get()
        slog.success(f"Found {len(vms)} VMs")

        return {"success": True, "data": vms, "error": None}

    except (ConnectionError, ResourceException) as e:
        slog.error(f"Failed to list VMs: {e}", e)
        return {"success": False, "data": None, "error": str(e)}
    except Exception as e:
        slog.error(f"Unexpected error listing VMs: {e}", e)
        return {"success": False, "data": None, "error": str(e)}
    finally:
        slog.generate_report()
