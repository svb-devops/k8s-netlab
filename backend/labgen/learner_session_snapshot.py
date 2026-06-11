"""
Learner Runtime Session Snapshot — read-only, learner-safe projection of LabSessionState.

Design invariants:
  - Only the session owner and admins may see a session (enforced by route via is_admin flag).
  - No internal fields: no namespace, no vm_id, no kubeconfig, no credentials.
  - All string fields pass through sanitize_text before being placed in response models.
  - Build and list operations are READ-ONLY: never persist, never start/check/complete/abort/cleanup.
  - failure_reason values use FailureReason stable machine codes (no raw exception text).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from backend.labgen.models import LabSessionStatus

if TYPE_CHECKING:
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.models import LabDraft, LabSessionState, Step
    from backend.labgen.repository import LabDraftRepository


# ---------------------------------------------------------------------------
# Closed / terminal state sets (local copies — avoid importing private symbols)
# ---------------------------------------------------------------------------

# States from which abort() raises SessionAlreadyTerminated, plus transient
# post-completion states that the UI should treat as done.
_NOT_ABORTABLE: frozenset[LabSessionStatus] = frozenset({
    LabSessionStatus.LAB_CLOSED,
    LabSessionStatus.LAB_CLEANUP_FAILED,
    LabSessionStatus.LAB_START_FAILED,
    LabSessionStatus.LAB_COMPLETED,
    LabSessionStatus.LAB_ABORTED,
    LabSessionStatus.LAB_TIMEOUT,
    LabSessionStatus.CLEANUP_VERIFIED,
})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SnapshotNotFound(Exception):
    pass


class SnapshotAccessDenied(Exception):
    pass


# ---------------------------------------------------------------------------
# Response models — learner-safe; no admin fields, no credentials
# ---------------------------------------------------------------------------


class LearnerSessionIssue(BaseModel):
    code: str
    message: str
    severity: str   # "error" | "warning" | "info"
    source: str     # "session" | "cleanup" | "step" | "vm"


class LearnerSessionCheckSummary(BaseModel):
    last_checked_at: Optional[str] = None   # ISO 8601 UTC, None if not checked
    last_result: str                         # "passed" | "failed" | "not_checked" | "unknown"
    safe_message: Optional[str] = None       # pre-defined safe string, never raw check output
    failure_reason: Optional[str] = None     # FailureReason stable code, sanitized


class LearnerSessionStepStatus(BaseModel):
    step_id: str
    title: str
    learner_goal: str
    status: str         # "passed" | "available" | "locked"
    is_current: bool
    check_summary: Optional[LearnerSessionCheckSummary] = None


class LearnerSessionRuntimeSummary(BaseModel):
    vm_status: str                   # safe label for session.lab_session_status
    ready_to_complete: bool
    cleanup_status: Optional[str] = None   # "verified" | "failed" | "closed" | None
    tainted: Optional[bool] = None
    failure_reason: Optional[str] = None   # sanitized FailureReason code


class LearnerSessionActionAvailability(BaseModel):
    can_check_current_step: bool
    can_complete: bool
    can_abort: bool
    disabled_reasons: list[LearnerSessionIssue] = Field(default_factory=list)


class LearnerSessionSnapshot(BaseModel):
    session_id: str
    lab_id: str
    title: str
    session_state: str                         # LabSessionStatus.value
    current_step_id: Optional[str] = None
    steps: list[LearnerSessionStepStatus] = Field(default_factory=list)
    runtime_summary: LearnerSessionRuntimeSummary
    action_availability: LearnerSessionActionAvailability
    issues: list[LearnerSessionIssue] = Field(default_factory=list)
    checked_at: str                            # ISO 8601 UTC


class LearnerSessionListItem(BaseModel):
    session_id: str
    lab_id: str
    title: str                          # from draft, "Unknown Lab" if unavailable
    session_state: str                  # LabSessionStatus.value
    current_step_id: Optional[str] = None
    ready_to_complete: bool
    started_at: Optional[str] = None   # ISO 8601 UTC


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitize(text: str) -> str:
    from backend.labgen.llm_generation import sanitize_text
    return sanitize_text(text)


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _check_summary_for_step(
    session: "LabSessionState",
    step: "Step",
) -> Optional[LearnerSessionCheckSummary]:
    """Compute check summary for the given step using session.last_verify_results.

    Returns None if session is not active (stale results don't apply).
    Returns LearnerSessionCheckSummary with last_result="not_checked" if no matching results.
    """
    if session.lab_session_status != LabSessionStatus.LAB_ACTIVE:
        return None

    results = session.last_verify_results
    if not results or not step.verify:
        return LearnerSessionCheckSummary(last_result="not_checked")

    current_ids = {vt.verify_id for vt in step.verify}
    result_ids = {r.verify_id for r in results}

    # No overlap → results are from a previous step
    if not current_ids.intersection(result_ids):
        return LearnerSessionCheckSummary(last_result="not_checked")

    all_passed = all(r.passed for r in results)
    if all_passed:
        return LearnerSessionCheckSummary(
            last_result="passed",
            safe_message=_sanitize("All checks passed"),
        )

    first_failure = next((r for r in results if not r.passed), None)
    failure_reason = None
    if first_failure and first_failure.failure_reason:
        failure_reason = _sanitize(first_failure.failure_reason)
    return LearnerSessionCheckSummary(
        last_result="failed",
        safe_message=_sanitize("One or more checks did not pass. Please review and try again."),
        failure_reason=failure_reason,
    )


def _build_step_statuses(
    session: "LabSessionState",
    steps: list["Step"],
) -> tuple[Optional[str], list[LearnerSessionStepStatus]]:
    """Derive per-step status from session state. Returns (current_step_id, step_list)."""
    result: list[LearnerSessionStepStatus] = []
    current_idx = session.current_step_index
    current_step_id: Optional[str] = None

    for idx, step in enumerate(steps):
        safe_id = _sanitize(step.step_id)
        safe_title = _sanitize(step.why)[:80]
        safe_goal = _sanitize(step.why)

        if safe_id in session.completed_step_ids or step.step_id in session.completed_step_ids:
            st = "passed"
            is_current = False
            check_summary = None
        elif idx == current_idx:
            st = "available"
            is_current = True
            current_step_id = safe_id
            check_summary = _check_summary_for_step(session, step)
        else:
            st = "locked"
            is_current = False
            check_summary = None

        result.append(LearnerSessionStepStatus(
            step_id=safe_id,
            title=safe_title,
            learner_goal=safe_goal,
            status=st,
            is_current=is_current,
            check_summary=check_summary,
        ))

    return current_step_id, result


def _build_runtime_summary(session: "LabSessionState") -> LearnerSessionRuntimeSummary:
    cleanup_status: Optional[str] = None
    if session.cleanup_verified:
        cleanup_status = "verified"
    elif session.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED:
        cleanup_status = "failed"
    elif session.lab_session_status == LabSessionStatus.LAB_CLOSED:
        cleanup_status = "closed"

    tainted: Optional[bool] = None
    if session.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED:
        tainted = True

    failure_reason: Optional[str] = None
    if session.failure_reason:
        failure_reason = _sanitize(session.failure_reason)

    return LearnerSessionRuntimeSummary(
        vm_status=session.lab_session_status.value,
        ready_to_complete=session.ready_to_complete,
        cleanup_status=cleanup_status,
        tainted=tainted,
        failure_reason=failure_reason,
    )


def _build_action_availability(
    session: "LabSessionState",
) -> LearnerSessionActionAvailability:
    disabled: list[LearnerSessionIssue] = []

    can_check = session.lab_session_status == LabSessionStatus.LAB_ACTIVE
    can_complete = (
        session.ready_to_complete
        and session.lab_session_status not in _NOT_ABORTABLE
    )
    can_abort = session.lab_session_status not in _NOT_ABORTABLE

    if not can_check:
        disabled.append(LearnerSessionIssue(
            code="NOT_ACTIVE",
            message=_sanitize("Lab session is not active"),
            severity="info",
            source="session",
        ))

    if not can_complete:
        if session.lab_session_status in _NOT_ABORTABLE:
            disabled.append(LearnerSessionIssue(
                code="SESSION_CLOSED",
                message=_sanitize("Session is already closed or terminated"),
                severity="info",
                source="session",
            ))
        else:
            disabled.append(LearnerSessionIssue(
                code="NOT_READY_TO_COMPLETE",
                message=_sanitize("All steps must be completed before finishing the lab"),
                severity="info",
                source="step",
            ))

    if not can_abort and can_complete is False and session.lab_session_status in _NOT_ABORTABLE:
        # SESSION_CLOSED already added above; only add if it wasn't
        pass  # already covered

    # Tainted VM warning in action context
    if session.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED:
        disabled.append(LearnerSessionIssue(
            code="VM_TAINTED",
            message=_sanitize("Lab cleanup failed. Contact an administrator."),
            severity="error",
            source="vm",
        ))

    return LearnerSessionActionAvailability(
        can_check_current_step=can_check,
        can_complete=can_complete,
        can_abort=can_abort,
        disabled_reasons=disabled,
    )


def _build_session_issues(session: "LabSessionState") -> list[LearnerSessionIssue]:
    from backend.labgen.failure_reasons import FailureReason
    issues: list[LearnerSessionIssue] = []
    if session.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED:
        issues.append(LearnerSessionIssue(
            code="CLEANUP_FAILED",
            message=_sanitize("Lab cleanup failed. Your virtual machine may require administrator attention."),
            severity="error",
            source="cleanup",
        ))
    elif session.lab_session_status == LabSessionStatus.LAB_START_FAILED:
        failure_reason = _sanitize(session.failure_reason) if session.failure_reason else None
        issues.append(LearnerSessionIssue(
            code="START_FAILED",
            message=_sanitize("Lab failed to start. Please try again or contact an administrator."),
            severity="error",
            source="session",
        ))
        if failure_reason:
            issues.append(LearnerSessionIssue(
                code="START_FAILED_REASON",
                message=failure_reason,
                severity="error",
                source="session",
            ))
    if session.failure_reason == FailureReason.LAB_TIMEOUT.value:
        issues.append(LearnerSessionIssue(
            code="LAB_TIMEOUT",
            message=_sanitize("Lab session exceeded the time limit and was automatically closed."),
            severity="info",
            source="session",
        ))
    return issues


def _current_step_id_from_session(
    session: "LabSessionState",
    steps: list["Step"],
) -> Optional[str]:
    idx = session.current_step_index
    if idx < len(steps):
        return _sanitize(steps[idx].step_id)
    return None


def _list_item_from_session(
    session: "LabSessionState",
    title: str,
    steps: list["Step"],
) -> LearnerSessionListItem:
    current_step_id: Optional[str] = None
    if steps:
        idx = session.current_step_index
        if idx < len(steps):
            current_step_id = _sanitize(steps[idx].step_id)

    return LearnerSessionListItem(
        session_id=session.session_id,
        lab_id=session.lab_id,
        title=_sanitize(title),
        session_state=session.lab_session_status.value,
        current_step_id=current_step_id,
        ready_to_complete=session.ready_to_complete,
        started_at=_fmt_dt(session.started_at),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LearnerSessionSnapshotService:
    def __init__(
        self,
        session_repo: "LabSessionRepository",
        draft_repo: "LabDraftRepository",
    ) -> None:
        self._session_repo = session_repo
        self._draft_repo = draft_repo

    def _get_draft_title_and_steps(
        self, lab_id: str
    ) -> tuple[str, list["Step"]]:
        """Return (title, steps) from draft, with safe fallback when unavailable."""
        draft = self._draft_repo.get(lab_id)
        if draft is None:
            return "Unknown Lab", []
        return draft.title, draft.steps

    def list_my_sessions(
        self,
        actor_user: str,
        status_filter: Optional[str] = None,
        lab_id_filter: Optional[str] = None,
    ) -> list[LearnerSessionListItem]:
        sessions = self._session_repo.list_by_student(actor_user)

        if status_filter:
            sessions = [s for s in sessions if s.lab_session_status.value == status_filter]
        if lab_id_filter:
            sessions = [s for s in sessions if s.lab_id == lab_id_filter]

        items: list[LearnerSessionListItem] = []
        for s in sessions:
            title, steps = self._get_draft_title_and_steps(s.lab_id)
            items.append(_list_item_from_session(s, title, steps))
        return items

    def build_snapshot(
        self,
        session_id: str,
        actor_user: str,
        is_admin: bool = False,
    ) -> LearnerSessionSnapshot:
        """
        Build a learner-safe snapshot for the given session.

        Raises:
            SnapshotNotFound: session does not exist.
            SnapshotAccessDenied: caller is not the owner and not an admin.
        """
        session = self._session_repo.get(session_id)
        if session is None:
            raise SnapshotNotFound(session_id)

        if session.student_username != actor_user and not is_admin:
            raise SnapshotAccessDenied(session_id)

        draft = self._draft_repo.get(session.lab_id)
        title = _sanitize(draft.title) if draft else "Unknown Lab"
        steps: list["Step"] = draft.steps if draft else []

        current_step_id, step_statuses = _build_step_statuses(session, steps)
        runtime_summary = _build_runtime_summary(session)
        action_availability = _build_action_availability(session)
        issues = _build_session_issues(session)

        return LearnerSessionSnapshot(
            session_id=session.session_id,
            lab_id=session.lab_id,
            title=title,
            session_state=session.lab_session_status.value,
            current_step_id=current_step_id,
            steps=step_statuses,
            runtime_summary=runtime_summary,
            action_availability=action_availability,
            issues=issues,
            checked_at=datetime.now(tz=timezone.utc).isoformat(),
        )
