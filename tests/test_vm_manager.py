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
    from smart_logger import SmartLogger
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
            newid=200, name="k8s-lab-200", full=1,
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
