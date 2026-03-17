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
