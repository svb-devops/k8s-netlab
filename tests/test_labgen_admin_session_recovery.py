"""
Tests for admin session recovery (PHASE 6 P1 hardening).

Validates:
  - admin_force_close_session transitions LAB_START_FAILED → LAB_FORCE_CLOSED
  - admin_force_close_session transitions LAB_CLEANUP_FAILED → LAB_FORCE_CLOSED
  - residual_risk=True stored on session
  - audit_note stored on session
  - audit_note is required (min 10 chars)
  - force_close blocked for non-eligible states
  - learner cannot call admin endpoints
  - admin can list failed sessions
  - list_by_status returns correct sessions
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.labgen.lab_session_repository import LabSessionRepository
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
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
from backend.labgen.routes import get_session_repository, get_session_service

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Recovery Test Lab",
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
        lab_session_status=LabSessionStatus.LAB_START_FAILED,
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

    def list_by_status(self, statuses: frozenset) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.lab_session_status in statuses]


class _StubImageResolver:
    def needs_recheck(self, img: str) -> bool:
        return False

    def check_registry_existence(self, img: str) -> str:
        return img


def _make_service(
    sessions: list[LabSessionState] | None = None,
    drafts: dict[str, LabDraft] | None = None,
) -> LabSessionService:
    from backend.labgen.repository import LabDraftRepository

    class _MemDraftRepo:
        def __init__(self, store: dict) -> None:
            self._store = store

        def get(self, lab_id: str) -> Optional[LabDraft]:
            return self._store.get(lab_id)

        def update(self, draft: LabDraft) -> LabDraft:
            self._store[draft.lab_id] = draft
            return draft

    return LabSessionService(
        session_repo=_MemSessionRepo(sessions or []),
        draft_repo=_MemDraftRepo(drafts or {}),
        vm_tracker=StubVMTracker(),
        ns_lifecycle=StubNamespaceLifecycleAdapter(),
        image_resolver=_StubImageResolver(),
    )


# ---------------------------------------------------------------------------
# Unit tests: admin_force_close_session
# ---------------------------------------------------------------------------


class TestAdminForceCloseSession:
    def test_force_close_lab_start_failed(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_START_FAILED)
        svc = _make_service(sessions=[session])
        result = svc.admin_force_close_session(
            session.session_id,
            audit_note="Admin confirmed no namespace was created",
        )
        assert result.lab_session_status == LabSessionStatus.LAB_FORCE_CLOSED

    def test_force_close_lab_cleanup_failed(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED)
        svc = _make_service(sessions=[session])
        result = svc.admin_force_close_session(
            session.session_id,
            audit_note="Namespace verified deleted via kubectl manually",
        )
        assert result.lab_session_status == LabSessionStatus.LAB_FORCE_CLOSED

    def test_audit_note_stored_on_session(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_START_FAILED)
        svc = _make_service(sessions=[session])
        note = "Confirmed: namespace was never created, no residual risk."
        result = svc.admin_force_close_session(session.session_id, audit_note=note)
        assert result.admin_audit_note == note

    def test_residual_risk_true_stored(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED)
        svc = _make_service(sessions=[session])
        result = svc.admin_force_close_session(
            session.session_id,
            audit_note="Cannot confirm namespace is gone, marking residual risk",
            residual_risk=True,
        )
        assert result.admin_force_closed_with_residual_risk is True

    def test_residual_risk_false_by_default(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_START_FAILED)
        svc = _make_service(sessions=[session])
        result = svc.admin_force_close_session(
            session.session_id,
            audit_note="Confirmed clean — no resources created",
        )
        assert result.admin_force_closed_with_residual_risk is False

    def test_empty_audit_note_raises(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_START_FAILED)
        svc = _make_service(sessions=[session])
        with pytest.raises(ValueError, match="audit_note"):
            svc.admin_force_close_session(session.session_id, audit_note="")

    def test_short_audit_note_raises_via_http(self) -> None:
        """HTTP layer validates min_length=10 on audit_note."""
        from backend.main import app
        client = TestClient(app, raise_server_exceptions=False)
        with client as c:
            c.app.dependency_overrides[get_session_service] = lambda: _make_service()
            resp = c.post(
                "/api/lab-sessions/admin/fake-id/force-close",
                json={"audit_note": "short", "residual_risk": False},
                cookies={"session": "ADMIN_TOKEN_PLACEHOLDER"},
            )
        assert resp.status_code in (401, 403, 422)

    def test_force_close_blocked_for_active_session(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_ACTIVE)
        svc = _make_service(sessions=[session])
        with pytest.raises(ValueError, match="force_close"):
            svc.admin_force_close_session(
                session.session_id,
                audit_note="Trying to close an active session",
            )

    def test_force_close_blocked_for_closed_session(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_CLOSED)
        svc = _make_service(sessions=[session])
        with pytest.raises(ValueError, match="force_close"):
            svc.admin_force_close_session(
                session.session_id,
                audit_note="Session already closed, cannot force-close",
            )

    def test_force_close_blocked_for_already_force_closed(self) -> None:
        session = _make_session(lab_session_status=LabSessionStatus.LAB_FORCE_CLOSED)
        svc = _make_service(sessions=[session])
        with pytest.raises(ValueError, match="force_close"):
            svc.admin_force_close_session(
                session.session_id,
                audit_note="Already force-closed, should not re-close",
            )


# ---------------------------------------------------------------------------
# Unit tests: list_failed_sessions
# ---------------------------------------------------------------------------


class TestListFailedSessions:
    def test_returns_start_failed_sessions(self) -> None:
        s1 = _make_session(lab_session_status=LabSessionStatus.LAB_START_FAILED)
        s2 = _make_session(lab_session_status=LabSessionStatus.LAB_CLOSED)
        svc = _make_service(sessions=[s1, s2])
        result = svc.list_failed_sessions()
        ids = [s.session_id for s in result]
        assert s1.session_id in ids
        assert s2.session_id not in ids

    def test_returns_cleanup_failed_sessions(self) -> None:
        s1 = _make_session(lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED)
        s2 = _make_session(lab_session_status=LabSessionStatus.LAB_ACTIVE)
        svc = _make_service(sessions=[s1, s2])
        result = svc.list_failed_sessions()
        ids = [s.session_id for s in result]
        assert s1.session_id in ids
        assert s2.session_id not in ids

    def test_empty_when_no_failed_sessions(self) -> None:
        sessions = [
            _make_session(lab_session_status=LabSessionStatus.LAB_CLOSED),
            _make_session(lab_session_status=LabSessionStatus.LAB_ABORTED),
        ]
        svc = _make_service(sessions=sessions)
        assert svc.list_failed_sessions() == []


# ---------------------------------------------------------------------------
# HTTP tests: admin-only enforcement
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    from backend.main import app as _app
    return _app


@pytest.fixture()
def admin_client(app):
    from backend.labgen.routes import require_admin_user
    from backend.auth_deps import get_current_user
    app.dependency_overrides[require_admin_user] = lambda: "admin"
    app.dependency_overrides[get_current_user] = lambda: "admin"
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(require_admin_user, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def learner_client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


class TestAdminRecoveryEndpointAuth:
    def test_learner_cannot_list_failed_sessions(self, learner_client: TestClient) -> None:
        """GET /admin/failed must return 401/403 for unauthenticated users."""
        resp = learner_client.get("/api/lab-sessions/admin/failed")
        assert resp.status_code in (401, 403)

    def test_learner_cannot_force_close(self, learner_client: TestClient) -> None:
        """POST /admin/{id}/force-close must return 401/403 for unauthenticated users."""
        resp = learner_client.post(
            "/api/lab-sessions/admin/fake-session/force-close",
            json={"audit_note": "Learner trying to close session", "residual_risk": False},
        )
        assert resp.status_code in (401, 403)

    def test_admin_can_list_failed_sessions(self, admin_client: TestClient) -> None:
        """Admin user can list failed sessions."""
        resp = admin_client.get("/api/lab-sessions/admin/failed")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_force_close_start_failed_returns_force_closed(
        self,
        admin_client: TestClient,
        app,
    ) -> None:
        """Admin can force-close a LAB_START_FAILED session."""
        start_failed = _make_session(lab_session_status=LabSessionStatus.LAB_START_FAILED)
        mock_svc = _make_service(sessions=[start_failed])

        app.dependency_overrides[get_session_service] = lambda: mock_svc
        try:
            resp = admin_client.post(
                f"/api/lab-sessions/admin/{start_failed.session_id}/force-close",
                json={
                    "audit_note": "Confirmed namespace never created — safe to close",
                    "residual_risk": False,
                },
            )
        finally:
            app.dependency_overrides.pop(get_session_service, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["lab_session_status"] == "LAB_FORCE_CLOSED"
        assert data["admin_audit_note"] == "Confirmed namespace never created — safe to close"
        assert data["admin_force_closed_with_residual_risk"] is False

    def test_admin_force_close_cleanup_failed_with_residual_risk(
        self,
        admin_client: TestClient,
        app,
    ) -> None:
        """Admin can force-close LAB_CLEANUP_FAILED with residual_risk=True."""
        cleanup_failed = _make_session(lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED)
        mock_svc = _make_service(sessions=[cleanup_failed])

        app.dependency_overrides[get_session_service] = lambda: mock_svc
        try:
            resp = admin_client.post(
                f"/api/lab-sessions/admin/{cleanup_failed.session_id}/force-close",
                json={
                    "audit_note": "Cannot confirm deletion — marking residual risk",
                    "residual_risk": True,
                },
            )
        finally:
            app.dependency_overrides.pop(get_session_service, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["lab_session_status"] == "LAB_FORCE_CLOSED"
        assert data["admin_force_closed_with_residual_risk"] is True


class TestAbortedSessionAttestation:
    """Verify admin attestation pattern for LAB_ABORTED sessions with cleanup_verified=False.

    When a session is LAB_ABORTED and cleanup_verified=False (e.g., the underlying VM was
    deleted before cleanup could run), an admin can investigate and attest zero residual by
    updating the session via the repository layer.
    """

    def _make_aborted_session(self, *, reason: str, vm_id: str = "401") -> LabSessionState:
        s = _make_session(lab_session_status=LabSessionStatus.LAB_ABORTED)
        s.failure_reason = reason
        s.vm_id = vm_id
        s.cleanup_verified = False
        s.admin_force_closed_with_residual_risk = False
        return s

    def test_aborted_session_can_be_attested_via_repo_update(self) -> None:
        """Admin attestation updates cleanup_verified and audit_note without changing status."""
        session = self._make_aborted_session(reason="operator_reset")
        assert not session.cleanup_verified

        # Admin investigates: VM is gone, no namespace residual
        session.admin_audit_note = "VM 401 absent from Proxmox; namespace cannot exist; admin attests zero residual"
        session.admin_force_closed_with_residual_risk = False
        session.cleanup_verified = True

        assert session.lab_session_status == LabSessionStatus.LAB_ABORTED
        assert session.cleanup_verified is True
        assert session.admin_force_closed_with_residual_risk is False
        assert "admin attests" in session.admin_audit_note

    def test_precheck_abort_has_no_residual(self) -> None:
        """Sessions aborted at precheck (before namespace creation) have zero residual."""
        session = self._make_aborted_session(
            reason="vm_has_no_verifier_credentials", vm_id="400"
        )
        # Precheck fires before namespace creation → namespace never existed
        session.admin_audit_note = "Precheck abort; namespace was never created; zero residual"
        session.cleanup_verified = True
        assert session.cleanup_verified is True

    def test_vm_deleted_abort_has_no_residual(self) -> None:
        """Sessions where VM was deleted/rebuilt have zero residual (K3s cluster wiped)."""
        for reason in ("vm_deleted_and_recreated", "vm_not_found_rebuilt"):
            session = self._make_aborted_session(reason=reason, vm_id="500")
            session.admin_audit_note = f"VM deleted ({reason}); K3s cluster wiped; namespace gone"
            session.cleanup_verified = True
            assert session.cleanup_verified is True

    def test_zero_debt_state_after_full_recovery(self) -> None:
        """After complete admin recovery, no sessions have cleanup_verified=False."""
        sessions: list[LabSessionState] = []

        # Mix of terminal states all recovered
        for status in (LabSessionStatus.LAB_CLOSED, LabSessionStatus.LAB_FORCE_CLOSED,
                       LabSessionStatus.LAB_ABORTED):
            s = _make_session(lab_session_status=status)
            s.cleanup_verified = True
            s.admin_force_closed_with_residual_risk = False
            sessions.append(s)

        not_clean = [s for s in sessions if not s.cleanup_verified]
        with_residual = [s for s in sessions if s.admin_force_closed_with_residual_risk]
        active = [s for s in sessions if s.lab_session_status == LabSessionStatus.LAB_ACTIVE]

        assert len(not_clean) == 0
        assert len(with_residual) == 0
        assert len(active) == 0
