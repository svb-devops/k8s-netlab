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
