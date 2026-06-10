"""
Demo Scenario Seed Pack v0.1 — backend tests.

Coverage areas:
  A. Seed API (HTTP layer)
  B. Idempotency
  C. Scenario correctness
  D. Image readiness scenarios (BLOCKED / UNRESOLVED / NOT_FOUND)
  E. Safety (no sensitive data)
  F. Regression (no Contract v0.1 modifications, no audit event types added)
"""
from __future__ import annotations

import re
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.demo_seed import (
    ALL_DEMO_SCENARIOS,
    DEMO_DRAFT_ID_DATA_BLOCKED,
    DEMO_DRAFT_ID_HTTP,
    DEMO_DRAFT_ID_HTTP_NOT_FOUND,
    DEMO_DRAFT_ID_PYTHON,
    DEMO_DRAFT_ID_PYTHON_UNRESOLVED,
    DEMO_SESSION_ID_ACTIVE,
    DEMO_SESSION_ID_CLEANUP_FAILED,
    DEMO_SESSION_ID_READY,
    DEMO_STUDENT_USERNAME,
    DEMO_VM_ID,
    DemoSeedScenarioId,
    DemoSeedService,
)
from backend.labgen.models import (
    ImageStatus,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
)
from backend.labgen.repository import LabDraftRepository
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.routes import (
    get_repository,
    get_session_repository,
    get_preview_service,
    get_snapshot_service,
    require_admin_user,
)
from backend.auth_deps import get_current_user
from backend.labgen.draft_preview import DraftPreviewService
from backend.labgen.image_readiness import ImageReadinessService, ImageReadinessStatus
from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Sensitive data patterns (must never appear in any response)
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = [
    r"-----BEGIN",               # PEM key
    r"kubeconfig",               # kubeconfig material
    r"token\s*:",                # token fields
    r"password\s*:",             # password
    r"private_key",              # private key
    r"client-key-data",          # kubeconfig key
    r"raw_model_output",         # LLM raw output
    r"hidden_prompt",            # hidden prompt
    r"provider_metadata",        # provider metadata
]

_COMPILED_SENSITIVE = [re.compile(p, re.IGNORECASE) for p in _SENSITIVE_PATTERNS]


def _assert_no_sensitive(data: dict | list | str, context: str = "") -> None:
    text = str(data)
    for pat in _COMPILED_SENSITIVE:
        assert not pat.search(text), (
            f"Sensitive pattern '{pat.pattern}' found in response{f' ({context})' if context else ''}"
        )


# ---------------------------------------------------------------------------
# In-memory repositories
# ---------------------------------------------------------------------------


