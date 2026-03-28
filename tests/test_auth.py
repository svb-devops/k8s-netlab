"""Tests for AuthManager — new methods added in Phase 1 admin observability work."""

import hashlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from backend.auth import AuthManager


@pytest.fixture
def auth(tmp_path):
    """AuthManager instance backed by temp files — fully isolated."""
    users_file = tmp_path / "users.json"
    sessions_file = tmp_path / "sessions.json"
    with patch("backend.auth.USERS_FILE", users_file), \
         patch("backend.auth.SESSIONS_FILE", sessions_file), \
         patch("backend.auth.DATA_DIR", tmp_path):
        manager = AuthManager()
        yield manager


# ============================================================
# create_session with login_ip
# ============================================================

class TestCreateSession:
    def test_login_ip_stored(self, auth):
        auth.register_user("alice", "pass123")
        auth.create_session("alice", login_ip="192.168.1.1")

        sessions = auth._load_sessions()
        session = next(iter(sessions.values()))
        assert session["login_ip"] == "192.168.1.1"

    def test_login_ip_none_when_omitted(self, auth):
        auth.register_user("alice", "pass123")
        auth.create_session("alice")

        sessions = auth._load_sessions()
        session = next(iter(sessions.values()))
        assert session["login_ip"] is None


# ============================================================
# get_active_sessions
# ============================================================

class TestGetActiveSessions:
    def test_returns_only_non_expired(self, auth):
        auth.register_user("alice", "pass123")
        auth.create_session("alice")  # valid (24h expiry)

        # Inject an already-expired session directly
        from backend.storage_utils import safe_update_json
        import backend.auth as auth_module

        def _inject(sessions):
            sessions["expired-token"] = {
                "username": "alice",
                "created_at": "2020-01-01T00:00:00",
                "expires_at": "2020-01-02T00:00:00",
                "login_ip": None,
            }
            return sessions

        safe_update_json(auth_module.SESSIONS_FILE, _inject)

        active = auth.get_active_sessions()
        assert len(active) == 1
        assert active[0]["username"] == "alice"

    def test_includes_login_ip_and_experiment(self, auth):
        auth.register_user("bob", "pass123")
        token = auth.create_session("bob", login_ip="10.0.0.2")
        auth.update_session_activity(token, current_experiment="07")

        active = auth.get_active_sessions()
        assert active[0]["login_ip"] == "10.0.0.2"
        assert active[0]["current_experiment"] == "07"


# ============================================================
# get_users_summary
# ============================================================

class TestGetUsersSummary:
    def test_no_password_hash_exposed(self, auth):
        auth.register_user("alice", "pass123")
        summary = auth.get_users_summary()

        assert "alice" in summary
        assert "password_hash" not in summary["alice"]
        assert "created_at" in summary["alice"]
        assert "is_admin" in summary["alice"]

    def test_all_users_returned(self, auth):
        auth.register_user("alice", "pass123")
        auth.register_user("bob", "pass456")
        summary = auth.get_users_summary()
        assert set(summary.keys()) == {"alice", "bob"}

    def test_is_admin_flag(self, auth):
        from unittest.mock import patch
        auth.register_user("alice", "pass123")
        auth.register_user("bob", "pass456")
        with patch("backend.config.ADMIN_USERNAMES", {"alice"}):
            summary = auth.get_users_summary()
        assert summary["alice"]["is_admin"] is True
        assert summary["bob"]["is_admin"] is False


# ============================================================
# update_session_activity
# ============================================================

class TestUpdateSessionActivity:
    def test_updates_experiment_and_timestamp(self, auth):
        auth.register_user("alice", "pass123")
        token = auth.create_session("alice")

        auth.update_session_activity(token, current_experiment="05")

        sessions = auth._load_sessions()
        assert sessions[token]["current_experiment"] == "05"
        assert "last_activity" in sessions[token]

    def test_silent_on_missing_token(self, auth):
        """Should not raise if token does not exist."""
        auth.update_session_activity("nonexistent-token", current_experiment="01")


# ============================================================
# auto_cleanup_task session 清理（L 回归）
# ============================================================

