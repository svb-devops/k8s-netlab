"""
Admin Publish Decision Gate — tests for PublishDecisionService + endpoints.

Coverage areas:
  A. Decision allowed
  B. Decision blocked by validator
  C. Decision permission
  D. Publish integration (gate wired to publish endpoint)
  E. Preview consistency
  F. Safety (no credential leak in any response leaf)
  G. Regression (GET decision is read-only, no side effects)
  H. Service unit tests
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.draft_preview import DraftPreviewService
from backend.labgen.models import (
    BlockingLevel,
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    PublishStatus,
    RuntimeRequirements,
    Step,
    ValidatorResult,
    ValidatorStatus,
)
from backend.labgen.publish_decision import (
    PublishBlockReasonCode,
    PublishDecision,
    PublishDecisionService,
    PublishDecisionStatus,
)
from backend.labgen.routes import (
    get_decision_service,
    get_preview_service,
    get_publish_service,
    get_repository,
    require_admin_user,
)
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
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
    """Recursively assert no credential patterns appear in any leaf string."""
    if isinstance(payload, str):
        for pat in _CREDENTIAL_PATTERNS:
            assert not pat.search(payload), f"Sensitive pattern {pat.pattern!r} in: {payload!r}"
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_sensitive(item)
    elif isinstance(payload, dict):
        for v in payload.values():
            _assert_no_sensitive(v)


def _make_valid_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Kubernetes Networking Lab",
        description="Learn pod-to-pod communication",
        estimated_duration_minutes=45,
        runtime_requirements=RuntimeRequirements(),
        steps=[
            Step(
                step_id="s1",
                order=1,
                why="Understand pod networking",
                do="kubectl apply -f nginx.yaml",
                observe="kubectl get pods -n default",
                explain=ExplainField(concept="pod networking", observation="pods are running"),
            )
        ],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
    )
    defaults.update(kw)
    return LabDraft(**defaults)


def _make_invalid_draft(**kw) -> LabDraft:
    """Draft with cleanup=None → StaticValidator PUBLISH_BLOCKING failure."""
    return _make_valid_draft(cleanup=None, **kw)


# ---------------------------------------------------------------------------
# In-memory repository
# ---------------------------------------------------------------------------


class _MemRepo:
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


# ---------------------------------------------------------------------------
# Test context helpers
# ---------------------------------------------------------------------------


@contextmanager
def _decision_ctx(
    mem_repo: _MemRepo,
    *,
    admin: str = "testadmin",
    also_preview: bool = False,
) -> Iterator[TestClient]:
    """Override repo + admin for decision endpoint tests."""
    from backend.main import app

    overrides = {
        get_repository: lambda: mem_repo,
        require_admin_user: lambda: admin,
    }
    if also_preview:
        # For consistency tests: ensure preview endpoint also uses mem_repo
        overrides[get_preview_service] = lambda: DraftPreviewService(
            repo=mem_repo, validator=StaticValidator()
        )

    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


@contextmanager
def _publish_ctx(
    mem_repo: _MemRepo,
    *,
    publish_svc=None,
    admin: str = "testadmin",
) -> Iterator[TestClient]:
    """Override repo + admin (+ optional publish service) for publish endpoint tests."""
    from backend.main import app

    overrides: dict = {
        get_repository: lambda: mem_repo,
        require_admin_user: lambda: admin,
    }
    if publish_svc is not None:
        overrides[get_publish_service] = lambda: publish_svc

    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# A. Decision allowed
# ---------------------------------------------------------------------------


class TestDecisionAllowed:
    def test_status_allowed_for_valid_draft(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.status_code == 200
        assert r.json()["status"] == "ALLOWED"

    def test_is_publishable_true(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["is_publishable"] is True

    def test_issues_empty_for_clean_draft(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["issues"] == []

    def test_draft_id_in_response(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["draft_id"] == draft.lab_id

    def test_draft_not_mutated_by_decision(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        original_status = draft.publish_status
        with _decision_ctx(mem) as client:
            client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert mem.get(draft.lab_id).publish_status == original_status
        assert mem.update_calls == []

    def test_validation_status_passed(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["validation_status"] == "passed"

    def test_checked_at_present_and_iso(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        checked_at = r.json()["checked_at"]
        assert checked_at
        datetime.fromisoformat(checked_at)  # must parse without error

    def test_preview_summary_present(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["preview_summary"] is not None


# ---------------------------------------------------------------------------
# B. Decision blocked by validator
# ---------------------------------------------------------------------------


class TestDecisionBlockedByValidator:
    def test_status_blocked_for_invalid_draft(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.status_code == 200
        assert r.json()["status"] == "BLOCKED"

    def test_is_publishable_false(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["is_publishable"] is False

    def test_contains_validation_failed_code(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        codes = [i["code"] for i in r.json()["issues"]]
        assert PublishBlockReasonCode.VALIDATION_FAILED.value in codes

    def test_issues_have_required_fields(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        for issue in r.json()["issues"]:
            assert "code" in issue
            assert "message" in issue
            assert "severity" in issue
            assert "source" in issue

    def test_blocking_issue_severity_is_error(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        summary = next(
            i for i in r.json()["issues"]
            if i["code"] == PublishBlockReasonCode.VALIDATION_FAILED.value
        )
        assert summary["severity"] == "error"

    def test_issue_source_is_validator(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        for issue in r.json()["issues"]:
            assert issue["source"] in {"validator", "preview", "state"}

    def test_draft_not_mutated(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        original_status = draft.publish_status
        with _decision_ctx(mem) as client:
            client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert mem.get(draft.lab_id).publish_status == original_status
        assert mem.update_calls == []

    def test_validation_status_failed(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.json()["validation_status"] == "failed"


# ---------------------------------------------------------------------------
# C. Decision permission
# ---------------------------------------------------------------------------


class TestDecisionPermission:
    def test_admin_can_get_decision(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem, admin="admin") as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.status_code == 200

    def test_non_admin_returns_403(self) -> None:
        from backend.main import app
        from backend.auth_deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: "regularuser"
        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/api/labgen/drafts/any-id/publish-decision")
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_missing_draft_returns_404(self) -> None:
        mem = _MemRepo()
        with _decision_ctx(mem) as client:
            r = client.get("/api/labgen/drafts/nonexistent/publish-decision")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# D. Publish integration — gate wired to publish endpoint
# ---------------------------------------------------------------------------


class TestPublishIntegration:
    def test_publish_valid_draft_succeeds(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _publish_ctx(mem) as client:
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.status_code == 200
        assert r.json()["publish_status"] == "published"

    def test_publish_invalid_draft_blocked(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _publish_ctx(mem) as client:
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.status_code == 409

    def test_blocked_publish_response_contains_issues(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _publish_ctx(mem) as client:
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        detail = r.json()["detail"]
        assert isinstance(detail, dict)
        assert "issues" in detail
        assert len(detail["issues"]) > 0

    def test_blocked_publish_detail_has_status_blocked(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _publish_ctx(mem) as client:
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.json()["detail"]["status"] == "BLOCKED"

    def test_blocked_publish_draft_not_mutated(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        original_status = draft.publish_status
        with _publish_ctx(mem) as client:
            client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        stored = mem.get(draft.lab_id)
        assert stored.publish_status == original_status

    def test_no_force_publish_via_query_param(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _publish_ctx(mem) as client:
            r = client.post(
                f"/api/labgen/drafts/{draft.lab_id}/publish?force=true"
            )
        # FastAPI ignores unknown query params; gate still blocks
        assert r.status_code == 409

    def test_publish_blocked_draft_cannot_publish(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft(publish_status=PublishStatus.PUBLISH_BLOCKED)
        mem.create(draft)
        with _publish_ctx(mem) as client:
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.status_code == 409

    def test_repeated_publish_on_valid_draft_is_idempotent(self) -> None:
        """Already-PUBLISHED valid draft: decision ALLOWED, publish succeeds again."""
        mem = _MemRepo()
        draft = _make_valid_draft(publish_status=PublishStatus.PUBLISHED)
        mem.create(draft)
        with _publish_ctx(mem) as client:
            r1 = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
            r2 = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.json()["publish_status"] == "published"


# ---------------------------------------------------------------------------
# E. Preview consistency
# ---------------------------------------------------------------------------


class TestPreviewConsistency:
    def test_preview_not_publishable_implies_decision_blocked(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem, also_preview=True) as client:
            preview = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview").json()
            decision = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision").json()
        assert preview["is_publishable"] is False
        assert decision["status"] == "BLOCKED"

    def test_preview_publishable_implies_decision_allowed(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem, also_preview=True) as client:
            preview = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview").json()
            decision = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision").json()
        assert preview["is_publishable"] is True
        assert decision["status"] == "ALLOWED"

    def test_issue_codes_consistent(self) -> None:
        """Check codes that appear in preview.issues also appear in decision.issues."""
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem, also_preview=True) as client:
            preview = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview").json()
            decision = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision").json()
        preview_codes = {i["code"] for i in preview["issues"]}
        decision_codes = {i["code"] for i in decision["issues"]}
        # All validator check codes from preview must appear in decision
        assert preview_codes.issubset(decision_codes)

    def test_issue_severities_consistent(self) -> None:
        """For codes appearing in both, severity must agree."""
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        with _decision_ctx(mem, also_preview=True) as client:
            preview = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview").json()
            decision = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision").json()
        preview_by_code = {i["code"]: i["severity"] for i in preview["issues"]}
        decision_by_code = {i["code"]: i["severity"] for i in decision["issues"]}
        for code, sev in preview_by_code.items():
            if code in decision_by_code:
                assert decision_by_code[code] == sev

    def test_decision_allowed_draft_publishes_successfully(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem, also_preview=True) as client:
            decision = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision").json()
        assert decision["status"] == "ALLOWED"
        # Now publish it
        with _publish_ctx(mem) as client:
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# F. Safety — no credential material in any leaf value
# ---------------------------------------------------------------------------


class TestSafety:
    def _poisoned_draft(self) -> LabDraft:
        """Draft whose fields contain credential-like strings."""
        return _make_valid_draft(
            title="Lab with token=eyJhbGciOiJIUzI1NiJ9.payload.sig in title",
            description=(
                "password=hunter2 secret=s3cr3t "
                "kubeconfig=/etc/k8s/admin.conf"
            ),
            steps=[
                Step(
                    step_id="s1",
                    order=1,
                    why="Bearer AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                    do="kubectl apply -f secret.yaml  # private_key: -----BEGIN RSA PRIVATE KEY-----",
                    observe="check output",
                    explain=ExplainField(concept="c", observation="o"),
                )
            ],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )

    def test_decision_response_no_sensitive_data(self) -> None:
        mem = _MemRepo()
        draft = self._poisoned_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        _assert_no_sensitive(r.json())

    def test_blocked_publish_response_no_sensitive_data(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft(
            description="token=abcdefghij secret=mysecret"
        )
        mem.create(draft)
        with _publish_ctx(mem) as client:
            r = client.post(f"/api/labgen/drafts/{draft.lab_id}/publish")
        assert r.status_code == 409
        _assert_no_sensitive(r.json())

    def test_no_raw_exception_in_decision(self) -> None:
        mem = _MemRepo()
        draft = self._poisoned_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        body = str(r.json())
        assert "Traceback" not in body
        assert "Exception" not in body
        assert "stack trace" not in body.lower()

    def test_no_raw_model_output_in_response(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        body = r.json()
        assert "raw_model_output" not in str(body)
        assert "hidden_prompt" not in str(body)
        assert "provider_metadata" not in str(body)

    def test_jwt_like_string_redacted(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft(
            title="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.sig"
        )
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        title_in_response = r.json().get("preview_summary", {})
        # JWT should not appear raw in any leaf
        _assert_no_sensitive(r.json())

    def test_bearer_token_redacted_in_issue_message(self) -> None:
        mem = _MemRepo()
        # Create a draft that will fail validation but whose fields contain bearer token
        draft = _make_invalid_draft(
            description="Bearer AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        )
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        _assert_no_sensitive(r.json())

    def test_no_kubeconfig_in_response(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft(
            title="kubeconfig: /etc/kubernetes/admin.conf"
        )
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        _assert_no_sensitive(r.json())


# ---------------------------------------------------------------------------
# G. Regression — GET decision is purely read-only
# ---------------------------------------------------------------------------


class TestRegression:
    def test_get_decision_does_not_publish(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert mem.get(draft.lab_id).publish_status != PublishStatus.PUBLISHED

    def test_get_decision_does_not_change_publish_status(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        before = draft.publish_status
        with _decision_ctx(mem) as client:
            client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert mem.get(draft.lab_id).publish_status == before

    def test_get_decision_does_not_call_repo_update(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert mem.update_calls == []

    def test_get_decision_does_not_start_lab(self) -> None:
        """No session created: session repo not touched."""
        from backend.labgen.lab_session_repository import LabSessionRepository
        from backend.labgen.routes import get_session_repository

        mem = _MemRepo()
        session_calls: list[str] = []

        class _SpySessionRepo(LabSessionRepository):
            def create(self, s):  # type: ignore[override]
                session_calls.append("create")
                return super().create(s)

        draft = _make_valid_draft()
        mem.create(draft)
        from backend.main import app

        app.dependency_overrides.update({
            get_repository: lambda: mem,
            require_admin_user: lambda: "testadmin",
            get_session_repository: lambda: _SpySessionRepo(),
        })
        try:
            client = TestClient(app, raise_server_exceptions=True)
            client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        finally:
            app.dependency_overrides.clear()
        assert session_calls == []

    def test_existing_preview_tests_pass(self) -> None:
        """Sanity: GET /preview still works after gate addition."""
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        from backend.main import app
        from backend.labgen.draft_preview import DraftPreviewService
        from backend.labgen.static_validator import StaticValidator

        app.dependency_overrides.update({
            get_preview_service: lambda: DraftPreviewService(
                repo=mem, validator=StaticValidator()
            ),
            require_admin_user: lambda: "testadmin",
        })
        try:
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/preview")
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200
        assert "is_publishable" in r.json()

    def test_get_decision_returns_200_not_201_or_204(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        assert r.status_code == 200

    def test_decision_response_schema_stable(self) -> None:
        """All required top-level fields present."""
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        with _decision_ctx(mem) as client:
            r = client.get(f"/api/labgen/drafts/{draft.lab_id}/publish-decision")
        body = r.json()
        for field in ("status", "is_publishable", "draft_id", "validation_status",
                      "issues", "checked_at"):
            assert field in body, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# H. Service unit tests (no HTTP layer)
# ---------------------------------------------------------------------------


class TestPublishDecisionService:
    def _make_svc(self, mem_repo: _MemRepo) -> PublishDecisionService:
        return PublishDecisionService(
            preview_svc=DraftPreviewService(repo=mem_repo, validator=StaticValidator())
        )

    def test_none_draft_returns_blocked_with_not_found(self) -> None:
        mem = _MemRepo()
        svc = self._make_svc(mem)
        decision = svc.evaluate("nonexistent-id")
        assert decision.status == PublishDecisionStatus.BLOCKED
        assert decision.validation_status == "not_found"

    def test_none_draft_has_draft_not_found_issue(self) -> None:
        mem = _MemRepo()
        svc = self._make_svc(mem)
        decision = svc.evaluate("nonexistent-id")
        codes = [i.code for i in decision.issues]
        assert PublishBlockReasonCode.DRAFT_NOT_FOUND.value in codes

    def test_valid_draft_returns_allowed(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        svc = self._make_svc(mem)
        decision = svc.evaluate(draft.lab_id)
        assert decision.status == PublishDecisionStatus.ALLOWED

    def test_invalid_draft_returns_blocked(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        svc = self._make_svc(mem)
        decision = svc.evaluate(draft.lab_id)
        assert decision.status == PublishDecisionStatus.BLOCKED

    def test_evaluate_never_calls_repo_update(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        svc = self._make_svc(mem)
        svc.evaluate(draft.lab_id)
        assert mem.update_calls == []

    def test_decision_issue_source_normalised_to_validator(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        svc = self._make_svc(mem)
        decision = svc.evaluate(draft.lab_id)
        validator_issues = [i for i in decision.issues if i.code not in {
            PublishBlockReasonCode.VALIDATION_FAILED.value,
            PublishBlockReasonCode.PREVIEW_NOT_PUBLISHABLE.value,
        }]
        for issue in validator_issues:
            assert issue.source == "validator"

    def test_blocked_decision_has_validation_failed_code(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        svc = self._make_svc(mem)
        decision = svc.evaluate(draft.lab_id)
        codes = [i.code for i in decision.issues]
        assert PublishBlockReasonCode.VALIDATION_FAILED.value in codes

    def test_allowed_decision_is_publishable_true(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        svc = self._make_svc(mem)
        decision = svc.evaluate(draft.lab_id)
        assert decision.is_publishable is True

    def test_blocked_decision_is_publishable_false(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft()
        mem.create(draft)
        svc = self._make_svc(mem)
        decision = svc.evaluate(draft.lab_id)
        assert decision.is_publishable is False

    def test_draft_id_matches_in_decision(self) -> None:
        mem = _MemRepo()
        draft = _make_valid_draft()
        mem.create(draft)
        svc = self._make_svc(mem)
        decision = svc.evaluate(draft.lab_id)
        assert decision.draft_id == draft.lab_id

    def test_issue_messages_sanitized(self) -> None:
        mem = _MemRepo()
        draft = _make_invalid_draft(
            title="token=Bearer supersecrettoken123456789012345678901234567890"
        )
        mem.create(draft)
        svc = self._make_svc(mem)
        decision = svc.evaluate(draft.lab_id)
        for issue in decision.issues:
            _assert_no_sensitive(issue.message)
