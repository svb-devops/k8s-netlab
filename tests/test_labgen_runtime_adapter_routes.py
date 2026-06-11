"""
Runtime adapter diagnostics API — HTTP endpoint tests.

Tests cover:
A. GET /api/labgen/runtime/adapter-status
   - admin can access
   - non-admin → 403
   - unauthenticated → 401 or 403
   - response schema is stable
   - response contains expected fields
   - production unsafe → issues list contains blocking issue
   - dev/stub → NON_PRODUCTION_STUB_ALLOWED warning present
   - production_safe is bool

B. Response safety
   - no kubeconfig content
   - no service account token
   - no raw env values
   - no stack traces

C. Regression
   - endpoint is read-only (does not mutate session state)
   - existing labgen contract-pack tests unaffected

D. Selection service override
   - admin GET reflects current selection result
   - different modes return different production_safe values
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.static


def _select_dev_stub():
    from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
    return RuntimeAdapterSelectionService.select(
        runtime_mode_raw="dev",
        adapter_kind_raw="stub",
        k8s_kubeconfig_path="",
    )


# ---------------------------------------------------------------------------
# Test client context (minimal — only auth overrides)
# ---------------------------------------------------------------------------

@contextmanager
def _ctx(*, as_admin: bool = True, selection_override=None):
    from backend.main import app
    from backend.auth_deps import get_current_user
    from backend.labgen.routes import require_admin_user, get_runtime_adapter_status

    saved = dict(app.dependency_overrides)

    if as_admin:
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[get_current_user] = lambda: "admin"
    else:
        app.dependency_overrides[get_current_user] = lambda: "student1"

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def _get_status(client):
    return client.get("/api/labgen/runtime/adapter-status")


# ---------------------------------------------------------------------------
# A. GET /api/labgen/runtime/adapter-status
# ---------------------------------------------------------------------------

class TestRuntimeAdapterStatusEndpoint:
    def test_admin_can_get_status(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        assert r.status_code == 200

    def test_non_admin_gets_403(self):
        with _ctx(as_admin=False) as client:
            r = _get_status(client)
        assert r.status_code == 403

    def test_unauthenticated_gets_401_or_403(self):
        from backend.main import app
        saved = dict(app.dependency_overrides)
        c = TestClient(app, raise_server_exceptions=False)
        try:
            r = c.get("/api/labgen/runtime/adapter-status")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)
        assert r.status_code in (401, 403)

    def test_response_schema_stable(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        assert r.status_code == 200
        body = r.json()
        assert "runtime_mode" in body
        assert "namespace_adapter_kind" in body
        assert "production_safe" in body
        assert "issues" in body
        assert "warnings" in body
        assert "checked_at" in body

    def test_runtime_mode_is_string(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert isinstance(body["runtime_mode"], str)

    def test_namespace_adapter_kind_is_string(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert isinstance(body["namespace_adapter_kind"], str)

    def test_production_safe_is_bool(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert isinstance(body["production_safe"], bool)

    def test_issues_is_list(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert isinstance(body["issues"], list)

    def test_warnings_is_list(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert isinstance(body["warnings"], list)

    def test_checked_at_is_iso_string(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert isinstance(body["checked_at"], str)
        assert "T" in body["checked_at"]

    def test_default_dev_stub_not_production_safe(self, monkeypatch):
        """Default config (dev + stub) must not be production_safe."""
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "LABGEN_RUNTIME_MODE", "dev")
        monkeypatch.setattr(_cfg, "LABGEN_NAMESPACE_ADAPTER", "stub")
        monkeypatch.setattr(_cfg, "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "")
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert body["production_safe"] is False

    def test_production_stub_has_blocking_issue(self, monkeypatch):
        """production + stub → at least one blocking issue in response."""
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "LABGEN_RUNTIME_MODE", "production")
        monkeypatch.setattr(_cfg, "LABGEN_NAMESPACE_ADAPTER", "stub")
        monkeypatch.setattr(_cfg, "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "")
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert body["production_safe"] is False
        blocking = [i for i in body["issues"] if i["severity"] == "blocking"]
        assert len(blocking) >= 1

    def test_production_k8s_with_kubeconfig_safe(self, monkeypatch):
        """production + k8s + kubeconfig path set → production_safe=True."""
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "LABGEN_RUNTIME_MODE", "production")
        monkeypatch.setattr(_cfg, "LABGEN_NAMESPACE_ADAPTER", "k8s")
        monkeypatch.setattr(_cfg, "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "/etc/k8s/platform.yaml")
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        assert body["production_safe"] is True
        blocking = [i for i in body["issues"] if i["severity"] == "blocking"]
        assert len(blocking) == 0

    def test_dev_stub_has_warning_in_issues(self, monkeypatch):
        """dev + stub → NON_PRODUCTION_STUB_ALLOWED warning appears in issues."""
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "LABGEN_RUNTIME_MODE", "dev")
        monkeypatch.setattr(_cfg, "LABGEN_NAMESPACE_ADAPTER", "stub")
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        codes = [i["code"] for i in body["issues"]]
        assert "NON_PRODUCTION_STUB_ALLOWED" in codes

    def test_issue_has_code_severity_message_fields(self, monkeypatch):
        """Each issue must have code, severity, and message fields."""
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "LABGEN_RUNTIME_MODE", "dev")
        monkeypatch.setattr(_cfg, "LABGEN_NAMESPACE_ADAPTER", "stub")
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        body = r.json()
        for issue in body["issues"]:
            assert "code" in issue
            assert "severity" in issue
            assert "message" in issue


# ---------------------------------------------------------------------------
# B. Response safety (no credential leakage)
# ---------------------------------------------------------------------------

class TestResponseSafety:
    FORBIDDEN_PATTERNS = [
        "kubeconfig",
        "eyJ",             # JWT prefix
        "-----BEGIN",      # PEM header
        "service_account_token",
        "cluster_endpoint_secret",
        "raw_env_value",
        "namespace_credential",
        "Traceback",
        "traceback",
    ]

    def _check_no_forbidden_content(self, obj, path=""):
        """Recursively check that no forbidden patterns appear in string values."""
        if isinstance(obj, str):
            for pattern in self.FORBIDDEN_PATTERNS:
                assert pattern not in obj, (
                    f"Forbidden pattern '{pattern}' found in response at {path}: {obj[:100]}"
                )
        elif isinstance(obj, dict):
            for k, v in obj.items():
                self._check_no_forbidden_content(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._check_no_forbidden_content(item, f"{path}[{i}]")

    def test_response_contains_no_credential_patterns(self):
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        assert r.status_code == 200
        self._check_no_forbidden_content(r.json(), "body")

    def test_response_contains_no_stack_trace(self, monkeypatch):
        """Even with a misconfigured adapter, no stack traces in response."""
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "LABGEN_RUNTIME_MODE", "production")
        monkeypatch.setattr(_cfg, "LABGEN_NAMESPACE_ADAPTER", "stub")
        with _ctx(as_admin=True) as client:
            r = _get_status(client)
        assert r.status_code == 200
        body_str = r.text
        assert "Traceback" not in body_str
        assert "traceback" not in body_str

    def test_response_is_read_only_no_namespace_created(self):
        """GET adapter-status must not create any K8s resource.

        Injects an observable stub as the session service's ns_lifecycle, then verifies the
        diagnostics endpoint never touches it (the endpoint calls RuntimeAdapterSelectionService
        directly and never invokes get_session_service).
        """
        from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
        from backend.labgen.lab_session_service import LabSessionService, StubVMTracker
        from backend.labgen.image_resolver import ImageResolver
        from backend.labgen.routes import get_session_service
        from backend.main import app
        from unittest.mock import MagicMock

        ns = StubNamespaceLifecycleAdapter()
        selection = _select_dev_stub()

        svc = LabSessionService(
            session_repo=MagicMock(),
            draft_repo=MagicMock(),
            vm_tracker=StubVMTracker(),
            ns_lifecycle=ns,
            image_resolver=ImageResolver(),
        )

        saved = dict(app.dependency_overrides)
        app.dependency_overrides[get_session_service] = lambda: svc
        try:
            with _ctx(as_admin=True) as client:
                r = _get_status(client)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

        assert r.status_code == 200
        # Diagnostics endpoint must not have touched the injected namespace adapter
        assert ns.created == []
        assert ns.rolebindings_created == []


# ---------------------------------------------------------------------------
# C. Regression
# ---------------------------------------------------------------------------

class TestRegression:
    def test_contract_pack_still_accessible(self):
        """Existing contract-pack endpoint must not be broken by new endpoint."""
        with _ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        assert r.status_code == 200

    def test_contract_pack_includes_runtime_adapter_status_endpoint(self):
        """Contract pack must list the new runtime adapter status endpoint."""
        with _ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        paths = [ep["path"] for ep in body["endpoints"]]
        assert "/api/labgen/runtime/adapter-status" in paths

    def test_runtime_adapter_endpoint_is_admin_only_in_contract(self):
        """The new endpoint must be listed as admin auth in the contract."""
        with _ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        ep = next(
            (e for e in body["endpoints"] if e["path"] == "/api/labgen/runtime/adapter-status"),
            None,
        )
        assert ep is not None
        assert ep["auth"] == "admin"

    def test_runtime_adapter_endpoint_is_read_only_in_contract(self):
        with _ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        ep = next(
            (e for e in body["endpoints"] if e["path"] == "/api/labgen/runtime/adapter-status"),
            None,
        )
        assert ep is not None
        assert ep["is_read_only"] is True

    def test_runtime_adapter_endpoint_not_in_learner_facing_categories(self):
        """Must not appear in LEARNER_CATALOG, LEARNER_RUNTIME, or RUNTIME_ACTIONS."""
        with _ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        learner_categories = {"learner_catalog", "learner_runtime", "runtime_actions"}
        for ep in body["endpoints"]:
            if ep["path"] == "/api/labgen/runtime/adapter-status":
                assert ep["category"] not in learner_categories
