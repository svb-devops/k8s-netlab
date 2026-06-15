"""
Learner Runtime Session Snapshot API — tests.

Coverage areas:
  A. Session list (GET /api/lab-sessions)
  B. Snapshot happy path
  C. Step progression states
  D. Completion availability
  E. Cleanup failure / VM tainted
  F. Permissions
  G. Safety (no credential leak)
  H. Regression (read-only invariants)
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.learner_session_snapshot import (
    LearnerSessionSnapshotService,
    SnapshotAccessDenied,
    SnapshotNotFound,
    _build_action_availability,
    _build_runtime_summary,
    _build_step_statuses,
    _check_summary_for_step,
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
    VerifyResult,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.routes import (
    get_current_user,
    get_repository,
    get_snapshot_service,
)
from backend.labgen.static_validator import StaticValidator
from backend.main import app

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Credential pattern checker (same as other test modules)
# ---------------------------------------------------------------------------

_CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._=+/\-]{8,}"),
    re.compile(r"(?i)(token|password|secret|private_key|credential|kubeconfig)\s*[=:]\s*\S+"),
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"(?i)stack\s+trace"),
]


def _assert_no_sensitive(payload) -> None:
    if isinstance(payload, str):
        for pat in _CREDENTIAL_PATTERNS:
            assert not pat.search(payload), (
                f"Sensitive pattern {pat.pattern!r} found in: {payload!r}"
            )
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_sensitive(item)
    elif isinstance(payload, dict):
        for v in payload.values():
            _assert_no_sensitive(v)


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def _make_draft(step_count: int = 2, lab_id: Optional[str] = None) -> LabDraft:
    steps = [
        Step(
            step_id=f"step-{i+1}",
            order=i + 1,
            why=f"Understand concept {i+1}",
            do=f"kubectl apply -f step{i+1}.yaml",
            observe=f"kubectl get pods -n lab",
            explain=ExplainField(
                concept=f"concept-{i+1}",
                observation=f"pods running step {i+1}",
            ),
            verify=[
                VerifyTemplate(
                    verify_id=f"vt-{i+1}-a",
                    type=VerifyType.POD_RUNNING,
                    name=f"nginx-{i+1}",
                )
            ],
        )
        for i in range(step_count)
    ]
    draft = LabDraft(
        source_article_id="art-snap-test",
        title="Snapshot Test Lab",
        description="A lab for snapshot tests",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=steps,
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
    )
    if lab_id:
        draft.lab_id = lab_id
    draft.publish_status = PublishStatus.PUBLISHED
    draft.validator_results = StaticValidator().validate(draft)
    return draft


def _make_session(
    lab_id: str,
    username: str,
    session_status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
    *,
    session_id: Optional[str] = None,
    current_step_index: int = 0,
    completed_step_ids: Optional[list[str]] = None,
    ready_to_complete: bool = False,
    last_verify_results: Optional[list[VerifyResult]] = None,
    failure_reason: Optional[str] = None,
    cleanup_verified: bool = False,
    namespace: Optional[str] = None,
) -> LabSessionState:
    s = LabSessionState(
        lab_id=lab_id,
        vm_id="501",
        student_username=username,
        lab_session_status=session_status,
        current_step_index=current_step_index,
        completed_step_ids=completed_step_ids or [],
        ready_to_complete=ready_to_complete,
        last_verify_results=last_verify_results or [],
        failure_reason=failure_reason,
        cleanup_verified=cleanup_verified,
        namespace=namespace,
    )
    if session_id:
        s.session_id = session_id
    return s


# ---------------------------------------------------------------------------
# In-memory repositories
# ---------------------------------------------------------------------------


class _MemDraftRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def put(self, draft: LabDraft) -> None:
        self._store[draft.lab_id] = draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemSessionRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabSessionState] = {}

    def put(self, session: LabSessionState) -> None:
        self._store[session.session_id] = session

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._store.get(session_id)

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]

    # Compatibility stubs (LabSessionService calls these)
    def create(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session

    def update(self, session: LabSessionState) -> LabSessionState:
        self._store[session.session_id] = session
        return session


# ---------------------------------------------------------------------------
# Test context manager — wires DI overrides
# ---------------------------------------------------------------------------


@contextmanager
def _snapshot_ctx(
    draft_repo: _MemDraftRepo,
    session_repo: _MemSessionRepo,
    *,
    user: str = "alice",
) -> Iterator[TestClient]:
    """Override get_repository, get_snapshot_service, get_current_user for tests."""
    svc = LearnerSessionSnapshotService(
        session_repo=session_repo,  # type: ignore[arg-type]
        draft_repo=draft_repo,      # type: ignore[arg-type]
    )
    overrides = {
        get_current_user: lambda: user,
        get_repository: lambda: draft_repo,
        get_snapshot_service: lambda: svc,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        for key in overrides:
            app.dependency_overrides.pop(key, None)


# ===========================================================================
# A. Session list (GET /api/lab-sessions)
# ===========================================================================


class TestSessionList:
    def test_owner_gets_own_sessions(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-list-1")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get("/api/lab-sessions")

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["session_id"] == sess.session_id
        assert items[0]["lab_id"] == draft.lab_id

    def test_list_excludes_other_users_sessions(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-list-2")
        dr.put(draft)
        alice_sess = _make_session(draft.lab_id, "alice")
        bob_sess = _make_session(draft.lab_id, "bob")
        sr.put(alice_sess)
        sr.put(bob_sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get("/api/lab-sessions")

        assert resp.status_code == 200
        items = resp.json()
        assert all(item["session_id"] == alice_sess.session_id for item in items)
        assert not any(item["session_id"] == bob_sess.session_id for item in items)

    def test_list_empty_when_no_sessions(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get("/api/lab-sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_response_schema_stable(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-schema-1")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get("/api/lab-sessions")

        item = resp.json()[0]
        assert {"session_id", "lab_id", "title", "session_state",
                "ready_to_complete", "current_step_id"}.issubset(set(item.keys()))

    def test_list_no_raw_runtime_internals(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-intern-1")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get("/api/lab-sessions")

        payload = resp.json()
        for item in payload:
            assert "namespace" not in item
            assert "vm_id" not in item
            assert "last_verify_results" not in item

    def test_list_filter_by_status(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-filter-1")
        dr.put(draft)
        active = _make_session(draft.lab_id, "alice", LabSessionStatus.LAB_ACTIVE)
        closed = _make_session(draft.lab_id, "alice", LabSessionStatus.LAB_CLOSED)
        sr.put(active)
        sr.put(closed)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get("/api/lab-sessions?status=LAB_ACTIVE")

        items = resp.json()
        assert len(items) == 1
        assert items[0]["session_state"] == "LAB_ACTIVE"

    def test_unauthenticated_returns_4xx(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        # No dependency override for get_current_user — must fail auth
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/lab-sessions")
        assert resp.status_code in (401, 403)


# ===========================================================================
# B. Snapshot happy path
# ===========================================================================


class TestSnapshotHappyPath:
    def test_active_session_returns_snapshot(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-snap-1")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == sess.session_id
        assert data["lab_id"] == draft.lab_id
        assert data["session_state"] == "LAB_ACTIVE"

    def test_snapshot_contains_required_fields(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-snap-2")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert "session_state" in data
        assert "current_step_id" in data
        assert "steps" in data
        assert "runtime_summary" in data
        assert "action_availability" in data
        assert "checked_at" in data

    def test_current_step_id_correct(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-snap-3", step_count=3)
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", current_step_index=1)
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["current_step_id"] == "step-2"

    def test_can_check_current_step_true_for_active(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-snap-4")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", LabSessionStatus.LAB_ACTIVE)
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["action_availability"]["can_check_current_step"] is True

    def test_can_complete_false_when_not_ready(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-snap-5")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", ready_to_complete=False)
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["action_availability"]["can_complete"] is False

    def test_snapshot_exposes_namespace_for_terminal_badge(self) -> None:
        # namespace is exposed to support the learner kubectl terminal badge.
        # It is the learner's own session namespace; not a secret.
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-snap-6")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", namespace="lab-alice-session-abc")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        # namespace key present and value matches
        assert data.get("namespace") == "lab-alice-session-abc"
        # vm_id still hidden
        assert "vm_id" not in str(data)


# ===========================================================================
# C. Step progression states
# ===========================================================================


class TestStepProgressionStates:
    def test_completed_steps_show_passed(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-prog-1", step_count=3)
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=1,
            completed_step_ids=["step-1"],
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        steps = {s["step_id"]: s for s in data["steps"]}
        assert steps["step-1"]["status"] == "passed"
        assert steps["step-2"]["status"] == "available"
        assert steps["step-3"]["status"] == "locked"

    def test_current_step_is_current(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-prog-2", step_count=2)
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", current_step_index=0)
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        current_steps = [s for s in data["steps"] if s["is_current"]]
        assert len(current_steps) == 1
        assert current_steps[0]["step_id"] == "step-1"

    def test_step_check_passed_shows_passed_check_summary(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-prog-3", step_count=1)
        dr.put(draft)
        current_step = draft.steps[0]
        passed_results = [
            VerifyResult(
                session_id="s1",
                verify_id=current_step.verify[0].verify_id,
                verify_type="pod_running",
                passed=True,
            )
        ]
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=0,
            last_verify_results=passed_results,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        step = data["steps"][0]
        assert step["check_summary"]["last_result"] == "passed"

    def test_step_check_passed_safe_message_uses_verify_detail(self) -> None:
        """After step passes (step in completed_step_ids), check_summary shows VerifyResult.detail."""
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-snap-detail-1", step_count=2)
        dr.put(draft)
        step1 = draft.steps[0]
        step2 = draft.steps[1]
        # Simulate: step1 passed, step2 is now current (advanced), last_verify_results = step1 results
        passed_results = [
            VerifyResult(
                session_id="s1",
                verify_id=step1.verify[0].verify_id,
                verify_type="deployment_ready",
                passed=True,
                detail=(
                    'Deployment "hello-deployment" is available with 1 ready replica '
                    "in your isolated namespace. Kubernetes has created a Pod for this workload."
                ),
            )
        ]
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=1,           # advanced past step1
            completed_step_ids=[step1.step_id],  # step1 is completed
            last_verify_results=passed_results,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        step1_data = data["steps"][0]
        summary = step1_data["check_summary"]
        assert summary is not None, "Completed step should show check_summary with PASS detail"
        assert summary["last_result"] == "passed"
        assert summary["safe_message"] is not None
        assert "1 ready replica" in summary["safe_message"]
        assert "Pod" in summary["safe_message"]
        _assert_no_sensitive(summary)

        # step2 (current, not yet checked) must show not_checked — no stale results
        step2_data = data["steps"][1]
        cs2 = step2_data["check_summary"]
        if cs2:
            assert cs2["last_result"] == "not_checked"

    def test_step_check_passed_safe_message_fallback_when_no_detail(self) -> None:
        """When VerifyResult.detail is empty on a completed step, fall back to generic message."""
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-snap-detail-2", step_count=2)
        dr.put(draft)
        step1 = draft.steps[0]
        passed_results = [
            VerifyResult(
                session_id="s1",
                verify_id=step1.verify[0].verify_id,
                verify_type="pod_running",
                passed=True,
                detail="",  # empty detail → should fall back to generic
            )
        ]
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=1,
            completed_step_ids=[step1.step_id],
            last_verify_results=passed_results,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        step1_data = data["steps"][0]
        summary = step1_data["check_summary"]
        assert summary is not None
        assert summary["last_result"] == "passed"
        assert summary["safe_message"] is not None
        _assert_no_sensitive(summary)

    def test_step_check_failed_shows_safe_message(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-prog-4", step_count=1)
        dr.put(draft)
        current_step = draft.steps[0]
        failed_results = [
            VerifyResult(
                session_id="s1",
                verify_id=current_step.verify[0].verify_id,
                verify_type="pod_running",
                passed=False,
                failure_reason=FailureReason.VERIFIER_TYPE_NOT_IMPLEMENTED.value,
            )
        ]
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=0,
            last_verify_results=failed_results,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        step = data["steps"][0]
        assert step["check_summary"]["last_result"] == "failed"
        assert step["check_summary"]["safe_message"] is not None
        # safe_message must NOT contain raw stack trace or credential
        _assert_no_sensitive(step["check_summary"])

    def test_stale_verify_results_show_not_checked(self) -> None:
        """Results from step-1 must not bleed into step-2's check summary."""
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-prog-5", step_count=2)
        dr.put(draft)
        # Results from step-1 (which has verify_id vt-1-a)
        stale_results = [
            VerifyResult(
                session_id="s1",
                verify_id="vt-1-a",   # belongs to step-1, not step-2
                verify_type="pod_running",
                passed=True,
            )
        ]
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=1,       # now on step-2
            completed_step_ids=["step-1"],
            last_verify_results=stale_results,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        step2 = next(s for s in data["steps"] if s["step_id"] == "step-2")
        assert step2["check_summary"]["last_result"] == "not_checked"

    def test_failure_reason_uses_safe_machine_code(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-prog-6", step_count=1)
        dr.put(draft)
        current_step = draft.steps[0]
        failed_results = [
            VerifyResult(
                session_id="s1",
                verify_id=current_step.verify[0].verify_id,
                verify_type="pod_running",
                passed=False,
                failure_reason=FailureReason.VERIFIER_CREDENTIAL_MISSING.value,
            )
        ]
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=0,
            last_verify_results=failed_results,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        reason = data["steps"][0]["check_summary"]["failure_reason"]
        assert reason == FailureReason.VERIFIER_CREDENTIAL_MISSING.value

    def test_all_steps_completed_no_current(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-prog-7", step_count=2)
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=2,  # past all steps
            completed_step_ids=["step-1", "step-2"],
            ready_to_complete=True,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["current_step_id"] is None
        for step in data["steps"]:
            assert step["status"] == "passed"

    def test_no_step_check_summary_for_non_active_session(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-prog-8", step_count=1)
        dr.put(draft)
        vr = VerifyResult(
            session_id="s1",
            verify_id=draft.steps[0].verify[0].verify_id,
            verify_type="pod_running",
            passed=True,
        )
        sess = _make_session(
            draft.lab_id, "alice",
            session_status=LabSessionStatus.LAB_CLOSED,
            last_verify_results=[vr],
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        # check_summary should be None since session is not LAB_ACTIVE
        assert data["steps"][0]["check_summary"] is None


# ===========================================================================
# D. Completion availability
# ===========================================================================


class TestCompletionAvailability:
    def test_ready_to_complete_enables_can_complete(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-comp-1")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_ACTIVE,
            ready_to_complete=True,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["action_availability"]["can_complete"] is True

    def test_completed_session_cannot_complete_again(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-comp-2")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_COMPLETED,
            ready_to_complete=True,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["action_availability"]["can_complete"] is False

    def test_closed_session_cannot_abort(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-comp-3")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", LabSessionStatus.LAB_CLOSED)
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["action_availability"]["can_abort"] is False

    def test_aborted_session_shows_both_disabled(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-comp-4")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", LabSessionStatus.LAB_ABORTED)
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        aa = data["action_availability"]
        assert aa["can_complete"] is False
        assert aa["can_abort"] is False

    def test_disabled_reasons_populated_when_not_ready(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-comp-5")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", ready_to_complete=False)
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        reasons = data["action_availability"]["disabled_reasons"]
        codes = {r["code"] for r in reasons}
        assert "NOT_READY_TO_COMPLETE" in codes

    def test_start_failed_session_cannot_check_or_complete(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-comp-6")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_START_FAILED,
            failure_reason=FailureReason.NAMESPACE_CREATE_FAILED.value,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        aa = data["action_availability"]
        assert aa["can_check_current_step"] is False
        assert aa["can_complete"] is False


# ===========================================================================
# E. Cleanup failure / VM tainted
# ===========================================================================


class TestCleanupFailureAndTaint:
    def test_cleanup_failed_shows_issue(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-clean-1")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_CLEANUP_FAILED,
            failure_reason=FailureReason.NAMESPACE_CLEANUP_FAILED.value,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        issue_codes = {i["code"] for i in data["issues"]}
        assert "CLEANUP_FAILED" in issue_codes

    def test_vm_tainted_flag_set_on_cleanup_failure(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-clean-2")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_CLEANUP_FAILED,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["runtime_summary"]["tainted"] is True

    def test_no_stack_trace_in_cleanup_issue_message(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-clean-3")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_CLEANUP_FAILED,
            failure_reason="Traceback (most recent call last): File something.py",
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        # failure_reason in runtime_summary must be sanitized
        _assert_no_sensitive(data["runtime_summary"])
        _assert_no_sensitive(data["issues"])

    def test_cleanup_success_sets_cleanup_status_closed(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-clean-4")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_CLOSED,
            cleanup_verified=True,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert data["runtime_summary"]["cleanup_status"] == "verified"

    def test_cleanup_failed_vm_tainted_disabled_reason(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-clean-5")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_CLEANUP_FAILED,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        reason_codes = {r["code"] for r in data["action_availability"]["disabled_reasons"]}
        assert "VM_TAINTED" in reason_codes


# ===========================================================================
# F. Permissions
# ===========================================================================


class TestPermissions:
    def test_owner_can_see_snapshot(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-perm-1")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")

        assert resp.status_code == 200

    def test_stranger_cannot_see_snapshot(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-perm-2")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="mallory") as client:
            resp = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")

        assert resp.status_code == 403

    def test_missing_session_returns_404(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()

        with _snapshot_ctx(dr, sr, user="alice") as client:
            resp = client.get(f"/api/lab-sessions/{uuid.uuid4()}/snapshot")

        assert resp.status_code == 404

    def test_unauthenticated_list_returns_4xx(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/lab-sessions")
        assert resp.status_code in (401, 403)

    def test_unauthenticated_snapshot_returns_4xx(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/lab-sessions/{uuid.uuid4()}/snapshot")
        assert resp.status_code in (401, 403)

    def test_admin_can_see_any_snapshot(self) -> None:
        """Admin user (is_admin=True) may read another user's snapshot."""
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-perm-3")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        # Patch is_admin by returning True for the admin user
        from backend.auth import auth_manager

        original = auth_manager.is_admin
        auth_manager.is_admin = lambda u: u == "admin"  # type: ignore[method-assign]
        try:
            with _snapshot_ctx(dr, sr, user="admin") as client:
                resp = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")
        finally:
            auth_manager.is_admin = original  # type: ignore[method-assign]

        assert resp.status_code == 200


# ===========================================================================
# G. Safety (no credential leak)
# ===========================================================================


class TestSafety:
    def test_session_state_has_no_credentials(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-safe-1")
        dr.put(draft)
        # Simulate a session whose failure_reason contains a secret-like string
        # (should be redacted by sanitize_text)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_START_FAILED,
            failure_reason="credential_missing: token=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.fake",
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        _assert_no_sensitive(data)

    def test_no_kubeconfig_in_snapshot(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-safe-2")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        payload_str = str(data)
        assert "kubeconfig" not in payload_str.lower() or "[REDACTED]" in payload_str

    def test_no_vm_id_in_snapshot(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-safe-3")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        assert "vm_id" not in data

    def test_no_raw_exception_repr_in_failure_reason(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-safe-4")
        dr.put(draft)
        sess = _make_session(
            draft.lab_id, "alice",
            LabSessionStatus.LAB_START_FAILED,
            failure_reason=FailureReason.NAMESPACE_CREATE_FAILED.value,
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        _assert_no_sensitive(data)

    def test_check_summary_safe_message_no_internal_detail(self) -> None:
        """safe_message must never contain kubeconfig / token / stack trace."""
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-safe-5", step_count=1)
        dr.put(draft)
        vr = VerifyResult(
            session_id="s1",
            verify_id=draft.steps[0].verify[0].verify_id,
            verify_type="pod_running",
            passed=False,
            failure_reason=FailureReason.VERIFIER_CREDENTIAL_MISSING.value,
            detail="secret: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        )
        sess = _make_session(
            draft.lab_id, "alice",
            current_step_index=0,
            last_verify_results=[vr],
        )
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        _assert_no_sensitive(data["steps"][0]["check_summary"])

    def test_list_response_no_sensitive_data(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-safe-6")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get("/api/lab-sessions").json()

        _assert_no_sensitive(data)

    def test_no_verifier_credential_in_snapshot(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-safe-7")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            data = client.get(f"/api/lab-sessions/{sess.session_id}/snapshot").json()

        payload_str = str(data)
        for kw in ("private_key", "bearer", "verifier_identity"):
            assert kw not in payload_str.lower()


# ===========================================================================
# H. Regression (read-only invariants)
# ===========================================================================


class TestRegression:
    def test_get_list_does_not_start_lab(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        original_count = len(sr._store)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            client.get("/api/lab-sessions")

        assert len(sr._store) == original_count

    def test_get_snapshot_does_not_start_lab(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-reg-1")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)
        original_state = sess.lab_session_status

        with _snapshot_ctx(dr, sr, user="alice") as client:
            client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")

        # Session state must be unchanged
        assert sr._store[sess.session_id].lab_session_status == original_state

    def test_get_snapshot_does_not_complete_session(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-reg-2")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", ready_to_complete=True)
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")

        assert sr._store[sess.session_id].lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_get_snapshot_does_not_abort_session(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-reg-3")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")

        assert sr._store[sess.session_id].lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_get_snapshot_does_not_step_check(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-reg-4")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice", current_step_index=0)
        sr.put(sess)
        original_verify_results = list(sess.last_verify_results)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")

        stored = sr._store[sess.session_id]
        assert stored.last_verify_results == original_verify_results
        assert stored.current_step_index == 0

    def test_get_snapshot_does_not_run_cleanup(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-reg-5")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)

        with _snapshot_ctx(dr, sr, user="alice") as client:
            client.get(f"/api/lab-sessions/{sess.session_id}/snapshot")

        # Must still be active — no cleanup triggered
        assert sr._store[sess.session_id].lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_existing_tests_not_broken(self) -> None:
        """Smoke: the test module imports cleanly without side effects."""
        from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService
        assert LearnerSessionSnapshotService is not None


# ===========================================================================
# Unit tests for internal helpers
# ===========================================================================


class TestSnapshotServiceUnit:
    def test_build_snapshot_raises_not_found(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        svc = LearnerSessionSnapshotService(
            session_repo=sr,  # type: ignore[arg-type]
            draft_repo=dr,    # type: ignore[arg-type]
        )
        with pytest.raises(SnapshotNotFound):
            svc.build_snapshot("nonexistent", "alice")

    def test_build_snapshot_raises_access_denied(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-unit-1")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)
        svc = LearnerSessionSnapshotService(
            session_repo=sr,  # type: ignore[arg-type]
            draft_repo=dr,    # type: ignore[arg-type]
        )
        with pytest.raises(SnapshotAccessDenied):
            svc.build_snapshot(sess.session_id, "mallory", is_admin=False)

    def test_admin_bypasses_access_denied(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-unit-2")
        dr.put(draft)
        sess = _make_session(draft.lab_id, "alice")
        sr.put(sess)
        svc = LearnerSessionSnapshotService(
            session_repo=sr,  # type: ignore[arg-type]
            draft_repo=dr,    # type: ignore[arg-type]
        )
        snapshot = svc.build_snapshot(sess.session_id, "admin", is_admin=True)
        assert snapshot.session_id == sess.session_id

    def test_list_my_sessions_returns_only_own(self) -> None:
        dr = _MemDraftRepo()
        sr = _MemSessionRepo()
        draft = _make_draft(lab_id="lab-unit-3")
        dr.put(draft)
        alice = _make_session(draft.lab_id, "alice")
        bob = _make_session(draft.lab_id, "bob")
        sr.put(alice)
        sr.put(bob)
        svc = LearnerSessionSnapshotService(
            session_repo=sr,  # type: ignore[arg-type]
            draft_repo=dr,    # type: ignore[arg-type]
        )
        items = svc.list_my_sessions("alice")
        assert len(items) == 1
        assert items[0].session_id == alice.session_id

    def test_snapshot_draft_unavailable_shows_unknown_title(self) -> None:
        sr = _MemSessionRepo()
        dr = _MemDraftRepo()   # No draft in repo
        sess = _make_session("missing-lab", "alice")
        sr.put(sess)
        svc = LearnerSessionSnapshotService(
            session_repo=sr,  # type: ignore[arg-type]
            draft_repo=dr,    # type: ignore[arg-type]
        )
        snapshot = svc.build_snapshot(sess.session_id, "alice")
        assert snapshot.title == "Unknown Lab"
        assert snapshot.steps == []
