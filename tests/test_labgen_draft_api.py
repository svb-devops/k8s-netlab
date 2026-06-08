"""Tests for LabGen Draft API — POST/GET/PATCH/validate endpoints."""

from __future__ import annotations

from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    PollutionLevel,
    PublishStatus,
    RuntimeRequirements,
    Step,
    ValidatorStatus,
)
from backend.labgen.routes import (
    get_repository,
    get_validator,
    require_admin_user,
)
from backend.labgen.static_validator import StaticValidator


# ---------------------------------------------------------------------------
# In-memory repository for tests
# ---------------------------------------------------------------------------


class _MemRepo:
    """Dict-backed repository — no filesystem I/O."""

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_repo() -> _MemRepo:
    return _MemRepo()


@pytest.fixture()
def client(mem_repo):
    from backend.main import app

    app.dependency_overrides[get_repository] = lambda: mem_repo
    app.dependency_overrides[require_admin_user] = lambda: "testadmin"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def non_admin_client():
    from backend.main import app

    # No override for require_admin_user — let it fall through to real auth
    # Override get_current_user to return a non-admin username
    from backend.auth_deps import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "regularuser"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


def _create_body(**extra) -> dict:
    return {
        "source_article_id": "article-123",
        "title": "Intro to Network Policies",
        "description": "Learn how K8s NetworkPolicy works",
        "estimated_duration_minutes": 45,
        "prerequisites": ["kubectl basics"],
        **extra,
    }


def _insert_draft(mem_repo: _MemRepo, **kw) -> LabDraft:
    """Directly insert a LabDraft into the in-memory repo (bypasses API)."""
    draft = LabDraft(
        source_article_id=kw.get("source_article_id", "art-1"),
        title=kw.get("title", "Test Lab"),
        description=kw.get("description", "desc"),
        estimated_duration_minutes=kw.get("estimated_duration_minutes", 30),
        runtime_requirements=RuntimeRequirements(),
        steps=kw.get("steps", [_make_step()]),
        cleanup=kw.get("cleanup", CleanupSpec(namespace_cleanup=CleanupNamespace())),
    )
    mem_repo.create(draft)
    return draft


def _make_step(step_id="s1") -> Step:
    return Step(
        step_id=step_id,
        order=1,
        why="why",
        do="do",
        observe="observe",
        explain=ExplainField(concept="c", observation="o"),
    )


# ---------------------------------------------------------------------------
# POST /api/labgen/drafts — create
# ---------------------------------------------------------------------------


class TestCreateDraft:
    def test_creates_draft_returns_201(self, client):
        r = client.post("/api/labgen/drafts", json=_create_body())
        assert r.status_code == 201

    def test_response_has_lab_id(self, client):
        r = client.post("/api/labgen/drafts", json=_create_body())
        data = r.json()
        assert "lab_id" in data
        assert len(data["lab_id"]) == 36  # UUID format

    def test_response_has_schema_version(self, client):
        r = client.post("/api/labgen/drafts", json=_create_body())
        assert r.json()["schema_version"] == "1.0"

    def test_response_reflects_input_fields(self, client):
        r = client.post("/api/labgen/drafts", json=_create_body())
        data = r.json()
        assert data["title"] == "Intro to Network Policies"
        assert data["estimated_duration_minutes"] == 45
        assert data["prerequisites"] == ["kubectl basics"]

    def test_default_publish_status_is_draft(self, client):
        r = client.post("/api/labgen/drafts", json=_create_body())
        assert r.json()["publish_status"] == "draft"

    def test_stub_generates_placeholder_step(self, client):
        r = client.post("/api/labgen/drafts", json=_create_body())
        steps = r.json()["steps"]
        assert len(steps) == 1
        assert steps[0]["step_id"] == "step-1"

    def test_draft_persisted_in_repo(self, client, mem_repo):
        r = client.post("/api/labgen/drafts", json=_create_body())
        lab_id = r.json()["lab_id"]
        assert mem_repo.get(lab_id) is not None

    def test_missing_required_field_returns_422(self, client):
        r = client.post("/api/labgen/drafts", json={"title": "x"})
        assert r.status_code == 422

    def test_admin_required(self, non_admin_client):
        r = non_admin_client.post("/api/labgen/drafts", json=_create_body())
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/labgen/drafts/{id} — read
# ---------------------------------------------------------------------------


