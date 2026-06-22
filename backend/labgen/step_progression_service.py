"""
Lab Step Progression Service — checks the current step's verify templates
and advances current_step_index when all pass.

Security constraints:
- Only LAB_ACTIVE sessions may be checked.
- Only the session owner may check their own session.
- Only the current step (current_step_index) may be checked.
- VerifyTemplate is always read from the published LabDraft, never from the caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.models import (
    LabDomainType,
    LabSessionStatus,
    PublishStatus,
    RuntimeAuditEventType,
    SchemaVersionedModel,
    SessionType,
    VerifyResult,
)
from backend.labgen.runtime_audit import RuntimeAuditService

if TYPE_CHECKING:
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.linux_verifier_client import LinuxVerifierService
    from backend.labgen.repository import LabDraftRepository
    from backend.labgen.verifier import VerifierService


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class StepCheckResponse(SchemaVersionedModel):
    session_id: str
    step_id: str
    all_passed: bool
    advanced: bool
    ready_to_complete: bool
    verify_results: list[VerifyResult]
    failure_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StepSessionNotFound(Exception):
    pass


class StepSessionNotActive(Exception):
    pass


class StepAccessDenied(Exception):
    pass


class StepDraftUnavailable(Exception):
    pass


class StepNotCurrent(Exception):
    pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class StepProgressionService:
    def __init__(
        self,
        session_repo: "LabSessionRepository",
        draft_repo: "LabDraftRepository",
        verifier_svc: "VerifierService",
        audit_svc: Optional[RuntimeAuditService] = None,
        linux_verifier_svc: Optional["LinuxVerifierService"] = None,
    ) -> None:
        self._session_repo = session_repo
        self._draft_repo = draft_repo
        self._verifier_svc = verifier_svc
        self._audit_svc = audit_svc
        self._linux_verifier_svc = linux_verifier_svc

    def _audit(
        self,
        session_id: str,
        event_type: RuntimeAuditEventType,
        failure_reason: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        if self._audit_svc is not None:
            self._audit_svc.record(session_id, event_type, failure_reason=failure_reason, metadata=metadata)

    def check_step(
        self,
        session_id: str,
        step_id: str,
        username: str,
    ) -> StepCheckResponse:
        session = self._session_repo.get(session_id)
        if session is None:
            raise StepSessionNotFound(session_id)

        if session.lab_session_status != LabSessionStatus.LAB_ACTIVE:
            raise StepSessionNotActive(f"status={session.lab_session_status.value}")

        if session.student_username != username:
            raise StepAccessDenied(session_id)

        draft = self._draft_repo.get(session.lab_id)
        is_rehearsal = session.session_type == SessionType.INTERNAL_REHEARSAL
        if draft is None or (
            draft.publish_status != PublishStatus.PUBLISHED and not is_rehearsal
        ):
            raise StepDraftUnavailable(session.lab_id)

        if not draft.steps:
            raise StepDraftUnavailable(f"no steps in lab {session.lab_id}")

        current_idx = session.current_step_index
        if current_idx >= len(draft.steps):
            raise StepNotCurrent("all steps already completed")

        current_step = draft.steps[current_idx]
        if current_step.step_id != step_id:
            raise StepNotCurrent(
                f"current step is {current_step.step_id!r}, requested {step_id!r}"
            )

        # Run all verify templates from the published draft (caller cannot inject templates).
        # Linux domain labs use linux_verify templates and the Linux verifier service.
        # K8s domain labs (and all others) use verify templates and the K8s verifier service.
        if draft.target_domain == LabDomainType.LINUX:
            if self._linux_verifier_svc is None:
                not_configured = VerifyResult(
                    session_id=session_id,
                    verify_id="linux_verifier_not_configured",
                    verify_type="linux",
                    passed=False,
                    error_code=FailureReason.LINUX_VERIFIER_NOT_CONFIGURED.value,
                    failure_reason=FailureReason.LINUX_VERIFIER_NOT_CONFIGURED.value,
                    detail="Linux verifier service is not configured for this environment.",
                )
                self._session_repo.update(session)
                return StepCheckResponse(
                    session_id=session_id,
                    step_id=step_id,
                    all_passed=False,
                    advanced=False,
                    ready_to_complete=session.ready_to_complete,
                    verify_results=[not_configured],
                    failure_reason=FailureReason.LINUX_VERIFIER_NOT_CONFIGURED.value,
                )
            verify_results: list[VerifyResult] = [
                self._linux_verifier_svc.check(session_id, tmpl)
                for tmpl in current_step.linux_verify
            ]
        else:
            verify_results = [
                self._verifier_svc.check(session_id, template)
                for template in current_step.verify
            ]

        # all([]) is True — steps with no verify templates advance automatically
        all_passed = all(r.passed for r in verify_results)

        session.last_verify_results = verify_results

        advanced = False
        if all_passed:
            session.current_step_index = current_idx + 1
            session.completed_step_ids.append(step_id)
            advanced = True

            if session.current_step_index >= len(draft.steps):
                session.ready_to_complete = True

            self._audit(
                session_id,
                RuntimeAuditEventType.STEP_CHECK_PASSED,
                metadata={"step_id": step_id, "step_index": current_idx},
            )
        else:
            first_failure = next(
                (r.failure_reason for r in verify_results if not r.passed and r.failure_reason),
                None,
            )
            self._audit(
                session_id,
                RuntimeAuditEventType.STEP_CHECK_FAILED,
                failure_reason=first_failure,
                metadata={"step_id": step_id, "step_index": current_idx},
            )

        self._session_repo.update(session)

        return StepCheckResponse(
            session_id=session_id,
            step_id=step_id,
            all_passed=all_passed,
            advanced=advanced,
            ready_to_complete=session.ready_to_complete,
            verify_results=verify_results,
        )
