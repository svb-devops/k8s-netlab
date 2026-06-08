"""Tests for LabGen Publish API — PublishService unit tests + endpoint tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.models import (
    BlockingLevel,
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    ImageResolutionResult,
    ImageStatus,
    LabDraft,
    PublishStatus,
    RuntimeRequirements,
    Step,
    ValidatorResult,
    ValidatorStatus,
)
from backend.labgen.publish_service import PublishService
from backend.labgen.routes import (
    get_publish_service,
    get_repository,
    require_admin_user,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Test Lab",
        description="desc",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="w", do="d", observe="o",
            explain=ExplainField(concept="c", observation="o"),
        )],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
    )
    defaults.update(kw)
    return LabDraft(**defaults)


def _make_result(check_id: str, status: ValidatorStatus, blocking: BlockingLevel) -> ValidatorResult:
    return ValidatorResult(
        check_id=check_id,
        status=status,
        blocking_level=blocking,
        field_path="test",
        message="test",
    )


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _MemRepo:
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


class _MockPublishService:
    """Returns a pre-configured draft, tracks call count."""

    def __init__(self, result: LabDraft) -> None:
        self._result = result
        self.called_with: Optional[LabDraft] = None
        self.call_count = 0

    def publish(self, draft: LabDraft) -> LabDraft:
        self.called_with = draft
        self.call_count += 1
        return self._result


class _MockValidator:
    def __init__(self, results: list[ValidatorResult]) -> None:
        self._results = results
        self.call_count = 0

    def validate(self, draft: LabDraft) -> list[ValidatorResult]:
        self.call_count += 1
        return self._results


class _MockImageResolver:
    def __init__(self, pass_check: bool = True) -> None:
        self._pass = pass_check
        self.checked: list[ImageResolutionResult] = []

    def check_registry_existence(self, img: ImageResolutionResult) -> ImageResolutionResult:
        self.checked.append(img)
        return img.model_copy(update={
            "existence_check_passed": self._pass,
            "existence_checked_at": datetime.now(tz=timezone.utc),
        })


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_repo() -> _MemRepo:
    return _MemRepo()


@pytest.fixture()
def client(mem_repo):
    from backend.main import app

    # Provide a default published-success service; tests can override per-case
    draft_holder = {}

    def _svc_factory():
        if "svc" in draft_holder:
            return draft_holder["svc"]
        # Default: always-pass service
        return _AlwaysPassPublishService()

    app.dependency_overrides[get_repository] = lambda: mem_repo
    app.dependency_overrides[require_admin_user] = lambda: "testadmin"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def non_admin_client():
    from backend.main import app
    from backend.auth_deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: "regularuser"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


class _AlwaysPassPublishService:
    """Publish service that sets publish_status=published, no blocking."""

    def publish(self, draft: LabDraft) -> LabDraft:
        draft.validator_results = [
            _make_result("cleanup.declared", ValidatorStatus.PASSED, BlockingLevel.PUBLISH_BLOCKING),
        ]
        draft.publish_status = PublishStatus.PUBLISHED
        draft.updated_at = datetime.now(tz=timezone.utc)
        return draft


class _AlwaysBlockPublishService:
    """Publish service that sets publish_status=publish_blocked."""

    def __init__(self, blocking_check_id: str = "cleanup.declared") -> None:
        self._check_id = blocking_check_id

    def publish(self, draft: LabDraft) -> LabDraft:
        draft.validator_results = [
            _make_result(self._check_id, ValidatorStatus.FAILED, BlockingLevel.PUBLISH_BLOCKING),
        ]
        draft.publish_status = PublishStatus.PUBLISH_BLOCKED
        draft.updated_at = datetime.now(tz=timezone.utc)
        return draft


def _insert_draft(mem_repo: _MemRepo, **kw) -> LabDraft:
    draft = _make_draft(**kw)
    mem_repo.create(draft)
    return draft


# ---------------------------------------------------------------------------
# PublishService unit tests
# ---------------------------------------------------------------------------


class TestPublishService:
    def test_clean_draft_sets_published(self):
        svc = PublishService(
            validator=_MockValidator([]),
            image_resolver=_MockImageResolver(),
        )
        draft = _make_draft()
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISHED

    def test_blocking_failure_sets_publish_blocked(self):
        blocking = _make_result("cleanup.declared", ValidatorStatus.FAILED, BlockingLevel.PUBLISH_BLOCKING)
        svc = PublishService(
            validator=_MockValidator([blocking]),
            image_resolver=_MockImageResolver(),
        )
        draft = _make_draft(cleanup=None)
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_review_required_does_not_block_publish(self):
        review = _make_result("helm.no_generation", ValidatorStatus.FAILED, BlockingLevel.REVIEW_REQUIRED)
        svc = PublishService(
            validator=_MockValidator([review]),
            image_resolver=_MockImageResolver(),
        )
        draft = _make_draft()
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISHED

    def test_draft_warning_does_not_block_publish(self):
        warning = _make_result("some.check", ValidatorStatus.WARNING, BlockingLevel.DRAFT_WARNING)
        svc = PublishService(
            validator=_MockValidator([warning]),
            image_resolver=_MockImageResolver(),
        )
        draft = _make_draft()
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISHED

    def test_validator_always_called(self):
        mock_validator = _MockValidator([])
        svc = PublishService(validator=mock_validator, image_resolver=_MockImageResolver())
        draft = _make_draft()
        svc.publish(draft)
        assert mock_validator.call_count == 1

    def test_image_resolver_called_for_each_resolved_image(self):
        mock_resolver = _MockImageResolver()
        svc = PublishService(validator=_MockValidator([]), image_resolver=mock_resolver)
        img = ImageResolutionResult(
            image_intent="nginx",
            requested_image="172.16.100.1:5000/nginx:1.25-alpine",
            resolved_image="172.16.100.1:5000/nginx:1.25-alpine",
            image_status=ImageStatus.RESOLVED,
        )
        draft = _make_draft(image_resolution=[img])
        svc.publish(draft)
        assert len(mock_resolver.checked) == 1

    def test_image_resolution_existence_checked_at_updated(self):
        mock_resolver = _MockImageResolver(pass_check=True)
        svc = PublishService(validator=_MockValidator([]), image_resolver=mock_resolver)
        img = ImageResolutionResult(
            image_intent="nginx",
            requested_image="172.16.100.1:5000/nginx:1.25-alpine",
            resolved_image="172.16.100.1:5000/nginx:1.25-alpine",
            image_status=ImageStatus.RESOLVED,
        )
        draft = _make_draft(image_resolution=[img])
        result = svc.publish(draft)
        assert result.image_resolution[0].existence_checked_at is not None

    def test_image_resolution_existence_check_passed_set(self):
        mock_resolver = _MockImageResolver(pass_check=True)
        svc = PublishService(validator=_MockValidator([]), image_resolver=mock_resolver)
        img = ImageResolutionResult(
            image_intent="nginx",
            requested_image="172.16.100.1:5000/nginx:1.25-alpine",
            resolved_image="172.16.100.1:5000/nginx:1.25-alpine",
            image_status=ImageStatus.RESOLVED,
        )
        draft = _make_draft(image_resolution=[img])
        result = svc.publish(draft)
        assert result.image_resolution[0].existence_check_passed is True

    def test_validator_results_stored_on_draft(self):
        r = _make_result("cleanup.declared", ValidatorStatus.PASSED, BlockingLevel.PUBLISH_BLOCKING)
        svc = PublishService(validator=_MockValidator([r]), image_resolver=_MockImageResolver())
        draft = _make_draft()
        result = svc.publish(draft)
        assert len(result.validator_results) == 1
        assert result.validator_results[0].check_id == "cleanup.declared"

    def test_updated_at_refreshed(self):
        svc = PublishService(validator=_MockValidator([]), image_resolver=_MockImageResolver())
        draft = _make_draft()
        old_updated_at = draft.updated_at
        result = svc.publish(draft)
        assert result.updated_at != old_updated_at

    def test_no_images_means_no_resolver_calls(self):
        mock_resolver = _MockImageResolver()
        svc = PublishService(validator=_MockValidator([]), image_resolver=mock_resolver)
        draft = _make_draft()  # no image_resolution
        svc.publish(draft)
        assert len(mock_resolver.checked) == 0


# ---------------------------------------------------------------------------
# Publish endpoint tests
# ---------------------------------------------------------------------------


class TestPublishEndpoint:
    def _client_with_svc(self, mem_repo, svc):
        from backend.main import app
        app.dependency_overrides[get_repository] = lambda: mem_repo
        app.dependency_overrides[require_admin_user] = lambda: "testadmin"
        app.dependency_overrides[get_publish_service] = lambda: svc
        c = TestClient(app, raise_server_exceptions=True)
        return c, app

    def test_successful_publish_returns_200(self, mem_repo):
        draft = _insert_draft(mem_repo)
        svc = _AlwaysPassPublishService()
        c, app = self._client_with_svc(mem_repo, svc)
        try:
            r = c.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            assert r.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_successful_publish_returns_published_status(self, mem_repo):
        draft = _insert_draft(mem_repo)
        svc = _AlwaysPassPublishService()
        c, app = self._client_with_svc(mem_repo, svc)
        try:
            r = c.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            assert r.json()["publish_status"] == "published"
        finally:
            app.dependency_overrides.clear()

    def test_blocking_failure_returns_409(self, mem_repo):
        draft = _insert_draft(mem_repo)
        svc = _AlwaysBlockPublishService()
        c, app = self._client_with_svc(mem_repo, svc)
        try:
            r = c.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            assert r.status_code == 409
        finally:
            app.dependency_overrides.clear()

    def test_409_detail_contains_check_id(self, mem_repo):
        draft = _insert_draft(mem_repo)
        svc = _AlwaysBlockPublishService(blocking_check_id="cleanup.declared")
        c, app = self._client_with_svc(mem_repo, svc)
        try:
            r = c.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            assert "cleanup.declared" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_draft_saved_on_success(self, mem_repo):
        draft = _insert_draft(mem_repo)
        svc = _AlwaysPassPublishService()
        c, app = self._client_with_svc(mem_repo, svc)
        try:
            c.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            stored = mem_repo.get(draft.lab_id)
            assert stored.publish_status == PublishStatus.PUBLISHED
        finally:
            app.dependency_overrides.clear()

    def test_draft_saved_even_on_409(self, mem_repo):
        draft = _insert_draft(mem_repo)
        svc = _AlwaysBlockPublishService()
        c, app = self._client_with_svc(mem_repo, svc)
        try:
            c.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            stored = mem_repo.get(draft.lab_id)
            assert stored.publish_status == PublishStatus.PUBLISH_BLOCKED
        finally:
            app.dependency_overrides.clear()

    def test_publish_calls_service(self, mem_repo):
        draft = _insert_draft(mem_repo)
        mock_svc = _MockPublishService(result=_make_draft(
            publish_status=PublishStatus.PUBLISHED,
            validator_results=[],
        ))
        c, app = self._client_with_svc(mem_repo, mock_svc)
        try:
            c.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            assert mock_svc.call_count == 1
        finally:
            app.dependency_overrides.clear()

    def test_404_for_missing_draft(self, mem_repo):
        svc = _AlwaysPassPublishService()
        c, app = self._client_with_svc(mem_repo, svc)
        try:
            r = c.post("/api/labgen/drafts/nonexistent/publish")
            assert r.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_403_without_admin(self, non_admin_client):
        r = non_admin_client.post("/api/labgen/drafts/some-id/publish")
        assert r.status_code == 403

    def test_response_has_schema_version(self, mem_repo):
        draft = _insert_draft(mem_repo)
        svc = _AlwaysPassPublishService()
        c, app = self._client_with_svc(mem_repo, svc)
        try:
            r = c.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            assert r.json()["schema_version"] == "1.0"
        finally:
            app.dependency_overrides.clear()
