"""
K8S NetLab - VM Lifecycle Manager

Creates, deletes, and lists VMs on Proxmox VE.
Each operation uses SmartLogger for structured logging and reporting.
"""

import logging
import time
from typing import Any, Dict, Optional, cast

from proxmoxer.core import ResourceException

from backend import config
from backend.labgen.verifier_credentials import (
    CommandResult,
    VerifierCredentialStore,
    VerifierIdentityManager,
    VMCommandExecutorPort,
)
from backend.proxmox_api import connect_proxmox
from backend.rate_limiter import rate_limiter
from backend.smart_logger import SmartLogger
from backend.vm_tracker import vm_tracker

logger = logging.getLogger(__name__)

# Valid VM ID range per Proxmox (100-999999)
VM_ID_MIN = 100
VM_ID_MAX = 999999


class VMQuotaExceeded(Exception):
    """Raised when the calling user has reached config.MAX_VMS_PER_USER."""

    def __init__(self, current_count: int, limit: int):
        self.current_count = current_count
        self.limit = limit
        super().__init__(f"user VM count {current_count}/{limit}")


class SystemCapacityExceeded(Exception):
    """Raised when the total tracked VM count has reached config.MAX_TOTAL_VMS."""

    def __init__(self, current_count: int, limit: int):
        self.current_count = current_count
        self.limit = limit
        super().__init__(f"system VM count {current_count}/{limit}")


