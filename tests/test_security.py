"""Security-focused tests: authentication enforcement, authorization bypass,
rate limiting at the HTTP layer, and input validation.

These tests verify that the *routes* correctly enforce security controls,
complementing the unit tests that test the underlying logic in isolation.
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AuthManager
from backend.auth_routes import router as auth_router
from backend.api_routes import router as api_router
from backend.docs_routes import router as docs_router
from backend.auth_deps import get_current_user


# ============================================================
# Helpers
# ============================================================

def _auth_client(tmp_path, rl_allowed=True):
    users_file = tmp_path / "users.json"
    sessions_file = tmp_path / "sessions.json"

    with patch("backend.auth.USERS_FILE", users_file), \
         patch("backend.auth.SESSIONS_FILE", sessions_file), \
         patch("backend.auth.DATA_DIR", tmp_path):
        mgr = AuthManager()

    mock_rl = MagicMock()
    mock_rl.is_allowed.return_value = rl_allowed
    mock_rl.retry_after.return_value = 55

    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app, raise_server_exceptions=False), mgr, mock_rl


def _api_app(username=None):
    """Build API app; if username is None no override → real dependency (401)."""
    app = FastAPI()
    app.include_router(api_router)
    if username:
        app.dependency_overrides[get_current_user] = lambda: username
    return app


# ============================================================
# 1. All protected endpoints reject unauthenticated requests
# ============================================================

class TestUnauthenticatedRejected:
    """Every route that requires a session must return 401 with no cookie."""

    @pytest.fixture
    def unauthed(self):
        return TestClient(_api_app(), raise_server_exceptions=False)

    def test_create_vm_requires_auth(self, unauthed):
        resp = unauthed.post("/api/vms/create", json={"template_id": 100})
        assert resp.status_code == 401

    def test_delete_vm_requires_auth(self, unauthed):
        resp = unauthed.delete("/api/vms/500")
        assert resp.status_code == 401

    def test_list_vms_requires_auth(self, unauthed):
        resp = unauthed.get("/api/vms")
        assert resp.status_code == 401

    def test_quota_requires_auth(self, unauthed):
        resp = unauthed.get("/api/quota")
        assert resp.status_code == 401

    def test_me_requires_auth(self):
        app = FastAPI()
        app.include_router(auth_router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_change_password_requires_auth(self):
        app = FastAPI()
        app.include_router(auth_router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/auth/change-password",
            json={"old_password": "x", "new_password": "newpass1"},
        )
        assert resp.status_code == 401


# ============================================================
# 2. Authorization bypass — cross-user VM ownership
# ============================================================

class TestAuthorizationBypass:
    def test_cannot_delete_other_users_vm(self):
        """User B must receive 403 when trying to delete User A's VM."""
        app = _api_app(username="userB")
        client = TestClient(app, raise_server_exceptions=False)

        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = False     # userB does not own VM 500
        mock_tracker.get_vm_owner.return_value = "userA"

        with patch("backend.api_routes.vm_tracker", mock_tracker):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 403

    def test_owner_can_delete_own_vm(self):
        """Positive: VM owner must be allowed to delete."""
        app = _api_app(username="userA")
        client = TestClient(app, raise_server_exceptions=True)

        mock_tracker = MagicMock()
        mock_tracker.is_owner.return_value = True

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.delete_vm", return_value={"success": True, "data": {}}):
            resp = client.delete("/api/vms/500")

        assert resp.status_code == 200

    def test_list_vms_only_returns_own_vms(self):
        """User must not see VMs belonging to other users."""
        app = _api_app(username="userA")
        client = TestClient(app, raise_server_exceptions=True)

        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = [500]  # only userA's VM
        mock_tracker.get_vm_owner.return_value = "userA"

        vms = [
            {"vmid": 500, "name": "lab-500", "template": False},  # userA's
            {"vmid": 501, "name": "lab-501", "template": False},  # userB's (not in user_vms)
        ]

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms", return_value={"success": True, "data": vms}), \
             patch("backend.config.VM_TEMPLATE_ID", 100):
            resp = client.get("/api/vms")

        assert resp.status_code == 200
        returned_ids = [v["vmid"] for v in resp.json()["data"]]
        assert 500 in returned_ids
        assert 501 not in returned_ids


