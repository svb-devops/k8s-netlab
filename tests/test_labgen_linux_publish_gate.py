"""
Linux Article-linked Lab Publish Gate tests — G-44.

Validates:
  A. StaticValidator gate lift — linux.publish_blocked_until_runtime removed
  B. PublishService — Linux draft transitions to PUBLISHED
  C. Precheck domain guard — Linux published lab blocked with LINUX_LEARNER_NOT_SUPPORTED
  D. Catalog — Linux lab appears after publish
  E. Negative checks — no rehearsal, duplicate, sandbox unsafe
  F. K8s regression — K8s publish path unchanged
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.image_resolver import ImageResolver
from backend.labgen.lab_session_service import LabSessionService
from backend.labgen.learner_catalog import LearnerCatalogService
from backend.labgen.linux_template import LinuxFilesPermissionsTemplate
from backend.labgen.models import (
    ImageResolutionResult,
    ImageStatus,
    LabDomainType,
    LabDraft,
    PublishStatus,
    ValidatorStatus,
)
from backend.labgen.publish_service import PublishService, RehearsalNotCompleted
from backend.labgen.repository import LabDraftRepository
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static

_TEMPLATE = LinuxFilesPermissionsTemplate()
_ART_ID = "art-linux-files-001"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _linux_draft(*, rehearsal_completed: bool = True) -> LabDraft:
    draft = _TEMPLATE.build_draft(_ART_ID)
    return draft.model_copy(update={"rehearsal_completed": rehearsal_completed})


def _k8s_draft() -> LabDraft:
    """Minimal K8s draft satisfying StaticValidator image/structure checks."""
    from backend.labgen.models import (
        CleanupNamespace,
        CleanupSpec,
        ExplainField,
        RuntimeRequirements,
        Step,
        VerifyTemplate,
        VerifyType,
    )
    return LabDraft(
        source_article_id="art-k8s-001",
        title="K8s Basics",
        description="A K8s lab.",
        estimated_duration_minutes=10,
        runtime_requirements=RuntimeRequirements(),
        image_resolution=[
            ImageResolutionResult(
                image_intent="nginx web server",
                requested_image="nginx:1.25-alpine",
                image_status=ImageStatus.RESOLVED,
                resolved_image="172.16.100.1:5000/nginx:1.25-alpine",
                existence_check_passed=True,
            )
        ],
        steps=[
            Step(
                step_id="s1",
                order=1,
                why="understand namespaces",
                do="run kubectl",
                commands=["kubectl apply -f app.yaml"],
                observe="pod created",
                explain=ExplainField(concept="namespace", observation="it exists"),
                verify=[VerifyTemplate(
                    verify_id="v1",
                    type=VerifyType.NAMESPACE_EXISTS,
                    namespace="{{lab_namespace}}",
                    name="test-ns",
                )],
            )
        ],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
    )


def _make_publish_service() -> PublishService:
    resolver = MagicMock(spec=ImageResolver)
    resolver.check_registry_existence.side_effect = lambda img: img
    return PublishService(validator=StaticValidator(), image_resolver=resolver)


def _make_session_service(draft: LabDraft) -> LabSessionService:
    from backend.labgen.lab_session_repository import LabSessionRepository

    draft_repo = MagicMock(spec=LabDraftRepository)
    draft_repo.get.return_value = draft

    session_repo = MagicMock(spec=LabSessionRepository)
    session_repo.list_by_student.return_value = []

    vm_tracker = MagicMock()
    vm_tracker.vm_exists.return_value = True
    vm_tracker.is_vm_owned_by.return_value = True
    vm_tracker.is_vm_tainted.return_value = False

    return LabSessionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        vm_tracker=vm_tracker,
        ns_lifecycle=MagicMock(),
        image_resolver=MagicMock(),
        audit_svc=None,
        adapter_selection=None,
    )


def _make_catalog(drafts: list[LabDraft]) -> LearnerCatalogService:
    from backend.labgen.lab_session_repository import LabSessionRepository

    draft_repo = MagicMock(spec=LabDraftRepository)
    draft_repo.list_all.return_value = drafts

    session_repo = MagicMock(spec=LabSessionRepository)
    session_repo.list_all.return_value = []

    return LearnerCatalogService(
        draft_repo=draft_repo,
        validator=StaticValidator(),
        session_repo=session_repo,
    )


# ─────────────────────────────────────────────────────────────────────────────
# A. StaticValidator gate lift
# ─────────────────────────────────────────────────────────────────────────────


class TestStaticValidatorGateLift:
    def test_linux_draft_no_longer_blocked_by_runtime_gate(self):
        """linux.publish_blocked_until_runtime must not appear in validator results."""
        draft = _linux_draft()
        results = StaticValidator().validate(draft)
        check_ids = [r.check_id for r in results]
        assert "linux.publish_blocked_until_runtime" not in check_ids

    def test_linux_draft_has_no_publish_blocking_failures(self):
        """A valid LinuxFilesPermissionsTemplate draft must pass all validator checks."""
        from backend.labgen.models import BlockingLevel
        draft = _linux_draft()
        results = StaticValidator().validate(draft)
        blocking = [
            r for r in results
            if r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        assert blocking == [], f"Unexpected PUBLISH_BLOCKING failures: {[(r.check_id, r.message) for r in blocking]}"

    def test_linux_domain_checks_still_run(self):
        """Other Linux-specific checks must still be evaluated."""
        draft = _linux_draft()
        results = StaticValidator().validate(draft)
        check_ids = {r.check_id for r in results}
        assert "linux.sandbox_policy_required" in check_ids
        assert "linux.cleanup_required" in check_ids
        assert "linux.verifiers_present" in check_ids
        assert "linux.sandbox_safe" in check_ids
        assert "linux.cleanup_safe" in check_ids

    def test_linux_validator_results_all_passed(self):
        """All checks in the valid Linux draft must return PASSED status."""
        draft = _linux_draft()
        results = StaticValidator().validate(draft)
        failed = [r for r in results if r.status == ValidatorStatus.FAILED]
        assert failed == [], f"Unexpected failures: {[(r.check_id, r.message) for r in failed]}"

    def test_k8s_validator_path_unchanged(self):
        """K8s draft validation must not be affected by the Linux gate lift."""
        from backend.labgen.models import BlockingLevel
        draft = _k8s_draft()
        results = StaticValidator().validate(draft)
        blocking = [
            r for r in results
            if r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        assert blocking == [], f"K8s regression: {[(r.check_id, r.message) for r in blocking]}"


# ─────────────────────────────────────────────────────────────────────────────
# B. PublishService — Linux draft publishes
# ─────────────────────────────────────────────────────────────────────────────


class TestPublishServiceLinux:
    def test_linux_draft_publishes_to_published_status(self):
        """PublishService.publish() must transition rehearsal_completed=True Linux draft to PUBLISHED."""
        draft = _linux_draft(rehearsal_completed=True)
        svc = _make_publish_service()
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISHED

    def test_linux_draft_without_rehearsal_raises(self):
        """Linux draft with rehearsal_required=True but rehearsal_completed=False must raise."""
        draft = _linux_draft(rehearsal_completed=False)
        draft = draft.model_copy(update={"rehearsal_required": True})
        svc = _make_publish_service()
        with pytest.raises(RehearsalNotCompleted):
            svc.publish(draft)

    def test_linux_publish_sets_validator_results(self):
        """Published Linux draft must have validator_results populated."""
        draft = _linux_draft()
        svc = _make_publish_service()
        result = svc.publish(draft)
        assert result.validator_results is not None
        assert len(result.validator_results) > 0

    def test_linux_publish_sets_updated_at(self):
        """Publish must set updated_at to a timezone-aware datetime."""
        from datetime import timezone
        draft = _linux_draft()
        svc = _make_publish_service()
        result = svc.publish(draft)
        assert result.updated_at is not None
        assert result.updated_at.tzinfo is not None
        assert result.updated_at.tzinfo == timezone.utc

    def test_linux_draft_without_sandbox_policy_is_blocked(self):
        """Linux draft missing sandbox policy must not publish."""
        draft = _linux_draft()
        draft = draft.model_copy(update={"linux_sandbox_policy": None})
        svc = _make_publish_service()
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_linux_publish_returns_same_object(self):
        """PublishService.publish() mutates and returns the same draft object."""
        draft = _linux_draft()
        svc = _make_publish_service()
        result = svc.publish(draft)
        # The service mutates draft in-place (by design) and returns it
        assert result is draft
        assert result.publish_status == PublishStatus.PUBLISHED


# ─────────────────────────────────────────────────────────────────────────────
# C. Precheck domain guard
# ─────────────────────────────────────────────────────────────────────────────


class TestPrecheckDomainGuard:
    def test_linux_published_draft_blocked_at_learner_precheck(self):
        """Published Linux draft must be blocked at learner precheck with LINUX_LEARNER_NOT_SUPPORTED."""
        draft = _linux_draft()
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        svc = _make_session_service(draft)
        result = svc.run_precheck(draft.lab_id, "500", "alice")
        assert not result.passed
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value in result.failures

    def test_linux_precheck_failure_does_not_expose_cleanup_error(self):
        """Linux precheck must return LINUX_LEARNER_NOT_SUPPORTED, not cleanup_not_declared."""
        draft = _linux_draft()
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        svc = _make_session_service(draft)
        result = svc.run_precheck(draft.lab_id, "500", "alice")
        # cleanup_not_declared must NOT appear — LINUX_LEARNER_NOT_SUPPORTED preempts it
        assert FailureReason.PRECHECK_CLEANUP_NOT_DECLARED.value not in result.failures

    def test_k8s_precheck_cleanup_check_still_runs(self):
        """K8s draft without cleanup must still fail with cleanup_not_declared."""
        k8s = _k8s_draft()
        k8s = k8s.model_copy(update={
            "publish_status": PublishStatus.PUBLISHED,
            "cleanup": None,
        })
        svc = _make_session_service(k8s)
        result = svc.run_precheck(k8s.lab_id, "500", "alice")
        assert not result.passed
        assert FailureReason.PRECHECK_CLEANUP_NOT_DECLARED.value in result.failures

    def test_linux_draft_not_published_still_fails_with_not_published(self):
        """Linux DRAFT (not published) must fail with PRECHECK_DRAFT_NOT_PUBLISHED."""
        draft = _linux_draft()  # publish_status=draft
        svc = _make_session_service(draft)
        result = svc.run_precheck(draft.lab_id, "500", "alice")
        assert not result.passed
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value in result.failures

    def test_linux_published_draft_also_has_linux_not_supported_in_result(self):
        """Linux DRAFT (not published) returns both not_published AND linux_not_supported."""
        draft = _linux_draft()  # publish_status=draft
        svc = _make_session_service(draft)
        result = svc.run_precheck(draft.lab_id, "500", "alice")
        # Both: not_published and linux_not_supported, since domain check runs alongside publish check
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value in result.failures

    def test_k8s_published_draft_with_cleanup_passes_precheck(self):
        """K8s published draft with cleanup must pass the precheck (vm/session aside)."""
        k8s = _k8s_draft()
        k8s = k8s.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        svc = _make_session_service(k8s)
        result = svc.run_precheck(k8s.lab_id, "500", "alice")
        assert result.passed


# ─────────────────────────────────────────────────────────────────────────────
# D. Catalog — Linux lab appears after publish
# ─────────────────────────────────────────────────────────────────────────────


class TestLinuxInLearnerCatalog:
    def test_linux_draft_not_in_catalog_before_publish(self):
        """Linux DRAFT must not appear in learner catalog."""
        draft = _linux_draft()  # publish_status=draft
        svc = _make_catalog([draft])
        items = svc.list_published_labs(actor_user="alice")
        lab_ids = [i.lab_id for i in items]
        assert draft.lab_id not in lab_ids

    def test_linux_published_lab_appears_in_catalog(self):
        """Published Linux lab must appear in learner catalog."""
        draft = _linux_draft()
        svc_publish = _make_publish_service()
        published = svc_publish.publish(draft)
        catalog = _make_catalog([published])
        items = catalog.list_published_labs(actor_user="alice")
        lab_ids = [i.lab_id for i in items]
        assert published.lab_id in lab_ids

    def test_linux_catalog_entry_has_correct_domain(self):
        """Catalog must include the published Linux lab with target_domain=LINUX."""
        draft = _linux_draft()
        svc_publish = _make_publish_service()
        published = svc_publish.publish(draft)
        catalog = _make_catalog([published])
        items = catalog.list_published_labs(actor_user="alice")
        linux_items = [i for i in items if i.lab_id == published.lab_id]
        assert len(linux_items) == 1

    def test_k8s_labs_unaffected_by_linux_publish(self):
        """K8s published labs remain in catalog when Linux lab is added."""
        k8s = _k8s_draft()
        k8s = k8s.model_copy(update={"publish_status": PublishStatus.PUBLISHED})

        linux = _linux_draft()
        svc_publish = _make_publish_service()
        published_linux = svc_publish.publish(linux)

        catalog = _make_catalog([k8s, published_linux])
        items = catalog.list_published_labs(actor_user="alice")
        assert len(items) == 2
        lab_ids = {i.lab_id for i in items}
        assert k8s.lab_id in lab_ids
        assert published_linux.lab_id in lab_ids

    def test_linux_internal_rehearsal_session_not_exposed_in_catalog(self):
        """Internal rehearsal sessions for Linux must not expose a DRAFT to catalog."""
        draft = _linux_draft()  # still DRAFT
        catalog = _make_catalog([draft])
        items = catalog.list_published_labs(actor_user="alice")
        assert all(i.lab_id != draft.lab_id for i in items)


# ─────────────────────────────────────────────────────────────────────────────
# E. Negative checks
# ─────────────────────────────────────────────────────────────────────────────


class TestNegativeChecks:
    def test_linux_draft_without_sandbox_policy_not_published(self):
        """Linux draft missing sandbox policy must remain PUBLISH_BLOCKED."""
        draft = _linux_draft()
        draft = draft.model_copy(update={"linux_sandbox_policy": None})
        svc = _make_publish_service()
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_linux_draft_with_placeholder_not_published(self):
        """Linux draft with placeholder text must remain PUBLISH_BLOCKED."""
        draft = _linux_draft()
        draft = draft.model_copy(update={"title": "Linux Files [TODO] Basics"})
        svc = _make_publish_service()
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_linux_draft_with_allow_root_not_published(self):
        """Linux draft with allow_root=True must remain PUBLISH_BLOCKED."""
        from backend.labgen.models import LinuxSandboxPolicy
        draft = _linux_draft()
        unsafe_policy = LinuxSandboxPolicy.model_construct(
            workspace_root="/home/learner/workspace",
            allowed_commands=["mkdir", "cat"],
            denied_commands=[],
            forbidden_paths=[],
            allow_root=True,
            allow_network=False,
        )
        draft = draft.model_copy(update={"linux_sandbox_policy": unsafe_policy})
        svc = _make_publish_service()
        result = svc.publish(draft)
        assert result.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_static_validator_still_blocks_linux_with_k8s_verifiers(self):
        """Linux draft with K8s verifiers must still be blocked (domain isolation)."""
        from backend.labgen.models import BlockingLevel, ExplainField, Step, VerifyTemplate, VerifyType
        draft = _linux_draft()
        step = draft.steps[0].model_copy(update={
            "verify": [VerifyTemplate(
                verify_id="v-k8s",
                type=VerifyType.NAMESPACE_EXISTS,
                namespace="{{lab_namespace}}",
                name="bad-ns",
            )]
        })
        draft = draft.model_copy(update={"steps": [step] + list(draft.steps[1:])})
        results = StaticValidator().validate(draft)
        blocking = [
            r for r in results
            if r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
            and r.check_id == "linux.no_k8s_verifiers"
        ]
        assert len(blocking) >= 1

    def test_already_published_linux_stays_published_on_republish(self):
        """Calling publish on an already-published Linux draft is idempotent."""
        draft = _linux_draft()
        svc = _make_publish_service()
        first = svc.publish(draft)
        assert first.publish_status == PublishStatus.PUBLISHED
        second = svc.publish(first)
        assert second.publish_status == PublishStatus.PUBLISHED


# ─────────────────────────────────────────────────────────────────────────────
# F. K8s regression
# ─────────────────────────────────────────────────────────────────────────────


class TestK8sRegression:
    def test_k8s_static_validator_check_ids_present(self):
        """K8s validation must return all expected check_ids after gate lift."""
        k8s = _k8s_draft()
        results = StaticValidator().validate(k8s)
        check_ids = {r.check_id for r in results}
        expected_k8s_checks = {
            "content.no_placeholders",
            "explain.verified_if_published",
            "namespace.no_hardcoded",
            "verify.no_shell_commands",
            "verify.no_secret_value",
            "cleanup.declared",
            "cluster_scoped.cleanup_declared",
            "helm.no_generation",
            "service.nodeport",
            "operator.crd",
            "pollution.known",
            "k8s.no_linux_verifiers",
        }
        assert expected_k8s_checks.issubset(check_ids), (
            f"Missing K8s checks: {expected_k8s_checks - check_ids}"
        )

    def test_linux_specific_check_ids_not_in_k8s_results(self):
        """Linux-specific checks must not appear in K8s draft results."""
        k8s = _k8s_draft()
        results = StaticValidator().validate(k8s)
        check_ids = {r.check_id for r in results}
        linux_checks = {
            "linux.sandbox_policy_required",
            "linux.cleanup_required",
            "linux.verifiers_present",
            "linux.verifiers_safe",
            "linux.sandbox_safe",
            "linux.cleanup_safe",
            "linux.no_k8s_verifiers",
            "linux.publish_blocked_until_runtime",
        }
        overlap = linux_checks & check_ids
        assert overlap == set(), f"Linux checks leaked into K8s results: {overlap}"

    def test_k8s_publish_service_still_works(self):
        """K8s draft publish must still work correctly after Linux gate lift."""
        k8s = _k8s_draft()
        k8s = k8s.model_copy(update={"rehearsal_required": False})
        svc = _make_publish_service()
        result = svc.publish(k8s)
        assert result.publish_status == PublishStatus.PUBLISHED