class _MemDraftRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def delete(self, lab_id: str) -> None:
        self._store.pop(lab_id, None)

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemSessionRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabSessionState] = {}

    def create(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._store.get(session_id)

    def update(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def list_by_student(self, student_username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == student_username]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def draft_repo() -> _MemDraftRepo:
    return _MemDraftRepo()


@pytest.fixture()
def session_repo() -> _MemSessionRepo:
    return _MemSessionRepo()


@pytest.fixture()
def seed_svc(draft_repo, session_repo) -> DemoSeedService:
    return DemoSeedService(draft_repo=draft_repo, session_repo=session_repo)


@pytest.fixture()
def admin_client(draft_repo, session_repo):
    from backend.main import app

    preview_svc = DraftPreviewService(
        repo=draft_repo,
        validator=StaticValidator(),
        image_readiness_svc=ImageReadinessService(),
    )
    snapshot_svc = LearnerSessionSnapshotService(
        session_repo=session_repo, draft_repo=draft_repo
    )

    app.dependency_overrides[get_repository] = lambda: draft_repo
    app.dependency_overrides[get_session_repository] = lambda: session_repo
    app.dependency_overrides[require_admin_user] = lambda: "testadmin"
    # Learner-facing endpoints (catalog, session snapshot) use get_current_user.
    # Use the demo student username so session ownership check passes without real auth.
    app.dependency_overrides[get_current_user] = lambda: DEMO_STUDENT_USERNAME
    # get_preview_service is a module-level singleton; must override so draft_repo propagates
    app.dependency_overrides[get_preview_service] = lambda: preview_svc
    # get_snapshot_service creates LabSessionRepository() directly; override to propagate repo
    app.dependency_overrides[get_snapshot_service] = lambda: snapshot_svc
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def non_admin_client(draft_repo, session_repo):
    from backend.main import app

    app.dependency_overrides[get_repository] = lambda: draft_repo
    app.dependency_overrides[get_session_repository] = lambda: session_repo
    app.dependency_overrides[get_current_user] = lambda: "regularuser"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client(draft_repo, session_repo):
    from backend.main import app

    app.dependency_overrides[get_repository] = lambda: draft_repo
    app.dependency_overrides[get_session_repository] = lambda: session_repo
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


# ===========================================================================
# A. Seed API
# ===========================================================================


class TestSeedApi:
    def test_admin_can_seed_all_defaults(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={})
        assert r.status_code == 200
        body = r.json()
        assert set(body["seeded_scenarios"]) == {s.value for s in ALL_DEMO_SCENARIOS}
        assert DEMO_DRAFT_ID_PYTHON in body["created_or_updated_draft_ids"]
        assert DEMO_DRAFT_ID_HTTP in body["created_or_updated_draft_ids"]
        assert DEMO_DRAFT_ID_DATA_BLOCKED in body["created_or_updated_draft_ids"]
        assert DEMO_DRAFT_ID_PYTHON_UNRESOLVED in body["created_or_updated_draft_ids"]
        assert DEMO_DRAFT_ID_HTTP_NOT_FOUND in body["created_or_updated_draft_ids"]
        assert DEMO_SESSION_ID_ACTIVE in body["created_or_updated_session_ids"]
        assert DEMO_SESSION_ID_READY in body["created_or_updated_session_ids"]
        assert DEMO_SESSION_ID_CLEANUP_FAILED in body["created_or_updated_session_ids"]

    def test_non_admin_forbidden(self, non_admin_client):
        r = non_admin_client.post("/api/labgen/demo/seed", json={})
        assert r.status_code == 403

    def test_response_schema_stable(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={})
        assert r.status_code == 200
        body = r.json()
        assert "seeded_scenarios" in body
        assert "created_or_updated_draft_ids" in body
        assert "created_or_updated_lab_ids" in body
        assert "created_or_updated_session_ids" in body
        assert "warnings" in body
        assert "next_steps" in body
        assert "checked_at" in body

    def test_response_contains_no_sensitive_data(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={})
        assert r.status_code == 200
        _assert_no_sensitive(r.json(), "seed response")

    def test_next_steps_contain_valid_paths(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={})
        body = r.json()
        for step in body["next_steps"]:
            assert "label" in step
            assert "path" in step
            assert step["path"].startswith("/")

    def test_select_subset_of_scenarios(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={
            "scenarios": ["PYTHON_BASICS_PUBLISHED", "HTTP_API_BASICS_PUBLISHED"]
        })
        assert r.status_code == 200
        body = r.json()
        assert set(body["seeded_scenarios"]) == {"PYTHON_BASICS_PUBLISHED", "HTTP_API_BASICS_PUBLISHED"}
        assert DEMO_DRAFT_ID_DATA_BLOCKED not in body["created_or_updated_draft_ids"]

    def test_include_runtime_sessions_false(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={
            "include_runtime_sessions": False
        })
        assert r.status_code == 200
        body = r.json()
        assert body["created_or_updated_session_ids"] == []
        assert DEMO_SESSION_ID_ACTIVE not in body["seeded_scenarios"]

    def test_does_not_return_raw_draft_fields(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={})
        body = r.json()
        # Response must not contain raw draft model output fields
        assert "steps" not in body
        assert "validator_results" not in body
        assert "runtime_requirements" not in body

    def test_does_not_return_runtime_internals(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={})
        body = r.json()
        # Must not leak session internal fields
        assert "namespace" not in body
        assert "vm_id" not in body
        assert "lab_session_status" not in body


# ===========================================================================
# B. Idempotency
# ===========================================================================


class TestIdempotency:
    def test_repeated_seed_does_not_duplicate_catalog_items(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        admin_client.post("/api/labgen/demo/seed", json={})
        # Only one entry per demo ID in repo
        all_drafts = draft_repo.list_all()
        ids = [d.lab_id for d in all_drafts]
        assert ids.count(DEMO_DRAFT_ID_PYTHON) == 1
        assert ids.count(DEMO_DRAFT_ID_HTTP) == 1
        assert ids.count(DEMO_DRAFT_ID_DATA_BLOCKED) == 1
        assert ids.count(DEMO_DRAFT_ID_PYTHON_UNRESOLVED) == 1
        assert ids.count(DEMO_DRAFT_ID_HTTP_NOT_FOUND) == 1

    def test_repeated_seed_does_not_duplicate_sessions(self, admin_client, session_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        admin_client.post("/api/labgen/demo/seed", json={})
        sessions = session_repo.list_by_student(DEMO_STUDENT_USERNAME)
        ids = [s.session_id for s in sessions]
        assert ids.count(DEMO_SESSION_ID_ACTIVE) == 1
        assert ids.count(DEMO_SESSION_ID_READY) == 1
        assert ids.count(DEMO_SESSION_ID_CLEANUP_FAILED) == 1

    def test_reset_true_replaces_demo_records(self, seed_svc, draft_repo):
        # First seed
        seed_svc.seed()
        original = draft_repo.get(DEMO_DRAFT_ID_PYTHON)
        assert original is not None

        # Second seed with reset=True — should result in exactly one record
        seed_svc.seed(reset=True)
        all_drafts = draft_repo.list_all()
        ids = [d.lab_id for d in all_drafts]
        assert ids.count(DEMO_DRAFT_ID_PYTHON) == 1

    def test_reset_does_not_affect_non_demo_records(self, seed_svc, draft_repo):
        from backend.labgen.generation_templates import GenerationTemplateId, GenerationTemplateRegistry

        # Create a non-demo draft
        reg = GenerationTemplateRegistry()
        template = reg.get_by_id(GenerationTemplateId.PYTHON_BASICS)
        cdict = template.build_candidate(user_prompt="")
        cdict["lab_id"] = "real-user-draft-abc123"
        real_draft = LabDraft.model_validate(cdict)
        draft_repo.create(real_draft)

        # Seed with reset=True — non-demo draft must survive
        seed_svc.seed(reset=True)
        assert draft_repo.get("real-user-draft-abc123") is not None

    def test_deterministic_ids_are_stable(self, seed_svc):
        r1 = seed_svc.seed()
        r2 = seed_svc.seed()
        assert set(r1.created_or_updated_draft_ids) == set(r2.created_or_updated_draft_ids)
        assert set(r1.created_or_updated_session_ids) == set(r2.created_or_updated_session_ids)

    def test_deterministic_titles_stable(self, seed_svc, draft_repo):
        seed_svc.seed()
        d1 = draft_repo.get(DEMO_DRAFT_ID_PYTHON)
        seed_svc.seed()
        d2 = draft_repo.get(DEMO_DRAFT_ID_PYTHON)
        assert d1 is not None and d2 is not None
        assert d1.title == d2.title


# ===========================================================================
# C. Scenario correctness
# ===========================================================================


class TestScenarioCorrectness:
    def test_python_basics_is_published(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_PYTHON)
        assert draft is not None
        assert draft.publish_status == PublishStatus.PUBLISHED

    def test_http_api_basics_is_published(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_HTTP)
        assert draft is not None
        assert draft.publish_status == PublishStatus.PUBLISHED

    def test_data_transform_image_blocked_is_publish_blocked(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_DATA_BLOCKED)
        assert draft is not None
        assert draft.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_python_unresolved_is_publish_blocked(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_PYTHON_UNRESOLVED)
        assert draft is not None
        assert draft.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_http_not_found_is_publish_blocked(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_HTTP_NOT_FOUND)
        assert draft is not None
        assert draft.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_blocked_drafts_not_in_learner_catalog(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get("/api/labs")
        assert r.status_code == 200
        lab_ids = [lab["lab_id"] for lab in r.json()]
        assert DEMO_DRAFT_ID_DATA_BLOCKED not in lab_ids
        assert DEMO_DRAFT_ID_PYTHON_UNRESOLVED not in lab_ids
        assert DEMO_DRAFT_ID_HTTP_NOT_FOUND not in lab_ids

    def test_published_labs_visible_in_learner_catalog(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get("/api/labs")
        assert r.status_code == 200
        lab_ids = [lab["lab_id"] for lab in r.json()]
        assert DEMO_DRAFT_ID_PYTHON in lab_ids
        assert DEMO_DRAFT_ID_HTTP in lab_ids

    def test_blocked_draft_preview_accessible(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/preview")
        assert r.status_code == 200

    def test_publish_decision_blocked_for_blocked_draft(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/publish-decision")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "BLOCKED"
        assert body["is_publishable"] is False

    def test_active_session_snapshot_readable(self, admin_client, session_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_ACTIVE}/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == DEMO_SESSION_ID_ACTIVE
        assert body["session_state"] == "LAB_ACTIVE"

    def test_ready_to_complete_session_can_complete_true(self, admin_client, session_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_READY}/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["runtime_summary"]["ready_to_complete"] is True
        assert body["action_availability"]["can_complete"] is True

    def test_cleanup_failed_session_shows_safety_issue(self, admin_client, session_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_CLEANUP_FAILED}/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["session_state"] == "LAB_CLEANUP_FAILED"
        assert body["runtime_summary"]["tainted"] is True
        assert body["runtime_summary"]["cleanup_status"] == "failed"
        issue_codes = [i["code"] for i in body["issues"]]
        assert "CLEANUP_FAILED" in issue_codes

    def test_learner_detail_shows_runtime_checks_deferred_warning(
        self, admin_client, draft_repo
    ):
        """Published lab detail should show RUNTIME_CHECKS_DEFERRED warning (no real K3s)."""
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labs/{DEMO_DRAFT_ID_PYTHON}")
        assert r.status_code == 200
        body = r.json()
        eligibility = body.get("start_eligibility", {})
        issue_codes = [i["code"] for i in eligibility.get("issues", [])]
        assert "RUNTIME_CHECKS_DEFERRED" in issue_codes

    def test_active_session_vm_id_absent_from_snapshot(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_ACTIVE}/snapshot")
        body = r.json()
        assert "vm_id" not in body
        assert DEMO_VM_ID not in str(body)

    def test_active_session_namespace_absent_from_snapshot(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_ACTIVE}/snapshot")
        body = r.json()
        assert "namespace" not in body


# ===========================================================================
# D. Image readiness scenarios
# ===========================================================================


class TestImageReadinessScenarios:
    def test_data_transform_has_blocked_image_resolution(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_DATA_BLOCKED)
        assert draft is not None
        assert len(draft.image_resolution) == 1
        assert draft.image_resolution[0].image_status == ImageStatus.BLOCKED

    def test_python_unresolved_has_unresolved_image_resolution(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_PYTHON_UNRESOLVED)
        assert draft is not None
        assert len(draft.image_resolution) == 1
        assert draft.image_resolution[0].image_status == ImageStatus.UNRESOLVED

    def test_http_not_found_has_resolved_but_missing_image(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_HTTP_NOT_FOUND)
        assert draft is not None
        assert len(draft.image_resolution) == 1
        img = draft.image_resolution[0]
        assert img.image_status == ImageStatus.RESOLVED
        assert img.existence_check_passed is False

    def test_data_transform_preview_image_readiness_blocked(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/preview")
        assert r.status_code == 200
        body = r.json()
        ir = body.get("image_readiness")
        assert ir is not None
        assert ir["status"] == "BLOCKED"

    def test_python_unresolved_preview_image_readiness_unresolved(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_PYTHON_UNRESOLVED}/preview")
        assert r.status_code == 200
        body = r.json()
        ir = body.get("image_readiness")
        assert ir is not None
        assert ir["status"] == "UNRESOLVED"

    def test_http_not_found_preview_image_readiness_not_found(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_HTTP_NOT_FOUND}/preview")
        assert r.status_code == 200
        body = r.json()
        ir = body.get("image_readiness")
        assert ir is not None
        assert ir["status"] == "NOT_FOUND"

    def test_python_unresolved_publish_decision_blocked(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_PYTHON_UNRESOLVED}/publish-decision")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "BLOCKED"
        assert body["is_publishable"] is False

    def test_http_not_found_publish_decision_blocked(self, admin_client, draft_repo):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_HTTP_NOT_FOUND}/publish-decision")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "BLOCKED"
        assert body["is_publishable"] is False

    def test_published_scenarios_image_readiness_ready(self, seed_svc, draft_repo):
        """PUBLISHED drafts must have image_readiness READY (set by PublishService)."""
        seed_svc.seed()
        from backend.labgen.image_readiness import ImageReadinessService
        svc = ImageReadinessService()
        for draft_id in [DEMO_DRAFT_ID_PYTHON, DEMO_DRAFT_ID_HTTP]:
            draft = draft_repo.get(draft_id)
            assert draft is not None
            result = svc.evaluate(list(draft.image_resolution))
            assert result.status == ImageReadinessStatus.READY, (
                f"Draft {draft_id} image_readiness should be READY, got {result.status}"
            )

    def test_image_resolution_contains_no_real_secrets(self, seed_svc, draft_repo):
        seed_svc.seed()
        for draft_id in [
            DEMO_DRAFT_ID_DATA_BLOCKED,
            DEMO_DRAFT_ID_PYTHON_UNRESOLVED,
            DEMO_DRAFT_ID_HTTP_NOT_FOUND,
        ]:
            draft = draft_repo.get(draft_id)
            assert draft is not None
            for img in draft.image_resolution:
                payload = str(img.model_dump())
                assert "token" not in payload.lower() or "existence" in payload.lower()
                assert "password" not in payload.lower()
                assert "secret" not in payload.lower()
                assert "-----BEGIN" not in payload


# ===========================================================================
# E. Safety
# ===========================================================================


class TestSafety:
    def test_seed_response_no_sensitive(self, admin_client):
        r = admin_client.post("/api/labgen/demo/seed", json={})
        _assert_no_sensitive(r.json(), "seed response")

    def test_catalog_response_no_sensitive(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get("/api/labs")
        _assert_no_sensitive(r.json(), "catalog response")

    def test_lab_detail_response_no_sensitive(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labs/{DEMO_DRAFT_ID_PYTHON}")
        _assert_no_sensitive(r.json(), "lab detail response")

    def test_session_snapshot_no_sensitive(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_ACTIVE}/snapshot")
        _assert_no_sensitive(r.json(), "session snapshot")

    def test_preview_no_sensitive(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/preview")
        _assert_no_sensitive(r.json(), "draft preview")

    def test_publish_decision_no_sensitive(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/publish-decision")
        _assert_no_sensitive(r.json(), "publish decision")

    def test_seed_does_not_produce_kubeconfig(self, seed_svc, draft_repo):
        seed_svc.seed()
        for draft in draft_repo.list_all():
            assert "kubeconfig" not in draft.model_dump_json()

    def test_seed_does_not_call_real_runtime_adapter(self, seed_svc, session_repo):
        seed_svc.seed()
        # All sessions must be in safe states (no intermediate inflight state that implies K8s call)
        active = session_repo.get(DEMO_SESSION_ID_ACTIVE)
        assert active is not None
        assert active.lab_session_status == LabSessionStatus.LAB_ACTIVE
        # Cleanup-failed session is directly in terminal state — no NAMESPACE_CREATING, etc.
        failed = session_repo.get(DEMO_SESSION_ID_CLEANUP_FAILED)
        assert failed is not None
        assert failed.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED

    def test_unresolved_preview_no_sensitive(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_PYTHON_UNRESOLVED}/preview")
        _assert_no_sensitive(r.json(), "unresolved preview")

    def test_not_found_preview_no_sensitive(self, admin_client):
        admin_client.post("/api/labgen/demo/seed", json={})
        r = admin_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_HTTP_NOT_FOUND}/preview")
        _assert_no_sensitive(r.json(), "not_found preview")


# ===========================================================================
# F. Regression
# ===========================================================================


class TestRegression:
    def test_demo_seed_does_not_modify_contract_v1_fields(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_PYTHON)
        assert draft is not None
        # All Contract v0.1 required fields present
        assert draft.schema_version == "1.0"
        assert draft.source_article_id.startswith("template:")
        assert isinstance(draft.steps, list) and len(draft.steps) > 0
        assert draft.cleanup is not None

    def test_demo_seed_does_not_add_new_audit_event_types(self):
        from backend.labgen.models import RuntimeAuditEventType
        existing = {e.value for e in RuntimeAuditEventType}
        # These are the only types defined in Contract v0.1 — seed must not add new ones
        expected = {
            "lab_start_success", "lab_start_failed",
            "step_check_passed", "step_check_failed",
            "lab_complete", "lab_abort",
            "cleanup_success", "cleanup_failed", "vm_tainted",
        }
        assert existing == expected, (
            f"Unexpected RuntimeAuditEventType values: {existing - expected}"
        )

    def test_published_python_draft_has_three_steps(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_PYTHON)
        assert draft is not None
        assert len(draft.steps) == 3

    def test_published_http_draft_has_three_steps(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_HTTP)
        assert draft is not None
        assert len(draft.steps) == 3

    def test_all_demo_scenarios_covered(self):
        assert len(ALL_DEMO_SCENARIOS) == 8

    def test_blocked_draft_has_blocking_validator_results(self, seed_svc, draft_repo):
        seed_svc.seed()
        draft = draft_repo.get(DEMO_DRAFT_ID_DATA_BLOCKED)
        assert draft is not None
        from backend.labgen.models import BlockingLevel, ValidatorStatus
        blocking = [
            r for r in draft.validator_results
            if r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        assert len(blocking) > 0, "Blocked draft must have at least one PUBLISH_BLOCKING result"

    def test_ready_session_has_all_steps_completed(self, seed_svc, session_repo):
        seed_svc.seed()
        session = session_repo.get(DEMO_SESSION_ID_READY)
        assert session is not None
        assert session.ready_to_complete is True
        assert len(session.completed_step_ids) == 3  # PYTHON_BASICS has 3 steps

    def test_cleanup_failed_session_has_failure_reason(self, seed_svc, session_repo):
        seed_svc.seed()
        session = session_repo.get(DEMO_SESSION_ID_CLEANUP_FAILED)
        assert session is not None
        assert session.failure_reason == "namespace_cleanup_failed"
        assert session.cleanup_verified is False

    def test_demo_scenario_ids_are_stable_strings(self):
        """Enum values must not change — they're part of the API surface."""
        assert DemoSeedScenarioId.PYTHON_BASICS_PUBLISHED.value == "PYTHON_BASICS_PUBLISHED"
        assert DemoSeedScenarioId.HTTP_API_BASICS_PUBLISHED.value == "HTTP_API_BASICS_PUBLISHED"
        assert DemoSeedScenarioId.DATA_TRANSFORM_IMAGE_BLOCKED_DRAFT.value == "DATA_TRANSFORM_IMAGE_BLOCKED_DRAFT"
        assert DemoSeedScenarioId.PYTHON_IMAGE_UNRESOLVED_DRAFT.value == "PYTHON_IMAGE_UNRESOLVED_DRAFT"
        assert DemoSeedScenarioId.HTTP_IMAGE_NOT_FOUND_DRAFT.value == "HTTP_IMAGE_NOT_FOUND_DRAFT"
        assert DemoSeedScenarioId.RUNTIME_ACTIVE_SESSION.value == "RUNTIME_ACTIVE_SESSION"
        assert DemoSeedScenarioId.RUNTIME_READY_TO_COMPLETE_SESSION.value == "RUNTIME_READY_TO_COMPLETE_SESSION"
        assert DemoSeedScenarioId.RUNTIME_CLEANUP_FAILED_TAINTED_SESSION.value == "RUNTIME_CLEANUP_FAILED_TAINTED_SESSION"
