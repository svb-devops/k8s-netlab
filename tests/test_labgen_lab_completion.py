"""
Lab Completion Hardening tests.

Validates the complete/abort boundary rules introduced by the completion
hardening requirement:
  - complete requires ready_to_complete=True
  - abort does not require ready_to_complete
  - complete and abort are mutually exclusive (terminal-state guard)
  - duplicate complete is rejected
  - cleanup failure marks VM tainted and enters LAB_CLEANUP_FAILED
  - non-owner is denied at the HTTP layer
"""

from __future__ import annotations

from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.lab_session_service import (
    LabNotReadyToComplete,
    LabSessionService,
    SessionAlreadyTerminated,
    StubVMTracker,
    VMTrackerPort,
)
from backend.labgen.namespace_lifecycle import (
    NamespaceLifecyclePort,
    StubNamespaceLifecycleAdapter,
)
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ConnectionState,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    Step,
)
from backend.labgen.routes import (
    get_session_repository,
    get_session_service,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers / in-memory fakes (duplicated locally so this file is self-contained)
# ---------------------------------------------------------------------------


def _make_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Completion Test Lab",
        description="desc",
        estimated_duration_minutes=20,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="w", do="d", observe="o",
            explain=ExplainField(concept="c", observation="o"),
        )],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.PUBLISHED,
    )
    defaults.update(kw)
    return LabDraft(**defaults)


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


class _RecordingVMTracker(VMTrackerPort):
    def __init__(self) -> None:
        self.tainted: list[str] = []

    def vm_exists(self, vm_id: str) -> bool:
        return True

    def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
        return True

    def mark_vm_tainted(self, vm_id: str) -> None:
        self.tainted.append(vm_id)

    def is_vm_tainted(self, vm_id: str) -> bool:
        return False


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


class _DelayedDeleteAdapter(NamespaceLifecyclePort):
    """Simulates async K3s namespace deletion: delete_namespace returns True immediately
    (K3s accepted the delete), but is_namespace_deleted returns False for the first
    `false_count` calls (namespace is Terminating), then True once actually gone.

    Regression adapter for: is_namespace_deleted called immediately after delete_namespace
    returned False even though deletion eventually completed.
    """

    def __init__(self, false_count: int = 1) -> None:
        self._false_count = false_count
        self._calls = 0

    def create_namespace(self, ns: str) -> bool:
        return True

    def namespace_exists(self, ns: str) -> bool:
        return True

    def delete_namespace(self, ns: str) -> bool:
        return True  # accepted immediately; K3s deletion is async

    def is_namespace_deleted(self, ns: str) -> bool:
        self._calls += 1
        return self._calls > self._false_count  # False for first N calls

    def ensure_verifier_rolebinding(self, ns: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, ns: str) -> bool:
        return True


def _make_svc(
    session_repo: _MemSessionRepo,
    ns_lifecycle: NamespaceLifecyclePort | None = None,
    vm_tracker: VMTrackerPort | None = None,
    ns_delete_poll_interval: float = 0.0,
    ns_delete_max_retries: int = 5,
) -> LabSessionService:
    return LabSessionService(
        session_repo=session_repo,
        draft_repo=_MemDraftRepo(),
        vm_tracker=vm_tracker or StubVMTracker(),
        ns_lifecycle=ns_lifecycle or StubNamespaceLifecycleAdapter(),
        image_resolver=_StubImageResolver(),
        ns_delete_poll_interval=ns_delete_poll_interval,
        ns_delete_max_retries=ns_delete_max_retries,
    )


class _StubImageResolver:
    def needs_recheck(self, img) -> bool:
        return False

    def check_registry_existence(self, img):
        return img


# ---------------------------------------------------------------------------
# Service-level: ready_to_complete guard
# ---------------------------------------------------------------------------


class TestReadyToCompleteGuard:
    def test_complete_raises_when_not_ready(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=False)
        repo.create(session)
        svc = _make_svc(repo)
        with pytest.raises(LabNotReadyToComplete):
            svc.complete_session(session.session_id)

    def test_session_stays_active_when_not_ready(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=False)
        repo.create(session)
        svc = _make_svc(repo)
        with pytest.raises(LabNotReadyToComplete):
            svc.complete_session(session.session_id)
        assert repo.get(session.session_id).lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_complete_succeeds_when_ready(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_abort_succeeds_without_ready_flag(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=False)
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED


# ---------------------------------------------------------------------------
# Service-level: mutual exclusion (complete ↔ abort)
# ---------------------------------------------------------------------------


class TestMutualExclusion:
    def test_complete_after_abort_raises(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo)
        svc.abort_session(session.session_id)
        with pytest.raises(SessionAlreadyTerminated):
            svc.complete_session(session.session_id)

    def test_abort_after_complete_raises(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo)
        svc.complete_session(session.session_id)
        with pytest.raises(SessionAlreadyTerminated):
            svc.abort_session(session.session_id)

    def test_double_complete_raises(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo)
        svc.complete_session(session.session_id)
        with pytest.raises(SessionAlreadyTerminated):
            svc.complete_session(session.session_id)

    def test_double_abort_raises(self):
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo)
        svc.abort_session(session.session_id)
        with pytest.raises(SessionAlreadyTerminated):
            svc.abort_session(session.session_id)


# ---------------------------------------------------------------------------
# Service-level: cleanup execution on complete / abort
# ---------------------------------------------------------------------------


