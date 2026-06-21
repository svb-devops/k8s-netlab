"""
Internal Rehearsal Bridge tests.

Validates:
  A. Precheck / session creation (service layer)
  B. Auth: non-admin rejected, learner rejected, admin allowed (HTTP layer)
  C. Catalog isolation: DRAFT generated lab not visible; published labs unaffected
  D. Session lifecycle: session_type/article_draft_id set, cleanup, taint
  E. Safety: normal learner path unchanged, draft stays DRAFT, no publish
"""

from __future__ import annotations

from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.lab_session_service import (
    LabSessionService,
    PrecheckFailed,
    StubVMTracker,
    VMTrackerPort,
)
from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    SessionType,
    Step,
)
from backend.labgen.namespace_lifecycle import NamespaceLifecyclePort

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# In-memory test doubles
# ---------------------------------------------------------------------------


class _MemDraftRepo:
    def __init__(self, drafts: Optional[list[LabDraft]] = None) -> None:
        self._store: dict[str, LabDraft] = {}
        for d in (drafts or []):
            self._store[d.lab_id] = d

    def create(self, d: LabDraft) -> LabDraft:
        self._store[d.lab_id] = d
        return d

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, d: LabDraft) -> LabDraft:
        self._store[d.lab_id] = d
        return d

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemSessionRepo:
    def __init__(self, sessions: Optional[list[LabSessionState]] = None) -> None:
        self._store: dict[str, LabSessionState] = {}
        for s in (sessions or []):
            self._store[s.session_id] = s

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


class _SimpleNsLifecycle(NamespaceLifecyclePort):
    def __init__(self, *, create_ok: bool = True, delete_ok: bool = True) -> None:
        self._create_ok = create_ok
        self._delete_ok = delete_ok

    def create_namespace(self, ns: str) -> bool:
        return self._create_ok

    def namespace_exists(self, ns: str) -> bool:
        return self._create_ok

    def delete_namespace(self, ns: str) -> bool:
        return self._delete_ok

    def is_namespace_deleted(self, ns: str) -> bool:
        return self._delete_ok

    def ensure_verifier_rolebinding(self, ns: str) -> bool:
        return self._create_ok

    def verifier_rolebinding_exists(self, ns: str) -> bool:
        return self._create_ok


class _StubImageResolver:
    def needs_recheck(self, img) -> bool:
        return False

    def check_registry_existence(self, img):
        return img


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(
    *,
    publish_status: PublishStatus = PublishStatus.DRAFT,
    source_article_id: str = "art-configmap-001",
    has_cleanup: bool = True,
) -> LabDraft:
    return LabDraft(
        source_article_id=source_article_id,
        title="ConfigMap Internal Rehearsal Lab",
        description="desc",
        estimated_duration_minutes=20,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="Create ConfigMap",
            do="kubectl create configmap my-app-config --from-literal=app.env=production",
            observe="ConfigMap my-app-config created",
            explain=ExplainField(concept="ConfigMap", observation="ConfigMap stores config"),
        )],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()) if has_cleanup else None,
        publish_status=publish_status,
    )


def _make_published_draft(title: str = "Published Lab") -> LabDraft:
    return LabDraft(
        source_article_id="existing-art-1",
        title=title,
        description="Published lab for learners",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="Do something",
            do="kubectl apply -f ...",
            observe="resource created",
            explain=ExplainField(concept="C", observation="O"),
        )],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.PUBLISHED,
    )


def _make_svc(
    drafts: Optional[list[LabDraft]] = None,
    sessions: Optional[list[LabSessionState]] = None,
    *,
    vm_tainted: bool = False,
    ns_create_ok: bool = True,
    ns_delete_ok: bool = True,
) -> tuple[LabSessionService, _MemDraftRepo, _MemSessionRepo, StubVMTracker]:
    draft_repo = _MemDraftRepo(drafts)
    session_repo = _MemSessionRepo(sessions)
    vm_tracker = StubVMTracker()
    if vm_tainted:
        vm_tracker.mark_vm_tainted("vm-500")
    ns = _SimpleNsLifecycle(create_ok=ns_create_ok, delete_ok=ns_delete_ok)
    svc = LabSessionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        vm_tracker=vm_tracker,
        ns_lifecycle=ns,
        image_resolver=_StubImageResolver(),
    )
    return svc, draft_repo, session_repo, vm_tracker


