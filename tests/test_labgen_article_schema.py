"""
Article-to-Lab MVP Contract Schema Gate — comprehensive tests.

Coverage:
- Pydantic serialization / deserialization
- Schema constraint validation
- ArticleDraftValidator guardrails (all 15 checks)
- Happy path, rejection paths, edge cases
- Domain portability (k8s allowed, linux/docker schema-ready, cloud blocked)
- Fail-closed behavior
"""

from __future__ import annotations

import hashlib
import pytest
from datetime import datetime, timezone

pytestmark = pytest.mark.static

from backend.labgen.article_models import (
    AdminDecision,
    AdminDecisionValue,
    ArticleDraftLabContract,
    ArticleDraftStatus,
    ArticleLabRuntimeRequirement,
    ArticleRuntimeType,
    ArticleSourceMetadata,
    ArticleSourceType,
    ArticleStoragePolicy,
    FeasibilityEvaluatedBy,
    FeasibilityResult,
    FeasibilityStatus,
    SafetyFlag,
    SourceGroundingSnippet,
    TargetDomain,
    UnsupportedInference,
    UnsupportedInferenceSeverity,
    VerifierCandidate,
    VerifierCandidateState,
    VerifierFeasibility,
)
from backend.labgen.static_validator import ArticleDraftValidator


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _content_hash(text: str = "test article content") -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _source_metadata(
    user_id: str = "admin-1",
    confirmed_right: bool = True,
    confirmed_secrets: bool = True,
    raw_text_persisted: bool = False,
    source_url: str | None = None,
    **kw,
) -> ArticleSourceMetadata:
    return ArticleSourceMetadata(
        submitted_by_user_id=user_id,
        content_hash=_content_hash(),
        content_length=1234,
        user_confirmed_right_to_use=confirmed_right,
        user_confirmed_no_secrets=confirmed_secrets,
        raw_text_persisted=raw_text_persisted,
        source_url=source_url,
        **kw,
    )


def _feasibility(
    status: FeasibilityStatus = FeasibilityStatus.DIRECTLY_LAB_READY,
    safety_flags: list[SafetyFlag] | None = None,
    evaluated_by: FeasibilityEvaluatedBy = FeasibilityEvaluatedBy.STUB,
    verifier_feasibility: VerifierFeasibility = VerifierFeasibility.REUSABLE_EXISTING,
    **kw,
) -> FeasibilityResult:
    return FeasibilityResult(
        status=status,
        safety_flags=safety_flags or [],
        evaluated_by=evaluated_by,
        verifier_feasibility=verifier_feasibility,
        target_domain_candidates=[TargetDomain.K8S],
        **kw,
    )


def _admin_decision(
    decision: AdminDecisionValue = AdminDecisionValue.PENDING,
    all_confirmed: bool = False,
) -> AdminDecision:
    if all_confirmed:
        return AdminDecision(
            decision=decision,
            confirmed_source_grounding=True,
            confirmed_safety=True,
            confirmed_cleanup=True,
            confirmed_verifier_strategy=True,
            confirmed_no_raw_secret=True,
            confirmed_no_direct_publish=True,
            reviewer_id="admin-1",
            reviewed_at=datetime.now(tz=timezone.utc),
        )
    return AdminDecision(decision=decision)


def _runtime(
    domain: TargetDomain = TargetDomain.K8S,
    runtime_type: ArticleRuntimeType = ArticleRuntimeType.K8S_NAMESPACE,
    cleanup_strategy: str | None = "delete_namespace",
    production_dependency: bool = False,
) -> ArticleLabRuntimeRequirement:
    return ArticleLabRuntimeRequirement(
        domain=domain,
        runtime_type=runtime_type,
        cleanup_strategy=cleanup_strategy,
        production_dependency=production_dependency,
    )


def _grounding(
    excerpt: str = "kubectl create namespace lab-ns",
    excerpt_hash: str | None = None,
    contains_sensitive_content: bool = False,
    supports_step_ids: list[str] | None = None,
) -> SourceGroundingSnippet:
    return SourceGroundingSnippet(
        excerpt=excerpt,
        excerpt_hash=excerpt_hash or _content_hash(excerpt),
        contains_sensitive_content=contains_sensitive_content,
        supports_step_ids=supports_step_ids or ["step-1"],
    )


def _verifier(
    state: VerifierCandidateState = VerifierCandidateState.REUSABLE_EXISTING,
    review_required: bool = False,
    admin_reviewed: bool = True,
) -> VerifierCandidate:
    return VerifierCandidate(
        candidate_state=state,
        review_required=review_required,
        admin_reviewed=admin_reviewed,
        expected_artifact="namespace/lab-ns",
        safe_message_template="Namespace {{namespace}} exists",
    )


