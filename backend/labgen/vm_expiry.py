"""
VM Expiry Service — Contract §12 LAB_TIMEOUT trigger.

Identifies lab sessions that have exceeded their TTL (started_at + session_ttl_minutes)
and drives them through timeout → cleanup via LabSessionService.timeout_session().

Design constraints:
- No real K8s calls: all namespace/credential cleanup is delegated to LabSessionService.
- No new runtime states or audit event types.
- Fail-closed per session: an exception during one session's timeout never aborts others.
- Injectable clock: deterministic in tests without real wall-clock delays.
- dry_run=True reads and reports expired sessions without mutating state.
- Response fields never contain kubeconfig, namespace, credential, raw exception, or stack trace.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Optional

from pydantic import BaseModel, Field

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.models import LabSessionStatus

if TYPE_CHECKING:
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.lab_session_service import LabSessionService
    from backend.labgen.models import LabSessionState

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_MINUTES: int = 30

# Sessions in these states have already been handled — skip during expiry scan.
_SKIP_STATUSES: frozenset[LabSessionStatus] = frozenset({
    LabSessionStatus.LAB_CLOSED,
    LabSessionStatus.LAB_CLEANUP_FAILED,
    LabSessionStatus.LAB_START_FAILED,
    LabSessionStatus.LAB_TIMEOUT,    # already in timeout / cleanup path
    LabSessionStatus.LAB_COMPLETED,
    LabSessionStatus.LAB_ABORTED,
})


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class VMExpiryIssue(BaseModel):
    """Safe diagnostic record for a session that failed timeout handling.

    Fields never contain credentials, namespace paths, or raw exception text.
    """
    session_id: str
    vm_id: str
    failure_reason: str   # FailureReason stable machine code
    message: str          # human-readable, pre-defined safe string


class VMExpiryResult(BaseModel):
    expired_session_ids: list[str] = Field(default_factory=list)
    cleaned_session_ids: list[str] = Field(default_factory=list)
    failed_session_ids: list[str] = Field(default_factory=list)
    tainted_vm_ids: list[str] = Field(default_factory=list)
    issues: list[VMExpiryIssue] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class VMExpiryService:
    """Detects and processes expired lab sessions.

    A session is considered expired when:
      - started_at is not None (session became active at some point)
      - lab_session_status is not in _SKIP_STATUSES
      - started_at + session_ttl_minutes < now

    Expired sessions are passed to LabSessionService.timeout_session() which
    transitions them through LAB_TIMEOUT → cleanup → LAB_CLOSED or LAB_CLEANUP_FAILED.
    """

    def __init__(
        self,
        session_repo: "LabSessionRepository",
        session_service: "LabSessionService",
        session_ttl_minutes: int = DEFAULT_SESSION_TTL_MINUTES,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    ) -> None:
        self._sessions = session_repo
        self._svc = session_service
        self._ttl = session_ttl_minutes
        self._clock = clock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_expired_sessions(
        self,
        now: Optional[datetime] = None,
    ) -> list["LabSessionState"]:
        """Return sessions past TTL that have not yet been terminated.

        Pure read — no state mutations.
        """
        if now is None:
            now = self._clock()
        cutoff = now - timedelta(minutes=self._ttl)

        expired: list["LabSessionState"] = []
        for session in self._sessions.list_all():
            if session.lab_session_status in _SKIP_STATUSES:
                continue
            if session.started_at is None:
                continue
            started_at = session.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            if started_at < cutoff:
                expired.append(session)
        return expired

    def expire_sessions(
        self,
        dry_run: bool = False,
        limit: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> VMExpiryResult:
        """Expire sessions that have exceeded their TTL.

        Args:
            dry_run: When True, identifies expired sessions without mutating state.
            limit: Maximum number of sessions to process in this call.
            now: Override wall-clock time (test injection only; production passes None).

        Returns:
            VMExpiryResult with safe IDs and issue codes — no credentials or internal paths.
        """
        if now is None:
            now = self._clock()

        expired = self.find_expired_sessions(now=now)
        if limit is not None:
            expired = expired[:limit]

        result = VMExpiryResult(checked_at=now)

        for session in expired:
            result.expired_session_ids.append(session.session_id)

            if dry_run:
                continue

            try:
                updated = self._svc.timeout_session(session.session_id)
            except Exception:
                logger.error(
                    "VMExpiryService: failed to timeout session %s (vm_id=%s)",
                    session.session_id,
                    session.vm_id,
                    exc_info=False,
                )
                result.failed_session_ids.append(session.session_id)
                result.issues.append(VMExpiryIssue(
                    session_id=session.session_id,
                    vm_id=session.vm_id,
                    failure_reason=FailureReason.LAB_TIMEOUT.value,
                    message="Timeout handling failed — check server logs",
                ))
                continue

            if updated.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED:
                result.failed_session_ids.append(session.session_id)
                result.tainted_vm_ids.append(session.vm_id)
                result.issues.append(VMExpiryIssue(
                    session_id=session.session_id,
                    vm_id=session.vm_id,
                    failure_reason=updated.failure_reason or FailureReason.LAB_TIMEOUT.value,
                    message="Timeout cleanup failed — VM tainted, administrator review required",
                ))
            else:
                result.cleaned_session_ids.append(session.session_id)

        return result
