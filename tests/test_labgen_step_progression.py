"""
Tests for backend/labgen/step_progression_service.py — StepProgressionService,
StepCheckResponse, and POST /api/lab-sessions/{id}/steps/{step_id}/check.
"""

from __future__ import annotations

from typing import Optional

import pytest

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
from backend.labgen.step_progression_service import (
    StepAccessDenied,
    StepCheckResponse,
    StepDraftUnavailable,
    StepNotCurrent,
    StepProgressionService,
    StepSessionNotActive,
    StepSessionNotFound,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _FakeSessionRepo:
    def __init__(self, sessions: Optional[dict[str, LabSessionState]] = None) -> None:
        self._sessions: dict[str, LabSessionState] = dict(sessions or {})

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._sessions.get(session_id)

    def update(self, session: LabSessionState) -> LabSessionState:
        self._sessions[session.session_id] = session
        return session

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._sessions.values() if s.student_username == username]

    def create(self, session: LabSessionState) -> LabSessionState:
        self._sessions[session.session_id] = session
        return session


class _FakeDraftRepo:
    def __init__(self, drafts: Optional[dict[str, LabDraft]] = None) -> None:
        self._drafts: dict[str, LabDraft] = dict(drafts or {})

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._drafts.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._drafts[draft.lab_id] = draft
        return draft


class _FakeVerifierSvc:
    """Configurable stub — returns per-verify_id results or a default."""

    def __init__(
        self,
        results: Optional[dict[str, VerifyResult]] = None,
        default_passed: bool = True,
    ) -> None:
        self._results: dict[str, VerifyResult] = results or {}
        self._default = default_passed

    def check(self, session_id: str, template: VerifyTemplate) -> VerifyResult:
        if template.verify_id in self._results:
            return self._results[template.verify_id]
        return VerifyResult(
            session_id=session_id,
            verify_id=template.verify_id,
            verify_type=template.type.value,
            passed=self._default,
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "sess-1",
    lab_id: str = "lab-1",
    vm_id: str = "501",
    username: str = "alice",
    status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
    namespace: str = "lab-sess-1",
    current_step_index: int = 0,
) -> LabSessionState:
    s = LabSessionState(
        session_id=session_id,
        lab_id=lab_id,
        vm_id=vm_id,
        student_username=username,
        lab_session_status=status,
        namespace=namespace,
    )
    s.current_step_index = current_step_index
    return s


def _make_verify_template(verify_id: str) -> VerifyTemplate:
    return VerifyTemplate(
        verify_id=verify_id,
        type=VerifyType.NAMESPACE_EXISTS,
        namespace="{{lab_namespace}}",
        name="placeholder",
    )


def _make_step(
    step_id: str = "step-1",
    order: int = 1,
    verify_ids: Optional[list[str]] = None,
) -> Step:
    return Step(
        step_id=step_id,
        order=order,
        why="test why",
        do="test do",
        observe="test observe",
        explain=ExplainField(concept="test", observation="test"),
        verify=[_make_verify_template(vid) for vid in (verify_ids or [])],
    )


def _make_draft(
    lab_id: str = "lab-1",
    steps: Optional[list[Step]] = None,
    published: bool = True,
) -> LabDraft:
    return LabDraft(
        lab_id=lab_id,
        source_article_id="art-1",
        title="Test Lab",
        description="Test",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=steps if steps is not None else [_make_step()],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.PUBLISHED if published else PublishStatus.DRAFT,
    )


def _make_svc(
    session: Optional[LabSessionState] = None,
    draft: Optional[LabDraft] = None,
    verifier_default_passed: bool = True,
    verifier_results: Optional[dict[str, VerifyResult]] = None,
) -> StepProgressionService:
    sessions = {session.session_id: session} if session else {}
    drafts = {draft.lab_id: draft} if draft else {}
    return StepProgressionService(
        session_repo=_FakeSessionRepo(sessions),
        draft_repo=_FakeDraftRepo(drafts),
        verifier_svc=_FakeVerifierSvc(verifier_results, verifier_default_passed),
    )


# ===========================================================================
# StepCheckResponse model
# ===========================================================================


