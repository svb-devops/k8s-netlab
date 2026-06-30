"""
Learner Lab Catalog & Start Eligibility — read-only, learner-safe projection.

Design invariants:
  - Only PUBLISHED labs are exposed. Both missing and unpublished labs return None (→ 404).
  - No admin internals: no draft preview issues, no validator field details, no raw model output.
  - All string fields pass through sanitize_text before being placed in response models.
  - evaluate_start_eligibility is READ-ONLY: never persists, never creates sessions/audit events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from backend.labgen.models import (
    BlockingLevel,
    ImageStatus,
    LabSessionStatus,
    PublishStatus,
    ValidatorStatus,
)
from backend.labgen.static_validator import StaticValidator

if TYPE_CHECKING:
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.models import LabDraft
    from backend.labgen.repository import LabDraftRepository


# ---------------------------------------------------------------------------
# Issue codes (string constants — not an Enum to keep response schema stable)
# ---------------------------------------------------------------------------

class EligibilityIssueCode:
    NOT_PUBLISHED = "NOT_PUBLISHED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    IMAGE_STATUS_UNKNOWN = "IMAGE_STATUS_UNKNOWN"
    RUNTIME_CHECKS_DEFERRED = "RUNTIME_CHECKS_DEFERRED"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL_UNAVAILABLE = "INTERNAL_UNAVAILABLE"
    SESSION_ALREADY_ACTIVE = "SESSION_ALREADY_ACTIVE"


# ---------------------------------------------------------------------------
# Active states (mirrors lab_session_service._ACTIVE_STATES — kept local to
# avoid importing a private symbol and introducing a circular dependency)
# ---------------------------------------------------------------------------

_ACTIVE_STATES: frozenset[LabSessionStatus] = frozenset({
    LabSessionStatus.LAB_CREATED,
    LabSessionStatus.LAB_STARTING,
    LabSessionStatus.VM_PRECHECK_RUNNING,
    LabSessionStatus.IMAGE_CHECK_RUNNING,
    LabSessionStatus.NAMESPACE_CREATING,
    LabSessionStatus.NAMESPACE_READY,
    LabSessionStatus.VERIFIER_BINDING_CREATING,
    LabSessionStatus.LAB_ACTIVE,
    LabSessionStatus.CLEANUP_REQUESTED,
    LabSessionStatus.NAMESPACE_TERMINATING_WAIT,
    LabSessionStatus.CLEANUP_VERIFICATION_RUNNING,
})


# ---------------------------------------------------------------------------
# Response models — learner-safe; no admin fields
# ---------------------------------------------------------------------------


class LearnerLabEligibilityIssue(BaseModel):
    code: str
    message: str
    severity: str   # "error" | "warning"
    source: str     # "catalog" | "validator" | "image" | "session" | "runtime"


class LearnerLabEligibility(BaseModel):
    is_startable: bool
    issues: list[LearnerLabEligibilityIssue] = Field(default_factory=list)
    checked_at: str  # ISO 8601 UTC
    existing_session_id: Optional[str] = None  # set when SESSION_ALREADY_ACTIVE; frontend uses for Resume button


class LearnerLabStepPreview(BaseModel):
    step_id: str
    title: str
    learner_goal: str
    instructions_summary: str
    expected_outcome_summary: str
    check_count: int


class LearnerLabCatalogItem(BaseModel):
    lab_id: str
    title: str
    summary: str
    objective_count: int
    step_count: int
    estimated_difficulty: Optional[str] = None
    template_id: Optional[str] = None
    published_at: Optional[str] = None
    is_startable: bool


class LearnerLabDetail(BaseModel):
    lab_id: str
    title: str
    summary: str
    objectives: list[str] = Field(default_factory=list)
    steps_preview: list[LearnerLabStepPreview] = Field(default_factory=list)
    estimated_difficulty: Optional[str] = None
    template_id: Optional[str] = None
    start_eligibility: LearnerLabEligibility
    experiment_background: Optional[str] = None
    completion_summary: Optional[str] = None
    # Article binding (G-58) — only present when cta_enabled=True on the published lab.
    # source_article_id and raw article text are NEVER included.
    article_url: Optional[str] = None
    article_title: Optional[str] = None
    article_channel: Optional[str] = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LearnerCatalogService:
    def __init__(
        self,
        draft_repo: "LabDraftRepository",
        validator: StaticValidator,
        session_repo: Optional["LabSessionRepository"] = None,
    ) -> None:
        self._draft_repo = draft_repo
        self._validator = validator
        self._session_repo = session_repo

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize(text: str) -> str:
        from backend.labgen.llm_generation import sanitize_text
        return sanitize_text(text)

    def _has_blocking_validation_failures(self, draft: "LabDraft") -> bool:
        results = draft.validator_results
        if not results:
            # A published draft must have cached validator_results. If they are absent,
            # treat it as a blocking failure rather than silently re-running validation
            # inside a read-only catalog endpoint — absence indicates a data integrity issue.
            return True
        failed = [r for r in results if r.status == ValidatorStatus.FAILED]
        return any(
            r.blocking_level in (BlockingLevel.PUBLISH_BLOCKING, BlockingLevel.REVIEW_REQUIRED)
            for r in failed
        )

    @staticmethod
    def _has_blocked_images(draft: "LabDraft") -> bool:
        return any(r.image_status == ImageStatus.BLOCKED for r in draft.image_resolution)

    def _compute_is_startable(self, draft: "LabDraft") -> bool:
        if draft.publish_status != PublishStatus.PUBLISHED:
            return False
        if self._has_blocking_validation_failures(draft):
            return False
        if self._has_blocked_images(draft):
            return False
        return True

    @staticmethod
    def _build_step_preview(step) -> "LearnerLabStepPreview":
        from backend.labgen.llm_generation import sanitize_text

        return LearnerLabStepPreview(
            step_id=sanitize_text(step.step_id),
            title=sanitize_text(step.why)[:80],
            learner_goal=sanitize_text(step.why),
            instructions_summary=sanitize_text(step.do)[:200],
            expected_outcome_summary=sanitize_text(step.observe)[:200],
            check_count=len(step.verify) + len(step.linux_verify),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_published_labs(self, actor_user: str) -> list[LearnerLabCatalogItem]:
        """Return catalog items for all PUBLISHED labs — learner-safe."""
        items: list[LearnerLabCatalogItem] = []
        for draft in self._draft_repo.list_all():
            if draft.publish_status != PublishStatus.PUBLISHED:
                continue
            items.append(LearnerLabCatalogItem(
                lab_id=draft.lab_id,
                title=self._sanitize(draft.title),
                summary=self._sanitize(draft.description),
                objective_count=len(draft.steps),
                step_count=len(draft.steps),
                estimated_difficulty=None,
                template_id=None,
                published_at=None,
                is_startable=self._compute_is_startable(draft),
            ))
        return items

    def get_published_lab_detail(
        self, lab_id: str, actor_user: str
    ) -> Optional[LearnerLabDetail]:
        """
        Return learner-safe detail for a PUBLISHED lab.
        Returns None if the lab does not exist or is not PUBLISHED (→ 404, both cases).
        Never reveals whether an unpublished draft exists.
        """
        draft = self._draft_repo.get(lab_id)
        if draft is None or draft.publish_status != PublishStatus.PUBLISHED:
            return None

        eligibility = self._evaluate(draft, lab_id, actor_user)
        steps_preview = [self._build_step_preview(s) for s in draft.steps]
        objectives = [self._sanitize(s.why) for s in draft.steps]

        bg = (draft.experiment_background or "").strip()
        summary_text = (draft.completion_summary or "").strip()

        # Only expose article binding when admin has explicitly enabled CTA.
        # source_article_id is NEVER included — internal tracking only.
        art_url = art_title = art_channel = None
        if getattr(draft, "cta_enabled", False):
            art_url = self._sanitize(draft.article_url or "")[:2000] or None
            art_title = self._sanitize(draft.article_title or "")[:500] or None
            art_channel = self._sanitize(draft.article_channel or "")[:50] or None

        return LearnerLabDetail(
            lab_id=draft.lab_id,
            title=self._sanitize(draft.title),
            summary=self._sanitize(draft.description),
            objectives=objectives,
            steps_preview=steps_preview,
            estimated_difficulty=None,
            template_id=None,
            start_eligibility=eligibility,
            experiment_background=self._sanitize(bg) if bg else None,
            completion_summary=self._sanitize(summary_text) if summary_text else None,
            article_url=art_url,
            article_title=art_title,
            article_channel=art_channel,
        )

    def evaluate_start_eligibility(
        self, lab_id: str, actor_user: str
    ) -> Optional[LearnerLabEligibility]:
        """
        Evaluate whether actor_user may start this lab right now.
        Returns None if the lab does not exist or is not PUBLISHED (→ 404).
        READ-ONLY: does not create sessions, namespaces, audit events, or VM operations.
        ALLOWED does not guarantee start success — start re-runs image TTL recheck.
        """
        draft = self._draft_repo.get(lab_id)
        if draft is None or draft.publish_status != PublishStatus.PUBLISHED:
            return None
        return self._evaluate(draft, lab_id, actor_user)

    # ------------------------------------------------------------------
    # Core eligibility logic
    # ------------------------------------------------------------------

    def _evaluate(
        self, draft: "LabDraft", lab_id: str, actor_user: str
    ) -> LearnerLabEligibility:
        checked_at = datetime.now(tz=timezone.utc).isoformat()
        issues: list[LearnerLabEligibilityIssue] = []
        is_startable = True

        # 1. Validation check
        if self._has_blocking_validation_failures(draft):
            is_startable = False
            issues.append(LearnerLabEligibilityIssue(
                code=EligibilityIssueCode.VALIDATION_FAILED,
                message=self._sanitize(
                    "Lab draft has validation errors that must be resolved before starting"
                ),
                severity="error",
                source="validator",
            ))

        # 2. Image check — BLOCKED images are a hard stop
        if self._has_blocked_images(draft):
            is_startable = False
            issues.append(LearnerLabEligibilityIssue(
                code=EligibilityIssueCode.IMAGE_STATUS_UNKNOWN,
                message=self._sanitize(
                    "One or more required container images are not available"
                ),
                severity="error",
                source="image",
            ))

        # 3. Active session check — mirrors start precheck; only if session_repo injected
        existing_session_id: Optional[str] = None
        if self._session_repo is not None:
            from backend.labgen.models import SessionType
            existing = self._session_repo.list_by_student(actor_user)
            active_match = next(
                (s for s in existing
                 if s.lab_id == lab_id
                 and s.lab_session_status in _ACTIVE_STATES
                 and s.session_type != SessionType.INTERNAL_REHEARSAL),
                None,
            )
            if active_match is not None:
                is_startable = False
                existing_session_id = active_match.session_id
                issues.append(LearnerLabEligibilityIssue(
                    code=EligibilityIssueCode.SESSION_ALREADY_ACTIVE,
                    message=self._sanitize(
                        "You already have an active session for this lab"
                    ),
                    severity="error",
                    source="session",
                ))

        # 4. Runtime checks deferred — always added when no hard blocks
        #    Image TTL recheck only runs at actual start time, not here.
        if is_startable:
            issues.append(LearnerLabEligibilityIssue(
                code=EligibilityIssueCode.RUNTIME_CHECKS_DEFERRED,
                message=self._sanitize(
                    "Image availability and runtime checks will be verified at start time"
                ),
                severity="warning",
                source="runtime",
            ))

        return LearnerLabEligibility(
            is_startable=is_startable,
            issues=issues,
            checked_at=checked_at,
            existing_session_id=existing_session_id,
        )
