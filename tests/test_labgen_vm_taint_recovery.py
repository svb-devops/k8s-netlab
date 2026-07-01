"""
VM Taint & Cleanup Failure Recovery Policy tests.

Validates:
  - cleanup failure sets failure_reason + cleanup_verified=False
  - cleanup success sets cleanup_verified=True, no taint
  - mark_vm_tainted not called twice (run_cleanup idempotent on terminal states)
  - tainted VM precheck returns precheck.vm_tainted
  - tainted VM create_session raises PrecheckFailed — no namespace creation
  - tainted VM HTTP create returns 422
  - StubVMTracker taint lifecycle
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.labgen.lab_session_service import (
    LabSessionService,
    PrecheckFailed,
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
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Taint Test Lab",
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
    def __init__(self, drafts: dict[str, LabDraft] | None = None) -> None:
        self._store: dict[str, LabDraft] = dict(drafts or {})

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft


class _RecordingNamespaceAdapter(NamespaceLifecyclePort):
    """Records calls to namespace lifecycle methods."""

    def __init__(self, delete_succeeds: bool = True) -> None:
        self.create_calls: list[str] = []
        self.delete_calls: list[str] = []
        self._delete_succeeds = delete_succeeds

    def create_namespace(self, ns: str) -> bool:
        self.create_calls.append(ns)
        return True

    def namespace_exists(self, ns: str) -> bool:
        return True

    def delete_namespace(self, ns: str) -> bool:
        self.delete_calls.append(ns)
        return self._delete_succeeds

    def is_namespace_deleted(self, ns: str) -> bool:
        return self._delete_succeeds

    def ensure_verifier_rolebinding(self, ns: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, ns: str) -> bool:
        return True


class _RecordingVMTracker(VMTrackerPort):
    """Records taint calls; configurable per-VM taint state."""

    def __init__(self, pre_tainted: set[str] | None = None) -> None:
        self._tainted: set[str] = set(pre_tainted or set())
        self.mark_calls: list[str] = []

    def vm_exists(self, vm_id: str) -> bool:
        return True

    def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
        return True

    def mark_vm_tainted(self, vm_id: str) -> None:
        self._tainted.add(vm_id)
        self.mark_calls.append(vm_id)

    def is_vm_tainted(self, vm_id: str) -> bool:
        return vm_id in self._tainted


class _StubImageResolver:
    def needs_recheck(self, img) -> bool:
        return False

    def check_registry_existence(self, img):
        return img


def _make_svc(
    session_repo: _MemSessionRepo,
    ns_lifecycle: NamespaceLifecyclePort | None = None,
    vm_tracker: VMTrackerPort | None = None,
    drafts: dict[str, LabDraft] | None = None,
) -> LabSessionService:
    return LabSessionService(
        session_repo=session_repo,
        draft_repo=_MemDraftRepo(drafts),
        vm_tracker=vm_tracker or _RecordingVMTracker(),
        ns_lifecycle=ns_lifecycle or StubNamespaceLifecycleAdapter(),
        image_resolver=_StubImageResolver(),
    )


# ---------------------------------------------------------------------------
# cleanup failure/success fields
# ---------------------------------------------------------------------------


class TestCleanupFieldsOnFailure:
    def test_failure_sets_failure_reason(self):
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo, ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=False))
        result = svc.abort_session(session.session_id)
        assert result.failure_reason == "namespace_cleanup_failed"

    def test_failure_sets_cleanup_verified_false(self):
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo, ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=False))
        result = svc.abort_session(session.session_id)
        assert result.cleanup_verified is False

    def test_failure_status_is_cleanup_failed(self):
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo, ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=False))
        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED


class TestCleanupFieldsOnSuccess:
    def test_success_sets_cleanup_verified_true(self):
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo, ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=True))
        result = svc.abort_session(session.session_id)
        assert result.cleanup_verified is True

    def test_success_status_is_closed(self):
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_success_does_not_mark_vm_tainted(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo, vm_tracker=tracker, ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=True))
        svc.abort_session(session.session_id)
        assert tracker.mark_calls == []

    def test_success_no_failure_reason(self):
        repo = _MemSessionRepo()
        session = _make_session()
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.abort_session(session.session_id)
        assert result.failure_reason is None

    def test_no_namespace_session_closes_with_cleanup_verified(self):
        repo = _MemSessionRepo()
        session = _make_session(namespace=None)
        repo.create(session)
        svc = _make_svc(repo)
        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert result.cleanup_verified is True


# ---------------------------------------------------------------------------
# mark_vm_tainted idempotency
# ---------------------------------------------------------------------------


class TestMarkVMTaintedIdempotency:
    def test_run_cleanup_on_cleanup_failed_does_not_re_taint(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker()
        session = _make_session(
            lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED,
            failure_reason="namespace_cleanup_failed",
        )
        repo.create(session)
        svc = _make_svc(
            repo,
            ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=False),
            vm_tracker=tracker,
        )
        svc.run_cleanup(session.session_id)
        # LAB_CLEANUP_FAILED is in _TERMINAL_STATES → early return, no taint call
        assert tracker.mark_calls == []

    def test_run_cleanup_on_lab_closed_is_idempotent(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker()
        session = _make_session(lab_session_status=LabSessionStatus.LAB_CLOSED)
        repo.create(session)
        svc = _make_svc(repo, vm_tracker=tracker)
        svc.run_cleanup(session.session_id)
        assert tracker.mark_calls == []

    def test_mark_vm_tainted_called_exactly_once_per_cleanup_failure(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker()
        session = _make_session(vm_id="vm-503")
        repo.create(session)
        svc = _make_svc(
            repo,
            ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=False),
            vm_tracker=tracker,
        )
        svc.abort_session(session.session_id)
        assert tracker.mark_calls.count("vm-503") == 1


# ---------------------------------------------------------------------------
# Tainted VM precheck
# ---------------------------------------------------------------------------


class TestTaintedVMPrecheck:
    def test_tainted_vm_precheck_fails_with_vm_tainted(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker(pre_tainted={"vm-500"})
        draft = _make_draft()
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({draft.lab_id: draft}),
            vm_tracker=tracker,
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
        
        )
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert not result.passed
        assert "precheck.vm_tainted" in result.failures

    def test_tainted_vm_create_session_raises_precheck_failed(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker(pre_tainted={"vm-500"})
        draft = _make_draft()
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({draft.lab_id: draft}),
            vm_tracker=tracker,
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
        
        )
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_session(draft.lab_id, "vm-500", "student1")
        assert "precheck.vm_tainted" in exc_info.value.failures

    def test_tainted_vm_does_not_create_namespace(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker(pre_tainted={"vm-500"})
        ns = _RecordingNamespaceAdapter()
        draft = _make_draft()
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({draft.lab_id: draft}),
            vm_tracker=tracker,
            ns_lifecycle=ns,
            image_resolver=_StubImageResolver(),
        
        )
        with pytest.raises(PrecheckFailed):
            svc.create_session(draft.lab_id, "vm-500", "student1")
        assert ns.create_calls == []

    def test_non_tainted_vm_precheck_passes(self):
        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker(pre_tainted=set())
        draft = _make_draft()
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({draft.lab_id: draft}),
            vm_tracker=tracker,
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
        
        )
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert result.passed
        assert "precheck.vm_tainted" not in result.failures

    def test_tainted_vm_http_create_returns_422(self):
        from backend.main import app
        from backend.auth_deps import get_current_user

        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker(pre_tainted={"vm-500"})
        draft = _make_draft()
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({draft.lab_id: draft}),
            vm_tracker=tracker,
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
        
        )
        app.dependency_overrides[get_session_repository] = lambda: repo
        app.dependency_overrides[get_session_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: "student1"
        try:
            client = TestClient(app, raise_server_exceptions=True)
            with patch("backend.labgen.routes.config.LABGEN_ENABLED_LAB_IDS", frozenset({draft.lab_id})):
                r = client.post(
                    "/api/lab-sessions",
                    json={"lab_id": draft.lab_id, "vm_id": "vm-500"},
                )
            assert r.status_code == 422
            failures = r.json()["detail"]["precheck_failures"]
            assert "precheck.vm_tainted" in failures
        finally:
            app.dependency_overrides.clear()

    def test_tainted_vm_http_create_no_session_created(self):
        from backend.main import app
        from backend.auth_deps import get_current_user

        repo = _MemSessionRepo()
        tracker = _RecordingVMTracker(pre_tainted={"vm-500"})
        draft = _make_draft()
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({draft.lab_id: draft}),
            vm_tracker=tracker,
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
        
        )
        app.dependency_overrides[get_session_repository] = lambda: repo
        app.dependency_overrides[get_session_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: "student1"
        try:
            client = TestClient(app, raise_server_exceptions=True)
            with patch("backend.labgen.routes.config.LABGEN_ENABLED_LAB_IDS", frozenset({draft.lab_id})):
                client.post(
                    "/api/lab-sessions",
                    json={"lab_id": draft.lab_id, "vm_id": "vm-500"},
                )
            # No session was persisted
            assert len(repo._store) == 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# StubVMTracker taint lifecycle
# ---------------------------------------------------------------------------


class TestStubVMTrackerTaintLifecycle:
    def test_new_stub_tracker_is_not_tainted(self):
        tracker = StubVMTracker()
        assert tracker.is_vm_tainted("vm-500") is False

    def test_mark_then_check_returns_true(self):
        tracker = StubVMTracker()
        tracker.mark_vm_tainted("vm-501")
        assert tracker.is_vm_tainted("vm-501") is True

    def test_taint_is_scoped_to_vm_id(self):
        tracker = StubVMTracker()
        tracker.mark_vm_tainted("vm-501")
        assert tracker.is_vm_tainted("vm-502") is False

    def test_double_mark_is_idempotent(self):
        tracker = StubVMTracker()
        tracker.mark_vm_tainted("vm-501")
        tracker.mark_vm_tainted("vm-501")
        assert tracker.is_vm_tainted("vm-501") is True

    def test_distinct_instances_are_isolated(self):
        t1 = StubVMTracker()
        t2 = StubVMTracker()
        t1.mark_vm_tainted("vm-501")
        assert t2.is_vm_tainted("vm-501") is False
