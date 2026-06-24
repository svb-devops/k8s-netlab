"""健壮性测试：畸形请求、边界条件、服务降级、错误传播。

验证系统在异常输入和下游故障下能优雅降级而不崩溃。
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AuthManager
from backend.auth_routes import router as auth_router
from backend.api_routes import router as api_router
from backend.auth_deps import get_current_user


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def auth_client(tmp_path):
    """TestClient for auth routes with patches alive during the test."""
    users_file = tmp_path / "users.json"
    sessions_file = tmp_path / "sessions.json"

    with patch("backend.auth.USERS_FILE", users_file), \
         patch("backend.auth.SESSIONS_FILE", sessions_file), \
         patch("backend.auth.DATA_DIR", tmp_path):
        mgr = AuthManager()
        mock_rl = MagicMock()
        mock_rl.is_allowed.return_value = True
        mock_rl.is_over_limit.return_value = False  # not over limit by default

        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            app = FastAPI()
            app.include_router(auth_router)
            yield TestClient(app, raise_server_exceptions=False), mgr


def _api_client(username="testuser"):
    app = FastAPI()
    app.include_router(api_router)
    app.dependency_overrides[get_current_user] = lambda: username
    return TestClient(app, raise_server_exceptions=False)


# ============================================================
# 1. 畸形 / 不完整的请求体
# ============================================================

class TestMalformedRequests:
    """服务端必须对所有输入错误返回 4xx，而不是 500 崩溃。"""

    def test_register_empty_body_returns_422(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register", json={})
        assert resp.status_code == 422

    def test_register_missing_password_returns_422(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register", json={"username": "alice"})
        assert resp.status_code == 422

    def test_register_missing_username_returns_422(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register", json={"password": "secret1"})
        assert resp.status_code == 422

    def test_login_empty_body_returns_422(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422

    def test_login_null_username_returns_422(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/login", json={"username": None, "password": "secret"})
        assert resp.status_code == 422

    def test_create_vm_non_json_body_returns_422(self):
        client = _api_client()
        resp = client.post(
            "/api/vms/create",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_create_vm_wrong_content_type_returns_422(self):
        client = _api_client()
        resp = client.post(
            "/api/vms/create",
            content=b'{"template_id": 100}',
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 422

    def test_delete_vm_string_id_returns_422(self):
        client = _api_client()
        resp = client.delete("/api/vms/not-a-number")
        assert resp.status_code == 422

    def test_change_password_empty_body_returns_422(self, auth_client):
        client, mgr = auth_client
        mgr.register_user("alice", "old_pass")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.post("/api/auth/change-password", json={})
        assert resp.status_code == 422


# ============================================================
# 2. 边界值：字符串长度极值
# ============================================================

class TestBoundaryValues:
    """Pydantic 字段约束必须在 HTTP 层面生效。"""

    def test_username_exactly_max_length_accepted(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register",
                           json={"username": "a" * 20, "password": "secret1", "email": "maxlen@example.com"})
        assert resp.status_code == 201

    def test_username_one_over_max_length_rejected(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register",
                           json={"username": "a" * 21, "password": "secret1"})
        assert resp.status_code == 422

    def test_password_exactly_min_length_accepted(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register",
                           json={"username": "userabc", "password": "a" * 6, "email": "minpw@example.com"})
        assert resp.status_code == 201

    def test_password_one_under_min_length_rejected(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register",
                           json={"username": "userabc", "password": "a" * 5})
        assert resp.status_code == 422

    def test_password_at_max_length_accepted(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register",
                           json={"username": "usermax", "password": "a" * 72, "email": "maxpw@example.com"})  # bcrypt max
        assert resp.status_code == 201

    def test_password_over_max_length_rejected(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register",
                           json={"username": "usermax", "password": "a" * 73})  # bcrypt max + 1
        assert resp.status_code == 422

    def test_vm_id_exactly_at_minimum_accepted(self):
        """VM ID=100 is the minimum valid value."""
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True
        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.delete_vm", return_value={"success": True, "data": {}}):
            resp = client.delete("/api/vms/100")
        assert resp.status_code == 200

    def test_vm_id_at_maximum_accepted(self):
        """VM ID=999999 is the maximum valid value."""
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True
        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.delete_vm", return_value={"success": True, "data": {}}):
            resp = client.delete("/api/vms/999999")
        assert resp.status_code == 200


# ============================================================
# 3. 服务降级：下游失败时的响应
# ============================================================

class TestServiceDegradation:
    """当 Proxmox 或存储层出错时，API 必须返回明确的 5xx，而不是 500 崩溃。"""

    def test_list_vms_proxmox_failure_returns_500(self):
        client = _api_client()
        with patch("backend.api_routes.list_vms",
                   return_value={"success": False, "error": "connection timeout"}):
            resp = client.get("/api/vms")
        assert resp.status_code == 500
        assert resp.json()  # must return JSON, not empty body

    def test_health_proxmox_down_returns_unhealthy_not_500(self):
        """健康检查端点在 Proxmox 不可达时必须返回 200 + unhealthy，而不是 500。"""
        client = _api_client()
        with patch("backend.api_routes.connect_proxmox",
                   side_effect=Exception("connection refused")):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unhealthy"

    def test_vm_status_proxmox_error_returns_500(self):
        client = _api_client()
        with patch("backend.api_routes.vm_tracker") as mock_tracker, \
             patch("backend.api_routes.connect_proxmox",
                   side_effect=Exception("internal server error")):
            mock_tracker.get_vm_owner.return_value = "testuser"
            resp = client.get("/api/vms/500/status")
        assert resp.status_code == 500

    def test_create_vm_proxmox_failure_does_not_track_vm(self):
        """Proxmox 失败时，VM 绝对不能被 tracker 记录（否则配额被占用）。"""
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms",
                   return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm",
                   return_value={"success": False, "error": "clone failed"}), \
             patch("backend.api_routes.rate_limiter") as mock_rl:
            mock_rl.is_allowed.return_value = True
            resp = client.post("/api/vms/create", json={"template_id": 100})

        assert resp.status_code == 500
        mock_tracker.track_vm.assert_not_called()

    def test_delete_vm_failure_does_not_untrack(self):
        """Proxmox 删除失败时，VM 必须保留在 tracker 中（否则成为孤儿）。"""
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.delete_vm",
                   return_value={"success": False, "error": "VM busy"}):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 500
        mock_tracker.untrack_vm.assert_not_called()

    def test_quota_endpoint_works_when_tracker_empty(self):
        """空系统下配额端点不应崩溃。"""
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []
        with patch("backend.api_routes.vm_tracker", mock_tracker):
            resp = client.get("/api/quota")
        assert resp.status_code == 200
        assert resp.json()["user"]["current"] == 0
        assert resp.json()["system"]["current"] == 0


# ============================================================
# 4. 幂等性与重复操作
# ============================================================

class TestIdempotency:
    def test_double_logout_does_not_crash(self, auth_client):
        """登出两次必须都返回 200，不应崩溃。"""
        client, mgr = auth_client
        mgr.register_user("alice", "secret1")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp1 = client.post("/api/auth/logout")
        resp2 = client.post("/api/auth/logout")
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    def test_register_same_user_twice_second_fails_400(self, auth_client):
        """同用户名注册两次：第一次 201，第二次 400。"""
        client, _ = auth_client
        resp1 = client.post("/api/auth/register",
                            json={"username": "alice", "password": "secret1", "email": "alice@example.com"})
        resp2 = client.post("/api/auth/register",
                            json={"username": "alice", "password": "secret1", "email": "alice2@example.com"})
        assert resp1.status_code == 201
        assert resp2.status_code == 400


class TestErrorInfoLeakage:
    """C 回归：生产模式下 500 响应体不得泄露内部异常信息。"""

    def test_create_vm_500_hides_internal_error(self):
        """APP_DEBUG=False 时，create VM 的 500 响应不应包含原始异常文本（C 回归）"""
        client = _api_client()
        secret_msg = "super_secret_internal_token_xyz"
        with patch("backend.api_routes.create_vm", side_effect=Exception(secret_msg)), \
             patch("backend.config.APP_DEBUG", False):
            resp = client.post("/api/vms/create", json={})
        assert resp.status_code == 500
        assert secret_msg not in resp.text

    def test_delete_vm_500_hides_internal_error(self):
        """APP_DEBUG=False 时，delete VM 的 500 响应不应包含原始异常文本（C 回归）"""
        client = _api_client()
        secret_msg = "super_secret_internal_token_xyz"
        with patch("backend.api_routes.delete_vm", side_effect=Exception(secret_msg)), \
             patch("backend.api_routes.vm_tracker") as mock_tracker, \
             patch("backend.config.APP_DEBUG", False):
            mock_tracker.get_vm_owner.return_value = "testuser"
            resp = client.delete("/api/vms/500")
        assert resp.status_code == 500
        assert secret_msg not in resp.text
