"""HTTP integration tests for registration email verification (/api/auth/*).

Covers: register response shape when RESEND_API_KEY is set/unset, the new
verify-email and resend-verification endpoints, and the login 403 gate for
unverified accounts. Legacy accounts (no email_verified field) must be
unaffected — that's the backward-compatibility guarantee this feature promises.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AuthManager
from backend.auth_routes import router


@pytest.fixture
def verify_setup(tmp_path):
    """TestClient + AuthManager backed by isolated temp files.

    RESEND_API_KEY defaults to a fake key (verification enabled) — tests that
    need it disabled override via a nested patch.
    """
    users_file = tmp_path / "users.json"
    sessions_file = tmp_path / "sessions.json"

    with patch("backend.auth.USERS_FILE", users_file), \
         patch("backend.auth.SESSIONS_FILE", sessions_file), \
         patch("backend.auth.DATA_DIR", tmp_path):
        mgr = AuthManager()

        mock_rl = MagicMock()
        mock_rl.is_over_limit.return_value = False
        mock_rl.retry_after.return_value = 30

        mock_send = AsyncMock(return_value=True)

        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl), \
             patch("backend.auth_routes.send_verification_email", mock_send), \
             patch("backend.config.RESEND_API_KEY", "re_test_key"):
            app = FastAPI()
            app.include_router(router)
            client = TestClient(app, raise_server_exceptions=True)
            yield client, mgr, mock_rl, mock_send


def _register(client, username="alice", email="alice@example.com", password="secret1"):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "email": email},
    )


# ============================================================
# POST /api/auth/register — verification_required flag
# ============================================================

class TestRegisterVerificationFlag:
    def test_verification_required_true_when_resend_enabled(self, verify_setup):
        client, _, _, mock_send = verify_setup
        resp = _register(client)
        assert resp.status_code == 201
        assert resp.json()["verification_required"] is True
        mock_send.assert_awaited_once()
        assert mock_send.call_args.args[0] == "alice@example.com"

    def test_verification_required_false_when_resend_disabled(self, verify_setup):
        client, _, _, mock_send = verify_setup
        with patch("backend.config.RESEND_API_KEY", ""):
            resp = _register(client)
        assert resp.status_code == 201
        assert resp.json()["verification_required"] is False
        mock_send.assert_not_awaited()

    def test_registration_succeeds_even_if_email_send_fails(self, verify_setup):
        client, _, _, mock_send = verify_setup
        mock_send.return_value = False
        resp = _register(client)
        assert resp.status_code == 201
        assert resp.json()["verification_required"] is True


# ============================================================
# POST /api/auth/login — blocked until verified
# ============================================================

class TestLoginVerificationGate:
    def test_unverified_user_login_returns_403(self, verify_setup):
        client, _, _, _ = verify_setup
        _register(client)
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 403

    def test_verified_user_login_succeeds(self, verify_setup):
        client, mgr, _, _ = verify_setup
        _register(client)
        code = mgr.generate_verification_code("alice")
        client.post("/api/auth/verify-email", json={"username": "alice", "code": code})

        resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret1"})
        assert resp.status_code == 200

    def test_legacy_user_without_verification_field_can_login(self, verify_setup):
        """Accounts created before this feature (or while RESEND_API_KEY was unset)
        must not be retroactively locked out."""
        client, _, _, _ = verify_setup
        with patch("backend.config.RESEND_API_KEY", ""):
            _register(client, username="legacy", email="legacy@example.com")
        # Now verification is "enabled" globally, but legacy's email_verified=True already
        resp = client.post("/api/auth/login", json={"username": "legacy", "password": "secret1"})
        assert resp.status_code == 200


# ============================================================
# POST /api/auth/verify-email
# ============================================================

class TestVerifyEmailRoute:
    def test_correct_code_returns_200(self, verify_setup):
        client, mgr, _, _ = verify_setup
        _register(client)
        code = mgr.generate_verification_code("alice")

        resp = client.post("/api/auth/verify-email", json={"username": "alice", "code": code})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_wrong_code_returns_400(self, verify_setup):
        client, mgr, _, _ = verify_setup
        _register(client)
        mgr.generate_verification_code("alice")

        resp = client.post("/api/auth/verify-email", json={"username": "alice", "code": "000000"})
        assert resp.status_code == 400

    def test_malformed_code_rejected_by_validation(self, verify_setup):
        client, _, _, _ = verify_setup
        _register(client)
        resp = client.post("/api/auth/verify-email", json={"username": "alice", "code": "abc"})
        assert resp.status_code == 422

    def test_unknown_username_returns_400(self, verify_setup):
        client, _, _, _ = verify_setup
        resp = client.post("/api/auth/verify-email", json={"username": "nobody", "code": "123456"})
        assert resp.status_code == 400


# ============================================================
# POST /api/auth/resend-verification
# ============================================================

class TestResendVerificationRoute:
    def test_resend_sends_new_code(self, verify_setup):
        client, mgr, _, mock_send = verify_setup
        _register(client)
        mock_send.reset_mock()

        resp = client.post("/api/auth/resend-verification", json={"username": "alice"})
        assert resp.status_code == 200
        mock_send.assert_awaited_once()

    def test_resend_unknown_username_still_returns_success(self, verify_setup):
        """Must not leak whether a username exists."""
        client, _, _, mock_send = verify_setup
        resp = client.post("/api/auth/resend-verification", json={"username": "nobody"})
        assert resp.status_code == 200
        mock_send.assert_not_awaited()

    def test_resend_rate_limited(self, verify_setup):
        client, _, mock_rl, _ = verify_setup
        _register(client)
        mock_rl.is_over_limit.return_value = True

        resp = client.post("/api/auth/resend-verification", json={"username": "alice"})
        assert resp.status_code == 429

    def test_new_code_invalidates_old_one(self, verify_setup):
        client, mgr, _, _ = verify_setup
        _register(client)
        old_code = mgr.generate_verification_code("alice")

        client.post("/api/auth/resend-verification", json={"username": "alice"})

        resp = client.post("/api/auth/verify-email", json={"username": "alice", "code": old_code})
        assert resp.status_code == 400

    def test_resend_ip_rate_limited(self, verify_setup):
        """A second, distinct rate-limit dimension (IP) — cycling through many
        usernames from one IP must also be throttled, not just per-username."""
        client, _, mock_rl, _ = verify_setup
        mock_rl.is_over_limit.side_effect = lambda key, **kw: key.startswith("resend-verification-ip:")

        resp = client.post("/api/auth/resend-verification", json={"username": "someone"})
        assert resp.status_code == 429


# ============================================================
# POST /api/auth/verify-email — rate limiting (safety-reviewer BLOCKER fix)
# ============================================================

class TestVerifyEmailRateLimit:
    def test_verify_email_rate_limited(self, verify_setup):
        client, _, mock_rl, _ = verify_setup
        mock_rl.is_over_limit.return_value = True

        resp = client.post("/api/auth/verify-email", json={"username": "alice", "code": "123456"})
        assert resp.status_code == 429

    def test_verify_email_not_limited_under_threshold(self, verify_setup):
        client, mgr, mock_rl, _ = verify_setup
        _register(client)
        code = mgr.generate_verification_code("alice")
        mock_rl.is_over_limit.return_value = False

        resp = client.post("/api/auth/verify-email", json={"username": "alice", "code": code})
        assert resp.status_code == 200
