"""
ArticleDraftService — business logic for Article-to-Lab draft pipeline.

Responsibilities:
  - Create ArticleDraftLabContract from article text + metadata
  - Run StubFeasibilityClassifier
  - Enforce status transitions (with ArticleDraftValidator guardrails)
  - Admin review decision recording
  - Convert approved_for_publish_candidate → LabDraft (does NOT auto-publish)
  - generate_lab_from_article: LLM-based LabDraft generation (admin-only, LABGEN_LLM_MODE gated)

Status transition rules:
  draft → (admin review) → needs_changes | rejected |
           approved_for_static_validation → approved_for_internal_rehearsal
           → approved_for_publish_candidate

Forbidden transitions:
  - LLM/stub output cannot move status beyond DRAFT without admin review
  - approved_for_publish_candidate → LabDraft requires explicit admin convert call
  - LabDraft created here is always status=DRAFT (not published)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.labgen.article_draft_repository import ArticleDraftRepository
from backend.labgen.article_models import (
    AdminDecision,
    AdminDecisionValue,
    ArticleDraftLabContract,
    ArticleDraftStatus,
    ArticleLabRuntimeRequirement,
    ArticleSourceMetadata,
    ArticleStoragePolicy,
    FeasibilityResult,
    FeasibilityStatus,
    TargetDomain,
)
from backend.labgen.repository import LabDraftRepository
from backend.labgen.static_validator import ArticleDraftValidator
from backend.labgen.stub_feasibility_classifier import (
    StubFeasibilityClassifier,
    compute_content_hash,
)
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainConfidence,
    ExplainField,
    LabDraft,
    PublishStatus,
    RuntimeRequirements,
    Step,
    VerifyTemplate,
    VerifyType,
)

logger = logging.getLogger(__name__)


class ArticleDraftServiceError(Exception):
    pass


class ArticleDraftNotFound(ArticleDraftServiceError):
    pass


class ArticleDraftTransitionForbidden(ArticleDraftServiceError):
    pass


class ArticleDraftGuardrailBlocked(ArticleDraftServiceError):
    def __init__(self, message: str, blocked_checks: list[str]) -> None:
        super().__init__(message)
        self.blocked_checks = blocked_checks


class ArticleOperabilityRejected(ArticleDraftServiceError):
    """Article is NOT_LAB_READY — LLM generation not allowed."""
    def __init__(self, rejection_code: Optional[str], reasons: list[str]) -> None:
        self.rejection_code = rejection_code
        self.reasons = reasons
        super().__init__(f"operability_rejected: {rejection_code} — {reasons}")


class LLMModeDisabled(ArticleDraftServiceError):
    """live_admin_only requested but LABGEN_LLM_MODE=fake_only."""


class LLMGenerationFailed(ArticleDraftServiceError):
    """LLM call failed or returned a rejected result."""
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class LLMDraftParseError(ArticleDraftServiceError):
    """LLM output could not be parsed as a LabDraft."""
    def __init__(self, errors: list[dict]) -> None:
        self.errors = errors
        super().__init__(str(errors))


@dataclass
class GenerateLabResult:
    """Result of generate_lab_from_article()."""
    lab_draft: LabDraft
    audit_id: str
    operability_status: str   # directly_lab_ready | partially_lab_ready
    warnings: list[str]
    validation_passed: bool   # True if no PUBLISH_BLOCKING validator results


class ArticleDraftService:
    def __init__(
        self,
        article_repo: Optional[ArticleDraftRepository] = None,
        lab_repo: Optional[LabDraftRepository] = None,
        classifier: Optional[StubFeasibilityClassifier] = None,
        validator: Optional[ArticleDraftValidator] = None,
    ) -> None:
        self._article_repo = article_repo or ArticleDraftRepository()
        self._lab_repo = lab_repo or LabDraftRepository()
        self._classifier = classifier or StubFeasibilityClassifier()
        self._validator = validator or ArticleDraftValidator()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_draft(
        self,
        raw_text: str,
        source_metadata: ArticleSourceMetadata,
        submitted_by: str,
    ) -> ArticleDraftLabContract:
        """
        Classify article text and create an ArticleDraftLabContract.

        raw_text is used for classification only — never persisted.
        content_hash must already be set in source_metadata.
        """
        # Verify the hash in metadata matches
        expected_hash = compute_content_hash(raw_text)
        if source_metadata.content_hash != expected_hash:
            raise ArticleDraftServiceError(
                "source_metadata.content_hash does not match SHA-256 of submitted text"
            )

        feasibility: FeasibilityResult = self._classifier.classify(raw_text)

        contract = ArticleDraftLabContract(
            source_metadata=source_metadata,
            feasibility_result=feasibility,
            target_domain=_pick_target_domain(feasibility),
            status=ArticleDraftStatus.DRAFT,
        )

        self._article_repo.create(contract)
        logger.info(
            "ArticleDraftService.create_draft: created %s (status=%s feasibility=%s)",
            contract.draft_id,
            contract.status,
            feasibility.status,
        )
        return contract

    # ------------------------------------------------------------------
    # Get / List
    # ------------------------------------------------------------------

    def get_draft(self, draft_id: str) -> ArticleDraftLabContract:
        contract = self._article_repo.get(draft_id)
        if contract is None:
            raise ArticleDraftNotFound(f"Article draft not found: {draft_id}")
        return contract

    def list_drafts(self) -> list[ArticleDraftLabContract]:
        return self._article_repo.list_all()

    # ------------------------------------------------------------------
    # Admin patch / review
    # ------------------------------------------------------------------

    def update_draft(
        self,
        draft_id: str,
        updates: dict,
        updated_by: str,
    ) -> ArticleDraftLabContract:
        """
        Apply field-level updates from admin.

        Allowed top-level keys: learning_objective, environment_requirements,
        learner_steps, expected_artifacts, verifier_candidates,
        cleanup_requirements, safety_constraints, terminal_requirements,
        estimated_duration_minutes, review_notes, required_runtime,
        target_domain.

        Status transitions must use record_admin_decision(), not this method.
        """
        _ALLOWED_UPDATE_KEYS = {
            "learning_objective",
            "environment_requirements",
            "learner_steps",
            "expected_artifacts",
            "verifier_candidates",
            "cleanup_requirements",
            "safety_constraints",
            "terminal_requirements",
            "estimated_duration_minutes",
            "review_notes",
            "required_runtime",
            "source_grounding",
            "target_domain",
        }
        contract = self.get_draft(draft_id)

        for key, value in updates.items():
            if key not in _ALLOWED_UPDATE_KEYS:
                raise ArticleDraftServiceError(
                    f"Field '{key}' cannot be updated via PATCH — use the appropriate service method"
                )
            setattr(contract, key, value)

        contract.updated_at = datetime.now(tz=timezone.utc)
        self._article_repo.update(contract)
        return contract

    def record_admin_decision(
        self,
        draft_id: str,
        decision: AdminDecisionValue,
        reviewer_id: str,
        comments: list[str] | None = None,
        required_changes: list[str] | None = None,
        confirmed_source_grounding: bool = False,
        confirmed_safety: bool = False,
        confirmed_cleanup: bool = False,
        confirmed_verifier_strategy: bool = False,
        confirmed_no_raw_secret: bool = False,
        confirmed_no_direct_publish: bool = False,
    ) -> ArticleDraftLabContract:
        """
        Record an admin review decision and advance/regress status.

        APPROVE → approved_for_static_validation (only if guardrails pass)
        REQUEST_CHANGES → needs_changes
        REJECT → rejected
        """
        contract = self.get_draft(draft_id)

        admin_decision = AdminDecision(
            decision=decision,
            reviewer_id=reviewer_id,
            reviewed_at=datetime.now(tz=timezone.utc),
            comments=comments or [],
            required_changes=required_changes or [],
            confirmed_source_grounding=confirmed_source_grounding,
            confirmed_safety=confirmed_safety,
            confirmed_cleanup=confirmed_cleanup,
            confirmed_verifier_strategy=confirmed_verifier_strategy,
            confirmed_no_raw_secret=confirmed_no_raw_secret,
            confirmed_no_direct_publish=confirmed_no_direct_publish,
        )
        contract.admin_decision = admin_decision

        if decision == AdminDecisionValue.APPROVE:
            if not admin_decision.is_fully_confirmed():
                raise ArticleDraftTransitionForbidden(
                    "APPROVE requires all confirmed_* fields to be True"
                )
            # Run guardrails before advancing status
            blocked = self._run_validator_and_collect_blockers(contract)
            if blocked:
                raise ArticleDraftGuardrailBlocked(
                    f"Guardrail checks blocked approval: {blocked}",
                    blocked_checks=blocked,
                )
            contract.status = ArticleDraftStatus.APPROVED_FOR_STATIC_VALIDATION

        elif decision == AdminDecisionValue.REQUEST_CHANGES:
            contract.status = ArticleDraftStatus.NEEDS_CHANGES

        elif decision == AdminDecisionValue.REJECT:
            contract.status = ArticleDraftStatus.REJECTED

        contract.updated_at = datetime.now(tz=timezone.utc)
        self._article_repo.update(contract)
        logger.info(
            "ArticleDraftService.record_admin_decision: %s → %s (reviewer=%s)",
            draft_id,
            contract.status,
            reviewer_id,
        )
        return contract

    def advance_to_internal_rehearsal(self, draft_id: str) -> ArticleDraftLabContract:
        """Advance approved_for_static_validation → approved_for_internal_rehearsal."""
        contract = self.get_draft(draft_id)
        if contract.status != ArticleDraftStatus.APPROVED_FOR_STATIC_VALIDATION:
            raise ArticleDraftTransitionForbidden(
                f"Can only advance to internal rehearsal from "
                f"APPROVED_FOR_STATIC_VALIDATION, current: {contract.status}"
            )
        blocked = self._run_validator_and_collect_blockers(contract)
        if blocked:
            raise ArticleDraftGuardrailBlocked(
                f"Cannot advance to internal rehearsal: {blocked}",
                blocked_checks=blocked,
            )
        contract.status = ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL
        contract.updated_at = datetime.now(tz=timezone.utc)
        self._article_repo.update(contract)
        return contract

    def advance_to_publish_candidate(self, draft_id: str) -> ArticleDraftLabContract:
        """Advance approved_for_internal_rehearsal → approved_for_publish_candidate."""
        contract = self.get_draft(draft_id)
        if contract.status != ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL:
            raise ArticleDraftTransitionForbidden(
                f"Can only advance to publish candidate from "
                f"APPROVED_FOR_INTERNAL_REHEARSAL, current: {contract.status}"
            )
        if not contract.can_proceed_to_publish_candidate():
            raise ArticleDraftTransitionForbidden(
                "ArticleDraftLabContract.can_proceed_to_publish_candidate() returned False — "
                "check feasibility, admin decision, domain, runtime, inferences, and verifier candidates"
            )
        blocked = self._run_validator_and_collect_blockers(contract)
        if blocked:
            raise ArticleDraftGuardrailBlocked(
                f"Cannot advance to publish candidate: {blocked}",
                blocked_checks=blocked,
            )
        contract.status = ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE
        contract.updated_at = datetime.now(tz=timezone.utc)
        self._article_repo.update(contract)
        return contract

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def validate_draft(self, draft_id: str) -> list[dict]:
        """Run ArticleDraftValidator and return all check results as dicts."""
        contract = self.get_draft(draft_id)
        results = self._validator.validate(contract)
        return [r.model_dump(mode="json") for r in results]

    # ------------------------------------------------------------------
    # Convert to LabDraft
    # ------------------------------------------------------------------

    def convert_to_lab_draft(self, draft_id: str, converted_by: str) -> LabDraft:
        """
        Convert an APPROVED_FOR_PUBLISH_CANDIDATE ArticleDraftLabContract into
        a LabDraft in DRAFT state.

        Does NOT publish the LabDraft. The LabDraft still requires the full
        StaticValidator + publish flow before learners can see it.
        """
        contract = self.get_draft(draft_id)

        if contract.status != ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE:
            raise ArticleDraftTransitionForbidden(
                f"Only APPROVED_FOR_PUBLISH_CANDIDATE contracts can be converted, "
                f"current status: {contract.status}"
            )

        if not contract.can_proceed_to_publish_candidate():
            raise ArticleDraftTransitionForbidden(
                "Contract failed can_proceed_to_publish_candidate() check — cannot convert"
            )

        lab_draft = _build_lab_draft_from_contract(contract, converted_by)
        self._lab_repo.create(lab_draft)
        logger.info(
            "ArticleDraftService.convert_to_lab_draft: article_draft=%s → lab_draft=%s",
            draft_id,
            lab_draft.lab_id,
        )
        return lab_draft

    # ------------------------------------------------------------------
    # LLM-based LabDraft generation from article
    # ------------------------------------------------------------------

    def generate_lab_from_article(
        self,
        draft_id: str,
        article_text: str,
        admin_user: str,
        desired_lab_title: Optional[str] = None,
        audit_repo=None,  # Optional[LLMAuditRepository]
    ) -> "GenerateLabResult":
        """
        Generate a LabDraft from an article using the configured LLM mode.

        Flow:
          1. Load ArticleDraftLabContract → get feasibility result
          2. NOT_LAB_READY → raise ArticleOperabilityRejected
          3. Check LABGEN_LLM_MODE → fake_only or live_admin_only
          4. Build article-to-lab prompt
          5. Call LLM (fake or live)
          6. Parse + validate → LabDraft
          7. Persist LabDraft (NEVER PUBLISHED; StaticValidator may set publish_blocked/review_required)
          8. Write audit log entry (guaranteed via finally, even on persist failure)
          9. Return GenerateLabResult

        Postcondition: persisted LabDraft.publish_status is NEVER "published".
        It may be "draft", "publish_blocked", or "review_required" depending on StaticValidator.
        rehearsal_required=True is always set.

        Raises:
          ArticleDraftNotFound       — draft_id does not exist
          ArticleOperabilityRejected — article is NOT_LAB_READY
          LLMGenerationFailed        — LLM call failed
          LLMDraftParseError         — LLM output could not be parsed
        """
        from backend import config as cfg
        from backend.labgen.article_models import FeasibilityStatus
        from backend.labgen.llm_audit import LLMAuditEntry, LLMAuditRepository
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.models import PublishStatus, ValidatorStatus, BlockingLevel

        audit = audit_repo or LLMAuditRepository()
        contract = self.get_draft(draft_id)

        # --- 1. Operability gate ---
        feasibility = contract.feasibility_result
        if feasibility.status == FeasibilityStatus.NOT_LAB_READY:
            audit.append(LLMAuditEntry(
                admin_user=admin_user,
                article_draft_id=draft_id,
                article_title=contract.source_metadata.title or "",
                target_domain=contract.target_domain.value,
                llm_mode=cfg.LABGEN_LLM_MODE,
                model_name="n/a",
                success=False,
                failure_reason="operability_rejected",
                operability_status="not_lab_ready",
            ))
            raise ArticleOperabilityRejected(
                feasibility.rejection_code,
                feasibility.reasons,
            )

        operability_status = (
            "directly_lab_ready"
            if feasibility.status == FeasibilityStatus.DIRECTLY_LAB_READY
            else "partially_lab_ready"
        )

        target_domain = contract.target_domain.value
        article_title = contract.source_metadata.title or ""

        # --- 2. Determine LLM mode ---
        llm_mode = cfg.LABGEN_LLM_MODE
        if llm_mode not in ("fake_only", "live_admin_only"):
            llm_mode = "fake_only"  # fail-closed

        # --- 3. Generate candidate ---
        model_name = "fake"
        candidate: Optional[dict] = None
        warnings: list[str] = []
        generation_failed = False
        failure_reason: Optional[str] = None

        if llm_mode == "live_admin_only":
            # Delegate to LLMProviderBoundaryService in live mode
            # Requires LABGEN_LLM_PROVIDER_MODE=live_enabled + LABGEN_LLM_OPENAI_* vars
            from backend.labgen.llm_provider_boundary import (
                LLMProviderBoundaryService,
                LLMProviderRequest,
            )
            from backend.labgen.llm_openai_compatible import OpenAICompatibleProviderConfig

            boundary = LLMProviderBoundaryService.create_from_env()
            if not boundary.live_enabled:
                # Live mode requested but config is invalid — fail closed
                config_issues = boundary.live_adapter_config_issues
                audit.append(LLMAuditEntry(
                    admin_user=admin_user,
                    article_draft_id=draft_id,
                    article_title=article_title,
                    target_domain=target_domain,
                    llm_mode=llm_mode,
                    model_name="n/a",
                    success=False,
                    failure_reason="live_provider_config_error",
                    operability_status=operability_status,
                ))
                raise LLMGenerationFailed(
                    "live_provider_config_error: "
                    + ("; ".join(config_issues) if config_issues else "unknown config issue")
                )

            # Get model name safely for audit
            model_name = cfg.LABGEN_LLM_OPENAI_MODEL or "openai_compatible"

            system_msg, user_msg = build_article_to_lab_messages(
                article_text,
                article_title=article_title,
                target_domain=target_domain,
                desired_lab_title=desired_lab_title,
                operability_status=operability_status,
            )

            pr = LLMProviderRequest(
                purpose="draft_generation",
                sanitized_user_prompt=f"Article: {article_title[:200]}",
                constraints_summary=f"domain={target_domain} operability={operability_status}",
            )

            try:
                # Use live adapter directly for article-to-lab (custom prompt)
                raw_candidate = boundary._live_adapter.call_generate(system_msg, user_msg)
                candidate = raw_candidate
            except Exception as exc:
                generation_failed = True
                failure_reason = "llm_call_failed"
                warnings.append(f"LLM generation failed: {type(exc).__name__}")

        else:
            # fake_only — use template-based generation
            from backend.labgen.llm_generation import FakeDraftGenerationAdapter, LabDraftGenerationRequest
            adapter = FakeDraftGenerationAdapter(inject_mode="valid")
            req = LabDraftGenerationRequest(
                user_prompt=f"Article: {article_title[:200]} | Domain: {target_domain}",
                requester_user_id=admin_user,
                constraints={"domain": target_domain, "mode": "article_to_lab"},
            )
            result = adapter.generate_lab_draft_candidate(req)
            if result.rejected_reason:
                generation_failed = True
                failure_reason = "adapter_rejected"
            else:
                candidate = result.candidate
                warnings = result.warnings or [
                    "fake generator: content is placeholder, admin review required"
                ]

        if generation_failed or candidate is None:
            audit.append(LLMAuditEntry(
                admin_user=admin_user,
                article_draft_id=draft_id,
                article_title=article_title,
                target_domain=target_domain,
                llm_mode=llm_mode,
                model_name=model_name,
                success=False,
                failure_reason=failure_reason or "generation_failed",
                operability_status=operability_status,
            ))
            raise LLMGenerationFailed(failure_reason or "generation_failed")

        # --- 4. Pydantic parse ---
        try:
            lab_draft = LabDraft.model_validate(candidate)
        except Exception as exc:
            errors = _extract_pydantic_errors(exc)
            audit.append(LLMAuditEntry(
                admin_user=admin_user,
                article_draft_id=draft_id,
                article_title=article_title,
                target_domain=target_domain,
                llm_mode=llm_mode,
                model_name=model_name,
                success=False,
                failure_reason="draft_parse_error",
                operability_status=operability_status,
            ))
            raise LLMDraftParseError(errors) from exc

        # --- 5. Force DRAFT status, set source_article_id, apply desired title ---
        lab_draft = lab_draft.model_copy(update={
            "publish_status": PublishStatus.DRAFT,
            "source_article_id": draft_id,
            "rehearsal_required": True,
        })
        if desired_lab_title:
            lab_draft = lab_draft.model_copy(update={"title": desired_lab_title[:200]})

        # --- 6. StaticValidator ---
        validator = StaticValidator()
        validator_results = validator.validate(lab_draft)
        has_blocking = any(
            r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
            for r in validator_results
        )
        from backend.labgen.llm_generation import _compute_publish_status
        lab_draft = lab_draft.model_copy(
            update={"publish_status": _compute_publish_status(validator_results)}
        )
        lab_draft.validator_results = validator_results

        # --- 7. Persist + 8. Audit (audit written in finally to survive persist failure) ---
        audit_entry = LLMAuditEntry(
            admin_user=admin_user,
            article_draft_id=draft_id,
            article_title=article_title,
            target_domain=target_domain,
            llm_mode=llm_mode,
            model_name=model_name,
            success=False,  # set True only after successful persist
            lab_draft_id=lab_draft.lab_id,
            operability_status=operability_status,
        )
        try:
            self._lab_repo.create(lab_draft)
            audit_entry.success = True
        finally:
            audit.append(audit_entry)

        logger.info(
            "ArticleDraftService.generate_lab_from_article: "
            "article_draft=%s → lab_draft=%s domain=%s mode=%s",
            draft_id,
            lab_draft.lab_id,
            target_domain,
            llm_mode,
        )

        return GenerateLabResult(
            lab_draft=lab_draft,
            audit_id=audit_entry.audit_id,
            operability_status=operability_status,
            warnings=warnings,
            validation_passed=not has_blocking,
        )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_draft(self, draft_id: str) -> None:
        """Delete an article draft. Source grounding snippets are deleted with it."""
        contract = self.get_draft(draft_id)
        if contract.status in (
            ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL,
        ):
            raise ArticleDraftTransitionForbidden(
                f"Cannot delete draft in status {contract.status} — "
                "advance or reject it first"
            )
        self._article_repo.delete(draft_id)
        logger.info("ArticleDraftService.delete_draft: %s", draft_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_validator_and_collect_blockers(self, contract: ArticleDraftLabContract) -> list[str]:
        """Run ArticleDraftValidator and return check_ids of all failing checks."""
        from backend.labgen.models import ValidatorStatus
        results = self._validator.validate(contract)
        return [r.check_id for r in results if r.status == ValidatorStatus.FAILED]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_pydantic_errors(exc: Exception) -> list[dict]:
    try:
        from pydantic import ValidationError
        if isinstance(exc, ValidationError):
            return [
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ]
    except Exception:
        pass
    return [{"msg": "candidate parse failed", "type": "parse_error"}]


def _pick_target_domain(feasibility: FeasibilityResult) -> TargetDomain:
    candidates = feasibility.target_domain_candidates
    if TargetDomain.K8S in candidates:
        return TargetDomain.K8S
    if TargetDomain.LINUX in candidates:
        return TargetDomain.LINUX
    if candidates:
        return candidates[0]
    return TargetDomain.UNKNOWN


def _build_lab_draft_from_contract(
    contract: ArticleDraftLabContract,
    converted_by: str,
) -> LabDraft:
    """
    Build a minimal LabDraft from an ArticleDraftLabContract.

    The draft is intentionally minimal — admin must fill in step details
    and verifier parameters before the LabDraft can be published.
    """
    steps: list[Step] = []
    for idx, step_desc in enumerate(contract.learner_steps):
        step_id = f"step_{idx + 1}"

        # Stub verifier — admin must configure parameters before publish
        verify_list: list[VerifyTemplate] = [
            VerifyTemplate(
                verify_id=f"{step_id}_v1",
                type=VerifyType.NAMESPACE_EXISTS,
                namespace="{{lab_namespace}}",
                name="{{lab_namespace}}",
                manual_review_required=True,
                notes="[TODO: configure verifier from article contract]",
            )
        ]

        # Try to reuse a verifier candidate from the contract
        if idx < len(contract.verifier_candidates):
            vc = contract.verifier_candidates[idx]
            if vc.primitive_name:
                try:
                    verify_list = [
                        VerifyTemplate(
                            verify_id=f"{step_id}_v1",
                            type=VerifyType(vc.primitive_name),
                            namespace=vc.parameters.get("namespace", "{{lab_namespace}}"),
                            name=vc.parameters.get("name", "{{lab_namespace}}"),
                            manual_review_required=not vc.admin_reviewed,
                            notes=vc.safe_message_template or None,
                        )
                    ]
                except (ValueError, KeyError):
                    pass

        steps.append(
            Step(
                step_id=step_id,
                order=idx + 1,
                why="[TODO: explain why this step matters]",
                do=step_desc,
                commands=[],
                observe="[TODO: describe what to observe after completing this step]",
                explain=ExplainField(
                    concept="[TODO: core concept]",
                    observation="[TODO: expected observation]",
                    confidence=ExplainConfidence.UNVERIFIED,
                    admin_verified=False,
                    published_to_student=False,
                ),
                verify=verify_list,
            )
        )

    if not steps:
        # Empty contract: create a placeholder step
        steps.append(
            Step(
                step_id="step_1",
                order=1,
                why="[TODO: explain why this step matters]",
                do="[TODO: Add step instructions from article]",
                commands=[],
                observe="[TODO: describe what to observe]",
                explain=ExplainField(
                    concept="[TODO: core concept]",
                    observation="[TODO: expected observation]",
                    confidence=ExplainConfidence.UNVERIFIED,
                    admin_verified=False,
                    published_to_student=False,
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="step_1_v1",
                        type=VerifyType.NAMESPACE_EXISTS,
                        namespace="{{lab_namespace}}",
                        name="{{lab_namespace}}",
                        manual_review_required=True,
                        notes="[TODO: configure verifier]",
                    )
                ],
            )
        )

    cleanup = CleanupSpec(
        namespace_cleanup=CleanupNamespace(
            type="delete_namespace",
            namespace="{{lab_namespace}}",
        ),
        cluster_scoped_resources=[],
        cleanup_verified=False,
    )

    return LabDraft(
        source_article_id=contract.draft_id,
        title=contract.source_metadata.title or "Untitled Lab (from article)",
        description=contract.learning_objective or "[TODO: Add description]",
        estimated_duration_minutes=contract.estimated_duration_minutes,
        steps=steps,
        runtime_requirements=RuntimeRequirements(),
        cleanup=cleanup,
        publish_status=PublishStatus.DRAFT,
        rehearsal_required=True,
    )
