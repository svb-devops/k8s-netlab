"""
Learner Lab Catalog & Start Eligibility API — tests.

Coverage areas:
  A. Catalog list
  B. Lab detail
  C. Start eligibility
  D. Permissions
  E. Safety (no credential leak)
  F. Regression (read-only invariants)
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.learner_catalog import (
    EligibilityIssueCode,
    LearnerCatalogService,
    LearnerLabCatalogItem,
    LearnerLabDetail,
    LearnerLabEligibility,
)
from backend.labgen.models import (
    BlockingLevel,
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    ImageResolutionResult,
    ImageStatus,
    LabDomainType,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    Step,
    ValidatorResult,
    ValidatorStatus,
)
from backend.labgen.routes import get_catalog_service, get_current_user, get_repository
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Credential pattern checks (same as publish_decision tests)
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
                f"Sensitive pattern {pat.pattern!r} in: {payload!r}"
            )
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_sensitive(item)
    elif isinstance(payload, dict):
        for v in payload.values():
            _assert_no_sensitive(v)


# ---------------------------------------------------------------------------
# Draft / session builder helpers
# ---------------------------------------------------------------------------


def _make_valid_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-test",
        title="K8s Network Lab",
        description="Learn pod-to-pod networking",
        estimated_duration_minutes=45,
        runtime_requirements=RuntimeRequirements(),
        steps=[
            Step(
                step_id="s1",
                order=1,
                why="Understand pod networking",
                do="kubectl apply -f nginx.yaml",
                observe="kubectl get pods",
                explain=ExplainField(
                    concept="pod networking", observation="pods are running"
                ),
            )
        ],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
    )
    defaults.update(kw)
    return LabDraft(**defaults)


def _make_published_draft(**kw) -> LabDraft:
    """Create a PUBLISHED draft with pre-populated validator_results (all PASSED)."""
    draft = _make_valid_draft(**kw)
    draft.publish_status = PublishStatus.PUBLISHED
    # Populate validator_results so the catalog service doesn't treat them as absent.
    # PublishService always runs the validator before publishing; we mirror that here.
    draft.validator_results = StaticValidator().validate(draft)
    return draft


def _make_invalid_draft(**kw) -> LabDraft:
    """cleanup=None → StaticValidator PUBLISH_BLOCKING failure."""
    return _make_valid_draft(cleanup=None, **kw)


def _make_active_session(lab_id: str, username: str) -> LabSessionState:
    return LabSessionState(
        session_id=str(uuid.uuid4()),
        lab_id=lab_id,
        vm_id="500",
        student_username=username,
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
    )


# ---------------------------------------------------------------------------
# In-memory repositories
# ---------------------------------------------------------------------------


class _MemDraftRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}
        self.update_calls: list[str] = []

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        self.update_calls.append(draft.lab_id)
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemSessionRepo:
    def __init__(self) -> None:
        self._sessions: list[LabSessionState] = []
        self.create_calls: list[str] = []

    def add(self, session: LabSessionState) -> None:
        self._sessions.append(session)

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._sessions if s.student_username == username]

    def create(self, session: LabSessionState) -> LabSessionState:
        self._sessions.append(session)
        self.create_calls.append(session.session_id)
        return session


# ---------------------------------------------------------------------------
# HTTP test context helpers
# ---------------------------------------------------------------------------


class _FakeInviteRegistry:
    """In-memory stand-in for InviteRegistry — same interface, no file I/O."""

    def __init__(self, registry: Optional[dict] = None) -> None:
        self._registry = registry or {}

    def requires_invite(self, lab_id: str) -> bool:
        return lab_id in self._registry

    def is_invited(self, lab_id: str, username: str) -> bool:
        return username in self._registry.get(lab_id, [])


@contextmanager
def _catalog_ctx(
    mem_repo: _MemDraftRepo,
    *,
    user: str = "student1",
    session_repo: Optional[_MemSessionRepo] = None,
    enabled_lab_ids: Optional[frozenset] = None,
    admin_usernames: frozenset = frozenset(),
    invite_registry: Optional[_FakeInviteRegistry] = None,
) -> Iterator[TestClient]:
    """Override repo + auth for catalog endpoint tests."""
    from backend.main import app

    catalog_svc = LearnerCatalogService(
        draft_repo=mem_repo,
        validator=StaticValidator(),
        session_repo=session_repo,
        enabled_lab_ids=enabled_lab_ids,
        admin_usernames=admin_usernames,
        invite_registry=invite_registry,
    )
    overrides = {
        get_repository: lambda: mem_repo,
        get_current_user: lambda: user,
        get_catalog_service: lambda: catalog_svc,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# A. Catalog list
# ---------------------------------------------------------------------------


class TestCatalogList:
    def test_returns_empty_list_when_no_published(self) -> None:
        mem = _MemDraftRepo()
        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        assert r.status_code == 200
        assert r.json() == []

    def test_only_published_labs_returned(self) -> None:
        mem = _MemDraftRepo()
        published = _make_published_draft(title="Published Lab")
        draft_only = _make_valid_draft(title="Draft Lab")
        blocked = _make_valid_draft(title="Blocked Lab")
        blocked.publish_status = PublishStatus.PUBLISH_BLOCKED
        for d in (published, draft_only, blocked):
            mem.create(d)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["lab_id"] == published.lab_id

    def test_catalog_item_has_required_fields(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        item = r.json()[0]

        assert "lab_id" in item
        assert "title" in item
        assert "summary" in item
        assert "objective_count" in item
        assert "step_count" in item
        assert "is_startable" in item

    def test_catalog_item_exposes_target_domain(self) -> None:
        """Frontend groups the catalog into Linux vs K8s sections — it needs
        target_domain on every item to know which section a lab belongs to."""
        mem = _MemDraftRepo()
        k8s_draft = _make_published_draft(title="K8s Lab")
        linux_draft = _make_published_draft(
            title="Linux Lab", target_domain=LabDomainType.LINUX
        )
        mem.create(k8s_draft)
        mem.create(linux_draft)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        items = {item["title"]: item["target_domain"] for item in r.json()}
        assert items["K8s Lab"] == "k8s"
        assert items["Linux Lab"] == "linux"

    def test_catalog_item_title_and_summary_sanitized(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft(
            title="Lab with token: secret123 info",
            description="Learn about kubeconfig: somevalue here",
        )
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        item = r.json()[0]
        assert "secret123" not in item["title"]
        assert "somevalue" not in item["summary"]

    def test_is_startable_true_for_valid_published(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        assert r.json()[0]["is_startable"] is True

    def test_is_startable_false_when_image_blocked(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        draft.image_resolution = [
            ImageResolutionResult(
                image_intent="nginx",
                requested_image="172.16.100.1:5000/nginx:1.25",
                image_status=ImageStatus.BLOCKED,
            )
        ]
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        assert r.json()[0]["is_startable"] is False

    def test_does_not_include_raw_draft_fields(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        item = r.json()[0]

        # Admin-only / internal fields must NOT appear
        for forbidden in (
            "validator_results",
            "cleanup",
            "runtime_requirements",
            "source_article_id",
            "publish_status",
            "image_resolution",
        ):
            assert forbidden not in item, f"Forbidden field '{forbidden}' leaked into catalog item"

    def test_multiple_published_labs_all_returned(self) -> None:
        mem = _MemDraftRepo()
        for i in range(3):
            mem.create(_make_published_draft(title=f"Lab {i}"))
        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        assert len(r.json()) == 3


# ---------------------------------------------------------------------------
# B. Lab detail
# ---------------------------------------------------------------------------


class TestLabDetail:
    def test_published_lab_returns_detail(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["lab_id"] == draft.lab_id
        assert "title" in data
        assert "summary" in data
        assert "objectives" in data
        assert "steps_preview" in data
        assert "start_eligibility" in data

    def test_unpublished_lab_returns_404(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_valid_draft()  # DRAFT status
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        assert r.status_code == 404

    def test_missing_lab_returns_404(self) -> None:
        mem = _MemDraftRepo()
        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs/nonexistent-id")
        assert r.status_code == 404

    def test_publish_blocked_returns_404(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_valid_draft()
        draft.publish_status = PublishStatus.PUBLISH_BLOCKED
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        assert r.status_code == 404

    def test_steps_preview_is_learner_safe(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        steps = r.json()["steps_preview"]
        assert len(steps) == 1
        step = steps[0]
        # Only learner-facing fields
        assert "step_id" in step
        assert "title" in step
        assert "learner_goal" in step
        assert "instructions_summary" in step
        assert "expected_outcome_summary" in step
        assert "check_count" in step
        # Internal fields must not be present
        for forbidden in ("commands", "verify", "explain", "order"):
            assert forbidden not in step

    def test_detail_does_not_expose_admin_fields(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        data = r.json()

        for forbidden in (
            "validator_results",
            "cleanup",
            "runtime_requirements",
            "source_article_id",
            "publish_status",
            "image_resolution",
        ):
            assert forbidden not in data

    def test_404_does_not_reveal_unpublished_existence(self) -> None:
        """Both missing and unpublished return identical 404 — no enumeration."""
        mem = _MemDraftRepo()
        unpublished = _make_valid_draft()
        mem.create(unpublished)

        with _catalog_ctx(mem) as client:
            missing_r = client.get("/api/labs/does-not-exist")
            unp_r = client.get(f"/api/labs/{unpublished.lab_id}")
        assert missing_r.status_code == 404
        assert unp_r.status_code == 404
        assert missing_r.json()["detail"] == unp_r.json()["detail"]

    def test_detail_includes_start_eligibility(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        el = r.json()["start_eligibility"]
        assert "is_startable" in el
        assert "issues" in el
        assert "checked_at" in el


# ---------------------------------------------------------------------------
# C. Start eligibility
# ---------------------------------------------------------------------------


class TestStartEligibility:
    def test_valid_published_lab_is_startable(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.status_code == 200
        data = r.json()
        assert data["is_startable"] is True

    def test_startable_lab_has_runtime_deferred_warning(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        issues = r.json()["issues"]
        codes = [i["code"] for i in issues]
        assert EligibilityIssueCode.RUNTIME_CHECKS_DEFERRED in codes
        deferred = next(i for i in issues if i["code"] == EligibilityIssueCode.RUNTIME_CHECKS_DEFERRED)
        assert deferred["severity"] == "warning"

    def test_validation_failed_draft_not_startable(self) -> None:
        mem = _MemDraftRepo()
        # Invalid draft (no cleanup) that somehow got published state with failing results
        draft = _make_invalid_draft()
        draft.publish_status = PublishStatus.PUBLISHED
        draft.validator_results = StaticValidator().validate(draft)
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.status_code == 200
        data = r.json()
        assert data["is_startable"] is False
        codes = [i["code"] for i in data["issues"]]
        assert EligibilityIssueCode.VALIDATION_FAILED in codes

    def test_blocked_image_not_startable(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        draft.image_resolution = [
            ImageResolutionResult(
                image_intent="nginx",
                requested_image="172.16.100.1:5000/nginx:1.25",
                image_status=ImageStatus.BLOCKED,
            )
        ]
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        data = r.json()
        assert data["is_startable"] is False
        codes = [i["code"] for i in data["issues"]]
        assert EligibilityIssueCode.IMAGE_STATUS_UNKNOWN in codes
        img_issue = next(i for i in data["issues"] if i["code"] == EligibilityIssueCode.IMAGE_STATUS_UNKNOWN)
        assert img_issue["severity"] == "error"

    def test_unpublished_lab_returns_404(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_valid_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.status_code == 404

    def test_missing_lab_returns_404(self) -> None:
        mem = _MemDraftRepo()
        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs/nope/start-eligibility")
        assert r.status_code == 404

    def test_active_session_makes_not_startable(self) -> None:
        mem = _MemDraftRepo()
        sess_repo = _MemSessionRepo()
        draft = _make_published_draft()
        mem.create(draft)
        sess_repo.add(_make_active_session(lab_id=draft.lab_id, username="student1"))

        with _catalog_ctx(mem, user="student1", session_repo=sess_repo) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        data = r.json()
        assert data["is_startable"] is False
        codes = [i["code"] for i in data["issues"]]
        assert EligibilityIssueCode.SESSION_ALREADY_ACTIVE in codes

    def test_active_session_includes_existing_session_id(self) -> None:
        """SESSION_ALREADY_ACTIVE eligibility must carry existing_session_id for Resume button."""
        mem = _MemDraftRepo()
        sess_repo = _MemSessionRepo()
        draft = _make_published_draft()
        active = _make_active_session(lab_id=draft.lab_id, username="student1")
        mem.create(draft)
        sess_repo.add(active)

        with _catalog_ctx(mem, user="student1", session_repo=sess_repo) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        data = r.json()
        assert data["is_startable"] is False
        assert data.get("existing_session_id") == active.session_id, (
            "existing_session_id must be set so the frontend can render a Resume button"
        )

    def test_active_session_different_lab_does_not_block(self) -> None:
        mem = _MemDraftRepo()
        sess_repo = _MemSessionRepo()
        draft = _make_published_draft()
        other_id = str(uuid.uuid4())
        mem.create(draft)
        sess_repo.add(_make_active_session(lab_id=other_id, username="student1"))

        with _catalog_ctx(mem, user="student1", session_repo=sess_repo) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.json()["is_startable"] is True

    def test_eligibility_does_not_create_session(self) -> None:
        mem = _MemDraftRepo()
        sess_repo = _MemSessionRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem, session_repo=sess_repo) as client:
            client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert sess_repo.create_calls == []

    def test_eligibility_does_not_mutate_draft(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert mem.update_calls == []

    def test_runtime_checks_deferred_absent_when_not_startable(self) -> None:
        """RUNTIME_CHECKS_DEFERRED warning only appears when is_startable=true."""
        mem = _MemDraftRepo()
        draft = _make_invalid_draft()
        draft.publish_status = PublishStatus.PUBLISHED
        draft.validator_results = StaticValidator().validate(draft)
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        data = r.json()
        assert data["is_startable"] is False
        codes = [i["code"] for i in data["issues"]]
        assert EligibilityIssueCode.RUNTIME_CHECKS_DEFERRED not in codes

    def test_response_has_checked_at_iso8601(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        checked_at = r.json()["checked_at"]
        # Must be parseable as ISO 8601 datetime
        datetime.fromisoformat(checked_at.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# D. Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_unauthenticated_catalog_returns_401(self) -> None:
        from backend.main import app
        app.dependency_overrides.clear()
        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/labs")
        assert r.status_code in (401, 403)

    def test_unauthenticated_detail_returns_401(self) -> None:
        from backend.main import app
        app.dependency_overrides.clear()
        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/labs/some-id")
        assert r.status_code in (401, 403)

    def test_unauthenticated_eligibility_returns_401(self) -> None:
        from backend.main import app
        app.dependency_overrides.clear()
        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/labs/some-id/start-eligibility")
        assert r.status_code in (401, 403)

    def test_authenticated_learner_can_access_catalog(self) -> None:
        mem = _MemDraftRepo()
        with _catalog_ctx(mem, user="learner42") as client:
            r = client.get("/api/labs")
        assert r.status_code == 200

    def test_admin_receives_learner_safe_catalog(self) -> None:
        """Admin using catalog endpoints gets learner-safe view, not admin preview."""
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem, user="adminuser") as client:
            r = client.get("/api/labs")
        assert r.status_code == 200
        item = r.json()[0]
        for forbidden in ("validator_results", "cleanup", "image_resolution"):
            assert forbidden not in item

    def test_unpublished_lab_not_visible_to_any_user(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_valid_draft()
        mem.create(draft)

        with _catalog_ctx(mem, user="adminuser") as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        assert r.status_code == 404

    def test_catalog_list_does_not_include_draft_status_labs(self) -> None:
        mem = _MemDraftRepo()
        for status in (
            PublishStatus.DRAFT,
            PublishStatus.REVIEW_REQUIRED,
            PublishStatus.PUBLISH_BLOCKED,
        ):
            d = _make_valid_draft()
            d.publish_status = status
            mem.create(d)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        assert r.json() == []


# ---------------------------------------------------------------------------
# D2. Access allowlist gate (LABGEN_ENABLED_LAB_IDS consistency)
# ---------------------------------------------------------------------------


class TestAccessAllowlistGate:
    """Regression (HIGH-001): catalog is_startable / start_eligibility must
    match LabSessionService.run_precheck's real LABGEN_ENABLED_LAB_IDS gate.
    Before this fix, a published-but-not-enabled lab showed is_startable=true
    in the catalog and only failed with 403 at actual Start click."""

    def test_published_not_enabled_catalog_is_startable_false(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem, user="student1", enabled_lab_ids=frozenset({"some-other-lab-id"})
        ) as client:
            r = client.get("/api/labs")
        assert r.status_code == 200
        item = next(i for i in r.json() if i["lab_id"] == draft.lab_id)
        assert item["is_startable"] is False

    def test_published_not_enabled_detail_is_startable_false_with_reason(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem, user="student1", enabled_lab_ids=frozenset({"some-other-lab-id"})
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["start_eligibility"]["is_startable"] is False
        codes = [i["code"] for i in body["start_eligibility"]["issues"]]
        assert EligibilityIssueCode.LAB_NOT_ENABLED in codes

    def test_enabled_lab_authorized_learner_catalog_is_startable_true(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem, user="student1", enabled_lab_ids=frozenset({draft.lab_id})
        ) as client:
            r = client.get("/api/labs")
        item = next(i for i in r.json() if i["lab_id"] == draft.lab_id)
        assert item["is_startable"] is True

    def test_enabled_lab_any_authenticated_learner_is_startable_true(self) -> None:
        """No separate per-user invite allowlist exists in the codebase today —
        LABGEN_ENABLED_LAB_IDS is the only access gate besides admin bypass.
        Once a lab_id is enabled, any authenticated (non-admin) user is
        authorized. This test documents that real current behavior rather
        than assume a per-user invite mechanism that does not exist."""
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem, user="any-authenticated-student", enabled_lab_ids=frozenset({draft.lab_id})
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.json()["is_startable"] is True

    def test_admin_bypasses_allowlist_gate(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem,
            user="adminuser",
            enabled_lab_ids=frozenset({"some-other-lab-id"}),
            admin_usernames=frozenset({"adminuser"}),
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.json()["is_startable"] is True

    def test_gate_not_configured_defaults_startable(self) -> None:
        """enabled_lab_ids=None (default, most tests/dev) means the gate is not
        configured — must not silently deny everything."""
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem, user="student1") as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.json()["is_startable"] is True

    def test_denied_lab_does_not_leak_runtime_checks_deferred_issue(self) -> None:
        """Denied labs must be a clean error state, not mixed with the
        'proceed, runtime will recheck' warning used for startable labs."""
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem, user="student1", enabled_lab_ids=frozenset({"some-other-lab-id"})
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        codes = [i["code"] for i in r.json()["issues"]]
        assert EligibilityIssueCode.RUNTIME_CHECKS_DEFERRED not in codes


# ---------------------------------------------------------------------------
# D3. Named-user invite gate (Controlled Micro Invite second gate)
# ---------------------------------------------------------------------------


class TestNamedUserInviteGate:
    """LABGEN_ENABLED_LAB_IDS alone is not sufficient for Controlled Micro
    Invite — any authenticated non-admin user is authorized once a lab_id is
    enabled. This registry adds a second, per-lab named-user gate. A lab_id
    absent from the registry is not invite-gated at all (core courses)."""

    def test_lab_not_in_registry_is_unaffected_core_course(self) -> None:
        """Core courses (never added to the invite registry) must keep
        exactly the pre-existing LABGEN_ENABLED_LAB_IDS-only behavior."""
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem,
            user="any-student",
            enabled_lab_ids=frozenset({draft.lab_id}),
            invite_registry=_FakeInviteRegistry({}),  # empty registry, no gating
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.json()["is_startable"] is True

    def test_enabled_lab_invite_gated_uninvited_user_denied(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem,
            user="stranger",
            enabled_lab_ids=frozenset({draft.lab_id}),
            invite_registry=_FakeInviteRegistry({draft.lab_id: ["alice"]}),
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        body = r.json()
        assert body["is_startable"] is False
        assert EligibilityIssueCode.NOT_INVITED in [i["code"] for i in body["issues"]]

    def test_enabled_lab_invite_gated_uninvited_user_catalog_false(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem,
            user="stranger",
            enabled_lab_ids=frozenset({draft.lab_id}),
            invite_registry=_FakeInviteRegistry({draft.lab_id: ["alice"]}),
        ) as client:
            r = client.get("/api/labs")
        item = next(i for i in r.json() if i["lab_id"] == draft.lab_id)
        assert item["is_startable"] is False

    def test_enabled_lab_invite_gated_invited_user_startable(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem,
            user="alice",
            enabled_lab_ids=frozenset({draft.lab_id}),
            invite_registry=_FakeInviteRegistry({draft.lab_id: ["alice"]}),
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.json()["is_startable"] is True

    def test_admin_bypasses_invite_gate(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem,
            user="adminuser",
            enabled_lab_ids=frozenset({draft.lab_id}),
            admin_usernames=frozenset({"adminuser"}),
            invite_registry=_FakeInviteRegistry({draft.lab_id: ["alice"]}),
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.json()["is_startable"] is True

    def test_lab_not_enabled_takes_priority_over_invite_status(self) -> None:
        """A lab that is both un-enabled AND invite-gated must report
        LAB_NOT_ENABLED, not NOT_INVITED — even for an invited user, since the
        outer LABGEN_ENABLED_LAB_IDS gate hasn't opened yet."""
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem,
            user="alice",
            enabled_lab_ids=frozenset({"some-other-lab-id"}),
            invite_registry=_FakeInviteRegistry({draft.lab_id: ["alice"]}),
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        body = r.json()
        assert body["is_startable"] is False
        codes = [i["code"] for i in body["issues"]]
        assert EligibilityIssueCode.LAB_NOT_ENABLED in codes
        assert EligibilityIssueCode.NOT_INVITED not in codes

    def test_registry_not_configured_defaults_unaffected(self) -> None:
        """invite_registry=None (default) means the second gate is not
        configured — must not silently deny everything."""
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(
            mem, user="student1", enabled_lab_ids=frozenset({draft.lab_id})
        ) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.json()["is_startable"] is True


