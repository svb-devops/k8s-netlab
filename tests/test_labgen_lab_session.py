"""Tests for Lab Session state machine — repository, service, and API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.lab_session_service import (
    LabSessionService,
    PrecheckFailed,
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
    ImageResolutionResult,
    ImageStatus,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    Step,
)
from backend.labgen.routes import (
    get_image_resolver,
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
        self._store: dict[str, LabDraft] = dict(drafts or {})
        self.update_calls: list[LabDraft] = []

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        self.update_calls.append(draft)
        return draft


class _StubImageResolver:
    """Stub ImageResolver — configurable pass/fail for image existence checks."""

    def __init__(
        self,
        needs_recheck_val: bool = False,
        existence_check_passes: bool = True,
    ) -> None:
        self._needs_recheck = needs_recheck_val
        self._passes = existence_check_passes
        self.recheck_called_for: list[ImageResolutionResult] = []

    def needs_recheck(self, img: ImageResolutionResult) -> bool:
        return self._needs_recheck

    def check_registry_existence(self, img: ImageResolutionResult) -> ImageResolutionResult:
        self.recheck_called_for.append(img)
        return img.model_copy(update={"existence_check_passed": self._passes})


class _FailingDeleteAdapter(NamespaceLifecyclePort):
    """create OK, delete returns False — simulates delete API failure."""

    def create_namespace(self, namespace: str) -> bool:
        return True

    def namespace_exists(self, namespace: str) -> bool:
        return True

    def delete_namespace(self, namespace: str) -> bool:
        return False

    def is_namespace_deleted(self, namespace: str) -> bool:
        return False

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        return True


class _RaisingDeleteAdapter(NamespaceLifecyclePort):
    """create OK, delete raises — simulates K8s API being unavailable."""

    def create_namespace(self, namespace: str) -> bool:
        return True

    def namespace_exists(self, namespace: str) -> bool:
        return True

    def delete_namespace(self, namespace: str) -> bool:
        raise RuntimeError("K8s unavailable")

    def is_namespace_deleted(self, namespace: str) -> bool:
        raise RuntimeError("K8s unavailable")

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        return True


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


def _make_svc(
    drafts: dict[str, LabDraft] | None = None,
    session_repo: _MemSessionRepo | None = None,
    vm_tracker: VMTrackerPort | None = None,
    ns_lifecycle: NamespaceLifecyclePort | None = None,
    image_resolver: _StubImageResolver | None = None,
) -> tuple[LabSessionService, _MemSessionRepo]:
    repo = session_repo or _MemSessionRepo()
    svc = LabSessionService(
        session_repo=repo,
        draft_repo=_MemDraftRepo(drafts),
        vm_tracker=vm_tracker or StubVMTracker(),
        ns_lifecycle=ns_lifecycle or StubNamespaceLifecycleAdapter(),
        image_resolver=image_resolver or _StubImageResolver(),
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
        ns_lifecycle=StubNamespaceLifecycleAdapter(),
        image_resolver=_StubImageResolver(),
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
        ns_lifecycle=StubNamespaceLifecycleAdapter(),
        image_resolver=_StubImageResolver(),
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

    def test_has_active_session_for_vm_true_when_lab_active(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        repo.create(_make_session(vm_id="401", lab_session_status=LabSessionStatus.LAB_ACTIVE))
        assert repo.has_active_session_for_vm("401") is True

    def test_has_active_session_for_vm_false_when_lab_closed(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        repo.create(_make_session(vm_id="401", lab_session_status=LabSessionStatus.LAB_CLOSED))
        assert repo.has_active_session_for_vm("401") is False

    def test_has_active_session_for_vm_false_when_no_sessions(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        assert repo.has_active_session_for_vm("401") is False

    def test_has_active_session_for_vm_false_when_aborted(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        repo.create(_make_session(vm_id="401", lab_session_status=LabSessionStatus.LAB_ABORTED))
        assert repo.has_active_session_for_vm("401") is False

    def test_has_active_session_for_vm_true_during_cleanup(self, tmp_path):
        """Cleanup 中的 session 仍应阻止 VM 删除。"""
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        repo.create(_make_session(vm_id="401", lab_session_status=LabSessionStatus.CLEANUP_REQUESTED))
        assert repo.has_active_session_for_vm("401") is True

    def test_has_active_session_for_vm_false_for_different_vm(self, tmp_path):
        repo = LabSessionRepository(path=tmp_path / "sessions.json")
        repo.create(_make_session(vm_id="402", lab_session_status=LabSessionStatus.LAB_ACTIVE))
        assert repo.has_active_session_for_vm("401") is False


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
            def is_vm_tainted(self, vm_id: str) -> bool:
                return False

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
            def is_vm_tainted(self, vm_id: str) -> bool:
                return False

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
        repo.update(session.model_copy(update={"ready_to_complete": True}))
        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_complete_session_sets_disconnected(self):
        draft = _make_published_draft()
        svc, repo = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        repo.update(session.model_copy(update={"ready_to_complete": True}))
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
            ns_lifecycle=_FailingDeleteAdapter(),
            image_resolver=_StubImageResolver(),
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
            ns_lifecycle=_RaisingDeleteAdapter(),
            image_resolver=_StubImageResolver(),
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

    def test_create_without_vm_id_returns_422_when_no_vm_assigned(self, student_client):
        """Regression: POST /api/lab-sessions without vm_id → 422 when student has no VM."""
        import unittest.mock as mock
        client, lab_id = student_client
        with mock.patch("backend.labgen.routes.VMTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.get_user_vms.return_value = []
            r = client.post("/api/lab-sessions", json={"lab_id": lab_id})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "precheck_failures" in detail
        codes = [f["code"] for f in detail["precheck_failures"]]
        assert "no_vm_assigned" in codes
        # Message must be actionable (tell user to go to /app) — not just "Contact instructor"
        msgs = [f.get("message", "") for f in detail["precheck_failures"]]
        assert any("/app" in m for m in msgs), (
            f"no_vm_assigned message must reference /app so user knows where to go. Got: {msgs}"
        )

    def test_create_without_vm_id_auto_discovers_student_vm(self, student_client):
        """Regression: POST /api/lab-sessions without vm_id uses student's first tracked VM."""
        import unittest.mock as mock
        client, lab_id = student_client
        with mock.patch("backend.labgen.routes.VMTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.get_user_vms.return_value = [500]
            r = client.post("/api/lab-sessions", json={"lab_id": lab_id})
        assert r.status_code == 201
        assert r.json()["vm_id"] == "500"


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
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
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
        session = _make_session(lab_id=lab_id, student_username="student1",
                                 ready_to_complete=True)
        mem_session_repo.create(session)
        r = client.post(f"/api/lab-sessions/{session.session_id}/complete")
        assert r.status_code == 200

    def test_complete_returns_lab_closed(self, student_client, mem_session_repo):
        client, lab_id = student_client
        session = _make_session(lab_id=lab_id, student_username="student1",
                                 ready_to_complete=True)
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


# ===========================================================================
# Service — IMAGE_CHECK_RUNNING phase unit tests
# ===========================================================================


def _make_resolved_img(**kw) -> ImageResolutionResult:
    defaults = dict(
        image_intent="nginx",
        requested_image="nginx:1.25-alpine",
        resolved_image="internal/nginx:1.25-alpine",
        image_status=ImageStatus.RESOLVED,
        existence_check_passed=True,
        existence_checked_at=datetime.now(timezone.utc),
    )
    defaults.update(kw)
    return ImageResolutionResult(**defaults)


class TestImageCheck:
    def test_no_images_passes(self):
        """Empty image_resolution list skips check, session becomes LAB_ACTIVE."""
        draft = _make_published_draft(image_resolution=[])
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_resolved_and_verified_image_passes(self):
        """RESOLVED image with cached existence_check_passed=True → LAB_ACTIVE."""
        img = _make_resolved_img(existence_check_passed=True)
        draft = _make_published_draft(image_resolution=[img])
        svc, _ = _make_svc(
            drafts={draft.lab_id: draft},
            image_resolver=_StubImageResolver(needs_recheck_val=False),
        )
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_unresolved_image_fails_start(self):
        """UNRESOLVED image → LAB_START_FAILED with failure_reason=image_unresolved."""
        img = _make_resolved_img(image_status=ImageStatus.UNRESOLVED)
        draft = _make_published_draft(image_resolution=[img])
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "image_unresolved"

    def test_blocked_image_fails_start(self):
        """BLOCKED image → LAB_START_FAILED with failure_reason=image_unresolved."""
        img = _make_resolved_img(image_status=ImageStatus.BLOCKED, resolved_image=None)
        draft = _make_published_draft(image_resolution=[img])
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "image_unresolved"

    def test_needs_recheck_calls_resolver(self):
        """needs_recheck=True → check_registry_existence is called → LAB_ACTIVE."""
        img = _make_resolved_img(existence_check_passed=None, existence_checked_at=None)
        draft = _make_published_draft(image_resolution=[img])
        resolver = _StubImageResolver(needs_recheck_val=True, existence_check_passes=True)
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, image_resolver=resolver)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        assert len(resolver.recheck_called_for) == 1

    def test_needs_recheck_fails_when_unavailable(self):
        """TTL expired + registry check fails → LAB_START_FAILED with failure_reason=image_unavailable."""
        img = _make_resolved_img(existence_check_passed=None, existence_checked_at=None)
        draft = _make_published_draft(image_resolution=[img])
        resolver = _StubImageResolver(needs_recheck_val=True, existence_check_passes=False)
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, image_resolver=resolver)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "image_unavailable"

    def test_cached_unavailable_fails_without_recheck(self):
        """existence_check_passed=False, needs_recheck=False → fail without calling resolver."""
        img = _make_resolved_img(existence_check_passed=False)
        draft = _make_published_draft(image_resolution=[img])
        resolver = _StubImageResolver(needs_recheck_val=False)
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, image_resolver=resolver)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "image_unavailable"
        assert len(resolver.recheck_called_for) == 0

    def test_recheck_updates_draft_on_success(self):
        """After successful recheck, draft.image_resolution is persisted."""
        img = _make_resolved_img(existence_check_passed=None, existence_checked_at=None)
        draft = _make_published_draft(image_resolution=[img])
        draft_repo = _MemDraftRepo(drafts={draft.lab_id: draft})
        resolver = _StubImageResolver(needs_recheck_val=True, existence_check_passes=True)
        svc = LabSessionService(
            session_repo=_MemSessionRepo(),
            draft_repo=draft_repo,
            vm_tracker=StubVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=resolver,
        )
        svc.create_session(draft.lab_id, "vm-500", "student1")
        assert len(draft_repo.update_calls) == 1
        saved = draft_repo.update_calls[0]
        assert saved.image_resolution[0].existence_check_passed is True

    def test_no_recheck_does_not_update_draft(self):
        """needs_recheck=False → draft not written."""
        img = _make_resolved_img(existence_check_passed=True)
        draft = _make_published_draft(image_resolution=[img])
        draft_repo = _MemDraftRepo(drafts={draft.lab_id: draft})
        resolver = _StubImageResolver(needs_recheck_val=False)
        svc = LabSessionService(
            session_repo=_MemSessionRepo(),
            draft_repo=draft_repo,
            vm_tracker=StubVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=resolver,
        )
        svc.create_session(draft.lab_id, "vm-500", "student1")
        assert len(draft_repo.update_calls) == 0

    def test_any_image_failure_stops_start(self):
        """First image passes, second is unresolved → LAB_START_FAILED."""
        good = _make_resolved_img(image_intent="nginx", existence_check_passed=True)
        bad = _make_resolved_img(
            image_intent="badimage",
            image_status=ImageStatus.UNRESOLVED,
        )
        draft = _make_published_draft(image_resolution=[good, bad])
        svc, _ = _make_svc(
            drafts={draft.lab_id: draft},
            image_resolver=_StubImageResolver(needs_recheck_val=False),
        )
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "image_unresolved"

    def test_start_failed_session_has_no_namespace(self):
        """LAB_START_FAILED (image) session must not have a namespace set."""
        img = _make_resolved_img(image_status=ImageStatus.UNRESOLVED)
        draft = _make_published_draft(image_resolution=[img])
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.namespace is None