class TestStepCheckResponseModel:
    def test_default_schema_version(self) -> None:
        r = StepCheckResponse(
            session_id="s",
            step_id="st",
            all_passed=True,
            advanced=True,
            ready_to_complete=False,
            verify_results=[],
        )
        assert r.schema_version == "1.0"

    def test_empty_verify_results_default(self) -> None:
        r = StepCheckResponse(
            session_id="s",
            step_id="st",
            all_passed=False,
            advanced=False,
            ready_to_complete=False,
            verify_results=[],
        )
        assert r.verify_results == []

    def test_nested_verify_result(self) -> None:
        vr = VerifyResult(
            session_id="s",
            verify_id="v",
            verify_type="namespace_exists",
            passed=True,
        )
        r = StepCheckResponse(
            session_id="s",
            step_id="st",
            all_passed=True,
            advanced=True,
            ready_to_complete=False,
            verify_results=[vr],
        )
        assert len(r.verify_results) == 1
        assert r.verify_results[0].passed is True


# ===========================================================================
# Service guards
# ===========================================================================


class TestStepProgressionServiceGuards:
    def test_session_not_found(self) -> None:
        svc = _make_svc()
        with pytest.raises(StepSessionNotFound):
            svc.check_step("missing", "step-1", "alice")

    def test_session_not_active_completed(self) -> None:
        session = _make_session(status=LabSessionStatus.LAB_COMPLETED)
        draft = _make_draft()
        svc = _make_svc(session, draft)
        with pytest.raises(StepSessionNotActive):
            svc.check_step(session.session_id, "step-1", "alice")

    def test_session_not_active_closed(self) -> None:
        session = _make_session(status=LabSessionStatus.LAB_CLOSED)
        draft = _make_draft()
        svc = _make_svc(session, draft)
        with pytest.raises(StepSessionNotActive):
            svc.check_step(session.session_id, "step-1", "alice")

    def test_session_not_active_aborted(self) -> None:
        session = _make_session(status=LabSessionStatus.LAB_ABORTED)
        draft = _make_draft()
        svc = _make_svc(session, draft)
        with pytest.raises(StepSessionNotActive):
            svc.check_step(session.session_id, "step-1", "alice")

    def test_access_denied_wrong_owner(self) -> None:
        session = _make_session(username="alice")
        draft = _make_draft()
        svc = _make_svc(session, draft)
        with pytest.raises(StepAccessDenied):
            svc.check_step(session.session_id, "step-1", "bob")

    def test_draft_not_found(self) -> None:
        session = _make_session()
        svc = StepProgressionService(
            session_repo=_FakeSessionRepo({session.session_id: session}),
            draft_repo=_FakeDraftRepo({}),
            verifier_svc=_FakeVerifierSvc(),
        )
        with pytest.raises(StepDraftUnavailable):
            svc.check_step(session.session_id, "step-1", "alice")

    def test_draft_not_published(self) -> None:
        session = _make_session()
        draft = _make_draft(published=False)
        svc = _make_svc(session, draft)
        with pytest.raises(StepDraftUnavailable):
            svc.check_step(session.session_id, "step-1", "alice")

    def test_no_steps_raises_draft_unavailable(self) -> None:
        session = _make_session()
        draft = _make_draft(steps=[])
        svc = _make_svc(session, draft)
        with pytest.raises(StepDraftUnavailable):
            svc.check_step(session.session_id, "step-1", "alice")

    def test_step_not_current_wrong_id(self) -> None:
        session = _make_session()
        draft = _make_draft(steps=[_make_step(step_id="step-1")])
        svc = _make_svc(session, draft)
        with pytest.raises(StepNotCurrent):
            svc.check_step(session.session_id, "step-WRONG", "alice")

    def test_all_steps_done_raises_step_not_current(self) -> None:
        session = _make_session(current_step_index=2)
        draft = _make_draft(steps=[_make_step("s1"), _make_step("s2", order=2)])
        svc = _make_svc(session, draft)
        with pytest.raises(StepNotCurrent):
            svc.check_step(session.session_id, "s1", "alice")