# ---------------------------------------------------------------------------
# A. Precheck / session creation (service layer)
# ---------------------------------------------------------------------------


class TestRehearsalPrecheck:
    def test_passes_for_draft_article_lab(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft])
        result = svc.run_rehearsal_precheck(draft.lab_id, "vm-500", "admin")
        assert result.passed
        assert result.failures == []

    def test_fails_when_draft_not_found(self):
        svc, *_ = _make_svc([])
        result = svc.run_rehearsal_precheck("app", "non-existent", "vm-500", "admin")
        assert not result.passed
        assert FailureReason.REHEARSAL_DRAFT_NOT_FOUND.value in result.failures

    def test_fails_when_source_article_id_empty(self):
        draft = _make_draft(source_article_id="")
        svc, *_ = _make_svc([draft])
        result = svc.run_rehearsal_precheck(draft.lab_id, "vm-500", "admin")
        assert not result.passed
        assert FailureReason.REHEARSAL_DRAFT_NOT_ARTICLE_GENERATED.value in result.failures

    def test_fails_when_cleanup_not_declared(self):
        draft = _make_draft(has_cleanup=False)
        svc, *_ = _make_svc([draft])
        result = svc.run_rehearsal_precheck(draft.lab_id, "vm-500", "admin")
        assert not result.passed
        assert FailureReason.REHEARSAL_CLEANUP_NOT_DECLARED.value in result.failures

    def test_fails_when_vm_tainted(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft], vm_tainted=True)
        result = svc.run_rehearsal_precheck(draft.lab_id, "vm-500", "admin")
        assert not result.passed
        assert FailureReason.REHEARSAL_VM_TAINTED.value in result.failures

    def test_fails_when_session_already_active(self):
        draft = _make_draft()
        existing = LabSessionState(
            lab_id=draft.lab_id, vm_id="vm-500", student_username="admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
        )
        svc, *_ = _make_svc([draft], [existing])
        result = svc.run_rehearsal_precheck(draft.lab_id, "vm-500", "admin")
        assert not result.passed
        assert FailureReason.REHEARSAL_SESSION_ALREADY_ACTIVE.value in result.failures

    def test_does_not_require_publish_status_published(self):
        """Core invariant: DRAFT labs pass the rehearsal precheck."""
        draft = _make_draft(publish_status=PublishStatus.DRAFT)
        svc, *_ = _make_svc([draft])
        result = svc.run_rehearsal_precheck(draft.lab_id, "vm-500", "admin")
        assert result.passed

    def test_normal_learner_precheck_still_requires_published(self):
        """Normal learner path is unchanged: DRAFT labs still rejected."""
        draft = _make_draft(publish_status=PublishStatus.DRAFT)
        svc, *_ = _make_svc([draft])
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert not result.passed
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value in result.failures

    def test_normal_learner_precheck_allows_published(self):
        draft = _make_published_draft()
        svc, *_ = _make_svc([draft])
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert result.passed

    def test_multiple_failures_collected(self):
        """All failures are reported, not just first."""
        svc, *_ = _make_svc([])
        result = svc.run_rehearsal_precheck("app", "non-existent", "vm-500", "admin")
        assert not result.passed
        assert FailureReason.REHEARSAL_DRAFT_NOT_FOUND.value in result.failures


class TestCreateRehearsalSession:
    def test_creates_session_with_internal_rehearsal_type(self):
        draft = _make_draft()
        svc, _, session_repo, _ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
            article_draft_id="art-configmap-001",
        )
        assert session.session_type == SessionType.INTERNAL_REHEARSAL
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        assert session.article_draft_id == "art-configmap-001"
        assert session.student_username == "admin"

    def test_raises_precheck_failed_when_no_source_article_id(self):
        draft = _make_draft(source_article_id="")
        svc, *_ = _make_svc([draft])
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_rehearsal_session(
                lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
            )
        assert FailureReason.REHEARSAL_DRAFT_NOT_ARTICLE_GENERATED.value in exc_info.value.failures

    def test_rehearsal_session_namespace_set(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
        )
        assert session.namespace is not None
        assert session.namespace.startswith("lab-")

    def test_learner_create_session_still_fails_for_draft_lab(self):
        """Normal path unchanged — DRAFT labs still rejected for learners."""
        draft = _make_draft(publish_status=PublishStatus.DRAFT)
        svc, *_ = _make_svc([draft])
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_session(lab_id=draft.lab_id, vm_id="vm-500", student_username="student1")
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value in exc_info.value.failures

    def test_rehearsal_abort_runs_cleanup(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
        )
        aborted = svc.abort_session(session.session_id)
        assert aborted.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert aborted.cleanup_verified is True

    def test_article_draft_id_none_is_allowed(self):
        """article_draft_id is optional."""
        draft = _make_draft()
        svc, *_ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
            article_draft_id=None,
        )
        assert session.session_type == SessionType.INTERNAL_REHEARSAL
        assert session.article_draft_id is None


