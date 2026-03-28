"""Tests for admin observability endpoint — auth, data aggregation, field correctness."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.admin_routes import router

TEST_TOKEN = "test-admin-secret-xyz"

# Minimal app containing only the admin router — avoids Proxmox startup
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ============================================================
# Auth guard
# ============================================================

class TestAdminAuth:
    def test_no_token_unconfigured_returns_503(self, client):
        """When ADMIN_TOKEN is not set, endpoint must be disabled (not just 403)."""
        with patch("backend.config.ADMIN_TOKEN", ""):
            resp = client.get("/api/admin/status")
        assert resp.status_code == 503

    def test_missing_token_returns_403(self, client):
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN):
            resp = client.get("/api/admin/status")
        assert resp.status_code == 403

    def test_wrong_token_returns_403(self, client):
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN):
            resp = client.get("/api/admin/status", headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 403


# ============================================================
# Data correctness
# ============================================================

_EMPTY_MOCKS = dict(
    get_active_sessions=lambda: [],
    get_users_summary=lambda: {},
    get_all_vms_with_details=lambda: [],
)


class TestAdminStatus:
    def _patch_all(self, sessions=None, users=None, vms=None):
        """Return a context-manager stack that patches all three data sources."""
        import contextlib
        sessions = sessions or []
        users = users or {}
        vms = vms or []
        return contextlib.ExitStack()  # built inline below

    def test_empty_system_returns_zeros(self, client):
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN), \
             patch("backend.admin_routes.auth_manager.get_active_sessions", return_value=[]), \
             patch("backend.admin_routes.auth_manager.get_users_summary", return_value={}), \
             patch("backend.admin_routes.vm_tracker.get_all_vms_with_details", return_value=[]):
            resp = client.get("/api/admin/status", headers={"X-Admin-Token": TEST_TOKEN})

        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["total_users"] == 0
        assert data["stats"]["active_sessions"] == 0
        assert data["stats"]["total_tracked_vms"] == 0
        assert data["sessions"] == []

    def test_session_fields_populated_correctly(self, client):
        mock_sessions = [{
            "username": "alice",
            "login_ip": "10.0.0.5",
            "created_at": "2026-03-11T10:00:00",
            "expires_at": "2026-03-12T10:00:00",
            "current_experiment": "03",
            "last_activity": "2026-03-11T10:30:00",
        }]
        mock_users = {"alice": {"created_at": "2026-02-01T00:00:00"}}
        mock_vms = [{
            "vm_id": 500, "owner": "alice",
            "created_at": "2026-03-11T10:05:00", "age_minutes": 5.0,
        }]

        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN), \
             patch("backend.admin_routes.auth_manager.get_active_sessions", return_value=mock_sessions), \
             patch("backend.admin_routes.auth_manager.get_users_summary", return_value=mock_users), \
             patch("backend.admin_routes.vm_tracker.get_all_vms_with_details", return_value=mock_vms):
            resp = client.get("/api/admin/status", headers={"X-Admin-Token": TEST_TOKEN})

        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["total_users"] == 1
        assert data["stats"]["active_sessions"] == 1
        assert data["stats"]["total_tracked_vms"] == 1

        s = data["sessions"][0]
        assert s["username"] == "alice"
        assert s["login_ip"] == "10.0.0.5"
        assert s["registered_at"] == "2026-02-01T00:00:00"
        assert s["current_experiment"] == "03"
        assert s["last_activity"] == "2026-03-11T10:30:00"
        assert len(s["vms"]) == 1
        assert s["vms"][0]["vm_id"] == 500

    def test_session_without_experiment_fields_defaults_to_null(self, client):
        """Sessions created before experiment tracking was added must not crash."""
        mock_sessions = [{
            "username": "bob",
            "login_ip": None,
            "created_at": "2026-03-11T09:00:00",
            "expires_at": "2026-03-12T09:00:00",
            # no current_experiment, no last_activity
        }]

        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN), \
             patch("backend.admin_routes.auth_manager.get_active_sessions", return_value=mock_sessions), \
             patch("backend.admin_routes.auth_manager.get_users_summary", return_value={"bob": {"created_at": None}}), \
             patch("backend.admin_routes.vm_tracker.get_all_vms_with_details", return_value=[]):
            resp = client.get("/api/admin/status", headers={"X-Admin-Token": TEST_TOKEN})

        assert resp.status_code == 200
        s = resp.json()["sessions"][0]
        assert s["current_experiment"] is None
        assert s["last_activity"] is None
        assert s["login_ip"] is None


# ============================================================
# POST /api/admin/reset-password
# ============================================================

    def test_session_with_missing_username_does_not_crash(self, client):
        """sessions.json 中 username 字段缺失时，admin status 应跳过该 session 而非 500 崩溃（第13轮回归）。"""
        mock_sessions = [
            {},  # 损坏的 session，缺少 username
            {
                "username": "alice",
                "login_ip": None,
                "created_at": "2026-03-11T09:00:00",
                "expires_at": "2026-03-12T09:00:00",
            },
        ]
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN), \
             patch("backend.admin_routes.auth_manager.get_active_sessions", return_value=mock_sessions), \
             patch("backend.admin_routes.auth_manager.get_users_summary", return_value={}), \
             patch("backend.admin_routes.vm_tracker.get_all_vms_with_details", return_value=[]):
            resp = client.get("/api/admin/status", headers={"X-Admin-Token": TEST_TOKEN})

        assert resp.status_code == 200
        data = resp.json()
        # 损坏的 session 应被跳过，仅 alice 出现
        assert data["stats"]["active_sessions"] == 1
        assert data["sessions"][0]["username"] == "alice"


class TestAdminResetPassword:
    def test_success_resets_password(self, client):
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN), \
             patch("backend.admin_routes.auth_manager.reset_password", return_value=True) as mock_rp:
            resp = client.post(
                "/api/admin/reset-password",
                json={"username": "alice", "new_password": "newpass1"},
                headers={"X-Admin-Token": TEST_TOKEN},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_rp.assert_called_once_with("alice", "newpass1")

    def test_user_not_found_returns_404(self, client):
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN), \
             patch("backend.admin_routes.auth_manager.reset_password", return_value=False):
            resp = client.post(
                "/api/admin/reset-password",
                json={"username": "ghost", "new_password": "newpass1"},
                headers={"X-Admin-Token": TEST_TOKEN},
            )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_no_token_returns_503(self, client):
        with patch("backend.config.ADMIN_TOKEN", ""):
            resp = client.post(
                "/api/admin/reset-password",
                json={"username": "alice", "new_password": "newpass1"},
            )
        assert resp.status_code == 503

    def test_wrong_token_returns_403(self, client):
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN):
            resp = client.post(
                "/api/admin/reset-password",
                json={"username": "alice", "new_password": "newpass1"},
                headers={"X-Admin-Token": "wrong-token"},
            )
        assert resp.status_code == 403

    def test_new_password_too_short_returns_422(self, client):
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN):
            resp = client.post(
                "/api/admin/reset-password",
                json={"username": "alice", "new_password": "abc"},
                headers={"X-Admin-Token": TEST_TOKEN},
            )
        assert resp.status_code == 422

    def test_missing_username_returns_422(self, client):
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN):
            resp = client.post(
                "/api/admin/reset-password",
                json={"new_password": "newpass1"},
                headers={"X-Admin-Token": TEST_TOKEN},
            )
        assert resp.status_code == 422


# ============================================================
# geo lookup 异常兜底 + 损坏 session 过滤
# ============================================================

class TestAdminEdgeCases:
    """admin_routes 的防御性兜底分支。"""

    def _patch_all(self, sessions=None):
        import contextlib
        sessions = sessions or []
        from unittest.mock import patch as _patch
        return contextlib.ExitStack()

    def test_geo_lookup_exception_does_not_crash_status(self, client):
        """_get_geo() 内部抛异常时 /api/admin/status 必须正常返回，不传播异常。"""
        session = {
            "username": "alice",
            "created_at": "2026-01-01T00:00:00",
            "expires_at": "2099-01-01T00:00:00",
            "login_ip": "1.2.3.4",
            "last_activity": "2026-01-01T01:00:00",
        }
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN), \
             patch("backend.admin_routes.auth_manager") as mock_auth, \
             patch("backend.admin_routes.vm_tracker") as mock_tracker, \
             patch("backend.admin_routes.httpx.AsyncClient") as mock_client_cls:
            mock_auth.get_active_sessions.return_value = [session]
            mock_auth.get_users_summary.return_value = {}
            mock_tracker.get_all_vms_with_details.return_value = []

            # httpx 抛异常模拟 geo 失败
            mock_client_cls.return_value.__aenter__.side_effect = Exception("network error")

            resp = client.get("/api/admin/status", headers={"X-Admin-Token": TEST_TOKEN})
        assert resp.status_code == 200

    def test_session_missing_timestamps_is_skipped(self, client):
        """created_at 或 expires_at 缺失的 session 必须被静默跳过，不崩溃（数据损坏防御）。"""
        corrupt_session = {
            "username": "bob",
            # created_at and expires_at intentionally absent
        }
        valid_session = {
            "username": "alice",
            "created_at": "2026-01-01T00:00:00",
            "expires_at": "2099-01-01T00:00:00",
            "login_ip": None,
            "last_activity": "2026-01-01T01:00:00",
        }
        with patch("backend.config.ADMIN_TOKEN", TEST_TOKEN), \
             patch("backend.admin_routes.auth_manager") as mock_auth, \
             patch("backend.admin_routes.vm_tracker") as mock_tracker, \
             patch("backend.admin_routes.httpx.AsyncClient"):
            mock_auth.get_active_sessions.return_value = [corrupt_session, valid_session]
            mock_auth.get_users_summary.return_value = {}
            mock_tracker.get_all_vms_with_details.return_value = []
            resp = client.get("/api/admin/status", headers={"X-Admin-Token": TEST_TOKEN})

        assert resp.status_code == 200
        data = resp.json()
        # 只有 alice（有效 session）被包含，bob（损坏）被跳过
        usernames = [s["username"] for s in data["sessions"]]
        assert "alice" in usernames
        assert "bob" not in usernames