# ===========================================================================
# Service — NAMESPACE_CREATING phase unit tests
# ===========================================================================


class TestNamespaceLifecycle:
    # ------------------------------------------------------------------
    # Namespace create + verify
    # ------------------------------------------------------------------

    def test_create_namespace_called_with_derived_name(self):
        """create_namespace is called with namespace = lab-{session_id}."""
        adapter = StubNamespaceLifecycleAdapter()
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert len(adapter.created) == 1
        assert adapter.created[0] == f"lab-{session.session_id}"

    def test_namespace_exists_verified_after_create(self):
        """After create_namespace succeeds, namespace_exists is always called."""

        class _TrackingAdapter(StubNamespaceLifecycleAdapter):
            def __init__(self):
                super().__init__()
                self.exists_calls: list[str] = []

            def namespace_exists(self, namespace: str) -> bool:
                self.exists_calls.append(namespace)
                return True

        adapter = _TrackingAdapter()
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert len(adapter.exists_calls) == 1
        assert adapter.exists_calls[0] == f"lab-{session.session_id}"

    def test_create_namespace_failure_returns_lab_start_failed(self):
        """create_namespace returns False → LAB_START_FAILED."""
        adapter = StubNamespaceLifecycleAdapter(create_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED

    def test_create_namespace_failure_has_observable_failure_reason(self):
        """failure_reason is set and readable when namespace create fails."""
        adapter = StubNamespaceLifecycleAdapter(create_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.failure_reason == "namespace_create_failed"

    def test_namespace_not_found_after_create_returns_lab_start_failed(self):
        """create_namespace succeeds but namespace_exists returns False → LAB_START_FAILED."""
        adapter = StubNamespaceLifecycleAdapter(
            create_succeeds=True, exists_after_create=False
        )
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "namespace_create_failed"

    def test_create_namespace_exception_returns_lab_start_failed(self):
        """Exception from create_namespace is caught and treated as failure."""

        class _ExplodingAdapter(NamespaceLifecyclePort):
            def create_namespace(self, namespace: str) -> bool:
                raise RuntimeError("K8s API unreachable")

            def namespace_exists(self, namespace: str) -> bool:
                return False

            def delete_namespace(self, namespace: str) -> bool:
                return True

            def is_namespace_deleted(self, namespace: str) -> bool:
                return True

            def ensure_verifier_rolebinding(self, namespace: str) -> bool:
                return True

            def verifier_rolebinding_exists(self, namespace: str) -> bool:
                return True

        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=_ExplodingAdapter())
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "namespace_create_failed"

    def test_start_failed_namespace_create_session_is_persisted(self):
        """LAB_START_FAILED (namespace) session is stored in the repository."""
        repo = _MemSessionRepo()
        adapter = StubNamespaceLifecycleAdapter(create_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, session_repo=repo, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        stored = repo.get(session.session_id)
        assert stored is not None
        assert stored.lab_session_status == LabSessionStatus.LAB_START_FAILED

    def test_start_failed_namespace_create_has_no_lab_active_state(self):
        """Namespace failure must not produce LAB_ACTIVE."""
        adapter = StubNamespaceLifecycleAdapter(create_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status != LabSessionStatus.LAB_ACTIVE

    # ------------------------------------------------------------------
    # Namespace delete + verify
    # ------------------------------------------------------------------

    def test_delete_namespace_called_on_cleanup(self):
        """delete_namespace is called with the session's namespace during cleanup."""
        adapter = StubNamespaceLifecycleAdapter()
        repo = _MemSessionRepo()
        session = _make_session(namespace="lab-abc123")
        repo.create(session)
        svc, _ = _make_svc(session_repo=repo, ns_lifecycle=adapter)
        svc.run_cleanup(session.session_id)
        assert "lab-abc123" in adapter.deleted

    def test_is_namespace_deleted_verified_after_delete(self):
        """After delete_namespace, is_namespace_deleted is called to confirm."""

        class _TrackingDeleteAdapter(StubNamespaceLifecycleAdapter):
            def __init__(self):
                super().__init__()
                self.deleted_check_calls: list[str] = []

            def is_namespace_deleted(self, namespace: str) -> bool:
                self.deleted_check_calls.append(namespace)
                return True

        adapter = _TrackingDeleteAdapter()
        repo = _MemSessionRepo()
        session = _make_session(namespace="lab-abc123")
        repo.create(session)
        svc, _ = _make_svc(session_repo=repo, ns_lifecycle=adapter)
        svc.run_cleanup(session.session_id)
        assert "lab-abc123" in adapter.deleted_check_calls

    def test_delete_namespace_failure_sets_cleanup_failed(self):
        """delete_namespace returns False → LAB_CLEANUP_FAILED."""
        adapter = StubNamespaceLifecycleAdapter(delete_succeeds=False)
        repo = _MemSessionRepo()
        session = _make_session(namespace="lab-abc123")
        repo.create(session)
        svc, _ = _make_svc(session_repo=repo, ns_lifecycle=adapter)
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED

    def test_namespace_not_deleted_after_delete_sets_cleanup_failed(self):
        """delete_namespace succeeds but is_namespace_deleted returns False → LAB_CLEANUP_FAILED."""
        adapter = StubNamespaceLifecycleAdapter(
            delete_succeeds=True, deleted_after_delete=False
        )
        repo = _MemSessionRepo()
        session = _make_session(namespace="lab-abc123")
        repo.create(session)
        svc, _ = _make_svc(session_repo=repo, ns_lifecycle=adapter)
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED

    def test_delete_failure_marks_vm_tainted(self):
        """delete_namespace failure triggers mark_vm_tainted."""
        tracker = _RecordingVMTracker()
        adapter = StubNamespaceLifecycleAdapter(delete_succeeds=False)
        repo = _MemSessionRepo()
        session = _make_session(vm_id="vm-501", namespace="lab-abc123")
        repo.create(session)
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo(),
            vm_tracker=tracker,
            ns_lifecycle=adapter,
            image_resolver=_StubImageResolver(),
        )
        svc.run_cleanup(session.session_id)
        assert "vm-501" in tracker.tainted

    def test_namespace_not_deleted_marks_vm_tainted(self):
        """is_namespace_deleted=False also triggers mark_vm_tainted."""
        tracker = _RecordingVMTracker()
        adapter = StubNamespaceLifecycleAdapter(
            delete_succeeds=True, deleted_after_delete=False
        )
        repo = _MemSessionRepo()
        session = _make_session(vm_id="vm-502", namespace="lab-abc123")
        repo.create(session)
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo(),
            vm_tracker=tracker,
            ns_lifecycle=adapter,
            image_resolver=_StubImageResolver(),
        )
        svc.run_cleanup(session.session_id)
        assert "vm-502" in tracker.tainted

    def test_delete_exception_results_in_cleanup_failed(self):
        """Exception during delete_namespace is caught → LAB_CLEANUP_FAILED."""
        repo = _MemSessionRepo()
        session = _make_session(namespace="lab-abc123")
        repo.create(session)
        svc, _ = _make_svc(session_repo=repo, ns_lifecycle=_RaisingDeleteAdapter())
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED

    def test_successful_cleanup_does_not_mark_vm_tainted(self):
        """Clean delete path must NOT call mark_vm_tainted."""
        tracker = _RecordingVMTracker()
        adapter = StubNamespaceLifecycleAdapter()  # default: all succeeds
        repo = _MemSessionRepo()
        session = _make_session(vm_id="vm-503", namespace="lab-abc123")
        repo.create(session)
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo(),
            vm_tracker=tracker,
            ns_lifecycle=adapter,
            image_resolver=_StubImageResolver(),
        )
        result = svc.run_cleanup(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert "vm-503" not in tracker.tainted

    # ------------------------------------------------------------------
    # Verifier kubeconfig separation (structural, not integration)
    # ------------------------------------------------------------------

    def test_k3s_adapter_requires_config(self):
        """K3sNamespaceLifecycleAdapter requires K8sAdapterConfig — no-arg construction forbidden."""
        from backend.labgen.namespace_lifecycle import K3sNamespaceLifecycleAdapter, K8sAdapterConfig, NamespaceAdapterConfigError
        # Must pass a valid K8sAdapterConfig — cannot construct without config
        with pytest.raises(TypeError):
            K3sNamespaceLifecycleAdapter()  # type: ignore[call-arg]
        # With invalid config, NamespaceAdapterConfigError is raised at config construction
        with pytest.raises(NamespaceAdapterConfigError):
            K8sAdapterConfig(kubeconfig_path="", in_cluster=False)


# ===========================================================================
# Stub rolebinding behaviour
# ===========================================================================


class TestNamespaceLifecycleStubRolebinding:
    """StubNamespaceLifecycleAdapter rolebinding methods."""

    def test_rolebinding_succeeds_by_default(self):
        adapter = StubNamespaceLifecycleAdapter()
        assert adapter.ensure_verifier_rolebinding("lab-abc") is True

    def test_rolebinding_records_namespace(self):
        adapter = StubNamespaceLifecycleAdapter()
        adapter.ensure_verifier_rolebinding("lab-abc")
        assert "lab-abc" in adapter.rolebindings_created

    def test_rolebinding_failure_configured(self):
        adapter = StubNamespaceLifecycleAdapter(rolebinding_succeeds=False)
        assert adapter.ensure_verifier_rolebinding("lab-abc") is False

    def test_rolebinding_failure_does_not_record_namespace(self):
        adapter = StubNamespaceLifecycleAdapter(rolebinding_succeeds=False)
        adapter.ensure_verifier_rolebinding("lab-abc")
        assert adapter.rolebindings_created == []

    def test_rolebinding_exists_true_by_default(self):
        adapter = StubNamespaceLifecycleAdapter()
        assert adapter.verifier_rolebinding_exists("lab-abc") is True

    def test_rolebinding_exists_false_configured(self):
        adapter = StubNamespaceLifecycleAdapter(rolebinding_exists_after_create=False)
        assert adapter.verifier_rolebinding_exists("lab-abc") is False

    def test_rolebindings_created_starts_empty(self):
        adapter = StubNamespaceLifecycleAdapter()
        assert adapter.rolebindings_created == []

    def test_multiple_rolebindings_recorded(self):
        adapter = StubNamespaceLifecycleAdapter()
        adapter.ensure_verifier_rolebinding("lab-aaa")
        adapter.ensure_verifier_rolebinding("lab-bbb")
        assert adapter.rolebindings_created == ["lab-aaa", "lab-bbb"]


# ===========================================================================
# Lab Session Verifier RoleBinding integration
# ===========================================================================


class TestLabSessionVerifierRolebinding:
    """Verifier RoleBinding creation during session start flow."""

    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_success_path_reaches_lab_active(self):
        """All namespace + rolebinding steps pass → LAB_ACTIVE."""
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft})
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_rolebinding_called_after_namespace_verified(self):
        """ensure_verifier_rolebinding is called after namespace_exists returns True."""
        adapter = StubNamespaceLifecycleAdapter()
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert len(adapter.rolebindings_created) == 1

    def test_rolebinding_called_with_session_namespace(self):
        """ensure_verifier_rolebinding receives the same namespace as create_namespace."""
        adapter = StubNamespaceLifecycleAdapter()
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert adapter.rolebindings_created[0] == f"lab-{session.session_id}"

    def test_rolebinding_not_called_when_namespace_create_fails(self):
        """Short-circuit: rolebinding must not be called if namespace create fails."""
        adapter = StubNamespaceLifecycleAdapter(create_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        svc.create_session(draft.lab_id, "vm-500", "student1")
        assert adapter.rolebindings_created == []

    def test_rolebinding_not_called_when_namespace_exists_fails(self):
        """Short-circuit: rolebinding must not be called if namespace_exists returns False."""
        adapter = StubNamespaceLifecycleAdapter(
            create_succeeds=True, exists_after_create=False
        )
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        svc.create_session(draft.lab_id, "vm-500", "student1")
        assert adapter.rolebindings_created == []

    # ------------------------------------------------------------------
    # RoleBinding create failure
    # ------------------------------------------------------------------

    def test_rolebinding_create_failure_returns_lab_start_failed(self):
        """ensure_verifier_rolebinding returns False → LAB_START_FAILED."""
        adapter = StubNamespaceLifecycleAdapter(rolebinding_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED

    def test_rolebinding_create_failure_reason(self):
        """failure_reason is verifier_rolebinding_create_failed when ensure returns False."""
        adapter = StubNamespaceLifecycleAdapter(rolebinding_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.failure_reason == "verifier_rolebinding_create_failed"

    def test_rolebinding_create_failure_not_lab_active(self):
        """RoleBinding failure must not produce LAB_ACTIVE."""
        adapter = StubNamespaceLifecycleAdapter(rolebinding_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status != LabSessionStatus.LAB_ACTIVE

    def test_rolebinding_create_failure_session_persisted(self):
        """LAB_START_FAILED (rolebinding create) session is stored in the repository."""
        repo = _MemSessionRepo()
        adapter = StubNamespaceLifecycleAdapter(rolebinding_succeeds=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, session_repo=repo, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        stored = repo.get(session.session_id)
        assert stored is not None
        assert stored.lab_session_status == LabSessionStatus.LAB_START_FAILED

    def test_rolebinding_create_exception_returns_lab_start_failed(self):
        """Exception from ensure_verifier_rolebinding is caught → LAB_START_FAILED."""

        class _RaisingRolebindingAdapter(StubNamespaceLifecycleAdapter):
            def ensure_verifier_rolebinding(self, namespace: str) -> bool:
                raise RuntimeError("kubectl apply failed")

        adapter = _RaisingRolebindingAdapter()
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "verifier_rolebinding_create_failed"

    # ------------------------------------------------------------------
    # RoleBinding verify failure
    # ------------------------------------------------------------------

    def test_rolebinding_verify_failure_returns_lab_start_failed(self):
        """verifier_rolebinding_exists returns False → LAB_START_FAILED."""
        adapter = StubNamespaceLifecycleAdapter(rolebinding_exists_after_create=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED

    def test_rolebinding_verify_failure_reason(self):
        """failure_reason is verifier_rolebinding_verify_failed when exists returns False."""
        adapter = StubNamespaceLifecycleAdapter(rolebinding_exists_after_create=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.failure_reason == "verifier_rolebinding_verify_failed"

    def test_rolebinding_verify_failure_not_lab_active(self):
        """RoleBinding verify failure must not produce LAB_ACTIVE."""
        adapter = StubNamespaceLifecycleAdapter(rolebinding_exists_after_create=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status != LabSessionStatus.LAB_ACTIVE

    def test_rolebinding_verify_exception_returns_lab_start_failed(self):
        """Exception from verifier_rolebinding_exists is caught → LAB_START_FAILED."""

        class _RaisingExistsAdapter(StubNamespaceLifecycleAdapter):
            def verifier_rolebinding_exists(self, namespace: str) -> bool:
                raise RuntimeError("kubectl get failed")

        adapter = _RaisingExistsAdapter()
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == "verifier_rolebinding_verify_failed"

    def test_rolebinding_verify_failure_session_persisted(self):
        """LAB_START_FAILED (rolebinding verify) session is stored in the repository."""
        repo = _MemSessionRepo()
        adapter = StubNamespaceLifecycleAdapter(rolebinding_exists_after_create=False)
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, session_repo=repo, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        stored = repo.get(session.session_id)
        assert stored is not None
        assert stored.lab_session_status == LabSessionStatus.LAB_START_FAILED

    # ------------------------------------------------------------------
    # No ClusterRoleBinding (structural: only namespace-scoped binding)
    # ------------------------------------------------------------------

    def test_verifier_binding_creating_in_active_states(self):
        """VERIFIER_BINDING_CREATING is in _ACTIVE_STATES (blocks duplicate session)."""
        from backend.labgen.lab_session_service import _ACTIVE_STATES
        assert LabSessionStatus.VERIFIER_BINDING_CREATING in _ACTIVE_STATES

    def test_rolebinding_called_with_lab_namespace_not_kube_system(self):
        """RoleBinding must be scoped to the lab namespace, not kube-system."""
        adapter = StubNamespaceLifecycleAdapter()
        draft = _make_published_draft()
        svc, _ = _make_svc(drafts={draft.lab_id: draft}, ns_lifecycle=adapter)
        session = svc.create_session(draft.lab_id, "vm-500", "student1")
        assert adapter.rolebindings_created[0].startswith("lab-")
        assert "kube-system" not in adapter.rolebindings_created[0]
