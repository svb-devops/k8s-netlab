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


class PublishDecisionStatus(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"


class PublishBlockReasonCode(str, Enum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PREVIEW_NOT_PUBLISHABLE = "PREVIEW_NOT_PUBLISHABLE"
    DRAFT_NOT_FOUND = "DRAFT_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_DRAFT_STATE = "INVALID_DRAFT_STATE"
    SENSITIVE_CONTENT_DETECTED = "SENSITIVE_CONTENT_DETECTED"


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

    def __init__(self, preview_svc: DraftPreviewService) -> None:
        self._preview_svc = preview_svc

    def evaluate(self, draft_id: str) -> PublishDecision:
        from backend.labgen.llm_generation import sanitize_text

        checked_at = datetime.now(tz=timezone.utc).isoformat()
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

        if not snapshot.is_publishable:
            # Always include a top-level summary code so callers can check for
            # VALIDATION_FAILED / PREVIEW_NOT_PUBLISHABLE without inspecting every issue.
            has_validator_failure = snapshot.validation_status == "failed"
            block_code = (
                PublishBlockReasonCode.VALIDATION_FAILED
                if has_validator_failure
                else PublishBlockReasonCode.PREVIEW_NOT_PUBLISHABLE
            )
            decision_issues.append(
                PublishDecisionIssue(
                    code=block_code.value,
                    message=sanitize_text(
                        "Validation failed: draft cannot be published"
                        if has_validator_failure
                        else "Preview indicates draft is not publishable"
                    ),
                    severity="error",
                    source="validator" if has_validator_failure else "preview",
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