# ---------------------------------------------------------------------------
# E. Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_catalog_response_no_sensitive_data(self) -> None:
        mem = _MemDraftRepo()
        # Lab with potentially dangerous content in fields
        draft = _make_published_draft(
            title="Lab kubeconfig: eyJhbGciOiJSUzI1NiJ9.payload.sig",
            description="token: Bearer eyJhbGciOiJSUzI1NiJ9.some.token",
        )
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        _assert_no_sensitive(r.json())

    def test_detail_response_no_sensitive_data(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft(
            title="Secure Lab",
            description="password: supersecret",
        )
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        _assert_no_sensitive(r.json())

    def test_eligibility_response_no_sensitive_data(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        _assert_no_sensitive(r.json())

    def test_step_content_sanitized(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft(
            steps=[
                Step(
                    step_id="s1",
                    order=1,
                    why="Deploy token: abcXYZ123456 nginx",
                    do="kubectl apply -f manifest.yaml",
                    observe="kubectl get pods",
                    explain=ExplainField(
                        concept="deploy", observation="running"
                    ),
                )
            ],
        )
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}")
        # "abcXYZ123456" would be redacted as part of "token: <value>"
        steps = r.json()["steps_preview"]
        _assert_no_sensitive(steps)

    def test_no_raw_model_output_in_catalog(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get("/api/labs")
        body = r.text
        for leaked in ("raw_model_output", "hidden_prompt", "provider_metadata"):
            assert leaked not in body

    def test_no_traceback_in_responses(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            catalog_r = client.get("/api/labs")
            detail_r = client.get(f"/api/labs/{draft.lab_id}")
            el_r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        for r in (catalog_r, detail_r, el_r):
            assert "Traceback" not in r.text
            assert "stack trace" not in r.text.lower()

    def test_eligibility_issue_messages_sanitized(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_invalid_draft()
        draft.publish_status = PublishStatus.PUBLISHED
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        for issue in r.json()["issues"]:
            _assert_no_sensitive(issue["message"])


# ---------------------------------------------------------------------------
# F. Regression — read-only invariants
# ---------------------------------------------------------------------------


class TestRegression:
    def test_get_labs_does_not_publish(self) -> None:
        mem = _MemDraftRepo()
        draft = _make_valid_draft()  # DRAFT
        mem.create(draft)

        with _catalog_ctx(mem) as client:
            client.get("/api/labs")
        assert mem._store[draft.lab_id].publish_status == PublishStatus.DRAFT

    def test_get_lab_detail_does_not_start(self) -> None:
        mem = _MemDraftRepo()
        sess_repo = _MemSessionRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem, session_repo=sess_repo) as client:
            client.get(f"/api/labs/{draft.lab_id}")
        assert sess_repo.create_calls == []

    def test_get_start_eligibility_does_not_start(self) -> None:
        mem = _MemDraftRepo()
        sess_repo = _MemSessionRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem, session_repo=sess_repo) as client:
            client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert sess_repo.create_calls == []

    def test_eligibility_does_not_create_audit_events(self) -> None:
        """Eligibility never creates audit events — verify by checking no session is made."""
        mem = _MemDraftRepo()
        sess_repo = _MemSessionRepo()
        draft = _make_published_draft()
        mem.create(draft)

        with _catalog_ctx(mem, session_repo=sess_repo) as client:
            r = client.get(f"/api/labs/{draft.lab_id}/start-eligibility")
        assert r.status_code == 200
        assert sess_repo.create_calls == []

    def test_catalog_list_does_not_mutate_drafts(self) -> None:
        mem = _MemDraftRepo()
        for i in range(3):
            mem.create(_make_published_draft(title=f"Lab {i}"))

        with _catalog_ctx(mem) as client:
            client.get("/api/labs")
        assert mem.update_calls == []

    def test_existing_publish_decision_endpoint_unaffected(self) -> None:
        """Confirm labgen admin endpoints still work alongside new catalog routes."""
        from backend.labgen.routes import require_admin_user
        from backend.main import app

        mem = _MemDraftRepo()
        draft = _make_published_draft()
        mem.create(draft)

        app.dependency_overrides[get_repository] = lambda: mem
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 200
        assert "status" in r.json()


# ---------------------------------------------------------------------------
# G. LearnerCatalogService unit tests
# ---------------------------------------------------------------------------


class TestLearnerCatalogServiceUnit:
    def test_list_published_returns_only_published(self) -> None:
        mem = _MemDraftRepo()
        pub = _make_published_draft(title="Published")
        dft = _make_valid_draft(title="Draft")
        mem.create(pub)
        mem.create(dft)

        svc = LearnerCatalogService(mem, StaticValidator())
        items = svc.list_published_labs("user")
        assert len(items) == 1
        assert items[0].lab_id == pub.lab_id

    def test_get_published_detail_returns_none_for_draft(self) -> None:
        mem = _MemDraftRepo()
        d = _make_valid_draft()
        mem.create(d)

        svc = LearnerCatalogService(mem, StaticValidator())
        result = svc.get_published_lab_detail(d.lab_id, "user")
        assert result is None

    def test_evaluate_returns_none_for_unpublished(self) -> None:
        mem = _MemDraftRepo()
        d = _make_valid_draft()
        mem.create(d)

        svc = LearnerCatalogService(mem, StaticValidator())
        result = svc.evaluate_start_eligibility(d.lab_id, "user")
        assert result is None

    def test_evaluate_returns_none_for_missing(self) -> None:
        mem = _MemDraftRepo()
        svc = LearnerCatalogService(mem, StaticValidator())
        result = svc.evaluate_start_eligibility("nonexistent", "user")
        assert result is None

    def test_empty_validator_results_on_published_is_blocking(self) -> None:
        """A published draft with no validator_results is treated as a blocking failure."""
        mem = _MemDraftRepo()
        draft = _make_valid_draft()
        draft.publish_status = PublishStatus.PUBLISHED
        # Intentionally leave validator_results empty (data integrity violation scenario)
        assert len(draft.validator_results) == 0
        mem.create(draft)

        svc = LearnerCatalogService(mem, StaticValidator())
        eligibility = svc.evaluate_start_eligibility(draft.lab_id, "user")
        assert eligibility is not None
        assert eligibility.is_startable is False
        codes = [i.code for i in eligibility.issues]
        assert EligibilityIssueCode.VALIDATION_FAILED in codes

    def test_step_preview_truncates_long_why(self) -> None:
        mem = _MemDraftRepo()
        long_text = "A" * 200
        draft = _make_published_draft(
            steps=[
                Step(
                    step_id="s1",
                    order=1,
                    why=long_text,
                    do="cmd",
                    observe="obs",
                    explain=ExplainField(concept="c", observation="o"),
                )
            ],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
        mem.create(draft)
        svc = LearnerCatalogService(mem, StaticValidator())
        items = svc.list_published_labs("user")
        assert items[0].objective_count == 1

        detail = svc.get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert len(detail.steps_preview[0].title) <= 80
        assert len(detail.steps_preview[0].instructions_summary) <= 200

    def test_check_count_reflects_verify_templates(self) -> None:
        from backend.labgen.models import VerifyTemplate, VerifyType

        mem = _MemDraftRepo()
        draft = _make_published_draft(
            steps=[
                Step(
                    step_id="s1",
                    order=1,
                    why="why",
                    do="do",
                    observe="obs",
                    explain=ExplainField(concept="c", observation="o"),
                    verify=[
                        VerifyTemplate(
                            verify_id="v1",
                            type=VerifyType.POD_RUNNING,
                            name="nginx",
                        ),
                        VerifyTemplate(
                            verify_id="v2",
                            type=VerifyType.SERVICE_EXISTS,
                            name="nginx-svc",
                        ),
                    ],
                )
            ],
        )
        mem.create(draft)
        svc = LearnerCatalogService(mem, StaticValidator())
        detail = svc.get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.steps_preview[0].check_count == 2

    def test_eligibility_uses_cached_validator_results(self) -> None:
        """If draft already has validator_results, service does not re-run validator."""
        mem = _MemDraftRepo()
        draft = _make_published_draft()
        # Pre-populate with a PASSED result to confirm it's used, not re-run
        draft.validator_results = [
            ValidatorResult(
                check_id="precomputed",
                status=ValidatorStatus.PASSED,
                blocking_level=BlockingLevel.DRAFT_WARNING,
                field_path="",
                message="ok",
            )
        ]
        mem.create(draft)

        svc = LearnerCatalogService(mem, StaticValidator())
        eligibility = svc.evaluate_start_eligibility(draft.lab_id, "user")
        assert eligibility is not None
        assert eligibility.is_startable is True

    def test_objectives_count_matches_steps(self) -> None:
        mem = _MemDraftRepo()
        steps = [
            Step(
                step_id=f"s{i}",
                order=i,
                why=f"Objective {i}",
                do="cmd",
                observe="obs",
                explain=ExplainField(concept="c", observation="o"),
            )
            for i in range(4)
        ]
        draft = _make_published_draft(
            steps=steps, cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace())
        )
        mem.create(draft)

        svc = LearnerCatalogService(mem, StaticValidator())
        items = svc.list_published_labs("user")
        assert items[0].objective_count == 4
        assert items[0].step_count == 4

        detail = svc.get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert len(detail.objectives) == 4
        assert len(detail.steps_preview) == 4
