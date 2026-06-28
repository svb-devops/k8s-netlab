"""
AI Draft Review & Repair Loop v0.1 — Tests.

Covers:
  A. Review result: malformed/invalid/valid candidate → DraftReviewResult
  B. Generate API without repair: enable_repair=False preserves current behaviour
  C. Generate API with repair success: initial invalid → repair valid → draft created
  D. Repair still invalid: repair passes Pydantic, fails StaticValidator
  E. Repair malformed: repair fails Pydantic → fall back to initial
  F. Repair safety: sensitive content in warnings/candidate is redacted
  G. Regression: no auto-publish, no session, no audit event, stable schema
  H. Sanitizer unit tests: all required patterns covered

All tests use mocked adapters — no real LLM, no real K3s, no real Proxmox.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.draft_repair import (
    DeterministicFakeDraftRepairAdapter,
    DraftRepairRequest,
    DraftRepairResult,
    DraftReviewResult,
    IssueSource,
    IssueSeverity,
    LabDraftRepairPort,
)
from backend.labgen.llm_generation import (
    FakeDraftGenerationAdapter,
    GenerateLabDraftResponse,
    LabDraftGenerationPort,
    LabDraftGenerationRequest,
    LabDraftGenerationService,
    RepairLoopOutcome,
    _sanitize_warnings,
    sanitize_text,
)
from backend.labgen.models import LabDraft, PublishStatus, ValidatorStatus
from backend.labgen.repository import LabDraftRepository
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# In-memory draft repo
# ---------------------------------------------------------------------------


class _MemDraftRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def _rt(self, draft: LabDraft) -> LabDraft:
        return LabDraft.model_validate(draft.model_dump(mode="json"))

    def create(self, draft: LabDraft) -> LabDraft:
        v = self._rt(draft)
        self._store[v.lab_id] = v
        return v

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        v = self._rt(draft)
        self._store[v.lab_id] = v
        return v

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


# ---------------------------------------------------------------------------
# Sensitive data guard
# ---------------------------------------------------------------------------

_SENSITIVE_KW = frozenset(
    {"kubeconfig", "private_key", "traceback", "stack trace", "raw exception", "password"}
)
_MACHINE_CODE_RE = re.compile(r"^[a-z][a-z_]*$")


def _leaf_strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        out: list[str] = []
        for item in obj:
            out.extend(_leaf_strings(item))
        return out
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out.extend(_leaf_strings(v))
        return out
    return []


def assert_no_sensitive(payload) -> None:
    for val in _leaf_strings(payload):
        v = val.lower()
        for kw in _SENSITIVE_KW:
            assert kw not in v, f"Sensitive kw {kw!r} in: {val[:120]!r}"
        if "token" in v:
            assert _MACHINE_CODE_RE.match(val) and len(val) <= 60, (
                f"Possible token leak: {val[:120]!r}"
            )
        if "secret" in v:
            assert _MACHINE_CODE_RE.match(val) and len(val) <= 40, (
                f"Possible secret leak: {val[:120]!r}"
            )


# ---------------------------------------------------------------------------
# Service factory helpers
# ---------------------------------------------------------------------------


def _make_svc(gen_mode: str = "valid", repo: Optional[_MemDraftRepo] = None):
    r = repo or _MemDraftRepo()
    svc = LabDraftGenerationService(
        port=FakeDraftGenerationAdapter(inject_mode=gen_mode),
        validator=StaticValidator(),
        repo=r,
    )
    return svc, r


def _req(prompt: str = "Deploy nginx", user: str = "student1") -> LabDraftGenerationRequest:
    return LabDraftGenerationRequest(user_prompt=prompt, requester_user_id=user)


# ---------------------------------------------------------------------------
# Context manager for API-level tests
# ---------------------------------------------------------------------------


@contextmanager
def _gen_ctx(
    gen_mode: str = "valid",
    repair_mode: str = "success",
    repair_port_override: Optional[LabDraftRepairPort] = None,
):
    from backend.main import app
    from backend.auth_deps import get_current_user
    from backend.labgen.routes import get_generation_service, get_repair_port

    repo = _MemDraftRepo()
    svc = LabDraftGenerationService(
        port=FakeDraftGenerationAdapter(inject_mode=gen_mode),
        validator=StaticValidator(),
        repo=repo,
    )
    repair = repair_port_override or DeterministicFakeDraftRepairAdapter(
        inject_mode=repair_mode
    )

    from backend.labgen.routes import require_admin_user

    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_generation_service] = lambda: svc
    app.dependency_overrides[get_repair_port] = lambda: repair
    app.dependency_overrides[get_current_user] = lambda: "admin"
    app.dependency_overrides[require_admin_user] = lambda: "admin"

    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield {"client": client, "repo": repo, "svc": svc, "repair": repair}
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def _post(
    client: TestClient,
    prompt: str = "Deploy nginx",
    enable_repair: bool = False,
    max_repair_attempts: int = 1,
):
    return client.post(
        "/api/lab-drafts/generate",
        json={
            "user_prompt": prompt,
            "enable_repair": enable_repair,
            "max_repair_attempts": max_repair_attempts,
        },
    )


# ===========================================================================
# A. Review result
# ===========================================================================


class TestReviewCandidate:
    def test_malformed_candidate_review_is_invalid(self):
        svc, _ = _make_svc()
        _, result = svc.review_candidate({"title": 12345, "steps": "not-a-list"})
        assert result.is_valid is False

    def test_malformed_candidate_has_pydantic_issues(self):
        svc, _ = _make_svc()
        _, result = svc.review_candidate({"title": 12345, "steps": "not-a-list"})
        assert any(i.source == IssueSource.PYDANTIC for i in result.issues)

    def test_malformed_candidate_returns_none_draft(self):
        svc, _ = _make_svc()
        draft, _ = svc.review_candidate({"title": 12345, "steps": "not-a-list"})
        assert draft is None

    def test_pydantic_issue_severity_is_error(self):
        svc, _ = _make_svc()
        _, result = svc.review_candidate({"title": 12345, "steps": "not-a-list"})
        assert all(i.severity == IssueSeverity.ERROR for i in result.issues)

    def test_static_validator_failure_review_is_invalid(self):
        svc, _ = _make_svc()
        # Build a structurally valid but cleanup-missing candidate
        valid_draft = FakeDraftGenerationAdapter("valid")
        gen_result = valid_draft.generate_lab_draft_candidate(_req())
        candidate = gen_result.candidate.copy()
        candidate["cleanup"] = None
        _, result = svc.review_candidate(candidate)
        assert result.is_valid is False

    def test_static_validator_failure_has_validator_issues(self):
        svc, _ = _make_svc()
        valid_draft = FakeDraftGenerationAdapter("valid")
        gen_result = valid_draft.generate_lab_draft_candidate(_req())
        candidate = gen_result.candidate.copy()
        candidate["cleanup"] = None
        _, result = svc.review_candidate(candidate)
        assert any(i.source == IssueSource.STATIC_VALIDATOR for i in result.issues)

    def test_valid_candidate_review_is_valid(self):
        svc, _ = _make_svc()
        valid_draft = FakeDraftGenerationAdapter("valid")
        gen_result = valid_draft.generate_lab_draft_candidate(_req())
        _, result = svc.review_candidate(gen_result.candidate)
        assert result.is_valid is True

    def test_valid_candidate_no_issues(self):
        svc, _ = _make_svc()
        valid_draft = FakeDraftGenerationAdapter("valid")
        gen_result = valid_draft.generate_lab_draft_candidate(_req())
        _, result = svc.review_candidate(gen_result.candidate)
        assert result.issues == []

    def test_review_issues_have_required_fields(self):
        svc, _ = _make_svc()
        _, result = svc.review_candidate({"title": 12345, "steps": "not-a-list"})
        for issue in result.issues:
            assert issue.code
            assert issue.message
            assert issue.severity in (IssueSeverity.ERROR, IssueSeverity.WARNING)
            assert issue.source in (
                IssueSource.PYDANTIC, IssueSource.STATIC_VALIDATOR, IssueSource.SAFETY
            )

    def test_review_result_no_sensitive_values(self):
        svc, _ = _make_svc()
        _, result = svc.review_candidate({"title": 12345, "steps": "not-a-list"})
        assert_no_sensitive(result.model_dump(mode="json"))

    def test_review_sanitized_summary_present(self):
        svc, _ = _make_svc()
        _, result = svc.review_candidate({"title": 12345, "steps": "not-a-list"})
        assert result.sanitized_summary

    def test_review_does_not_persist_draft(self):
        svc, repo = _make_svc()
        valid_draft = FakeDraftGenerationAdapter("valid")
        gen_result = valid_draft.generate_lab_draft_candidate(_req())
        svc.review_candidate(gen_result.candidate)
        assert repo.list_all() == []


# ===========================================================================
# B. Generate API without repair
# ===========================================================================


class TestGenerateNoRepair:
    def test_enable_repair_false_does_not_call_repair(self):
        call_log: list[str] = []

        class _SpyRepair(LabDraftRepairPort):
            def repair_draft_candidate(self, req: DraftRepairRequest) -> DraftRepairResult:
                call_log.append("called")
                return DraftRepairResult()

        with _gen_ctx("invalid", repair_port_override=_SpyRepair()) as ctx:
            _post(ctx["client"], enable_repair=False)
        assert call_log == []

    def test_enable_repair_false_draft_created_when_invalid(self):
        with _gen_ctx("invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=False)
        assert resp.status_code == 201
        assert resp.json()["draft_id"] is not None

    def test_enable_repair_false_repair_attempted_false(self):
        with _gen_ctx("invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=False)
        assert resp.json()["repair_attempted"] is False

    def test_enable_repair_false_repair_applied_false(self):
        with _gen_ctx("invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=False)
        assert resp.json()["repair_applied"] is False

    def test_enable_repair_false_repair_result_null(self):
        with _gen_ctx("invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=False)
        assert resp.json()["repair_result"] is None

    def test_enable_repair_false_validation_status_preserved(self):
        with _gen_ctx("invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=False)
        assert resp.json()["validation_status"] == "validation_failed"

    def test_enable_repair_false_valid_candidate_unchanged(self):
        with _gen_ctx("valid") as ctx:
            resp = _post(ctx["client"], enable_repair=False)
        assert resp.status_code == 201
        assert resp.json()["validation_status"] == "passed"

    def test_new_response_fields_present_in_schema(self):
        with _gen_ctx("valid") as ctx:
            resp = _post(ctx["client"], enable_repair=False)
        body = resp.json()
        assert "repair_attempted" in body
        assert "repair_applied" in body
        assert "repair_result" in body
        assert "review_result" in body

    def test_existing_fields_still_present(self):
        with _gen_ctx("valid") as ctx:
            resp = _post(ctx["client"], enable_repair=False)
        body = resp.json()
        assert "draft_id" in body
        assert "validation_status" in body
        assert "validation_errors" in body
        assert "warnings" in body
        assert "selected_template_id" in body
        assert "candidate_summary" in body


# ===========================================================================
# C. Generate API with repair success
# ===========================================================================


class TestRepairSuccess:
    def test_draft_created(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.status_code == 201
        assert resp.json()["draft_id"] is not None

    def test_validation_status_passed(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["validation_status"] == "passed"

    def test_repair_attempted_true(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_attempted"] is True

    def test_repair_applied_true(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_applied"] is True

    def test_not_published(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        data = resp.json()
        if data.get("candidate_summary"):
            assert data["candidate_summary"]["publish_status"] != PublishStatus.PUBLISHED.value

    def test_review_result_present(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["review_result"] is not None

    def test_repair_result_present(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_result"] is not None

    def test_repair_result_status_passed(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_result"]["repaired_validation_status"] == "passed"

    def test_no_lab_session_created(self):
        with _gen_ctx("invalid", "success") as ctx:
            from backend.labgen.lab_session_repository import LabSessionRepository
            from unittest.mock import patch

            with patch.object(LabSessionRepository, "create") as mock_create:
                _post(ctx["client"], enable_repair=True)
        mock_create.assert_not_called()

    def test_no_sensitive_data_in_response(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert_no_sensitive(resp.json())

    def test_repair_only_when_initial_invalid(self):
        # If initial is valid, repair must NOT be called
        call_log: list[str] = []

        class _SpyRepair(LabDraftRepairPort):
            def repair_draft_candidate(self, req: DraftRepairRequest) -> DraftRepairResult:
                call_log.append("called")
                return DraftRepairResult()

        with _gen_ctx("valid", repair_port_override=_SpyRepair()) as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.status_code == 201
        assert call_log == []
        assert resp.json()["repair_attempted"] is False

    def test_repaired_candidate_not_in_response(self):
        # repaired_candidate is raw adapter output — must never appear in HTTP response
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        body_str = str(resp.json())
        assert "repaired_candidate" not in body_str


# ===========================================================================
# D. Repair still invalid
# ===========================================================================


class TestRepairStillInvalid:
    def test_draft_created(self):
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.status_code == 201
        assert resp.json()["draft_id"] is not None

    def test_response_has_repair_result(self):
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_result"] is not None

    def test_response_has_review_result(self):
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["review_result"] is not None

    def test_not_500(self):
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.status_code != 500

    def test_not_published(self):
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        data = resp.json()
        if data.get("candidate_summary"):
            assert data["candidate_summary"]["publish_status"] != PublishStatus.PUBLISHED.value

    def test_repair_attempted_true(self):
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_attempted"] is True

    def test_validation_status_still_failed(self):
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["validation_status"] == "validation_failed"

    def test_repair_result_status_still_invalid(self):
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_result"]["repaired_validation_status"] == "still_invalid"

    def test_repair_applied_true(self):
        # Repair produced a parseable (but still invalid) candidate — it was used
        with _gen_ctx("invalid", "still_invalid") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_applied"] is True


# ===========================================================================
# E. Repair malformed
# ===========================================================================


class TestRepairMalformed:
    def test_not_500(self):
        with _gen_ctx("invalid", "malformed") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.status_code != 500

    def test_structured_response(self):
        with _gen_ctx("invalid", "malformed") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        body = resp.json()
        assert "repair_result" in body
        assert "review_result" in body

    def test_repair_attempted_true(self):
        with _gen_ctx("invalid", "malformed") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_attempted"] is True

    def test_repair_applied_false(self):
        with _gen_ctx("invalid", "malformed") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_applied"] is False

    def test_not_published(self):
        with _gen_ctx("invalid", "malformed") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        data = resp.json()
        if data.get("candidate_summary"):
            assert data["candidate_summary"]["publish_status"] != PublishStatus.PUBLISHED.value

    def test_repair_result_status_malformed(self):
        with _gen_ctx("invalid", "malformed") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        repair = resp.json()["repair_result"]
        assert repair is not None
        assert repair["repaired_validation_status"] == "malformed"

    def test_draft_created_from_initial(self):
        # Fall back to initial (invalid) draft — consistent with current behaviour
        with _gen_ctx("invalid", "malformed") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.status_code == 201
        assert resp.json()["draft_id"] is not None

    def test_repaired_candidate_not_in_response(self):
        # repaired_candidate is raw adapter output — must never appear in HTTP response
        with _gen_ctx("invalid", "malformed") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        body_str = str(resp.json())
        assert "repaired_candidate" not in body_str


# ===========================================================================
# E2. Repair adapter raises exception (adapter_error fallback)
# ===========================================================================


class TestRepairAdapterError:
    def test_not_500_when_adapter_raises(self):
        class _RaisingRepair(LabDraftRepairPort):
            def repair_draft_candidate(self, req: DraftRepairRequest) -> DraftRepairResult:
                raise RuntimeError("adapter crashed")

        with _gen_ctx("invalid", repair_port_override=_RaisingRepair()) as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.status_code != 500

    def test_draft_created_on_adapter_error(self):
        class _RaisingRepair(LabDraftRepairPort):
            def repair_draft_candidate(self, req: DraftRepairRequest) -> DraftRepairResult:
                raise RuntimeError("adapter crashed")

        with _gen_ctx("invalid", repair_port_override=_RaisingRepair()) as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["draft_id"] is not None

    def test_repair_result_has_adapter_error_reason(self):
        class _RaisingRepair(LabDraftRepairPort):
            def repair_draft_candidate(self, req: DraftRepairRequest) -> DraftRepairResult:
                raise RuntimeError("adapter crashed")

        with _gen_ctx("invalid", repair_port_override=_RaisingRepair()) as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        repair = resp.json()["repair_result"]
        assert repair is not None
        assert repair["repaired_validation_status"] == "repair_failed"
        assert repair["rejected_reason"] == "adapter_error"

    def test_repair_attempted_true_on_adapter_error(self):
        class _RaisingRepair(LabDraftRepairPort):
            def repair_draft_candidate(self, req: DraftRepairRequest) -> DraftRepairResult:
                raise ValueError("something went wrong")

        with _gen_ctx("invalid", repair_port_override=_RaisingRepair()) as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_attempted"] is True

    def test_repair_applied_false_on_adapter_error(self):
        class _RaisingRepair(LabDraftRepairPort):
            def repair_draft_candidate(self, req: DraftRepairRequest) -> DraftRepairResult:
                raise ValueError("something went wrong")

        with _gen_ctx("invalid", repair_port_override=_RaisingRepair()) as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["repair_applied"] is False


# ===========================================================================
# F. Repair safety
# ===========================================================================


class TestRepairSafety:
    def test_repair_warnings_with_sensitive_content_redacted(self):
        with _gen_ctx("invalid", "sensitive") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        body = resp.json()
        # repair_result.repair_warnings must not contain raw tokens/passwords
        if body.get("repair_result") and body["repair_result"].get("repair_warnings"):
            for w in body["repair_result"]["repair_warnings"]:
                assert "password=hunter2" not in w
                assert "eyJhbGciOiJSUzI1NiJ9.fake.payload" not in w

    def test_full_response_no_sensitive_data(self):
        with _gen_ctx("invalid", "sensitive") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert_no_sensitive(resp.json())

    def test_no_raw_model_output_field(self):
        with _gen_ctx("invalid", "sensitive") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        body_str = str(resp.json())
        assert "raw_model_output" not in body_str

    def test_no_raw_exception_repr(self):
        with _gen_ctx("invalid", "sensitive") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        body_str = str(resp.json()).lower()
        assert "traceback" not in body_str

    def test_sanitize_warnings_covers_bearer(self):
        result = _sanitize_warnings(["auth: Bearer eyJhbGciOiJSUzI1NiJ9.x.y"])
        assert "Bearer eyJhbGciOiJSUzI1NiJ9" not in result[0]
        assert "[REDACTED]" in result[0]

    def test_sanitize_warnings_covers_password_eq(self):
        result = _sanitize_warnings(["hint: password=hunter2 used"])
        assert "hunter2" not in result[0]

    def test_sanitize_warnings_covers_token_colon(self):
        result = _sanitize_warnings(["token: mytoken123"])
        assert "mytoken123" not in result[0]
        assert "[REDACTED]" in result[0]


# ===========================================================================
# G. Regression
# ===========================================================================


class TestRepairRegression:
    def test_initial_valid_no_repair_called(self):
        call_log: list[str] = []

        class _SpyRepair(LabDraftRepairPort):
            def repair_draft_candidate(self, req: DraftRepairRequest) -> DraftRepairResult:
                call_log.append("called")
                return DraftRepairResult()

        with _gen_ctx("valid", repair_port_override=_SpyRepair()) as ctx:
            _post(ctx["client"], enable_repair=True)
        assert call_log == []

    def test_generation_no_lab_session_created(self):
        with _gen_ctx("invalid", "success") as ctx:
            from backend.labgen.lab_session_repository import LabSessionRepository
            from unittest.mock import patch

            with patch.object(LabSessionRepository, "create") as mock_create:
                _post(ctx["client"], enable_repair=True)
        mock_create.assert_not_called()

    def test_generation_not_auto_published(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        data = resp.json()
        if data.get("candidate_summary"):
            ps = data["candidate_summary"].get("publish_status", "")
            assert ps != PublishStatus.PUBLISHED.value

    def test_publish_status_never_exceeds_draft_or_blocked(self):
        for gen_mode in ("valid", "invalid"):
            with _gen_ctx(gen_mode, "success") as ctx:
                resp = _post(ctx["client"], enable_repair=(gen_mode == "invalid"))
            data = resp.json()
            if data.get("candidate_summary"):
                ps = data["candidate_summary"]["publish_status"]
                assert ps in (
                    PublishStatus.DRAFT.value,
                    PublishStatus.PUBLISH_BLOCKED.value,
                    PublishStatus.REVIEW_REQUIRED.value,
                ), f"Unexpected publish_status: {ps!r}"

    def test_selected_template_id_stable(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["selected_template_id"] is not None

    def test_candidate_summary_stable(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = _post(ctx["client"], enable_repair=True)
        assert resp.json()["candidate_summary"] is not None

    def test_enable_repair_default_is_false(self):
        # Omitting enable_repair must default to False (no repair called)
        with _gen_ctx("invalid") as ctx:
            resp = ctx["client"].post(
                "/api/lab-drafts/generate",
                json={"user_prompt": "Deploy nginx"},
            )
        assert resp.json()["repair_attempted"] is False

    def test_max_repair_attempts_rejected_if_above_2(self):
        with _gen_ctx("invalid", "success") as ctx:
            resp = ctx["client"].post(
                "/api/lab-drafts/generate",
                json={
                    "user_prompt": "Deploy nginx",
                    "enable_repair": True,
                    "max_repair_attempts": 99,
                },
            )
        assert resp.status_code == 422


# ===========================================================================
# H. Sanitizer unit tests
# ===========================================================================


class TestSanitizer:
    def test_sanitize_token_eq(self):
        out = sanitize_text("debug: token=abc123def")
        assert "abc123def" not in out
        assert "[REDACTED]" in out

    def test_sanitize_password_eq(self):
        out = sanitize_text("auth: password=s3cr3t!")
        assert "s3cr3t!" not in out
        assert "[REDACTED]" in out

    def test_sanitize_kubeconfig_colon(self):
        out = sanitize_text("kubeconfig: /etc/kube/config")
        assert "/etc/kube/config" not in out
        assert "[REDACTED]" in out

    def test_sanitize_kubeconfig_eq(self):
        out = sanitize_text("kubeconfig=/etc/kube/config")
        assert "/etc/kube/config" not in out

    def test_sanitize_bearer_token(self):
        out = sanitize_text("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig")
        assert "eyJhbGciOiJSUzI1NiJ9" not in out
        assert "[REDACTED]" in out

    def test_sanitize_jwt_standalone(self):
        out = sanitize_text("token was eyJhbGciOiJSUzI1NiJ9.payload.signature")
        assert "eyJhbGciOiJSUzI1NiJ9" not in out

    def test_sanitize_long_base64(self):
        long_b64 = "A" * 65
        out = sanitize_text(f"cert data: {long_b64}")
        assert long_b64 not in out
        assert "[REDACTED]" in out

    def test_sanitize_traceback(self):
        tb = "Traceback (most recent call last):\n  File 'x.py', line 1\nValueError: bad"
        out = sanitize_text(tb)
        assert "ValueError: bad" not in out or "Traceback" not in out

    def test_sanitize_stack_trace_label(self):
        out = sanitize_text("stack trace: some long trace here")
        assert "some long trace here" not in out
        assert "[REDACTED]" in out

    def test_sanitize_raw_exception_label(self):
        out = sanitize_text("raw exception: RuntimeError('oops')")
        assert "RuntimeError" not in out
        assert "[REDACTED]" in out

    def test_sanitize_token_colon_bearer_value_not_leaked(self):
        # "token: Bearer <value>" — kv_pat used to eat "Bearer" leaving value exposed
        out = sanitize_text("token: Bearer eyJhbGciOiJSUzI1NiJ9.abc.def")
        assert "eyJhbGciOiJSUzI1NiJ9" not in out

    def test_sanitize_private_key(self):
        out = sanitize_text("private_key=-----BEGIN RSA PRIVATE KEY-----")
        assert "BEGIN RSA" not in out

    def test_sanitize_credential(self):
        out = sanitize_text("credential=supersecret")
        assert "supersecret" not in out

    def test_sanitize_preserves_safe_text(self):
        safe = "deploy nginx pod with replica count 3"
        out = sanitize_text(safe)
        assert out == safe

    def test_sanitize_empty_string(self):
        assert sanitize_text("") == ""

    def test_sanitize_warnings_list(self):
        warnings = [
            "token=abc123",
            "safe message about deploying pods",
        ]
        result = _sanitize_warnings(warnings)
        assert "abc123" not in result[0]
        assert result[1] == "safe message about deploying pods"


# ===========================================================================
# I. Fake adapter unit tests
# ===========================================================================


class TestFakeRepairAdapter:
    def test_success_mode_returns_valid_candidate(self):
        adapter = DeterministicFakeDraftRepairAdapter("success")
        svc, _ = _make_svc("invalid")
        _, review = svc.review_candidate(
            FakeDraftGenerationAdapter("invalid")
            .generate_lab_draft_candidate(_req())
            .candidate
        )
        req = DraftRepairRequest(
            original_candidate={},
            review_result=review,
            requester_user_id="u1",
        )
        result = adapter.repair_draft_candidate(req)
        assert result.repaired_candidate is not None
        assert result.repair_applied is True

    def test_malformed_mode_returns_bad_candidate(self):
        adapter = DeterministicFakeDraftRepairAdapter("malformed")
        req = DraftRepairRequest(
            original_candidate={},
            review_result=DraftReviewResult(is_valid=False, sanitized_summary="x"),
            requester_user_id="u1",
        )
        result = adapter.repair_draft_candidate(req)
        # Service will fail to parse this
        assert result.repaired_candidate is not None
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LabDraft.model_validate(result.repaired_candidate)

    def test_still_invalid_mode_passes_pydantic_fails_validator(self):
        adapter = DeterministicFakeDraftRepairAdapter("still_invalid")
        req = DraftRepairRequest(
            original_candidate={},
            review_result=DraftReviewResult(is_valid=False, sanitized_summary="x"),
            requester_user_id="u1",
        )
        result = adapter.repair_draft_candidate(req)
        assert result.repaired_candidate is not None
        # Must parse
        draft = LabDraft.model_validate(result.repaired_candidate)
        # Must fail StaticValidator
        validator_results = StaticValidator().validate(draft)
        assert any(r.status == ValidatorStatus.FAILED for r in validator_results)

    def test_sensitive_mode_warnings_contain_credentials(self):
        adapter = DeterministicFakeDraftRepairAdapter("sensitive")
        req = DraftRepairRequest(
            original_candidate={},
            review_result=DraftReviewResult(is_valid=False, sanitized_summary="x"),
            requester_user_id="u1",
        )
        result = adapter.repair_draft_candidate(req)
        # Warnings contain raw credential-like strings (service must redact)
        combined = " ".join(result.repair_warnings)
        assert any(kw in combined for kw in ("token=", "password="))

    def test_adapter_does_not_set_repaired_validation_status(self):
        # Default is "not_attempted" — service overwrites it
        adapter = DeterministicFakeDraftRepairAdapter("success")
        req = DraftRepairRequest(
            original_candidate={},
            review_result=DraftReviewResult(is_valid=False, sanitized_summary="x"),
            requester_user_id="u1",
        )
        result = adapter.repair_draft_candidate(req)
        assert result.repaired_validation_status == "not_attempted"
