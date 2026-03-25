"""HTTP integration tests for /api/vms/* and /api/health, /api/quota routes.

All Proxmox calls are mocked. get_current_user dependency is overridden.
vm_tracker is patched per-test to control ownership and quota state.
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api_routes import router
from backend.auth_deps import get_current_user


# ============================================================
# Fixtures
# ============================================================

def _make_client(username="testuser", rl_allowed=True):
    """Build TestClient with dependency override for current user."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: username

    mock_rl = MagicMock()
    mock_rl.is_allowed.return_value = rl_allowed
    mock_rl.retry_after.return_value = 1800

    return app, mock_rl


@pytest.fixture
def client():
    app, _ = _make_client()
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def client_with_rl():
    """Returns (client, mock_rate_limiter) — lets tests toggle rate limiting."""
    app, mock_rl = _make_client()
    with patch("backend.api_routes.rate_limiter", mock_rl):
        yield TestClient(app, raise_server_exceptions=True), mock_rl


@pytest.fixture
def unauthed_client():
    """Client with no user override — dependency raises 401."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ============================================================
# POST /api/vms/create
# ============================================================

class TestCreateVM:
    def test_success_returns_201(self, client_with_rl):
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm", return_value={"success": True, "data": {"vm_id": 500}}):
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 201
        assert resp.json()["success"] is True
        mock_tracker.track_vm.assert_called_once_with(500, owner="testuser")

    def test_create_vm_always_uses_config_template_id(self, client_with_rl):
        """Regression: create_vm must be called with config.VM_TEMPLATE_ID, never a
        client-supplied value. This test would have caught the api.js hardcoded-100 bug."""
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm", return_value={"success": True, "data": {"vm_id": 500}}) as mock_create, \
             patch("backend.api_routes.config") as mock_config:
            mock_config.VM_TEMPLATE_ID = 999
            mock_config.MAX_VMS_PER_USER = 5
            mock_config.MAX_TOTAL_VMS = 20
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 201
        # The second positional arg to create_vm must be config.VM_TEMPLATE_ID (999), not any hardcoded value
        called_template_id = mock_create.call_args[0][1]
        assert called_template_id == 999, (
            f"create_vm called with template_id={called_template_id}, expected config.VM_TEMPLATE_ID=999. "
            "Frontend or API route must not hardcode template IDs."
        )

    def test_unauthenticated_returns_401(self, unauthed_client):
        resp = unauthed_client.post("/api/vms/create", json={})
        assert resp.status_code == 401

    def test_per_user_quota_exceeded_returns_429(self, client_with_rl):
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = [500]  # already at limit

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.config.MAX_VMS_PER_USER", 1):
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 429

    def test_system_quota_exceeded_returns_503(self, client_with_rl):
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = list(range(12))  # at system limit

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.config.MAX_VMS_PER_USER", 5), \
             patch("backend.config.MAX_TOTAL_VMS", 12):
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 503

    def test_rate_limit_returns_429_with_retry_after(self, client_with_rl):
        client, mock_rl = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []
        mock_rl.is_allowed.return_value = False
        mock_rl.retry_after.return_value = 1800

        with patch("backend.api_routes.vm_tracker", mock_tracker):
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 429
        assert "retry-after" in resp.headers

    def test_proxmox_failure_returns_500(self, client_with_rl):
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm", return_value={"success": False, "error": "Proxmox error"}):
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 500

    def test_vm_id_range_validation(self, client_with_rl):
        client, _ = client_with_rl
        resp = client.post("/api/vms/create", json={"vm_id": 50})
        assert resp.status_code == 422


# ============================================================
# DELETE /api/vms/{vm_id}
# ============================================================

class TestDeleteVM:
    def test_success_returns_200(self, client):
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.delete_vm", return_value={"success": True, "data": {}}):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 200
        mock_tracker.untrack_vm.assert_called_once_with(500)

    def test_unauthenticated_returns_401(self, unauthed_client):
        resp = unauthed_client.delete("/api/vms/500")
        assert resp.status_code == 401

    def test_not_owner_returns_403(self, client):
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = False
        mock_tracker.get_vm_owner.return_value = "otheruser"

        with patch("backend.api_routes.vm_tracker", mock_tracker):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 403
        assert "permission" in resp.json()["detail"].lower()

    def test_proxmox_failure_returns_500(self, client):
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.delete_vm", return_value={"success": False, "error": "fail"}):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 500

    def test_vm_id_below_range_returns_422(self, client):
        resp = client.delete("/api/vms/50")
        assert resp.status_code == 422


# ============================================================
# GET /api/vms
# ============================================================

class TestListVMs:
    def test_returns_only_user_vms(self, client):
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = [500]
        mock_tracker.get_vm_owner.return_value = "testuser"

        all_vms = [
            {"vmid": 500, "name": "k8s-lab-500", "template": False},
            {"vmid": 501, "name": "k8s-lab-501", "template": False},
        ]

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": all_vms}), \
             patch("backend.config.VM_TEMPLATE_ID", 100):
            resp = client.get("/api/vms")

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert len(resp.json()["data"]) == 1
        assert resp.json()["data"][0]["vmid"] == 500

    def test_unauthenticated_returns_401(self, unauthed_client):
        resp = unauthed_client.get("/api/vms")
        assert resp.status_code == 401

    def test_auto_claims_orphaned_vm(self, client):
        """VM with no owner is auto-assigned to current user."""
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_vm_owner.return_value = None  # orphaned

        orphan = {"vmid": 502, "name": "k8s-lab-502", "template": False}

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": [orphan]}), \
             patch("backend.config.VM_TEMPLATE_ID", 100):
            resp = client.get("/api/vms")

        assert resp.status_code == 200
        mock_tracker.track_vm.assert_called_once_with(502, owner="testuser")

    def test_template_vm_not_auto_claimed(self, client):
        """Template VMs must never be auto-claimed."""
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []

        template_vm = {"vmid": 100, "name": "template", "template": False}

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": [template_vm]}), \
             patch("backend.config.VM_TEMPLATE_ID", 100):
            resp = client.get("/api/vms")

        assert resp.status_code == 200
        mock_tracker.track_vm.assert_not_called()

    def test_proxmox_failure_returns_500(self, client):
        with patch("backend.api_routes.list_vms", return_value={"success": False, "error": "timeout"}):
            resp = client.get("/api/vms")
        assert resp.status_code == 500


# ============================================================
# GET /api/vms/{vm_id}/status
# ============================================================

class TestVMStatus:
    def test_success(self, client):
        mock_proxmox = MagicMock()
        mock_proxmox.nodes.return_value.qemu.return_value.status.current.get.return_value = {
            "status": "running", "uptime": 120, "cpu": 0.1, "mem": 1024,
            "maxmem": 8192, "cpus": 4, "name": "k8s-lab-500",
        }

        with patch("backend.api_routes.connect_proxmox", return_value=mock_proxmox):
            resp = client.get("/api/vms/500/status")

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "running"
        assert resp.json()["data"]["vm_id"] == 500

    def test_vm_not_found_returns_404(self, client):
        with patch("backend.api_routes.connect_proxmox", side_effect=Exception("does not exist")):
            resp = client.get("/api/vms/500/status")
        assert resp.status_code == 404


# ============================================================
# GET /api/health
# ============================================================

class TestHealth:
    def test_healthy(self, client):
        mock_proxmox = MagicMock()
        mock_proxmox.version.get.return_value = {"version": "8.1.0"}

        with patch("backend.api_routes.connect_proxmox", return_value=mock_proxmox):
            resp = client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
        assert resp.json()["proxmox"]["connected"] is True

    def test_unhealthy_when_proxmox_unreachable(self, client):
        with patch("backend.api_routes.connect_proxmox", side_effect=Exception("connection refused")):
            resp = client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json()["status"] == "unhealthy"


# ============================================================
# GET /api/quota
# ============================================================

class TestQuota:
    def test_returns_correct_quota(self, client):
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = [500]
        mock_tracker.get_all_tracked_vms.return_value = [500, 501]

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.config.MAX_VMS_PER_USER", 3), \
             patch("backend.config.MAX_TOTAL_VMS", 12):
            resp = client.get("/api/quota")

        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["current"] == 1
        assert data["user"]["max"] == 3
        assert data["user"]["available"] == 2
        assert data["system"]["current"] == 2
        assert data["system"]["max"] == 12

    def test_unauthenticated_returns_401(self, unauthed_client):
        resp = unauthed_client.get("/api/quota")
        assert resp.status_code == 401