class TestCleanupOnComplete:
    def test_complete_triggers_cleanup_and_closes(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True, namespace="lab-ns-complete")
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_complete_sets_connection_disconnected(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.complete_session(session.session_id)
        assert result.connection_state == ConnectionState.DISCONNECTED

    def test_cleanup_fail_on_complete_reaches_cleanup_failed(self):
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True, namespace="lab-ns-c")
        repo.create(session)
        svc = _make_svc(repo, ns_lifecycle=_FailingDeleteAdapter())
        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED

    def test_cleanup_fail_on_complete_marks_vm_tainted(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker()
        session = _make_session(vm_id="vm-501", ready_to_complete=True, namespace="lab-ns-d")
        repo.create(session)
        svc = _make_svc(repo, ns_lifecycle=_FailingDeleteAdapter(), vm_tracker=tracker)
        svc.complete_session(session.session_id)
        assert "vm-501" in tracker.tainted

    def test_cleanup_succeeds_when_namespace_deletion_is_async(self):
        """Regression: K3s namespace deletion is async. is_namespace_deleted may return False
        immediately after delete_namespace (namespace still Terminating), but cleanup must
        retry and eventually succeed once the namespace is actually gone."""
        repo = _MemSessionRepo()
        session = _make_session(ready_to_complete=True, namespace="lab-ns-async-del")
        repo.create(session)
        svc = _make_svc(
            repo,
            ns_lifecycle=_DelayedDeleteAdapter(false_count=2),
            ns_delete_poll_interval=0.0,
            ns_delete_max_retries=5,
        )
        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert result.cleanup_verified is True


class TestCleanupOnAbort:
    def test_abort_triggers_cleanup_and_closes(self):
        repo = _MemSessionRepo()
        session = _make_session(namespace="lab-ns-abort")
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_abort_sets_connection_disconnected(self):
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.abort_session(session.session_id)
        assert result.connection_state == ConnectionState.DISCONNECTED

    def test_cleanup_fail_on_abort_reaches_cleanup_failed(self):
        repo = _MemSessionRepo()
        session = _make_session(namespace="lab-ns-e")
        repo.create(session)
        svc = _make_svc(repo, ns_lifecycle=_FailingDeleteAdapter())
        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED

    def test_cleanup_fail_on_abort_marks_vm_tainted(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker()
        session = _make_session(vm_id="vm-502", namespace="lab-ns-f")
        repo.create(session)
        svc = _make_svc(repo, ns_lifecycle=_FailingDeleteAdapter(), vm_tracker=tracker)
        svc.abort_session(session.session_id)
        assert "vm-502" in tracker.tainted


# ---------------------------------------------------------------------------
# HTTP layer: endpoint behaviour
# ---------------------------------------------------------------------------


def _make_api_client(
    username: str,
    session: LabSessionState,
    ns_lifecycle: NamespaceLifecyclePort | None = None,
    vm_tracker: VMTrackerPort | None = None,
) -> tuple[TestClient, _MemSessionRepo]:
    from backend.main import app
    from backend.auth_deps import get_current_user

    repo = _MemSessionRepo()
    repo.create(session)
    svc = _make_svc(repo, ns_lifecycle=ns_lifecycle, vm_tracker=vm_tracker)

    app.dependency_overrides[get_session_repository] = lambda: repo
    app.dependency_overrides[get_session_service] = lambda: svc
    app.dependency_overrides[get_current_user] = lambda: username
    client = TestClient(app, raise_server_exceptions=True)
    return client, repo


class TestCompletionAPIEndpoints:
    def teardown_method(self) -> None:
        from backend.main import app
        app.dependency_overrides.clear()

    def test_complete_409_when_not_ready(self):
        session = _make_session(ready_to_complete=False)
        client, _ = _make_api_client("student1", session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 409
        assert "lab_not_ready_to_complete" in r.json()["detail"]

    def test_complete_200_when_ready(self):
        session = _make_session(ready_to_complete=True)
        client, _ = _make_api_client("student1", session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 200
        assert r.json()["lab_session_status"] == "LAB_CLOSED"

    def test_complete_409_on_duplicate_call(self):
        session = _make_session(ready_to_complete=True)
        client, _ = _make_api_client("student1", session)
        client.post(f"/api/lab-sessions/{session.session_id}/complete")
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 409

    def test_complete_403_for_non_owner(self):
        session = _make_session(student_username="other")
        client, _ = _make_api_client("attacker", session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 403

    def test_abort_200_without_ready_flag(self):
        session = _make_session(ready_to_complete=False)
        client, _ = _make_api_client("student1", session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/abort")
        assert r.status_code == 200

    def test_abort_403_for_non_owner(self):
        session = _make_session(student_username="other")
        client, _ = _make_api_client("attacker", session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/abort")
        assert r.status_code == 403

    def test_abort_409_after_complete(self):
        session = _make_session(ready_to_complete=True)
        client, _ = _make_api_client("student1", session)
        client.post(f"/api/lab-sessions/{session.session_id}/complete")
        r = client.post(f"/api/lab-sessions/{session.session_id}/abort")
        assert r.status_code == 409

    def test_complete_409_after_abort(self):
        session = _make_session(ready_to_complete=True)
        client, _ = _make_api_client("student1", session)
        client.post(f"/api/lab-sessions/{session.session_id}/abort")
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 409

    def test_complete_cleanup_fail_returns_cleanup_failed(self):
        session = _make_session(ready_to_complete=True, namespace="lab-ns-g")
        client, _ = _make_api_client("student1", session, ns_lifecycle=_FailingDeleteAdapter())
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 200
        assert r.json()["lab_session_status"] == "LAB_CLEANUP_FAILED"
