"""
Tests for backend/vm_manager.py

All Proxmox calls are mocked. Tests cover:
- Input validation (VM ID range)
- create_vm: clone -> configure -> start flow
- delete_vm: status check -> stop -> delete flow
- list_vms: listing and error handling
"""

import pytest
from unittest.mock import patch, MagicMock, call


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    """Patch config values for all tests."""
    from backend import config
    monkeypatch.setattr(config, "PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setattr(config, "PROXMOX_PORT", 8006)
    monkeypatch.setattr(config, "PROXMOX_USER", "root@pam")
    monkeypatch.setattr(config, "PROXMOX_PASSWORD", "testpass")
    monkeypatch.setattr(config, "PROXMOX_VERIFY_SSL", False)
    monkeypatch.setattr(config, "PROXMOX_NODE", "pve")
    monkeypatch.setattr(config, "VM_CORES", 4)
    monkeypatch.setattr(config, "VM_MEMORY_MB", 8192)


@pytest.fixture
def mock_proxmox():
    """Provide a mocked Proxmox connection."""
    with patch("backend.vm_manager.connect_proxmox") as mock_connect:
        mock_pve = MagicMock()
        mock_connect.return_value = mock_pve
        yield mock_pve


@pytest.fixture(autouse=True)
def _suppress_reports(monkeypatch):
    """Suppress SmartLogger report file creation during tests."""
    from backend.smart_logger import SmartLogger
    monkeypatch.setattr(SmartLogger, "generate_report", lambda self: "test_report.txt")


# --- Validation Tests ---

class TestValidateVmId:
    """Tests for _validate_vm_id()"""

    def test_valid_id(self):
        """Accepts valid VM IDs."""
        from backend.vm_manager import _validate_vm_id
        _validate_vm_id(100)
        _validate_vm_id(500)
        _validate_vm_id(999999)

    def test_id_too_low(self):
        """Rejects VM ID below 100."""
        from backend.vm_manager import _validate_vm_id
        with pytest.raises(ValueError, match="Invalid VM ID: 99"):
            _validate_vm_id(99)

    def test_id_too_high(self):
        """Rejects VM ID above 999999."""
        from backend.vm_manager import _validate_vm_id
        with pytest.raises(ValueError, match="Invalid VM ID: 1000000"):
            _validate_vm_id(1000000)

    def test_non_integer(self):
        """Rejects non-integer VM ID."""
        from backend.vm_manager import _validate_vm_id
        with pytest.raises(ValueError, match="must be an integer"):
            _validate_vm_id("abc")


# --- create_vm Tests ---

class TestCreateVm:
    """Tests for create_vm()"""

    def test_create_vm_uses_config_pool_name(self, mock_proxmox, monkeypatch):
        """Regression: create_vm must call proxmox.pools(config.PROXMOX_POOL), not
        the hardcoded string 'k8s-netlab'. Changing PROXMOX_POOL env var must take effect."""
        from backend import config
        monkeypatch.setattr(config, "PROXMOX_POOL", "custom-pool-name")

        node = mock_proxmox.nodes("pve")
        node.qemu(9000).clone.post.return_value = "UPID:clone:task"
        node.tasks("UPID:clone:task").status.get.return_value = {
            "status": "stopped", "exitstatus": "OK"
        }

        from backend.vm_manager import create_vm
        result = create_vm(vm_id=200, template_id=9000)

        assert result["success"] is True
        # Verify pool call used the config value, not a hardcoded string
        pool_calls = [str(c) for c in mock_proxmox.pools.call_args_list]
        assert any("custom-pool-name" in c for c in pool_calls), (
            f"proxmox.pools was not called with 'custom-pool-name'. "
            f"Calls: {pool_calls}. vm_manager must use config.PROXMOX_POOL."
        )
        assert not any("k8s-netlab" in c for c in pool_calls), (
            "proxmox.pools was called with hardcoded 'k8s-netlab' instead of config.PROXMOX_POOL."
        )

    def test_successful_creation(self, mock_proxmox):
        """Full flow: clone -> pool -> configure -> start -> success."""
        node = mock_proxmox.nodes("pve")
        node.qemu(9000).clone.post.return_value = "UPID:clone:task"
        # Task polling must return 'stopped'/'OK' immediately or loop hangs
        node.tasks("UPID:clone:task").status.get.return_value = {
            "status": "stopped", "exitstatus": "OK"
        }

        from backend.vm_manager import create_vm
        result = create_vm(vm_id=200, template_id=9000)

        assert result["success"] is True
        assert result["data"]["vm_id"] == 200
        assert result["data"]["name"] == "k8s-lab-200"
        # _patch_config (autouse) sets VM_CORES=4, VM_MEMORY_MB=8192 for this test
        assert result["data"]["cores"] == 4
        assert result["data"]["memory_mb"] == 8192
        assert result["error"] is None

        # Verify clone was called
        node.qemu(9000).clone.post.assert_called_once_with(
            newid=200, name="k8s-lab-200", full=0,
        )
        # Verify config was called
        node.qemu(200).config.put.assert_called_once_with(
            cores=4, memory=8192,
        )
        # Verify start was called
        node.qemu(200).status.start.post.assert_called_once()

    def test_invalid_vm_id_raises(self):
        """Raises ValueError for invalid VM ID."""
        from backend.vm_manager import create_vm
        with pytest.raises(ValueError, match="Invalid VM ID"):
            create_vm(vm_id=50, template_id=9000)

    def test_invalid_template_id_raises(self):
        """Raises ValueError for invalid template ID."""
        from backend.vm_manager import create_vm
        with pytest.raises(ValueError, match="Invalid VM ID"):
            create_vm(vm_id=200, template_id=10)

    def test_connection_error(self, mock_proxmox):
        """Returns failure dict on connection error."""
        with patch("backend.vm_manager.connect_proxmox") as mock_conn:
            mock_conn.side_effect = ConnectionError("unreachable")

            from backend.vm_manager import create_vm
            result = create_vm(vm_id=200, template_id=9000)

            assert result["success"] is False
            assert "unreachable" in result["error"]

    def test_clone_failure(self, mock_proxmox):
        """Returns failure dict when clone fails."""
        from proxmoxer.core import ResourceException
        node = mock_proxmox.nodes("pve")
        node.qemu(9000).clone.post.side_effect = ResourceException(500, "Error", "Clone failed")

        from backend.vm_manager import create_vm
        result = create_vm(vm_id=200, template_id=9000)

        assert result["success"] is False
        assert result["data"] is None
        assert result["error"] is not None


class TestCreateVmRollback:
    """
    回归测试：create_vm 在 clone 成功后的步骤（pool/config/start）失败时，
    必须自动清理孤儿 VM，防止 Proxmox 中出现未被跟踪的残留 VM。
    """

    def _setup_successful_clone(self, mock_proxmox):
        """配置 mock 使 clone 步骤成功完成。"""
        node = mock_proxmox.nodes("pve")
        node.qemu(9000).clone.post.return_value = "UPID:clone:task"
        node.tasks("UPID:clone:task").status.get.return_value = {
            "status": "stopped", "exitstatus": "OK"
        }
        return node

    def test_orphan_vm_deleted_when_pool_add_fails(self, mock_proxmox):
        """
        clone 成功后 pool add 失败 → 必须删除孤儿 VM。
        根因：Step 2 失败时 VM 已在 Proxmox 创建，但不在 vm_tracker，
        必须通过 rollback 删除，否则 VM 永远占用 VMID。
        """
        node = self._setup_successful_clone(mock_proxmox)
        mock_proxmox.pools.return_value.put.side_effect = RuntimeError("pool ACL error")

        from backend.vm_manager import create_vm
        result = create_vm(vm_id=200, template_id=9000)

        assert result["success"] is False
        node.qemu(200).delete.assert_called_once()

    def test_orphan_vm_deleted_when_config_fails(self, mock_proxmox):
        """clone + pool add 成功后 config 失败 → 必须删除孤儿 VM。"""
        node = self._setup_successful_clone(mock_proxmox)
        node.qemu(200).config.put.side_effect = RuntimeError("config error")

        from backend.vm_manager import create_vm
        result = create_vm(vm_id=200, template_id=9000)

        assert result["success"] is False
        node.qemu(200).delete.assert_called_once()

    def test_orphan_vm_deleted_when_start_fails(self, mock_proxmox):
        """clone + pool + config 成功后 start 失败 → 必须删除孤儿 VM。"""
        node = self._setup_successful_clone(mock_proxmox)
        node.qemu(200).status.start.post.side_effect = RuntimeError("start error")

        from backend.vm_manager import create_vm
        result = create_vm(vm_id=200, template_id=9000)

        assert result["success"] is False
        node.qemu(200).delete.assert_called_once()

    def test_no_cleanup_when_clone_fails(self, mock_proxmox):
        """clone 本身失败 → VM 从未创建，不得调用 delete。"""
        node = mock_proxmox.nodes("pve")
        node.qemu(9000).clone.post.side_effect = RuntimeError("clone error")

        from backend.vm_manager import create_vm
        result = create_vm(vm_id=200, template_id=9000)

        assert result["success"] is False
        node.qemu(200).delete.assert_not_called()

    def test_cleanup_failure_does_not_mask_original_error(self, mock_proxmox):
        """
        如果 rollback 删除也失败，返回的 error 必须是原始错误，
        不能被 cleanup 的异常覆盖。
        """
        node = self._setup_successful_clone(mock_proxmox)
        mock_proxmox.pools.return_value.put.side_effect = RuntimeError("pool error")
        node.qemu(200).delete.side_effect = RuntimeError("delete also failed")

        from backend.vm_manager import create_vm
        result = create_vm(vm_id=200, template_id=9000)

        assert result["success"] is False
        assert "pool error" in result["error"]


# --- delete_vm Tests ---

class TestDeleteVm:
    """Tests for delete_vm()"""

    def test_delete_running_vm_force(self, mock_proxmox):
        """Force-stops running VM then deletes."""
        node = mock_proxmox.nodes("pve")
        vm = node.qemu(200)
        # First call: running (initial check); second call: stopped (wait loop)
        vm.status.current.get.side_effect = [
            {"status": "running"}, {"status": "stopped"}
        ]

        from backend.vm_manager import delete_vm
        result = delete_vm(vm_id=200, force=True)

        assert result["success"] is True
        assert result["data"]["vm_id"] == 200
        assert result["data"]["previous_status"] == "running"
        vm.status.stop.post.assert_called_once()
        vm.delete.assert_called_once()

    def test_delete_running_vm_graceful(self, mock_proxmox):
        """Gracefully shuts down running VM then deletes."""
        node = mock_proxmox.nodes("pve")
        vm = node.qemu(300)
        vm.status.current.get.side_effect = [
            {"status": "running"}, {"status": "stopped"}
        ]

        from backend.vm_manager import delete_vm
        result = delete_vm(vm_id=300, force=False)

        assert result["success"] is True
        vm.status.shutdown.post.assert_called_once()
        vm.delete.assert_called_once()

    def test_delete_stopped_vm(self, mock_proxmox):
        """Deletes already-stopped VM without stop call."""
        node = mock_proxmox.nodes("pve")
        vm = node.qemu(400)
        vm.status.current.get.return_value = {"status": "stopped"}

        from backend.vm_manager import delete_vm
        result = delete_vm(vm_id=400)

        assert result["success"] is True
        vm.status.stop.post.assert_not_called()
        vm.status.shutdown.post.assert_not_called()
        vm.delete.assert_called_once()

    def test_invalid_vm_id_raises(self):
        """Raises ValueError for invalid VM ID."""
        from backend.vm_manager import delete_vm
        with pytest.raises(ValueError, match="Invalid VM ID"):
            delete_vm(vm_id=-1)

    def test_connection_error(self):
        """Returns failure dict on connection error."""
        with patch("backend.vm_manager.connect_proxmox") as mock_conn:
            mock_conn.side_effect = ConnectionError("down")

            from backend.vm_manager import delete_vm
            result = delete_vm(vm_id=200)

            assert result["success"] is False
            assert "down" in result["error"]

    def test_delete_vm_not_in_pool_403_status_blind_destroy_succeeds(self, mock_proxmox):
        """
        Regression: VM not in Proxmox pool gets 403 on status check.
        delete_vm must fall through to blind destroy using VM.Allocate (global perm).
        sfl-test-02 postmortem: VM 500 was not in k8s-netlab pool, destroy got 403 on
        status check, causing silent untrack instead of actual deletion.
        """
        from proxmoxer.core import ResourceException
        from backend.vm_manager import delete_vm

        node = mock_proxmox.nodes("pve")
        vm = node.qemu(500)
        vm.status.current.get.side_effect = ResourceException(
            403,
            "Forbidden",
            "Permission check failed (user k8s-netlab@pve!netlab-token, path /vms/500, perm VM.Audit)",
        )
        vm.delete.return_value = None

        result = delete_vm(vm_id=500, force=True)

        assert result["success"] is True, f"blind destroy should succeed: {result['error']}"
        vm.status.stop.post.assert_not_called()
        vm.delete.assert_called_once()

    def test_delete_vm_non_permission_resource_exception_propagates(self, mock_proxmox):
        """Non-403 ResourceException (e.g. 500 internal error) must propagate, not be swallowed."""
        from proxmoxer.core import ResourceException
        from backend.vm_manager import delete_vm

        node = mock_proxmox.nodes("pve")
        vm = node.qemu(501)
        vm.status.current.get.side_effect = ResourceException(500, "Internal Server Error", "Internal server error")

        result = delete_vm(vm_id=501)

        assert result["success"] is False
        assert "500" in result["error"] or "Internal" in result["error"]


# --- list_vms Tests ---

class TestListVms:
    """Tests for list_vms()"""

    def test_success(self, mock_proxmox):
        """Returns list of VMs on success."""
        mock_proxmox.nodes("pve").qemu.get.return_value = [
            {"vmid": 100, "name": "template", "status": "stopped"},
            {"vmid": 200, "name": "k8s-lab-200", "status": "running"},
        ]

        from backend.vm_manager import list_vms
        result = list_vms()

        assert result["success"] is True
        assert len(result["data"]) == 2
        assert result["error"] is None

    def test_empty_list(self, mock_proxmox):
        """Returns empty list when no VMs exist."""
        mock_proxmox.nodes("pve").qemu.get.return_value = []

        from backend.vm_manager import list_vms
        result = list_vms()

        assert result["success"] is True
        assert result["data"] == []

    def test_connection_error(self):
        """Returns failure dict on connection error."""
        with patch("backend.vm_manager.connect_proxmox") as mock_conn:
            mock_conn.side_effect = ConnectionError("timeout")

            from backend.vm_manager import list_vms
            result = list_vms()

            assert result["success"] is False
            assert "timeout" in result["error"]


# --- provision_vm_for_user Tests ---
# Shared core used by both POST /api/vms/create and LabGen's background
# auto-provisioning (backend/labgen/vm_provisioning.py). These tests pin down
# the exact quota/rate-limit/creation pipeline so the api_routes.py extraction
# is provably behavior-preserving.

class TestProvisionVmForUser:
    """Tests for provision_vm_for_user()"""

    @pytest.fixture(autouse=True)
    def _reset_state(self, monkeypatch):
        from backend import config
        monkeypatch.setattr(config, "MAX_VMS_PER_USER", 1)
        monkeypatch.setattr(config, "MAX_TOTAL_VMS", 12)
        monkeypatch.setattr(config, "VM_ID_MIN", 500)
        monkeypatch.setattr(config, "VM_ID_MAX", 599)
        monkeypatch.setattr(config, "VM_TEMPLATE_ID", 101)

    def test_success_assigns_id_creates_and_tracks(self, monkeypatch):
        from backend import vm_manager

        monkeypatch.setattr(vm_manager, "list_vms", lambda: {"success": True, "data": []})
        monkeypatch.setattr(
            vm_manager.vm_tracker, "get_user_vms", lambda u: []
        )
        monkeypatch.setattr(
            vm_manager.vm_tracker, "get_all_tracked_vms", lambda: []
        )
        monkeypatch.setattr(
            vm_manager.rate_limiter, "is_allowed", lambda *a, **k: True
        )
        tracked = {}
        monkeypatch.setattr(
            vm_manager.vm_tracker, "track_vm",
            lambda vid, owner: tracked.update(vm_id=vid, owner=owner),
        )
        monkeypatch.setattr(
            vm_manager, "create_vm",
            lambda vid, tid: {"success": True, "data": {"vm_id": vid, "template_id": tid}, "error": None},
        )

        data = vm_manager.provision_vm_for_user("alice")

        assert data["vm_id"] == 500
        assert tracked == {"vm_id": 500, "owner": "alice"}

    def test_explicit_vm_id_bypasses_auto_assign(self, monkeypatch):
        from backend import vm_manager

        monkeypatch.setattr(vm_manager, "list_vms", lambda: {"success": True, "data": []})
        monkeypatch.setattr(vm_manager.vm_tracker, "get_user_vms", lambda u: [])
        monkeypatch.setattr(vm_manager.vm_tracker, "get_all_tracked_vms", lambda: [])
        monkeypatch.setattr(vm_manager.rate_limiter, "is_allowed", lambda *a, **k: True)
        monkeypatch.setattr(vm_manager.vm_tracker, "track_vm", lambda vid, owner: None)
        calls = []
        monkeypatch.setattr(
            vm_manager, "create_vm",
            lambda vid, tid: (calls.append(vid), {"success": True, "data": {"vm_id": vid}, "error": None})[1],
        )

        vm_manager.provision_vm_for_user("alice", vm_id=555)

        assert calls == [555]

    def test_quota_exceeded_raises_with_counts(self, monkeypatch):
        from backend import vm_manager

        monkeypatch.setattr(vm_manager, "list_vms", lambda: {"success": True, "data": []})
        monkeypatch.setattr(vm_manager.vm_tracker, "get_user_vms", lambda u: [500])

        with pytest.raises(vm_manager.VMQuotaExceeded) as exc:
            vm_manager.provision_vm_for_user("alice")

        assert exc.value.current_count == 1
        assert exc.value.limit == 1

    def test_system_capacity_exceeded_raises_with_counts(self, monkeypatch):
        from backend import vm_manager

        monkeypatch.setattr(vm_manager, "list_vms", lambda: {"success": True, "data": []})
        monkeypatch.setattr(vm_manager.vm_tracker, "get_user_vms", lambda u: [])
        monkeypatch.setattr(
            vm_manager.vm_tracker, "get_all_tracked_vms", lambda: list(range(12))
        )

        with pytest.raises(vm_manager.SystemCapacityExceeded) as exc:
            vm_manager.provision_vm_for_user("alice")

        assert exc.value.current_count == 12
        assert exc.value.limit == 12

    def test_rate_limited_raises_with_retry_after(self, monkeypatch):
        from backend import vm_manager

        monkeypatch.setattr(vm_manager, "list_vms", lambda: {"success": True, "data": []})
        monkeypatch.setattr(vm_manager.vm_tracker, "get_user_vms", lambda u: [])
        monkeypatch.setattr(vm_manager.vm_tracker, "get_all_tracked_vms", lambda: [])
        monkeypatch.setattr(vm_manager.rate_limiter, "is_allowed", lambda *a, **k: False)
        monkeypatch.setattr(vm_manager.rate_limiter, "retry_after", lambda *a, **k: 300)

        with pytest.raises(vm_manager.VMRateLimited) as exc:
            vm_manager.provision_vm_for_user("alice")

        assert exc.value.retry_after == 300

    def test_create_vm_failure_raises_runtime_error_no_track(self, monkeypatch):
        from backend import vm_manager

        monkeypatch.setattr(vm_manager, "list_vms", lambda: {"success": True, "data": []})
        monkeypatch.setattr(vm_manager.vm_tracker, "get_user_vms", lambda u: [])
        monkeypatch.setattr(vm_manager.vm_tracker, "get_all_tracked_vms", lambda: [])
        monkeypatch.setattr(vm_manager.rate_limiter, "is_allowed", lambda *a, **k: True)
        tracked = []
        monkeypatch.setattr(vm_manager.vm_tracker, "track_vm", lambda vid, owner: tracked.append(vid))
        monkeypatch.setattr(
            vm_manager, "create_vm",
            lambda vid, tid: {"success": False, "data": None, "error": "Proxmox error"},
        )

        with pytest.raises(RuntimeError, match="Proxmox error"):
            vm_manager.provision_vm_for_user("alice")

        assert tracked == []  # never tracked on failure — no orphan tracker entry

    def test_reconcile_untracks_stale_vm_before_quota_check(self, monkeypatch):
        """A VM in the tracker but gone from Proxmox must not count toward quota."""
        from backend import vm_manager

        monkeypatch.setattr(
            vm_manager, "list_vms",
            lambda: {"success": True, "data": [{"vmid": 999}]},  # 500 no longer exists
        )
        owned = [500]
        monkeypatch.setattr(vm_manager.vm_tracker, "get_user_vms", lambda u: list(owned))
        untracked = []

        def _untrack(vid):
            untracked.append(vid)
            owned.remove(vid)

        monkeypatch.setattr(vm_manager.vm_tracker, "untrack_vm", _untrack)
        monkeypatch.setattr(vm_manager.vm_tracker, "get_all_tracked_vms", lambda: [])
        monkeypatch.setattr(vm_manager.rate_limiter, "is_allowed", lambda *a, **k: True)
        monkeypatch.setattr(vm_manager.vm_tracker, "track_vm", lambda vid, owner: None)
        monkeypatch.setattr(
            vm_manager, "create_vm",
            lambda vid, tid: {"success": True, "data": {"vm_id": vid}, "error": None},
        )

        # Real VMTracker reflects untrack_vm immediately — the reconcile step must
        # remove the stale entry *before* the quota check reads get_user_vms again,
        # otherwise a legitimately-empty user would be wrongly quota-blocked.
        vm_manager.provision_vm_for_user("alice")

        assert untracked == [500]
