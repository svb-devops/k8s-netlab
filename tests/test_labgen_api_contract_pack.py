"""
Frontend Integration Contract Pack — Tests.

A. Contract pack API
   - admin can GET /api/labgen/contract-pack
   - non-admin → 403
   - response contains version, endpoints, example_responses, sensitive_field_policy
   - response contains no sensitive data
   - GET contract-pack does not mutate any business state

B. Endpoint inventory
   - contract endpoints are consistent with routes.py / OpenAPI actual paths
   - no phantom endpoints (listed in contract but missing from OpenAPI)
   - no missing core endpoints (present in OpenAPI but absent from contract)

C. OpenAPI sanity
   - OpenAPI JSON is generatable
   - core endpoints have response schemas
   - OpenAPI schema is JSON-serializable
   - no obvious sensitive example content in OpenAPI

D. Golden examples
   - key example response fields are stable
   - examples contain no sensitive data
   - examples do not include raw_model_output / hidden prompt / provider metadata
   - start eligibility example explicitly contains RUNTIME_CHECKS_DEFERRED

F. Regression
   - contract-pack API does not publish
   - contract-pack API does not start session
   - contract-pack API does not create session
   - contract-pack API does not create audit event
   - existing tests are unaffected (import-only regression)
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.api_contract import (
    ApiContractCategory,
    ApiContractPack,
    build_contract_pack,
)
from tests.labgen_contract_helpers import assert_contract_response_safe

pytestmark = pytest.mark.static


# ===========================================================================
# Test client context
# ===========================================================================


@contextmanager
def _contract_ctx(*, as_admin: bool = True):
    """Minimal context: only overrides auth — no business state."""
    from backend.main import app
    from backend.auth_deps import get_current_user
    from backend.labgen.routes import require_admin_user

    saved = dict(app.dependency_overrides)

    if as_admin:
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[get_current_user] = lambda: "admin"
    else:
        # Non-admin: get_current_user returns regular user; require_admin_user
        # is NOT overridden, so the real check runs and returns 403.
        app.dependency_overrides[get_current_user] = lambda: "student1"

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


# ===========================================================================
# A. Contract pack API
# ===========================================================================


class TestContractPackAPI:
    def test_admin_can_get_contract_pack(self):
        with _contract_ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == "v0.1"

    def test_non_admin_gets_403(self):
        with _contract_ctx(as_admin=False) as client:
            r = client.get("/api/labgen/contract-pack")
        assert r.status_code == 403

    def test_unauthenticated_gets_401_or_403(self):
        from backend.main import app

        saved = dict(app.dependency_overrides)
        client = TestClient(app, raise_server_exceptions=False)
        try:
            r = client.get("/api/labgen/contract-pack")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)
        assert r.status_code in (401, 403)

    def test_response_contains_required_fields(self):
        with _contract_ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        assert r.status_code == 200
        body = r.json()
        assert "version" in body
        assert "built_at" in body
        assert "endpoints" in body
        assert "example_responses" in body
        assert "sensitive_field_policy" in body
        assert "known_deferred_runtime_checks" in body
        assert "notes" in body

    def test_response_has_endpoints(self):
        with _contract_ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        assert len(body["endpoints"]) > 0

    def test_response_has_examples(self):
        with _contract_ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        assert len(body["example_responses"]) > 0

    def test_response_contains_no_sensitive_data(self):
        with _contract_ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        # sensitive_field_policy and notes intentionally name prohibited keywords
        # as part of their documentation — exclude them from the leaf-value check.
        # Only content fields (endpoints, example_responses) must be safe.
        content = {
            "endpoints": body.get("endpoints", []),
            "example_responses": body.get("example_responses", []),
        }
        assert_contract_response_safe(content)

    def test_sensitive_field_policy_is_present(self):
        with _contract_ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        policy = r.json()["sensitive_field_policy"]
        assert len(policy["prohibited_in_response_values"]) >= 5
        assert "enforcement_note" in policy
        assert policy["enforcement_note"]

    def test_known_deferred_checks_listed(self):
        with _contract_ctx(as_admin=True) as client:
            r = client.get("/api/labgen/contract-pack")
        body = r.json()
        checks = body["known_deferred_runtime_checks"]
        assert any("image" in c.lower() for c in checks), (
            "expected image TTL recheck to be listed as deferred"
        )

    def test_get_does_not_create_session(self):
        """GET contract-pack must not create any sessions."""
        from backend.labgen.lab_session_repository import LabSessionRepository
        from backend.labgen.routes import get_session_repository

        class _SpyRepo:
            create_called = False

            def create(self, s):
                _SpyRepo.create_called = True
                return s

            def get(self, sid):
                return None

            def update(self, s):
                return s

            def list_by_student(self, u):
                return []

        from backend.main import app
        from backend.labgen.routes import require_admin_user

        saved = dict(app.dependency_overrides)
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[get_session_repository] = lambda: _SpyRepo()

        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/labgen/contract-pack")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

        assert r.status_code == 200
        assert not _SpyRepo.create_called

    def test_get_does_not_publish_draft(self):
        """GET contract-pack must not publish any draft."""
        from backend.labgen.publish_service import PublishService
        from backend.labgen.routes import get_publish_service

        class _SpyPublishService:
            publish_called = False

            def publish(self, lab_id):
                _SpyPublishService.publish_called = True
                raise RuntimeError("should not be called")

        from backend.main import app
        from backend.labgen.routes import require_admin_user

        saved = dict(app.dependency_overrides)
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[get_publish_service] = lambda: _SpyPublishService()

        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/labgen/contract-pack")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

        assert r.status_code == 200
        assert not _SpyPublishService.publish_called

    def test_get_does_not_create_audit_event(self):
        """GET contract-pack must not write any audit event."""
        from backend.labgen.runtime_audit import RuntimeAuditRepository
        from backend.labgen.routes import get_audit_repository

        class _SpyAuditRepo:
            append_called = False

            def append(self, event):
                _SpyAuditRepo.append_called = True
                raise RuntimeError("should not be called")

            def list_by_session(self, sid):
                return []

        from backend.main import app
        from backend.labgen.routes import require_admin_user

        saved = dict(app.dependency_overrides)
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[get_audit_repository] = lambda: _SpyAuditRepo()

        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/labgen/contract-pack")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

        assert r.status_code == 200
        assert not _SpyAuditRepo.append_called


# ===========================================================================
# B. Endpoint inventory
# ===========================================================================


class TestEndpointInventory:
    """Contract pack endpoints must match actual routes in the app."""

    @pytest.fixture(scope="class")
    def openapi(self):
        from backend.main import app

        saved = dict(app.dependency_overrides)
        try:
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/openapi.json")
            assert r.status_code == 200
            return r.json()
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

    def _openapi_route_set(self, openapi: dict) -> set[tuple[str, str]]:
        """Return set of (normalized_path, METHOD) from OpenAPI paths."""
        routes: set[tuple[str, str]] = set()
        for path, methods in openapi.get("paths", {}).items():
            for method in methods:
                if method.lower() in ("get", "post", "patch", "put", "delete"):
                    routes.add((path, method.upper()))
        return routes

    def test_all_contract_endpoints_exist_in_openapi(self, openapi):
        """No phantom endpoints — every contract endpoint must appear in OpenAPI."""
        pack = build_contract_pack()
        routes = self._openapi_route_set(openapi)

        missing = []
        for ep in pack.endpoints:
            if (ep.path, ep.method) not in routes:
                missing.append(f"{ep.method} {ep.path}")

        assert not missing, (
            f"Contract endpoints not found in OpenAPI: {missing}\n"
            "Check that routes.py registers these paths."
        )

    def test_core_endpoints_present_in_contract(self):
        """Core endpoints from routes.py must appear in the contract."""
        pack = build_contract_pack()
        paths = {(ep.path, ep.method) for ep in pack.endpoints}

        required = [
            ("/api/lab-drafts/generate", "POST"),
            ("/api/labgen/drafts/{lab_id}/preview", "GET"),
            ("/api/labgen/drafts/{lab_id}/publish-decision", "GET"),
            ("/api/labgen/drafts/{lab_id}/publish", "POST"),
            ("/api/labs", "GET"),
            ("/api/labs/{lab_id}", "GET"),
            ("/api/labs/{lab_id}/start-eligibility", "GET"),
            ("/api/lab-sessions", "GET"),
            ("/api/lab-sessions/{session_id}/snapshot", "GET"),
            ("/api/lab-sessions", "POST"),
            ("/api/lab-sessions/{session_id}/steps/{step_id}/check", "POST"),
            ("/api/lab-sessions/{session_id}/complete", "POST"),
            ("/api/lab-sessions/{session_id}/abort", "POST"),
            ("/api/lab-sessions/{session_id}/audit-events", "GET"),
        ]
        missing = [f"{m} {p}" for p, m in required if (p, m) not in paths]
        assert not missing, f"Core endpoints missing from contract: {missing}"

    def test_all_categories_covered(self):
        pack = build_contract_pack()
        covered = {ep.category for ep in pack.endpoints}
        required = set(ApiContractCategory)
        assert required.issubset(covered), (
            f"Missing categories: {required - covered}"
        )

    def test_no_internal_endpoints_in_contract(self):
        """Internal-only routes must not appear in the frontend contract."""
        pack = build_contract_pack()
        for ep in pack.endpoints:
            assert not ep.path.startswith("/internal/"), (
                f"Internal route {ep.path!r} should not be in the frontend contract"
            )

    def test_all_endpoints_have_response_model(self):
        pack = build_contract_pack()
        for ep in pack.endpoints:
            assert ep.response_model, f"{ep.method} {ep.path} has no response_model"

    def test_all_endpoints_have_tags(self):
        pack = build_contract_pack()
        for ep in pack.endpoints:
            assert ep.tags, f"{ep.method} {ep.path} has no tags"

    def test_response_model_classes_exist_in_backend(self):
        """Every response_model string must resolve to a real Pydantic class in the backend.
        Catches silent failures when a model is renamed without updating the contract pack."""
        import inspect
        import importlib
        from pydantic import BaseModel

        _MODULES = [
            "backend.labgen.models",
            "backend.labgen.llm_generation",
            "backend.labgen.draft_preview",
            "backend.labgen.publish_decision",
            "backend.labgen.learner_catalog",
            "backend.labgen.learner_session_snapshot",
            "backend.labgen.runtime_audit",
            "backend.labgen.step_progression_service",
        ]
        known: dict[str, type] = {}
        for mod_name in _MODULES:
            mod = importlib.import_module(mod_name)
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(obj, BaseModel):
                    known[name] = obj

        pack = build_contract_pack()
        unresolved = []
        for ep in pack.endpoints:
            raw = ep.response_model
            # strip list[...] wrapper
            class_name = raw[5:-1] if raw.startswith("list[") and raw.endswith("]") else raw
            if class_name not in known:
                unresolved.append(f"{ep.method} {ep.path} → '{raw}'")

        assert not unresolved, (
            "Contract response_model strings do not resolve to Pydantic classes:\n"
            + "\n".join(unresolved)
            + "\nUpdate api_contract.py if a model was renamed."
        )

    def test_response_model_matches_openapi_schema_ref(self, openapi):
        """For each contract endpoint the declared response_model must match the actual
        OpenAPI $ref. Catches divergence between the contract documentation and reality."""
        pack = build_contract_pack()
        oapi_paths = openapi.get("paths", {})

        mismatches = []
        for ep in pack.endpoints:
            op = oapi_paths.get(ep.path, {}).get(ep.method.lower(), {})
            if not op:
                continue  # already caught by test_all_contract_endpoints_exist_in_openapi

            # Determine the expected bare class name (strip list[...])
            raw = ep.response_model
            is_list = raw.startswith("list[") and raw.endswith("]")
            expected_class = raw[5:-1] if is_list else raw

            # Find the $ref in the 2xx response content schema
            responses = op.get("responses", {})
            resp_body = responses.get("200") or responses.get("201") or {}
            content = resp_body.get("content", {}).get("application/json", {})
            schema = content.get("schema", {})

            if is_list:
                ref = schema.get("items", {}).get("$ref", "")
            else:
                ref = schema.get("$ref", "")
                if not ref:
                    # FastAPI sometimes wraps in allOf for response models
                    allof = schema.get("allOf", [])
                    ref = allof[0].get("$ref", "") if allof else ""

            if not ref:
                continue  # schema structure not verifiable (e.g. inline/primitive)

            actual_class = ref.split("/")[-1]
            if actual_class != expected_class:
                mismatches.append(
                    f"{ep.method} {ep.path}: contract declares '{raw}' "
                    f"but OpenAPI schema ref is '{actual_class}'"
                )

        assert not mismatches, (
            "Contract response_model diverges from actual OpenAPI schema:\n"
            + "\n".join(mismatches)
            + "\nUpdate api_contract.py response_model strings to match the real models."
        )

    def test_contract_has_all_five_categories(self):
        pack = build_contract_pack()
        categories = {ep.category for ep in pack.endpoints}
        assert ApiContractCategory.GENERATION in categories
        assert ApiContractCategory.ADMIN_REVIEW in categories
        assert ApiContractCategory.LEARNER_CATALOG in categories
        assert ApiContractCategory.LEARNER_RUNTIME in categories
        assert ApiContractCategory.RUNTIME_ACTIONS in categories


# ===========================================================================
# C. OpenAPI sanity
# ===========================================================================


class TestOpenAPISanity:

    @pytest.fixture(scope="class")
    def openapi(self):
        from backend.main import app

        saved = dict(app.dependency_overrides)
        try:
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/openapi.json")
            assert r.status_code == 200
            return r.json()
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

    def test_openapi_is_json_serializable(self, openapi):
        json.dumps(openapi)

    def test_openapi_has_paths(self, openapi):
        assert "paths" in openapi
        assert len(openapi["paths"]) > 0

    def test_core_endpoints_have_schema(self, openapi):
        """Each core endpoint path must appear in OpenAPI paths."""
        core_paths = [
            "/api/lab-drafts/generate",
            "/api/labgen/drafts/{lab_id}/preview",
            "/api/labgen/drafts/{lab_id}/publish-decision",
            "/api/labgen/drafts/{lab_id}/publish",
            "/api/labs",
            "/api/labs/{lab_id}",
            "/api/labs/{lab_id}/start-eligibility",
            "/api/lab-sessions/{session_id}/snapshot",
            "/api/lab-sessions/{session_id}/steps/{step_id}/check",
            "/api/lab-sessions/{session_id}/complete",
            "/api/lab-sessions/{session_id}/abort",
            "/api/lab-sessions/{session_id}/audit-events",
        ]
        paths = openapi.get("paths", {})
        missing = [p for p in core_paths if p not in paths]
        assert not missing, f"Core paths missing from OpenAPI: {missing}"

    def test_contract_pack_endpoint_in_openapi(self, openapi):
        paths = openapi.get("paths", {})
        assert "/api/labgen/contract-pack" in paths

    def test_core_endpoints_have_response_definitions(self, openapi):
        """POST /api/lab-drafts/generate must have a 201 response definition."""
        path_def = openapi["paths"].get("/api/lab-drafts/generate", {})
        post_def = path_def.get("post", {})
        responses = post_def.get("responses", {})
        assert "201" in responses or "200" in responses, (
            "POST /api/lab-drafts/generate should have a 2xx response schema"
        )

    def test_openapi_schema_has_components(self, openapi):
        """Schemas must be present for model types."""
        assert "components" in openapi or "definitions" in openapi

    def test_openapi_contains_no_obvious_secrets(self, openapi):
        """OpenAPI spec must not contain obvious credential examples."""
        spec_str = json.dumps(openapi).lower()
        assert "password123" not in spec_str
        assert "mysecret" not in spec_str
        assert "apikey" not in spec_str
        # JWT / Bearer pattern check on the raw spec string
        import re
        bearer_pat = re.compile(r"bearer\s+[a-za-z0-9._=+/\-]{8,}", re.IGNORECASE)
        assert not bearer_pat.search(spec_str), "Possible Bearer token in OpenAPI spec"


# ===========================================================================
# D. Golden examples
# ===========================================================================


class TestGoldenExamples:

    @pytest.fixture(scope="class")
    def pack(self) -> ApiContractPack:
        return build_contract_pack()

    def _example(self, pack: ApiContractPack, name: str) -> dict:
        for ex in pack.example_responses:
            if ex.name == name:
                return ex.response
        raise KeyError(f"Example {name!r} not found")

    def test_all_examples_no_sensitive_data(self, pack):
        for ex in pack.example_responses:
            # ex.response is the actual payload — check for data leaks
            assert_contract_response_safe(ex.response), f"Example {ex.name!r} has sensitive data"

    def test_generate_success_has_required_fields(self, pack):
        ex = self._example(pack, "generate_draft_success_with_template")
        assert "draft_id" in ex
        assert ex["validation_status"] == "passed"
        assert "selected_template_id" in ex
        assert ex["selected_template_id"] is not None
        assert "repair_attempted" in ex
        assert ex["repair_attempted"] is False

    def test_generate_repair_example_has_repair_applied(self, pack):
        ex = self._example(pack, "generate_draft_with_repair_result")
        assert ex["repair_applied"] is True
        assert ex["repair_attempted"] is True
        repair = ex["repair_result"]
        assert repair is not None
        assert repair["repair_applied"] is True

    def test_generate_examples_no_raw_model_output(self, pack):
        for ex in pack.example_responses:
            if ex.category == ApiContractCategory.GENERATION:
                assert "raw_model_output" not in ex.response
                assert "hidden_prompt" not in ex.response
                assert "provider_metadata" not in ex.response

    def test_preview_snapshot_fields(self, pack):
        ex = self._example(pack, "preview_snapshot")
        assert "draft_id" in ex
        assert "title" in ex
        assert "publish_status" in ex
        assert "validation_status" in ex
        assert "is_publishable" in ex
        assert ex["is_publishable"] is True

    def test_publish_decision_allowed_fields(self, pack):
        ex = self._example(pack, "publish_decision_allowed")
        assert ex["status"] == "ALLOWED"
        assert ex["is_publishable"] is True
        assert ex["issues"] == []

    def test_publish_decision_blocked_has_issues(self, pack):
        ex = self._example(pack, "publish_decision_blocked")
        assert ex["status"] == "BLOCKED"
        assert ex["is_publishable"] is False
        assert len(ex["issues"]) > 0
        assert any(i["code"] == "VALIDATION_FAILED" for i in ex["issues"])

    def test_catalog_item_fields(self, pack):
        ex = self._example(pack, "learner_catalog_item")
        assert "lab_id" in ex
        assert "title" in ex
        assert "summary" in ex
        assert "is_startable" in ex
        assert isinstance(ex["step_count"], int)
        assert isinstance(ex["objective_count"], int)

    def test_lab_detail_has_steps_preview(self, pack):
        ex = self._example(pack, "learner_lab_detail")
        assert "steps_preview" in ex
        assert len(ex["steps_preview"]) > 0
        step = ex["steps_preview"][0]
        assert "step_id" in step
        assert "check_count" in step

    def test_start_eligibility_contains_runtime_checks_deferred(self, pack):
        """is_startable=true but RUNTIME_CHECKS_DEFERRED warning must be present."""
        ex = self._example(pack, "start_eligibility_with_runtime_checks_deferred")
        assert ex["is_startable"] is True
        codes = [i["code"] for i in ex["issues"]]
        assert "RUNTIME_CHECKS_DEFERRED" in codes, (
            "start_eligibility example must include RUNTIME_CHECKS_DEFERRED warning"
        )

    def test_session_snapshot_active_fields(self, pack):
        ex = self._example(pack, "learner_session_snapshot_active")
        assert ex["session_state"] == "LAB_ACTIVE"
        assert ex["runtime_summary"]["ready_to_complete"] is False
        assert ex["action_availability"]["can_abort"] is True
        assert ex["action_availability"]["can_complete"] is False
        assert ex["current_step_id"] is not None

    def test_session_snapshot_ready_to_complete(self, pack):
        ex = self._example(pack, "learner_session_snapshot_ready_to_complete")
        assert ex["session_state"] == "LAB_ACTIVE"
        assert ex["runtime_summary"]["ready_to_complete"] is True
        assert ex["action_availability"]["can_complete"] is True
        assert ex["current_step_id"] is None

    def test_session_snapshots_no_kubeconfig_or_vm_id(self, pack):
        for ex in pack.example_responses:
            if "snapshot" in ex.name and "session" in ex.name:
                r = ex.response
                assert "vm_id" not in r
                assert "namespace" not in r

    def test_audit_events_list_fields(self, pack):
        ex = self._example(pack, "audit_events_list")
        assert isinstance(ex, list)
        assert len(ex) >= 2
        event = ex[0]
        assert "event_type" in event
        assert "session_id" in event
        assert "timestamp" in event

    def test_examples_are_deterministic(self):
        pack1 = build_contract_pack()
        pack2 = build_contract_pack()
        for e1, e2 in zip(pack1.example_responses, pack2.example_responses):
            assert e1.name == e2.name
            assert e1.response == e2.response

    def test_all_five_categories_have_examples(self, pack):
        cats = {ex.category for ex in pack.example_responses}
        assert ApiContractCategory.GENERATION in cats
        assert ApiContractCategory.ADMIN_REVIEW in cats
        assert ApiContractCategory.LEARNER_CATALOG in cats
        assert ApiContractCategory.LEARNER_RUNTIME in cats
        assert ApiContractCategory.RUNTIME_ACTIONS in cats


# ===========================================================================
# F. Regression
# ===========================================================================


class TestRegression:

    def test_contract_pack_model_is_importable(self):
        from backend.labgen.api_contract import ApiContractPack, build_contract_pack  # noqa: F401

    def test_build_contract_pack_is_pure(self):
        """build_contract_pack must return valid Pydantic model without errors."""
        pack = build_contract_pack()
        assert isinstance(pack, ApiContractPack)

    def test_contract_pack_is_json_serializable(self):
        pack = build_contract_pack()
        data = pack.model_dump(mode="json")
        json.dumps(data)  # must not raise

    def test_existing_learner_catalog_importable(self):
        from backend.labgen.learner_catalog import LearnerCatalogService  # noqa: F401

    def test_existing_learner_snapshot_importable(self):
        from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService  # noqa: F401

    def test_existing_publish_decision_importable(self):
        from backend.labgen.publish_decision import PublishDecisionService  # noqa: F401

    def test_existing_draft_preview_importable(self):
        from backend.labgen.draft_preview import DraftPreviewService  # noqa: F401

    def test_contract_pack_endpoint_count(self):
        """Endpoint count must match the number of declared routes."""
        pack = build_contract_pack()
        # 14 endpoints: 1 generate + 3 admin_review + 3 learner_catalog +
        # 2 learner_runtime + 5 runtime_actions
        assert len(pack.endpoints) == 14

    def test_contract_pack_example_count(self):
        pack = build_contract_pack()
        # 11 examples as declared
        assert len(pack.example_responses) == 11