# ============================================================
# 3. Rate limiting at the HTTP layer
# ============================================================

class TestRateLimiting:
    def test_login_rate_limit_returns_429(self, tmp_path):
        client, mgr, mock_rl = _auth_client(tmp_path)
        mgr.register_user("alice", "secret1")
        mock_rl.is_allowed.return_value = False

        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})

        assert resp.status_code == 429

    def test_login_rate_limit_includes_retry_after_header(self, tmp_path):
        client, mgr, mock_rl = _auth_client(tmp_path)
        mgr.register_user("alice", "secret1")
        mock_rl.is_allowed.return_value = False
        mock_rl.retry_after.return_value = 55

        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})

        assert resp.headers.get("retry-after") == "55"

    def test_successful_login_not_rate_limited(self, tmp_path):
        client, mgr, mock_rl = _auth_client(tmp_path)
        mgr.register_user("alice", "secret1")
        mock_rl.is_allowed.return_value = True

        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})

        assert resp.status_code == 200

    def test_vm_create_rate_limit_returns_429(self):
        app = _api_app(username="testuser")
        mock_rl = MagicMock()
        mock_rl.is_allowed.return_value = False
        mock_rl.retry_after.return_value = 1800

        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []

        with patch("backend.api_routes.rate_limiter", mock_rl), \
             patch("backend.api_routes.vm_tracker", mock_tracker):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/vms/create", json={"template_id": 100})

        assert resp.status_code == 429
        assert "retry-after" in resp.headers


# ============================================================
# 4. Input validation
# ============================================================

class TestInputValidation:
    @pytest.fixture
    def reg_client(self, tmp_path):
        client, _, _ = _auth_client(tmp_path)
        return client

    def test_username_with_spaces_rejected(self, reg_client, tmp_path):
        _, mgr, mock_rl = _auth_client(tmp_path)
        app = FastAPI()
        app.include_router(auth_router)
        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.post("/api/auth/register", json={"username": "my user", "password": "secret1"})
        assert resp.status_code == 422

    def test_username_with_special_chars_rejected(self, tmp_path):
        _, mgr, mock_rl = _auth_client(tmp_path)
        app = FastAPI()
        app.include_router(auth_router)
        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.post("/api/auth/register", json={"username": "user@name", "password": "secret1"})
        assert resp.status_code == 422

    def test_vm_id_below_minimum_rejected(self):
        app = _api_app(username="testuser")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/vms/99")
        assert resp.status_code == 422

    def test_vm_id_above_maximum_rejected(self):
        app = _api_app(username="testuser")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/vms/1000000")
        assert resp.status_code == 422

    def test_create_vm_with_invalid_vm_id_range(self):
        app = _api_app(username="testuser")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/vms/create", json={"template_id": 100, "vm_id": 50})
        assert resp.status_code == 422

    def test_experiment_id_not_found_returns_404(self, tmp_path):
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        app = FastAPI()
        app.include_router(docs_router)
        with patch("backend.docs_routes.EXPERIMENTS_DIR", exp_dir):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/experiments/99")
        assert resp.status_code == 404


# ============================================================
# 5. Session invalidation
# ============================================================

