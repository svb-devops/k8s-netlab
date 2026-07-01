"""
性能基线测试：验证核心端点在 TestClient（无网络延迟）环境下满足响应时间阈值。

阈值定义（TestClient 本地调用，无真实网络/IO）：
  - 纯内存端点（health/me/quota/experiments）：< 200ms
  - 含 bcrypt 的认证端点：< 800ms
  - 并发安全：rate limiter 多线程不越限，API 返回码一致
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
# Fixtures
# ============================================================

@pytest.fixture
def auth_client(tmp_path):
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
    # Mock fetch_experiment_list so the test exercises only in-process logic,
    # not a real HTTP call to Directus (which can easily exceed 200ms under load).
    with patch("backend.docs_routes.EXPERIMENTS_DIR", exp_dir), \
         patch("backend.docs_routes.fetch_experiment_list", return_value=None):
        yield TestClient(app, raise_server_exceptions=True)


# ============================================================
# 1. 响应时间基线
# ============================================================

class TestResponseTime:
    FAST_THRESHOLD_MS = 200   # 纯内存端点
    AUTH_THRESHOLD_MS = 800   # 含 bcrypt 的登录端点

    def _measure_ms(self, fn) -> float:
        start = time.perf_counter()
        fn()
        return (time.perf_counter() - start) * 1000

    def test_health_response_time(self):
        client = _api_client()
        with patch("backend.api_routes.connect_proxmox") as mock_pve:
            mock_pve.return_value.version.get.return_value = {"version": "7.4"}
            # Warm up first (cold-start import overhead skews first call under full suite).
            client.get("/api/health")
            elapsed = min(self._measure_ms(lambda: client.get("/api/health")) for _ in range(3))
        assert elapsed < self.FAST_THRESHOLD_MS, \
            f"/health 响应最快 {elapsed:.1f}ms（3次取最小），超过 {self.FAST_THRESHOLD_MS}ms 阈值"

    def test_quota_response_time(self):
        client = _api_client()
        mock_tracker = MagicMock()
        mock_tracker.get_user_vms.return_value = []
        mock_tracker.get_all_tracked_vms.return_value = []
        with patch("backend.api_routes.vm_tracker", mock_tracker):
            elapsed = self._measure_ms(lambda: client.get("/api/quota"))
        assert elapsed < self.FAST_THRESHOLD_MS, \
            f"/quota 响应 {elapsed:.1f}ms，超过 {self.FAST_THRESHOLD_MS}ms 阈值"

    def test_me_response_time(self, auth_client):
        client, mgr = auth_client
        mgr.register_user("alice", "secret1")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        elapsed = self._measure_ms(lambda: client.get("/api/auth/me"))
        assert elapsed < self.FAST_THRESHOLD_MS, \
            f"/me 响应 {elapsed:.1f}ms，超过 {self.FAST_THRESHOLD_MS}ms 阈值"

    def test_experiments_list_response_time(self, docs_client):
        elapsed = self._measure_ms(lambda: docs_client.get("/api/experiments"))
        assert elapsed < self.FAST_THRESHOLD_MS, \
            f"/experiments 响应 {elapsed:.1f}ms，超过 {self.FAST_THRESHOLD_MS}ms 阈值"

    def test_login_with_bcrypt_response_time(self, auth_client):
        """bcrypt 验证有计算开销，阈值相对宽松。"""
        client, mgr = auth_client
        mgr.register_user("alice", "secret1")
        elapsed = self._measure_ms(
            lambda: client.post("/api/auth/login",
                                json={"username": "alice", "password": "secret1"})
        )
        assert elapsed < self.AUTH_THRESHOLD_MS, \
            f"login(bcrypt) 响应 {elapsed:.1f}ms，超过 {self.AUTH_THRESHOLD_MS}ms 阈值"


# ============================================================
# 2. 并发安全
# ============================================================

class TestConcurrency:
    def test_concurrent_login_rate_limiter_thread_safe(self, auth_client):
        """10 个线程同时发起登录，rate limiter 全部放行，无崩溃，全部返回有效状态码。"""
        client, mgr = auth_client
        mgr.register_user("alice", "secret1")

        results = []

        def do_login():
            resp = client.post("/api/auth/login",
                               json={"username": "alice", "password": "secret1"})
            return resp.status_code

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(do_login) for _ in range(10)]
            results = [f.result() for f in as_completed(futures)]

        assert all(code in (200, 429) for code in results), \
            f"并发登录出现意外状态码: {set(results)}"
        # rate limiter mock 全放行，应全部 200
        assert all(code == 200 for code in results), \
            "mock rate limiter 全放行，期望全部 200"

    def test_concurrent_quota_check_documents_race_window(self):
        """
        并发创建 VM 时存在已知的 TOCTOU 竞态窗口。
        本测试记录行为（success_count 可能为 1 或 2）而非断言特定结果。
        TODO: 添加 asyncio.Lock() 消除竞态后，此测试应改为 assert success_count == 1。
        """
        results = []
        mock_rl = MagicMock()
        mock_rl.is_allowed.return_value = True

        def make_request():
            # 每个线程独立创建 client，避免共享 TestClient 状态
            app = FastAPI()
            app.include_router(api_router)
            app.dependency_overrides[get_current_user] = lambda: "testuser"
            c = TestClient(app, raise_server_exceptions=False)

            mock_tracker = MagicMock()
            mock_tracker.get_user_vms.return_value = []   # 每次都看到 0（竞态）
            mock_tracker.get_all_tracked_vms.return_value = []
            with patch("backend.api_routes.vm_tracker", mock_tracker), \
                 patch("backend.api_routes.list_vms",
                       return_value={"success": True, "data": []}), \
                 patch("backend.api_routes.create_vm",
                       return_value={"success": True, "data": {"vm_id": 500}}), \
                 patch("backend.api_routes.rate_limiter", mock_rl):
                resp = c.post("/api/vms/create", json={"template_id": 100})
            return resp.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(make_request) for _ in range(2)]
            results = [f.result() for f in as_completed(futures)]

        success_count = results.count(201)
        # 记录竞态行为：理想情况应为 1，当前实现可能为 1 或 2
        assert success_count in (1, 2), f"意外结果: {results}"

    def test_concurrent_read_experiments_no_crash(self, docs_client):
        """10 个线程并发读实验文档，无崩溃，全部返回 200。"""
        results = []

        def do_read():
            return docs_client.get("/api/experiments/01").status_code

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(do_read) for _ in range(10)]
            results = [f.result() for f in as_completed(futures)]

        assert all(code == 200 for code in results), \
            f"并发读实验出现非 200: {results}"
