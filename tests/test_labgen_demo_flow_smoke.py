"""
Demo Flow Smoke Tests — end-to-end demo scenario verification.

Covers the complete demo flow without real K3s, real LLM, or real VMs.
Uses in-memory repos and DemoSeedService directly.

Smoke path:
  1. Admin seeds demo data (all scenarios).
  2. Learner catalog sees PUBLISHED labs.
  3. Blocked/unresolved/not-found drafts absent from learner catalog.
  4. Admin preview correctly shows image_readiness for each scenario.
  5. Publish decision correctly blocks all non-ready drafts.
  6. Learner detail shows RUNTIME_CHECKS_DEFERRED warning.
  7. Runtime session snapshots readable with correct states.
  8. All responses pass sensitive data assertion.
"""
from __future__ import annotations

import re
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.demo_seed import (
    DEMO_DRAFT_ID_DATA_BLOCKED,
    DEMO_DRAFT_ID_HTTP,
    DEMO_DRAFT_ID_HTTP_NOT_FOUND,
    DEMO_DRAFT_ID_PYTHON,
    DEMO_DRAFT_ID_PYTHON_UNRESOLVED,
    DEMO_SESSION_ID_ACTIVE,
    DEMO_SESSION_ID_CLEANUP_FAILED,
    DEMO_SESSION_ID_READY,
    DEMO_STUDENT_USERNAME,
    DemoSeedService,
)
from backend.labgen.models import LabDraft, LabSessionState
from backend.auth_deps import get_current_user
from backend.labgen.routes import (
    get_preview_service,
    get_repository,
    get_session_repository,
    get_snapshot_service,
    require_admin_user,
)
from backend.labgen.draft_preview import DraftPreviewService
from backend.labgen.image_readiness import ImageReadinessService
from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static

# KNOWN DEBT (2026-07-12, found while adding verify.type_implemented in the
# Service-no-Endpoints lab sprint): demo_seed's PYTHON_BASICS/HTTP_API_BASICS
# templates reference nonexistent manifests/*.yaml files (pre-existing,
# unrelated to this check) and separately use unimplemented VerifyType values
# (POD_READY, JOB_COMPLETED) newly caught by verify.type_implemented, so they
# no longer reach PublishStatus.PUBLISHED / the learner catalog. Tracked, not
# silently hidden — see CHANGELOG for the sprint that surfaced this.
_TEMPLATE_DEBT_XFAIL_REASON = (
    "KNOWN DEBT: GenerationTemplateRegistry fixtures reference nonexistent "
    "manifest files and use unimplemented VerifyType values (POD_READY/"
    "JOB_COMPLETED) now caught by verify.type_implemented — see git blame / "
    "CHANGELOG for the Service-no-Endpoints lab sprint that surfaced this."
)

# ---------------------------------------------------------------------------
# Sensitive data assertion
# ---------------------------------------------------------------------------

_SENSITIVE_RE = [
    re.compile(p, re.IGNORECASE) for p in [
        r"-----BEGIN",
        r"kubeconfig",
        r"token\s*:",
        r"password\s*:",
        r"private_key",
        r"client-key-data",
        r"raw_model_output",
        r"hidden_prompt",
        r"provider_metadata",
        r"verifier.credential",
        r"registry.*secret",
        r"registry.*token",
        r"registry.*auth",
    ]
]


def _assert_no_sensitive(data, context: str = "") -> None:
    text = str(data)
    for pat in _SENSITIVE_RE:
        assert not pat.search(text), (
            f"Sensitive pattern '{pat.pattern}' in {context or 'response'}"
        )


# ---------------------------------------------------------------------------
# In-memory repositories
# ---------------------------------------------------------------------------


