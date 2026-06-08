"""
Lab Session state machine — ports, service, and stubs.

Ports (abstract interfaces) decouple the service from real K8s and VM tracker.
Stubs ship for MVP skeleton; real adapters are wired in production.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from backend.labgen.models import (
    ConnectionState,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
)

if TYPE_CHECKING:
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.repository import LabDraftRepository


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

_TERMINAL_STATES: frozenset[LabSessionStatus] = frozenset({
    LabSessionStatus.LAB_CLOSED,
    LabSessionStatus.LAB_CLEANUP_FAILED,
    LabSessionStatus.LAB_START_FAILED,
})

_ACTIVE_STATES: frozenset[LabSessionStatus] = frozenset({
    LabSessionStatus.LAB_CREATED,
    LabSessionStatus.LAB_STARTING,
    LabSessionStatus.VM_PRECHECK_RUNNING,
    LabSessionStatus.IMAGE_CHECK_RUNNING,
    LabSessionStatus.NAMESPACE_CREATING,
    LabSessionStatus.NAMESPACE_READY,
    LabSessionStatus.LAB_ACTIVE,
    LabSessionStatus.CLEANUP_REQUESTED,
    LabSessionStatus.NAMESPACE_TERMINATING_WAIT,
    LabSessionStatus.CLEANUP_VERIFICATION_RUNNING,
})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PrecheckFailed(Exception):
    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__(f"Precheck failed: {failures}")


class SessionNotFound(Exception):
    pass


class SessionAlreadyTerminated(Exception):
    pass


# ---------------------------------------------------------------------------
# Ports (abstract interfaces)
# ---------------------------------------------------------------------------


class VMTrackerPort(ABC):
    @abstractmethod
    def vm_exists(self, vm_id: str) -> bool: ...

    @abstractmethod
    def is_vm_owned_by(self, vm_id: str, username: str) -> bool: ...

    @abstractmethod
    def mark_vm_tainted(self, vm_id: str) -> None: ...


class NamespaceInspector(ABC):
    @abstractmethod
    def request_namespace_cleanup(self, namespace: str) -> bool: ...


# ---------------------------------------------------------------------------
# Stubs (MVP skeleton — no real K8s / VM allocation)
# ---------------------------------------------------------------------------


class StubVMTracker(VMTrackerPort):
    """Always reports VM exists and is owned by any user. Tests only."""

    def vm_exists(self, vm_id: str) -> bool:
        return True

    def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
        return True

    def mark_vm_tainted(self, vm_id: str) -> None:
        pass


class RealVMTracker(VMTrackerPort):
    """Wraps the project's existing in-memory vm_tracker for real ownership checks."""

    def _parse_vm_id(self, vm_id: str) -> Optional[int]:
        try:
            return int(vm_id)
        except (ValueError, TypeError):
            return None

    def vm_exists(self, vm_id: str) -> bool:
        vid = self._parse_vm_id(vm_id)
        if vid is None:
            return False
        from backend.vm_tracker import vm_tracker as _vt
        return _vt.get_vm_owner(vid) is not None

    def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
        vid = self._parse_vm_id(vm_id)
        if vid is None:
            return False
        from backend.vm_tracker import vm_tracker as _vt
        return _vt.is_owner(vid, username)

    def mark_vm_tainted(self, vm_id: str) -> None:
        import logging as _log
        _log.getLogger(__name__).warning(
            "VM %s tainted after cleanup failure — manual review required", vm_id
        )


