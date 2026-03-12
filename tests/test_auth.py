"""Tests for AuthManager — new methods added in Phase 1 admin observability work."""

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

    def test_all_users_returned(self, auth):
        auth.register_user("alice", "pass123")
        auth.register_user("bob", "pass456")
        summary = auth.get_users_summary()
        assert set(summary.keys()) == {"alice", "bob"}


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
