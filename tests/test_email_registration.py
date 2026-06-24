"""
G-62: Email Registration P1 tests.

Covers:
A. Registration API (email field, validation, uniqueness, storage)
B. Legacy user compatibility (no email → login still works)
C. Login API (username+password only, email not required)
D. Frontend/static checks (form has email input, JS includes email)
E. Security (password_hash not exposed, email not in catalog/lab APIs)
F. Regression (existing labs, CTA, article endpoints unaffected)
"""

import json
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AuthManager
from backend.auth_routes import router as auth_router

pytestmark = pytest.mark.static

_TESTPASS = "secret123"  # test-only placeholder — never used in production


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_setup(tmp_path):
    """Isolated AuthManager + TestClient, rate limiter bypassed."""
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
            client = TestClient(app, raise_server_exceptions=True)
            yield client, mgr, users_file


def _reg(client, username="alice", password=_TESTPASS, email="alice@example.com"):
    return client.post("/api/auth/register", json={"username": username, "password": password, "email": email})


def _login(client, username="alice", password=_TESTPASS):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# ──────────────────────────────────────────────────────────────────
# A. Registration API tests
# ──────────────────────────────────────────────────────────────────

class TestRegistrationAPI:

    def test_register_with_valid_email_succeeds(self, auth_setup):
        client, _, _ = auth_setup
        resp = _reg(client)
        assert resp.status_code == 201
        assert resp.json()["success"] is True
        assert resp.json()["username"] == "alice"

    def test_missing_email_rejected_422(self, auth_setup):
        client, _, _ = auth_setup
        resp = client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
        assert resp.status_code == 422

    def test_invalid_email_format_rejected_422(self, auth_setup):
        client, _, _ = auth_setup
        resp = _reg(client, email="not-an-email")
        assert resp.status_code == 422

    def test_invalid_email_missing_domain_rejected(self, auth_setup):
        client, _, _ = auth_setup
        resp = _reg(client, email="alice@")
        assert resp.status_code == 422

    def test_invalid_email_missing_local_rejected(self, auth_setup):
        client, _, _ = auth_setup
        resp = _reg(client, email="@example.com")
        assert resp.status_code == 422

    def test_duplicate_email_rejected_400(self, auth_setup):
        client, _, _ = auth_setup
        first = _reg(client, username="alice", email="shared@example.com")
        assert first.status_code == 201, f"First registration must succeed: {first.text}"
        resp = _reg(client, username="bob", email="shared@example.com")
        assert resp.status_code == 400

    def test_duplicate_username_rejected_400(self, auth_setup):
        client, _, _ = auth_setup
        _reg(client)
        resp = _reg(client, email="alice2@example.com")
        assert resp.status_code == 400

    def test_email_normalized_lowercase(self, auth_setup):
        client, _, users_file = auth_setup
        _reg(client, email="Alice@EXAMPLE.COM")
        users = json.loads(users_file.read_text())
        assert users["alice"]["email"] == "alice@example.com"

    def test_email_trimmed_of_spaces(self, auth_setup):
        client, _, users_file = auth_setup
        resp = _reg(client, email="  alice@example.com  ")
        assert resp.status_code == 201
        users = json.loads(users_file.read_text())
        assert users["alice"]["email"] == "alice@example.com"

    def test_password_hash_stored_not_plaintext(self, auth_setup):
        client, _, users_file = auth_setup
        _reg(client, password=_TESTPASS)
        users = json.loads(users_file.read_text())
        record = users["alice"]
        assert "password_hash" in record
        assert record.get("password") is None
        assert record["password_hash"] != "mypassword"

    def test_response_does_not_include_password_hash(self, auth_setup):
        client, _, _ = auth_setup
        resp = _reg(client)
        assert resp.status_code == 201
        data = resp.json()
        assert "password_hash" not in data
        assert "password" not in data

    def test_response_does_not_include_email(self, auth_setup):
        """Email is stored but not echoed back in the registration response."""
        client, _, _ = auth_setup
        resp = _reg(client, email="alice@example.com")
        assert resp.status_code == 201
        assert "email" not in resp.json()

    def test_email_stored_in_users_json(self, auth_setup):
        client, _, users_file = auth_setup
        _reg(client, email="alice@example.com")
        users = json.loads(users_file.read_text())
        assert users["alice"]["email"] == "alice@example.com"

    def test_duplicate_email_case_insensitive(self, auth_setup):
        """ALICE@EXAMPLE.COM and alice@example.com are the same after normalization."""
        client, _, _ = auth_setup
        first = _reg(client, username="alice", email="alice@example.com")
        assert first.status_code == 201
        resp = _reg(client, username="bob", email="ALICE@EXAMPLE.COM")
        assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────