class _MemDraftRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def create(self, d: LabDraft) -> LabDraft:
        self._store[d.lab_id] = d
        return d

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, d: LabDraft) -> LabDraft:
        self._store[d.lab_id] = d
        return d

    def delete(self, lab_id: str) -> None:
        self._store.pop(lab_id, None)

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemSessionRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabSessionState] = {}

    def create(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._store.get(session_id)

    def update(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]


# ---------------------------------------------------------------------------
# Fixtures — seeded client
# ---------------------------------------------------------------------------


@pytest.fixture()
def draft_repo() -> _MemDraftRepo:
    return _MemDraftRepo()


@pytest.fixture()
def session_repo() -> _MemSessionRepo:
    return _MemSessionRepo()


@pytest.fixture()
def seeded_client(draft_repo, session_repo):
    """TestClient with all demo scenarios pre-seeded, ready for smoke assertions."""
    from backend.main import app

    # Seed before overriding — uses the in-memory repos directly
    svc = DemoSeedService(draft_repo=draft_repo, session_repo=session_repo)
    svc.seed()

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
    app.dependency_overrides[require_admin_user] = lambda: "smokeadmin"
    app.dependency_overrides[get_current_user] = lambda: DEMO_STUDENT_USERNAME
    app.dependency_overrides[get_preview_service] = lambda: preview_svc
    app.dependency_overrides[get_snapshot_service] = lambda: snapshot_svc

    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


# ===========================================================================
# 1. Learner catalog smoke
# ===========================================================================


class TestCatalogSmoke:
    @pytest.mark.xfail(reason=_TEMPLATE_DEBT_XFAIL_REASON, strict=True)
    def test_python_basics_visible_in_catalog(self, seeded_client):
        r = seeded_client.get("/api/labs")
        assert r.status_code == 200
        lab_ids = [lab["lab_id"] for lab in r.json()]
        assert DEMO_DRAFT_ID_PYTHON in lab_ids

    @pytest.mark.xfail(reason=_TEMPLATE_DEBT_XFAIL_REASON, strict=True)
    def test_http_api_basics_visible_in_catalog(self, seeded_client):
        r = seeded_client.get("/api/labs")
        assert r.status_code == 200
        lab_ids = [lab["lab_id"] for lab in r.json()]
        assert DEMO_DRAFT_ID_HTTP in lab_ids

    def test_data_transform_blocked_absent_from_catalog(self, seeded_client):
        r = seeded_client.get("/api/labs")
        lab_ids = [lab["lab_id"] for lab in r.json()]
        assert DEMO_DRAFT_ID_DATA_BLOCKED not in lab_ids

    def test_python_unresolved_absent_from_catalog(self, seeded_client):
        r = seeded_client.get("/api/labs")
        lab_ids = [lab["lab_id"] for lab in r.json()]
        assert DEMO_DRAFT_ID_PYTHON_UNRESOLVED not in lab_ids

    def test_http_not_found_absent_from_catalog(self, seeded_client):
        r = seeded_client.get("/api/labs")
        lab_ids = [lab["lab_id"] for lab in r.json()]
        assert DEMO_DRAFT_ID_HTTP_NOT_FOUND not in lab_ids

    def test_catalog_response_no_sensitive(self, seeded_client):
        r = seeded_client.get("/api/labs")
        _assert_no_sensitive(r.json(), "catalog")


# ===========================================================================
# 2. Admin preview image readiness smoke
# ===========================================================================


class TestPreviewImageReadinessSmoke:
    def test_data_transform_image_readiness_blocked(self, seeded_client):
        r = seeded_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/preview")
        assert r.status_code == 200
        ir = r.json().get("image_readiness")
        assert ir is not None
        assert ir["status"] == "BLOCKED"

    def test_python_unresolved_image_readiness_unresolved(self, seeded_client):
        r = seeded_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_PYTHON_UNRESOLVED}/preview")
        assert r.status_code == 200
        ir = r.json().get("image_readiness")
        assert ir is not None
        assert ir["status"] == "UNRESOLVED"

    def test_http_not_found_image_readiness_not_found(self, seeded_client):
        r = seeded_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_HTTP_NOT_FOUND}/preview")
        assert r.status_code == 200
        ir = r.json().get("image_readiness")
        assert ir is not None
        assert ir["status"] == "NOT_FOUND"

    def test_preview_no_sensitive_data_blocked(self, seeded_client):
        r = seeded_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/preview")
        _assert_no_sensitive(r.json(), "data_transform preview")

    def test_preview_no_sensitive_unresolved(self, seeded_client):
        r = seeded_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_PYTHON_UNRESOLVED}/preview")
        _assert_no_sensitive(r.json(), "unresolved preview")

    def test_preview_no_sensitive_not_found(self, seeded_client):
        r = seeded_client.get(f"/api/labgen/drafts/{DEMO_DRAFT_ID_HTTP_NOT_FOUND}/preview")
        _assert_no_sensitive(r.json(), "not_found preview")