class TestGetDraft:
    def test_returns_existing_draft(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.get(f"/api/labgen/drafts/{draft.lab_id}")
        assert r.status_code == 200
        assert r.json()["lab_id"] == draft.lab_id

    def test_404_for_missing_draft(self, client):
        r = client.get("/api/labgen/drafts/nonexistent-id")
        assert r.status_code == 404

    def test_returned_draft_matches_stored(self, client, mem_repo):
        draft = _insert_draft(mem_repo, title="My Lab")
        r = client.get(f"/api/labgen/drafts/{draft.lab_id}")
        assert r.json()["title"] == "My Lab"

    def test_admin_required(self, non_admin_client):
        r = non_admin_client.get("/api/labgen/drafts/some-id")
        assert r.status_code == 403

    def test_roundtrip_create_then_get(self, client):
        r_create = client.post("/api/labgen/drafts", json=_create_body())
        lab_id = r_create.json()["lab_id"]
        r_get = client.get(f"/api/labgen/drafts/{lab_id}")
        assert r_get.status_code == 200
        assert r_get.json()["lab_id"] == lab_id


# ---------------------------------------------------------------------------
# PATCH /api/labgen/drafts/{id} — partial update
# ---------------------------------------------------------------------------


class TestPatchDraft:
    def test_update_title(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "Updated Title"})
        assert r.status_code == 200
        assert r.json()["title"] == "Updated Title"

    def test_update_description(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"description": "New desc"})
        assert r.json()["description"] == "New desc"

    def test_update_estimated_duration(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"estimated_duration_minutes": 60})
        assert r.json()["estimated_duration_minutes"] == 60

    def test_update_prerequisites(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"prerequisites": ["helm", "kubectl"]})
        assert r.json()["prerequisites"] == ["helm", "kubectl"]

    def test_update_publish_status_to_review_required(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"publish_status": "review_required"},
        )
        assert r.status_code == 200
        assert r.json()["publish_status"] == "review_required"

    def test_cannot_set_publish_status_to_published(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"publish_status": "published"},
        )
        assert r.status_code == 400
        assert "published" in r.json()["detail"].lower()

    def test_partial_update_leaves_other_fields_unchanged(self, client, mem_repo):
        draft = _insert_draft(mem_repo, title="Original Title", description="Original Desc")
        r = client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New Title"})
        data = r.json()
        assert data["title"] == "New Title"
        assert data["description"] == "Original Desc"

    def test_updated_at_is_refreshed(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        original_updated_at = draft.updated_at.isoformat()
        r = client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "x"})
        assert r.json()["updated_at"] != original_updated_at

    def test_immutable_fields_not_in_patch(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        original_lab_id = draft.lab_id
        # Attempt to send lab_id in patch body — should be ignored (not in PatchDraftRequest)
        r = client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"title": "new title", "lab_id": "evil-id"},
        )
        assert r.status_code == 200
        assert r.json()["lab_id"] == original_lab_id

    def test_404_for_missing_draft(self, client):
        r = client.patch("/api/labgen/drafts/not-found", json={"title": "x"})
        assert r.status_code == 404

    def test_admin_required(self, non_admin_client):
        r = non_admin_client.patch("/api/labgen/drafts/some-id", json={"title": "x"})
        assert r.status_code == 403

    def test_empty_patch_body_returns_200(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/labgen/drafts/{id}/validate
# ---------------------------------------------------------------------------


class TestValidateDraft:
    def test_validate_clean_draft_returns_200(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        assert r.status_code == 200

    def test_validate_updates_validator_results(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        data = r.json()
        assert isinstance(data["validator_results"], list)
        assert len(data["validator_results"]) > 0

    def test_validator_results_have_schema_version(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        for vr in r.json()["validator_results"]:
            assert vr["schema_version"] == "1.0"
            assert "check_id" in vr
            assert "status" in vr

    def test_clean_stub_draft_publish_status_is_draft(self, client, mem_repo):
        # Stub draft has cleanup + steps → no publish-blocking issues
        draft = _insert_draft(mem_repo)
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        assert r.json()["publish_status"] == "draft"

    def test_missing_cleanup_causes_publish_blocked(self, client, mem_repo):
        draft = _insert_draft(mem_repo, cleanup=None)
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        assert r.json()["publish_status"] == "publish_blocked"

    def test_validate_sets_pollution_level(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        data = r.json()
        assert data["pollution_level"] in ("namespace_only", "cluster_scoped", "node_level", "unknown")

    def test_stub_draft_pollution_level_is_namespace_only(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        assert r.json()["pollution_level"] == "namespace_only"

    def test_validate_sets_shared_namespace_candidate(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        data = r.json()
        assert isinstance(data["shared_namespace_candidate"], bool)

    def test_validate_persists_changes(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        # Fetch again — persisted changes should be visible
        r = client.get(f"/api/labgen/drafts/{draft.lab_id}")
        assert len(r.json()["validator_results"]) > 0

    def test_validate_updates_updated_at(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        original_updated_at = draft.updated_at.isoformat()
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        assert r.json()["updated_at"] != original_updated_at

    def test_404_for_missing_draft(self, client):
        r = client.post("/api/labgen/drafts/not-found/validate")
        assert r.status_code == 404

    def test_admin_required(self, non_admin_client):
        r = non_admin_client.post("/api/labgen/drafts/some-id/validate")
        assert r.status_code == 403

    def test_review_required_status_from_helm_command(self, client, mem_repo):
        # Helm install → review_required (not publish_blocking)
        step = Step(
            step_id="s1", order=1, why="w", do="d", observe="o",
            commands=["helm install myapp ./chart"],
            explain=ExplainField(concept="c", observation="o"),
        )
        draft = _insert_draft(mem_repo, steps=[step])
        r = client.post(f"/api/labgen/drafts/{draft.lab_id}/validate")
        assert r.json()["publish_status"] == "review_required"


# ---------------------------------------------------------------------------
# _compute_publish_status helper (unit tests)
# ---------------------------------------------------------------------------


class TestComputePublishStatus:
    def test_publish_blocking_takes_precedence(self):
        from backend.labgen.routes import _compute_publish_status
        from backend.labgen.models import BlockingLevel, ValidatorResult, ValidatorStatus

        results = [
            ValidatorResult(
                check_id="cleanup.declared",
                status=ValidatorStatus.FAILED,
                blocking_level=BlockingLevel.PUBLISH_BLOCKING,
                field_path="cleanup",
                message="missing",
            ),
            ValidatorResult(
                check_id="helm.no_generation",
                status=ValidatorStatus.FAILED,
                blocking_level=BlockingLevel.REVIEW_REQUIRED,
                field_path="steps",
                message="helm found",
            ),
        ]
        assert _compute_publish_status(results) == PublishStatus.PUBLISH_BLOCKED

    def test_review_required_when_no_publish_blocking(self):
        from backend.labgen.routes import _compute_publish_status
        from backend.labgen.models import BlockingLevel, ValidatorResult, ValidatorStatus

        results = [
            ValidatorResult(
                check_id="helm.no_generation",
                status=ValidatorStatus.FAILED,
                blocking_level=BlockingLevel.REVIEW_REQUIRED,
                field_path="steps",
                message="helm found",
            ),
        ]
        assert _compute_publish_status(results) == PublishStatus.REVIEW_REQUIRED

    def test_draft_when_all_passed(self):
        from backend.labgen.routes import _compute_publish_status
        from backend.labgen.models import BlockingLevel, ValidatorResult, ValidatorStatus

        results = [
            ValidatorResult(
                check_id="cleanup.declared",
                status=ValidatorStatus.PASSED,
                blocking_level=BlockingLevel.DRAFT_WARNING,
                field_path="cleanup",
                message="OK",
            ),
        ]
        assert _compute_publish_status(results) == PublishStatus.DRAFT

    def test_draft_when_empty_results(self):
        from backend.labgen.routes import _compute_publish_status

        assert _compute_publish_status([]) == PublishStatus.DRAFT
