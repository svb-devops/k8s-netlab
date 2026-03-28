"""HTTP integration tests for /api/auth/* routes.

Uses FastAPI TestClient with a real AuthManager backed by tmp_path,
so all file I/O is isolated and no real data is touched.
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AuthManager
from backend.auth_routes import router


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def auth_setup(tmp_path):
    """TestClient + AuthManager backed by isolated temp files.

    Rate limiter is allowed by default; individual tests override as needed.
    """
    users_file = tmp_path / "users.json"
    sessions_file = tmp_path / "sessions.json"

    with patch("backend.auth.USERS_FILE", users_file), \
         patch("backend.auth.SESSIONS_FILE", sessions_file), \
         patch("backend.auth.DATA_DIR", tmp_path):
        mgr = AuthManager()

        mock_rl = MagicMock()
        mock_rl.is_over_limit.return_value = False  # not over limit by default
        mock_rl.retry_after.return_value = 30

        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl):
            app = FastAPI()
            app.include_router(router)
            client = TestClient(app, raise_server_exceptions=True)
            yield client, mgr, mock_rl


# ============================================================
# POST /api/auth/register
# ============================================================

class TestRegister:
    def test_success_returns_201(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post("/api/auth/register", json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 201
        assert resp.json()["success"] is True
        assert resp.json()["username"] == "alice"

    def test_duplicate_username_returns_400(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "secret1")
        resp = client.post("/api/auth/register", json={"username": "alice", "password": "secret2"})
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_username_too_short_returns_422(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post("/api/auth/register", json={"username": "ab", "password": "secret1"})
        assert resp.status_code == 422

    def test_username_invalid_chars_returns_422(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post("/api/auth/register", json={"username": "ali ce!", "password": "secret1"})
        assert resp.status_code == 422

    def test_password_too_short_returns_422(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post("/api/auth/register", json={"username": "alice", "password": "abc"})
        assert resp.status_code == 422

    def test_username_too_long_returns_422(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post("/api/auth/register", json={"username": "a" * 21, "password": "secret1"})
        assert resp.status_code == 422

    def test_register_rate_limit_returns_429(self, auth_setup):
        """注册接口超出速率限制时应返回 429（register DoS 防护回归）。"""
        client, _, mock_rl = auth_setup
        mock_rl.is_over_limit.return_value = True
        mock_rl.retry_after.return_value = 60

        resp = client.post("/api/auth/register", json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 429, (
            f"Expected 429 when register rate limit exceeded, got {resp.status_code}"
        )
        assert resp.headers.get("retry-after") == "60"

    def test_register_records_rate_limit_on_success(self, auth_setup):
        """注册成功时应向 rate_limiter 记录本次请求（register DoS 防护回归）。"""
        client, _, mock_rl = auth_setup
        mock_rl.is_over_limit.return_value = False

        client.post("/api/auth/register", json={"username": "alice", "password": "secret1"})
        mock_rl.record.assert_called_once()
        call_key = mock_rl.record.call_args[0][0]
        assert call_key.startswith("register:"), (
            f"Rate limit key should start with 'register:', got '{call_key}'"
        )

    def test_register_records_rate_limit_on_failed_attempt(self, auth_setup):
        """注册失败（用户名已存在）时也必须记录 rate limit，防止无限探测用户名枚举攻击（回归）。"""
        client, mgr, mock_rl = auth_setup
        mock_rl.is_over_limit.return_value = False
        mgr.register_user("alice", "secret1")  # pre-create the user

        resp = client.post("/api/auth/register", json={"username": "alice", "password": "secret2"})
        assert resp.status_code == 400
        assert mock_rl.record.call_count == 1, (
            "rate_limiter.record() must be called even when registration fails — "
            "otherwise unlimited failed attempts bypass rate limiting, enabling username enumeration"
        )


# ============================================================
# POST /api/auth/login
# ============================================================

class TestLogin:
    def test_success_sets_cookie(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "secret1")
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "session_token" in resp.cookies

    def test_cookie_secure_flag_follows_config(self, auth_setup):
        """SESSION_COOKIE_SECURE=True 时 login cookie 必须带 secure 属性（P2 回归）"""
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "secret1")
        with patch("backend.auth_routes.SESSION_COOKIE_SECURE", True):
            resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 200
        set_cookie_header = resp.headers.get("set-cookie", "")
        assert "secure" in set_cookie_header.lower(), (
            "Cookie must carry Secure attribute when SESSION_COOKIE_SECURE=True"
        )

    def test_special_char_username_returns_422(self, auth_setup):
        """登录用户名含特殊字符应返回 422（A 回归，与注册保持一致）"""
        client, _, _ = auth_setup
        resp = client.post("/api/auth/login", json={"username": "alice<script>", "password": "x"})
        assert resp.status_code == 422

    def test_wrong_password_returns_401(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "secret1")
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 401

    def test_unknown_user_returns_401(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post("/api/auth/login", json={"username": "nobody", "password": "secret1"})
        assert resp.status_code == 401

    def test_rate_limit_returns_429_with_retry_after(self, auth_setup):
        client, mgr, mock_rl = auth_setup
        mgr.register_user("alice", "secret1")
        mock_rl.is_over_limit.return_value = True
        mock_rl.retry_after.return_value = 42

        resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 429
        assert resp.headers.get("retry-after") == "42"

    def test_login_cookie_samesite_strict(self, auth_setup):
        """Login cookie 必须使用 SameSite=strict 以防 CSRF（I2 回归）。"""
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "secret1")
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "samesite=strict" in set_cookie.lower(), (
            f"Expected SameSite=strict in cookie, got: {set_cookie}"
        )

    def test_ipv6_mapped_ipv4_normalized(self, auth_setup):
        """::ffff:1.2.3.4 must be stripped to 1.2.3.4 for rate limiting key."""
        client, mgr, mock_rl = auth_setup
        mgr.register_user("alice", "secret1")

        resp = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "secret1"},
            headers={"X-Forwarded-For": "::ffff:192.168.1.1"},
        )
        # rate limiter key must not contain ::ffff: prefix
        call_key = mock_rl.is_over_limit.call_args[0][0]
        assert "::ffff:" not in call_key

    def test_login_evicts_previous_session(self, auth_setup):
        """Regression: 登录时应清除该用户所有旧 session，防止 session 无限堆积。
        Bug: 重复登录不清除旧 token，sessions.json 无限增长。
        Fix: commit 5ad6384"""
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "secret1")

        # 登录两次
        resp1 = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
        token1 = resp1.cookies["session_token"]

        resp2 = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
        token2 = resp2.cookies["session_token"]

        assert token1 != token2, "两次登录应生成不同 token"

        # 旧 token 必须已失效
        assert mgr.verify_session(token1) is None, "旧 session 应在新登录时被清除"
        # 新 token 有效
        assert mgr.verify_session(token2) is not None


# ============================================================
# POST /api/auth/logout
# ============================================================

class TestLogout:
    def test_logout_with_valid_cookie(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "secret1")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_logout_without_cookie_still_succeeds(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ============================================================
# GET /api/auth/me
# ============================================================

class TestMe:
    def test_authenticated_returns_username(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "secret1")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"
        assert "is_admin" in resp.json()

    def test_no_cookie_returns_401(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, auth_setup):
        client, _, _ = auth_setup
        client.cookies.set("session_token", "invalid-token-xyz")
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_admin_user_returns_is_admin_true(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("admin1", "secret1")
        token = mgr.create_session("admin1")
        client.cookies.set("session_token", token)
        with patch("backend.config.ADMIN_USERNAMES", {"admin1"}):
            resp = client.get("/api/auth/me")
        assert resp.json()["is_admin"] is True

    def test_regular_user_returns_is_admin_false(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("bob", "secret1")
        token = mgr.create_session("bob")
        client.cookies.set("session_token", token)
        with patch("backend.config.ADMIN_USERNAMES", set()):
            resp = client.get("/api/auth/me")
        assert resp.json()["is_admin"] is False


# ============================================================
# POST /api/auth/change-password
# ============================================================

class TestChangePassword:
    def test_success(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "old_pass")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.post(
            "/api/auth/change-password",
            json={"old_password": "old_pass", "new_password": "new_pass_123"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_wrong_old_password_returns_400(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "old_pass")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.post(
            "/api/auth/change-password",
            json={"old_password": "wrong", "new_password": "new_pass_123"},
        )
        assert resp.status_code == 400

    def test_new_password_too_short_returns_422(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "old_pass")
        token = mgr.create_session("alice")
        client.cookies.set("session_token", token)
        resp = client.post(
            "/api/auth/change-password",
            json={"old_password": "old_pass", "new_password": "abc"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_returns_401(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post(
            "/api/auth/change-password",
            json={"old_password": "old_pass", "new_password": "new_pass_123"},
        )
        assert resp.status_code == 401

    def test_change_password_invalidates_existing_sessions(self, auth_setup):
        """密码修改后所有旧 session 应失效（防止泄露的 cookie 继续使用）。"""
        client, mgr, _ = auth_setup
        mgr.register_user("alice", "old_pass")
        old_token = mgr.create_session("alice")

        # 用旧 token 修改密码
        client.cookies.set("session_token", old_token)
        resp = client.post(
            "/api/auth/change-password",
            json={"old_password": "old_pass", "new_password": "new_pass_123"},
        )
        assert resp.status_code == 200

        # 旧 token 应已作废
        assert mgr.verify_session(old_token) is None


# ============================================================
# _get_client_ip — 代理头信任逻辑（CF-Connecting-IP 回归）
# ============================================================

class TestGetClientIP:
    """验证 _get_client_ip 仅在受信任代理（loopback）连接时才读取转发头。

    部署环境：Cloudflare Tunnel（cloudflared）监听 127.0.0.1，将真实客户端 IP
    放在 CF-Connecting-IP 头。若不读该头，所有用户 IP 均为 127.0.0.1，
    导致速率限制所有用户共享同一个桶（B 回归）。
    """

    def _make_request(self, host: str, headers: dict):
        """构造带指定 client.host 和 headers 的 mock Request。"""
        req = MagicMock()
        req.client.host = host
        req.headers = headers
        return req

    def test_cf_connecting_ip_used_when_from_loopback(self):
        """来自 loopback 的连接，CF-Connecting-IP 应作为真实 IP。"""
        from backend.auth_routes import _get_client_ip
        req = self._make_request("127.0.0.1", {"CF-Connecting-IP": "203.0.113.42"})
        assert _get_client_ip(req) == "203.0.113.42"

    def test_x_forwarded_for_used_as_fallback_from_loopback(self):
        """无 CF-Connecting-IP 时，X-Forwarded-For 第一个 IP 作为真实 IP。"""
        from backend.auth_routes import _get_client_ip
        req = self._make_request("127.0.0.1", {"X-Forwarded-For": "198.51.100.1, 10.0.0.1"})
        assert _get_client_ip(req) == "198.51.100.1"

    def test_headers_ignored_when_not_from_trusted_proxy(self):
        """非 loopback 直连时，转发头应被忽略（防止外部伪造 CF-Connecting-IP）。"""
        from backend.auth_routes import _get_client_ip
        req = self._make_request("10.0.0.5", {"CF-Connecting-IP": "1.2.3.4"})
        assert _get_client_ip(req) == "10.0.0.5"

    def test_ipv6_mapped_ipv4_stripped_from_cf_header(self):
        """CF-Connecting-IP 中 ::ffff: 前缀应被剥离。"""
        from backend.auth_routes import _get_client_ip
        req = self._make_request("127.0.0.1", {"CF-Connecting-IP": "::ffff:203.0.113.1"})
        assert _get_client_ip(req) == "203.0.113.1"

    def test_ipv6_loopback_also_trusted(self):
        """::1（IPv6 loopback）同样受信任。"""
        from backend.auth_routes import _get_client_ip
        req = self._make_request("::1", {"CF-Connecting-IP": "203.0.113.7"})
        assert _get_client_ip(req) == "203.0.113.7"

    def test_no_client_returns_unknown(self):
        """request.client 为 None 时返回 'unknown'。"""
        from backend.auth_routes import _get_client_ip
        req = MagicMock()
        req.client = None
        req.headers = {}
        assert _get_client_ip(req) == "unknown"
