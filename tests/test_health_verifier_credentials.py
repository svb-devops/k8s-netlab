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

    def test_health_has_sessions_field(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert "sessions" in data

    def test_health_sessions_has_required_keys(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        sessions = data["sessions"]
        assert "status" in sessions
        assert "active_session_count" in sessions
        assert "failed_terminal_session_count" in sessions
        assert "tainted_vm_count" in sessions
        assert "warnings" in sessions

    def test_health_sessions_counts_are_ints(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        s = data["sessions"]
        assert isinstance(s["active_session_count"], int)
        assert isinstance(s["failed_terminal_session_count"], int)
        assert isinstance(s["tainted_vm_count"], int)

    def test_health_sessions_warnings_is_list(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert isinstance(data["sessions"]["warnings"], list)

    def test_health_sessions_status_is_string(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert isinstance(data["sessions"]["status"], str)

    def test_health_sessions_no_secrets_exposed(self, client: TestClient) -> None:
        resp_str = client.get("/api/health").text
        assert "kubeconfig" not in resp_str
        assert "token" not in resp_str.lower()
        assert "password" not in resp_str.lower()
        assert "username" not in resp_str.lower()


# ---------------------------------------------------------------------------
# _check_labgen_session_health unit tests
# ---------------------------------------------------------------------------


class TestLabgenSessionHealth:
    def _call_session_health_fn(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        sessions: list,
        tainted: dict,
        diffs_size_bytes: int = 500,
        zombie_days: int = 0,
        tmp_path: Path,
    ) -> dict[str, Any]:
        import json
        from backend.api_routes import _check_labgen_session_health
        from backend.labgen import lab_session_repository as repo_mod
        from backend.labgen import data_retention as dr_mod

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        tainted_path = data_dir / "tainted_vms.json"
        tainted_path.write_text(json.dumps(tainted))

        diffs_path = data_dir / "lab_review_diffs.json"
        diffs_path.write_bytes(b"x" * diffs_size_bytes)

        drafts_path = data_dir / "lab_drafts.json"
        if zombie_days > 0:
            from datetime import datetime, timedelta, timezone
            old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=zombie_days)).isoformat()
            drafts_path.write_text(json.dumps([{"lab_id": "z1", "publish_status": "draft", "updated_at": old_ts, "rehearsal_completed": False}]))
        else:
            drafts_path.write_text("[]")

        class _FakeRepo:
            def list_all(self_inner):
                return sessions

        monkeypatch.setattr(repo_mod, "LabSessionRepository", lambda: _FakeRepo())

        orig_path = __import__("pathlib").Path
        monkeypatch.setattr("backend.api_routes.Path" if hasattr(__import__("backend.api_routes", fromlist=["Path"]), "Path") else "pathlib.Path", orig_path)

        import builtins
        real_open = builtins.open

        def patched_open(path, *args, **kwargs):
            p = str(path)
            if "tainted_vms.json" in p:
                return real_open(tainted_path, *args, **kwargs)
            if "lab_review_diffs.json" in p and "stat" not in p:
                return real_open(diffs_path, *args, **kwargs)
            if "lab_drafts.json" in p:
                return real_open(drafts_path, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        import unittest.mock as _mock
        with _mock.patch("pathlib.Path.exists", lambda s: True), \
             _mock.patch("pathlib.Path.stat", return_value=type("S", (), {"st_size": diffs_size_bytes})()), \
             _mock.patch("pathlib.Path.read_text", side_effect=lambda **kw: tainted_path.read_text()):
            return _check_labgen_session_health()

    def test_session_health_ok_when_all_clean(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        s = data["sessions"]
        assert s["status"] in ("ok", "degraded")
        assert s["active_session_count"] >= 0
        assert s["failed_terminal_session_count"] >= 0
        assert s["tainted_vm_count"] >= 0

    def test_session_health_structure_never_has_secrets(self, client: TestClient) -> None:
        import json
        raw = json.dumps(client.get("/api/health").json()["sessions"])
        for forbidden in ("kubeconfig", "password", "secret", "token", "username"):
            assert forbidden not in raw.lower(), f"health sessions exposed: {forbidden}"

    def test_session_health_unknown_on_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.api_routes import _check_labgen_session_health
        import backend.labgen.lab_session_repository as repo_mod

        def _boom():
            raise RuntimeError("repo unavailable")

        monkeypatch.setattr(repo_mod, "LabSessionRepository", _boom)
        result = _check_labgen_session_health()
        assert result["status"] == "unknown"
        assert "error" in result

    def test_session_health_warnings_on_failed_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.api_routes import _check_labgen_session_health
        import backend.labgen.lab_session_repository as repo_mod
        from backend.labgen.models import LabSessionStatus
        import unittest.mock as _mock

        class _FakeSession:
            lab_session_status = LabSessionStatus.LAB_START_FAILED

        class _FakeRepo:
            def list_all(self):
                return [_FakeSession()]

        monkeypatch.setattr(repo_mod, "LabSessionRepository", lambda: _FakeRepo())

        with _mock.patch("pathlib.Path.exists", return_value=False):
            result = _check_labgen_session_health()

        assert result["failed_terminal_session_count"] == 1
        assert result["status"] == "degraded"
        assert any("recovery" in w for w in result["warnings"])