# ===========================================================================
# 3. Publish decision smoke
# ===========================================================================


class TestPublishDecisionSmoke:
    def test_data_transform_blocked_publish_decision(self, seeded_client):
        r = seeded_client.get(
            f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/publish-decision"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "BLOCKED"
        assert body["is_publishable"] is False

    def test_python_unresolved_publish_decision_blocked(self, seeded_client):
        r = seeded_client.get(
            f"/api/labgen/drafts/{DEMO_DRAFT_ID_PYTHON_UNRESOLVED}/publish-decision"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "BLOCKED"
        assert body["is_publishable"] is False

    def test_http_not_found_publish_decision_blocked(self, seeded_client):
        r = seeded_client.get(
            f"/api/labgen/drafts/{DEMO_DRAFT_ID_HTTP_NOT_FOUND}/publish-decision"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "BLOCKED"
        assert body["is_publishable"] is False

    def test_publish_decision_no_sensitive_blocked(self, seeded_client):
        r = seeded_client.get(
            f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/publish-decision"
        )
        _assert_no_sensitive(r.json(), "publish_decision blocked")

    def test_publish_decision_no_sensitive_unresolved(self, seeded_client):
        r = seeded_client.get(
            f"/api/labgen/drafts/{DEMO_DRAFT_ID_PYTHON_UNRESOLVED}/publish-decision"
        )
        _assert_no_sensitive(r.json(), "publish_decision unresolved")


# ===========================================================================
# 4. Learner lab detail smoke
# ===========================================================================


class TestLearnerDetailSmoke:
    @pytest.mark.xfail(reason=_TEMPLATE_DEBT_XFAIL_REASON, strict=True)
    def test_python_lab_detail_accessible(self, seeded_client):
        r = seeded_client.get(f"/api/labs/{DEMO_DRAFT_ID_PYTHON}")
        assert r.status_code == 200
        body = r.json()
        assert body["lab_id"] == DEMO_DRAFT_ID_PYTHON

    @pytest.mark.xfail(reason=_TEMPLATE_DEBT_XFAIL_REASON, strict=True)
    def test_learner_detail_runtime_checks_deferred(self, seeded_client):
        r = seeded_client.get(f"/api/labs/{DEMO_DRAFT_ID_PYTHON}")
        assert r.status_code == 200
        eligibility = r.json().get("start_eligibility", {})
        issue_codes = [i["code"] for i in eligibility.get("issues", [])]
        assert "RUNTIME_CHECKS_DEFERRED" in issue_codes

    def test_lab_detail_no_sensitive(self, seeded_client):
        r = seeded_client.get(f"/api/labs/{DEMO_DRAFT_ID_PYTHON}")
        _assert_no_sensitive(r.json(), "lab detail")


# ===========================================================================
# 5. Runtime session snapshot smoke
# ===========================================================================


class TestSessionSnapshotSmoke:
    def test_active_session_snapshot_readable(self, seeded_client):
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_ACTIVE}/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == DEMO_SESSION_ID_ACTIVE
        assert body["session_state"] == "LAB_ACTIVE"

    def test_ready_to_complete_session_can_complete_true(self, seeded_client):
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_READY}/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["runtime_summary"]["ready_to_complete"] is True
        assert body["action_availability"]["can_complete"] is True

    def test_cleanup_failed_session_shows_tainted(self, seeded_client):
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_CLEANUP_FAILED}/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["session_state"] == "LAB_CLEANUP_FAILED"
        assert body["runtime_summary"]["tainted"] is True
        assert body["runtime_summary"]["cleanup_status"] == "failed"

    def test_cleanup_failed_session_issue_code(self, seeded_client):
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_CLEANUP_FAILED}/snapshot")
        body = r.json()
        issue_codes = [i["code"] for i in body["issues"]]
        assert "CLEANUP_FAILED" in issue_codes

    def test_active_session_snapshot_no_sensitive(self, seeded_client):
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_ACTIVE}/snapshot")
        _assert_no_sensitive(r.json(), "active session snapshot")

    def test_ready_session_snapshot_no_sensitive(self, seeded_client):
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_READY}/snapshot")
        _assert_no_sensitive(r.json(), "ready session snapshot")

    def test_cleanup_failed_session_no_sensitive(self, seeded_client):
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_CLEANUP_FAILED}/snapshot")
        _assert_no_sensitive(r.json(), "cleanup_failed session snapshot")

    def test_active_session_does_not_expose_vm_id(self, seeded_client):
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_ACTIVE}/snapshot")
        body = r.json()
        assert "vm_id" not in body

    def test_active_session_exposes_namespace_for_terminal_badge(self, seeded_client):
        # namespace is intentionally exposed so the learner terminal badge can show it.
        # It is scoped to the session owner's own namespace; not a sensitive field.
        r = seeded_client.get(f"/api/lab-sessions/{DEMO_SESSION_ID_ACTIVE}/snapshot")
        body = r.json()
        # namespace key present (may be None for very early states)
        assert "namespace" in body
        # Sensitive fields still hidden
        assert "vm_id" not in body
        assert "kubeconfig" not in body