# ===========================================================================
# Service progression logic
# ===========================================================================


class TestStepProgressionServiceProgression:
    def test_all_pass_returns_advanced_true(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert result.advanced is True
        assert result.all_passed is True

    def test_all_pass_advances_step_index(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        svc.check_step(session.session_id, "step-1", "alice")
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert updated.current_step_index == 1

    def test_all_pass_adds_to_completed_ids(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        svc.check_step(session.session_id, "step-1", "alice")
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert "step-1" in updated.completed_step_ids

    def test_fail_does_not_advance(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=False)
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert result.all_passed is False
        assert result.advanced is False
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert updated.current_step_index == 0

    def test_fail_does_not_add_to_completed_ids(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=False)
        svc.check_step(session.session_id, "step-1", "alice")
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert "step-1" not in updated.completed_step_ids

    def test_no_verify_templates_auto_advances(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=[])
        draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
        svc = _make_svc(session, draft)
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert result.all_passed is True
        assert result.advanced is True
        assert result.verify_results == []

    def test_last_step_sets_ready_to_complete(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert result.ready_to_complete is True
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert updated.ready_to_complete is True

    def test_non_last_step_not_ready_to_complete(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert result.ready_to_complete is False

    def test_status_stays_lab_active_after_last_step(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        svc.check_step(session.session_id, "step-1", "alice")
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert updated.lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_last_verify_results_saved_on_pass(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1", "v2"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        svc.check_step(session.session_id, "step-1", "alice")
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert len(updated.last_verify_results) == 2

    def test_last_verify_results_saved_on_fail(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=False)
        svc.check_step(session.session_id, "step-1", "alice")
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert len(updated.last_verify_results) == 1
        assert updated.last_verify_results[0].passed is False

    def test_partial_fail_no_advance(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v-pass", "v-fail"])
        draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
        svc = _make_svc(
            session,
            draft,
            verifier_default_passed=True,
            verifier_results={
                "v-fail": VerifyResult(
                    session_id=session.session_id,
                    verify_id="v-fail",
                    verify_type="namespace_exists",
                    passed=False,
                )
            },
        )
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert result.all_passed is False
        assert result.advanced is False
        updated = svc._session_repo.get(session.session_id)
        assert updated is not None
        assert updated.current_step_index == 0

    def test_multi_step_progression(self) -> None:
        session = _make_session()
        steps = [
            _make_step("s1", order=1, verify_ids=["v1"]),
            _make_step("s2", order=2, verify_ids=["v2"]),
        ]
        draft = _make_draft(steps=steps)
        svc = _make_svc(session, draft, verifier_default_passed=True)

        r1 = svc.check_step(session.session_id, "s1", "alice")
        assert r1.advanced is True
        assert r1.ready_to_complete is False

        r2 = svc.check_step(session.session_id, "s2", "alice")
        assert r2.advanced is True
        assert r2.ready_to_complete is True

    def test_result_verify_results_match_template_count(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1", "v2", "v3"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert len(result.verify_results) == 3

    def test_response_fields_on_success(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=True)
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert result.session_id == session.session_id
        assert result.step_id == "step-1"
        assert result.schema_version == "1.0"

    def test_response_fields_on_fail(self) -> None:
        session = _make_session()
        step = _make_step(step_id="step-1", verify_ids=["v1"])
        draft = _make_draft(steps=[step])
        svc = _make_svc(session, draft, verifier_default_passed=False)
        result = svc.check_step(session.session_id, "step-1", "alice")
        assert result.session_id == session.session_id
        assert result.step_id == "step-1"
        assert result.ready_to_complete is False


# ===========================================================================
# HTTP endpoint — POST /api/lab-sessions/{id}/steps/{step_id}/check
# ===========================================================================


class _FakeSvc:
    def __init__(
        self,
        exc: Optional[Exception] = None,
        result: Optional[StepCheckResponse] = None,
    ) -> None:
        self._exc = exc
        self._result = result

    def check_step(self, session_id: str, step_id: str, username: str) -> StepCheckResponse:
        if self._exc is not None:
            raise self._exc
        return self._result or StepCheckResponse(
            session_id=session_id,
            step_id=step_id,
            all_passed=True,
            advanced=True,
            ready_to_complete=False,
            verify_results=[],
        )


class TestStepProgressionRoute:
    _URL = "/api/lab-sessions/sess-1/steps/step-1/check"

    def test_401_no_auth(self) -> None:
        from fastapi.testclient import TestClient
        from backend.main import app

        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post(self._URL)
        assert resp.status_code == 401

    def test_200_success(self) -> None:
        from fastapi.testclient import TestClient
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_step_progression_service
        from backend.main import app

        fake = _FakeSvc()
        app.dependency_overrides[get_current_user] = lambda: "alice"
        app.dependency_overrides[get_step_progression_service] = lambda: fake
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.post(self._URL)
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-1"
        assert data["step_id"] == "step-1"
        assert data["all_passed"] is True
        assert data["advanced"] is True
        assert data["ready_to_complete"] is False

    def test_404_session_not_found(self) -> None:
        from fastapi.testclient import TestClient
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_step_progression_service
        from backend.main import app

        fake = _FakeSvc(exc=StepSessionNotFound("sess-1"))
        app.dependency_overrides[get_current_user] = lambda: "alice"
        app.dependency_overrides[get_step_progression_service] = lambda: fake
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.post(self._URL)
        app.dependency_overrides.clear()

        assert resp.status_code == 404

    def test_409_session_not_active(self) -> None:
        from fastapi.testclient import TestClient
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_step_progression_service
        from backend.main import app

        fake = _FakeSvc(exc=StepSessionNotActive("status=LAB_COMPLETED"))
        app.dependency_overrides[get_current_user] = lambda: "alice"
        app.dependency_overrides[get_step_progression_service] = lambda: fake
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.post(self._URL)
        app.dependency_overrides.clear()

        assert resp.status_code == 409

    def test_403_access_denied(self) -> None:
        from fastapi.testclient import TestClient
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_step_progression_service
        from backend.main import app

        fake = _FakeSvc(exc=StepAccessDenied("sess-1"))
        app.dependency_overrides[get_current_user] = lambda: "alice"
        app.dependency_overrides[get_step_progression_service] = lambda: fake
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.post(self._URL)
        app.dependency_overrides.clear()

        assert resp.status_code == 403

    def test_409_draft_unavailable(self) -> None:
        from fastapi.testclient import TestClient
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_step_progression_service
        from backend.main import app

        fake = _FakeSvc(exc=StepDraftUnavailable("lab-1"))
        app.dependency_overrides[get_current_user] = lambda: "alice"
        app.dependency_overrides[get_step_progression_service] = lambda: fake
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.post(self._URL)
        app.dependency_overrides.clear()

        assert resp.status_code == 409

    def test_409_step_not_current(self) -> None:
        from fastapi.testclient import TestClient
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_step_progression_service
        from backend.main import app

        fake = _FakeSvc(exc=StepNotCurrent("current step is 'step-2'"))
        app.dependency_overrides[get_current_user] = lambda: "alice"
        app.dependency_overrides[get_step_progression_service] = lambda: fake
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.post(self._URL)
        app.dependency_overrides.clear()

        assert resp.status_code == 409

    def test_response_contains_verify_results(self) -> None:
        from fastapi.testclient import TestClient
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_step_progression_service
        from backend.main import app

        vr = VerifyResult(
            session_id="sess-1",
            verify_id="v1",
            verify_type="namespace_exists",
            passed=True,
        )
        fake_result = StepCheckResponse(
            session_id="sess-1",
            step_id="step-1",
            all_passed=True,
            advanced=True,
            ready_to_complete=False,
            verify_results=[vr],
        )
        fake = _FakeSvc(result=fake_result)
        app.dependency_overrides[get_current_user] = lambda: "alice"
        app.dependency_overrides[get_step_progression_service] = lambda: fake
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.post(self._URL)
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["verify_results"]) == 1
        assert data["verify_results"][0]["verify_id"] == "v1"
        assert data["verify_results"][0]["passed"] is True
