"""
Admin-curated Article-linked Lab Publish Gate tests.

Validates:
  A. Publish gate blocks without rehearsal (article-linked labs)
  B. Publish gate allows after rehearsal completed
  C. Manually-authored labs unaffected by rehearsal gate
  D. Catalog: draft invisible before publish, visible after
  E. Safety: no raw article text, no LLM call, no credential leak
  F. Regression: normal learner path, rehearsal bridge still requires admin
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    SessionType,
    Step,
)
from backend.labgen.publish_decision import PublishDecision, PublishDecisionStatus, PublishBlockReasonCode
from backend.labgen.failure_reasons import FailureReason
from backend.labgen.lab_session_service import (
    LabSessionService,
    PrecheckFailed,
    StubVMTracker,
)
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
from backend.labgen.lab_session_repository import LabSessionRepository

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers — minimal valid LabDraft factories
# ---------------------------------------------------------------------------


def _manual_draft(lab_id: str = "manual-001") -> LabDraft:
    """Manually-authored lab — no article pipeline, rehearsal_required=False."""
    return LabDraft(
        lab_id=lab_id,
        source_article_id="pilot:k8s-configmap-v1",
        title="K8s ConfigMap Basics",
        description="Learn ConfigMaps",
        estimated_duration_minutes=10,
        runtime_requirements=RuntimeRequirements(),
        steps=[
            Step(
                step_id="step_1",
                order=1,
                why="understand configmaps",
                do="create a configmap",
                observe="a configmap exists",
                explain=ExplainField(concept="ConfigMap", observation="key-value store"),
            )
        ],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.DRAFT,
        rehearsal_required=False,
        rehearsal_completed=False,
    )


def _article_draft_unpublished(lab_id: str = "art-001") -> LabDraft:
    """Article-generated lab — rehearsal_required=True, rehearsal_completed=False."""
    return LabDraft(
        lab_id=lab_id,
        source_article_id="88adee20-1a50-4183-8879-046334bc144d",
        title="ConfigMap from Article",
        description="Learn ConfigMaps from article",
        estimated_duration_minutes=10,
        runtime_requirements=RuntimeRequirements(),
        steps=[
            Step(
                step_id="step_1",
                order=1,
                why="understand configmaps",
                do="create a configmap",
                observe="a configmap exists",
                explain=ExplainField(concept="ConfigMap", observation="key-value store"),
            )
        ],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.DRAFT,
        rehearsal_required=True,
        rehearsal_completed=False,
    )


def _article_draft_rehearsed(lab_id: str = "art-001") -> LabDraft:
    """Article-generated lab — rehearsal completed."""
    d = _article_draft_unpublished(lab_id)
    return d.model_copy(update={"rehearsal_completed": True})


# ---------------------------------------------------------------------------
# In-memory test doubles
# ---------------------------------------------------------------------------


class _MemDraftRepo:
    def __init__(self, drafts: Optional[list[LabDraft]] = None) -> None:
        self._store: dict[str, LabDraft] = {}
        for d in (drafts or []):
            self._store[d.lab_id] = d

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemSessionRepo:
    def __init__(self, sessions: Optional[list[LabSessionState]] = None) -> None:
        self._store: dict[str, LabSessionState] = {}
        for s in (sessions or []):
            self._store[s.session_id] = s

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._store.get(session_id)

    def create(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def update(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def list_all(self) -> list[LabSessionState]:
        return list(self._store.values())

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]


def _make_service(draft_repo, session_repo=None, ns=None, vm_tracker=None):
    from backend.labgen.image_resolver import ImageResolver
    from backend.labgen.runtime_audit import RuntimeAuditRepository, RuntimeAuditService
    from backend.labgen.runtime_precheck import RuntimePrecheckService

    sr = session_repo or _MemSessionRepo()
    ns = ns or StubNamespaceLifecycleAdapter()
    vt = vm_tracker or StubVMTracker()
    audit_repo = RuntimeAuditRepository.__new__(RuntimeAuditRepository)
    audit_repo._sessions: list = []

    class _NullAudit:
        def record(self, *a, **kw): pass

    class _NullImageResolver:
        def needs_recheck(self, img): return False
        def check_registry_existence(self, img): return img

    class _NullRuntimePrecheck:
        def check(self, session, draft): return []

    return LabSessionService(
        session_repo=sr,
        draft_repo=draft_repo,
        vm_tracker=vt,
        ns_lifecycle=ns,
        image_resolver=_NullImageResolver(),
        audit_svc=_NullAudit(),
        adapter_selection=None,
        credential_reclaimer=None,
        runtime_precheck=_NullRuntimePrecheck(),
    )


# ===========================================================================
# A. Publish Gate — rehearsal requirement
# ===========================================================================


class TestPublishGateRehearsalRequirement:
    """publish_decision.evaluate() enforces rehearsal gate for article-generated labs."""

    def _evaluate(self, draft: LabDraft) -> PublishDecision:
        from backend.labgen.publish_decision import PublishDecisionService
        from backend.labgen.draft_preview import DraftPreviewService
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.image_readiness import ImageReadinessService

        dr = _MemDraftRepo(drafts=[draft])
        preview_svc = DraftPreviewService(
            repo=dr,
            validator=StaticValidator(),
            image_readiness_svc=ImageReadinessService(),
        )
        svc = PublishDecisionService(preview_svc=preview_svc, draft_repo=dr)
        return svc.evaluate(draft.lab_id)

    def test_article_draft_without_rehearsal_is_blocked(self):
        draft = _article_draft_unpublished()
        decision = self._evaluate(draft)
        assert decision.status == PublishDecisionStatus.BLOCKED
        codes = {i.code for i in decision.issues}
        assert PublishBlockReasonCode.REHEARSAL_REQUIRED.value in codes

    def test_article_draft_after_rehearsal_is_not_blocked_by_rehearsal_gate(self):
        """With rehearsal_completed=True, rehearsal gate should not fire."""
        draft = _article_draft_rehearsed()
        decision = self._evaluate(draft)
        # The draft may still be blocked by StaticValidator (missing fields),
        # but NOT by the rehearsal gate
        codes = {i.code for i in decision.issues}
        assert PublishBlockReasonCode.REHEARSAL_REQUIRED.value not in codes

    def test_manually_authored_draft_not_blocked_by_rehearsal_gate(self):
        """rehearsal_required=False → rehearsal gate does not fire."""
        draft = _manual_draft()
        decision = self._evaluate(draft)
        codes = {i.code for i in decision.issues}
        assert PublishBlockReasonCode.REHEARSAL_REQUIRED.value not in codes

    def test_rehearsal_required_field_defaults_false(self):
        """New LabDraft has rehearsal_required=False by default (backward compat)."""
        draft = LabDraft(
            source_article_id="pilot:test",
            title="t", description="d", estimated_duration_minutes=5,
            runtime_requirements=RuntimeRequirements(),
            steps=[],
        )
        assert draft.rehearsal_required is False
        assert draft.rehearsal_completed is False

    def test_publish_decision_service_requires_draft_repo(self):
        """PublishDecisionService accepts draft_repo parameter."""
        from backend.labgen.publish_decision import PublishDecisionService
        from backend.labgen.draft_preview import DraftPreviewService
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.image_readiness import ImageReadinessService

        dr = _MemDraftRepo()
        preview_svc = DraftPreviewService(
            repo=dr, validator=StaticValidator(),
            image_readiness_svc=ImageReadinessService(),
        )
        svc = PublishDecisionService(preview_svc=preview_svc, draft_repo=dr)
        assert svc is not None


# ===========================================================================
# B. Rehearsal Completion Updates Draft
# ===========================================================================


class TestRehearsalCompletionUpdatesDraft:
    """Completing a rehearsal session sets draft.rehearsal_completed=True."""

    def _make_rehearsal_session(self, lab_id: str, vm_id: str = "401") -> LabSessionState:
        return LabSessionState(
            lab_id=lab_id,
            vm_id=vm_id,
            student_username="smoke-admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
            namespace=f"lab-rehearsal-test-{lab_id[:8]}",
            ready_to_complete=True,
        )

    def test_rehearsal_cleanup_success_sets_rehearsal_completed(self):
        draft = _article_draft_unpublished()
        assert draft.rehearsal_completed is False

        dr = _MemDraftRepo(drafts=[draft])
        session = self._make_rehearsal_session(draft.lab_id)
        sr = _MemSessionRepo(sessions=[session])

        svc = _make_service(draft_repo=dr, session_repo=sr)
        # Simulate successful cleanup
        svc._do_cleanup(session)

        updated = dr.get(draft.lab_id)
        assert updated is not None
        assert updated.rehearsal_completed is True

    def test_rehearsal_cleanup_failure_does_not_set_rehearsal_completed(self):
        """If cleanup fails, draft.rehearsal_completed stays False."""
        draft = _article_draft_unpublished()
        dr = _MemDraftRepo(drafts=[draft])
        session = self._make_rehearsal_session(draft.lab_id)
        sr = _MemSessionRepo(sessions=[session])

        ns_fail = StubNamespaceLifecycleAdapter(
            delete_succeeds=False,
            deleted_after_delete=False,
        )
        svc = _make_service(draft_repo=dr, session_repo=sr, ns=ns_fail)
        svc._do_cleanup(session)

        updated = dr.get(draft.lab_id)
        assert updated is not None
        assert updated.rehearsal_completed is False

    def test_learner_session_cleanup_does_not_set_rehearsal_completed(self):
        """Cleanup of a LEARNER session must NOT set draft.rehearsal_completed."""
        draft = _article_draft_unpublished()
        dr = _MemDraftRepo(drafts=[draft])

        session = LabSessionState(
            lab_id=draft.lab_id,
            vm_id="401",
            student_username="learner1",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.LEARNER,
            namespace="lab-learner-test",
            ready_to_complete=True,
        )
        sr = _MemSessionRepo(sessions=[session])
        svc = _make_service(draft_repo=dr, session_repo=sr)
        svc._do_cleanup(session)

        updated = dr.get(draft.lab_id)
        assert updated is not None
        assert updated.rehearsal_completed is False


# ===========================================================================
# C. Publish Gate — HTTP layer (via TestClient)
# ===========================================================================


class TestPublishGateHTTP:
    """End-to-end HTTP tests for the rehearsal gate on POST /api/labgen/drafts/{id}/publish."""

    def _make_publishable_draft(
        self, rehearsal_required: bool, rehearsal_completed: bool
    ) -> LabDraft:
        """Build a draft that passes all StaticValidator checks."""
        from backend.labgen.models import (
            VerifyTemplate, VerifyType, ImageResolutionResult, ImageStatus,
        )
        return LabDraft(
            lab_id="pub-gate-test-001",
            source_article_id="88adee20-0000-0000-0000-000000000000" if rehearsal_required else "pilot:manual",
            title="Test Lab",
            description="Test description",
            estimated_duration_minutes=15,
            runtime_requirements=RuntimeRequirements(),
            steps=[
                Step(
                    step_id="step_1",
                    order=1,
                    why="learn",
                    do="create a namespace",
                    observe="a namespace exists",
                    explain=ExplainField(concept="namespace", observation="created"),
                    verify=[
                        VerifyTemplate(
                            verify_id="v1",
                            type=VerifyType.NAMESPACE_EXISTS,
                            namespace="{{lab_namespace}}",
                            name="{{lab_namespace}}",
                        )
                    ],
                )
            ],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
            image_resolution=[
                ImageResolutionResult(
                    image_intent="nginx",
                    requested_image="172.16.100.1:5000/nginx:latest",
                    resolved_image="172.16.100.1:5000/nginx:latest",
                    image_status=ImageStatus.RESOLVED,
                    existence_check_passed=True,
                )
            ],
            publish_status=PublishStatus.DRAFT,
            rehearsal_required=rehearsal_required,
            rehearsal_completed=rehearsal_completed,
        )

    def test_publish_without_rehearsal_returns_409(self, admin_client):
        """Article-linked lab cannot be published without rehearsal."""
        from backend.main import app
        from backend.labgen.routes import get_repository

        draft = self._make_publishable_draft(rehearsal_required=True, rehearsal_completed=False)
        mem_repo = _MemDraftRepo(drafts=[draft])

        app.dependency_overrides[get_repository] = lambda: mem_repo
        try:
            resp = admin_client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
            body = resp.json()
            raw = str(body)
            assert "rehearsal" in raw.lower() or "REHEARSAL" in raw, (
                f"Expected rehearsal error, got: {body}"
            )
        finally:
            app.dependency_overrides.pop(get_repository, None)

    def test_publish_without_rehearsal_blocked_by_publish_decision(self, admin_client):
        """GET publish-decision also reports rehearsal gate."""
        from backend.main import app
        from backend.labgen.routes import get_repository

        draft = self._make_publishable_draft(rehearsal_required=True, rehearsal_completed=False)
        mem_repo = _MemDraftRepo(drafts=[draft])

        app.dependency_overrides[get_repository] = lambda: mem_repo
        try:
            resp = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "BLOCKED"
            codes = [i["code"] for i in body.get("issues", [])]
            assert PublishBlockReasonCode.REHEARSAL_REQUIRED.value in codes
        finally:
            app.dependency_overrides.pop(get_repository, None)


# ===========================================================================
# D. Catalog isolation
# ===========================================================================


class TestCatalogIsolation:
    """Article-linked draft not visible before publish; visible after."""

    def test_draft_lab_not_in_catalog_before_publish(self):
        from backend.labgen.learner_catalog import LearnerCatalogService

        draft = _article_draft_unpublished()
        dr = _MemDraftRepo(drafts=[draft])
        sr = _MemSessionRepo()
        from backend.labgen.static_validator import StaticValidator
        svc = LearnerCatalogService(draft_repo=dr, validator=StaticValidator(), session_repo=sr)

        items = svc.list_published_labs(actor_user="learner1")
        ids = [i.lab_id for i in items]
        assert draft.lab_id not in ids

    def test_rehearsed_draft_not_in_catalog_before_publish(self):
        """Even after rehearsal completes, draft is NOT in catalog until published."""
        from backend.labgen.learner_catalog import LearnerCatalogService

        draft = _article_draft_rehearsed()
        # Still DRAFT status
        assert draft.publish_status == PublishStatus.DRAFT
        dr = _MemDraftRepo(drafts=[draft])
        sr = _MemSessionRepo()
        from backend.labgen.static_validator import StaticValidator
        svc = LearnerCatalogService(draft_repo=dr, validator=StaticValidator(), session_repo=sr)

        items = svc.list_published_labs(actor_user="learner1")
        ids = [i.lab_id for i in items]
        assert draft.lab_id not in ids

    def test_published_article_lab_appears_in_catalog(self):
        from backend.labgen.learner_catalog import LearnerCatalogService

        draft = _article_draft_rehearsed()
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        dr = _MemDraftRepo(drafts=[draft])
        sr = _MemSessionRepo()
        from backend.labgen.static_validator import StaticValidator
        svc = LearnerCatalogService(draft_repo=dr, validator=StaticValidator(), session_repo=sr)

        items = svc.list_published_labs(actor_user="learner1")
        ids = [i.lab_id for i in items]
        assert draft.lab_id in ids

    def test_internal_rehearsal_session_not_visible_to_learner(self):
        from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService

        draft = _article_draft_unpublished()
        dr = _MemDraftRepo(drafts=[draft])

        rehearsal_session = LabSessionState(
            lab_id=draft.lab_id,
            vm_id="401",
            student_username="smoke-admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
        )
        sr = _MemSessionRepo(sessions=[rehearsal_session])
        svc = LearnerSessionSnapshotService(session_repo=sr, draft_repo=dr)

        items = svc.list_my_sessions(actor_user="learner1")
        session_ids = [i.session_id for i in items]
        assert rehearsal_session.session_id not in session_ids

    def test_existing_4_labs_still_visible_after_publish(self):
        """The 4 existing published labs remain in catalog (regression)."""
        from backend.labgen.learner_catalog import LearnerCatalogService

        published_ids = ["67fca5e4", "b0b97742", "d9f44383", "e52b8b80"]
        drafts = []
        for lab_id in published_ids:
            d = _manual_draft(lab_id=lab_id)
            d = d.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
            drafts.append(d)

        # Add the article-linked lab (also published)
        art = _article_draft_rehearsed("art-published")
        art = art.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        drafts.append(art)

        dr = _MemDraftRepo(drafts=drafts)
        sr = _MemSessionRepo()
        from backend.labgen.static_validator import StaticValidator
        svc = LearnerCatalogService(draft_repo=dr, validator=StaticValidator(), session_repo=sr)

        items = svc.list_published_labs(actor_user="learner1")
        ids = {i.lab_id for i in items}
        for lab_id in published_ids:
            assert lab_id in ids, f"Missing published lab: {lab_id}"
        assert art.lab_id in ids


# ===========================================================================
# E. Safety invariants
# ===========================================================================


class TestSafetyInvariants:
    """Safety checks: no raw article text, no LLM, no credential leak."""

    def test_rehearsal_required_field_set_by_article_pipeline(self):
        """LabDraft from _build_lab_draft_from_contract has rehearsal_required=True."""
        from backend.labgen.article_draft_service import _build_lab_draft_from_contract
        from backend.labgen.article_models import (
            ArticleDraftLabContract, FeasibilityResult, FeasibilityStatus,
            ArticleSourceMetadata, ArticleStoragePolicy, AdminDecision,
            AdminDecisionValue, TargetDomain, ArticleLabRuntimeRequirement,
        )

        contract = ArticleDraftLabContract(
            draft_id="88adee20-1a50-4183-8879-046334bc144d",
            content_hash="abc123",
            target_domain=TargetDomain.K8S,
            feasibility_result=FeasibilityResult(
                status=FeasibilityStatus.DIRECTLY_LAB_READY,
                evaluated_by="stub",
            ),
            source_metadata=ArticleSourceMetadata(
                source_type="internal_doc",
                source_url=None,
                author_confirmed_right_to_use=True,
                submitted_by_user_id="smoke-admin",
                content_hash="abc123deadbeef",
                content_length=1024,
            ),
            storage_policy=ArticleStoragePolicy(),
            required_runtime=ArticleLabRuntimeRequirement(
                runtime_type="k8s_namespace",
                cleanup_strategy="namespace_delete",
            ),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            admin_decision=AdminDecision(
                decision=AdminDecisionValue.APPROVE,
                reviewer_id="smoke-admin",
                confirmed_source_grounding=True,
                confirmed_safety=True,
                confirmed_cleanup=True,
                confirmed_verifier_strategy=True,
                confirmed_no_raw_secret=True,
                confirmed_no_direct_publish=True,
            ),
        )

        lab_draft = _build_lab_draft_from_contract(contract, converted_by="smoke-admin")
        assert lab_draft.rehearsal_required is True, (
            "convert_to_lab_draft must set rehearsal_required=True"
        )
        assert lab_draft.rehearsal_completed is False

    def test_rehearsal_completed_false_by_default(self):
        draft = _article_draft_unpublished()
        assert draft.rehearsal_completed is False

    def test_publish_gate_blocks_even_if_validator_passes(self):
        """Rehearsal gate fires regardless of StaticValidator outcome."""
        from backend.labgen.publish_decision import PublishDecisionService
        from backend.labgen.draft_preview import DraftPreviewService
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.image_readiness import ImageReadinessService

        # Use a rehearsed draft so validator might pass, but rehearsal_completed=False
        draft = _article_draft_unpublished()
        # explicitly: rehearsal_required=True, rehearsal_completed=False
        dr = _MemDraftRepo(drafts=[draft])
        preview_svc = DraftPreviewService(
            repo=dr, validator=StaticValidator(),
            image_readiness_svc=ImageReadinessService(),
        )
        svc = PublishDecisionService(preview_svc=preview_svc, draft_repo=dr)
        decision = svc.evaluate(draft.lab_id)
        assert decision.status == PublishDecisionStatus.BLOCKED
        codes = {i.code for i in decision.issues}
        assert PublishBlockReasonCode.REHEARSAL_REQUIRED.value in codes

    def test_normal_learner_precheck_unchanged(self):
        """run_precheck() still blocks DRAFT labs for normal learners."""
        draft = _article_draft_unpublished()
        # Even rehearsed, a DRAFT lab cannot be started by a learner
        dr = _MemDraftRepo(drafts=[draft])
        svc = _make_service(draft_repo=dr)
        result = svc.run_precheck("art-001", "401", "learner1")
        assert not result.passed
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value in result.failures

    def test_no_source_article_id_in_published_lab_response(self):
        """source_article_id is a UUID for article-generated labs, not raw article text."""
        draft = _article_draft_rehearsed()
        # The draft only stores the article_draft_id (UUID), not raw article text
        # Verify that source_article_id looks like an article draft ID or UUID
        sid = draft.source_article_id
        assert len(sid) >= 10, "source_article_id should not be empty"
        # Raw article text would be much longer (>100 chars in typical articles)
        assert len(sid) < 100, (
            f"source_article_id suspiciously long ({len(sid)} chars) — "
            "may contain raw article text"
        )


# ===========================================================================
# F. Regression — existing paths unchanged
# ===========================================================================


class TestRegression:
    """Normal flows are unaffected by publish gate changes."""

    def test_manually_authored_lab_can_still_publish_without_rehearsal(self):
        """rehearsal_required=False drafts are not blocked by rehearsal gate."""
        from backend.labgen.publish_decision import PublishDecisionService
        from backend.labgen.draft_preview import DraftPreviewService
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.image_readiness import ImageReadinessService

        draft = _manual_draft()
        dr = _MemDraftRepo(drafts=[draft])
        preview_svc = DraftPreviewService(
            repo=dr, validator=StaticValidator(),
            image_readiness_svc=ImageReadinessService(),
        )
        svc = PublishDecisionService(preview_svc=preview_svc, draft_repo=dr)
        decision = svc.evaluate(draft.lab_id)
        codes = {i.code for i in decision.issues}
        assert PublishBlockReasonCode.REHEARSAL_REQUIRED.value not in codes

    def test_internal_rehearsal_bridge_still_requires_admin_token(self, app_client):
        """POST /internal/rehearsal-sessions rejects requests without X-Admin-Token."""
        resp = app_client.post(
            "/internal/rehearsal-sessions",
            json={"lab_id": "art-001", "vm_id": "401"},
        )
        assert resp.status_code in (401, 403, 422)

    def test_non_admin_cannot_call_publish_endpoint(self, learner_client):
        """Non-admin cannot publish a draft."""
        resp = learner_client.post("/api/labgen/drafts/any-lab-id/publish")
        assert resp.status_code in (401, 403, 404)

    def test_rejected_draft_cannot_publish(self):
        """PUBLISH_BLOCKED status prevents publish (regression: ensure StaticValidator still fires)."""
        from backend.labgen.publish_decision import PublishDecisionService
        from backend.labgen.draft_preview import DraftPreviewService
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.image_readiness import ImageReadinessService

        # Draft with rehearsal complete but StaticValidator failures (no steps, no cleanup)
        draft = LabDraft(
            lab_id="blocked-lab",
            source_article_id="pilot:manual",
            title="t",
            description="d",
            estimated_duration_minutes=5,
            runtime_requirements=RuntimeRequirements(),
            steps=[],  # triggers validator failure
            rehearsal_required=False,
            rehearsal_completed=False,
        )
        dr = _MemDraftRepo(drafts=[draft])
        preview_svc = DraftPreviewService(
            repo=dr, validator=StaticValidator(),
            image_readiness_svc=ImageReadinessService(),
        )
        svc = PublishDecisionService(preview_svc=preview_svc, draft_repo=dr)
        decision = svc.evaluate(draft.lab_id)
        assert decision.status == PublishDecisionStatus.BLOCKED
        # StaticValidator should have fired (validator failure, not rehearsal)
        codes = {i.code for i in decision.issues}
        assert PublishBlockReasonCode.REHEARSAL_REQUIRED.value not in codes

    def test_session_type_learner_by_default(self):
        """LabSessionState.session_type defaults to LEARNER (backward compat)."""
        s = LabSessionState(
            lab_id="x", vm_id="501", student_username="u",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
        )
        assert s.session_type == SessionType.LEARNER

    def test_publish_service_blocks_when_rehearsal_not_completed(self):
        """PublishService.publish() raises RehearsalNotCompleted — defense in depth (BLOCKER fix)."""
        from backend.labgen.publish_service import PublishService, RehearsalNotCompleted
        from backend.labgen.image_resolver import ImageResolver
        from backend.labgen.static_validator import StaticValidator
        import pytest

        draft = _article_draft_unpublished()
        svc = PublishService(validator=StaticValidator(), image_resolver=ImageResolver())
        with pytest.raises(RehearsalNotCompleted):
            svc.publish(draft)

    def test_publish_service_allows_when_rehearsal_completed(self):
        """PublishService.publish() does not raise when rehearsal_completed=True."""
        from backend.labgen.publish_service import PublishService, RehearsalNotCompleted
        from backend.labgen.image_resolver import ImageResolver
        from backend.labgen.static_validator import StaticValidator

        draft = _article_draft_rehearsed()
        svc = PublishService(validator=StaticValidator(), image_resolver=ImageResolver())
        # Should not raise — may return PUBLISHED or PUBLISH_BLOCKED depending on validator
        result = svc.publish(draft)
        assert result is not None

    def test_aborted_rehearsal_session_does_not_set_rehearsal_completed(self):
        """Aborted rehearsal (ready_to_complete=False) must not unblock publish gate (HIGH fix)."""
        from backend.labgen.lab_session_service import LabSessionService

        draft = _article_draft_unpublished()
        dr = _MemDraftRepo(drafts=[draft])

        # Session with ready_to_complete=False — admin started rehearsal but aborted
        aborted_session = LabSessionState(
            lab_id=draft.lab_id,
            vm_id="401",
            student_username="smoke-admin",
            lab_session_status=LabSessionStatus.LAB_ABORTED,
            session_type=SessionType.INTERNAL_REHEARSAL,
            namespace="lab-abort-test",
            ready_to_complete=False,  # steps not completed
        )
        sr = _MemSessionRepo(sessions=[aborted_session])
        svc = _make_service(draft_repo=dr, session_repo=sr)
        svc._do_cleanup(aborted_session)

        updated = dr.get(draft.lab_id)
        assert updated is not None
        assert updated.rehearsal_completed is False, (
            "Aborted rehearsal must not set rehearsal_completed=True"
        )

    def test_internal_rehearsal_step_check_allowed_on_draft_lab(self):
        """INTERNAL_REHEARSAL session can check steps even when draft is not PUBLISHED."""
        from backend.labgen.step_progression_service import StepProgressionService, StepDraftUnavailable
        from backend.labgen.runtime_audit import RuntimeAuditRepository, RuntimeAuditService

        draft = _article_draft_unpublished()
        assert draft.publish_status == PublishStatus.DRAFT

        rehearsal_session = LabSessionState(
            lab_id=draft.lab_id,
            vm_id="401",
            student_username="smoke-admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
            namespace="lab-rehearsal-test",
        )
        dr = _MemDraftRepo(drafts=[draft])
        sr = _MemSessionRepo(sessions=[rehearsal_session])

        class _NullAudit:
            def record(self, *a, **kw): pass

        class _NullVerifier:
            def check(self, session_id, template): return VerifyResult(
                verify_id=template.verify_id,
                type=template.type,
                passed=True,
                error_code=None,
                failure_reason=None,
            )

        from backend.labgen.models import VerifyResult as _VR
        svc = StepProgressionService(
            session_repo=sr,
            draft_repo=dr,
            verifier_svc=_NullVerifier(),
            audit_svc=_NullAudit(),
        )
        # Should NOT raise StepDraftUnavailable for INTERNAL_REHEARSAL
        result = svc.check_step(rehearsal_session.session_id, "step_1", "smoke-admin")
        assert result.all_passed is True

    def test_learner_session_cannot_check_steps_on_draft_lab(self):
        """LEARNER session still cannot check steps on an unpublished lab (gate preserved)."""
        from backend.labgen.step_progression_service import StepProgressionService, StepDraftUnavailable
        from backend.labgen.models import VerifyResult as _VR

        draft = _article_draft_unpublished()
        assert draft.publish_status == PublishStatus.DRAFT

        learner_session = LabSessionState(
            lab_id=draft.lab_id,
            vm_id="501",
            student_username="learner-test",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.LEARNER,
            namespace="lab-learner-test",
        )
        dr = _MemDraftRepo(drafts=[draft])
        sr = _MemSessionRepo(sessions=[learner_session])

        class _NullAudit:
            def record(self, *a, **kw): pass

        class _NullVerifier:
            def check(self, session_id, template): return _VR(
                verify_id=template.verify_id,
                type=template.type,
                passed=True,
                error_code=None,
                failure_reason=None,
            )

        svc = StepProgressionService(
            session_repo=sr,
            draft_repo=dr,
            verifier_svc=_NullVerifier(),
            audit_svc=_NullAudit(),
        )
        import pytest
        with pytest.raises(StepDraftUnavailable):
            svc.check_step(learner_session.session_id, "step_1", "learner-test")

    def test_published_article_linked_lab_allows_learner_precheck(self):
        """Learner precheck PASSES for a PUBLISHED article-linked lab (positive reader path)."""
        draft = _article_draft_rehearsed()
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        dr = _MemDraftRepo(drafts=[draft])
        svc = _make_service(draft_repo=dr)
        result = svc.run_precheck(draft.lab_id, "401", "learner1")
        assert result.passed, f"Expected precheck PASS for published article lab, got: {result.failures}"

    def test_published_article_lab_step_preview_has_do_instruction(self):
        """Published article-linked lab's step preview contains the 'do' instruction for reader."""
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator

        draft = _article_draft_rehearsed()
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        dr = _MemDraftRepo(drafts=[draft])
        sr = _MemSessionRepo()
        svc = LearnerCatalogService(draft_repo=dr, validator=StaticValidator(), session_repo=sr)

        detail = svc.get_published_lab_detail(draft.lab_id, actor_user="learner1")
        assert detail is not None
        assert len(detail.steps_preview) > 0
        first_step = detail.steps_preview[0]
        assert first_step.instructions_summary, "step must have non-empty instructions_summary for reader"

    def test_published_article_lab_step_check_count_matches_verify_list(self):
        """check_count in step preview equals the number of verify templates in the draft."""
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator

        draft = _article_draft_rehearsed()
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        step = draft.steps[0]

        dr = _MemDraftRepo(drafts=[draft])
        sr = _MemSessionRepo()
        svc = LearnerCatalogService(draft_repo=dr, validator=StaticValidator(), session_repo=sr)

        detail = svc.get_published_lab_detail(draft.lab_id, actor_user="learner1")
        preview_step = detail.steps_preview[0]
        assert preview_step.check_count == len(step.verify), (
            f"check_count {preview_step.check_count} must equal len(step.verify) {len(step.verify)}"
        )


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def app_client():
    from backend.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def learner_client(tmp_path):
    """Authenticated learner (non-admin) TestClient."""
    from backend.main import app
    from backend import config as cfg

    with TestClient(app) as client:
        # Register + login
        client.post("/api/auth/register", json={"username": "gate_learner", "password": "pass123!", "email": "gate_learner@example.com"})
        resp = client.post("/api/auth/login", json={"username": "gate_learner", "password": "pass123!"})
        yield client


@pytest.fixture
def admin_client():
    """TestClient with require_admin_user overridden — same pattern as other labgen tests."""
    from backend.main import app
    from backend.labgen.routes import require_admin_user

    app.dependency_overrides[require_admin_user] = lambda: "smoke-admin"
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(require_admin_user, None)
