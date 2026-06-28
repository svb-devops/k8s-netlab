"""
Regression tests for namespace str | None type safety.

Validates:
  - lab_session_service sets session.namespace to a typed str before calling lifecycle methods
  - runtime_precheck ignores sessions with namespace=None (no crash)
  - namespace=None sessions in precheck do not block or crash
  - lab session namespace is always "lab-{session_id}" format
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from backend.labgen.lab_session_service import (
    LabSessionService,
    StubVMTracker,
)
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    Step,
)
from backend.labgen.namespace_lifecycle import (
    NamespaceLifecyclePort,
    StubNamespaceLifecycleAdapter,
)
from backend.labgen.runtime_precheck import RuntimePrecheckService

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Type Safety Lab",
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
        vm_id="500",
        student_username="student1",
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
        namespace="lab-test-ns",
    )
    defaults.update(kw)
    return LabSessionState(**defaults)


class _MemSessionRepo:
    def __init__(self, sessions: list[LabSessionState] | None = None) -> None:
        self._store: dict[str, LabSessionState] = {s.session_id: s for s in (sessions or [])}

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

    def list_by_vm_id(self, vm_id: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.vm_id == vm_id]


class _MemDraftRepo:
    def __init__(self, drafts: dict[str, LabDraft] | None = None) -> None:
        self._store: dict[str, LabDraft] = dict(drafts or {})

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft


class _StubImageResolver:
    def needs_recheck(self, img: str) -> bool:
        return False

    def check_registry_existence(self, img: str) -> str:
        return img


def _make_service(
    draft: LabDraft,
    sessions: list[LabSessionState] | None = None,
    ns_adapter: Optional[NamespaceLifecyclePort] = None,
) -> LabSessionService:
    draft_repo = _MemDraftRepo({draft.lab_id: draft})
    session_repo = _MemSessionRepo(sessions or [])
    # StubVMTracker always reports vm_exists=True and is_vm_owned_by=True
    vm_tracker = StubVMTracker()
    return LabSessionService(
        draft_repo=draft_repo,
        session_repo=session_repo,
        vm_tracker=vm_tracker,
        ns_lifecycle=ns_adapter or StubNamespaceLifecycleAdapter(),
        image_resolver=_StubImageResolver(),
    )


def _make_precheck_service(
    sessions: list[LabSessionState] | None = None,
    ns_adapter: Optional[NamespaceLifecyclePort] = None,
    threshold: int = 300,
) -> RuntimePrecheckService:
    draft_repo = _MemDraftRepo()
    session_repo = _MemSessionRepo(sessions or [])
    return RuntimePrecheckService(
        ns_lifecycle=ns_adapter or StubNamespaceLifecycleAdapter(),
        session_repo=session_repo,
        draft_repo=draft_repo,
        terminating_threshold_seconds=threshold,
    )


# ---------------------------------------------------------------------------
# Tests: namespace is always str after session creation
# ---------------------------------------------------------------------------


class TestNamespaceIsStrAfterCreate:
    def test_session_namespace_is_set_to_str(self) -> None:
        """Created session must have namespace as str, not None."""
        draft = _make_draft()
        svc = _make_service(draft)
        session = svc.create_session(draft.lab_id, "500", "student1")
        assert session.namespace is not None
        assert isinstance(session.namespace, str)

    def test_session_namespace_format_is_lab_prefixed(self) -> None:
        """Namespace must be lab-{session_id}."""
        draft = _make_draft()
        svc = _make_service(draft)
        session = svc.create_session(draft.lab_id, "500", "student1")
        assert session.namespace is not None
        assert session.namespace == f"lab-{session.session_id}"

    def test_namespace_passed_to_create_matches_session_namespace(self) -> None:
        """NamespaceLifecyclePort.create_namespace is called with session's own namespace."""
        draft = _make_draft()
        called_with: list[str] = []

        class _CapturingAdapter(StubNamespaceLifecycleAdapter):
            def create_namespace(self, ns: str) -> bool:
                called_with.append(ns)
                return True

        svc = _make_service(draft, ns_adapter=_CapturingAdapter())
        session = svc.create_session(draft.lab_id, "500", "student1")
        assert len(called_with) == 1
        assert called_with[0] == session.namespace
        assert isinstance(called_with[0], str)

    def test_namespace_exists_called_with_str_not_none(self) -> None:
        """namespace_exists must never be called with None."""
        draft = _make_draft()
        received_ns: list[Optional[str]] = []

        class _CapturingAdapter(StubNamespaceLifecycleAdapter):
            def namespace_exists(self, ns: str) -> bool:
                received_ns.append(ns)
                return True

        svc = _make_service(draft, ns_adapter=_CapturingAdapter())
        svc.create_session(draft.lab_id, "500", "student1")
        assert len(received_ns) == 1
        assert received_ns[0] is not None
        assert isinstance(received_ns[0], str)