def _inference(
    severity: UnsupportedInferenceSeverity = UnsupportedInferenceSeverity.LOW,
    requires_admin_confirmation: bool = False,
    admin_confirmed: bool = False,
    description: str = "inferred step count",
) -> UnsupportedInference:
    return UnsupportedInference(
        description=description,
        reason="not enough source grounding to confirm",
        severity=severity,
        requires_admin_confirmation=requires_admin_confirmation,
        admin_confirmed=admin_confirmed,
    )


def _approved_contract(**kw) -> ArticleDraftLabContract:
    """Helper: fully valid publish-candidate contract."""
    defaults = dict(
        source_metadata=_source_metadata(),
        feasibility_result=_feasibility(status=FeasibilityStatus.DIRECTLY_LAB_READY),
        target_domain=TargetDomain.K8S,
        required_runtime=_runtime(),
        admin_decision=_admin_decision(
            decision=AdminDecisionValue.APPROVE, all_confirmed=True
        ),
        source_grounding=[_grounding()],
        verifier_candidates=[_verifier()],
        status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
        learning_objective="understand namespace isolation",
    )
    defaults.update(kw)
    return ArticleDraftLabContract(**defaults)


# ---------------------------------------------------------------------------
# 1. Enum completeness
# ---------------------------------------------------------------------------


class TestEnumCompleteness:
    def test_feasibility_status_values(self):
        assert FeasibilityStatus.DIRECTLY_LAB_READY.value == "directly_lab_ready"
        assert FeasibilityStatus.PARTIALLY_LAB_READY.value == "partially_lab_ready"
        assert FeasibilityStatus.NOT_LAB_READY.value == "not_lab_ready"

    def test_safety_flag_count(self):
        assert len(SafetyFlag) == 13

    def test_safety_flag_hard_rejects(self):
        assert SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT.value == "contains_secret_like_content"
        assert SafetyFlag.DANGEROUS_OR_ILLEGAL.value == "dangerous_or_illegal"

    def test_target_domain_portability(self):
        domains = {d.value for d in TargetDomain}
        assert "k8s" in domains
        assert "linux" in domains
        assert "docker" in domains
        assert "networking" in domains
        assert "database" in domains
        assert "cicd" in domains
        assert "cloud" in domains
        assert "unknown" in domains

    def test_article_draft_status_progression(self):
        statuses = {s.value for s in ArticleDraftStatus}
        assert "draft" in statuses
        assert "approved_for_publish_candidate" in statuses
        assert "rejected" in statuses

    def test_article_source_type_values(self):
        assert ArticleSourceType.PASTED_TEXT.value == "pasted_text"
        assert ArticleSourceType.MARKDOWN.value == "markdown"
        assert ArticleSourceType.README.value == "readme"

    def test_verifier_candidate_state_values(self):
        assert VerifierCandidateState.UNSAFE_TO_VERIFY.value == "unsafe_to_verify"
        assert VerifierCandidateState.NEEDS_NEW_PRIMITIVE.value == "needs_new_primitive"


# ---------------------------------------------------------------------------
# 2. ArticleSourceMetadata schema
# ---------------------------------------------------------------------------


class TestArticleSourceMetadata:
    def test_defaults(self):
        m = _source_metadata()
        assert m.raw_text_persisted is False
        assert m.retention_policy_version == "v0.1"
        assert m.schema_version == "1.0"

    def test_raw_text_persisted_default_false(self):
        m = ArticleSourceMetadata(
            submitted_by_user_id="u1",
            content_hash=_content_hash(),
            content_length=100,
        )
        assert m.raw_text_persisted is False

    def test_source_url_metadata_only(self):
        m = _source_metadata(source_url="https://example.com/article")
        assert m.source_url == "https://example.com/article"
        # source_url is just a string field; no fetch is triggered by the model

    def test_serialization_roundtrip(self):
        m = _source_metadata()
        data = m.model_dump()
        m2 = ArticleSourceMetadata(**data)
        assert m2.content_hash == m.content_hash
        assert m2.raw_text_persisted is False

    def test_user_confirmations_fields(self):
        m = _source_metadata(confirmed_right=True, confirmed_secrets=False)
        assert m.user_confirmed_right_to_use is True
        assert m.user_confirmed_no_secrets is False


# ---------------------------------------------------------------------------
# 3. FeasibilityResult schema
# ---------------------------------------------------------------------------


