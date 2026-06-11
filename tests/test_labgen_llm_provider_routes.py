"""
LLM Provider Boundary Hardening v0.1 — route tests.

Coverage areas:
  D. Provider diagnostics API (GET /api/labgen/llm-provider/status)
  D2. Provider dry-run API (POST /api/labgen/llm-provider/dry-run)
  E. Contract pack — provider endpoints registered, sensitive policy updated
  G. Regression — existing tests unaffected
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.labgen.llm_provider_boundary import (
    DryRunLLMProviderAdapter,
    LLMProviderBoundaryService,
    LLMProviderConfig,
    LLMProviderMode,
    LLMProviderName,
)
from backend.labgen.routes import get_llm_provider_service, require_admin_user
from backend.auth_deps import get_current_user

pytestmark = pytest.mark.static


def _make_app_with_overrides(*, as_admin: bool = True, svc=None):
    from contextlib import contextmanager

    from backend.main import app

    @contextmanager
    def _ctx():
        saved = dict(app.dependency_overrides)
        try:
            if as_admin:
                app.dependency_overrides[require_admin_user] = lambda: "admin"
                app.dependency_overrides[get_current_user] = lambda: "admin"
            else:
                app.dependency_overrides[get_current_user] = lambda: "student1"
                # do NOT override require_admin_user so it can reject the request

            if svc is not None:
                app.dependency_overrides[get_llm_provider_service] = lambda: svc
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

    return _ctx()


def _default_fake_svc():
    return LLMProviderBoundaryService(
        config=LLMProviderConfig(mode=LLMProviderMode.FAKE_ONLY)
    )


def _dry_run_svc(inject_mode: str = "valid_candidate"):
    return LLMProviderBoundaryService(
        config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
        dry_run_adapter=DryRunLLMProviderAdapter(inject_mode=inject_mode),
    )


# ---------------------------------------------------------------------------
# D. Provider status endpoint
# ---------------------------------------------------------------------------


class TestProviderStatusEndpoint:
    def test_admin_can_get_status(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        assert r.status_code == 200

    def test_non_admin_forbidden(self):
        with _make_app_with_overrides(as_admin=False) as client:
            r = client.get("/api/labgen/llm-provider/status")
        assert r.status_code == 403

    def test_response_contains_provider_name(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        body = r.json()
        assert body["provider_name"] == "fake"

    def test_response_contains_mode(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        body = r.json()
        assert body["mode"] == "fake_only"

    def test_live_enabled_always_false(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        body = r.json()
        assert body["live_enabled"] is False

    def test_dry_run_available_false_for_fake_only(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        body = r.json()
        assert body["dry_run_available"] is False

    def test_dry_run_available_true_for_dry_run_mode(self):
        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN)
        )
        with _make_app_with_overrides(as_admin=True, svc=svc) as client:
            r = client.get("/api/labgen/llm-provider/status")
        body = r.json()
        assert body["dry_run_available"] is True

    def test_response_contains_safety_policy_summary(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        body = r.json()
        assert "safety_policy_summary" in body
        assert len(body["safety_policy_summary"]) > 0

    def test_response_has_no_api_key(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        text = r.text.lower()
        assert "sk-" not in text
        assert "api_key" not in text or '"api_key"' not in text  # field name allowed, value must be absent

    def test_response_has_no_raw_output(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        assert "raw_model_output" not in r.text
        assert "chain_of_thought" not in r.text
        assert "hidden_prompt" not in r.text

    def test_disabled_mode_adds_warning(self):
        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DISABLED)
        )
        with _make_app_with_overrides(as_admin=True, svc=svc) as client:
            r = client.get("/api/labgen/llm-provider/status")
        body = r.json()
        assert len(body["warnings"]) > 0

    def test_response_schema_stable(self):
        with _make_app_with_overrides(as_admin=True, svc=_default_fake_svc()) as client:
            r = client.get("/api/labgen/llm-provider/status")
        body = r.json()
        required_fields = {
            "provider_name", "mode", "live_enabled", "dry_run_available",
            "timeout_ms", "max_output_tokens", "safety_policy_summary", "warnings",
            "generation_supported", "repair_supported", "config_issues",
        }
        assert required_fields.issubset(body.keys())


# ---------------------------------------------------------------------------
# D2. Provider dry-run endpoint
# ---------------------------------------------------------------------------


class TestProviderDryRunEndpoint:
    def test_admin_can_run_dry_run(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "k8s lab test"},
            )
        assert r.status_code == 200

    def test_non_admin_forbidden(self):
        with _make_app_with_overrides(as_admin=False) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "k8s lab test"},
            )
        assert r.status_code == 403

    def test_valid_candidate_mode_returns_candidate_json(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "k8s lab test", "inject_mode": "valid_candidate"},
            )
        body = r.json()
        assert body["candidate_json"] is not None
        assert body["rejected_reason"] is None

    def test_provider_disabled_returns_rejected_reason(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "test", "inject_mode": "provider_disabled"},
            )
        body = r.json()
        assert body["rejected_reason"] == "provider_disabled"
        assert body["candidate_json"] is None

    def test_safety_rejection_returns_rejected_reason(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "test", "inject_mode": "safety_rejection"},
            )
        body = r.json()
        assert body["rejected_reason"] == "safety_policy_rejected"

    def test_timeout_mode_returns_timeout_simulated(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "test", "inject_mode": "timeout"},
            )
        body = r.json()
        assert body["rejected_reason"] == "timeout_simulated"

    def test_invalid_inject_mode_rejected_422(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "test", "inject_mode": "not_a_real_mode"},
            )
        assert r.status_code == 422

    def test_response_has_no_raw_output(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "test", "inject_mode": "valid_candidate"},
            )
        assert "raw_model_output" not in r.text
        assert "chain_of_thought" not in r.text
        assert "hidden_prompt" not in r.text

    def test_sensitive_output_warnings_redacted_in_response(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "test", "inject_mode": "sensitive_output"},
            )
        text = r.text
        assert "sk-abcde" not in text
        assert "eyJhbGci" not in text

    def test_response_does_not_create_draft(self):
        """dry-run must not persist any draft to the repository."""
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.routes import get_repository

        created = []

        class _SpyRepo(LabDraftRepository):
            def __init__(self):
                self._path = None

            def create(self, draft):
                created.append(draft)
                return draft

        from backend.main import app

        saved = dict(app.dependency_overrides)
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[get_current_user] = lambda: "admin"
        app.dependency_overrides[get_repository] = lambda: _SpyRepo()
        client = TestClient(app)
        try:
            client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "k8s test", "inject_mode": "valid_candidate"},
            )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

        assert len(created) == 0, "dry-run must not call repo.create"

    def test_response_schema_stable(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/labgen/llm-provider/dry-run",
                json={"sanitized_prompt": "test", "inject_mode": "provider_disabled"},
            )
        body = r.json()
        required = {"provider_name", "mode", "candidate_json", "warnings", "usage_summary", "rejected_reason"}
        assert required.issubset(body.keys())


# ---------------------------------------------------------------------------
# E. Contract pack includes provider endpoints
# ---------------------------------------------------------------------------


class TestContractPackProviderEndpoints:
    def test_provider_status_endpoint_in_contract(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        paths = [e["path"] for e in body["endpoints"]]
        assert "/api/labgen/llm-provider/status" in paths

    def test_provider_dry_run_endpoint_in_contract(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        paths = [e["path"] for e in body["endpoints"]]
        assert "/api/labgen/llm-provider/dry-run" in paths

    def test_provider_status_endpoint_is_admin_only(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        status_ep = next(
            (e for e in body["endpoints"] if e["path"] == "/api/labgen/llm-provider/status"),
            None,
        )
        assert status_ep is not None
        assert status_ep["auth"] == "admin"
        assert status_ep["is_read_only"] is True

    def test_provider_dry_run_is_not_read_only(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        dry_run_ep = next(
            (e for e in body["endpoints"] if e["path"] == "/api/labgen/llm-provider/dry-run"),
            None,
        )
        assert dry_run_ep is not None
        assert dry_run_ep["is_read_only"] is False

    def test_sensitive_policy_includes_api_key(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        prohibited = body["sensitive_field_policy"]["prohibited_in_response_values"]
        assert "api_key" in prohibited

    def test_sensitive_policy_includes_chain_of_thought(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        prohibited = body["sensitive_field_policy"]["prohibited_in_response_values"]
        assert "chain_of_thought" in prohibited

    def test_provider_status_example_in_contract_examples(self):
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        names = [e["name"] for e in body["example_responses"]]
        assert "llm_provider_status" in names

    def test_contract_examples_no_sensitive_data(self):
        """Contract pack examples must not contain API keys or raw output."""
        from tests.labgen_contract_helpers import assert_contract_response_safe

        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        content = {
            "endpoints": body.get("endpoints", []),
            "example_responses": body.get("example_responses", []),
        }
        assert_contract_response_safe(content)

    def test_learner_facing_contract_has_no_provider_internals(self):
        """Provider endpoints must not appear in learner_catalog or learner_runtime."""
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        learner_eps = [
            e for e in body["endpoints"]
            if e["category"] in ("learner_catalog", "learner_runtime")
        ]
        for ep in learner_eps:
            assert "llm-provider" not in ep["path"]


# ---------------------------------------------------------------------------
# G. Regression: existing API unchanged
# ---------------------------------------------------------------------------


class TestRegressionExistingAPI:
    def test_generate_endpoint_still_works(self):
        """POST /api/lab-drafts/generate must still return 201 with default fake adapter."""
        from backend.labgen.routes import get_generation_service, get_repair_port

        with _make_app_with_overrides(as_admin=True) as client:
            r = client.post(
                "/api/lab-drafts/generate",
                json={"user_prompt": "k8s regression test"},
            )
        assert r.status_code == 201
        body = r.json()
        assert body["draft_id"] is not None

    def test_contract_pack_still_has_correct_example_count(self):
        """Contract pack must have at least 18 examples (13 original + 2 boundary hardening + 3 live provider)."""
        with _make_app_with_overrides(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        assert len(body["example_responses"]) >= 18