# ---------------------------------------------------------------------------
# Tests: runtime_precheck handles sessions with namespace=None
# ---------------------------------------------------------------------------


class _TrackingNamespaceAdapter(StubNamespaceLifecycleAdapter):
    """StubNamespaceLifecycleAdapter that records all namespace args passed to it."""

    def __init__(self, stuck_namespaces: set[str] | None = None) -> None:
        super().__init__()
        self._stuck = stuck_namespaces or set()
        self.stuck_calls: list[str] = []

    def is_namespace_stuck_terminating(self, namespace: str, threshold_seconds: int = 300) -> bool:
        self.stuck_calls.append(namespace)
        return namespace in self._stuck


class TestPrecheckIgnoresNoneNamespaceSessions:
    def test_no_crash_when_existing_session_has_none_namespace(self) -> None:
        """Condition 4 precheck must not crash when prior session has namespace=None."""
        prior_session = _make_session(
            vm_id="500",
            namespace=None,
            lab_session_status=LabSessionStatus.LAB_START_FAILED,
        )
        adapter = _TrackingNamespaceAdapter()
        svc = _make_precheck_service(sessions=[prior_session], ns_adapter=adapter)
        # Should not crash — sessions with namespace=None are filtered
        svc.check(vm_id="500", student_username="new_student")
        # is_namespace_stuck_terminating must NEVER be called with None
        for ns in adapter.stuck_calls:
            assert ns is not None, "namespace must not be None when passed to lifecycle port"

    def test_no_crash_when_all_sessions_have_none_namespace(self) -> None:
        """When all prior sessions have namespace=None, no stuck-terminating check is made."""
        sessions = [
            _make_session(vm_id="500", namespace=None, lab_session_status=LabSessionStatus.LAB_START_FAILED),
            _make_session(vm_id="500", namespace=None, lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED),
        ]
        adapter = _TrackingNamespaceAdapter()
        svc = _make_precheck_service(sessions=sessions, ns_adapter=adapter)
        svc.check(vm_id="500", student_username="new_student")
        # No namespace_stuck check should be made for None namespaces
        assert adapter.stuck_calls == []

    def test_sessions_with_namespace_still_checked(self) -> None:
        """Sessions with non-None namespace are still checked for stuck termination."""
        stuck_session = _make_session(
            vm_id="500",
            namespace="lab-stuck-ns",
            lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED,
        )
        adapter = _TrackingNamespaceAdapter(stuck_namespaces={"lab-stuck-ns"})
        svc = _make_precheck_service(sessions=[stuck_session], ns_adapter=adapter)
        result = svc.check(vm_id="500", student_username="new_student")
        assert len(adapter.stuck_calls) >= 1
        assert adapter.stuck_calls[0] == "lab-stuck-ns"
        assert isinstance(adapter.stuck_calls[0], str)

    def test_mixed_none_and_valid_namespaces_only_checks_valid(self) -> None:
        """When sessions mix None and non-None namespaces, only valid ones are checked."""
        sessions = [
            _make_session(vm_id="500", namespace=None, lab_session_status=LabSessionStatus.LAB_START_FAILED),
            _make_session(vm_id="500", namespace="lab-valid-ns", lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED),
        ]
        adapter = _TrackingNamespaceAdapter()
        svc = _make_precheck_service(sessions=sessions, ns_adapter=adapter)
        svc.check(vm_id="500", student_username="new_student")
        # All recorded calls must be non-None
        for ns in adapter.stuck_calls:
            assert ns is not None
        # None-namespace session must have been skipped
        assert None not in adapter.stuck_calls
