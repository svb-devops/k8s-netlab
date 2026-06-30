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
            mock_config.VM_ID_MIN = 500
            mock_config.VM_ID_MAX = 599
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

        # list_vms must confirm VM 500 exists in Proxmox so reconcile keeps it
        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": [{"vmid": 500, "status": "running"}]}), \
             patch("backend.config.MAX_VMS_PER_USER", 1):
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 429

    def test_stale_tracker_entry_cleared_before_quota_check(self, client_with_rl):
        """孤儿 VM 回归：tracker 中有 VM 500 但 Proxmox 中不存在时，
        配额检查前应自动清除该条目，创建应成功而非返回 429（回归）。"""
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        # Simulate dynamic tracker: untrack_vm actually removes from tracked set
        tracked = [500]
        mock_tracker.get_user_vms.side_effect = lambda _user: list(tracked)
        mock_tracker.untrack_vm.side_effect = lambda vm_id: tracked.remove(vm_id) if vm_id in tracked else None
        mock_tracker.get_all_tracked_vms.return_value = []

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm", return_value={"success": True, "data": {"vm_id": 501}}), \
             patch("backend.config.MAX_VMS_PER_USER", 1):
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 201, (
            f"Expected 201 but got {resp.status_code}: stale tracker entry not reconciled before quota check"
        )
        mock_tracker.untrack_vm.assert_called_with(500)

    def test_system_quota_exceeded_returns_503(self, client_with_rl):
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = list(range(12))  # at system limit

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": []}), \
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

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": []}):
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

    def test_create_vm_proxmox_timeout_returns_504(self, client_with_rl):
        """Proxmox 挂起时 create_vm 应在超时后返回 504（B2 回归）。"""
        import asyncio as _asyncio
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []

        async def _timeout(*args, **kwargs):
            raise _asyncio.TimeoutError()

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": []}), \
             patch("backend.api_routes.asyncio.wait_for", _timeout):
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 504
        assert "timed out" in resp.json()["detail"].lower()

    def test_vm_id_range_validation(self, client_with_rl):
        client, _ = client_with_rl
        resp = client.post("/api/vms/create", json={"vm_id": 50})
        assert resp.status_code == 422

    def test_auto_assignment_respects_config_vm_id_range(self, client_with_rl):
        """Regression: _find_available_vm_id must scan config.VM_ID_MIN..VM_ID_MAX,
        not the hardcoded range(500, 600). Auto-assigned ID must fall within the
        configured range even when the range differs from the default."""
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []

        captured = {}

        def fake_create_vm(vm_id, template_id):
            captured["vm_id"] = vm_id
            return {"success": True, "data": {"vm_id": vm_id}, "error": None}

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm", side_effect=fake_create_vm), \
             patch("backend.api_routes.config") as mock_config:
            mock_config.VM_TEMPLATE_ID = 100
            mock_config.MAX_VMS_PER_USER = 5
            mock_config.MAX_TOTAL_VMS = 20
            mock_config.VM_ID_MIN = 300
            mock_config.VM_ID_MAX = 302
            resp = client.post("/api/vms/create", json={})

        assert resp.status_code == 201
        assert 300 <= captured["vm_id"] <= 302, (
            f"Auto-assigned vm_id={captured['vm_id']} is outside config range [300, 302]. "
            "api_routes._find_available_vm_id must use config.VM_ID_MIN/VM_ID_MAX."
        )

    def test_explicit_vm_id_outside_config_range_returns_422(self, client_with_rl):
        """客户端指定的 vm_id 超出 config.VM_ID_MIN..MAX 范围时应返回 422（J 回归）。
        Pydantic 允许 100-999999，但 config 范围更窄（如 500-599），handler 须额外校验。"""
        client, _ = client_with_rl
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []
        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.rate_limiter") as mock_rl, \
             patch("backend.config.VM_ID_MIN", 500), \
             patch("backend.config.VM_ID_MAX", 599):
            mock_rl.is_allowed.return_value = True
            # vm_id=200 passes Pydantic (≥100) but is outside config range [500,599]
            resp = client.post("/api/vms/create", json={"vm_id": 200})
        assert resp.status_code == 422


# ============================================================
# DELETE /api/vms/{vm_id}
# ============================================================

