"""
Image API routes tests — POST /api/images/resolve and POST /api/images/check-existence.

Coverage areas:
  A. Auth guard (admin-only, 403 for non-admin, 401 for unauthenticated)
  B. POST /api/images/resolve — blocking, unresolved, resolved, batch, empty
  C. POST /api/images/check-existence — resolved (mock HTTP), blocked pass-through, batch, empty
  D. Contract correctness (response shape, image_status values)
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.labgen.image_resolver import ImageResolver
from backend.labgen.models import ImageResolutionResult, ImageStatus
from backend.labgen.routes import get_image_resolver, require_admin_user
from backend.auth_deps import get_current_user

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# App import (deferred to avoid import-time side-effects)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from backend.main import app as _app
    return _app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def admin_client(app):
    """TestClient with admin auth + injectable ImageResolver."""
    app.dependency_overrides[require_admin_user] = lambda: "admin"
    app.dependency_overrides[get_current_user] = lambda: "admin"
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(require_admin_user, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_image_resolver, None)


@pytest.fixture()
def noauth_client(app):
    """TestClient with no auth overrides (triggers 401/403)."""
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _make_resolver(http_status: int = 200) -> ImageResolver:
    """ImageResolver with mocked HTTP GET."""
    return ImageResolver(
        whitelist_path="config/image_whitelist.json",
        _http_get=lambda url: http_status,
    )


# ---------------------------------------------------------------------------
# A. Auth guard
# ---------------------------------------------------------------------------


class TestAuthGuard:
    def test_resolve_requires_auth(self, noauth_client):
        r = noauth_client.post("/api/images/resolve", json={"images": []})
        assert r.status_code in (401, 403)

    def test_check_existence_requires_auth(self, noauth_client):
        r = noauth_client.post("/api/images/check-existence", json={"images": []})
        assert r.status_code in (401, 403)

    def test_resolve_non_admin_forbidden(self, app):
        app.dependency_overrides[get_current_user] = lambda: "student"
        with TestClient(app) as client:
            r = client.post("/api/images/resolve", json={"images": []})
        app.dependency_overrides.pop(get_current_user, None)
        assert r.status_code == 403

    def test_check_existence_non_admin_forbidden(self, app):
        app.dependency_overrides[get_current_user] = lambda: "student"
        with TestClient(app) as client:
            r = client.post("/api/images/check-existence", json={"images": []})
        app.dependency_overrides.pop(get_current_user, None)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# B. POST /api/images/resolve
# ---------------------------------------------------------------------------


class TestResolveImages:
    def test_empty_list_returns_empty(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={"images": []})
        assert r.status_code == 200
        assert r.json() == []

    def test_blocked_latest_tag(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "nginx:latest"}]
        })
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["image_status"] == ImageStatus.BLOCKED

    def test_blocked_no_tag(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "nginx"}]
        })
        assert r.status_code == 200
        assert r.json()[0]["image_status"] == ImageStatus.BLOCKED

    def test_blocked_external_registry(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "docker.io/library/nginx:1.25"}]
        })
        assert r.status_code == 200
        assert r.json()[0]["image_status"] == ImageStatus.BLOCKED

    def test_unresolved_unknown_image(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "unknown-image:1.0"}]
        })
        assert r.status_code == 200
        assert r.json()[0]["image_status"] == ImageStatus.UNRESOLVED

    def test_resolved_whitelisted_image(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "nginx:alpine", "image_intent": "nginx"}]
        })
        assert r.status_code == 200
        result = r.json()[0]
        assert result["image_status"] == ImageStatus.RESOLVED
        assert "172.16.100.1:5000" in result["resolved_image"]
        assert result["existence_check_passed"] is None

    def test_resolved_uses_intent_for_lookup(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "shell:1.36", "image_intent": "busybox"}]
        })
        assert r.status_code == 200
        result = r.json()[0]
        assert result["image_status"] == ImageStatus.RESOLVED

    def test_batch_multiple_images(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [
                {"requested_image": "nginx:alpine"},
                {"requested_image": "nginx:latest"},
                {"requested_image": "ghost-image:1.0"},
            ]
        })
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 3
        statuses = [x["image_status"] for x in results]
        assert ImageStatus.RESOLVED in statuses
        assert ImageStatus.BLOCKED in statuses
        assert ImageStatus.UNRESOLVED in statuses

    def test_resolve_does_not_run_existence_check(self, admin_client, app):
        """resolve should never set existence_check_passed."""
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=200)
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "nginx:alpine"}]
        })
        assert r.status_code == 200
        assert r.json()[0]["existence_check_passed"] is None

    def test_schema_version_in_response(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "nginx:alpine"}]
        })
        assert r.status_code == 200
        assert r.json()[0]["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# C. POST /api/images/check-existence
# ---------------------------------------------------------------------------


def _resolved_result(resolved_image: str = "172.16.100.1:5000/nginx:1.25-alpine") -> dict:
    return {
        "schema_version": "1.0",
        "image_intent": "nginx",
        "requested_image": "nginx:alpine",
        "resolved_image": resolved_image,
        "image_status": ImageStatus.RESOLVED,
        "existence_checked_at": None,
        "existence_check_passed": None,
        "recheck_after_hours": 24,
    }


def _blocked_result() -> dict:
    return {
        "schema_version": "1.0",
        "image_intent": "nginx",
        "requested_image": "nginx:latest",
        "resolved_image": None,
        "image_status": ImageStatus.BLOCKED,
        "existence_checked_at": None,
        "existence_check_passed": None,
        "recheck_after_hours": 24,
    }


class TestCheckExistence:
    def test_empty_list_returns_empty(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/check-existence", json={"images": []})
        assert r.status_code == 200
        assert r.json() == []

    def test_resolved_image_existence_check_passes(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=200)
        r = admin_client.post("/api/images/check-existence", json={
            "images": [_resolved_result()]
        })
        assert r.status_code == 200
        result = r.json()[0]
        assert result["existence_check_passed"] is True
        assert result["existence_checked_at"] is not None

    def test_resolved_image_existence_check_fails(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=404)
        r = admin_client.post("/api/images/check-existence", json={
            "images": [_resolved_result()]
        })
        assert r.status_code == 200
        result = r.json()[0]
        assert result["existence_check_passed"] is False

    def test_resolved_image_existence_check_network_error(self, admin_client, app):
        """HTTP 0 (network error) → existence_check_passed = False."""
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=0)
        r = admin_client.post("/api/images/check-existence", json={
            "images": [_resolved_result()]
        })
        assert r.status_code == 200
        assert r.json()[0]["existence_check_passed"] is False

    def test_blocked_image_passes_through_unchanged(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=200)
        r = admin_client.post("/api/images/check-existence", json={
            "images": [_blocked_result()]
        })
        assert r.status_code == 200
        result = r.json()[0]
        assert result["image_status"] == ImageStatus.BLOCKED
        assert result["existence_check_passed"] is None
        assert result["existence_checked_at"] is None

    def test_unresolved_image_passes_through_unchanged(self, admin_client, app):
        unresolved = {
            **_resolved_result(),
            "image_status": ImageStatus.UNRESOLVED,
            "resolved_image": None,
        }
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=200)
        r = admin_client.post("/api/images/check-existence", json={"images": [unresolved]})
        assert r.status_code == 200
        result = r.json()[0]
        assert result["image_status"] == ImageStatus.UNRESOLVED
        assert result["existence_check_passed"] is None

    def test_batch_mixed_statuses(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=200)
        r = admin_client.post("/api/images/check-existence", json={
            "images": [
                _resolved_result(),
                _blocked_result(),
            ]
        })
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 2
        resolved, blocked = results
        assert resolved["existence_check_passed"] is True
        assert blocked["existence_check_passed"] is None

    def test_check_preserves_image_intent(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=200)
        r = admin_client.post("/api/images/check-existence", json={
            "images": [_resolved_result()]
        })
        assert r.json()[0]["image_intent"] == "nginx"

    def test_check_preserves_requested_image(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=200)
        r = admin_client.post("/api/images/check-existence", json={
            "images": [_resolved_result()]
        })
        assert r.json()[0]["requested_image"] == "nginx:alpine"


# ---------------------------------------------------------------------------
# D. Contract correctness
# ---------------------------------------------------------------------------


class TestContractCorrectness:
    def test_resolve_response_has_all_contract_fields(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "nginx:alpine"}]
        })
        result = r.json()[0]
        required_fields = {
            "schema_version", "image_intent", "requested_image",
            "resolved_image", "image_status", "existence_checked_at",
            "existence_check_passed", "recheck_after_hours",
        }
        assert required_fields.issubset(result.keys())

    def test_check_response_has_all_contract_fields(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver(http_status=200)
        r = admin_client.post("/api/images/check-existence", json={
            "images": [_resolved_result()]
        })
        result = r.json()[0]
        required_fields = {
            "schema_version", "image_intent", "requested_image",
            "resolved_image", "image_status", "existence_checked_at",
            "existence_check_passed", "recheck_after_hours",
        }
        assert required_fields.issubset(result.keys())

    def test_image_status_values_are_contract_enum(self, admin_client, app):
        valid_statuses = {ImageStatus.RESOLVED, ImageStatus.UNRESOLVED, ImageStatus.BLOCKED}
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [
                {"requested_image": "nginx:alpine"},
                {"requested_image": "nginx:latest"},
                {"requested_image": "unknown:1.0"},
            ]
        })
        for result in r.json():
            assert result["image_status"] in valid_statuses

    def test_recheck_after_hours_default_24(self, admin_client, app):
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "nginx:alpine"}]
        })
        assert r.json()[0]["recheck_after_hours"] == 24

    def test_missing_image_intent_defaults_to_intent_key(self, admin_client, app):
        """When image_intent is omitted, falls back to parsed intent_key."""
        app.dependency_overrides[get_image_resolver] = lambda: _make_resolver()
        r = admin_client.post("/api/images/resolve", json={
            "images": [{"requested_image": "nginx:alpine"}]  # no image_intent
        })
        result = r.json()[0]
        assert result["image_intent"] is not None
        assert len(result["image_intent"]) > 0