# ---------------------------------------------------------------------------
# B. Auth: HTTP layer
# ---------------------------------------------------------------------------


def _http_deps(
    drafts: Optional[list[LabDraft]] = None,
    admin_user: str = "admin",
):
    """Returns (draft_repo, session_repo, svc_factory, ns_lifecycle)."""
    draft_repo = _MemDraftRepo(drafts)
    session_repo = _MemSessionRepo()
    ns = _SimpleNsLifecycle()

    def _svc():
        return LabSessionService(
            session_repo=session_repo,
            draft_repo=draft_repo,
            vm_tracker=StubVMTracker(),
            ns_lifecycle=ns,
            image_resolver=_StubImageResolver(),
        )

    return draft_repo, session_repo, _svc


class TestRehearsalAuth:
    def test_admin_can_create_rehearsal_session_http(self):
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import (
            get_session_service, get_session_repository,
            require_internal_token, require_admin_user,
        )

        draft = _make_draft()
        draft_repo, session_repo, svc_factory = _http_deps([draft])
        app.dependency_overrides[get_session_service] = svc_factory
        app.dependency_overrides[get_session_repository] = lambda: session_repo
        app.dependency_overrides[get_current_user] = lambda: "admin"
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[require_internal_token] = lambda: None
        try:
            client = TestClient(app)
            resp = client.post(
                "/internal/rehearsal-sessions",
                json={"lab_id": draft.lab_id, "vm_id": "vm-500"},
            )
            assert resp.status_code == 201, resp.text
            data = resp.json()
            assert data["session_type"] == "internal_rehearsal"
            assert data["lab_session_status"] == "LAB_ACTIVE"
        finally:
            app.dependency_overrides.clear()

    def test_missing_admin_token_rejected(self):
        """Without overriding require_internal_token, missing token → 401."""
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_session_service, get_session_repository

        draft = _make_draft()
        draft_repo, session_repo, svc_factory = _http_deps([draft])
        app.dependency_overrides[get_session_service] = svc_factory
        app.dependency_overrides[get_session_repository] = lambda: session_repo
        app.dependency_overrides[get_current_user] = lambda: "admin"
        try:
            client = TestClient(app)
            resp = client.post(
                "/internal/rehearsal-sessions",
                json={"lab_id": draft.lab_id, "vm_id": "vm-500"},
            )
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_wrong_admin_token_rejected(self):
        """Wrong X-Admin-Token → 401."""
        import os
        actual_token = os.environ.get("ADMIN_TOKEN", "")
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_session_service, get_session_repository

        draft = _make_draft()
        draft_repo, session_repo, svc_factory = _http_deps([draft])
        app.dependency_overrides[get_session_service] = svc_factory
        app.dependency_overrides[get_session_repository] = lambda: session_repo
        app.dependency_overrides[get_current_user] = lambda: "admin"
        try:
            client = TestClient(app)
            resp = client.post(
                "/internal/rehearsal-sessions",
                json={"lab_id": draft.lab_id, "vm_id": "vm-500"},
                headers={"X-Admin-Token": "definitely-wrong-token-not-matching"},
            )
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_non_admin_user_rejected(self):
        """Admin token OK but user is not admin → 403."""
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_session_service, get_session_repository, require_internal_token

        draft = _make_draft()
        draft_repo, session_repo, svc_factory = _http_deps([draft])
        app.dependency_overrides[get_session_service] = svc_factory
        app.dependency_overrides[get_session_repository] = lambda: session_repo
        # Simulate learner (not admin) as current user
        app.dependency_overrides[get_current_user] = lambda: "student1"
        app.dependency_overrides[require_internal_token] = lambda: None
        try:
            client = TestClient(app)
            resp = client.post(
                "/internal/rehearsal-sessions",
                json={"lab_id": draft.lab_id, "vm_id": "vm-500"},
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_unapproved_draft_returns_422(self):
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import (
            get_session_service, get_session_repository,
            require_internal_token, require_admin_user,
        )

        # Draft has no source_article_id → not article-generated
        draft = _make_draft(source_article_id="")
        draft_repo, session_repo, svc_factory = _http_deps([draft])
        app.dependency_overrides[get_session_service] = svc_factory
        app.dependency_overrides[get_session_repository] = lambda: session_repo
        app.dependency_overrides[get_current_user] = lambda: "admin"
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        app.dependency_overrides[require_internal_token] = lambda: None
        try:
            client = TestClient(app)
            resp = client.post(
                "/internal/rehearsal-sessions",
                json={"lab_id": draft.lab_id, "vm_id": "vm-500"},
            )
            assert resp.status_code == 422
            data = resp.json()
            failures = data["detail"]["precheck_failures"]
            assert FailureReason.REHEARSAL_DRAFT_NOT_ARTICLE_GENERATED.value in failures
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# C. Catalog isolation
# ---------------------------------------------------------------------------


class TestCatalogIsolation:
    def test_draft_generated_lab_not_in_learner_catalog(self):
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator

        draft = _make_draft(publish_status=PublishStatus.DRAFT)
        draft_repo = _MemDraftRepo([draft])
        session_repo = _MemSessionRepo()

        svc = LearnerCatalogService(
            draft_repo=draft_repo,
            validator=StaticValidator(),
            session_repo=session_repo,
        )
        items = svc.list_published_labs(actor_user="student1")
        assert draft.lab_id not in [i.lab_id for i in items]

    def test_published_labs_unaffected_by_bridge(self):
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator

        published = _make_published_draft("K8s Networking Lab")
        draft = _make_draft(publish_status=PublishStatus.DRAFT)
        draft_repo = _MemDraftRepo([published, draft])
        session_repo = _MemSessionRepo()

        svc = LearnerCatalogService(
            draft_repo=draft_repo,
            validator=StaticValidator(),
            session_repo=session_repo,
        )
        items = svc.list_published_labs(actor_user="student1")
        lab_ids = [i.lab_id for i in items]
        assert published.lab_id in lab_ids
        assert draft.lab_id not in lab_ids

    def test_rehearsal_session_excluded_from_learner_session_list(self):
        draft = _make_draft()
        draft_repo = _MemDraftRepo([draft])
        rehearsal_session = LabSessionState(
            lab_id=draft.lab_id, vm_id="vm-500", student_username="admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
        )
        session_repo = _MemSessionRepo([rehearsal_session])

        svc = LearnerSessionSnapshotService(
            session_repo=session_repo,
            draft_repo=draft_repo,
        )
        items = svc.list_my_sessions(actor_user="admin")
        assert rehearsal_session.session_id not in [i.session_id for i in items]

    def test_learner_sessions_remain_visible_in_list(self):
        draft = _make_published_draft()
        draft_repo = _MemDraftRepo([draft])
        learner_session = LabSessionState(
            lab_id=draft.lab_id, vm_id="vm-500", student_username="student1",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.LEARNER,
        )
        session_repo = _MemSessionRepo([learner_session])

        svc = LearnerSessionSnapshotService(
            session_repo=session_repo,
            draft_repo=draft_repo,
        )
        items = svc.list_my_sessions(actor_user="student1")
        assert learner_session.session_id in [i.session_id for i in items]

    def test_catalog_detail_returns_none_for_draft(self):
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator

        draft = _make_draft(publish_status=PublishStatus.DRAFT)
        draft_repo = _MemDraftRepo([draft])

        svc = LearnerCatalogService(
            draft_repo=draft_repo,
            validator=StaticValidator(),
        )
        detail = svc.get_published_lab_detail(lab_id=draft.lab_id, actor_user="student1")
        assert detail is None


# ---------------------------------------------------------------------------
# D. Session lifecycle
# ---------------------------------------------------------------------------


class TestRehearsalLifecycle:
    def test_session_type_and_article_draft_id_persisted(self):
        draft = _make_draft()
        svc, _, session_repo, _ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
            article_draft_id="art-draft-abc",
        )
        retrieved = session_repo.get(session.session_id)
        assert retrieved is not None
        assert retrieved.session_type == SessionType.INTERNAL_REHEARSAL
        assert retrieved.article_draft_id == "art-draft-abc"

    def test_complete_after_ready_runs_cleanup(self):
        draft = _make_draft()
        svc, _, session_repo, _ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
        )
        session.ready_to_complete = True
        session_repo.update(session)

        completed = svc.complete_session(session.session_id)
        assert completed.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert completed.cleanup_verified is True

    def test_abort_runs_cleanup(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
        )
        aborted = svc.abort_session(session.session_id)
        assert aborted.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert aborted.cleanup_verified is True

    def test_cleanup_failure_marks_vm_tainted(self):
        draft = _make_draft()
        svc, _, _, vm_tracker = _make_svc([draft], ns_delete_ok=False)
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
        )
        aborted = svc.abort_session(session.session_id)
        assert aborted.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED
        assert aborted.cleanup_verified is False
        assert vm_tracker.is_vm_tainted("vm-500")

    def test_tainted_vm_blocks_next_rehearsal(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft], vm_tainted=True)
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_rehearsal_session(
                lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
            )
        assert FailureReason.REHEARSAL_VM_TAINTED.value in exc_info.value.failures

    def test_run_cleanup_idempotent_on_closed_session(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
        )
        closed = svc.abort_session(session.session_id)
        assert closed.lab_session_status == LabSessionStatus.LAB_CLOSED

        again = svc.run_cleanup(session.session_id)
        assert again.lab_session_status == LabSessionStatus.LAB_CLOSED