class TestDeleteVM:
    def test_delete_vm_proxmox_timeout_returns_504(self, client):
        """Proxmox 挂起时 delete_vm 应在超时后返回 504（B2 回归）。"""
        import asyncio as _asyncio
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True
        mock_repo = MagicMock()
        mock_repo.has_active_session_for_vm.return_value = False

        async def _timeout(*args, **kwargs):
            raise _asyncio.TimeoutError()

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes._get_lab_session_repo", return_value=mock_repo), \
             patch("backend.api_routes.asyncio.wait_for", _timeout):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 504
        assert "timed out" in resp.json()["detail"].lower()

    def test_success_returns_200(self, client):
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True
        mock_repo = MagicMock()
        mock_repo.has_active_session_for_vm.return_value = False

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes._get_lab_session_repo", return_value=mock_repo), \
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

    def test_not_owner_403_does_not_reveal_owner_username(self, client):
        """403 response must not disclose the VM owner's username — info disclosure (N 回归)."""
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = False
        mock_tracker.get_vm_owner.return_value = "secretuser"

        with patch("backend.api_routes.vm_tracker", mock_tracker):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 403
        assert "secretuser" not in resp.json()["detail"]

    def test_proxmox_failure_returns_500(self, client):
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True
        mock_repo = MagicMock()
        mock_repo.has_active_session_for_vm.return_value = False

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes._get_lab_session_repo", return_value=mock_repo), \
             patch("backend.api_routes.delete_vm", return_value={"success": False, "error": "fail"}):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 500

    def test_vm_id_below_range_returns_422(self, client):
        resp = client.delete("/api/vms/50")
        assert resp.status_code == 422

    def test_active_labgen_session_blocks_deletion_with_409(self, client):
        """VM 有活跃 LabGen session 时，DELETE 返回 409 而非执行删除。"""
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True

        mock_repo = MagicMock()
        mock_repo.has_active_session_for_vm.return_value = True

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes._get_lab_session_repo", return_value=mock_repo):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 409
        assert "lab session" in resp.json()["detail"].lower()
        mock_repo.has_active_session_for_vm.assert_called_once_with("500")

    def test_closed_labgen_session_does_not_block_deletion(self, client):
        """VM 只有已关闭的 LabGen session（无活跃），DELETE 正常执行。"""
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True

        mock_repo = MagicMock()
        mock_repo.has_active_session_for_vm.return_value = False

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes._get_lab_session_repo", return_value=mock_repo), \
             patch("backend.api_routes.delete_vm", return_value={"success": True, "data": {}}):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 200

    def test_no_labgen_sessions_proceeds_normally(self, client):
        """VM 没有任何 LabGen session 时，DELETE 正常执行。"""
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True

        mock_repo = MagicMock()
        mock_repo.has_active_session_for_vm.return_value = False

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes._get_lab_session_repo", return_value=mock_repo), \
             patch("backend.api_routes.delete_vm", return_value={"success": True, "data": {}}):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 200


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

    def test_auto_claim_respects_per_user_quota(self, client):
        """孤儿 VM 认领不得突破 MAX_VMS_PER_USER 配额（P1 回归）"""
        mock_tracker = MagicMock()
        # 用户已满配额（1/1）
        mock_tracker.get_user_vms.return_value = [501]
        mock_tracker.get_vm_owner.return_value = None  # VM 502 是孤儿

        orphan = {"vmid": 502, "name": "k8s-lab-502", "template": False}

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": [orphan]}), \
             patch("backend.config.VM_TEMPLATE_ID", 100), \
             patch("backend.config.MAX_VMS_PER_USER", 1):
            resp = client.get("/api/vms")

        assert resp.status_code == 200
        # 配额已满时，孤儿 VM 不应被认领
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

        with patch("backend.api_routes.connect_proxmox", return_value=mock_proxmox), \
             patch("backend.api_routes.vm_tracker") as mock_tracker:
            mock_tracker.get_vm_owner.return_value = "testuser"  # client fixture uses testuser
            resp = client.get("/api/vms/500/status")

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "running"
        assert resp.json()["data"]["vm_id"] == 500

    def test_vm_not_found_returns_404(self, client):
        with patch("backend.api_routes.vm_tracker") as mock_tracker, \
             patch("backend.api_routes.connect_proxmox", side_effect=Exception("does not exist")):
            mock_tracker.get_vm_owner.return_value = "testuser"
            resp = client.get("/api/vms/500/status")
        assert resp.status_code == 404

    def test_unauthenticated_returns_401(self, unauthed_client):
        """未登录用户不得查询任意 VM 状态（P0 安全回归）"""
        resp = unauthed_client.get("/api/vms/500/status")
        assert resp.status_code == 401

    def test_non_owner_returns_403(self, client):
        """已登录但非 VM 归属用户不得查询状态（P0 归属校验回归）"""
        with patch("backend.api_routes.vm_tracker") as mock_tracker:
            mock_tracker.get_vm_owner.return_value = "other_user"  # VM 属于其他人
            resp = client.get("/api/vms/500/status")
        assert resp.status_code == 403

    def test_non_owner_status_does_not_disclose_vm_existence(self, client):
        """非 VM 持有者查询状态时，响应不得泄露 VM 归属（A2 回归，防 VM ID 枚举）。"""
        with patch("backend.api_routes.vm_tracker") as mock_tracker:
            mock_tracker.get_vm_owner.return_value = "other_user"
            resp = client.get("/api/vms/500/status")
        assert resp.status_code == 403
        detail = resp.json().get("detail", "")
        assert "own" not in detail.lower(), (
            f"Error detail must not reveal VM ownership, got: {detail!r}"
        )


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

    def test_healthy_response_does_not_expose_fingerprinting_info(self, client):
        """健康端点不得暴露 Proxmox version/host/node 指纹信息（H 回归）。"""
        mock_proxmox = MagicMock()
        mock_proxmox.version.get.return_value = {"version": "8.0.0"}
        with patch("backend.api_routes.connect_proxmox", return_value=mock_proxmox):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        proxmox_data = resp.json().get("proxmox", {})
        assert "version" not in proxmox_data
        assert "host" not in proxmox_data
        assert "node" not in proxmox_data

    def test_unhealthy_error_not_exposed(self, client):
        """health 不健康时不得向匿名调用者暴露原始异常（O 回归）。"""
        with patch("backend.api_routes.connect_proxmox",
                   side_effect=Exception("Connection to 192.168.1.10:8006 refused")):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unhealthy"
        assert "192.168.1.10" not in resp.text
        assert resp.json()["error"] == "Proxmox connection failed"

    def test_head_health_returns_200(self, client):
        """HEAD /api/health 必须返回 200 而非 405 — 修复 UptimeRobot 监控误报（回归）。"""
        resp = client.head("/api/health")
        assert resp.status_code == 200


# ============================================================
# GET /api (info endpoint)
# ============================================================

class TestApiInfo:
    def test_version_not_exposed(self):
        """GET /api 不得暴露版本号，与 health 端点去指纹精神一致（Y 回归）。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.main import api_info

        app2 = FastAPI()
        app2.add_api_route("/api", api_info)
        c = TestClient(app2)
        resp = c.get("/api")
        assert resp.status_code == 200
        assert "version" not in resp.json()


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
