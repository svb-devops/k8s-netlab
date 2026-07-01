"""Tests for AuthManager email verification (registration hardening for public launch)."""

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


def _with_resend_key(enabled: bool):
    return patch("backend.config.RESEND_API_KEY", "re_test_key" if enabled else "")


# ============================================================
# register_user: email_verified default
# ============================================================

class TestRegisterEmailVerifiedDefault:
    def test_verified_true_when_resend_unset(self, auth):
        with _with_resend_key(False):
            auth.register_user("alice", "pass123", email="alice@example.com")
        assert auth.is_email_verified("alice") is True

    def test_verified_false_when_resend_set(self, auth):
        with _with_resend_key(True):
            auth.register_user("bob", "pass123", email="bob@example.com")
        assert auth.is_email_verified("bob") is False

    def test_legacy_user_without_field_is_verified(self, auth):
        """Users created before this feature existed have no email_verified key."""
        from backend.auth import USERS_FILE
        from backend.storage_utils import safe_update_json

        auth.register_user("legacy", "pass123")

        def _strip(users):
            users["legacy"].pop("email_verified", None)
            return users
        safe_update_json(USERS_FILE, _strip)

        assert auth.is_email_verified("legacy") is True

    def test_unknown_user_is_verified(self, auth):
        assert auth.is_email_verified("nobody") is True


# ============================================================
# generate_verification_code
# ============================================================

class TestGenerateVerificationCode:
    def test_returns_six_digit_code(self, auth):
        auth.register_user("alice", "pass123", email="alice@example.com")
        code = auth.generate_verification_code("alice")
        assert code is not None
        assert len(code) == 6
        assert code.isdigit()

    def test_returns_none_for_unknown_user(self, auth):
        assert auth.generate_verification_code("nobody") is None

    def test_code_not_stored_in_plaintext(self, auth):
        auth.register_user("alice", "pass123", email="alice@example.com")
        code = auth.generate_verification_code("alice")
        users = auth._load_users()
        assert code not in str(users["alice"])
        assert "verification_code_hash" in users["alice"]

    def test_resets_attempts_on_new_code(self, auth):
        with _with_resend_key(True):
            auth.register_user("alice", "pass123", email="alice@example.com")
        auth.generate_verification_code("alice")
        auth.verify_email("alice", "000000")  # wrong code, bumps attempts
        auth.generate_verification_code("alice")  # resend
        users = auth._load_users()
        assert users["alice"]["verification_attempts"] == 0


# ============================================================
# verify_email
# ============================================================

class TestVerifyEmail:
    def test_correct_code_succeeds(self, auth):
        with _with_resend_key(True):
            auth.register_user("alice", "pass123", email="alice@example.com")
        code = auth.generate_verification_code("alice")

        result = auth.verify_email("alice", code)

        assert result["success"] is True
        assert auth.is_email_verified("alice") is True

    def test_wrong_code_fails_and_counts_attempt(self, auth):
        with _with_resend_key(True):
            auth.register_user("alice", "pass123", email="alice@example.com")
        auth.generate_verification_code("alice")

        result = auth.verify_email("alice", "000000")

        assert result["success"] is False
        assert result["reason"] == "invalid_code"
        assert result["attempts_remaining"] == 4
        assert auth.is_email_verified("alice") is False

    def test_five_wrong_attempts_then_rejected(self, auth):
        with _with_resend_key(True):
            auth.register_user("alice", "pass123", email="alice@example.com")
        auth.generate_verification_code("alice")

        for _ in range(5):
            auth.verify_email("alice", "000000")

        result = auth.verify_email("alice", "000000")
        assert result["success"] is False
        assert result["reason"] == "too_many_attempts"

    def test_expired_code_rejected(self, auth):
        with _with_resend_key(True):
            auth.register_user("alice", "pass123", email="alice@example.com")
        code = auth.generate_verification_code("alice")

        def _expire(users):
            users["alice"]["verification_code_expires_at"] = (
                datetime.now() - timedelta(minutes=1)
            ).isoformat()
            return users
        from backend.storage_utils import safe_update_json
        from backend.auth import USERS_FILE as _uf
        safe_update_json(_uf, _expire)

        result = auth.verify_email("alice", code)
        assert result["success"] is False
        assert result["reason"] == "expired"

    def test_unknown_user_rejected(self, auth):
        result = auth.verify_email("nobody", "123456")
        assert result["success"] is False
        assert result["reason"] == "not_found"

    def test_already_verified_user_returns_success(self, auth):
        with _with_resend_key(False):
            auth.register_user("alice", "pass123", email="alice@example.com")
        result = auth.verify_email("alice", "000000")
        assert result["success"] is True

    def test_code_cleared_after_successful_verification(self, auth):
        with _with_resend_key(True):
            auth.register_user("alice", "pass123", email="alice@example.com")
        code = auth.generate_verification_code("alice")
        auth.verify_email("alice", code)

        users = auth._load_users()
        assert "verification_code_hash" not in users["alice"]
        assert "verification_code_expires_at" not in users["alice"]