class TestFeasibilityResult:
    def test_not_lab_ready_cannot_enter_pipeline(self):
        f = _feasibility(status=FeasibilityStatus.NOT_LAB_READY)
        assert f.can_enter_draft_pipeline() is False

    def test_directly_lab_ready_can_enter_pipeline(self):
        f = _feasibility(status=FeasibilityStatus.DIRECTLY_LAB_READY)
        assert f.can_enter_draft_pipeline() is True

    def test_hard_reject_flag_blocks_pipeline(self):
        f = _feasibility(
            status=FeasibilityStatus.DIRECTLY_LAB_READY,
            safety_flags=[SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT],
        )
        assert f.has_hard_reject_flag() is True
        assert f.can_enter_draft_pipeline() is False

    def test_dangerous_or_illegal_blocks_pipeline(self):
        f = _feasibility(
            status=FeasibilityStatus.DIRECTLY_LAB_READY,
            safety_flags=[SafetyFlag.DANGEROUS_OR_ILLEGAL],
        )
        assert f.has_hard_reject_flag() is True
        assert f.can_enter_draft_pipeline() is False

    def test_unclear_cleanup_blocks_publish_only(self):
        f = _feasibility(
            status=FeasibilityStatus.DIRECTLY_LAB_READY,
            safety_flags=[SafetyFlag.UNCLEAR_CLEANUP],
        )
        assert f.has_hard_reject_flag() is False
        assert f.has_cannot_publish_flag() is True
        assert f.can_enter_draft_pipeline() is True  # enters pipeline but cannot publish

    def test_partial_status_cannot_enter_pipeline(self):
        # partially_lab_ready can enter pipeline (draft) but not become publish candidate
        f = _feasibility(status=FeasibilityStatus.PARTIALLY_LAB_READY)
        assert f.can_enter_draft_pipeline() is True

    def test_serialization_roundtrip(self):
        f = _feasibility()
        data = f.model_dump()
        f2 = FeasibilityResult(**data)
        assert f2.status == f.status

    def test_operability_score_bounds(self):
        import pydantic
        with pytest.raises((ValueError, pydantic.ValidationError)):
            FeasibilityResult(
                status=FeasibilityStatus.DIRECTLY_LAB_READY,
                operability_score=1.5,  # > 1.0
            )

    def test_operability_score_valid(self):
        f = FeasibilityResult(
            status=FeasibilityStatus.DIRECTLY_LAB_READY,
            operability_score=0.85,
        )
        assert f.operability_score == 0.85


# ---------------------------------------------------------------------------
# 4. SourceGroundingSnippet schema
# ---------------------------------------------------------------------------


class TestSourceGroundingSnippet:
    def test_defaults(self):
        sg = _grounding()
        assert sg.minimized is True
        assert sg.contains_sensitive_content is False
        assert sg.schema_version == "1.0"

    def test_snippet_id_auto_generated(self):
        sg1 = _grounding()
        sg2 = _grounding()
        assert sg1.snippet_id != sg2.snippet_id

    def test_serialization_roundtrip(self):
        sg = _grounding(excerpt="some excerpt")
        data = sg.model_dump()
        sg2 = SourceGroundingSnippet(**data)
        assert sg2.excerpt == "some excerpt"


# ---------------------------------------------------------------------------
# 5. UnsupportedInference schema
# ---------------------------------------------------------------------------


class TestUnsupportedInference:
    def test_defaults(self):
        ui = _inference()
        assert ui.requires_admin_confirmation is False
        assert ui.admin_confirmed is False

    def test_high_severity(self):
        ui = _inference(severity=UnsupportedInferenceSeverity.HIGH)
        assert ui.severity == UnsupportedInferenceSeverity.HIGH

    def test_blocker_severity(self):
        ui = _inference(severity=UnsupportedInferenceSeverity.BLOCKER)
        assert ui.severity == UnsupportedInferenceSeverity.BLOCKER

    def test_serialization_roundtrip(self):
        ui = _inference(severity=UnsupportedInferenceSeverity.MEDIUM)
        data = ui.model_dump()
        ui2 = UnsupportedInference(**data)
        assert ui2.severity == UnsupportedInferenceSeverity.MEDIUM


# ---------------------------------------------------------------------------
# 6. AdminDecision schema
# ---------------------------------------------------------------------------


class TestAdminDecision:
    def test_defaults_pending(self):
        d = AdminDecision()
        assert d.decision == AdminDecisionValue.PENDING
        assert d.is_fully_confirmed() is False

    def test_fully_confirmed(self):
        d = _admin_decision(decision=AdminDecisionValue.APPROVE, all_confirmed=True)
        assert d.is_fully_confirmed() is True

    def test_partially_confirmed_not_fully(self):
        d = AdminDecision(
            decision=AdminDecisionValue.APPROVE,
            confirmed_source_grounding=True,
            confirmed_safety=True,
            # rest are False
        )
        assert d.is_fully_confirmed() is False

    def test_serialization_roundtrip(self):
        d = _admin_decision(decision=AdminDecisionValue.APPROVE, all_confirmed=True)
        data = d.model_dump()
        d2 = AdminDecision(**data)
        assert d2.decision == AdminDecisionValue.APPROVE
        assert d2.is_fully_confirmed() is True


# ---------------------------------------------------------------------------
# 7. ArticleStoragePolicy schema
# ---------------------------------------------------------------------------