class VMRateLimited(Exception):
    """Raised when the per-user VM-creation rate limit has been hit."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"rate limited, retry after {retry_after}s")


class NoAvailableVMId(Exception):
    """Raised when no VM ID is available in the configured range."""


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


def _find_available_vm_id(cfg: Any, do_list_vms: Any) -> int:
    """Scan cfg.VM_ID_MIN..VM_ID_MAX and return the first ID not in Proxmox."""
    result = do_list_vms()
    if not result["success"]:
        raise RuntimeError(f"Failed to list VMs: {result['error']}")

    existing_ids = {vm["vmid"] for vm in result["data"]}
    for candidate in range(cfg.VM_ID_MIN, cfg.VM_ID_MAX + 1):
        if candidate not in existing_ids:
            return candidate

    raise NoAvailableVMId(f"No available VM IDs in range {cfg.VM_ID_MIN}-{cfg.VM_ID_MAX}")


def provision_vm_for_user(
    username: str,
    vm_id: Optional[int] = None,
    *,
    _config: Any = None,
    _vm_tracker: Any = None,
    _rate_limiter: Any = None,
    _list_vms: Any = None,
    _create_vm: Any = None,
) -> Dict[str, Any]:
    """
    Shared VM-creation core used by both POST /api/vms/create (backend/api_routes.py)
    and LabGen's background auto-provisioning path (backend/labgen/vm_provisioning.py).

    Pipeline: reconcile tracker vs Proxmox -> per-user/system quota check ->
    rate limit -> assign vm_id (if not given) -> create_vm -> track_vm.

    Pure sync function — caller decides whether to run this in a thread pool.

    The `_config`/`_vm_tracker`/`_rate_limiter`/`_list_vms`/`_create_vm` keyword-only
    params let a caller (namely api_create_vm) pass through *its own* module-level
    references so existing unit tests that patch `backend.api_routes.vm_tracker`
    etc. keep working unchanged — this function's own module globals remain the
    default for every other caller (e.g. LabGen's background provisioning).

    Raises:
        VMQuotaExceeded, SystemCapacityExceeded, VMRateLimited, NoAvailableVMId,
        RuntimeError (create_vm itself failed).
    Returns:
        create_vm()'s data dict (vm_id, name, template_id, cores, memory_mb, clone_task).
    """
    cfg = _config if _config is not None else config
    tracker = _vm_tracker if _vm_tracker is not None else vm_tracker
    limiter = _rate_limiter if _rate_limiter is not None else rate_limiter
    do_list_vms = _list_vms if _list_vms is not None else list_vms
    do_create_vm = _create_vm if _create_vm is not None else create_vm

    # Reconcile tracker with Proxmox before quota check. Removes stale tracker
    # entries for VMs that no longer exist in Proxmox, preventing false
    # "quota exceeded" errors from orphaned entries.
    try:
        proxmox_check = do_list_vms()
        if proxmox_check.get("success"):
            existing_ids = {vm["vmid"] for vm in proxmox_check["data"]}
            for stale_id in list(tracker.get_user_vms(username)):
                if stale_id not in existing_ids:
                    logger.warning(
                        f"Quota reconcile: VM {stale_id} in tracker but not in Proxmox "
                        f"(user='{username}'), removing stale entry"
                    )
                    tracker.untrack_vm(stale_id)
    except Exception as reconcile_err:
        logger.warning(f"Quota reconcile failed, using tracker as-is: {reconcile_err}")

    user_vm_count = len(tracker.get_user_vms(username))
    if user_vm_count >= cfg.MAX_VMS_PER_USER:
        raise VMQuotaExceeded(user_vm_count, cfg.MAX_VMS_PER_USER)

    total_vm_count = len(tracker.get_all_tracked_vms())
    if total_vm_count >= cfg.MAX_TOTAL_VMS:
        raise SystemCapacityExceeded(total_vm_count, cfg.MAX_TOTAL_VMS)

    if not limiter.is_allowed(f"create_vm:{username}", max_requests=3, window_seconds=3600):
        wait = limiter.retry_after(f"create_vm:{username}", window_seconds=3600)
        raise VMRateLimited(wait)

    resolved_vm_id = vm_id if vm_id is not None else _find_available_vm_id(cfg, do_list_vms)

    logger.info(
        f"provision_vm_for_user: user '{username}' creating VM {resolved_vm_id} "
        f"from template {cfg.VM_TEMPLATE_ID}"
    )
    result = do_create_vm(resolved_vm_id, cfg.VM_TEMPLATE_ID)
    if not result["success"]:
        raise RuntimeError(result["error"])

    tracker.track_vm(resolved_vm_id, owner=username)
    return cast(Dict[str, Any], result["data"])


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

        # Step 1: Check VM status and stop if running.
        # Pool-scoped VMs have VM.Audit via K8SNetLab role; non-pool VMs may get 403 here.
        # If 403, attempt blind destroy (VM.Allocate is granted globally via K8SNetLabCreate).
        try:
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

                max_wait = 60
                wait_interval = 2
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
        except ResourceException as status_err:
            if "403" in str(status_err) or "Permission check failed" in str(status_err):
                # VM not in pool — K8SNetLab role doesn't apply. Log warning and proceed
                # with blind destroy using VM.Allocate (granted globally via K8SNetLabCreate).
                # If VM is still running, destroy will fail; caller should check success flag.
                slog.warning(
                    f"VM {vm_id} status check 403 (not in pool); attempting blind destroy: {status_err}",
                )
                vm_status = "unknown"
            else:
                raise

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


def list_vms() -> Dict[str, Any]:
    """
    List all VMs on the configured Proxmox node.

    Returns:
        dict: {'success': bool, 'data': list or None, 'error': str or None}
    """
    logger.debug(f"Listing VMs on node '{config.PROXMOX_NODE}'")

    try:
        proxmox = connect_proxmox()
        vms = proxmox.nodes(config.PROXMOX_NODE).qemu.get()
        logger.debug(f"Found {len(vms)} VMs")
        return {"success": True, "data": vms, "error": None}

    except (ConnectionError, ResourceException) as e:
        logger.error(f"Failed to list VMs: {e}")
        return {"success": False, "data": None, "error": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error listing VMs: {e}", exc_info=True)
        return {"success": False, "data": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Verifier identity initialization
# ---------------------------------------------------------------------------


class AgentVMCommandExecutor(VMCommandExecutorPort):
    """Runs commands on a VM via Proxmox QEMU guest agent.

    Polls exec-status until the command exits or _poll_iterations is exhausted.
    Only kubectl and python3 -c commands are allowed (defence in depth).
    Use StubVMCommandExecutor in tests to avoid real Proxmox dependency.
    """

    _poll_iterations: int = 60  # one poll per second → 60s max

    # Allowed command prefixes — defence in depth against accidental misuse.
    _ALLOWED_PREFIXES: tuple[list[str], ...] = (
        ["kubectl"],
        ["python3", "-c"],
    )

    def _check_command(self, command: list[str]) -> None:
        if not any(command[: len(p)] == p for p in self._ALLOWED_PREFIXES):
            raise ValueError(
                f"AgentVMCommandExecutor: command not in allowlist: {command[0]!r}"
            )

    def execute(self, vm_id: str, command: list[str]) -> CommandResult:
        from backend.labgen.verifier_credentials import _validate_vm_id
        _validate_vm_id(vm_id)
        self._check_command(command)

        proxmox = connect_proxmox()
        agent = proxmox.nodes(config.PROXMOX_NODE).qemu(int(vm_id)).agent

        r = agent.post("exec", command=command)
        pid = r.get("pid")

        for _ in range(self._poll_iterations):
            time.sleep(1)
            s = agent.get("exec-status", pid=pid)
            if s.get("exited"):
                return CommandResult(
                    exit_code=s.get("exitcode", 0),
                    stdout=s.get("out-data", ""),
                    stderr=s.get("err-data", ""),
                )

        raise TimeoutError(
            f"Agent command timed out after {self._poll_iterations}s on VM {vm_id}"
        )


def initialize_verifier_for_vm(
    vm_id: int,
    *,
    store: Optional[VerifierCredentialStore] = None,
    executor: Optional[VMCommandExecutorPort] = None,
) -> Dict[str, Any]:
    """Initialize verifier identity for a VM after K3s is confirmed ready.

    Steps:
      1. Apply lab-verifier ServiceAccount + ClusterRole via kubectl (idempotent)
      2. Extract kubeconfig and save via VerifierCredentialStore
      3. Run structural smoke test

    VM is considered READY only after all three steps pass.
    kubeconfig content is NEVER logged.

    Args:
        vm_id:    VM ID (100-999999)
        store:    Override VerifierCredentialStore (default: creds/vm_creds/)
        executor: Override command executor (default: AgentVMCommandExecutor)

    Returns:
        {"success": bool, "data": dict | None, "error": str | None}
    """
    _validate_vm_id(vm_id)

    if store is None:
        from backend import config as _cfg
        store = VerifierCredentialStore(_cfg.LABGEN_VERIFIER_CREDENTIAL_ROOT)
    if executor is None:
        executor = AgentVMCommandExecutor()

    manager = VerifierIdentityManager(store=store, executor=executor)
    vm_id_str = str(vm_id)

    slog = SmartLogger(f"init_verifier_{vm_id}")
    try:
        metadata = manager.ensure_verifier_identity(vm_id_str)
        slog.info(
            f"VM {vm_id}: verifier identity ensured "
            f"(generation={metadata.credential_generation})"
        )

        # NEVER log the return value of export_verifier_kubeconfig
        manager.export_verifier_kubeconfig(vm_id_str)
        slog.info(f"VM {vm_id}: verifier kubeconfig exported")

        smoke = manager.run_smoke_test(vm_id_str)
        if not smoke.passed:
            failed = [c.check_name for c in smoke.checks if not c.passed]
            slog.warning(f"VM {vm_id}: verifier smoke test failed: {failed}")
            return {
                "success": False,
                "data": None,
                "error": f"smoke_test_failed: {failed}",
            }

        slog.success(f"VM {vm_id}: verifier initialized and verified")
        return {
            "success": True,
            "data": {"credential_generation": metadata.credential_generation},
            "error": None,
        }

    except Exception as e:
        slog.error(f"VM {vm_id}: verifier initialization failed: {e}", e)
        return {"success": False, "data": None, "error": str(e)}
    finally:
        slog.generate_report()


def initialize_verifier_for_vm_host_side(
    vm_id: int,
    platform_kubeconfig_path: str,
    *,
    store: Optional[VerifierCredentialStore] = None,
    _factory: "Optional[Any]" = None,
) -> Dict[str, Any]:
    """Initialize verifier identity using the platform K3s kubeconfig (host-side).

    For home_lab_mvp/cloud profiles where lab namespaces are created on a shared
    K3s cluster (e.g. VM 401 in home_lab_mvp).  Unlike initialize_verifier_for_vm
    (QEMU agent on student VMs), this function connects to the platform K3s cluster
    directly from the Proxmox host using the Python kubernetes client, ensuring
    verifier credentials point to the same K3s where lab namespaces are created.

    Steps:
      1. Apply lab-verifier ServiceAccount to kube-system (idempotent)
      2. Apply lab-verifier-namespace-readonly ClusterRole (idempotent)
      3. Create service account token via TokenRequest API (8760h)
      4. Build verifier kubeconfig pointing to platform K3s
      5. Save to VerifierCredentialStore under creds/vm_creds/{vm_id}/
      6. Run structural smoke test

    Security: platform_kubeconfig_path content is NEVER logged.

    Args:
        vm_id: Staging VM ID (100-999999; policy requires 400-499 for staging)
        platform_kubeconfig_path: Absolute path to platform kubeconfig (chmod 600, repo-external)
        store: VerifierCredentialStore override (default: config.LABGEN_VERIFIER_CREDENTIAL_ROOT)

    Returns:
        {"success": bool, "data": dict | None, "error": str | None}
    """
    _validate_vm_id(vm_id)

    if store is None:
        store = VerifierCredentialStore(config.LABGEN_VERIFIER_CREDENTIAL_ROOT)

    slog = SmartLogger(f"init_verifier_host_side_{vm_id}")

    try:
        from pathlib import Path
        try:
            kubeconfig_content = Path(platform_kubeconfig_path).read_text()
        except (OSError, IOError) as exc:
            return {"success": False, "data": None, "error": f"kubeconfig read failed: {exc}"}

        from backend.labgen.verifier_credentials import PlatformVerifierInitializer, StubVMCommandExecutor
        initializer = PlatformVerifierInitializer(store=store, factory=_factory)
        vm_id_str = str(vm_id)

        metadata = initializer.ensure_verifier_identity(vm_id_str, kubeconfig_content)
        slog.info(
            f"VM {vm_id}: verifier identity ensured host-side "
            f"(generation={metadata.credential_generation})"
        )

        smoke = VerifierIdentityManager(
            store=store, executor=StubVMCommandExecutor()
        ).run_smoke_test(vm_id_str)
        if not smoke.passed:
            failed = [c.check_name for c in smoke.checks if not c.passed]
            slog.warning(f"VM {vm_id}: verifier smoke test failed: {failed}")
            return {"success": False, "data": None, "error": f"smoke_test_failed: {failed}"}

        slog.info(f"VM {vm_id}: host-side verifier initialized and structural smoke passed")
        slog.generate_report()
        return {
            "success": True,
            "data": {
                "vm_id": vm_id,
                "credential_generation": metadata.credential_generation,
                "k3s_endpoint": "<redacted>",
                "smoke_passed": True,
            },
            "error": None,
        }

    except Exception as e:
        slog.error(f"VM {vm_id}: host-side verifier initialization failed: {e}", e)
        slog.generate_report()
        return {"success": False, "data": None, "error": str(e)}
