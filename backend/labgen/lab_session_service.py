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

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.models import (
    ConnectionState,
    ImageResolutionResult,
    ImageStatus,
    LabDomainType,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeAuditEventType,
    SessionType,
)
from backend.labgen.namespace_lifecycle import (
    NamespaceLifecyclePort,
    StubNamespaceLifecycleAdapter,
)
from backend.labgen.runtime_audit import RuntimeAuditService

if TYPE_CHECKING:
    from backend.labgen.article_models import ArticleDraftLabContract
    from backend.labgen.image_resolver import ImageResolver
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.models import LabDraft
    from backend.labgen.repository import LabDraftRepository
    from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionResult
    from backend.labgen.runtime_precheck import RuntimePrecheckService
    from backend.labgen.verifier_credentials import VerifierCredentialReclaimer


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

_TERMINAL_STATES: frozenset[LabSessionStatus] = frozenset({
    LabSessionStatus.LAB_CLOSED,
    LabSessionStatus.LAB_CLEANUP_FAILED,
    LabSessionStatus.LAB_START_FAILED,
})

# States that have already ended (either terminal or completed lifecycle) — timeout is a no-op.
_ALREADY_ENDED_STATES: frozenset[LabSessionStatus] = frozenset({
    LabSessionStatus.LAB_CLOSED,
    LabSessionStatus.LAB_CLEANUP_FAILED,
    LabSessionStatus.LAB_START_FAILED,
    LabSessionStatus.LAB_TIMEOUT,
    LabSessionStatus.LAB_COMPLETED,
    LabSessionStatus.LAB_ABORTED,
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


class LabNotReadyToComplete(Exception):
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

    @abstractmethod
    def is_vm_tainted(self, vm_id: str) -> bool: ...


# ---------------------------------------------------------------------------
# Stubs (MVP skeleton — no real K8s / VM allocation)
# ---------------------------------------------------------------------------


class StubVMTracker(VMTrackerPort):
    """Always reports VM exists and is owned by any user. Tests only."""

    def __init__(self) -> None:
        self._tainted: set[str] = set()

    def vm_exists(self, vm_id: str) -> bool:
        return True

    def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
        return True

    def mark_vm_tainted(self, vm_id: str) -> None:
        self._tainted.add(vm_id)

    def is_vm_tainted(self, vm_id: str) -> bool:
        return vm_id in self._tainted


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
        from pathlib import Path as _Path
        from backend.storage_utils import safe_update_json as _upd
        _log.getLogger(__name__).warning(
            "VM %s tainted after cleanup failure — manual review required", vm_id
        )
        _tainted_file = _Path(__file__).parent.parent.parent / "data" / "tainted_vms.json"

        def _add(data: dict) -> dict:
            data[vm_id] = True
            return data

        _upd(_tainted_file, _add)

    def is_vm_tainted(self, vm_id: str) -> bool:
        from pathlib import Path as _Path
        from backend.storage_utils import safe_read_json as _read
        _tainted_file = _Path(__file__).parent.parent.parent / "data" / "tainted_vms.json"
        data = _read(_tainted_file, default={})
        return bool(data.get(vm_id, False))


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
        audit_svc: Optional[RuntimeAuditService] = None,
        adapter_selection: Optional["RuntimeAdapterSelectionResult"] = None,
        credential_reclaimer: Optional["VerifierCredentialReclaimer"] = None,
        runtime_precheck: Optional["RuntimePrecheckService"] = None,
        ns_delete_poll_interval: float = 1.0,
        ns_delete_max_retries: int = 5,
        credential_reclaim_exempt_vm_ids: frozenset = frozenset(),
    ) -> None:
        self._session_repo = session_repo
        self._draft_repo = draft_repo
        self._vm_tracker = vm_tracker
        self._ns_lifecycle = ns_lifecycle
        self._image_resolver = image_resolver
        self._audit_svc = audit_svc
        self._adapter_selection = adapter_selection
        self._credential_reclaimer = credential_reclaimer
        self._runtime_precheck = runtime_precheck
        self._ns_delete_poll_interval = ns_delete_poll_interval
        self._ns_delete_max_retries = ns_delete_max_retries
        self._credential_reclaim_exempt_vm_ids = credential_reclaim_exempt_vm_ids

    def _audit(
        self,
        session_id: str,
        event_type: RuntimeAuditEventType,
        failure_reason: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        if self._audit_svc is not None:
            self._audit_svc.record(session_id, event_type, failure_reason=failure_reason, metadata=metadata)

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
            failures.append(FailureReason.PRECHECK_DRAFT_NOT_FOUND.value)
        else:
            if draft.publish_status != PublishStatus.PUBLISHED:
                failures.append(FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value)
            if draft.target_domain == LabDomainType.LINUX:
                failures.append(FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value)
            elif draft.cleanup is None:
                failures.append(FailureReason.PRECHECK_CLEANUP_NOT_DECLARED.value)

        if not self._vm_tracker.vm_exists(vm_id):
            failures.append(FailureReason.PRECHECK_VM_NOT_FOUND.value)
        elif not self._vm_tracker.is_vm_owned_by(vm_id, student_username):
            failures.append(FailureReason.PRECHECK_VM_NOT_OWNED_BY_STUDENT.value)
        elif self._vm_tracker.is_vm_tainted(vm_id):
            failures.append(FailureReason.PRECHECK_VM_TAINTED.value)

        existing = self._session_repo.list_by_student(student_username)
        if any(
            s.lab_id == lab_id
            and s.lab_session_status in _ACTIVE_STATES
            and s.session_type != SessionType.INTERNAL_REHEARSAL
            for s in existing
        ):
            failures.append(FailureReason.PRECHECK_SESSION_ALREADY_ACTIVE.value)

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
        # Runtime adapter safety guard — must run before precheck or any resource creation.
        # Fires when ANY blocking adapter-selection issue is present (invalid mode, invalid
        # adapter kind, or production+stub/k8s-without-kubeconfig).  This covers typos such as
        # LABGEN_RUNTIME_MODE=prod which produce INVALID_RUNTIME_MODE (blocking) but whose
        # fallback runtime_mode value is DEV — not caught by a production-only check.
        if self._adapter_selection is not None:
            if any(i.severity == "blocking" for i in self._adapter_selection.issues):
                session = LabSessionState(
                    lab_id=lab_id,
                    vm_id=vm_id,
                    student_username=student_username,
                    lab_session_status=LabSessionStatus.LAB_START_FAILED,
                    failure_reason=FailureReason.ADAPTER_UNSAFE_IN_PRODUCTION.value,
                )
                session = self._session_repo.create(session)
                self._audit(
                    session.session_id,
                    RuntimeAuditEventType.LAB_START_FAILED,
                    failure_reason=FailureReason.ADAPTER_UNSAFE_IN_PRODUCTION.value,
                )
                return session

        result = self.run_precheck(lab_id, vm_id, student_username)
        if not result.passed:
            raise PrecheckFailed(result.failures)

        # Contract §11 conditions 4 and 6 — runtime state checks that require
        # namespace lifecycle and session history.  Must run before any K8s
        # resource creation.  Failure creates a LAB_START_FAILED session and
        # emits a safe audit event (no kubeconfig / credential / stack trace).
        if self._runtime_precheck is not None:
            rp_result = self._runtime_precheck.check(vm_id, student_username)
            if not rp_result.passed:
                from backend.labgen.failure_reasons import FailureReason as _FR
                top_reason = (
                    rp_result.issues[0].code
                    if len(rp_result.issues) == 1
                    else _FR.RUNTIME_PRECHECK_FAILED.value
                )
                session = LabSessionState(
                    lab_id=lab_id,
                    vm_id=vm_id,
                    student_username=student_username,
                    lab_session_status=LabSessionStatus.LAB_START_FAILED,
                    failure_reason=top_reason,
                )
                session = self._session_repo.create(session)
                self._audit(
                    session.session_id,
                    RuntimeAuditEventType.LAB_START_FAILED,
                    failure_reason=top_reason,
                    metadata={
                        "blocked_conditions": [
                            c.value for c in rp_result.blocked_conditions
                        ],
                        "issue_codes": [i.code for i in rp_result.issues],
                    },
                )
                return session

        return self._do_create_session(
            lab_id=lab_id,
            vm_id=vm_id,
            username=student_username,
            session_type=SessionType.LEARNER,
        )

    def run_rehearsal_precheck(
        self,
        lab_id: str,
        vm_id: str,
        admin_username: str,
        article_draft_id: Optional[str] = None,
    ) -> PrecheckResult:
        """Precheck for admin-only internal rehearsal sessions.

        Differences from run_precheck():
        - Does NOT require publish_status=PUBLISHED (DRAFT is expected)
        - DOES require source_article_id to be set (confirms article-generated origin;
          source_article_id is only set by convert_to_lab_draft which requires an
          approved article draft)
        - Normal cleanup / VM / duplicate-session checks still apply
        """

        failures: list[str] = []

        draft = self._draft_repo.get(lab_id)
        if draft is None:
            failures.append(FailureReason.REHEARSAL_DRAFT_NOT_FOUND.value)
        else:
            if not draft.source_article_id:
                failures.append(FailureReason.REHEARSAL_DRAFT_NOT_ARTICLE_GENERATED.value)
            if draft.cleanup is None:
                failures.append(FailureReason.REHEARSAL_CLEANUP_NOT_DECLARED.value)

        if not self._vm_tracker.vm_exists(vm_id):
            failures.append(FailureReason.REHEARSAL_VM_NOT_FOUND.value)
        elif not self._vm_tracker.is_vm_owned_by(vm_id, admin_username):
            failures.append(FailureReason.REHEARSAL_VM_NOT_OWNED.value)
        elif self._vm_tracker.is_vm_tainted(vm_id):
            failures.append(FailureReason.REHEARSAL_VM_TAINTED.value)

        existing = self._session_repo.list_by_student(admin_username)
        if any(
            s.lab_id == lab_id and s.lab_session_status in _ACTIVE_STATES
            for s in existing
        ):
            failures.append(FailureReason.REHEARSAL_SESSION_ALREADY_ACTIVE.value)

        return PrecheckResult(passed=len(failures) == 0, failures=failures)

    def create_rehearsal_session(
        self,
        lab_id: str,
        vm_id: str,
        admin_username: str,
        article_draft_id: Optional[str] = None,
    ) -> LabSessionState:
        """Create an admin-only internal rehearsal session against a DRAFT lab.

        Safety guarantees:
        - Does NOT require publish_status=PUBLISHED
        - Does NOT add the lab to the learner catalog
        - Session is tagged session_type=INTERNAL_REHEARSAL
        - Normal cleanup / namespace / credential lifecycle still applies
        - Only callable through the /internal/rehearsal-sessions route (X-Admin-Token)
        """
        if self._adapter_selection is not None:
            if any(i.severity == "blocking" for i in self._adapter_selection.issues):
                session = LabSessionState(
                    lab_id=lab_id,
                    vm_id=vm_id,
                    student_username=admin_username,
                    lab_session_status=LabSessionStatus.LAB_START_FAILED,
                    failure_reason=FailureReason.ADAPTER_UNSAFE_IN_PRODUCTION.value,
                    session_type=SessionType.INTERNAL_REHEARSAL,
                    article_draft_id=article_draft_id,
                )
                session = self._session_repo.create(session)
                self._audit(
                    session.session_id,
                    RuntimeAuditEventType.LAB_START_FAILED,
                    failure_reason=FailureReason.ADAPTER_UNSAFE_IN_PRODUCTION.value,
                )
                return session

        result = self.run_rehearsal_precheck(lab_id, vm_id, admin_username, article_draft_id)
        if not result.passed:
            raise PrecheckFailed(result.failures)

        return self._do_create_session(
            lab_id=lab_id,
            vm_id=vm_id,
            username=admin_username,
            session_type=SessionType.INTERNAL_REHEARSAL,
            article_draft_id=article_draft_id,
        )

    def _do_create_session(
        self,
        lab_id: str,
        vm_id: str,
        username: str,
        session_type: SessionType,
        article_draft_id: Optional[str] = None,
    ) -> LabSessionState:
        """Shared post-precheck session creation: image check → ns create → rb create → active."""
        # Safe: precheck already verified draft exists
        draft = self._draft_repo.get(lab_id)

        passed, failure_reason, updated_images, any_rechecked = self._run_image_check(draft)

        if not passed:
            session = LabSessionState(
                lab_id=lab_id,
                vm_id=vm_id,
                student_username=username,
                lab_session_status=LabSessionStatus.LAB_START_FAILED,
                failure_reason=failure_reason,
                session_type=session_type,
                article_draft_id=article_draft_id,
            )
            session = self._session_repo.create(session)
            self._audit(session.session_id, RuntimeAuditEventType.LAB_START_FAILED, failure_reason=failure_reason)
            return session

        if any_rechecked and draft is not None:
            self._draft_repo.update(draft.model_copy(update={"image_resolution": updated_images}))

        session = LabSessionState(
            lab_id=lab_id,
            vm_id=vm_id,
            student_username=username,
            lab_session_status=LabSessionStatus.NAMESPACE_CREATING,
            session_type=session_type,
            article_draft_id=article_draft_id,
        )
        session.namespace = f"lab-{session.session_id}"

        try:
            create_ok = self._ns_lifecycle.create_namespace(session.namespace)
        except Exception:
            create_ok = False

        if not create_ok:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = FailureReason.NAMESPACE_CREATE_FAILED.value
            session = self._session_repo.create(session)
            self._audit(session.session_id, RuntimeAuditEventType.LAB_START_FAILED, failure_reason=FailureReason.NAMESPACE_CREATE_FAILED.value)
            return session

        try:
            exists = self._ns_lifecycle.namespace_exists(session.namespace)
        except Exception:
            exists = False

        if not exists:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = FailureReason.NAMESPACE_CREATE_FAILED.value
            session = self._session_repo.create(session)
            self._audit(session.session_id, RuntimeAuditEventType.LAB_START_FAILED, failure_reason=FailureReason.NAMESPACE_CREATE_FAILED.value)
            return session

        session.lab_session_status = LabSessionStatus.VERIFIER_BINDING_CREATING
        try:
            binding_ok = self._ns_lifecycle.ensure_verifier_rolebinding(session.namespace)
        except Exception:
            binding_ok = False

        if not binding_ok:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = FailureReason.VERIFIER_ROLEBINDING_CREATE_FAILED.value
            session = self._session_repo.create(session)
            self._audit(session.session_id, RuntimeAuditEventType.LAB_START_FAILED, failure_reason=FailureReason.VERIFIER_ROLEBINDING_CREATE_FAILED.value)
            return session

        try:
            binding_exists = self._ns_lifecycle.verifier_rolebinding_exists(session.namespace)
        except Exception:
            binding_exists = False

        if not binding_exists:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = FailureReason.VERIFIER_ROLEBINDING_VERIFY_FAILED.value
            session = self._session_repo.create(session)
            self._audit(session.session_id, RuntimeAuditEventType.LAB_START_FAILED, failure_reason=FailureReason.VERIFIER_ROLEBINDING_VERIFY_FAILED.value)
            return session

        session.lab_session_status = LabSessionStatus.LAB_ACTIVE
        session.connection_state = ConnectionState.CONNECTED
        session.started_at = datetime.now(tz=timezone.utc)
        session = self._session_repo.create(session)
        self._audit(session.session_id, RuntimeAuditEventType.LAB_START_SUCCESS)
        return session

    def complete_session(self, session_id: str) -> LabSessionState:
        session = self._require_session(session_id)
        if session.lab_session_status in _TERMINAL_STATES:
            raise SessionAlreadyTerminated(session_id)
        if not session.ready_to_complete:
            raise LabNotReadyToComplete(session_id)

        session.lab_session_status = LabSessionStatus.LAB_COMPLETED
        session.connection_state = ConnectionState.DISCONNECTED
        session.ended_at = datetime.now(tz=timezone.utc)
        session = self._session_repo.update(session)
        self._audit(session.session_id, RuntimeAuditEventType.LAB_COMPLETE)

        return self._do_cleanup(session)

    def abort_session(self, session_id: str) -> LabSessionState:
        session = self._require_session(session_id)
        if session.lab_session_status in _TERMINAL_STATES:
            raise SessionAlreadyTerminated(session_id)

        session.lab_session_status = LabSessionStatus.LAB_ABORTED
        session.connection_state = ConnectionState.DISCONNECTED
        session.ended_at = datetime.now(tz=timezone.utc)
        session = self._session_repo.update(session)
        self._audit(session.session_id, RuntimeAuditEventType.LAB_ABORT)

        return self._do_cleanup(session)

    def run_cleanup(self, session_id: str) -> LabSessionState:
        session = self._require_session(session_id)
        if session.lab_session_status in _TERMINAL_STATES:
            return session  # idempotent — already closed or permanently failed
        return self._do_cleanup(session)

    def timeout_session(self, session_id: str) -> LabSessionState:
        """Apply LAB_TIMEOUT to an active session then run cleanup.

        Idempotent: returns session unchanged if it has already ended.
        Does NOT emit a new audit event for the timeout transition itself
        (no matching RuntimeAuditEventType — timeout is expressed via
        failure_reason on the session and via CLEANUP_FAILED/VM_TAINTED
        audit events if cleanup fails).
        """
        session = self._require_session(session_id)
        if session.lab_session_status in _ALREADY_ENDED_STATES:
            return session

        session.lab_session_status = LabSessionStatus.LAB_TIMEOUT
        session.failure_reason = FailureReason.LAB_TIMEOUT.value
        session.connection_state = ConnectionState.DISCONNECTED
        session.ended_at = datetime.now(tz=timezone.utc)
        session = self._session_repo.update(session)
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

        - image_status != RESOLVED  → (False, FailureReason.IMAGE_UNRESOLVED.value, ...)
        - existence_check_passed is False → (False, FailureReason.IMAGE_UNAVAILABLE.value, ...)
        - recheck performed          → any_rechecked=True so caller can persist fresh results
        """
        if draft is None or not draft.image_resolution:
            return True, None, [], False

        updated_images: list[ImageResolutionResult] = []
        any_rechecked = False

        for img in draft.image_resolution:
            if img.image_status != ImageStatus.RESOLVED:
                return False, FailureReason.IMAGE_UNRESOLVED.value, updated_images, False
            if self._image_resolver.needs_recheck(img):
                img = self._image_resolver.check_registry_existence(img)
                any_rechecked = True
            if img.existence_check_passed is False:
                return False, FailureReason.IMAGE_UNAVAILABLE.value, updated_images, False
            updated_images.append(img)

        return True, None, updated_images, any_rechecked

    def _do_cleanup(self, session: LabSessionState) -> LabSessionState:
        # Phase 1: namespace deletion (skipped when session has no namespace)
        namespace_ok = True
        namespace_failure_reason: Optional[str] = None
        if session.namespace is not None:
            deleted = False
            try:
                if self._ns_lifecycle.delete_namespace(session.namespace):
                    # K3s namespace deletion is async — retry until gone or retries exhausted
                    for attempt in range(self._ns_delete_max_retries):
                        if self._ns_lifecycle.is_namespace_deleted(session.namespace):
                            deleted = True
                            break
                        if attempt < self._ns_delete_max_retries - 1:
                            import time
                            time.sleep(self._ns_delete_poll_interval)
            except Exception:
                deleted = False
            if not deleted:
                namespace_ok = False
                namespace_failure_reason = FailureReason.NAMESPACE_CLEANUP_FAILED.value

        # Phase 2: verifier credential reclaim (skipped when no reclaimer injected,
        # or when the VM is a shared/persistent VM reused across many sessions —
        # reclaiming after every session would wipe credentials the next session
        # on the same VM needs).
        cred_ok = True
        cred_failure_reason: Optional[str] = None
        if (
            self._credential_reclaimer is not None
            and session.vm_id not in self._credential_reclaim_exempt_vm_ids
        ):
            cred_result = self._credential_reclaimer.reclaim_for_vm(session.vm_id)
            cred_ok = cred_result.success
            cred_failure_reason = cred_result.failure_reason

        if namespace_ok and cred_ok:
            session.lab_session_status = LabSessionStatus.LAB_CLOSED
            session.cleanup_verified = True
            session = self._session_repo.update(session)
            self._audit(session.session_id, RuntimeAuditEventType.CLEANUP_SUCCESS)
            # Mark the source draft as rehearsal_completed only when a fully-completed
            # INTERNAL_REHEARSAL session cleans up successfully. Aborted/timed-out
            # rehearsal sessions (ready_to_complete=False) must not unblock the gate.
            if (
                session.session_type == SessionType.INTERNAL_REHEARSAL
                and session.ready_to_complete
            ):
                draft = self._draft_repo.get(session.lab_id)
                if draft is not None and not draft.rehearsal_completed:
                    self._draft_repo.update(draft.model_copy(update={"rehearsal_completed": True}))
            return session

        # Namespace failure takes precedence over credential failure in the failure_reason
        # recorded on the session; audit metadata carries the specific phase that failed.
        failure_reason = (
            namespace_failure_reason
            or cred_failure_reason
            or FailureReason.NAMESPACE_CLEANUP_FAILED.value
        )
        audit_metadata: Optional[dict] = None
        if not cred_ok and namespace_ok:
            # Credential-only failure: include safe cleanup phase for ops visibility.
            audit_metadata = {"cleanup_phase": "verifier_credential_reclaim"}

        session.lab_session_status = LabSessionStatus.LAB_CLEANUP_FAILED
        session.failure_reason = failure_reason
        session.cleanup_verified = False
        self._vm_tracker.mark_vm_tainted(session.vm_id)
        session = self._session_repo.update(session)
        self._audit(
            session.session_id,
            RuntimeAuditEventType.CLEANUP_FAILED,
            failure_reason=failure_reason,
            metadata=audit_metadata,
        )
        self._audit(session.session_id, RuntimeAuditEventType.VM_TAINTED, metadata={"vm_id": session.vm_id})
        return session

    def _require_session(self, session_id: str) -> LabSessionState:
        session = self._session_repo.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session
