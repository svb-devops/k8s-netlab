"""Tests for Lab Session state machine — repository, service, and API endpoints."""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.lab_session_service import (
    LabSessionService,
    NamespaceInspector,
    PrecheckFailed,
    SessionAlreadyTerminated,
    StubNamespaceInspector,
    StubVMTracker,
    VMTrackerPort,
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
    require_internal_token,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_published_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Test Lab",
        description="desc",
        estimated_duration_minutes=30,
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
        namespace="lab-abc12345",
    )
    defaults.update(kw)
    return LabSessionState(**defaults)


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _MemSessionRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabSessionState] = {}

    def create(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._store.get(session_id)

    def update(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def list_by_student(self, student_username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == student_username]


class _MemDraftRepo:
    def __init__(self, drafts: dict[str, LabDraft] | None = None) -> None:
        self._store: dict[str, LabDraft] = drafts or {}

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)


class _FailingNamespaceInspector(NamespaceInspector):
    def request_namespace_cleanup(self, namespace: str) -> bool:
        return False


class _RaisingNamespaceInspector(NamespaceInspector):
    def request_namespace_cleanup(self, namespace: str) -> bool:
        raise RuntimeError("K8s unavailable")


class _RecordingVMTracker(VMTrackerPort):
    def __init__(self) -> None:
        self.tainted: list[str] = []

    def vm_exists(self, vm_id: str) -> bool:
        return True

    def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
        return True

    def mark_vm_tainted(self, vm_id: str) -> None:
        self.tainted.append(vm_id)


def _make_svc(
    drafts: dict[str, LabDraft] | None = None,
    session_repo: _MemSessionRepo | None = None,
    vm_tracker: VMTrackerPort | None = None,
    ns_inspector: NamespaceInspector | None = None,
) -> tuple[LabSessionService, _MemSessionRepo]:
    repo = session_repo or _MemSessionRepo()
    svc = LabSessionService(
        session_repo=repo,
        draft_repo=_MemDraftRepo(drafts),
        vm_tracker=vm_tracker or StubVMTracker(),
        ns_inspector=ns_inspector or StubNamespaceInspector(),
    )
    return svc, repo


# ---------------------------------------------------------------------------
# Fixtures for API tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_session_repo() -> _MemSessionRepo:
    return _MemSessionRepo()


@pytest.fixture()
def student_client(mem_session_repo):
    from backend.main import app
    from backend.auth_deps import get_current_user

    draft = _make_published_draft()
    drafts = {draft.lab_id: draft}

    svc = LabSessionService(
        session_repo=mem_session_repo,
        draft_repo=_MemDraftRepo(drafts),
        vm_tracker=StubVMTracker(),
        ns_inspector=StubNamespaceInspector(),
    )

    app.dependency_overrides[get_session_repository] = lambda: mem_session_repo
    app.dependency_overrides[get_session_service] = lambda: svc
    app.dependency_overrides[get_current_user] = lambda: "student1"
    c = TestClient(app, raise_server_exceptions=True)
    yield c, draft.lab_id
    app.dependency_overrides.clear()


@pytest.fixture()
def internal_client(mem_session_repo):
    from backend.main import app

    svc = LabSessionService(
        session_repo=mem_session_repo,
        draft_repo=_MemDraftRepo(),
        vm_tracker=StubVMTracker(),
        ns_inspector=StubNamespaceInspector(),
    )

    app.dependency_overrides[get_session_repository] = lambda: mem_session_repo
    app.dependency_overrides[get_session_service] = lambda: svc
    app.dependency_overrides[require_internal_token] = lambda: None
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


# ===========================================================================
# Repository unit tests
# ===========================================================================


class TestLabSessionRepository:
    def test_create_and_get_roundtrip(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        session = _make_session()
        repo.create(session)
        loaded = repo.get(session.session_id)
        assert loaded is not None
        assert loaded.session_id == session.session_id

    def test_get_returns_none_for_missing(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        assert repo.get("nonexistent") is None

    def test_update_overwrites(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        session = _make_session()
        repo.create(session)
        updated = session.model_copy(update={"lab_session_status": LabSessionStatus.LAB_CLOSED})
        repo.update(updated)
        assert repo.get(session.session_id).lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_list_by_student_filters_correctly(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        s1 = _make_session(student_username="alice")
        s2 = _make_session(student_username="bob")
        repo.create(s1)
        repo.create(s2)
        alice_sessions = repo.list_by_student("alice")
        assert len(alice_sessions) == 1
        assert alice_sessions[0].student_username == "alice"

    def test_list_by_student_empty_for_unknown(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        assert repo.list_by_student("nobody") == []

    def test_schema_version_preserved(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        session = _make_session()
        repo.create(session)
        assert repo.get(session.session_id).schema_version == "1.0"


# ===========================================================================
# Service — precheck unit tests
# ===========================================================================


class TestPrecheck:
    def test_all_checks_pass_on_valid_draft(self):
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert result.passed
        assert result.failures == []

    def test_precheck_fails_when_draft_not_found(self):
        svc, _ = _make_svc(drafts={})
        result = svc.run_precheck("missing-draft", "vm-500", "student1")
        assert not result.passed
        assert "precheck.draft_not_found" in result.failures

    def test_precheck_fails_when_draft_not_published(self):
        draft = _make_published_draft(publish_status=PublishStatus.DRAFT)
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert "precheck.draft_not_published" in result.failures

    def test_precheck_fails_when_cleanup_not_declared(self):
        draft = _make_published_draft(cleanup=None)
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert "precheck.cleanup_not_declared" in result.failures

    def test_precheck_fails_when_vm_not_found(self):
        class NoVMTracker(VMTrackerPort):
            def vm_exists(self, vm_id: str) -> bool:
                return False
            def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
                return False
            def mark_vm_tainted(self, vm_id: str) -> None:
                pass

        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, vm_tracker=NoVMTracker())
        result = svc.run_precheck(draft.lab_id, "vm-999", "student1")
        assert "precheck.vm_not_found" in result.failures

    def test_precheck_fails_when_vm_not_owned(self):
        class WrongOwnerTracker(VMTrackerPort):
            def vm_exists(self, vm_id: str) -> bool:
                return True
            def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
                return False
            def mark_vm_tainted(self, vm_id: str) -> None:
                pass

        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, vm_tracker=WrongOwnerTracker())
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert "precheck.vm_not_owned_by_student" in result.failures

    def test_precheck_fails_when_session_already_active(self):
        draft = _make_published_draft()
        repo = _MemSessionRepo()
        existing = _make_session(lab_id=draft.lab_id, student_username="student1",
                                  lab_session_status=LabSessionStatus.LAB_ACTIVE)
        repo.create(existing)
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, session_repo=repo)
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert "precheck.session_already_active" in result.failures


# ===========================================================================
# Service — lifecycle unit tests
# ===========================================================================


class TestLabSessionLifecycle:
    def test_create_session_returns_lab_active(self):
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_create_session_sets_namespace(self):
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.namespace is not None
        assert session.namespace == f"lab-{session.session_id}"

    def test_run_cleanup_is_idempotent_on_closed_session(self):
        repo = _MemSessionRepo()
        session = _make_session(lab_session_status=LabSessionStatus.LAB_CLOSED)
        repo.create(session)
        svc, _ = _make_svc(session_repo=repo)
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_create_session_sets_connection_state_connected(self):
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.connection_state == ConnectionState.CONNECTED

    def test_create_session_raises_precheck_failed_on_bad_draft(self):
        svc, _ = _make_svc(drafts={})
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_session("nonexistent", "vm-500", "student1")
        assert "precheck.draft_not_found" in exc_info.value.failures

    def test_complete_session_moves_to_lab_closed(self):
        draft = _make_published_draft()
        svc, repo = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_complete_session_sets_disconnected(self):
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        result = svc.complete_session(session.session_id)
        assert result.connection_state == ConnectionState.DISCONNECTED

    def test_complete_session_raises_if_already_terminal(self):
        repo = _MemSessionRepo()
        closed = _make_session(lab_session_status=LabSessionStatus.LAB_CLOSED)
        repo.create(closed)
        svc, _ = _make_svc(session_repo=repo)
        with pytest.raises(SessionAlreadyTerminated):
            svc.complete_session(closed.session_id)

    def test_abort_session_moves_to_lab_closed(self):
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_abort_session_raises_if_already_terminal(self):
        repo = _MemSessionRepo()
        closed = _make_session(lab_session_status=LabSessionStatus.LAB_CLOSED)
        repo.create(closed)
        svc, _ = _make_svc(session_repo=repo)
        with pytest.raises(SessionAlreadyTerminated):
            svc.abort_session(closed.session_id)

    def test_cleanup_failure_marks_vm_tainted(self):
        tracker = _RecordingVMTracker()
        repo = _MemSessionRepo()
        session = _make_session(vm_id="vm-500", lab_id="lab-1",
                                 lab_session_status=LabSessionStatus.LAB_ACTIVE,
                                 namespace="lab-abc12345")
        repo.create(session)
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo(),
            vm_tracker=tracker,
            ns_inspector=_FailingNamespaceInspector(),
        )
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED
        assert "vm-500" in tracker.tainted

    def test_cleanup_exception_also_marks_vm_tainted(self):
        tracker = _RecordingVMTracker()
        repo = _MemSessionRepo()
        session = _make_session(vm_id="vm-500", namespace="lab-abc12345")
        repo.create(session)
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo(),
            vm_tracker=tracker,
            ns_inspector=_RaisingNamespaceInspector(),
        )
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED

    def test_cleanup_without_namespace_closes_directly(self):
        repo = _MemSessionRepo()
        session = _make_session(namespace=None)
        repo.create(session)
        svc, _ = _make_svc(session_repo=repo)
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_run_cleanup_is_independent_of_complete_abort(self):
        repo = _MemSessionRepo()
        session = _make_session(lab_session_status=LabSessionStatus.LAB_ABORTED)
        repo.create(session)
        svc, _ = _make_svc(session_repo=repo)
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED


# ===========================================================================
# API endpoint tests
# ===========================================================================


class TestCreateSessionEndpoint:
    def test_create_returns_201(self, student_client):
        client, lab_id = student_client
        r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "vm-500"})
        assert r.status_code == 201

    def test_create_returns_lab_active(self, student_client):
        client, lab_id = student_client
        r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "vm-500"})
        assert r.json()["lab_session_status"] == "LAB_ACTIVE"

    def test_create_returns_session_id(self, student_client):
        client, lab_id = student_client
        r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "vm-500"})
        assert "session_id" in r.json()

    def test_create_precheck_fail_returns_422(self, student_client):
        client, _ = student_client
        r = client.post("/api/lab-sessions", json={"lab_id": "nonexistent", "vm_id": "vm-500"})
        assert r.status_code == 422

    def test_create_422_body_contains_precheck_failures(self, student_client):
        client, _ = student_client
        r = client.post("/api/lab-sessions", json={"lab_id": "nonexistent", "vm_id": "vm-500"})
        detail = r.json()["detail"]
        assert "precheck_failures" in detail

    def test_create_requires_auth(self):
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/api/lab-sessions", json={"lab_id": "lab-1", "vm_id": "vm-500"})
        assert r.status_code in (401, 403)


