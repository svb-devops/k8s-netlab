"""
Admin Publish Decision Gate — read-only service evaluating whether a draft is
safe to publish. Never mutates draft state, never creates sessions or events.

Design invariants:
  - evaluate() is READ-ONLY: never calls repo.update, no sessions, no audit events.
  - Uses DraftPreviewService so preview and publish-decision share validator logic.
  - All message strings are sanitized via sanitize_text before returning.
  - No raw exception, no stack trace, no credential material in any field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from backend.labgen.draft_preview import DraftPreviewService, DraftPreviewSummary
from backend.labgen.image_readiness import ImageReadinessStatus
from backend.labgen.repository import LabDraftRepository


class PublishDecisionStatus(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"


class PublishBlockReasonCode(str, Enum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PREVIEW_NOT_PUBLISHABLE = "PREVIEW_NOT_PUBLISHABLE"
    IMAGE_READINESS_BLOCKED = "IMAGE_READINESS_BLOCKED"
    DRAFT_NOT_FOUND = "DRAFT_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_DRAFT_STATE = "INVALID_DRAFT_STATE"
    SENSITIVE_CONTENT_DETECTED = "SENSITIVE_CONTENT_DETECTED"
    REHEARSAL_REQUIRED = "REHEARSAL_REQUIRED"


class PublishDecisionIssue(BaseModel):
    code: str
    message: str
    severity: str  # "error" | "warning"
    path: Optional[str] = None
    source: str  # "validator" | "preview" | "permission" | "safety" | "state"


class PublishDecision(BaseModel):
    status: PublishDecisionStatus
    is_publishable: bool
    draft_id: str
    validation_status: str
    preview_summary: Optional[DraftPreviewSummary] = None
    issues: list[PublishDecisionIssue] = Field(default_factory=list)
    checked_at: str  # ISO 8601 UTC


class PublishDecisionService:
    """
    Evaluates whether a draft may be published.

    Read-only: never calls repo.update, never creates sessions or audit events.
    Delegates to DraftPreviewService so preview and publish-decision share the
    same StaticValidator run and issue-mapping logic.
    """

    def __init__(
        self,
        preview_svc: DraftPreviewService,
        draft_repo: Optional[LabDraftRepository] = None,
    ) -> None:
        self._preview_svc = preview_svc
        self._draft_repo = draft_repo

    def evaluate(self, draft_id: str) -> PublishDecision:
        from backend.labgen.llm_generation import sanitize_text

        checked_at = datetime.now(tz=timezone.utc).isoformat()

        # Rehearsal gate: article-pipeline drafts must complete an internal rehearsal
        # before publish. Check before snapshot so we don't leak validator state.
        if self._draft_repo is not None:
            draft = self._draft_repo.get(draft_id)
            if draft is not None and draft.rehearsal_required and not draft.rehearsal_completed:
                return PublishDecision(
                    status=PublishDecisionStatus.BLOCKED,
                    is_publishable=False,
                    draft_id=draft_id,
                    validation_status="rehearsal_required",
                    preview_summary=None,
                    issues=[
                        PublishDecisionIssue(
                            code=PublishBlockReasonCode.REHEARSAL_REQUIRED.value,
                            message=sanitize_text(
                                "This lab was generated from an article and must complete "
                                "an internal rehearsal session before it can be published."
                            ),
                            severity="error",
                            source="state",
                        )
                    ],
                    checked_at=checked_at,
                )

        snapshot = self._preview_svc.build_snapshot(draft_id)

        if snapshot is None:
            return PublishDecision(
                status=PublishDecisionStatus.BLOCKED,
                is_publishable=False,
                draft_id=draft_id,
                validation_status="not_found",
                preview_summary=None,
                issues=[
                    PublishDecisionIssue(
                        code=PublishBlockReasonCode.DRAFT_NOT_FOUND.value,
                        message="Draft not found",
                        severity="error",
                        source="state",
                    )
                ],
                checked_at=checked_at,
            )

        # Map snapshot issues -> decision issues.
        # draft_preview uses source="static_validator"; decision normalises to "validator"
        # so callers use the compact source vocabulary.
        decision_issues: list[PublishDecisionIssue] = [
            PublishDecisionIssue(
                code=issue.code,
                message=sanitize_text(issue.message),
                severity=issue.severity,
                path=issue.path,
                source="validator",
            )
            for issue in snapshot.issues
        ]

        # Map image readiness issues — include both errors and warnings so callers can
        # distinguish validator failures from image resolution failures.
        image_readiness_blocked = False
        if snapshot.image_readiness is not None:
            for ir_issue in snapshot.image_readiness.issues:
                decision_issues.append(PublishDecisionIssue(
                    code=ir_issue.code,
                    message=sanitize_text(ir_issue.message),
                    severity=ir_issue.severity,
                    path=ir_issue.path,
                    source="image_readiness",
                ))
            if snapshot.image_readiness.status != ImageReadinessStatus.READY:
                image_readiness_blocked = True

        if not snapshot.is_publishable:
            # Add top-level summary codes so callers can quickly filter issues by source.
            # Multiple summary codes can coexist (e.g. validator + image readiness both fail).
            has_validator_failure = snapshot.validation_status == "failed"

            if image_readiness_blocked:
                decision_issues.append(
                    PublishDecisionIssue(
                        code=PublishBlockReasonCode.IMAGE_READINESS_BLOCKED.value,
                        message=sanitize_text(
                            "Image readiness check failed — resolve all images before publishing"
                        ),
                        severity="error",
                        source="image_readiness",
                    )
                )

            if has_validator_failure:
                decision_issues.append(
                    PublishDecisionIssue(
                        code=PublishBlockReasonCode.VALIDATION_FAILED.value,
                        message=sanitize_text(
                            "Validation failed: draft cannot be published"
                        ),
                        severity="error",
                        source="validator",
                    )
                )
            elif not image_readiness_blocked:
                # Not publishable for some other reason (should be rare)
                decision_issues.append(
                    PublishDecisionIssue(
                        code=PublishBlockReasonCode.PREVIEW_NOT_PUBLISHABLE.value,
                        message=sanitize_text(
                            "Preview indicates draft is not publishable"
                        ),
                        severity="error",
                        source="preview",
                    )
                )

        decision_status = (
            PublishDecisionStatus.ALLOWED
            if snapshot.is_publishable
            else PublishDecisionStatus.BLOCKED
        )

        return PublishDecision(
            status=decision_status,
            is_publishable=snapshot.is_publishable,
            draft_id=draft_id,
            validation_status=snapshot.validation_status,
            preview_summary=snapshot.summary,
            issues=decision_issues,
            checked_at=checked_at,
        )
