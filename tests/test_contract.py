"""
契约测试：验证所有公开 API 端点的响应字段名、类型、必填项。

防止字段改名/删除/类型变更等"无声的 breaking change"破坏前端。
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AuthManager
from backend.auth_routes import router as auth_router
from backend.api_routes import router as api_router
from backend.docs_routes import router as docs_router
from backend.admin_routes import router as admin_router
from backend.auth_deps import get_current_user


# ============================================================
# Schema 断言工具
# ============================================================

def assert_schema(data: dict, required_fields: dict, context: str = ""):
    """验证 dict 满足 required_fields 中所有字段的类型/断言。"""
    for field, check in required_fields.items():
        assert field in data, f"[{context}] 缺少字段: '{field}'"
        value = data[field]
        if isinstance(check, type):
            assert isinstance(value, check), (
                f"[{context}] 字段 '{field}' 应为 {check.__name__}，"
                f"实际为 {type(value).__name__}（值: {value!r}）"
            )
        elif callable(check):
            assert check(value), (
                f"[{context}] 字段 '{field}' 断言失败，值: {value!r}"
            )


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def auth_client(tmp_path):
    """带临时文件的 auth 路由 TestClient，patches 在整个测试期间保持活跃。"""
    users_file = tmp_path / "users.json"
    sessions_file = tmp_path / "sessions.json"

    with patch("backend.auth.USERS_FILE", users_file), \
         patch("backend.auth.SESSIONS_FILE", sessions_file), \
         patch("backend.auth.DATA_DIR", tmp_path):
        mgr = AuthManager()
        mock_rl = MagicMock()
        mock_rl.is_over_limit.return_value = False
        mock_rl.retry_after.return_value = 30

        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            app = FastAPI()
            app.include_router(auth_router)
            yield TestClient(app, raise_server_exceptions=True), mgr


def _api_client(username="testuser"):
    app = FastAPI()
    app.include_router(api_router)
    app.dependency_overrides[get_current_user] = lambda: username
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def docs_client(tmp_path):
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    (exp_dir / "01-kubernetes-network-basics.md").write_text("# 实验一\n内容", encoding="utf-8")
    app = FastAPI()
    app.include_router(docs_router)
    with patch("backend.docs_routes.EXPERIMENTS_DIR", exp_dir):
        yield TestClient(app, raise_server_exceptions=True)


ADMIN_TOKEN = "test-admin-xyz"


@pytest.fixture
def admin_client():
    app = FastAPI()
    app.include_router(admin_router)
    return TestClient(app, raise_server_exceptions=True)


# ============================================================
# 1. Auth 端点契约
# ============================================================

class TestAuthContract:
    AUTH_RESPONSE_SCHEMA = {
        "success": bool,
        "message": str,
    }

    def test_register_response_schema(self, auth_client):
        client, _ = auth_client
        resp = client.post("/api/auth/register",
                           json={"username": "alice", "password": "secret1", "email": "alice@example.com"})
        assert resp.status_code == 201
        data = resp.json()
        assert_schema(data, self.AUTH_RESPONSE_SCHEMA, "register")
        assert_schema(data, {"username": str}, "register")
        assert data["success"] is True

    def test_login_response_schema(self, auth_client):
        """login 必须返回 success/message/username，且设置 Set-Cookie。
        is_admin 在 login 响应中为 None（前端通过 /me 获取）。"""
        client, mgr = auth_client
        mgr.register_user("alice", "secret1")
        resp = client.post("/api/auth/login",
                           json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 200
        data = resp.json()
        assert_schema(data, self.AUTH_RESPONSE_SCHEMA, "login")
        assert_schema(data, {"username": str}, "login")
        assert data["success"] is True
        assert "set-cookie" in resp.headers

    def test_logout_response_schema(self, auth_client):
        client, mgr = auth_client
        mgr.register_user("alice", "secret1")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert_schema(resp.json(), self.AUTH_RESPONSE_SCHEMA, "logout")

    def test_me_response_schema(self, auth_client):
        """me 必须返回 success/message/username/is_admin。"""
        client, mgr = auth_client
        mgr.register_user("alice", "secret1")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert_schema(data, self.AUTH_RESPONSE_SCHEMA, "me")
        assert_schema(data, {"username": str, "is_admin": bool}, "me")

    def test_change_password_response_schema(self, auth_client):
        client, mgr = auth_client
        mgr.register_user("alice", "secret1")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.post("/api/auth/change-password",
                           json={"old_password": "secret1", "new_password": "newsecret"})
        assert resp.status_code == 200
        assert_schema(resp.json(), self.AUTH_RESPONSE_SCHEMA, "change-password")

    def test_error_response_has_detail(self, auth_client):
        """所有错误响应必须包含 detail 字段（FastAPI 标准）。"""
        client, _ = auth_client
        resp = client.post("/api/auth/login",
                           json={"username": "nobody", "password": "wrong"})
        assert resp.status_code == 401
        assert "detail" in resp.json(), "错误响应必须包含 detail 字段"


# ============================================================
# 2. VM API 端点契约
# ============================================================

class TestVMContract:
    VM_RESPONSE_SCHEMA = {
        "success": bool,
    }

    def _mock_create(self, vm_id=500):
        """返回创建成功的 mock patch 组合。"""
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []
        mock_rl = MagicMock()
        mock_rl.is_allowed.return_value = True
        return mock_tracker, mock_rl

    def test_create_vm_response_schema(self):
        client = _api_client()
        mock_tracker, mock_rl = self._mock_create()
        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms",
                   return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm",
                   return_value={"success": True, "data": {
                       "vm_id": 500, "name": "k8s-lab-500",
                       "cores": 4, "memory_mb": 8192,
                   }}), \
             patch("backend.api_routes.rate_limiter", mock_rl):
            resp = client.post("/api/vms/create", json={"template_id": 100})
        assert resp.status_code == 201
        data = resp.json()
        assert_schema(data, self.VM_RESPONSE_SCHEMA, "create_vm")
        assert data["success"] is True
        assert "data" in data

    def test_delete_vm_response_schema(self):
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True
        mock_repo = MagicMock()
        mock_repo.has_active_session_for_vm.return_value = False
        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes._get_lab_session_repo", return_value=mock_repo), \
             patch("backend.api_routes.delete_vm",
                   return_value={"success": True, "data": {}}):
            resp = client.delete("/api/vms/500")
        assert resp.status_code == 200
        assert_schema(resp.json(), self.VM_RESPONSE_SCHEMA, "delete_vm")

    def test_list_vms_response_schema(self):
        """list vms 必须返回 success=True 且 data 为 list。"""
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = [500]
        mock_tracker.get_all_tracked_vms.return_value = [500]
        mock_vms = [{"vmid": 500, "name": "k8s-lab-500", "status": "running"}]
        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms",
                   return_value={"success": True, "data": mock_vms}):
            resp = client.get("/api/vms")
        assert resp.status_code == 200
        data = resp.json()
        assert_schema(data, self.VM_RESPONSE_SCHEMA, "list_vms")
        assert isinstance(data["data"], list), "data 字段必须为 list"

    def test_vm_status_response_schema(self):
        client = _api_client()
        with patch("backend.api_routes.connect_proxmox") as mock_pve, \
             patch("backend.api_routes.vm_tracker") as mock_tracker:
            mock_tracker.get_vm_owner.return_value = "testuser"
            mock_pve.return_value.nodes.return_value.__getitem__ \
                .return_value.qemu.return_value.__getitem__ \
                .return_value.status.current.get.return_value = {
                    "status": "running", "vmid": 500,
                }
            resp = client.get("/api/vms/500/status")
        assert resp.status_code == 200
        data = resp.json()
        assert_schema(data, self.VM_RESPONSE_SCHEMA, "vm_status")

    def test_health_response_schema(self):
        """/health 必须包含 status 字段，值为字符串。"""
        client = _api_client()
        with patch("backend.api_routes.connect_proxmox") as mock_pve:
            mock_pve.return_value.version.get.return_value = {"version": "7.4"}
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert_schema(data, {"status": str}, "health")
        assert data["status"] in ("healthy", "unhealthy")

    def test_quota_response_schema(self):
        """quota 必须有 user 和 system 两个嵌套对象，各含 current/max/available。"""
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []
        with patch("backend.api_routes.vm_tracker", mock_tracker):
            resp = client.get("/api/quota")
        assert resp.status_code == 200
        data = resp.json()

        QUOTA_BLOCK = {
            "current": int,
            "max": int,
            "available": int,
        }
        assert "user" in data and "system" in data, "quota 必须包含 user 和 system"
        assert_schema(data["user"], QUOTA_BLOCK, "quota.user")
        assert_schema(data["system"], QUOTA_BLOCK, "quota.system")

    def test_vm_error_response_has_detail(self):
        """4xx/5xx 错误响应必须包含 detail 字段。"""
        client = _api_client()
        resp = client.delete("/api/vms/not-a-number")
        assert resp.status_code == 422
        assert "detail" in resp.json()


# ============================================================
# 3. Experiments 端点契约
# ============================================================

class TestExperimentsContract:
    def test_list_experiments_response_schema(self, docs_client):
        """列表必须包含 experiments 数组，每项有必填字段。"""
        resp = docs_client.get("/api/experiments")
        assert resp.status_code == 200
        data = resp.json()
        assert "experiments" in data
        assert isinstance(data["experiments"], list)
        assert len(data["experiments"]) > 0

        EXP_SCHEMA = {
            "id": str,
            "title": str,
            "difficulty": int,
            "duration": str,
            "phase": int,
        }
        for exp in data["experiments"]:
            assert_schema(exp, EXP_SCHEMA, "experiments[*]")

    def test_get_experiment_response_schema(self, docs_client):
        """/experiments/{id} 必须返回 id/title/difficulty/duration/content。"""
        resp = docs_client.get("/api/experiments/01")
        assert resp.status_code == 200
        data = resp.json()
        assert_schema(data, {
            "id": str,
            "title": str,
            "difficulty": int,
            "duration": str,
            "content": str,
        }, "get_experiment")
        assert len(data["content"]) > 0, "content 不能为空"

    def test_experiment_not_found_has_detail(self, docs_client):
        resp = docs_client.get("/api/experiments/99")
        assert resp.status_code == 404
        assert "detail" in resp.json()


# ============================================================
# 4. Admin 端点契约
# ============================================================

class TestAdminContract:
    def test_admin_status_response_schema(self, admin_client):
        """admin/status 必须包含 stats（三个计数）+ sessions 数组。"""
        with patch("backend.config.ADMIN_TOKEN", ADMIN_TOKEN), \
             patch("backend.admin_routes.auth_manager.get_active_sessions",
                   return_value=[{
                       "username": "alice",
                       "login_ip": "1.2.3.4",
                       "created_at": "2026-03-17T10:00:00",
                       "expires_at": "2026-03-18T10:00:00",
                   }]), \
             patch("backend.admin_routes.auth_manager.get_users_summary",
                   return_value={"alice": {"created_at": "2026-01-01T00:00:00"}}), \
             patch("backend.admin_routes.vm_tracker.get_all_vms_with_details",
                   return_value=[]):
            resp = admin_client.get("/api/admin/status",
                                    headers={"X-Admin-Token": ADMIN_TOKEN})

        assert resp.status_code == 200
        data = resp.json()

        assert_schema(data, {
            "stats": dict,
            "sessions": list,
        }, "admin_status")
        assert_schema(data["stats"], {
            "total_users": int,
            "active_sessions": int,
            "total_tracked_vms": int,
        }, "admin_status.stats")

    def test_admin_session_detail_schema(self, admin_client):
        """sessions 数组中每个元素必须包含所有声明字段。"""
        mock_session = {
            "username": "alice",
            "login_ip": "10.0.0.1",
            "created_at": "2026-03-17T10:00:00",
            "expires_at": "2026-03-18T10:00:00",
            "current_experiment": "03",
            "last_activity": "2026-03-17T10:30:00",
        }
        with patch("backend.config.ADMIN_TOKEN", ADMIN_TOKEN), \
             patch("backend.admin_routes.auth_manager.get_active_sessions",
                   return_value=[mock_session]), \
             patch("backend.admin_routes.auth_manager.get_users_summary",
                   return_value={"alice": {"created_at": "2026-01-01T00:00:00"}}), \
             patch("backend.admin_routes.vm_tracker.get_all_vms_with_details",
                   return_value=[]):
            resp = admin_client.get("/api/admin/status",
                                    headers={"X-Admin-Token": ADMIN_TOKEN})

        assert resp.status_code == 200
        session = resp.json()["sessions"][0]
        SESSION_SCHEMA = {
            "username": str,
            "is_admin": bool,
            "login_time": str,
            "expires_at": str,
            "vms": list,
        }
        assert_schema(session, SESSION_SCHEMA, "session_detail")
        # nullable 字段必须存在（即使值为 None）
        for nullable in ("login_ip", "login_location", "registered_at",
                         "current_experiment", "last_activity"):
            assert nullable in session, f"session 缺少可空字段: '{nullable}'"

    def test_admin_reset_password_response_schema(self, admin_client):
        with patch("backend.config.ADMIN_TOKEN", ADMIN_TOKEN), \
             patch("backend.admin_routes.auth_manager.reset_password", return_value=True):
            resp = admin_client.post(
                "/api/admin/reset-password",
                json={"username": "alice", "new_password": "newpass1"},
                headers={"X-Admin-Token": ADMIN_TOKEN},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert data["success"] is True

    def test_admin_error_response_has_detail(self, admin_client):
        with patch("backend.config.ADMIN_TOKEN", ADMIN_TOKEN):
            resp = admin_client.get("/api/admin/status",
                                    headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 403
        assert "detail" in resp.json()
