"""
Tests for VMExpiryService (backend/labgen/vm_expiry.py).

Coverage groups:
  A. Expiry detection
  B. Timeout handling success
  C. Timeout cleanup failure
  D. limit + dry_run behaviour
  E. Edge cases (no sessions, already-ended states, no started_at)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.models import (
    LabSessionState,
    LabSessionStatus,
)
from backend.labgen.vm_expiry import VMExpiryService, DEFAULT_SESSION_TTL_MINUTES

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
_TTL = 30  # minutes


def _clock() -> datetime:
    return _NOW


def _make_session(
    session_id: str = "s1",
    vm_id: str = "501",
    username: str = "alice",
    status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
    started_at: Optional[datetime] = None,
    failure_reason: Optional[str] = None,
    cleanup_verified: bool = False,
    namespace: Optional[str] = "lab-s1",
) -> LabSessionState:
    return LabSessionState(
        session_id=session_id,
        lab_id="lab1",
        vm_id=vm_id,
        student_username=username,
        lab_session_status=status,
        started_at=started_at,
        failure_reason=failure_reason,
        cleanup_verified=cleanup_verified,
        namespace=namespace,
    )


class _MemSessionRepo:
    def __init__(self, sessions: list[LabSessionState]) -> None:
        self._store: dict[str, LabSessionState] = {s.session_id: s for s in sessions}

    def list_all(self) -> list[LabSessionState]:
        return list(self._store.values())

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._store.get(session_id)

    def update(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def create(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]

    def list_by_vm_id(self, vm_id: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.vm_id == vm_id]


def _svc(sessions: list[LabSessionState]) -> tuple[VMExpiryService, _MemSessionRepo, MagicMock]:
    """Build VMExpiryService with injectable mocks. Returns (svc, repo, session_service_mock)."""
    repo = _MemSessionRepo(sessions)
    session_svc_mock = MagicMock()
    # By default, timeout_session returns a LAB_CLOSED session
    def _timeout_side_effect(session_id: str) -> LabSessionState:
        s = repo.get(session_id)
        assert s is not None
        s.lab_session_status = LabSessionStatus.LAB_CLOSED
        s.cleanup_verified = True
        s.failure_reason = FailureReason.LAB_TIMEOUT.value
        repo.update(s)
        return s
    session_svc_mock.timeout_session.side_effect = _timeout_side_effect
    expiry_svc = VMExpiryService(
        session_repo=repo,
        session_service=session_svc_mock,
        session_ttl_minutes=_TTL,
        clock=_clock,
    )
    return expiry_svc, repo, session_svc_mock


# ---------------------------------------------------------------------------
# A. Expiry detection
# ---------------------------------------------------------------------------

class TestExpiryDetection:
    def test_active_before_ttl_not_expired(self):
        # Started 29 minutes ago — not yet expired
        started = _NOW - timedelta(minutes=29)
        session = _make_session(started_at=started)
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_active_exactly_at_ttl_not_expired(self):
        # started_at == cutoff (i.e., age == TTL, not strictly greater)
        started = _NOW - timedelta(minutes=_TTL)
        session = _make_session(started_at=started)
        svc, _, _ = _svc([session])
        # cutoff = _NOW - TTL; started_at < cutoff is False when equal
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_active_after_ttl_expired(self):
        # Started 31 minutes ago — expired
        started = _NOW - timedelta(minutes=31)
        session = _make_session(started_at=started)
        svc, _, _ = _svc([session])
        expired = svc.find_expired_sessions(now=_NOW)
        assert len(expired) == 1
        assert expired[0].session_id == "s1"

    def test_completed_session_not_expired(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started, status=LabSessionStatus.LAB_COMPLETED)
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_aborted_session_not_expired(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started, status=LabSessionStatus.LAB_ABORTED)
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_closed_session_not_expired(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started, status=LabSessionStatus.LAB_CLOSED)
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_cleanup_failed_session_not_expired(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started, status=LabSessionStatus.LAB_CLEANUP_FAILED)
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_already_timed_out_session_not_expired(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started, status=LabSessionStatus.LAB_TIMEOUT)
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_force_closed_session_not_expired(self):
        """LAB_FORCE_CLOSED is terminal (admin-only force close) and must be skipped —
        otherwise a cron-driven expire_sessions call re-selects it on every run forever
        (regression: _SKIP_STATUSES omitted LAB_FORCE_CLOSED while lab_session_service's
        own _ALREADY_ENDED_STATES already treated it as terminal)."""
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started, status=LabSessionStatus.LAB_FORCE_CLOSED)
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_session_without_started_at_not_expired(self):
        session = _make_session(started_at=None)
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_multiple_sessions_only_expired_returned(self):
        fresh = _make_session("s1", started_at=_NOW - timedelta(minutes=10))
        old1 = _make_session("s2", vm_id="502", started_at=_NOW - timedelta(minutes=60))
        old2 = _make_session("s3", vm_id="503", started_at=_NOW - timedelta(minutes=45))
        done = _make_session("s4", vm_id="504", started_at=_NOW - timedelta(minutes=90),
                             status=LabSessionStatus.LAB_CLOSED)
        svc, _, _ = _svc([fresh, old1, old2, done])
        expired = svc.find_expired_sessions(now=_NOW)
        ids = {s.session_id for s in expired}
        assert ids == {"s2", "s3"}

    def test_uses_clock_when_now_not_provided(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        svc, _, _ = _svc([session])
        expired = svc.find_expired_sessions()  # no now= argument
        assert len(expired) == 1


# ---------------------------------------------------------------------------
# B. Timeout handling success
# ---------------------------------------------------------------------------

class TestTimeoutHandlingSuccess:
    def test_expired_session_is_expired_id_recorded(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        svc, _, mock_svc = _svc([session])
        result = svc.expire_sessions(now=_NOW)
        assert "s1" in result.expired_session_ids

    def test_successful_timeout_session_in_cleaned_ids(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        svc, _, _ = _svc([session])
        result = svc.expire_sessions(now=_NOW)
        assert "s1" in result.cleaned_session_ids
        assert "s1" not in result.failed_session_ids

    def test_timeout_session_called_with_session_id(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        svc, _, mock_svc = _svc([session])
        svc.expire_sessions(now=_NOW)
        mock_svc.timeout_session.assert_called_once_with("s1")

    def test_already_closed_session_not_called_again(self):
        """Session already LAB_CLOSED must not be passed to timeout_session."""
        session = _make_session(started_at=_NOW - timedelta(minutes=60),
                                status=LabSessionStatus.LAB_CLOSED)
        svc, _, mock_svc = _svc([session])
        svc.expire_sessions(now=_NOW)
        mock_svc.timeout_session.assert_not_called()

    def test_repeated_expiry_call_idempotent(self):
        """After first expiry, session is LAB_CLOSED and should not be expired again."""
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        svc, repo, _ = _svc([session])
        svc.expire_sessions(now=_NOW)
        # Session is now LAB_CLOSED in repo
        result2 = svc.expire_sessions(now=_NOW)
        assert result2.expired_session_ids == []
        assert result2.cleaned_session_ids == []


# ---------------------------------------------------------------------------
# C. Timeout cleanup failure
# ---------------------------------------------------------------------------

class TestTimeoutCleanupFailure:
    def test_cleanup_failed_in_failed_ids(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        repo = _MemSessionRepo([session])
        mock_svc = MagicMock()

        def _fail_timeout(session_id: str) -> LabSessionState:
            s = repo.get(session_id)
            s.lab_session_status = LabSessionStatus.LAB_CLEANUP_FAILED
            s.failure_reason = FailureReason.NAMESPACE_CLEANUP_FAILED.value
            repo.update(s)
            return s
        mock_svc.timeout_session.side_effect = _fail_timeout
        expiry_svc = VMExpiryService(
            session_repo=repo,
            session_service=mock_svc,
            session_ttl_minutes=_TTL,
            clock=_clock,
        )
        result = expiry_svc.expire_sessions(now=_NOW)
        assert "s1" in result.failed_session_ids
        assert "s1" not in result.cleaned_session_ids

    def test_cleanup_failed_vm_tainted(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        repo = _MemSessionRepo([session])
        mock_svc = MagicMock()

        def _fail_timeout(session_id: str) -> LabSessionState:
            s = repo.get(session_id)
            s.lab_session_status = LabSessionStatus.LAB_CLEANUP_FAILED
            s.failure_reason = FailureReason.NAMESPACE_CLEANUP_FAILED.value
            repo.update(s)
            return s
        mock_svc.timeout_session.side_effect = _fail_timeout
        expiry_svc = VMExpiryService(
            session_repo=repo, session_service=mock_svc, session_ttl_minutes=_TTL, clock=_clock
        )
        result = expiry_svc.expire_sessions(now=_NOW)
        assert "501" in result.tainted_vm_ids

    def test_cleanup_failed_issue_has_stable_code(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        repo = _MemSessionRepo([session])
        mock_svc = MagicMock()

        def _fail_timeout(session_id: str) -> LabSessionState:
            s = repo.get(session_id)
            s.lab_session_status = LabSessionStatus.LAB_CLEANUP_FAILED
            s.failure_reason = FailureReason.NAMESPACE_CLEANUP_FAILED.value
            repo.update(s)
            return s
        mock_svc.timeout_session.side_effect = _fail_timeout
        expiry_svc = VMExpiryService(
            session_repo=repo, session_service=mock_svc, session_ttl_minutes=_TTL, clock=_clock
        )
        result = expiry_svc.expire_sessions(now=_NOW)
        assert len(result.issues) == 1
        assert result.issues[0].failure_reason == FailureReason.NAMESPACE_CLEANUP_FAILED.value

    def test_cleanup_failed_issue_no_credential_in_message(self):
        """Issue message must not contain credential material."""
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        repo = _MemSessionRepo([session])
        mock_svc = MagicMock()

        def _fail_timeout(session_id: str) -> LabSessionState:
            s = repo.get(session_id)
            s.lab_session_status = LabSessionStatus.LAB_CLEANUP_FAILED
            s.failure_reason = FailureReason.NAMESPACE_CLEANUP_FAILED.value
            repo.update(s)
            return s
        mock_svc.timeout_session.side_effect = _fail_timeout
        expiry_svc = VMExpiryService(
            session_repo=repo, session_service=mock_svc, session_ttl_minutes=_TTL, clock=_clock
        )
        result = expiry_svc.expire_sessions(now=_NOW)
        msg = result.issues[0].message
        for word in ("Bearer", "kubeconfig", "password", "secret", "token:", "eyJ", "namespace"):
            assert word.lower() not in msg.lower(), f"Sensitive word '{word}' found in issue message"

    def test_timeout_exception_does_not_abort_other_sessions(self):
        """An exception for one session must not prevent others from being processed."""
        s1 = _make_session("s1", vm_id="501", started_at=_NOW - timedelta(minutes=60))
        s2 = _make_session("s2", vm_id="502", started_at=_NOW - timedelta(minutes=60))
        repo = _MemSessionRepo([s1, s2])
        mock_svc = MagicMock()
        call_count = {"n": 0}

        def _mixed_timeout(session_id: str) -> LabSessionState:
            call_count["n"] += 1
            if session_id == "s1":
                raise RuntimeError("simulated crash")
            s = repo.get(session_id)
            s.lab_session_status = LabSessionStatus.LAB_CLOSED
            s.cleanup_verified = True
            repo.update(s)
            return s
        mock_svc.timeout_session.side_effect = _mixed_timeout
        expiry_svc = VMExpiryService(
            session_repo=repo, session_service=mock_svc, session_ttl_minutes=_TTL, clock=_clock
        )
        result = expiry_svc.expire_sessions(now=_NOW)
        assert call_count["n"] == 2
        assert "s2" in result.cleaned_session_ids
        assert "s1" in result.failed_session_ids

    def test_exception_issue_has_lab_timeout_code(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        repo = _MemSessionRepo([session])
        mock_svc = MagicMock()
        mock_svc.timeout_session.side_effect = RuntimeError("boom")
        expiry_svc = VMExpiryService(
            session_repo=repo, session_service=mock_svc, session_ttl_minutes=_TTL, clock=_clock
        )
        result = expiry_svc.expire_sessions(now=_NOW)
        assert len(result.issues) == 1
        assert result.issues[0].failure_reason == FailureReason.LAB_TIMEOUT.value

    def test_exception_issue_no_raw_exception_in_message(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        repo = _MemSessionRepo([session])
        mock_svc = MagicMock()
        mock_svc.timeout_session.side_effect = RuntimeError("db conn string: postgresql://admin:secret@host/db")
        expiry_svc = VMExpiryService(
            session_repo=repo, session_service=mock_svc, session_ttl_minutes=_TTL, clock=_clock
        )
        result = expiry_svc.expire_sessions(now=_NOW)
        msg = result.issues[0].message
        assert "secret" not in msg
        assert "postgresql" not in msg
        assert "admin" not in msg


# ---------------------------------------------------------------------------
# D. limit + dry_run behaviour
# ---------------------------------------------------------------------------

class TestLimitAndDryRun:
    def test_limit_caps_processed_sessions(self):
        sessions = [
            _make_session(f"s{i}", vm_id=str(500 + i), started_at=_NOW - timedelta(minutes=60))
            for i in range(5)
        ]
        svc, _, mock_svc = _svc(sessions)
        result = svc.expire_sessions(limit=2, now=_NOW)
        assert len(result.expired_session_ids) == 2
        assert mock_svc.timeout_session.call_count == 2

    def test_dry_run_does_not_mutate_state(self):
        started = _NOW - timedelta(minutes=60)
        session = _make_session(started_at=started)
        svc, _, mock_svc = _svc([session])
        result = svc.expire_sessions(dry_run=True, now=_NOW)
        assert "s1" in result.expired_session_ids
        assert result.cleaned_session_ids == []
        assert result.failed_session_ids == []
        mock_svc.timeout_session.assert_not_called()

    def test_dry_run_limit_combined(self):
        sessions = [
            _make_session(f"s{i}", vm_id=str(500 + i), started_at=_NOW - timedelta(minutes=60))
            for i in range(5)
        ]
        svc, _, mock_svc = _svc(sessions)
        result = svc.expire_sessions(dry_run=True, limit=3, now=_NOW)
        assert len(result.expired_session_ids) == 3
        mock_svc.timeout_session.assert_not_called()

    def test_no_expired_sessions_empty_result(self):
        session = _make_session(started_at=_NOW - timedelta(minutes=5))
        svc, _, mock_svc = _svc([session])
        result = svc.expire_sessions(now=_NOW)
        assert result.expired_session_ids == []
        assert result.cleaned_session_ids == []
        assert result.failed_session_ids == []
        mock_svc.timeout_session.assert_not_called()

    def test_checked_at_uses_provided_now(self):
        svc, _, _ = _svc([])
        result = svc.expire_sessions(now=_NOW)
        assert result.checked_at == _NOW

    def test_checked_at_uses_clock_when_no_now(self):
        svc, _, _ = _svc([])
        result = svc.expire_sessions()
        assert result.checked_at == _NOW


# ---------------------------------------------------------------------------
# E. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_repo_no_sessions(self):
        svc, _, _ = _svc([])
        result = svc.expire_sessions(now=_NOW)
        assert result.expired_session_ids == []

    def test_start_failed_session_not_expired(self):
        session = _make_session(
            started_at=_NOW - timedelta(minutes=60),
            status=LabSessionStatus.LAB_START_FAILED,
        )
        svc, _, _ = _svc([session])
        assert svc.find_expired_sessions(now=_NOW) == []

    def test_naive_datetime_treated_as_utc(self):
        """started_at without tzinfo should be treated as UTC."""
        naive_started = datetime(2026, 6, 11, 11, 0, 0)  # 1 hour ago, naive
        session = _make_session(started_at=naive_started)
        svc, _, _ = _svc([session])
        expired = svc.find_expired_sessions(now=_NOW)
        assert len(expired) == 1

    def test_default_ttl_is_30_minutes(self):
        assert DEFAULT_SESSION_TTL_MINUTES == 30


class TestGetExpiryServiceWiring:
    """Pod Pending release stabilization (2026-07-18): pins that the real
    production entry point (backend.labgen.routes.get_expiry_service)
    actually threads config.LABGEN_LAB_SESSION_TTL_MINUTES into
    VMExpiryService, rather than silently falling back to
    DEFAULT_SESSION_TTL_MINUTES (30). The class default alone is correct and
    intentional for direct instantiation (e.g. tests, or any future caller
    that doesn't have a configured value) — this test guards the *wiring*,
    which is the part that would let a real deployment silently regress to
    a 30-minute TTL instead of the intended production value if someone
    edited get_expiry_service() to drop the session_ttl_minutes= kwarg.

    The 2026-07-18 incident itself was not a wiring bug (get_expiry_service
    was already correctly wired) — it was a drop-in EnvironmentFile
    (/etc/labgen/home_lab_mvp.env) shadowing config.LABGEN_LAB_SESSION_TTL_MINUTES
    at the OS/systemd level, which no unit test can observe. This test
    exists so that if the wiring itself ever regresses too, it's caught here
    instead of only in production.
    """

    def test_expiry_service_uses_configured_ttl_not_class_default(self, monkeypatch):
        import backend.labgen.routes as routes_module

        monkeypatch.setattr(routes_module, "_expiry_svc", None)
        monkeypatch.setattr("backend.config.LABGEN_LAB_SESSION_TTL_MINUTES", 90)

        svc = routes_module.get_expiry_service()

        assert svc._ttl == 90
        assert svc._ttl != DEFAULT_SESSION_TTL_MINUTES
