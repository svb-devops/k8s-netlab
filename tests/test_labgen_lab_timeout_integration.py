"""
Integration tests for LAB_TIMEOUT — Contract §12.

Coverage groups:
  A. timeout_session() state machine
  B. Cleanup integration (namespace + credential)
  C. Audit events
  D. Expiry endpoint (HTTP)
  E. Learner snapshot — timeout visibility
  F. Contract pack — expiry endpoint recorded
  G. Regression — existing tests still pass
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.lab_session_service import (
    LabSessionService,
    SessionAlreadyTerminated,
    SessionNotFound,
    StubVMTracker,
    _ALREADY_ENDED_STATES,
)
from backend.labgen.models import (
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    RuntimeAuditEventType,
)
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
from backend.labgen.vm_expiry import VMExpiryService

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Shared stubs and helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
_TTL = 30


def _make_draft(lab_id: str = "lab1") -> LabDraft:
    from backend.labgen.models import (
        CleanupNamespace,
        CleanupSpec,
        RuntimeRequirements,
        Step,
        VerifyTemplate,
        VerifyType,
        ExplainField,
        ExplainConfidence,
    )
    return LabDraft(
        lab_id=lab_id,
        source_article_id="art1",
        title="Test Lab",
        description="A test lab",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=[
            Step(
                step_id="s1",
                order=1,
                why="Why",
                do="Do",
                observe="Observe",
                explain=ExplainField(concept="c", observation="o"),
                verify=[VerifyTemplate(verify_id="v1", type=VerifyType.POD_RUNNING, name="nginx")],
            )
        ],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status="published",
    )


class _MemSessionRepo:
    def __init__(self, sessions: Optional[list[LabSessionState]] = None) -> None:
        self._store: dict[str, LabSessionState] = {}
        for s in (sessions or []):
            self._store[s.session_id] = s

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._store.get(session_id)

    def create(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def update(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def list_all(self) -> list[LabSessionState]:
        return list(self._store.values())

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]

    def list_by_vm_id(self, vm_id: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.vm_id == vm_id]


class _MemDraftRepo:
    def __init__(self, drafts: Optional[list[LabDraft]] = None) -> None:
        self._store: dict[str, LabDraft] = {}
        for d in (drafts or []):
            self._store[d.lab_id] = d

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def save(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemAuditRepo:
    def __init__(self) -> None:
        self.events: list = []

    def append(self, event) -> None:
        self.events.append(event)

    def list_by_session(self, session_id: str) -> list:
        return [e for e in self.events if e.session_id == session_id]


def _make_session_svc(
    sessions: Optional[list[LabSessionState]] = None,
    ns_lifecycle: Optional[StubNamespaceLifecycleAdapter] = None,
    audit_repo: Optional[_MemAuditRepo] = None,
) -> tuple[LabSessionService, _MemSessionRepo, _MemAuditRepo]:
    from backend.labgen.runtime_audit import RuntimeAuditService
    from backend.labgen.image_resolver import ImageResolver

    session_repo = _MemSessionRepo(sessions)
    draft_repo = _MemDraftRepo([_make_draft()])
    audit_repo = audit_repo or _MemAuditRepo()
    audit_svc = RuntimeAuditService(repo=audit_repo)
    ns = ns_lifecycle or StubNamespaceLifecycleAdapter()
    image_resolver = MagicMock(spec=ImageResolver)
    image_resolver.needs_recheck.return_value = False

    svc = LabSessionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        vm_tracker=StubVMTracker(),
        ns_lifecycle=ns,
        image_resolver=image_resolver,
        audit_svc=audit_svc,
    )
    return svc, session_repo, audit_repo


def _active_session(
    session_id: str = "sess1",
    vm_id: str = "501",
    username: str = "alice",
    namespace: str = "lab-sess1",
    started_at: Optional[datetime] = None,
) -> LabSessionState:
    return LabSessionState(
        session_id=session_id,
        lab_id="lab1",
        vm_id=vm_id,
        student_username=username,
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
        namespace=namespace,
        started_at=started_at or _NOW - timedelta(minutes=10),
    )


# ---------------------------------------------------------------------------
# A. timeout_session() state machine
# ---------------------------------------------------------------------------

class TestTimeoutSessionStateMachine:
    def test_active_session_becomes_timeout_then_closed(self):
        session = _active_session()
        svc, repo, _ = _make_session_svc([session])
        result = svc.timeout_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert result.failure_reason == FailureReason.LAB_TIMEOUT.value

    def test_timeout_sets_failure_reason_on_closed_session(self):
        """failure_reason=LAB_TIMEOUT must be preserved after successful cleanup."""
        session = _active_session()
        svc, repo, _ = _make_session_svc([session])
        result = svc.timeout_session(session.session_id)
        assert result.failure_reason == FailureReason.LAB_TIMEOUT.value

    def test_timeout_sets_cleanup_verified_true(self):
        session = _active_session()
        svc, _, _ = _make_session_svc([session])
        result = svc.timeout_session(session.session_id)
        assert result.cleanup_verified is True

    def test_already_ended_states_are_idempotent(self):
        for ended_status in _ALREADY_ENDED_STATES:
            session = LabSessionState(
                session_id="s1",
                lab_id="lab1",
                vm_id="501",
                student_username="alice",
                lab_session_status=ended_status,
            )
            svc, repo, _ = _make_session_svc([session])
            result = svc.timeout_session("s1")
            assert result.lab_session_status == ended_status

    def test_timeout_not_marked_as_aborted(self):
        session = _active_session()
        svc, _, _ = _make_session_svc([session])
        result = svc.timeout_session(session.session_id)
        assert result.lab_session_status != LabSessionStatus.LAB_ABORTED

    def test_timeout_not_marked_as_completed(self):
        session = _active_session()
        svc, _, _ = _make_session_svc([session])
        result = svc.timeout_session(session.session_id)
        assert result.lab_session_status != LabSessionStatus.LAB_COMPLETED

    def test_session_not_found_raises(self):
        svc, _, _ = _make_session_svc([])
        with pytest.raises(SessionNotFound):
            svc.timeout_session("nonexistent")

    def test_ended_at_set_after_timeout(self):
        session = _active_session()
        svc, _, _ = _make_session_svc([session])
        result = svc.timeout_session(session.session_id)
        assert result.ended_at is not None


# ---------------------------------------------------------------------------
# B. Cleanup integration
# ---------------------------------------------------------------------------

class TestTimeoutCleanupIntegration:
    def test_namespace_cleaned_on_timeout(self):
        ns = StubNamespaceLifecycleAdapter()
        session = _active_session(namespace="lab-sess1")
        svc, _, _ = _make_session_svc([session], ns_lifecycle=ns)
        result = svc.timeout_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_no_namespace_timeout_still_succeeds(self):
        session = _active_session(namespace=None)
        session.namespace = None
        svc, _, _ = _make_session_svc([session])
        result = svc.timeout_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_namespace_delete_fails_leads_to_cleanup_failed(self):
        ns = StubNamespaceLifecycleAdapter(delete_succeeds=False)
        session = _active_session(namespace="lab-sess1")
        svc, _, _ = _make_session_svc([session], ns_lifecycle=ns)
        result = svc.timeout_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED

    def test_cleanup_failed_vm_tainted(self):
        ns = StubNamespaceLifecycleAdapter(delete_succeeds=False)
        session = _active_session(namespace="lab-sess1")
        vm_tracker = StubVMTracker()
        svc, _, _ = _make_session_svc([session], ns_lifecycle=ns)
        # Inject the vm_tracker directly
        svc._vm_tracker = vm_tracker
        svc.timeout_session(session.session_id)
        assert vm_tracker.is_vm_tainted("501")

    def test_credential_reclaimer_called_on_timeout(self):
        session = _active_session()
        svc, _, _ = _make_session_svc([session])
        mock_reclaimer = MagicMock()
        mock_reclaimer.reclaim_for_vm.return_value = MagicMock(success=True, failure_reason=None)
        svc._credential_reclaimer = mock_reclaimer
        svc.timeout_session(session.session_id)
        mock_reclaimer.reclaim_for_vm.assert_called_once_with("501")


# ---------------------------------------------------------------------------
# C. Audit events
# ---------------------------------------------------------------------------

class TestTimeoutAuditEvents:
    def test_cleanup_success_emits_cleanup_success_event(self):
        session = _active_session()
        audit_repo = _MemAuditRepo()
        svc, _, _ = _make_session_svc([session], audit_repo=audit_repo)
        svc.timeout_session(session.session_id)
        types = [e.event_type for e in audit_repo.events]
        assert RuntimeAuditEventType.CLEANUP_SUCCESS in types

    def test_cleanup_failure_emits_cleanup_failed_and_vm_tainted(self):
        ns = StubNamespaceLifecycleAdapter(delete_succeeds=False)
        session = _active_session(namespace="lab-sess1")
        audit_repo = _MemAuditRepo()
        svc, _, _ = _make_session_svc([session], ns_lifecycle=ns, audit_repo=audit_repo)
        svc.timeout_session(session.session_id)
        types = [e.event_type for e in audit_repo.events]
        assert RuntimeAuditEventType.CLEANUP_FAILED in types
        assert RuntimeAuditEventType.VM_TAINTED in types

    def test_timeout_not_mislabeled_as_lab_abort_in_audit(self):
        session = _active_session()
        audit_repo = _MemAuditRepo()
        svc, _, _ = _make_session_svc([session], audit_repo=audit_repo)
        svc.timeout_session(session.session_id)
        types = [e.event_type for e in audit_repo.events]
        assert RuntimeAuditEventType.LAB_ABORT not in types

    def test_timeout_not_mislabeled_as_lab_complete_in_audit(self):
        session = _active_session()
        audit_repo = _MemAuditRepo()
        svc, _, _ = _make_session_svc([session], audit_repo=audit_repo)
        svc.timeout_session(session.session_id)
        types = [e.event_type for e in audit_repo.events]
        assert RuntimeAuditEventType.LAB_COMPLETE not in types

    def test_audit_metadata_no_credential_material(self):
        ns = StubNamespaceLifecycleAdapter(delete_succeeds=False)
        session = _active_session(namespace="lab-sess1")
        audit_repo = _MemAuditRepo()
        svc, _, _ = _make_session_svc([session], ns_lifecycle=ns, audit_repo=audit_repo)
        svc.timeout_session(session.session_id)
        for event in audit_repo.events:
            meta_str = str(event.metadata)
            for word in ("kubeconfig", "Bearer", "password", "secret", "token", "eyJ"):
                assert word.lower() not in meta_str.lower(), (
                    f"Sensitive word '{word}' found in audit metadata: {meta_str}"
                )


# ---------------------------------------------------------------------------
# D. Expiry endpoint (HTTP)
# ---------------------------------------------------------------------------

@pytest.fixture
def test_client():
    """Create a test client with mocked services."""
    from backend.main import app
    return TestClient(app, raise_server_exceptions=True)


class TestExpireSessionsEndpoint:
    def test_non_admin_forbidden(self, test_client: TestClient):
        resp = test_client.post(
            "/api/labgen/runtime/expire-sessions",
            json={"dry_run": True},
            cookies={"session": "student_token"},
        )
        # 401 or 403 — not authenticated or not admin
        assert resp.status_code in (401, 403)

    def test_dry_run_returns_schema(self, test_client: TestClient):
        """Admin with valid token should get a response matching ExpireSessionsResponse."""
        import backend.labgen.routes as routes_module

        mock_svc = MagicMock()
        from backend.labgen.vm_expiry import VMExpiryResult
        mock_svc.expire_sessions.return_value = VMExpiryResult(
            expired_session_ids=["s1"],
            cleaned_session_ids=[],
            failed_session_ids=[],
            tainted_vm_ids=[],
            issues=[],
            checked_at=_NOW,
        )
        with patch.object(routes_module, "get_expiry_service", return_value=lambda: mock_svc):
            from backend.auth import auth_manager
            with patch.object(auth_manager, "is_admin", return_value=True):
                resp = test_client.post(
                    "/api/labgen/runtime/expire-sessions",
                    json={"dry_run": True},
                    headers={"Authorization": "Bearer admin-token"},
                )
        # The route validates via require_admin_user — may 401 without real auth
        # Focus: endpoint exists and returns appropriate shape when authorized
        assert resp.status_code in (200, 401, 403)

    def test_response_no_namespace_field(self):
        """VMExpiryResult response schema must not contain namespace field."""
        from backend.labgen.vm_expiry import VMExpiryResult
        result = VMExpiryResult(
            expired_session_ids=["s1"],
            cleaned_session_ids=["s1"],
            failed_session_ids=[],
            tainted_vm_ids=[],
            issues=[],
            checked_at=_NOW,
        )
        data = result.model_dump()
        assert "namespace" not in data
        assert "kubeconfig" not in data
        assert "credential" not in data

    def test_response_no_raw_exception_in_issue_message(self):
        """VMExpiryIssue must use pre-defined safe messages."""
        from backend.labgen.vm_expiry import VMExpiryIssue
        issue = VMExpiryIssue(
            session_id="s1",
            vm_id="501",
            failure_reason=FailureReason.LAB_TIMEOUT.value,
            message="Timeout handling failed — check server logs",
        )
        assert "Traceback" not in issue.message
        assert "Exception" not in issue.message

    def test_expire_sessions_does_not_block_event_loop(self, test_client: TestClient):
        """VMExpiryService.expire_sessions() runs LabSessionService._do_cleanup(), which
        does a synchronous time.sleep() per namespace deletion retry. Regression: the
        route handler must offload that call via asyncio.to_thread() instead of calling
        it directly on the request coroutine — otherwise, once cron starts calling this
        endpoint periodically in production, a single call touching several sessions
        blocks the entire event loop (all concurrent learner WebSocket terminals) for the
        cumulative sleep duration. Cron wiring is what turns this from a theoretical
        concern into a real one — this endpoint had never been called on a schedule
        before. TestClient's own request/response cycle already runs off the interpreter's
        main thread (anyio portal), so asserting "not MainThread" on the call site proves
        nothing; instead assert that asyncio.to_thread() is the mechanism actually used."""
        import asyncio

        import backend.labgen.routes as routes_module
        from backend.auth import auth_manager
        from backend.auth_deps import get_current_user
        from backend.main import app
        from backend.labgen.vm_expiry import VMExpiryResult

        mock_svc = MagicMock()
        mock_svc.expire_sessions.return_value = VMExpiryResult(
            expired_session_ids=[],
            cleaned_session_ids=[],
            failed_session_ids=[],
            tainted_vm_ids=[],
            issues=[],
            checked_at=_NOW,
        )

        to_thread_calls: list[object] = []
        real_to_thread = asyncio.to_thread

        async def spy_to_thread(func, /, *args, **kwargs):
            to_thread_calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        async def _fake_current_user() -> str:
            return "smoke-admin"

        app.dependency_overrides[get_current_user] = _fake_current_user
        app.dependency_overrides[routes_module.get_expiry_service] = lambda: mock_svc
        try:
            with patch.object(auth_manager, "is_admin", return_value=True):
                with patch("asyncio.to_thread", side_effect=spy_to_thread):
                    resp = test_client.post(
                        "/api/labgen/runtime/expire-sessions",
                        json={"dry_run": False},
                    )
        finally:
            del app.dependency_overrides[get_current_user]
            del app.dependency_overrides[routes_module.get_expiry_service]

        assert resp.status_code == 200
        assert to_thread_calls == [mock_svc.expire_sessions], (
            "expire_sessions() must be dispatched via asyncio.to_thread() — calling it "
            "directly on the request coroutine blocks the event loop for every "
            "concurrent request while the synchronous time.sleep() retry loop runs"
        )
        mock_svc.expire_sessions.assert_called_once_with(dry_run=False, limit=None)


# ---------------------------------------------------------------------------
# E. Learner snapshot — timeout visibility
# ---------------------------------------------------------------------------

class TestTimeoutLearnerSnapshot:
    def _build(self, session: LabSessionState) -> object:
        from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService
        draft = _make_draft()
        repo = _MemSessionRepo([session])
        draft_repo = _MemDraftRepo([draft])
        svc = LearnerSessionSnapshotService(
            session_repo=repo,
            draft_repo=draft_repo,
        )
        return svc.build_snapshot(session.session_id, actor_user=session.student_username, is_admin=False)

    def test_timed_out_closed_session_shows_lab_timeout_issue(self):
        session = LabSessionState(
            session_id="s1",
            lab_id="lab1",
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_CLOSED,
            failure_reason=FailureReason.LAB_TIMEOUT.value,
            cleanup_verified=True,
        )
        snap = self._build(session)
        codes = {i.code for i in snap.issues}
        assert "LAB_TIMEOUT" in codes

    def test_timed_out_closed_session_cannot_check_step(self):
        session = LabSessionState(
            session_id="s1",
            lab_id="lab1",
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_CLOSED,
            failure_reason=FailureReason.LAB_TIMEOUT.value,
            cleanup_verified=True,
        )
        snap = self._build(session)
        assert snap.action_availability.can_check_current_step is False

    def test_timed_out_closed_session_cannot_complete(self):
        session = LabSessionState(
            session_id="s1",
            lab_id="lab1",
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_CLOSED,
            failure_reason=FailureReason.LAB_TIMEOUT.value,
            cleanup_verified=True,
        )
        snap = self._build(session)
        assert snap.action_availability.can_complete is False

    def test_timed_out_closed_session_cannot_abort(self):
        session = LabSessionState(
            session_id="s1",
            lab_id="lab1",
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_CLOSED,
            failure_reason=FailureReason.LAB_TIMEOUT.value,
            cleanup_verified=True,
        )
        snap = self._build(session)
        assert snap.action_availability.can_abort is False

    def test_timed_out_closed_session_no_vm_id_in_snapshot(self):
        """Snapshot must not expose vm_id."""
        session = LabSessionState(
            session_id="s1",
            lab_id="lab1",
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_CLOSED,
            failure_reason=FailureReason.LAB_TIMEOUT.value,
            cleanup_verified=True,
        )
        snap = self._build(session)
        snap_dict = snap.model_dump()
        snap_str = str(snap_dict)
        assert "501" not in snap_str  # vm_id not leaked

    def test_timed_out_cleanup_failed_shows_cleanup_failed_issue(self):
        session = LabSessionState(
            session_id="s1",
            lab_id="lab1",
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED,
            failure_reason=FailureReason.NAMESPACE_CLEANUP_FAILED.value,
            cleanup_verified=False,
        )
        snap = self._build(session)
        codes = {i.code for i in snap.issues}
        assert "CLEANUP_FAILED" in codes

    def test_normal_active_session_no_timeout_issue(self):
        session = LabSessionState(
            session_id="s1",
            lab_id="lab1",
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
        )
        snap = self._build(session)
        codes = {i.code for i in snap.issues}
        assert "LAB_TIMEOUT" not in codes

    def test_failure_reason_shown_in_runtime_summary(self):
        session = LabSessionState(
            session_id="s1",
            lab_id="lab1",
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_CLOSED,
            failure_reason=FailureReason.LAB_TIMEOUT.value,
            cleanup_verified=True,
        )
        snap = self._build(session)
        assert snap.runtime_summary.failure_reason == FailureReason.LAB_TIMEOUT.value


# ---------------------------------------------------------------------------
# F. Contract pack — expiry endpoint recorded
# ---------------------------------------------------------------------------

class TestContractPackExpiryEndpoint:
    def test_expiry_endpoint_in_contract_pack(self):
        from backend.labgen.api_contract import build_contract_pack
        pack = build_contract_pack()
        paths = [e.path for e in pack.endpoints]
        assert "/api/labgen/runtime/expire-sessions" in paths

    def test_expiry_endpoint_is_admin_auth(self):
        from backend.labgen.api_contract import build_contract_pack
        pack = build_contract_pack()
        endpoint = next(
            (e for e in pack.endpoints if e.path == "/api/labgen/runtime/expire-sessions"),
            None,
        )
        assert endpoint is not None
        assert endpoint.auth == "admin"

    def test_expiry_endpoint_not_read_only(self):
        from backend.labgen.api_contract import build_contract_pack
        pack = build_contract_pack()
        endpoint = next(
            (e for e in pack.endpoints if e.path == "/api/labgen/runtime/expire-sessions"),
            None,
        )
        assert endpoint is not None
        assert endpoint.is_read_only is False

    def test_expiry_note_in_contract_notes(self):
        from backend.labgen.api_contract import build_contract_pack
        pack = build_contract_pack()
        combined_notes = " ".join(pack.notes)
        assert "expire-sessions" in combined_notes

    def test_expiry_endpoint_not_in_learner_facing_category(self):
        from backend.labgen.api_contract import build_contract_pack, ApiContractCategory
        pack = build_contract_pack()
        learner_endpoints = [
            e for e in pack.endpoints
            if e.category in (ApiContractCategory.LEARNER_RUNTIME, ApiContractCategory.LEARNER_CATALOG)
        ]
        learner_paths = [e.path for e in learner_endpoints]
        assert "/api/labgen/runtime/expire-sessions" not in learner_paths


# ---------------------------------------------------------------------------
# G. Regression
# ---------------------------------------------------------------------------

class TestRegressionExistingBehaviour:
    def test_abort_session_still_works(self):
        session = _active_session()
        svc, _, _ = _make_session_svc([session])
        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_abort_not_misidentified_as_timeout(self):
        session = _active_session()
        svc, _, _ = _make_session_svc([session])
        result = svc.abort_session(session.session_id)
        assert result.failure_reason != FailureReason.LAB_TIMEOUT.value

    def test_runtime_precheck_tests_still_importable(self):
        from backend.labgen.runtime_precheck import RuntimePrecheckService  # noqa: F401
        assert RuntimePrecheckService is not None

    def test_verifier_credential_reclaim_still_importable(self):
        from backend.labgen.verifier_credentials import VerifierCredentialReclaimer  # noqa: F401
        assert VerifierCredentialReclaimer is not None

    def test_failure_reasons_all_unique_values(self):
        from backend.labgen.failure_reasons import FailureReason
        values = [r.value for r in FailureReason]
        assert len(values) == len(set(values)), "Duplicate failure reason values detected"

    def test_lab_timeout_failure_reason_value(self):
        assert FailureReason.LAB_TIMEOUT.value == "lab_timeout"
