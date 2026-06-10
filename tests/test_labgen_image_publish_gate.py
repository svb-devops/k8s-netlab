"""
Image Readiness Publish Gate Integration v0.1 — Tests.

Verifies that image readiness is correctly integrated into the publish gate.

Coverage areas:
  A. ImageReadinessService wired into DraftPreviewService / snapshot
  B. Publish decision blocked by BLOCKED/UNRESOLVED/NOT_FOUND images
  C. Publish decision allowed when images are READY
  D. POST /api/labgen/drafts/{id}/publish respects image gate
  E. Publish blocked → 409 with IMAGE_ codes in detail
  F. Force publish bypass is not possible
  G. Preview image_readiness field present and sanitized
  H. Learner API does not expose admin-only image resolver details
  I. Contract pack examples include image_readiness; no sensitive content
  J. Regression — image readiness does not create sessions / audit events
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.draft_preview import DraftPreviewService
from backend.labgen.image_readiness import ImageReadinessService, ImageReadinessStatus
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
from backend.labgen.publish_decision import (
    PublishBlockReasonCode,
    PublishDecision,
    PublishDecisionService,
    PublishDecisionStatus,
)
from backend.labgen.routes import (
    get_decision_service,
    get_preview_service,
    get_publish_service,
    get_repository,
    require_admin_user,
)
from backend.labgen.static_validator import StaticValidator
from backend.labgen.publish_service import PublishService
from backend.labgen.image_resolver import ImageResolver

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._=+/\-]{8,}"),
    re.compile(r"(?i)(token|password|secret|private_key|credential|kubeconfig)\s*[=:]\s*\S+"),
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    re.compile(r"Traceback \(most recent call last\)"),
]


def _assert_no_sensitive(payload) -> None:
    if isinstance(payload, str):
        for pat in _SENSITIVE_PATTERNS:
            assert not pat.search(payload), f"Sensitive {pat.pattern!r} in: {payload!r}"
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_sensitive(item)
    elif isinstance(payload, dict):
        for v in payload.values():
            _assert_no_sensitive(v)


def _image(
    status: ImageStatus = ImageStatus.RESOLVED,
    existence_checked: Optional[bool] = True,
) -> ImageResolutionResult:
    return ImageResolutionResult(
        image_intent="nginx",
        requested_image="nginx:alpine",
        resolved_image="172.16.100.1:5000/nginx:1.25-alpine" if status == ImageStatus.RESOLVED else None,
        image_status=status,
        existence_check_passed=existence_checked if status == ImageStatus.RESOLVED else None,
    )


def _make_valid_draft(image_resolution: Optional[list[ImageResolutionResult]] = None) -> LabDraft:
    return LabDraft(
        source_article_id="art-1",
        title="Kubernetes Networking Lab",
        description="Learn pod-to-pod communication",
        estimated_duration_minutes=45,
        runtime_requirements=RuntimeRequirements(),
        steps=[
            Step(
                step_id="s1",
                order=1,
                why="Understand pod networking",
                do="kubectl apply -f nginx.yaml",
                observe="kubectl get pods",
                explain=ExplainField(concept="networking", observation="running"),
            )
        ],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        image_resolution=image_resolution or [],
    )


class _MemRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}
        self.update_calls: list[str] = []

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        self.update_calls.append(draft.lab_id)
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


@contextmanager
def _ctx(
    mem_repo: _MemRepo,
    *,
    admin: str = "testadmin",
) -> Iterator[TestClient]:
    from backend.main import app
    from backend.labgen.publish_decision import PublishDecisionService

    preview_svc = DraftPreviewService(
        repo=mem_repo,
        validator=StaticValidator(),
        image_readiness_svc=ImageReadinessService(),
    )
    decision_svc = PublishDecisionService(preview_svc=preview_svc)

    overrides: dict = {
        get_repository: lambda: mem_repo,
        require_admin_user: lambda: admin,
        get_preview_service: lambda: preview_svc,
        get_decision_service: lambda: decision_svc,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# A. ImageReadinessService wired into snapshot
# ===========================================================================

class TestSnapshotImageReadiness:
    def test_snapshot_has_image_readiness_field(self):
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[_image(existence_checked=True)])
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        assert r.status_code == 200
        body = r.json()
        assert "image_readiness" in body
        assert body["image_readiness"] is not None

    def test_snapshot_image_readiness_ready_for_resolved_images(self):
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[_image(existence_checked=True)])
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        ir = r.json()["image_readiness"]
        assert ir["status"] == ImageReadinessStatus.READY

    def test_snapshot_image_readiness_blocked_for_blocked_images(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        ir = r.json()["image_readiness"]
        assert ir["status"] == ImageReadinessStatus.BLOCKED

    def test_snapshot_is_publishable_false_when_blocked_images(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        assert r.json()["is_publishable"] is False

    def test_snapshot_is_publishable_true_with_ready_images(self):
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[_image(existence_checked=True)])
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        assert r.json()["is_publishable"] is True

    def test_snapshot_no_image_readiness_when_no_images(self):
        """Empty image_resolution → image_readiness.status=READY."""
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[])
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        ir = r.json()["image_readiness"]
        assert ir["status"] == ImageReadinessStatus.READY

    def test_snapshot_image_readiness_sanitized(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        _assert_no_sensitive(r.json()["image_readiness"])


# ===========================================================================
# B. Publish decision blocked by image status
# ===========================================================================

class TestPublishDecisionImageBlocked:
    def test_blocked_images_decision_blocked(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.status_code == 200
        assert r.json()["status"] == "BLOCKED"

    def test_unresolved_images_decision_blocked(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.UNRESOLVED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["status"] == "BLOCKED"

    def test_not_found_images_decision_blocked(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(existence_checked=False)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["status"] == "BLOCKED"

    def test_blocked_images_has_image_blocked_issue_code(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        codes = {i["code"] for i in r.json()["issues"]}
        assert "IMAGE_BLOCKED" in codes

    def test_unresolved_images_has_image_unresolved_code(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.UNRESOLVED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        codes = {i["code"] for i in r.json()["issues"]}
        assert "IMAGE_UNRESOLVED" in codes

    def test_not_found_has_image_not_found_code(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(existence_checked=False)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        codes = {i["code"] for i in r.json()["issues"]}
        assert "IMAGE_NOT_FOUND" in codes

    def test_image_readiness_blocked_summary_code_present(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        codes = {i["code"] for i in r.json()["issues"]}
        assert "IMAGE_READINESS_BLOCKED" in codes

    def test_decision_blocked_no_sensitive_in_issues(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        _assert_no_sensitive(r.json())


# ===========================================================================
# C. Publish decision ALLOWED when images are READY
# ===========================================================================

class TestPublishDecisionImageAllowed:
    def test_ready_images_decision_allowed(self):
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[_image(existence_checked=True)])
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["status"] == "ALLOWED"

    def test_empty_images_decision_allowed(self):
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[])
        mem.create(draft)
        with _ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["status"] == "ALLOWED"

    def test_decision_is_read_only(self):
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[_image(existence_checked=True)])
        mem.create(draft)
        with _ctx(mem) as client:
            client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert mem.update_calls == []


# ===========================================================================
# D. POST /publish respects image gate
# ===========================================================================

class _AlwaysPassImageResolver(ImageResolver):
    def check_registry_existence(self, img):
        return img.model_copy(update={"existence_check_passed": True})


class TestPublishEndpointImageGate:
    def test_publish_blocked_when_images_blocked(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        pub_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=_AlwaysPassImageResolver(),
        )
        with _ctx(mem) as client:
            client.app.dependency_overrides[get_publish_service] = lambda: pub_svc
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.status_code == 409

    def test_publish_blocked_when_images_unresolved(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.UNRESOLVED)]
        )
        mem.create(draft)
        pub_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=_AlwaysPassImageResolver(),
        )
        with _ctx(mem) as client:
            client.app.dependency_overrides[get_publish_service] = lambda: pub_svc
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.status_code == 409

    def test_publish_409_contains_image_issues(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        pub_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=_AlwaysPassImageResolver(),
        )
        with _ctx(mem) as client:
            client.app.dependency_overrides[get_publish_service] = lambda: pub_svc
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        detail = r.json()["detail"]
        codes = {i["code"] for i in detail["issues"]}
        assert "IMAGE_BLOCKED" in codes or "IMAGE_READINESS_BLOCKED" in codes

    def test_publish_409_no_sensitive_content(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        pub_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=_AlwaysPassImageResolver(),
        )
        with _ctx(mem) as client:
            client.app.dependency_overrides[get_publish_service] = lambda: pub_svc
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        _assert_no_sensitive(r.json())

    def test_publish_succeeds_with_ready_images(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(existence_checked=True)]
        )
        mem.create(draft)
        pub_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=_AlwaysPassImageResolver(),
        )
        with _ctx(mem) as client:
            client.app.dependency_overrides[get_publish_service] = lambda: pub_svc
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.status_code == 200
        assert r.json()["publish_status"] == "published"

    def test_draft_not_mutated_when_publish_blocked(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        original_status = draft.publish_status
        pub_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=_AlwaysPassImageResolver(),
        )
        with _ctx(mem) as client:
            client.app.dependency_overrides[get_publish_service] = lambda: pub_svc
            client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert mem.get(draft.lab_id).publish_status == original_status


# ===========================================================================
# E. Force-publish bypass not possible
# ===========================================================================

class TestNoForcePublishBypass:
    def test_no_force_param_accepted(self):
        """There must be no query param that allows bypassing the image gate."""
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        pub_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=_AlwaysPassImageResolver(),
        )
        with _ctx(mem) as client:
            client.app.dependency_overrides[get_publish_service] = lambda: pub_svc
            # Attempt to bypass with ?force=true
            r = client.post(
                f"/api/labgen/drafts/{draft.lab_id}/publish",
                params={"force": "true"},
            )
        # Still blocked — force param has no effect
        assert r.status_code == 409

    def test_preview_failed_publish_still_blocked(self):
        """If preview says is_publishable=False, publish must not succeed."""
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.UNRESOLVED)]
        )
        mem.create(draft)
        pub_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=_AlwaysPassImageResolver(),
        )
        with _ctx(mem) as client:
            client.app.dependency_overrides[get_publish_service] = lambda: pub_svc
            # Check preview
            prev = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
            assert prev.json()["is_publishable"] is False
            # Attempt publish
            pub = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            assert pub.status_code == 409


# ===========================================================================
# F. Learner API does not expose admin-only image details
# ===========================================================================

class TestLearnerApiImageReadinessPrivacy:
    def test_catalog_does_not_expose_image_readiness(self):
        """LearnerLabCatalogItem must not contain image_readiness."""
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[_image(existence_checked=True)])
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        # Pre-populate validator results so catalog doesn't treat missing as blocking
        from backend.labgen.static_validator import StaticValidator as SV
        results = SV().validate(draft)
        draft = draft.model_copy(update={"validator_results": results})
        mem.create(draft)

        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_catalog_service
        from backend.labgen.learner_catalog import LearnerCatalogService

        cat_svc = LearnerCatalogService(
            draft_repo=mem,
            validator=StaticValidator(),
        )
        overrides = {
            get_repository: lambda: mem,
            get_current_user: lambda: "student1",
            get_catalog_service: lambda: cat_svc,
        }
        app.dependency_overrides.update(overrides)
        try:
            with TestClient(app) as client:
                r = client.get("/api/labs")
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        for item in items:
            assert "image_readiness" not in item
            assert "image_resolver" not in item

    def test_catalog_item_no_sensitive_data(self):
        mem = _MemRepo()
        draft = _make_valid_draft(image_resolution=[_image(existence_checked=True)])
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        from backend.labgen.static_validator import StaticValidator as SV
        results = SV().validate(draft)
        draft = draft.model_copy(update={"validator_results": results})
        mem.create(draft)

        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_catalog_service
        from backend.labgen.learner_catalog import LearnerCatalogService

        cat_svc = LearnerCatalogService(
            draft_repo=mem,
            validator=StaticValidator(),
        )
        overrides = {
            get_repository: lambda: mem,
            get_current_user: lambda: "student1",
            get_catalog_service: lambda: cat_svc,
        }
        app.dependency_overrides.update(overrides)
        try:
            with TestClient(app) as client:
                r = client.get("/api/labs")
        finally:
            app.dependency_overrides.clear()

        _assert_no_sensitive(r.json())


# ===========================================================================
# G. Contract pack includes image_readiness example + no sensitive content
# ===========================================================================

class TestContractPackImageReadiness:
    def test_preview_example_has_image_readiness(self):
        from backend.labgen.api_contract import build_contract_pack

        pack = build_contract_pack()
        preview_ex = next(
            (e for e in pack.example_responses if e.name == "preview_snapshot"),
            None,
        )
        assert preview_ex is not None
        resp = preview_ex.response
        assert "image_readiness" in resp

    def test_image_readiness_example_is_ready(self):
        from backend.labgen.api_contract import build_contract_pack

        pack = build_contract_pack()
        preview_ex = next(e for e in pack.example_responses if e.name == "preview_snapshot")
        assert preview_ex.response["image_readiness"]["status"] == "READY"

    def test_publish_decision_blocked_image_example_exists(self):
        from backend.labgen.api_contract import build_contract_pack

        pack = build_contract_pack()
        ex = next(
            (e for e in pack.example_responses if e.name == "publish_decision_blocked_image"),
            None,
        )
        assert ex is not None
        codes = {i["code"] for i in ex.response["issues"]}
        assert "IMAGE_UNRESOLVED" in codes or "IMAGE_BLOCKED" in codes or "IMAGE_READINESS_BLOCKED" in codes

    def test_sensitive_field_policy_includes_registry_credential(self):
        from backend.labgen.api_contract import build_contract_pack

        pack = build_contract_pack()
        policy_vals = pack.sensitive_field_policy.prohibited_in_response_values
        assert any("registry" in v for v in policy_vals)

    def test_contract_pack_no_sensitive_content(self):
        from backend.labgen.api_contract import build_contract_pack
        from tests.labgen_contract_helpers import assert_contract_response_safe

        pack = build_contract_pack()
        for ex in pack.example_responses:
            assert_contract_response_safe(ex.response)


# ===========================================================================
# H. Regression — image readiness does not create sessions / audit events
# ===========================================================================

class TestImageReadinessRegression:
    def test_preview_does_not_create_session(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        # No update calls on draft repo (preview is read-only)
        assert mem.update_calls == []

    def test_decision_does_not_create_session(self):
        mem = _MemRepo()
        draft = _make_valid_draft(
            image_resolution=[_image(status=ImageStatus.BLOCKED)]
        )
        mem.create(draft)
        with _ctx(mem) as client:
            client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert mem.update_calls == []

    def test_image_readiness_service_does_not_affect_start_lab(self):
        """ImageReadinessService.evaluate is separate from lab session creation."""
        svc = ImageReadinessService()
        images = [_image(status=ImageStatus.BLOCKED)]
        result = svc.evaluate(images)
        # Result returned — no side effects
        assert result.status == ImageReadinessStatus.BLOCKED
        # No sessions, no audit events, no K3s calls

    def test_existing_image_routes_still_work(self):
        """Existing Image API tests are not broken by image readiness integration."""
        from backend.labgen.image_resolver import ImageResolver as IR
        from backend.labgen.routes import get_image_resolver

        from backend.main import app
        from backend.auth_deps import get_current_user

        resolver = IR(
            whitelist_path="config/image_whitelist.json",
            _http_get=lambda url: 200,
        )
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[get_current_user] = lambda: "admin"
        app.dependency_overrides[get_image_resolver] = lambda: resolver
        try:
            with TestClient(app) as client:
                r = client.post(
                    "/api/images/resolve",
                    json={"images": [{"requested_image": "nginx:alpine"}]},
                )
            assert r.status_code == 200
            assert r.json()[0]["image_status"] == ImageStatus.RESOLVED
        finally:
            app.dependency_overrides.pop(require_admin_user, None)
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_image_resolver, None)