class StubNamespaceInspector(NamespaceInspector):
    """Always reports cleanup succeeded."""

    def request_namespace_cleanup(self, namespace: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# Precheck result
# ---------------------------------------------------------------------------


@dataclass
class PrecheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LabSessionService:
    def __init__(
        self,
        session_repo: "LabSessionRepository",
        draft_repo: "LabDraftRepository",
        vm_tracker: VMTrackerPort,
        ns_inspector: NamespaceInspector,
    ) -> None:
        self._session_repo = session_repo
        self._draft_repo = draft_repo
        self._vm_tracker = vm_tracker
        self._ns_inspector = ns_inspector

    # ------------------------------------------------------------------
    # Precheck — 6 local/stub checks, no real K8s calls
    # ------------------------------------------------------------------

    def run_precheck(
        self,
        lab_id: str,
        vm_id: str,
        student_username: str,
    ) -> PrecheckResult:
        failures: list[str] = []

        draft = self._draft_repo.get(lab_id)
        if draft is None:
            failures.append("precheck.draft_not_found")
        else:
            if draft.publish_status != PublishStatus.PUBLISHED:
                failures.append("precheck.draft_not_published")
            if draft.cleanup is None:
                failures.append("precheck.cleanup_not_declared")

        if not self._vm_tracker.vm_exists(vm_id):
            failures.append("precheck.vm_not_found")
        elif not self._vm_tracker.is_vm_owned_by(vm_id, student_username):
            failures.append("precheck.vm_not_owned_by_student")

        existing = self._session_repo.list_by_student(student_username)
        if any(
            s.lab_id == lab_id and s.lab_session_status in _ACTIVE_STATES
            for s in existing
        ):
            failures.append("precheck.session_already_active")

        return PrecheckResult(passed=len(failures) == 0, failures=failures)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create_session(
        self,
        lab_id: str,
        vm_id: str,
        student_username: str,
    ) -> LabSessionState:
        result = self.run_precheck(lab_id, vm_id, student_username)
        if not result.passed:
            raise PrecheckFailed(result.failures)

        session = LabSessionState(
            lab_id=lab_id,
            vm_id=vm_id,
            student_username=student_username,
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            connection_state=ConnectionState.CONNECTED,
            started_at=datetime.now(tz=timezone.utc),
        )
        # Derive namespace from full session_id — globally unique, no collision possible
        session.namespace = f"lab-{session.session_id}"

        return self._session_repo.create(session)

    def complete_session(self, session_id: str) -> LabSessionState:
        session = self._require_session(session_id)
        if session.lab_session_status in _TERMINAL_STATES:
            raise SessionAlreadyTerminated(session_id)

        session.lab_session_status = LabSessionStatus.LAB_COMPLETED
        session.connection_state = ConnectionState.DISCONNECTED
        session.ended_at = datetime.now(tz=timezone.utc)
        session = self._session_repo.update(session)

        return self._do_cleanup(session)

    def abort_session(self, session_id: str) -> LabSessionState:
        session = self._require_session(session_id)
        if session.lab_session_status in _TERMINAL_STATES:
            raise SessionAlreadyTerminated(session_id)

        session.lab_session_status = LabSessionStatus.LAB_ABORTED
        session.connection_state = ConnectionState.DISCONNECTED
        session.ended_at = datetime.now(tz=timezone.utc)
        session = self._session_repo.update(session)

        return self._do_cleanup(session)

    def run_cleanup(self, session_id: str) -> LabSessionState:
        session = self._require_session(session_id)
        if session.lab_session_status == LabSessionStatus.LAB_CLOSED:
            return session  # already clean, idempotent
        return self._do_cleanup(session)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_cleanup(self, session: LabSessionState) -> LabSessionState:
        if session.namespace is None:
            session.lab_session_status = LabSessionStatus.LAB_CLOSED
            return self._session_repo.update(session)

        try:
            success = self._ns_inspector.request_namespace_cleanup(session.namespace)
        except Exception:
            success = False

        if success:
            session.lab_session_status = LabSessionStatus.LAB_CLOSED
        else:
            session.lab_session_status = LabSessionStatus.LAB_CLEANUP_FAILED
            self._vm_tracker.mark_vm_tainted(session.vm_id)

        return self._session_repo.update(session)

    def _require_session(self, session_id: str) -> LabSessionState:
        session = self._session_repo.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session