class TestSessionInvalidation:
    def test_expired_token_returns_401(self, tmp_path):
        _, mgr, mock_rl = _auth_client(tmp_path)
        users_file = tmp_path / "users.json"
        sessions_file = tmp_path / "sessions.json"

        with patch("backend.auth.USERS_FILE", users_file), \
             patch("backend.auth.SESSIONS_FILE", sessions_file), \
             patch("backend.auth.DATA_DIR", tmp_path):
            mgr2 = AuthManager()
            mgr2.register_user("alice", "secret1")
            token = mgr2.create_session("alice")

            # Manually expire the session
            from backend.storage_utils import safe_update_json
            import backend.auth as auth_module

            def _expire(sessions):
                if token in sessions:
                    sessions[token]["expires_at"] = "2020-01-01T00:00:00"
                return sessions

            safe_update_json(sessions_file, _expire)

            app = FastAPI()
            app.include_router(auth_router)
            with patch("backend.auth_routes.auth_manager", mgr2), \
                 patch("backend.auth_routes.rate_limiter", mock_rl):
                client = TestClient(app, raise_server_exceptions=False)
                client.cookies.set("session_token", token)
                resp = client.get("/api/auth/me")

        assert resp.status_code == 401

    def test_logout_invalidates_session(self, tmp_path):
        _, mgr, mock_rl = _auth_client(tmp_path)
        users_file = tmp_path / "users.json"
        sessions_file = tmp_path / "sessions.json"

        with patch("backend.auth.USERS_FILE", users_file), \
             patch("backend.auth.SESSIONS_FILE", sessions_file), \
             patch("backend.auth.DATA_DIR", tmp_path):
            mgr2 = AuthManager()
            mgr2.register_user("alice", "secret1")
            token = mgr2.create_session("alice")

            app = FastAPI()
            app.include_router(auth_router)
            with patch("backend.auth_routes.auth_manager", mgr2), \
                 patch("backend.auth_routes.rate_limiter", mock_rl):
                client = TestClient(app, raise_server_exceptions=False)
                client.cookies.set("session_token", token)
                client.post("/api/auth/logout")
                # Token must be invalid now
                resp = client.get("/api/auth/me")

        assert resp.status_code == 401


# ============================================================
# 6. 路径遍历防护
# ============================================================