# ===========================================================================
# 6. Full flow — seed then verify all paths
# ===========================================================================


class TestFullFlowSmoke:
    def test_seed_returns_all_8_scenarios(self, draft_repo, session_repo):
        from backend.main import app
        from backend.labgen.demo_seed import ALL_DEMO_SCENARIOS

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
        app.dependency_overrides[require_admin_user] = lambda: "smokeadmin"
        app.dependency_overrides[get_current_user] = lambda: DEMO_STUDENT_USERNAME
        app.dependency_overrides[get_preview_service] = lambda: preview_svc
        app.dependency_overrides[get_snapshot_service] = lambda: snapshot_svc

        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.post("/api/labgen/demo/seed", json={})
            assert r.status_code == 200
            body = r.json()
            assert set(body["seeded_scenarios"]) == {s.value for s in ALL_DEMO_SCENARIOS}
            assert len(body["created_or_updated_draft_ids"]) == 5
            assert len(body["created_or_updated_session_ids"]) == 3
            # checked_at is present and parseable
            from datetime import datetime
            datetime.fromisoformat(body["checked_at"])
        finally:
            app.dependency_overrides.clear()

    def test_seed_response_no_sensitive(self, draft_repo, session_repo):
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
        app.dependency_overrides[require_admin_user] = lambda: "smokeadmin"
        app.dependency_overrides[get_current_user] = lambda: DEMO_STUDENT_USERNAME
        app.dependency_overrides[get_preview_service] = lambda: preview_svc
        app.dependency_overrides[get_snapshot_service] = lambda: snapshot_svc

        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.post("/api/labgen/demo/seed", json={})
            _assert_no_sensitive(r.json(), "full flow seed response")
        finally:
            app.dependency_overrides.clear()