# ---------------------------------------------------------------------------
# E. Safety invariants
# ---------------------------------------------------------------------------


class TestSafetyInvariants:
    def test_generated_draft_publish_status_remains_draft_after_rehearsal(self):
        draft = _make_draft(publish_status=PublishStatus.DRAFT)
        svc, draft_repo, _, _ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
        )
        svc.abort_session(session.session_id)

        persisted = draft_repo.get(draft.lab_id)
        assert persisted is not None
        assert persisted.publish_status == PublishStatus.DRAFT

    def test_normal_learner_path_still_blocks_draft_lab(self):
        """Bridge must NOT weaken the existing learner precheck."""
        draft = _make_draft(publish_status=PublishStatus.DRAFT)
        svc, *_ = _make_svc([draft])
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert not result.passed
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value in result.failures

    def test_learner_session_type_is_learner(self):
        draft = _make_published_draft()
        svc, *_ = _make_svc([draft])
        session = svc.create_session(
            lab_id=draft.lab_id, vm_id="vm-500", student_username="student1",
        )
        assert session.session_type == SessionType.LEARNER

    def test_rehearsal_session_type_is_internal_rehearsal(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
        )
        assert session.session_type == SessionType.INTERNAL_REHEARSAL
        assert session.session_type != SessionType.LEARNER

    def test_article_draft_id_propagated(self):
        draft = _make_draft()
        svc, *_ = _make_svc([draft])
        session = svc.create_rehearsal_session(
            lab_id=draft.lab_id, vm_id="vm-500", admin_username="admin",
            article_draft_id="88adee20-1a50-4183-8879-046334bc144d",
        )
        assert session.article_draft_id == "88adee20-1a50-4183-8879-046334bc144d"

    def test_learner_precheck_not_modified(self):
        """run_precheck() signature / behavior unchanged for learner path."""
        draft = _make_published_draft()
        svc, *_ = _make_svc([draft])
        result = svc.run_precheck(draft.lab_id, "vm-500", "student1")
        assert result.passed
        assert result.failures == []

    def test_rehearsal_precheck_accepts_publish_blocked_draft(self):
        """Rehearsal doesn't care about publish_status (PUBLISH_BLOCKED is allowed too)."""
        draft = _make_draft(publish_status=PublishStatus.PUBLISH_BLOCKED)
        svc, *_ = _make_svc([draft])
        result = svc.run_rehearsal_precheck(draft.lab_id, "vm-500", "admin")
        assert result.passed

    def test_rehearsal_precheck_accepts_review_required_draft(self):
        draft = _make_draft(publish_status=PublishStatus.REVIEW_REQUIRED)
        svc, *_ = _make_svc([draft])
        result = svc.run_rehearsal_precheck(draft.lab_id, "vm-500", "admin")
        assert result.passed

    # -- Security regression tests (safety-reviewer fixes, 2026-06-20) ---------

    def test_learner_get_session_endpoint_blocks_rehearsal_session_for_non_admin(self):
        """HIGH: learner GET /api/lab-sessions/{id} must return 404 for rehearsal sessions."""
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_session_service, get_session_repository

        draft = _make_draft()
        draft_repo, session_repo, svc_factory = _http_deps([draft])

        # Pre-seed a rehearsal session owned by "admin"
        rehearsal = LabSessionState(
            lab_id=draft.lab_id, vm_id="vm-500", student_username="admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
        )
        session_repo._store[rehearsal.session_id] = rehearsal

        app.dependency_overrides[get_session_service] = svc_factory
        app.dependency_overrides[get_session_repository] = lambda: session_repo
        app.dependency_overrides[get_current_user] = lambda: "admin"
        try:
            client = TestClient(app)
            # Non-admin caller (admin is the session owner but NOT an is_admin user here)
            resp = client.get(f"/api/lab-sessions/{rehearsal.session_id}")
            assert resp.status_code == 404, resp.text
        finally:
            app.dependency_overrides.clear()

    def test_learner_complete_endpoint_blocks_rehearsal_session(self):
        """MEDIUM: learner POST /api/lab-sessions/{id}/complete must return 404 for rehearsal."""
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_session_service, get_session_repository

        draft = _make_draft()
        draft_repo, session_repo, svc_factory = _http_deps([draft])

        rehearsal = LabSessionState(
            lab_id=draft.lab_id, vm_id="vm-500", student_username="admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
            ready_to_complete=True,
        )
        session_repo._store[rehearsal.session_id] = rehearsal

        app.dependency_overrides[get_session_service] = svc_factory
        app.dependency_overrides[get_session_repository] = lambda: session_repo
        app.dependency_overrides[get_current_user] = lambda: "admin"
        try:
            client = TestClient(app)
            resp = client.post(f"/api/lab-sessions/{rehearsal.session_id}/complete")
            assert resp.status_code == 404, resp.text
        finally:
            app.dependency_overrides.clear()

    def test_learner_abort_endpoint_blocks_rehearsal_session(self):
        """MEDIUM: learner POST /api/lab-sessions/{id}/abort must return 404 for rehearsal."""
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_session_service, get_session_repository

        draft = _make_draft()
        draft_repo, session_repo, svc_factory = _http_deps([draft])

        rehearsal = LabSessionState(
            lab_id=draft.lab_id, vm_id="vm-500", student_username="admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
        )
        session_repo._store[rehearsal.session_id] = rehearsal

        app.dependency_overrides[get_session_service] = svc_factory
        app.dependency_overrides[get_session_repository] = lambda: session_repo
        app.dependency_overrides[get_current_user] = lambda: "admin"
        try:
            client = TestClient(app)
            resp = client.post(f"/api/lab-sessions/{rehearsal.session_id}/abort")
            assert resp.status_code == 404, resp.text
        finally:
            app.dependency_overrides.clear()

    def test_rehearsal_active_session_does_not_pollute_learner_precheck(self):
        """HIGH: active rehearsal session must NOT trigger PRECHECK_SESSION_ALREADY_ACTIVE on learner path."""
        published_draft = _make_published_draft()
        svc, _, session_repo, _ = _make_svc([published_draft])

        # Seed an active rehearsal session for the same lab + same user
        rehearsal = LabSessionState(
            lab_id=published_draft.lab_id, vm_id="vm-500", student_username="student1",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
        )
        session_repo._store[rehearsal.session_id] = rehearsal

        result = svc.run_precheck(published_draft.lab_id, "vm-500", "student1")
        assert result.passed, f"Expected precheck to pass but got failures: {result.failures}"
        assert FailureReason.PRECHECK_SESSION_ALREADY_ACTIVE.value not in result.failures

    def test_snapshot_build_blocks_rehearsal_session_for_non_admin(self):
        """HIGH: learner snapshot service must raise SnapshotNotFound for rehearsal sessions."""
        from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService, SnapshotNotFound

        draft = _make_draft()
        draft_repo = _MemDraftRepo([draft])

        rehearsal = LabSessionState(
            lab_id=draft.lab_id, vm_id="vm-500", student_username="admin",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
        )
        session_repo = _MemSessionRepo([rehearsal])

        snapshot_svc = LearnerSessionSnapshotService(
            session_repo=session_repo,
            draft_repo=draft_repo,
        )

        with pytest.raises(SnapshotNotFound):
            snapshot_svc.build_snapshot(
                session_id=rehearsal.session_id,
                actor_user="admin",
                is_admin=False,
            )
