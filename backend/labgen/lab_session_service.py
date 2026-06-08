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
    ImageResolutionResult,
    ImageStatus,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
)
from backend.labgen.namespace_lifecycle import (
    NamespaceLifecyclePort,
    StubNamespaceLifecycleAdapter,
)

if TYPE_CHECKING:
    from backend.labgen.image_resolver import ImageResolver
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.models import LabDraft
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
    LabSessionStatus.VERIFIER_BINDING_CREATING,
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
# VMTracker port
# ---------------------------------------------------------------------------


class VMTrackerPort(ABC):
    @abstractmethod
    def vm_exists(self, vm_id: str) -> bool: ...

    @abstractmethod
    def is_vm_owned_by(self, vm_id: str, username: str) -> bool: ...

    @abstractmethod
    def mark_vm_tainted(self, vm_id: str) -> None: ...


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
        ns_lifecycle: NamespaceLifecyclePort,
        image_resolver: "ImageResolver",
    ) -> None:
        self._session_repo = session_repo
        self._draft_repo = draft_repo
        self._vm_tracker = vm_tracker
        self._ns_lifecycle = ns_lifecycle
        self._image_resolver = image_resolver

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

        # Safe: precheck already verified draft exists
        draft = self._draft_repo.get(lab_id)

        passed, failure_reason, updated_images, any_rechecked = self._run_image_check(draft)

        if not passed:
            session = LabSessionState(
                lab_id=lab_id,
                vm_id=vm_id,
                student_username=student_username,
                lab_session_status=LabSessionStatus.LAB_START_FAILED,
                failure_reason=failure_reason,
            )
            return self._session_repo.create(session)

        if any_rechecked and draft is not None:
            self._draft_repo.update(draft.model_copy(update={"image_resolution": updated_images}))

        # Allocate session_id early so namespace is derived from it
        session = LabSessionState(
            lab_id=lab_id,
            vm_id=vm_id,
            student_username=student_username,
            lab_session_status=LabSessionStatus.NAMESPACE_CREATING,
        )
        session.namespace = f"lab-{session.session_id}"

        # NAMESPACE_CREATING: attempt to create, then confirm existence
        try:
            create_ok = self._ns_lifecycle.create_namespace(session.namespace)
        except Exception:
            create_ok = False

        if not create_ok:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = "namespace_create_failed"
            return self._session_repo.create(session)

        try:
            exists = self._ns_lifecycle.namespace_exists(session.namespace)
        except Exception:
            exists = False

        if not exists:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = "namespace_create_failed"
            return self._session_repo.create(session)

        # VERIFIER_BINDING_CREATING: create RoleBinding, then verify existence
        session.lab_session_status = LabSessionStatus.VERIFIER_BINDING_CREATING
        try:
            binding_ok = self._ns_lifecycle.ensure_verifier_rolebinding(session.namespace)
        except Exception:
            binding_ok = False

        if not binding_ok:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = "verifier_rolebinding_create_failed"
            return self._session_repo.create(session)

        try:
            binding_exists = self._ns_lifecycle.verifier_rolebinding_exists(session.namespace)
        except Exception:
            binding_exists = False

        if not binding_exists:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = "verifier_rolebinding_verify_failed"
            return self._session_repo.create(session)

        session.lab_session_status = LabSessionStatus.LAB_ACTIVE
        session.connection_state = ConnectionState.CONNECTED
        session.started_at = datetime.now(tz=timezone.utc)
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

    def _run_image_check(
        self,
        draft: Optional["LabDraft"],
    ) -> "tuple[bool, Optional[str], list[ImageResolutionResult], bool]":
        """
        Returns (all_passed, failure_reason, updated_images, any_rechecked).

        - image_status != RESOLVED  → (False, "image_unresolved", ...)
        - existence_check_passed is False → (False, "image_unavailable", ...)
        - recheck performed          → any_rechecked=True so caller can persist fresh results
        """
        if draft is None or not draft.image_resolution:
            return True, None, [], False

        updated_images: list[ImageResolutionResult] = []
        any_rechecked = False

        for img in draft.image_resolution:
            if img.image_status != ImageStatus.RESOLVED:
                return False, "image_unresolved", updated_images, False
            if self._image_resolver.needs_recheck(img):
                img = self._image_resolver.check_registry_existence(img)
                any_rechecked = True
            if img.existence_check_passed is False:
                return False, "image_unavailable", updated_images, False
            updated_images.append(img)

        return True, None, updated_images, any_rechecked

    def _do_cleanup(self, session: LabSessionState) -> LabSessionState:
        if session.namespace is None:
            session.lab_session_status = LabSessionStatus.LAB_CLOSED
            return self._session_repo.update(session)

        # NAMESPACE_TERMINATING_WAIT: delete namespace, then verify deletion
        deleted = False
        try:
            if self._ns_lifecycle.delete_namespace(session.namespace):
                deleted = self._ns_lifecycle.is_namespace_deleted(session.namespace)
        except Exception:
            deleted = False

        if deleted:
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