class TestAutoCleanupTaskSessionPurge:
    """L 回归：auto_cleanup_task 必须在每轮循环中清理过期 session。"""

    async def test_auto_cleanup_task_calls_cleanup_expired_sessions(self):
        """auto_cleanup_task 应调用 auth_manager.cleanup_expired_sessions()（L 回归）。"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from backend.main import auto_cleanup_task

        mock_auth = MagicMock()
        mock_tracker = MagicMock()
        mock_tracker.get_expired_vms.return_value = []

        sleep_calls = [None, asyncio.CancelledError()]

        async def fake_sleep(_):
            val = sleep_calls.pop(0)
            if isinstance(val, type) and issubclass(val, BaseException):
                raise val()
            if isinstance(val, BaseException):
                raise val

        with patch("backend.main.auth_manager", mock_auth), \
             patch("backend.main.vm_tracker", mock_tracker), \
             patch("backend.main.config") as mock_config, \
             patch("asyncio.sleep", side_effect=fake_sleep):
            mock_config.VM_SESSION_TIMEOUT_MIN = 30
            try:
                await auto_cleanup_task()
            except asyncio.CancelledError:
                pass

        mock_auth.cleanup_expired_sessions.assert_called_once()

    async def test_auto_cleanup_vm_not_found_warning_includes_error_string(self):
        """auto_cleanup_task 匹配到 VM 不存在时，warning 日志必须包含原始错误串（第13轮回归）。"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch, call

        from backend.main import auto_cleanup_task

        delete_error = "Configuration file 'nodes/pve/qemu-server/101.conf' does not exist"
        delete_result = {"success": False, "error": delete_error}

        mock_auth = MagicMock()
        mock_tracker = MagicMock()
        mock_tracker.get_expired_vms.return_value = [101]

        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value=delete_result)

        sleep_calls = [None, asyncio.CancelledError()]

        async def fake_sleep(_):
            val = sleep_calls.pop(0)
            if isinstance(val, type) and issubclass(val, BaseException):
                raise val()
            if isinstance(val, BaseException):
                raise val

        with patch("backend.main.auth_manager", mock_auth), \
             patch("backend.main.vm_tracker", mock_tracker), \
             patch("backend.main.config") as mock_config, \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("asyncio.sleep", side_effect=fake_sleep), \
             patch("backend.main.logger") as mock_logger:
            mock_config.VM_SESSION_TIMEOUT_MIN = 30
            mock_config.VM_TEMPLATE_ID = 100
            try:
                await auto_cleanup_task()
            except asyncio.CancelledError:
                pass

        # 检查 logger.warning 被调用，且调用参数包含原始错误串
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("101" in c for c in warning_calls), \
            f"Expected VM 101 in warning calls. Got: {warning_calls}"
        assert any("does not exist" in c or "101.conf" in c for c in warning_calls), (
            f"Warning call must include original error string. Got: {warning_calls}"
        )


# ============================================================
# SHA-256 → bcrypt 自动升级（L2 回归）
# ============================================================

class TestPasswordAutoUpgrade:
    def test_sha256_hash_upgraded_to_bcrypt_on_login(self, auth, tmp_path):
        """
        登录时若存储的是 SHA-256 明文哈希，必须自动升级为 bcrypt（回归：
        旧用户首次在新版本登录后哈希格式应透明升级，防止旧弱哈希长期留存）。
        """
        import backend.auth as auth_module

        # 直接注入 SHA-256 哈希的用户
        sha256_hash = hashlib.sha256("secret".encode()).hexdigest()
        users_file = auth_module.USERS_FILE
        from backend.storage_utils import safe_write_json
        safe_write_json(users_file, {
            "legacy_user": {
                "password_hash": sha256_hash,
                "created_at": "2025-01-01T00:00:00",
            }
        })

        # 登录成功
        assert auth.verify_credentials("legacy_user", "secret") is True

        # 升级后哈希应为 bcrypt 格式
        from backend.storage_utils import safe_read_json
        upgraded = safe_read_json(users_file)
        new_hash = upgraded["legacy_user"]["password_hash"]
        assert new_hash.startswith("$2b$"), (
            f"SHA-256 哈希未升级为 bcrypt，当前值: {new_hash!r}"
        )


# ============================================================
# reset_password（管理员强制重置）
# ============================================================

class TestResetPassword:
    def test_reset_existing_user_returns_true(self, auth):
        """reset_password 对已有用户必须返回 True 并更新密码。"""
        auth.register_user("alice", "oldpass")
        result = auth.reset_password("alice", "newpass")
        assert result is True
        assert auth.verify_credentials("alice", "newpass") is True

    def test_reset_nonexistent_user_returns_false(self, auth):
        """reset_password 对不存在的用户必须返回 False，不抛异常。"""
        result = auth.reset_password("ghost", "anypass")
        assert result is False

    def test_reset_invalidates_existing_sessions(self, auth):
        """reset_password 后旧 session 必须失效（安全回归）。"""
        auth.register_user("alice", "oldpass")
        old_token = auth.create_session("alice")
        assert auth.verify_session(old_token) == "alice"

        auth.reset_password("alice", "newpass")
        assert auth.verify_session(old_token) is None


# ============================================================
# cleanup_expired_sessions
# ============================================================

class TestCleanupExpiredSessions:
    def test_removes_expired_keeps_valid(self, auth):
        """cleanup_expired_sessions 必须删除过期 session，保留有效 session。"""
        import backend.auth as auth_module
        from backend.storage_utils import safe_update_json

        auth.register_user("alice", "pass")
        valid_token = auth.create_session("alice")

        # 注入已过期的 session
        def _inject(sessions):
            sessions["expired-tok"] = {
                "username": "alice",
                "created_at": "2020-01-01T00:00:00",
                "expires_at": "2020-01-02T00:00:00",
                "login_ip": None,
            }
            return sessions

        safe_update_json(auth_module.SESSIONS_FILE, _inject)

        auth.cleanup_expired_sessions()

        sessions = auth._load_sessions()
        assert "expired-tok" not in sessions
        assert valid_token in sessions

    def test_no_error_when_no_sessions(self, auth):
        """cleanup_expired_sessions 在没有任何 session 时不抛异常。"""
        auth.cleanup_expired_sessions()  # must not raise
