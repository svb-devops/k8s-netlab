"""
Tests for verifier credentials health check in /api/health.

Validates:
  - Health response includes labgen section
  - labgen.status is "ok" when all exempt VM credentials are present
  - labgen.status is "degraded" when any exempt VM credentials are missing
  - labgen.missing_credentials lists VM IDs with missing credentials
  - labgen.credential_root_exists is reported correctly
  - Existing consumers: status/proxmox fields still present (backward compat)
  - Health check never exposes credential content
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.static


@pytest.fixture(scope="module")
def app():
    from backend.main import app as _app
    return _app


@pytest.fixture()
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# _check_verifier_credentials_health unit tests
# ---------------------------------------------------------------------------


class TestVerifierCredentialsHealth:
    def _call_health_fn(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        exempt_ids: frozenset,
        credentials_present: dict[str, bool],
        cred_root_exists: bool = True,
    ) -> dict[str, Any]:
        import backend.labgen.verifier_credentials as vc_mod
        from backend import config as cfg
        from backend.api_routes import _check_verifier_credentials_health

        monkeypatch.setattr(cfg, "VM_CLEANUP_EXEMPT_IDS", exempt_ids)

        _root_exists = cred_root_exists
        _creds = credentials_present

        class _FakeStore:
            def __init__(self, _root: Any = None) -> None:
                pass

            @property
            def credential_root_exists(self) -> bool:
                return _root_exists

            def exists(self, vm_id: str) -> bool:
                return _creds.get(vm_id, False)

        original = vc_mod.VerifierCredentialStore
        vc_mod.VerifierCredentialStore = _FakeStore  # type: ignore[attr-defined]
        try:
            return _check_verifier_credentials_health()
        finally:
            vc_mod.VerifierCredentialStore = original

    def test_status_ok_when_all_credentials_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._call_health_fn(
            monkeypatch,
            exempt_ids=frozenset({401, 299}),
            credentials_present={"401": True, "299": True},
        )
        assert result["status"] == "ok"
        assert result["missing_credentials"] == []

    def test_status_degraded_when_credentials_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._call_health_fn(
            monkeypatch,
            exempt_ids=frozenset({401, 299}),
            credentials_present={"401": True, "299": False},
        )
        assert result["status"] == "degraded"
        assert "299" in result["missing_credentials"]
        assert "401" not in result["missing_credentials"]

    def test_missing_credentials_lists_all_absent_vms(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._call_health_fn(
            monkeypatch,
            exempt_ids=frozenset({401, 299, 500}),
            credentials_present={"401": False, "299": False, "500": True},
        )
        assert result["status"] == "degraded"
        assert set(result["missing_credentials"]) == {"401", "299"}

    def test_credential_root_exists_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._call_health_fn(
            monkeypatch,
            exempt_ids=frozenset({401}),
            credentials_present={"401": True},
            cred_root_exists=True,
        )
        assert "credential_root_exists" in result

    def test_empty_exempt_ids_status_ok(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._call_health_fn(
            monkeypatch,
            exempt_ids=frozenset(),
            credentials_present={},
        )
        assert result["status"] == "ok"
        assert result["missing_credentials"] == []

    def test_no_credential_content_in_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._call_health_fn(
            monkeypatch,
            exempt_ids=frozenset({401}),
            credentials_present={"401": True},
        )
        result_str = str(result)
        assert "kubeconfig" not in result_str
        assert "token" not in result_str
        assert "secret" not in result_str.lower()


# ---------------------------------------------------------------------------
# HTTP integration tests: /api/health backward compatibility
# ---------------------------------------------------------------------------


class TestHealthEndpointBackwardCompat:
    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_has_status_field(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert "status" in data

    def test_health_has_proxmox_field(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert "proxmox" in data
        assert "connected" in data["proxmox"]

    def test_health_has_labgen_field(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert "labgen" in data

    def test_health_labgen_has_required_keys(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        labgen = data["labgen"]
        assert "status" in labgen
        assert "credential_root_exists" in labgen
        assert "exempt_vms" in labgen
        assert "missing_credentials" in labgen

    def test_health_labgen_status_is_string(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert isinstance(data["labgen"]["status"], str)

    def test_health_labgen_missing_credentials_is_list(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert isinstance(data["labgen"]["missing_credentials"], list)

    def test_health_head_returns_200(self, client: TestClient) -> None:
        """HEAD /api/health must still work (monitoring tool compat)."""
        resp = client.head("/api/health")
        assert resp.status_code == 200