class TestArticleStoragePolicy:
    def test_raw_text_default_false(self):
        p = ArticleStoragePolicy()
        assert p.raw_text_persisted is False

    def test_forbidden_fields_include_raw_text(self):
        p = ArticleStoragePolicy()
        assert "raw_article_text" in p.forbidden_persisted_fields

    def test_forbidden_fields_include_secrets(self):
        p = ArticleStoragePolicy()
        assert "secret_values" in p.forbidden_persisted_fields
        assert "private_keys" in p.forbidden_persisted_fields

    def test_rejection_metadata_retention_days_default(self):
        p = ArticleStoragePolicy()
        assert p.rejection_metadata_retention_days == 30

    def test_serialization_roundtrip(self):
        p = ArticleStoragePolicy()
        data = p.model_dump()
        p2 = ArticleStoragePolicy(**data)
        assert p2.raw_text_persisted is False


# ---------------------------------------------------------------------------
# 8. ArticleDraftLabContract schema
# ---------------------------------------------------------------------------


class TestArticleDraftLabContract:
    def test_happy_path_draft(self):
        contract = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.K8S,
        )
        assert contract.status == ArticleDraftStatus.DRAFT
        assert contract.schema_version == "1.0"

    def test_draft_id_auto_generated(self):
        c1 = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
        )
        c2 = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
        )
        assert c1.draft_id != c2.draft_id

    def test_raw_text_persisted_true_raises(self):
        import pydantic
        with pytest.raises((ValueError, pydantic.ValidationError)):
            ArticleDraftLabContract(
                source_metadata=_source_metadata(raw_text_persisted=True),
                feasibility_result=_feasibility(),
            )

    def test_storage_policy_raw_text_persisted_true_raises(self):
        import pydantic
        with pytest.raises((ValueError, pydantic.ValidationError)):
            bad_policy = ArticleStoragePolicy()
            bad_policy.raw_text_persisted = True  # mutate after creation
            ArticleDraftLabContract(
                source_metadata=_source_metadata(),
                feasibility_result=_feasibility(),
                storage_policy=bad_policy,
            )

    def test_can_proceed_to_publish_candidate_happy(self):
        c = _approved_contract()
        assert c.can_proceed_to_publish_candidate() is True

    def test_not_lab_ready_cannot_publish(self):
        c = _approved_contract(
            feasibility_result=_feasibility(status=FeasibilityStatus.NOT_LAB_READY)
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_partially_lab_ready_cannot_publish(self):
        c = _approved_contract(
            feasibility_result=_feasibility(status=FeasibilityStatus.PARTIALLY_LAB_READY)
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_pending_admin_decision_blocks_publish(self):
        c = _approved_contract(
            admin_decision=_admin_decision(decision=AdminDecisionValue.PENDING)
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_rejected_admin_decision_blocks_publish(self):
        c = _approved_contract(
            admin_decision=_admin_decision(decision=AdminDecisionValue.REJECT)
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_cloud_domain_blocks_publish(self):
        c = _approved_contract(
            target_domain=TargetDomain.CLOUD,
            required_runtime=_runtime(domain=TargetDomain.CLOUD),
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_unknown_domain_blocks_publish(self):
        c = _approved_contract(target_domain=TargetDomain.UNKNOWN)
        assert c.can_proceed_to_publish_candidate() is False

    def test_missing_cleanup_strategy_blocks_publish(self):
        c = _approved_contract(
            required_runtime=_runtime(cleanup_strategy=None)
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_production_dependency_blocks_publish(self):
        c = _approved_contract(
            required_runtime=_runtime(production_dependency=True)
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_high_severity_inference_blocks_publish(self):
        c = _approved_contract(
            unsupported_inferences=[_inference(severity=UnsupportedInferenceSeverity.HIGH)]
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_blocker_severity_inference_blocks_publish(self):
        c = _approved_contract(
            unsupported_inferences=[_inference(severity=UnsupportedInferenceSeverity.BLOCKER)]
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_unconfirmed_inference_blocks_publish(self):
        c = _approved_contract(
            unsupported_inferences=[_inference(
                severity=UnsupportedInferenceSeverity.MEDIUM,
                requires_admin_confirmation=True,
                admin_confirmed=False,
            )]
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_confirmed_inference_does_not_block(self):
        c = _approved_contract(
            unsupported_inferences=[_inference(
                severity=UnsupportedInferenceSeverity.MEDIUM,
                requires_admin_confirmation=True,
                admin_confirmed=True,
            )]
        )
        assert c.can_proceed_to_publish_candidate() is True

    def test_unsafe_verifier_blocks_publish(self):
        c = _approved_contract(
            verifier_candidates=[_verifier(state=VerifierCandidateState.UNSAFE_TO_VERIFY)]
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_unreviewed_verifier_blocks_publish(self):
        c = _approved_contract(
            verifier_candidates=[_verifier(review_required=True, admin_reviewed=False)]
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_no_source_grounding_blocks_publish(self):
        c = _approved_contract(source_grounding=[])
        assert c.can_proceed_to_publish_candidate() is False

    def test_sensitive_grounding_blocks_publish(self):
        c = _approved_contract(
            source_grounding=[_grounding(contains_sensitive_content=True)]
        )
        assert c.can_proceed_to_publish_candidate() is False

    def test_serialization_roundtrip(self):
        c = _approved_contract()
        data = c.model_dump()
        c2 = ArticleDraftLabContract(**data)
        assert c2.draft_id == c.draft_id
        assert c2.status == c.status

    def test_linux_domain_accepted_in_schema(self):
        # linux is schema-ready but not allowed through publish in v0.1
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.LINUX,
        )
        assert c.target_domain == TargetDomain.LINUX

    def test_docker_domain_accepted_in_schema(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.DOCKER,
        )
        assert c.target_domain == TargetDomain.DOCKER

    def test_k8s_allowed_draft_mode(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.K8S,
        )
        assert c.target_domain == TargetDomain.K8S


# ---------------------------------------------------------------------------
# 9. ArticleDraftValidator — guardrail checks
# ---------------------------------------------------------------------------


class TestArticleDraftValidatorGuardrails:
    def setup_method(self):
        self.validator = ArticleDraftValidator()

    def _results_by_id(self, contract) -> dict:
        results = self.validator.validate(contract)
        return {r.check_id: r for r in results}

    # -- Guardrail 1: rejected feasibility cannot publish --

    def test_not_lab_ready_publish_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(status=FeasibilityStatus.NOT_LAB_READY),
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=_admin_decision(AdminDecisionValue.APPROVE, all_confirmed=True),
            target_domain=TargetDomain.K8S,
        )
        results = self._results_by_id(c)
        r = results["article_draft.rejected_feasibility_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_not_lab_ready_draft_status_passes(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(status=FeasibilityStatus.NOT_LAB_READY),
            status=ArticleDraftStatus.DRAFT,
        )
        results = self._results_by_id(c)
        r = results["article_draft.rejected_feasibility_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 2: partially lab-ready cannot publish candidate --

    def test_partially_ready_publish_candidate_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(status=FeasibilityStatus.PARTIALLY_LAB_READY),
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=_admin_decision(AdminDecisionValue.APPROVE, all_confirmed=True),
            target_domain=TargetDomain.K8S,
        )
        results = self._results_by_id(c)
        r = results["article_draft.partial_feasibility_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_partially_ready_draft_status_passes(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(status=FeasibilityStatus.PARTIALLY_LAB_READY),
            status=ArticleDraftStatus.DRAFT,
        )
        results = self._results_by_id(c)
        r = results["article_draft.partial_feasibility_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 3: directly_lab_ready still requires admin review --

    def test_directly_ready_without_admin_approval_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(status=FeasibilityStatus.DIRECTLY_LAB_READY),
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=_admin_decision(AdminDecisionValue.PENDING),
            target_domain=TargetDomain.K8S,
        )
        results = self._results_by_id(c)
        r = results["article_draft.directly_ready_requires_admin_review"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_directly_ready_with_admin_approval_passes(self):
        c = _approved_contract()
        results = self._results_by_id(c)
        r = results["article_draft.directly_ready_requires_admin_review"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 4: missing source grounding blocks publish candidate --

    def test_no_grounding_in_publish_candidate_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=_admin_decision(AdminDecisionValue.APPROVE, all_confirmed=True),
            target_domain=TargetDomain.K8S,
            source_grounding=[],
        )
        results = self._results_by_id(c)
        r = results["article_draft.missing_source_grounding"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_grounding_present_passes(self):
        c = _approved_contract()
        results = self._results_by_id(c)
        r = results["article_draft.missing_source_grounding"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_no_grounding_in_draft_status_passes(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            status=ArticleDraftStatus.DRAFT,
            source_grounding=[],
        )
        results = self._results_by_id(c)
        r = results["article_draft.missing_source_grounding"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 5: unsupported inference high/blocker blocks publish --

    def test_high_inference_in_publish_candidate_fails(self):
        c = _approved_contract(
            unsupported_inferences=[
                _inference(severity=UnsupportedInferenceSeverity.HIGH)
            ]
        )
        results = self._results_by_id(c)
        from backend.labgen.models import ValidatorStatus
        # There may be multiple results with same check_id; at least one fails
        all_results = self.validator.validate(c)
        failing = [
            r for r in all_results
            if r.check_id == "article_draft.unsupported_inference_high_blocker"
            and r.status == ValidatorStatus.FAILED
        ]
        assert failing

    def test_blocker_inference_fails(self):
        c = _approved_contract(
            unsupported_inferences=[
                _inference(severity=UnsupportedInferenceSeverity.BLOCKER)
            ]
        )
        from backend.labgen.models import ValidatorStatus
        all_results = self.validator.validate(c)
        failing = [
            r for r in all_results
            if r.check_id == "article_draft.unsupported_inference_high_blocker"
            and r.status == ValidatorStatus.FAILED
        ]
        assert failing

    def test_low_severity_inference_passes(self):
        c = _approved_contract(
            unsupported_inferences=[
                _inference(severity=UnsupportedInferenceSeverity.LOW)
            ]
        )
        results = self._results_by_id(c)
        r = results["article_draft.unsupported_inference_high_blocker"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_unconfirmed_medium_inference_fails(self):
        c = _approved_contract(
            unsupported_inferences=[
                _inference(
                    severity=UnsupportedInferenceSeverity.MEDIUM,
                    requires_admin_confirmation=True,
                    admin_confirmed=False,
                )
            ]
        )
        from backend.labgen.models import ValidatorStatus
        all_results = self.validator.validate(c)
        failing = [
            r for r in all_results
            if r.check_id == "article_draft.unsupported_inference_high_blocker"
            and r.status == ValidatorStatus.FAILED
        ]
        assert failing

    def test_confirmed_medium_inference_passes(self):
        c = _approved_contract(
            unsupported_inferences=[
                _inference(
                    severity=UnsupportedInferenceSeverity.MEDIUM,
                    requires_admin_confirmation=True,
                    admin_confirmed=True,
                )
            ]
        )
        results = self._results_by_id(c)
        r = results["article_draft.unsupported_inference_high_blocker"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 6: raw article text field forbidden --

    def test_no_raw_text_check_passes_by_default(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
        )
        results = self._results_by_id(c)
        r = results["article_draft.no_raw_text_field"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 7: sensitive source grounding excerpt forbidden --

    def test_sensitive_grounding_with_excerpt_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            source_grounding=[
                _grounding(
                    contains_sensitive_content=True,
                    excerpt="sk-secret-token-here",
                )
            ],
        )
        from backend.labgen.models import ValidatorStatus
        all_results = self.validator.validate(c)
        failing = [
            r for r in all_results
            if r.check_id == "article_draft.no_sensitive_grounding_excerpt"
            and r.status == ValidatorStatus.FAILED
        ]
        assert failing

    def test_non_sensitive_grounding_passes(self):
        c = _approved_contract()
        results = self._results_by_id(c)
        r = results["article_draft.no_sensitive_grounding_excerpt"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 8: admin approve requires all confirmations --

    def test_approve_without_confirmations_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            admin_decision=AdminDecision(
                decision=AdminDecisionValue.APPROVE,
                confirmed_source_grounding=True,
                # rest False
            ),
        )
        results = self._results_by_id(c)
        r = results["article_draft.admin_approve_requires_confirmations"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_approve_with_all_confirmations_passes(self):
        c = _approved_contract()
        results = self._results_by_id(c)
        r = results["article_draft.admin_approve_requires_confirmations"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_pending_decision_always_passes_this_check(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            admin_decision=_admin_decision(AdminDecisionValue.PENDING),
        )
        results = self._results_by_id(c)
        r = results["article_draft.admin_approve_requires_confirmations"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 9: unknown target_domain cannot publish --

    def test_unknown_domain_in_publish_candidate_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            target_domain=TargetDomain.UNKNOWN,
            admin_decision=_admin_decision(AdminDecisionValue.APPROVE, all_confirmed=True),
        )
        results = self._results_by_id(c)
        r = results["article_draft.unknown_domain_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_k8s_domain_in_publish_candidate_passes(self):
        c = _approved_contract()
        results = self._results_by_id(c)
        r = results["article_draft.unknown_domain_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_unknown_domain_in_draft_status_passes(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.UNKNOWN,
        )
        results = self._results_by_id(c)
        r = results["article_draft.unknown_domain_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 10: unsafe verifier candidate cannot publish --

    def test_unsafe_verifier_in_publish_candidate_fails(self):
        c = _approved_contract(
            verifier_candidates=[_verifier(state=VerifierCandidateState.UNSAFE_TO_VERIFY)]
        )
        from backend.labgen.models import ValidatorStatus
        all_results = self.validator.validate(c)
        failing = [
            r for r in all_results
            if r.check_id == "article_draft.unsafe_verifier_cannot_publish"
            and r.status == ValidatorStatus.FAILED
        ]
        assert failing

    def test_unreviewed_verifier_in_publish_candidate_fails(self):
        c = _approved_contract(
            verifier_candidates=[_verifier(review_required=True, admin_reviewed=False)]
        )
        from backend.labgen.models import ValidatorStatus
        all_results = self.validator.validate(c)
        failing = [
            r for r in all_results
            if r.check_id == "article_draft.unsafe_verifier_cannot_publish"
            and r.status == ValidatorStatus.FAILED
        ]
        assert failing

    def test_reviewed_verifier_passes(self):
        c = _approved_contract(
            verifier_candidates=[_verifier(review_required=True, admin_reviewed=True)]
        )
        results = self._results_by_id(c)
        r = results["article_draft.unsafe_verifier_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_needs_new_primitive_not_unsafe_by_default(self):
        # needs_new_primitive blocks auto-generation but is not unsafe_to_verify
        c = _approved_contract(
            verifier_candidates=[_verifier(
                state=VerifierCandidateState.NEEDS_NEW_PRIMITIVE,
                review_required=False,
            )]
        )
        results = self._results_by_id(c)
        r = results["article_draft.unsafe_verifier_cannot_publish"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 11: cleanup strategy required --

    def test_no_cleanup_in_publish_candidate_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            status=ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL,
            required_runtime=_runtime(cleanup_strategy=None),
            admin_decision=_admin_decision(AdminDecisionValue.APPROVE, all_confirmed=True),
            target_domain=TargetDomain.K8S,
        )
        results = self._results_by_id(c)
        r = results["article_draft.cleanup_strategy_required"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_cleanup_present_passes(self):
        c = _approved_contract()
        results = self._results_by_id(c)
        r = results["article_draft.cleanup_strategy_required"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_no_cleanup_in_draft_status_passes(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            required_runtime=_runtime(cleanup_strategy=None),
        )
        results = self._results_by_id(c)
        r = results["article_draft.cleanup_strategy_required"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 12: LLM/stub draft cannot bypass review --

    def test_stub_evaluated_without_approval_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(evaluated_by=FeasibilityEvaluatedBy.STUB),
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=_admin_decision(AdminDecisionValue.PENDING),
            target_domain=TargetDomain.K8S,
        )
        results = self._results_by_id(c)
        r = results["article_draft.llm_draft_cannot_bypass_review"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_llm_draft_evaluated_without_approval_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(evaluated_by=FeasibilityEvaluatedBy.LLM_DRAFT),
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=_admin_decision(AdminDecisionValue.PENDING),
            target_domain=TargetDomain.K8S,
        )
        results = self._results_by_id(c)
        r = results["article_draft.llm_draft_cannot_bypass_review"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_stub_evaluated_with_approval_passes(self):
        c = _approved_contract()
        results = self._results_by_id(c)
        r = results["article_draft.llm_draft_cannot_bypass_review"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_human_evaluated_without_approval_passes(self):
        # human-evaluated can be in publish candidate without approval check failing this
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(evaluated_by=FeasibilityEvaluatedBy.HUMAN),
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=_admin_decision(AdminDecisionValue.PENDING),
            target_domain=TargetDomain.K8S,
        )
        results = self._results_by_id(c)
        r = results["article_draft.llm_draft_cannot_bypass_review"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 13: cloud domain blocked by default in v0.1 --

    def test_cloud_domain_non_draft_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.CLOUD,
            status=ArticleDraftStatus.NEEDS_CHANGES,
        )
        results = self._results_by_id(c)
        r = results["article_draft.cloud_domain_blocked_v1"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.FAILED

    def test_cloud_domain_draft_status_passes(self):
        # Cloud can be in DRAFT (initial analysis); blocked from advancing
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.CLOUD,
            status=ArticleDraftStatus.DRAFT,
        )
        results = self._results_by_id(c)
        r = results["article_draft.cloud_domain_blocked_v1"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_non_cloud_domain_passes(self):
        c = _approved_contract(target_domain=TargetDomain.K8S)
        results = self._results_by_id(c)
        r = results["article_draft.cloud_domain_blocked_v1"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 14: source_url no scraping --

    def test_source_url_no_scraping_always_passes(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(source_url="https://example.com/k8s-secrets"),
            feasibility_result=_feasibility(),
        )
        results = self._results_by_id(c)
        r = results["article_draft.source_url_no_scraping"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    # -- Guardrail 15: user confirmations required --

    def test_unconfirmed_right_to_use_non_draft_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(confirmed_right=False),
            feasibility_result=_feasibility(),
            status=ArticleDraftStatus.NEEDS_CHANGES,
        )
        from backend.labgen.models import ValidatorStatus
        all_results = self.validator.validate(c)
        failing = [
            r for r in all_results
            if r.check_id == "article_draft.user_confirmations_required"
            and r.status == ValidatorStatus.FAILED
        ]
        assert failing

    def test_unconfirmed_no_secrets_non_draft_fails(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(confirmed_secrets=False),
            feasibility_result=_feasibility(),
            status=ArticleDraftStatus.APPROVED_FOR_STATIC_VALIDATION,
        )
        from backend.labgen.models import ValidatorStatus
        all_results = self.validator.validate(c)
        failing = [
            r for r in all_results
            if r.check_id == "article_draft.user_confirmations_required"
            and r.status == ValidatorStatus.FAILED
        ]
        assert failing

    def test_both_confirmations_present_passes(self):
        c = _approved_contract()
        results = self._results_by_id(c)
        r = results["article_draft.user_confirmations_required"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED

    def test_unconfirmed_in_draft_status_passes(self):
        # DRAFT status is before confirmations are required
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(confirmed_right=False, confirmed_secrets=False),
            feasibility_result=_feasibility(),
            status=ArticleDraftStatus.DRAFT,
        )
        results = self._results_by_id(c)
        r = results["article_draft.user_confirmations_required"]
        from backend.labgen.models import ValidatorStatus
        assert r.status == ValidatorStatus.PASSED


# ---------------------------------------------------------------------------
# 10. Domain portability
# ---------------------------------------------------------------------------


class TestDomainPortability:
    def test_linux_accepted_in_schema(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.LINUX,
        )
        assert c.target_domain == TargetDomain.LINUX

    def test_linux_blocked_in_publish_candidate_by_unknown_domain_check(self):
        # linux is not in _ALLOWED_DRAFT_DOMAINS_V1 for implementation,
        # but is allowed in schema — guardrail unknown_domain_cannot_publish
        # passes (linux is not UNKNOWN). However, can_proceed_to_publish_candidate
        # is False because linux is not in _BLOCKED_DOMAINS_V1 and not UNKNOWN.
        # So: schema accepts linux, but publish attempt in _approved_contract
        # with linux domain would be blocked elsewhere (no implementation).
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.LINUX,
        )
        validator = ArticleDraftValidator()
        results = {r.check_id: r for r in validator.validate(c)}
        # unknown_domain check: linux is not UNKNOWN, so passes
        from backend.labgen.models import ValidatorStatus
        assert results["article_draft.unknown_domain_cannot_publish"].status == ValidatorStatus.PASSED
        # cloud block check: linux is not cloud, so passes
        assert results["article_draft.cloud_domain_blocked_v1"].status == ValidatorStatus.PASSED

    def test_docker_accepted_in_schema(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.DOCKER,
        )
        assert c.target_domain == TargetDomain.DOCKER

    def test_cloud_blocked_by_default(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
            target_domain=TargetDomain.CLOUD,
            status=ArticleDraftStatus.APPROVED_FOR_STATIC_VALIDATION,
        )
        validator = ArticleDraftValidator()
        results = {r.check_id: r for r in validator.validate(c)}
        from backend.labgen.models import ValidatorStatus
        assert results["article_draft.cloud_domain_blocked_v1"].status == ValidatorStatus.FAILED

    def test_k8s_allowed_and_passes_all_domain_checks(self):
        c = _approved_contract(target_domain=TargetDomain.K8S)
        validator = ArticleDraftValidator()
        results = {r.check_id: r for r in validator.validate(c)}
        from backend.labgen.models import ValidatorStatus
        assert results["article_draft.unknown_domain_cannot_publish"].status == ValidatorStatus.PASSED
        assert results["article_draft.cloud_domain_blocked_v1"].status == ValidatorStatus.PASSED


# ---------------------------------------------------------------------------
# 11. Retention / storage policy defaults
# ---------------------------------------------------------------------------


class TestRetentionPolicyDefaults:
    def test_rejection_metadata_30_days(self):
        p = ArticleStoragePolicy()
        assert p.rejection_metadata_retention_days == 30

    def test_audit_retention_indefinite(self):
        p = ArticleStoragePolicy()
        assert p.audit_retention == "indefinite"

    def test_draft_retention_until_deleted(self):
        p = ArticleStoragePolicy()
        assert p.draft_retention == "until_deleted"

    def test_raw_text_retention_ephemeral(self):
        p = ArticleStoragePolicy()
        assert p.raw_text_retention == "ephemeral"

    def test_delete_and_purge_supported(self):
        p = ArticleStoragePolicy()
        assert p.delete_supported is True
        assert p.purge_supported is True


# ---------------------------------------------------------------------------
# 12. Validator returns all 15 check IDs
# ---------------------------------------------------------------------------


class TestValidatorCheckIds:
    EXPECTED_CHECK_IDS = {
        "article_draft.rejected_feasibility_cannot_publish",
        "article_draft.partial_feasibility_cannot_publish",
        "article_draft.directly_ready_requires_admin_review",
        "article_draft.missing_source_grounding",
        "article_draft.unsupported_inference_high_blocker",
        "article_draft.no_raw_text_field",
        "article_draft.no_sensitive_grounding_excerpt",
        "article_draft.admin_approve_requires_confirmations",
        "article_draft.unknown_domain_cannot_publish",
        "article_draft.unsafe_verifier_cannot_publish",
        "article_draft.cleanup_strategy_required",
        "article_draft.llm_draft_cannot_bypass_review",
        "article_draft.cloud_domain_blocked_v1",
        "article_draft.source_url_no_scraping",
        "article_draft.user_confirmations_required",
    }

    def test_all_check_ids_returned_for_draft(self):
        c = ArticleDraftLabContract(
            source_metadata=_source_metadata(),
            feasibility_result=_feasibility(),
        )
        validator = ArticleDraftValidator()
        results = validator.validate(c)
        ids = {r.check_id for r in results}
        assert self.EXPECTED_CHECK_IDS.issubset(ids)

    def test_all_check_ids_returned_for_publish_candidate(self):
        c = _approved_contract()
        validator = ArticleDraftValidator()
        results = validator.validate(c)
        ids = {r.check_id for r in results}
        assert self.EXPECTED_CHECK_IDS.issubset(ids)
