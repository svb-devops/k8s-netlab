"""
Runtime Audit Log tests.

Validates append-only audit events for lab lifecycle (start, step check,
complete, abort, cleanup, VM tainted) and the GET audit-events route.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.lab_session_service import (
    LabSessionService,
    StubVMTracker,
    VMTrackerPort,
)
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    ImageResolutionResult,
    ImageStatus,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeAuditEvent,
    RuntimeAuditEventType,
    RuntimeRequirements,
    Step,
    VerifyResult,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.namespace_lifecycle import (
    NamespaceLifecyclePort,
    StubNamespaceLifecycleAdapter,
)
from backend.labgen.runtime_audit import RuntimeAuditRepository, RuntimeAuditService
from backend.labgen.step_progression_service import StepProgressionService

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _MemAuditRepo:
    def __init__(self) -> None:
        self._events: list[RuntimeAuditEvent] = []

    def append(self, event: RuntimeAuditEvent) -> RuntimeAuditEvent:
        self._events.append(event)
        return event

    def list_by_session(self, session_id: str) -> list[RuntimeAuditEvent]:
        return [e for e in self._events if e.session_id == session_id]


class _RaisingAuditRepo:
    def append(self, event: RuntimeAuditEvent) -> RuntimeAuditEvent:
        raise OSError("disk full")

    def list_by_session(self, session_id: str) -> list[RuntimeAuditEvent]:
        return []


class _MemSessionRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabSessionState] = {}

    def create(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def get(self, sid: str) -> Optional[LabSessionState]:
        return self._store.get(sid)

    def update(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]


class _MemDraftRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft


class _StubImageResolver:
    def needs_recheck(self, img: ImageResolutionResult) -> bool:
        return False

    def check_registry_existence(self, img: ImageResolutionResult) -> ImageResolutionResult:
        return img


class _FailingCreateAdapter(NamespaceLifecyclePort):
    def create_namespace(self, ns: str) -> bool:
        return False

    def namespace_exists(self, ns: str) -> bool:
        return False

    def delete_namespace(self, ns: str) -> bool:
        return True

    def is_namespace_deleted(self, ns: str) -> bool:
        return True

    def ensure_verifier_rolebinding(self, ns: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, ns: str) -> bool:
        return True


class _FailingDeleteAdapter(NamespaceLifecyclePort):
    def create_namespace(self, ns: str) -> bool:
        return True

    def namespace_exists(self, ns: str) -> bool:
        return True

    def delete_namespace(self, ns: str) -> bool:
        return False

    def is_namespace_deleted(self, ns: str) -> bool:
        return False

    def ensure_verifier_rolebinding(self, ns: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, ns: str) -> bool:
        return True


def _make_published_draft(lab_id: str = "lab-1", image_resolution: Optional[list] = None) -> LabDraft:
    return LabDraft(
        lab_id=lab_id,
        source_article_id="art-1",
        title="Audit Test Lab",
        description="desc",
        estimated_duration_minutes=20,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="w", do="d", observe="o",
            explain=ExplainField(concept="c", observation="o"),
        )],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.PUBLISHED,
        image_resolution=image_resolution or [],
    )


def _make_session(**kw) -> LabSessionState:
    defaults = dict(
        lab_id="lab-1",
        vm_id="vm-500",
        student_username="student1",
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
        namespace="lab-test-ns",
    )
    defaults.update(kw)
    return LabSessionState(**defaults)


def _make_svc(
    session_repo: _MemSessionRepo,
    draft_repo: Optional[_MemDraftRepo] = None,
    ns_lifecycle: Optional[NamespaceLifecyclePort] = None,
    vm_tracker: Optional[VMTrackerPort] = None,
    audit_repo: Optional[_MemAuditRepo] = None,
) -> LabSessionService:
    dr = draft_repo or _MemDraftRepo()
    audit_svc = RuntimeAuditService(repo=audit_repo) if audit_repo is not None else None
    return LabSessionService(
        session_repo=session_repo,
        draft_repo=dr,
        vm_tracker=vm_tracker or StubVMTracker(),
        ns_lifecycle=ns_lifecycle or StubNamespaceLifecycleAdapter(),
        image_resolver=_StubImageResolver(),
        audit_svc=audit_svc,
    )


# ---------------------------------------------------------------------------
# Tests: RuntimeAuditRepository
# ---------------------------------------------------------------------------


class TestRuntimeAuditRepository:
    def test_append_creates_session_entry(self, tmp_path: Path) -> None:
        repo = RuntimeAuditRepository(path=tmp_path / "audit.json")
        event = RuntimeAuditEvent(session_id="s1", event_type=RuntimeAuditEventType.LAB_START_SUCCESS)
        repo.append(event)
        events = repo.list_by_session("s1")
        assert len(events) == 1
        assert events[0].event_type == RuntimeAuditEventType.LAB_START_SUCCESS

    def test_append_multiple_events_in_order(self, tmp_path: Path) -> None:
        repo = RuntimeAuditRepository(path=tmp_path / "audit.json")
        for et in [RuntimeAuditEventType.LAB_START_SUCCESS, RuntimeAuditEventType.LAB_COMPLETE, RuntimeAuditEventType.CLEANUP_SUCCESS]:
            repo.append(RuntimeAuditEvent(session_id="s1", event_type=et))
        events = repo.list_by_session("s1")
        assert [e.event_type for e in events] == [
            RuntimeAuditEventType.LAB_START_SUCCESS,
            RuntimeAuditEventType.LAB_COMPLETE,
            RuntimeAuditEventType.CLEANUP_SUCCESS,
        ]

    def test_list_by_session_returns_empty_for_unknown(self, tmp_path: Path) -> None:
        repo = RuntimeAuditRepository(path=tmp_path / "audit.json")
        assert repo.list_by_session("nonexistent") == []

    def test_multiple_sessions_are_independent(self, tmp_path: Path) -> None:
        repo = RuntimeAuditRepository(path=tmp_path / "audit.json")
        repo.append(RuntimeAuditEvent(session_id="s1", event_type=RuntimeAuditEventType.LAB_START_SUCCESS))
        repo.append(RuntimeAuditEvent(session_id="s2", event_type=RuntimeAuditEventType.LAB_ABORT))
        assert len(repo.list_by_session("s1")) == 1
        assert repo.list_by_session("s1")[0].event_type == RuntimeAuditEventType.LAB_START_SUCCESS
        assert len(repo.list_by_session("s2")) == 1
        assert repo.list_by_session("s2")[0].event_type == RuntimeAuditEventType.LAB_ABORT


# ---------------------------------------------------------------------------
# Tests: RuntimeAuditService
# ---------------------------------------------------------------------------


class TestRuntimeAuditService:
    def test_record_stores_event(self) -> None:
        repo = _MemAuditRepo()
        svc = RuntimeAuditService(repo=repo)
        svc.record("sid", RuntimeAuditEventType.LAB_START_SUCCESS)
        assert len(repo._events) == 1
        assert repo._events[0].session_id == "sid"
        assert repo._events[0].event_type == RuntimeAuditEventType.LAB_START_SUCCESS

    def test_record_with_failure_reason_and_metadata(self) -> None:
        repo = _MemAuditRepo()
        svc = RuntimeAuditService(repo=repo)
        svc.record("sid", RuntimeAuditEventType.LAB_START_FAILED,
                   failure_reason=FailureReason.IMAGE_UNRESOLVED.value,
                   metadata={"extra": "data"})
        e = repo._events[0]
        assert e.failure_reason == FailureReason.IMAGE_UNRESOLVED.value
        assert e.metadata == {"extra": "data"}

    def test_repo_error_is_swallowed(self) -> None:
        svc = RuntimeAuditService(repo=_RaisingAuditRepo())
        svc.record("sid", RuntimeAuditEventType.LAB_START_SUCCESS)  # must not raise


# ---------------------------------------------------------------------------
# Tests: LabSessionService audit — None audit_svc
# ---------------------------------------------------------------------------


class TestLabSessionServiceNoAudit:
    def test_create_session_without_audit_svc_does_not_raise(self) -> None:
        repo = _MemSessionRepo()
        dr = _MemDraftRepo()
        dr._store["lab-1"] = _make_published_draft()
        svc = _make_svc(repo, draft_repo=dr, audit_repo=None)
        session = svc.create_session("lab-1", "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_complete_without_audit_svc_does_not_raise(self) -> None:
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, audit_repo=None)
        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED


# ---------------------------------------------------------------------------
# Tests: LabSessionService audit — events recorded
# ---------------------------------------------------------------------------


class TestLabSessionServiceAuditEvents:
    def test_create_session_success_emits_lab_start_success(self) -> None:
        repo = _MemSessionRepo()
        dr = _MemDraftRepo()
        dr._store["lab-1"] = _make_published_draft()
        audit = _MemAuditRepo()
        svc = _make_svc(repo, draft_repo=dr, audit_repo=audit)
        session = svc.create_session("lab-1", "vm-500", "student1")
        events = audit.list_by_session(session.session_id)
        assert len(events) == 1
        assert events[0].event_type == RuntimeAuditEventType.LAB_START_SUCCESS
        assert events[0].failure_reason is None

    def test_create_session_image_unresolved_emits_lab_start_failed(self) -> None:
        repo = _MemSessionRepo()
        dr = _MemDraftRepo()
        dr._store["lab-1"] = _make_published_draft(image_resolution=[
            ImageResolutionResult(
                image_intent="nginx",
                requested_image="nginx:latest",
                image_status=ImageStatus.UNRESOLVED,
            ),
        ])
        audit = _MemAuditRepo()
        svc = _make_svc(repo, draft_repo=dr, audit_repo=audit)
        session = svc.create_session("lab-1", "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        events = audit.list_by_session(session.session_id)
        assert len(events) == 1
        assert events[0].event_type == RuntimeAuditEventType.LAB_START_FAILED
        assert events[0].failure_reason == FailureReason.IMAGE_UNRESOLVED.value

    def test_create_session_namespace_fail_emits_lab_start_failed(self) -> None:
        repo = _MemSessionRepo()
        dr = _MemDraftRepo()
        dr._store["lab-1"] = _make_published_draft()
        audit = _MemAuditRepo()
        svc = _make_svc(repo, draft_repo=dr, ns_lifecycle=_FailingCreateAdapter(), audit_repo=audit)
        session = svc.create_session("lab-1", "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        events = audit.list_by_session(session.session_id)
        assert len(events) == 1
        assert events[0].event_type == RuntimeAuditEventType.LAB_START_FAILED
        assert events[0].failure_reason == FailureReason.NAMESPACE_CREATE_FAILED.value

    def test_complete_session_emits_complete_then_cleanup_success(self) -> None:
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        audit = _MemAuditRepo()
        svc = _make_svc(repo, audit_repo=audit)
        svc.complete_session(session.session_id)
        events = audit.list_by_session(session.session_id)
        event_types = [e.event_type for e in events]
        assert RuntimeAuditEventType.LAB_COMPLETE in event_types
        assert RuntimeAuditEventType.CLEANUP_SUCCESS in event_types
        assert event_types.index(RuntimeAuditEventType.LAB_COMPLETE) < event_types.index(RuntimeAuditEventType.CLEANUP_SUCCESS)

    def test_abort_session_emits_abort_then_cleanup_success(self) -> None:
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        audit = _MemAuditRepo()
        svc = _make_svc(repo, audit_repo=audit)
        svc.abort_session(session.session_id)
        events = audit.list_by_session(session.session_id)
        event_types = [e.event_type for e in events]
        assert RuntimeAuditEventType.LAB_ABORT in event_types
        assert RuntimeAuditEventType.CLEANUP_SUCCESS in event_types

    def test_cleanup_failed_emits_cleanup_failed_and_vm_tainted(self) -> None:
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        audit = _MemAuditRepo()
        svc = _make_svc(repo, ns_lifecycle=_FailingDeleteAdapter(), audit_repo=audit)
        svc.complete_session(session.session_id)
        events = audit.list_by_session(session.session_id)
        event_types = [e.event_type for e in events]
        assert RuntimeAuditEventType.CLEANUP_FAILED in event_types
        assert RuntimeAuditEventType.VM_TAINTED in event_types

    def test_cleanup_failed_event_has_failure_reason(self) -> None:
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        audit = _MemAuditRepo()
        svc = _make_svc(repo, ns_lifecycle=_FailingDeleteAdapter(), audit_repo=audit)
        svc.complete_session(session.session_id)
        failed = next(e for e in audit._events if e.event_type == RuntimeAuditEventType.CLEANUP_FAILED)
        assert failed.failure_reason == FailureReason.NAMESPACE_CLEANUP_FAILED.value

    def test_vm_tainted_event_has_vm_id_in_metadata(self) -> None:
        repo = _MemSessionRepo()
        session = _make_session(vm_id="vm-555", ready_to_complete=True)
        repo.create(session)
        audit = _MemAuditRepo()
        svc = _make_svc(repo, ns_lifecycle=_FailingDeleteAdapter(), audit_repo=audit)
        svc.complete_session(session.session_id)
        tainted = next(e for e in audit._events if e.event_type == RuntimeAuditEventType.VM_TAINTED)
        assert tainted.metadata.get("vm_id") == "vm-555"

    def test_no_namespace_cleanup_emits_cleanup_success(self) -> None:
        repo = _MemSessionRepo()
        session = _make_session(namespace=None, ready_to_complete=True)
        repo.create(session)
        audit = _MemAuditRepo()
        svc = _make_svc(repo, audit_repo=audit)
        svc.complete_session(session.session_id)
        event_types = [e.event_type for e in audit._events]
        assert RuntimeAuditEventType.CLEANUP_SUCCESS in event_types
        assert RuntimeAuditEventType.CLEANUP_FAILED not in event_types


# ---------------------------------------------------------------------------
# Tests: StepProgressionService audit
# ---------------------------------------------------------------------------


class _StubVerifierPassed:
    def check(self, session_id: str, template: VerifyTemplate) -> VerifyResult:
        return VerifyResult(session_id=session_id, verify_id=template.verify_id, verify_type=template.type.value, passed=True)


class _StubVerifierFailed:
    def check(self, session_id: str, template: VerifyTemplate) -> VerifyResult:
        return VerifyResult(
            session_id=session_id,
            verify_id=template.verify_id,
            verify_type=template.type.value,
            passed=False,
            error_code=FailureReason.VERIFIER_TYPE_NOT_IMPLEMENTED.value,
            failure_reason=FailureReason.VERIFIER_TYPE_NOT_IMPLEMENTED.value,
        )


def _make_step_draft(lab_id: str = "lab-1") -> LabDraft:
    return LabDraft(
        lab_id=lab_id,
        source_article_id="art-1",
        title="Step Test Lab",
        description="desc",
        estimated_duration_minutes=10,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="w", do="d", observe="o",
            explain=ExplainField(concept="c", observation="o"),
            verify=[VerifyTemplate(
                verify_id="v1",
                type=VerifyType.POD_RUNNING,
                name="nginx",
                namespace="test-ns",
            )],
        )],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.PUBLISHED,
    )


def _make_step_svc(
    session_repo: _MemSessionRepo,
    draft_repo: _MemDraftRepo,
    verifier,
    audit_repo: Optional[_MemAuditRepo] = None,
) -> StepProgressionService:
    audit_svc = RuntimeAuditService(repo=audit_repo) if audit_repo is not None else None
    return StepProgressionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        verifier_svc=verifier,
        audit_svc=audit_svc,
    )


class TestStepProgressionAudit:
    def test_step_check_passed_emits_step_check_passed(self) -> None:
        repo = _MemSessionRepo()
        dr = _MemDraftRepo()
        session = _make_session(lab_id="lab-1")
        repo.create(session)
        dr._store["lab-1"] = _make_step_draft()
        audit = _MemAuditRepo()
        svc = _make_step_svc(repo, dr, _StubVerifierPassed(), audit_repo=audit)
        svc.check_step(session.session_id, "s1", "student1")
        events = audit.list_by_session(session.session_id)
        assert len(events) == 1
        assert events[0].event_type == RuntimeAuditEventType.STEP_CHECK_PASSED
        assert events[0].metadata["step_id"] == "s1"
        assert events[0].metadata["step_index"] == 0

    def test_step_check_failed_emits_step_check_failed_with_failure_reason(self) -> None:
        repo = _MemSessionRepo()
        dr = _MemDraftRepo()
        session = _make_session(lab_id="lab-1")
        repo.create(session)
        dr._store["lab-1"] = _make_step_draft()
        audit = _MemAuditRepo()
        svc = _make_step_svc(repo, dr, _StubVerifierFailed(), audit_repo=audit)
        svc.check_step(session.session_id, "s1", "student1")
        events = audit.list_by_session(session.session_id)
        assert len(events) == 1
        assert events[0].event_type == RuntimeAuditEventType.STEP_CHECK_FAILED
        assert events[0].failure_reason == FailureReason.VERIFIER_TYPE_NOT_IMPLEMENTED.value

    def test_step_check_failed_without_failure_reason_has_none(self) -> None:
        class _VerifierFailedNoReason:
            def check(self, session_id: str, template: VerifyTemplate) -> VerifyResult:
                return VerifyResult(session_id=session_id, verify_id=template.verify_id, verify_type=template.type.value, passed=False)

        repo = _MemSessionRepo()
        dr = _MemDraftRepo()
        session = _make_session(lab_id="lab-1")
        repo.create(session)
        dr._store["lab-1"] = _make_step_draft()
        audit = _MemAuditRepo()
        svc = _make_step_svc(repo, dr, _VerifierFailedNoReason(), audit_repo=audit)
        svc.check_step(session.session_id, "s1", "student1")
        events = audit.list_by_session(session.session_id)
        assert events[0].failure_reason is None

    def test_step_check_with_no_audit_svc_does_not_raise(self) -> None:
        repo = _MemSessionRepo()
        dr = _MemDraftRepo()
        session = _make_session(lab_id="lab-1")
        repo.create(session)
        dr._store["lab-1"] = _make_step_draft()
        svc = _make_step_svc(repo, dr, _StubVerifierPassed(), audit_repo=None)
        result = svc.check_step(session.session_id, "s1", "student1")
        assert result.all_passed is True


# ---------------------------------------------------------------------------
# Tests: GET /api/lab-sessions/{id}/audit-events route
# ---------------------------------------------------------------------------


@contextmanager
def _audit_api_client(username: str, session: LabSessionState, audit_events: list[RuntimeAuditEvent]):
    from backend.main import app
    from backend.auth_deps import get_current_user
    from backend.labgen.routes import get_audit_repository, get_session_service

    repo = _MemSessionRepo()
    repo.create(session)
    audit_repo = _MemAuditRepo()
    for e in audit_events:
        audit_repo.append(e)

    svc = _make_svc(repo, audit_repo=None)  # audit not needed for route-level test

    app.dependency_overrides[get_session_service] = lambda: svc
    app.dependency_overrides[get_audit_repository] = lambda: audit_repo
    app.dependency_overrides[get_current_user] = lambda: username

    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


def _make_audit_events(session_id: str, n: int = 2) -> list[RuntimeAuditEvent]:
    types = [RuntimeAuditEventType.LAB_START_SUCCESS, RuntimeAuditEventType.LAB_COMPLETE]
    return [RuntimeAuditEvent(session_id=session_id, event_type=types[i % len(types)]) for i in range(n)]


class TestAuditEventRoute:
    def test_owner_can_get_audit_events(self) -> None:
        session = _make_session(student_username="student1")
        events = _make_audit_events(session.session_id)
        with _audit_api_client("student1", session, events) as client:
            r = client.get(f"/api/lab-sessions/{session.session_id}/audit-events")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_admin_can_get_audit_events(self) -> None:
        session = _make_session(student_username="student1")
        events = _make_audit_events(session.session_id, n=1)
        with _audit_api_client("admin", session, events) as client:
            with patch("backend.labgen.routes.auth_manager") as mock_am:
                mock_am.is_admin.return_value = True
                r = client.get(f"/api/lab-sessions/{session.session_id}/audit-events")
        assert r.status_code == 200

    def test_stranger_gets_403(self) -> None:
        session = _make_session(student_username="student1")
        with _audit_api_client("attacker", session, []) as client:
            r = client.get(f"/api/lab-sessions/{session.session_id}/audit-events")
        assert r.status_code == 403

    def test_unknown_session_gets_404(self) -> None:
        session = _make_session(student_username="student1")
        with _audit_api_client("student1", session, []) as client:
            r = client.get("/api/lab-sessions/nonexistent-id/audit-events")
        assert r.status_code == 404

    def test_empty_events_returns_empty_list(self) -> None:
        session = _make_session(student_username="student1")
        with _audit_api_client("student1", session, []) as client:
            r = client.get(f"/api/lab-sessions/{session.session_id}/audit-events")
        assert r.status_code == 200
        assert r.json() == []

    def test_event_type_field_in_response(self) -> None:
        session = _make_session(student_username="student1")
        events = [RuntimeAuditEvent(session_id=session.session_id, event_type=RuntimeAuditEventType.LAB_START_SUCCESS)]
        with _audit_api_client("student1", session, events) as client:
            r = client.get(f"/api/lab-sessions/{session.session_id}/audit-events")
        assert r.status_code == 200
        data = r.json()
        assert data[0]["event_type"] == RuntimeAuditEventType.LAB_START_SUCCESS.value
        assert data[0]["session_id"] == session.session_id