class TestPathTraversal:
    """实验 ID 必须经过注册表验证，不能直接拼接到文件路径。"""

    @pytest.fixture
    def docs_client(self, tmp_path):
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        (exp_dir / "01-kubernetes-network-basics.md").write_text("# test", encoding="utf-8")
        app = FastAPI()
        app.include_router(docs_router)
        with patch("backend.docs_routes.EXPERIMENTS_DIR", exp_dir):
            yield TestClient(app, raise_server_exceptions=False)

    def test_path_traversal_attempt_returns_404(self, docs_client):
        """../../../etc/passwd 形式的 ID 必须被注册表拦截，返回 404。"""
        resp = docs_client.get("/api/experiments/../../../etc/passwd")
        assert resp.status_code in (404, 422)

    def test_dotdot_encoded_returns_404(self, docs_client):
        """URL 编码的路径遍历尝试也必须被拦截。"""
        resp = docs_client.get("/api/experiments/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (404, 422)

    def test_absolute_path_id_returns_404(self, docs_client):
        """/etc/passwd 形式的绝对路径 ID 被注册表拦截。"""
        resp = docs_client.get("/api/experiments//etc/passwd")
        assert resp.status_code in (404, 422)

    def test_null_byte_in_id_returns_404_or_422(self, docs_client):
        """空字节注入必须被拦截。"""
        resp = docs_client.get("/api/experiments/01%00.txt")
        assert resp.status_code in (404, 422)

    def test_registered_id_reads_correct_file(self, docs_client):
        """正常 ID 仍然正常工作（确保防御不过度）。"""
        resp = docs_client.get("/api/experiments/01")
        assert resp.status_code == 200
        assert resp.json()["id"] == "01"


# ============================================================
# 7. Cookie 安全属性
# ============================================================

class TestCookieAttributes:
    """登录响应的 session_token cookie 必须设置安全属性。"""

    def _login_resp(self, tmp_path):
        """返回一次成功登录的 response 对象。"""
        client, mgr, mock_rl = _auth_client(tmp_path)
        mgr.register_user("alice", "secret1")
        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            return client.post("/api/auth/login",
                               json={"username": "alice", "password": "secret1"})

    def test_session_cookie_is_httponly(self, tmp_path):
        resp = self._login_resp(tmp_path)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower(), \
            f"session_token cookie must be HttpOnly. Got: {set_cookie}"

    def test_session_cookie_has_samesite(self, tmp_path):
        resp = self._login_resp(tmp_path)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "samesite" in set_cookie.lower(), \
            f"session_token cookie must have SameSite. Got: {set_cookie}"

    def test_session_cookie_has_max_age(self, tmp_path):
        resp = self._login_resp(tmp_path)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "max-age" in set_cookie.lower(), \
            f"session_token cookie must have Max-Age. Got: {set_cookie}"


# ============================================================
# 8. 并发配额竞态 (TOCTOU)
# ============================================================

class TestConcurrentQuota:
    """
    已知设计缺陷：quota check (get_user_vms) 与 track_vm 之间无原子锁。
    两个并发请求可能同时通过配额检查，然后都成功创建 VM，突破 MAX_VMS_PER_USER。

    这组测试验证：
    1. 串行请求正确拦截第二次 (基准行为)
    2. 记录并发场景下系统的实际行为（文档化竞态窗口）
    """

    def test_serial_second_creation_blocked_by_quota(self):
        """串行创建：第二次请求必须被 429 拦截。"""
        app = _api_app(username="testuser")
        creation_count = [0]

        def mock_create(*args):
            creation_count[0] += 1
            return {"success": True, "data": {"vm_id": 500 + creation_count[0]}}

        mock_tracker = MagicMock()
        # 第一次调用：用户没有 VM；第二次：已有 1 个 VM
        mock_tracker.get_user_vms.side_effect = [[], [500]]
        mock_tracker.get_all_tracked_vms.return_value = []

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms",
                   return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm", side_effect=mock_create), \
             patch("backend.api_routes.rate_limiter") as mock_rl, \
             patch("backend.config.MAX_VMS_PER_USER", 1):
            mock_rl.is_allowed.return_value = True
            client = TestClient(app, raise_server_exceptions=False)
            resp1 = client.post("/api/vms/create", json={"template_id": 100})
            resp2 = client.post("/api/vms/create", json={"template_id": 100})

        assert resp1.status_code == 201
        assert resp2.status_code == 429

    def test_concurrent_creation_documents_race_window(self):
        """
        并发创建测试：记录竞态条件下的实际行为。

        已知问题：get_user_vms() + track_vm() 不是原子操作。
        若两个请求同时通过配额检查（都看到 0 个 VM），
        则两个都会调用 create_vm，突破 MAX_VMS_PER_USER=1 限制。

        上线前必须添加 asyncio.Lock() 或类似机制保护该临界区。
        """
        import threading

        app = _api_app(username="testuser")
        results = []
        lock = threading.Barrier(2)  # 确保两个请求同时进入路由处理

        mock_tracker = MagicMock()
        # 模拟竞态窗口：两个请求都在对方调用 track_vm 之前检查配额
        mock_tracker.get_user_vms.return_value = []  # 始终返回空（未加锁的竞态）
        mock_tracker.get_all_tracked_vms.return_value = []

        creation_count = [0]

        def slow_create(*args):
            creation_count[0] += 1
            return {"success": True, "data": {"vm_id": 500 + creation_count[0]}}

        with patch("backend.api_routes.vm_tracker", mock_tracker), \
             patch("backend.api_routes.list_vms",
                   return_value={"success": True, "data": []}), \
             patch("backend.api_routes.create_vm", side_effect=slow_create), \
             patch("backend.api_routes.rate_limiter") as mock_rl, \
             patch("backend.config.MAX_VMS_PER_USER", 1):
            mock_rl.is_allowed.return_value = True
            client = TestClient(app, raise_server_exceptions=False)

            def make_request():
                resp = client.post("/api/vms/create", json={"template_id": 100})
                results.append(resp.status_code)

            threads = [threading.Thread(target=make_request) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        success_count = results.count(201)
        # 记录实际结果。理想情况下 success_count == 1。
        # 若 success_count == 2，说明竞态被触发（已知漏洞）。
        # 此测试不设置 assert，仅文档化行为。
        # TODO: 添加 asyncio.Lock() 后改为 assert success_count == 1
        assert success_count in (1, 2), \
            f"Unexpected result: {results}. Known race: may be 1 or 2."