# B. Legacy user compatibility
# ──────────────────────────────────────────────────────────────────

class TestLegacyUserCompatibility:

    def test_legacy_user_without_email_can_login(self, auth_setup):
        """Users registered before email field existed can still log in."""
        client, mgr, _ = auth_setup
        mgr.register_user("legacy", _TESTPASS)  # no email
        resp = _login(client, username="legacy", password=_TESTPASS)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_legacy_user_has_no_email_in_record(self, auth_setup):
        client, mgr, users_file = auth_setup
        mgr.register_user("legacy", _TESTPASS)
        users = json.loads(users_file.read_text())
        assert "email" not in users["legacy"]

    def test_new_user_with_email_can_login(self, auth_setup):
        client, _, _ = auth_setup
        _reg(client)
        resp = _login(client)
        assert resp.status_code == 200

    def test_legacy_and_new_users_coexist(self, auth_setup):
        client, mgr, users_file = auth_setup
        mgr.register_user("legacy", _TESTPASS)  # no email
        _reg(client, username="newuser", email="new@example.com")
        users = json.loads(users_file.read_text())
        assert "email" not in users["legacy"]
        assert users["newuser"]["email"] == "new@example.com"

    def test_register_user_direct_still_works_without_email(self, auth_setup):
        """Direct AuthManager.register_user() call without email remains backward-compatible."""
        _, mgr, users_file = auth_setup
        result = mgr.register_user("bob", _TESTPASS)
        assert result is True
        users = json.loads(users_file.read_text())
        assert "bob" in users


# ──────────────────────────────────────────────────────────────────
# C. Login API (email NOT required)
# ──────────────────────────────────────────────────────────────────

