"""
Draft Preview & Review Snapshot — read-only API-safe projection of LabDraft.

Design invariants:
  - build_snapshot is READ-ONLY: never persists, never mutates draft state.
  - No raw LLM output, no kubeconfig, no credential material, no tracebacks.
  - All string fields are sanitized via sanitize_text before returning.
  - DraftPreviewSnapshot is the only type exposed to HTTP responses.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.labgen.image_readiness import ImageReadinessResult, ImageReadinessService, ImageReadinessStatus
from backend.labgen.models import BlockingLevel, LabDraft, ValidatorStatus
from backend.labgen.repository import LabDraftRepository
from backend.labgen.static_validator import StaticValidator


# ---------------------------------------------------------------------------
# Snapshot models
# ---------------------------------------------------------------------------


class DraftPreviewSourceInfo(BaseModel):
    source_type: str = "unknown"  # manual | generated | repaired | unknown
    selected_template_id: Optional[str] = None
    generation_warnings: list[str] = Field(default_factory=list)
    repair_applied: Optional[bool] = None


class DraftPreviewCheck(BaseModel):
    check_id: str
    check_type: str
    description: str
    safe_expectation_summary: str


class DraftPreviewStep(BaseModel):
    step_id: str
    title: str
    learner_goal: str
    instructions_summary: str
    expected_outcome_summary: str
    checks: list[DraftPreviewCheck] = Field(default_factory=list)


class DraftPreviewIssue(BaseModel):
    code: str
    message: str
    severity: str  # "error" | "warning"
    path: Optional[str] = None
    source: str  # "static_validator" | "pydantic" | "safety"


class DraftPreviewSummary(BaseModel):
    objective_count: int
    step_count: int
    check_count: int
    estimated_difficulty: Optional[str] = None
    template_id: Optional[str] = None
    has_repair_history: bool = False


class DraftPreviewSnapshot(BaseModel):
    draft_id: str
    title: str
    publish_status: str
    validation_status: str  # "passed" | "failed" | "not_validated"
    source_info: DraftPreviewSourceInfo
    summary: DraftPreviewSummary
    objectives: list[str]
    steps: list[DraftPreviewStep]
    issues: list[DraftPreviewIssue] = Field(default_factory=list)
    generated_at: Optional[str] = None
    updated_at: Optional[str] = None
    image_readiness: Optional[ImageReadinessResult] = None
    is_publishable: bool


# ---------------------------------------------------------------------------
# Recursive sanitizer
# ---------------------------------------------------------------------------


def sanitize_value(v: Any) -> Any:
    """
    Recursively sanitize strings in dicts/lists/scalars.

    Exported as a utility for callers that work with raw dicts (e.g., tests,
    API middleware, external consumers).  build_snapshot uses inline
    sanitize_text() calls instead of this helper so that each field is
    sanitized before being assigned to a typed Pydantic model attribute.
    """
    from backend.labgen.llm_generation import sanitize_text

    if isinstance(v, str):
        return sanitize_text(v)
    if isinstance(v, list):
        return [sanitize_value(item) for item in v]
    if isinstance(v, dict):
        return {k: sanitize_value(val) for k, val in v.items()}
    return v


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DraftPreviewService:
    def __init__(
        self,
        repo: LabDraftRepository,
        validator: StaticValidator,
        image_readiness_svc: Optional[ImageReadinessService] = None,
    ) -> None:
        self._repo = repo
        self._validator = validator
        self._image_readiness_svc = image_readiness_svc

    def build_snapshot(self, draft_id: str) -> Optional[DraftPreviewSnapshot]:
        """
        Build a read-only preview snapshot for the given draft.
        Returns None if the draft does not exist.
        Never persists anything. Never mutates the draft.
        """
        from backend.labgen.llm_generation import sanitize_text

        draft = self._repo.get(draft_id)
        if draft is None:
            return None

        # Run validator if no cached results — read-only, don't persist
        validator_results = list(draft.validator_results)
        if not validator_results:
            validator_results = self._validator.validate(draft)

        # Derive validation_status
        failed_results = [r for r in validator_results if r.status == ValidatorStatus.FAILED]
        if not validator_results:
            validation_status = "not_validated"
        elif failed_results:
            validation_status = "failed"
        else:
            validation_status = "passed"

        # Build issues (failed validator checks only)
        issues: list[DraftPreviewIssue] = []
        for r in failed_results:
            severity = (
                "error"
                if r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
                else "warning"
            )
            issues.append(
                DraftPreviewIssue(
                    code=r.check_id,
                    message=sanitize_text(r.message),
                    severity=severity,
                    path=r.field_path if r.field_path else None,
                    source="static_validator",
                )
            )

        # is_publishable: no PUBLISH_BLOCKING or REVIEW_REQUIRED failures + image readiness
        publish_blocking = any(
            r.blocking_level == BlockingLevel.PUBLISH_BLOCKING for r in failed_results
        )
        review_required = any(
            r.blocking_level == BlockingLevel.REVIEW_REQUIRED for r in failed_results
        )

        # Image readiness — only gates is_publishable when service is injected
        image_readiness: Optional[ImageReadinessResult] = None
        if self._image_readiness_svc is not None:
            image_readiness = self._image_readiness_svc.evaluate(list(draft.image_resolution))

        image_ready = (
            image_readiness is None
            or image_readiness.status == ImageReadinessStatus.READY
        )
        is_publishable = not publish_blocking and not review_required and image_ready

        # Build steps
        steps: list[DraftPreviewStep] = []
        total_checks = 0
        for step in draft.steps:
            checks: list[DraftPreviewCheck] = []
            for v in step.verify:
                desc = sanitize_text(v.notes or f"verify {v.type.value}")
                expectation = sanitize_text(
                    f"{v.type.value}: {v.name} in {v.namespace}"
                )
                checks.append(
                    DraftPreviewCheck(
                        check_id=v.verify_id,
                        check_type=v.type.value,
                        description=desc,
                        safe_expectation_summary=expectation,
                    )
                )
                total_checks += 1

            # Sanitize before slicing so credential patterns are not split at the boundary
            steps.append(
                DraftPreviewStep(
                    step_id=step.step_id,
                    title=sanitize_text(step.why)[:80],
                    learner_goal=sanitize_text(step.why),
                    instructions_summary=sanitize_text(step.do)[:200],
                    expected_outcome_summary=sanitize_text(step.observe)[:200],
                    checks=checks,
                )
            )

        objectives = [sanitize_text(s.why) for s in draft.steps]

        summary = DraftPreviewSummary(
            objective_count=len(draft.steps),
            step_count=len(draft.steps),
            check_count=total_checks,
            estimated_difficulty=None,
            template_id=None,
            has_repair_history=False,
        )

        # source_type is always "unknown" — LabDraft doesn't store provenance
        source_info = DraftPreviewSourceInfo(
            source_type="unknown",
            selected_template_id=None,
            generation_warnings=[],
            repair_applied=None,
        )

        return DraftPreviewSnapshot(
            draft_id=draft.lab_id,
            title=sanitize_text(draft.title),
            publish_status=draft.publish_status.value,
            validation_status=validation_status,
            source_info=source_info,
            summary=summary,
            objectives=objectives,
            steps=steps,
            issues=issues,
            generated_at=(
                draft.created_at.isoformat() if draft.created_at else None
            ),
            updated_at=(
                draft.updated_at.isoformat() if draft.updated_at else None
            ),
            image_readiness=image_readiness,
            is_publishable=is_publishable,
        )