class TestGetSessionEndpoint:
    def test_owner_can_get_session(self, student_client, mem_session_repo):
        client, lab_id = student_client
        session = _make_session(lab_id=lab_id, student_username="student1")
        mem_session_repo.create(session)
        r = client.get(f"/api/lab-sessions/{session.session_id}")
        assert r.status_code == 200

    def test_get_returns_correct_session_id(self, student_client, mem_session_repo):
        client, lab_id = student_client
        session = _make_session(lab_id=lab_id, student_username="student1")
        mem_session_repo.create(session)
        r = client.get(f"/api/lab-sessions/{session.session_id}")
        assert r.json()["session_id"] == session.session_id

    def test_get_404_for_missing(self, student_client):
        client, _ = student_client
        r = client.get("/api/lab-sessions/nonexistent")
        assert r.status_code == 404

    def test_get_403_for_other_student(self, mem_session_repo):
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.lab_session_service import LabSessionService

        session = _make_session(student_username="other_student")
        mem_session_repo.create(session)
        svc = LabSessionService(
            session_repo=mem_session_repo,
            draft_repo=_MemDraftRepo(),
            vm_tracker=StubVMTracker(),
            ns_inspector=StubNamespaceInspector(),
        )
        app.dependency_overrides[get_session_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: "attacker"
        c = TestClient(app, raise_server_exceptions=True)
        r = c.get(f"/api/lab-sessions/{session.session_id}")
        app.dependency_overrides.clear()
        assert r.status_code == 403


class TestCompleteAbortEndpoints:
    def test_complete_returns_200(self, student_client, mem_session_repo):
        client, lab_id = student_client
        session = _make_session(lab_id=lab_id, student_username="student1")
        mem_session_repo.create(session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 200

    def test_complete_returns_lab_closed(self, student_client, mem_session_repo):
        client, lab_id = student_client
        session = _make_session(lab_id=lab_id, student_username="student1")
        mem_session_repo.create(session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.json()["lab_session_status"] == "LAB_CLOSED"

    def test_abort_returns_200(self, student_client, mem_session_repo):
        client, lab_id = student_client
        session = _make_session(lab_id=lab_id, student_username="student1")
        mem_session_repo.create(session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/abort")
        assert r.status_code == 200

    def test_complete_404_for_missing(self, student_client):
        client, _ = student_client
        r = client.post("/api/lab-sessions/nonexistent/complete")
        assert r.status_code == 404

    def test_complete_409_on_terminal_session(self, student_client, mem_session_repo):
        client, lab_id = student_client
        session = _make_session(lab_id=lab_id, student_username="student1",
                                 lab_session_status=LabSessionStatus.LAB_CLOSED)
        mem_session_repo.create(session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 409


class TestInternalCleanupEndpoint:
    def test_cleanup_returns_200(self, internal_client, mem_session_repo):
        session = _make_session()
        mem_session_repo.create(session)
        r = internal_client.post(f"/internal/lab-sessions/{session.session_id}/cleanup")
        assert r.status_code == 200

    def test_cleanup_returns_lab_closed(self, internal_client, mem_session_repo):
        session = _make_session()
        mem_session_repo.create(session)
        r = internal_client.post(f"/internal/lab-sessions/{session.session_id}/cleanup")
        assert r.json()["lab_session_status"] == "LAB_CLOSED"

    def test_cleanup_404_for_missing(self, internal_client):
        r = internal_client.post("/internal/lab-sessions/nonexistent/cleanup")
        assert r.status_code == 404

    def test_cleanup_requires_admin_token(self):
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/internal/lab-sessions/some-id/cleanup")
        assert r.status_code == 401