class TestLoginAPIEmailNotRequired:

    def test_login_uses_username_and_password_only(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", _TESTPASS)
        resp = _login(client, username="alice", password=_TESTPASS)
        assert resp.status_code == 200

    def test_login_does_not_accept_email_as_username(self, auth_setup):
        """Login form is username+password — email address as username is invalid format."""
        client, _, _ = auth_setup
        resp = client.post("/api/auth/login", json={"username": "alice@example.com", "password": _TESTPASS})
        # email contains @ which is not allowed in username pattern → 422
        assert resp.status_code == 422

    def test_login_does_not_require_email_field(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", _TESTPASS)
        resp = client.post("/api/auth/login", json={"username": "alice", "password": _TESTPASS})
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────
# D. Frontend / static checks
# ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent


class TestFrontendStaticChecks:

    def test_register_form_has_email_input(self):
        html = (REPO_ROOT / "frontend" / "login.html").read_text()
        assert 'id="register-email"' in html

    def test_register_email_input_is_required(self):
        html = (REPO_ROOT / "frontend" / "login.html").read_text()
        # find the email input and verify 'required' attribute is present
        idx = html.index('id="register-email"')
        snippet = html[max(0, idx - 200):idx + 300]
        assert "required" in snippet

    def test_register_email_input_type_is_email(self):
        html = (REPO_ROOT / "frontend" / "login.html").read_text()
        idx = html.index('id="register-email"')
        snippet = html[max(0, idx - 200):idx + 200]
        assert 'type="email"' in snippet

    def test_auth_js_sends_email_in_register_body(self):
        js = (REPO_ROOT / "frontend" / "js" / "auth.js").read_text()
        # Confirm email is captured and sent
        assert "register-email" in js
        assert "email" in js

    def test_auth_js_normalizes_email_client_side(self):
        js = (REPO_ROOT / "frontend" / "js" / "auth.js").read_text()
        assert ".trim()" in js
        assert ".toLowerCase()" in js

    def test_auth_js_includes_email_in_json_body(self):
        js = (REPO_ROOT / "frontend" / "js" / "auth.js").read_text()
        assert "JSON.stringify({ username, email, password }" in js

    def test_register_form_label_mentions_email(self):
        html = (REPO_ROOT / "frontend" / "login.html").read_text()
        assert "邮箱" in html


# ──────────────────────────────────────────────────────────────────
# E. Security checks
# ──────────────────────────────────────────────────────────────────

class TestEmailSecurityBoundaries:

    def test_password_hash_never_in_api_response(self, auth_setup):
        client, _, _ = auth_setup
        _reg(client)
        resp = _login(client)
        assert "password_hash" not in resp.text
        assert "password_hash" not in resp.json()

    def test_no_smtp_config_in_auth_routes(self):
        src = (REPO_ROOT / "backend" / "auth_routes.py").read_text()
        for keyword in ["smtplib", "sendgrid", "mailgun", "send_email", "aws_ses", "boto_ses"]:
            assert keyword.lower() not in src.lower(), f"Found forbidden email-service keyword: {keyword}"

    def test_no_smtp_config_in_auth_py(self):
        src = (REPO_ROOT / "backend" / "auth.py").read_text()
        for keyword in ["smtplib", "sendgrid", "mailgun", "send_email", "aws_ses", "boto_ses"]:
            assert keyword.lower() not in src.lower(), f"Found forbidden email-service keyword: {keyword}"

    def test_email_not_in_me_response(self, auth_setup):
        client, mgr, _ = auth_setup
        _reg(client)
        _login(client)
        # Get session cookie
        login_resp = _login(client)
        me_resp = client.get("/api/auth/me", cookies=login_resp.cookies)
        assert me_resp.status_code == 200
        assert "email" not in me_resp.json()

    def test_users_json_not_accessible_via_static_route(self):
        """users.json must not be served under any frontend static path."""
        auth_routes_src = (REPO_ROOT / "backend" / "auth_routes.py").read_text()
        main_src = (REPO_ROOT / "backend" / "main.py").read_text()
        # No StaticFiles mount should expose the data/ directory
        assert "StaticFiles" not in auth_routes_src
        # Confirm data/ is not mounted as static in main (existing safety guard)
        combined = auth_routes_src + main_src
        assert 'directory="data"' not in combined
        assert "directory='data'" not in combined

    def test_no_new_secrets_in_auth_py(self):
        src = (REPO_ROOT / "backend" / "auth.py").read_text()
        for keyword in ["SENDGRID_API_KEY", "MAILGUN_API_KEY", "SMTP_PASSWORD", "EMAIL_TOKEN"]:
            assert keyword not in src


# ──────────────────────────────────────────────────────────────────
# F. Regression
# ──────────────────────────────────────────────────────────────────

class TestRegressionChecks:

    def test_article_cta_endpoint_unchanged(self):
        src = (REPO_ROOT / "backend" / "articles_routes.py").read_text()
        assert "lab-cta" in src
        assert "has_cta" in src

    def test_auth_me_endpoint_still_works(self, auth_setup):
        client, mgr, _ = auth_setup
        mgr.register_user("alice", _TESTPASS)
        login_resp = _login(client, username="alice", password=_TESTPASS)
        me_resp = client.get("/api/auth/me", cookies=login_resp.cookies)
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "alice"

    def test_source_article_id_not_in_auth_response(self, auth_setup):
        client, _, _ = auth_setup
        resp = _reg(client)
        assert "source_article_id" not in resp.text

    def test_login_html_still_has_all_three_tabs(self):
        html = (REPO_ROOT / "frontend" / "login.html").read_text()
        assert "tab-login" in html
        assert "tab-directus" in html
        assert "tab-register" in html

    def test_no_live_llm_in_auth(self):
        src = (REPO_ROOT / "backend" / "auth_routes.py").read_text()
        src += (REPO_ROOT / "backend" / "auth.py").read_text()
        assert "anthropic" not in src.lower()
        assert "openai" not in src.lower()
        assert "llm" not in src.lower()

    def test_no_public_upload_route(self):
        src = (REPO_ROOT / "backend" / "auth_routes.py").read_text()
        assert "upload" not in src.lower()
        assert "article" not in src.lower()
