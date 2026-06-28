"""
Draft Preview & Review Snapshot API v0.1 — Tests.

Covers:
  A. Preview happy path — generated valid draft, full snapshot fields
  B. Manual draft preview — no generation metadata, source_type=unknown
  C. Validator issue preview — failed draft returns issues, is_publishable=false
  D. Repair metadata preview — current model: has_repair_history=False, repair_applied=None
  E. Permissions — admin OK, non-admin 403, nonexistent 404
  F. Safety — credential-like / traceback content in draft fields is [REDACTED]
  G. Regression — preview never publishes, starts sessions, mutates draft, creates audits

All tests use in-memory repos — no filesystem I/O, no real K3s, no real Proxmox.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.draft_preview import (
    DraftPreviewService,
    DraftPreviewSnapshot,
    sanitize_value,
)
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
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.repository import LabDraftRepository
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# In-memory repository
# ---------------------------------------------------------------------------


class _MemRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


# ---------------------------------------------------------------------------
# Draft / step builders
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str = "s1",
    why: str = "Understand how pod scheduling works",
    do: str = "Apply the manifest with kubectl apply -f pod.yaml",
    observe: str = "Pod enters Running state within 30 seconds",
    with_verify: bool = False,
) -> Step:
    verify = []
    if with_verify:
        verify = [
            VerifyTemplate(
                verify_id="v1",
                type=VerifyType.POD_RUNNING,
                name="nginx",
                namespace="{{lab_namespace}}",
            )
        ]
    return Step(
        step_id=step_id,
        order=1,
        why=why,
        do=do,
        observe=observe,
        explain=ExplainField(concept="Pod lifecycle", observation="Pod is Running"),
        verify=verify,
    )


def _make_valid_draft(**kw) -> LabDraft:
    return LabDraft(
        source_article_id=kw.get("source_article_id", "art-1"),
        title=kw.get("title", "Network Policy Lab"),
        description=kw.get("description", "Learn K8s NetworkPolicy"),
        estimated_duration_minutes=kw.get("estimated_duration_minutes", 45),
        runtime_requirements=RuntimeRequirements(),
        steps=kw.get("steps", [_make_step()]),
        cleanup=kw.get(
            "cleanup", CleanupSpec(namespace_cleanup=CleanupNamespace())
        ),
        publish_status=kw.get("publish_status", PublishStatus.DRAFT),
        validator_results=kw.get("validator_results", []),
    )


# ---------------------------------------------------------------------------
# Sensitive-data guard helpers
# ---------------------------------------------------------------------------

# Patterns that must never appear in preview responses.
# These mirror _REDACT_PATTERNS in llm_generation.py — if any survive sanitization
# that is a security defect.
_CREDENTIAL_PATTERNS = [
    # Bearer tokens — header value only, not the word "Bearer" alone
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._=+/\-]{8,}"),
    # key=value or key: value credential assignments
    re.compile(
        r"(?i)(token|password|secret|private_key|credential|kubeconfig)\s*[=:]\s*\S+"
    ),
    # JWT tokens (three base64url segments separated by dots)
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    # Long base64 blocks (certs, kubeconfig data)
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    # Python tracebacks
    re.compile(r"Traceback \(most recent call last\)"),
    # Stack trace markers
    re.compile(r"(?i)stack\s+trace"),
]


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


def assert_no_sensitive_preview_data(payload) -> None:
    """Assert no credential-like or traceback content exists in any leaf string."""
    for val in _leaf_strings(payload):
        for pat in _CREDENTIAL_PATTERNS:
            m = pat.search(val)
            assert m is None, (
                f"Sensitive pattern {pat.pattern!r} matched {m.group()!r} in: {val[:120]!r}"
            )


# ---------------------------------------------------------------------------
# Context manager wiring
# ---------------------------------------------------------------------------


@contextmanager
def _preview_ctx(*, admin: bool = True, draft: Optional[LabDraft] = None):
    """
    Wire up dependency overrides for preview endpoint tests.
    Yields dict with 'client', 'draft_repo', 'preview_svc'.
    """
    from backend.main import app
    from backend.auth_deps import get_current_user
    from backend.labgen.routes import get_preview_service, require_admin_user

    repo = _MemRepo()
    if draft is not None:
        repo.create(draft)

    validator = StaticValidator()
    preview_svc = DraftPreviewService(repo=repo, validator=validator)

    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_preview_service] = lambda: preview_svc

    if admin:
        app.dependency_overrides[require_admin_user] = lambda: "testadmin"
    else:
        # Non-admin: do NOT override require_admin_user — let it call auth_manager.is_admin
        # Override get_current_user so it returns a user that is_admin returns False for
        app.dependency_overrides[get_current_user] = lambda: "regularuser"

    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield {"client": client, "draft_repo": repo, "preview_svc": preview_svc}
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def _get_preview(client: TestClient, lab_id: str) -> dict:
    return client.get(f"/api/labgen/drafts/{lab_id}/preview")


# ---------------------------------------------------------------------------
# A. Preview happy path
# ---------------------------------------------------------------------------


class TestPreviewHappyPath:
    def test_200_for_valid_draft(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            r = _get_preview(ctx["client"], draft.lab_id)
            assert r.status_code == 200

    def test_contains_draft_id(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["draft_id"] == draft.lab_id

    def test_contains_title(self):
        draft = _make_valid_draft(title="My Test Lab")
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["title"] == "My Test Lab"

    def test_publish_status_in_response(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["publish_status"] == "draft"

    def test_summary_step_count(self):
        steps = [_make_step("s1"), _make_step("s2"), _make_step("s3")]
        draft = _make_valid_draft(steps=steps)
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["summary"]["step_count"] == 3

    def test_summary_objective_count(self):
        steps = [_make_step("s1"), _make_step("s2")]
        draft = _make_valid_draft(steps=steps)
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["summary"]["objective_count"] == 2

    def test_summary_check_count_with_verify(self):
        steps = [_make_step("s1", with_verify=True), _make_step("s2", with_verify=True)]
        draft = _make_valid_draft(steps=steps)
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["summary"]["check_count"] == 2

    def test_summary_check_count_no_verify(self):
        draft = _make_valid_draft(steps=[_make_step("s1", with_verify=False)])
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["summary"]["check_count"] == 0

    def test_objectives_list(self):
        steps = [_make_step("s1", why="Goal A"), _make_step("s2", why="Goal B")]
        draft = _make_valid_draft(steps=steps)
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["objectives"] == ["Goal A", "Goal B"]

    def test_steps_list_structure(self):
        draft = _make_valid_draft(steps=[_make_step("step-x")])
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert len(body["steps"]) == 1
            s = body["steps"][0]
            assert s["step_id"] == "step-x"
            assert "learner_goal" in s
            assert "instructions_summary" in s
            assert "expected_outcome_summary" in s

    def test_checks_in_steps(self):
        draft = _make_valid_draft(steps=[_make_step("s1", with_verify=True)])
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            checks = body["steps"][0]["checks"]
            assert len(checks) == 1
            c = checks[0]
            assert c["check_id"] == "v1"
            assert c["check_type"] == "pod_running"

    def test_is_publishable_true_for_valid_draft(self):
        # Pre-populate passing validator_results so no re-run needed
        from backend.labgen.models import SCHEMA_VERSION
        results = [
            ValidatorResult(
                check_id="cleanup.declared",
                status=ValidatorStatus.PASSED,
                blocking_level=BlockingLevel.PUBLISH_BLOCKING,
                field_path="cleanup",
                message="ok",
            )
        ]
        draft = _make_valid_draft(validator_results=results)
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["is_publishable"] is True

    def test_draft_state_unchanged_after_preview(self):
        draft = _make_valid_draft()
        original_status = draft.publish_status
        with _preview_ctx(draft=draft) as ctx:
            _get_preview(ctx["client"], draft.lab_id)
            stored = ctx["draft_repo"].get(draft.lab_id)
            # Stored draft is unchanged (preview never persists)
            assert stored.publish_status == original_status

    def test_selected_template_id_is_none(self):
        # LabDraft model doesn't store template provenance — must return None
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["summary"]["template_id"] is None

    def test_generated_at_present(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["generated_at"] is not None

    def test_no_raw_model_output_field(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert "raw_model_output" not in body

    def test_no_hidden_prompt_field(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert "hidden_prompt" not in body

    def test_no_provider_metadata_field(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert "provider_metadata" not in body


# ---------------------------------------------------------------------------
# B. Manual draft preview
# ---------------------------------------------------------------------------


class TestManualDraftPreview:
    def test_manual_draft_returns_200(self):
        draft = LabDraft(
            source_article_id="manual-article",
            title="Manual Lab",
            description="Created by admin",
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            steps=[_make_step()],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
        with _preview_ctx(draft=draft) as ctx:
            r = _get_preview(ctx["client"], draft.lab_id)
            assert r.status_code == 200

    def test_source_type_is_unknown(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            # Model doesn't store provenance — always "unknown"
            assert body["source_info"]["source_type"] == "unknown"

    def test_source_info_generation_warnings_empty(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["source_info"]["generation_warnings"] == []

    def test_no_generation_metadata_dependency(self):
        # Draft created without any template/generation fields still gives valid preview
        draft = LabDraft(
            source_article_id="manual",
            title="Plain Lab",
            description="No LLM involved",
            estimated_duration_minutes=20,
            runtime_requirements=RuntimeRequirements(),
            steps=[_make_step()],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["draft_id"] == draft.lab_id
            assert body["summary"]["step_count"] == 1


# ---------------------------------------------------------------------------
# C. Validator issue preview
# ---------------------------------------------------------------------------


class TestValidatorIssuePreview:
    def _make_invalid_draft(self) -> LabDraft:
        # cleanup=None causes cleanup.declared failure (PUBLISH_BLOCKING)
        return LabDraft(
            source_article_id="art-inv",
            title="Invalid Lab",
            description="desc",
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            steps=[_make_step()],
            cleanup=None,
        )

    def test_invalid_draft_returns_200(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            r = _get_preview(ctx["client"], draft.lab_id)
            assert r.status_code == 200

    def test_issues_non_empty(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert len(body["issues"]) > 0

    def test_issue_has_code(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            issue = body["issues"][0]
            assert "code" in issue
            assert issue["code"]  # non-empty

    def test_issue_has_severity(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            issue = body["issues"][0]
            assert issue["severity"] in ("error", "warning")

    def test_publish_blocking_issue_severity_is_error(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            errors = [i for i in body["issues"] if i["severity"] == "error"]
            assert len(errors) > 0

    def test_issue_has_source(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            issue = body["issues"][0]
            assert issue["source"] == "static_validator"

    def test_validation_status_failed(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["validation_status"] == "failed"

    def test_is_publishable_false(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["is_publishable"] is False

    def test_issue_message_is_string(self):
        draft = self._make_invalid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            for issue in body["issues"]:
                assert isinstance(issue["message"], str)
                assert len(issue["message"]) > 0

    def test_cached_validator_results_used(self):
        # Pre-populate failed result — service should use it, not re-run
        results = [
            ValidatorResult(
                check_id="my_custom_check",
                status=ValidatorStatus.FAILED,
                blocking_level=BlockingLevel.PUBLISH_BLOCKING,
                field_path="steps",
                message="custom failure",
            )
        ]
        draft = _make_valid_draft(validator_results=results)
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            codes = [i["code"] for i in body["issues"]]
            assert "my_custom_check" in codes


# ---------------------------------------------------------------------------
# D. Repair metadata preview
# ---------------------------------------------------------------------------


class TestRepairMetadataPreview:
    def test_has_repair_history_false(self):
        # LabDraft model has no repair metadata field — always False
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["summary"]["has_repair_history"] is False

    def test_repair_applied_is_none(self):
        # No repair provenance stored in LabDraft — repair_applied = None
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["source_info"]["repair_applied"] is None

    def test_selected_template_id_is_none(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert body["source_info"]["selected_template_id"] is None

    def test_no_repair_history_no_extra_fields(self):
        # Ensure no phantom repair-related top-level fields
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert "repaired_candidate" not in body
            assert "repair_result" not in body
            assert "raw_repair" not in body


# ---------------------------------------------------------------------------
# E. Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_admin_can_get_preview(self):
        draft = _make_valid_draft()
        with _preview_ctx(admin=True, draft=draft) as ctx:
            r = _get_preview(ctx["client"], draft.lab_id)
            assert r.status_code == 200

    def test_non_admin_gets_403(self):
        draft = _make_valid_draft()
        # For non-admin: we need a draft in the shared repo but the client
        # has no admin override — use a pre-wired client that's not admin
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_repository, require_admin_user

        repo = _MemRepo()
        repo.create(draft)
        saved = dict(app.dependency_overrides)
        app.dependency_overrides[get_repository] = lambda: repo
        app.dependency_overrides[get_current_user] = lambda: "regularuser"
        # Do NOT override require_admin_user — let it call auth_manager.is_admin

        client = TestClient(app, raise_server_exceptions=True)
        try:
            r = _get_preview(client, draft.lab_id)
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)

    def test_nonexistent_draft_404(self):
        with _preview_ctx(admin=True) as ctx:
            r = _get_preview(ctx["client"], "does-not-exist")
            assert r.status_code == 404

    def test_404_detail_message(self):
        with _preview_ctx(admin=True) as ctx:
            r = _get_preview(ctx["client"], "ghost-id")
            assert "not found" in r.json()["detail"].lower()

    def test_different_admin_can_see_any_draft(self):
        # Preview is not owner-restricted — any admin can view
        draft = _make_valid_draft()
        with _preview_ctx(admin=True, draft=draft) as ctx:
            r = _get_preview(ctx["client"], draft.lab_id)
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# F. Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def _make_sensitive_draft(self) -> LabDraft:
        return _make_valid_draft(
            title="Lab with token=eyJhbGciOiJSUzI1NiJ9.fake.payload in title",
            steps=[
                _make_step(
                    why="password=hunter2 setup step",
                    do="kubectl apply -f secret.yaml  # kubeconfig: /root/.kube/config",
                    observe="service started; private_key=/etc/ssl/private/lab.key",
                )
            ],
        )

    def test_sensitive_title_redacted(self):
        draft = self._make_sensitive_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert "eyJhbGciOiJSUzI1NiJ9" not in body["title"]
            assert "[REDACTED]" in body["title"]

    def test_sensitive_step_fields_redacted(self):
        draft = self._make_sensitive_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            step = body["steps"][0]
            # password= in why → redacted in learner_goal
            assert "hunter2" not in step["learner_goal"]
            # kubeconfig: in do → redacted in instructions_summary
            assert "kubeconfig" not in step["instructions_summary"].lower()
            # private_key= in observe → redacted in expected_outcome_summary
            assert "private_key" not in step["expected_outcome_summary"].lower()

    def test_full_response_no_sensitive_data(self):
        draft = self._make_sensitive_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert_no_sensitive_preview_data(body)

    def test_bearer_token_in_step_redacted(self):
        draft = _make_valid_draft(
            steps=[_make_step(do="curl -H 'Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.x.y' https://k8s-api")]
        )
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            instr = body["steps"][0]["instructions_summary"]
            assert "eyJhbGciOiJSUzI1NiJ9" not in instr
            assert "Bearer" not in instr or "[REDACTED]" in instr

    def test_long_base64_in_step_redacted(self):
        long_b64 = "A" * 80  # pure base64-alphabet string longer than 60 chars
        draft = _make_valid_draft(
            steps=[_make_step(do=f"echo data={long_b64} | base64 -d")]
        )
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            instr = body["steps"][0]["instructions_summary"]
            assert long_b64 not in instr

    def test_validator_message_sanitized(self):
        sensitive_msg = "cleanup missing: token=eyJhbGciOiJSUzI1NiJ9.x.y"
        results = [
            ValidatorResult(
                check_id="cleanup.declared",
                status=ValidatorStatus.FAILED,
                blocking_level=BlockingLevel.PUBLISH_BLOCKING,
                field_path="cleanup",
                message=sensitive_msg,
            )
        ]
        draft = _make_valid_draft(validator_results=results)
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            for issue in body["issues"]:
                assert "eyJhbGciOiJSUzI1NiJ9" not in issue["message"]

    def test_no_raw_exception_in_response(self):
        # Even if draft fields trigger edge cases, response must not contain tracebacks
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            payload_str = str(body)
            assert "Traceback" not in payload_str
            assert "stack trace" not in payload_str.lower()

    def test_no_repaired_candidate_in_response(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert "repaired_candidate" not in body

    def test_no_raw_model_output_in_response(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert "raw_model_output" not in body

    def test_no_provider_metadata_in_response(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            body = _get_preview(ctx["client"], draft.lab_id).json()
            assert "provider_metadata" not in body


# ---------------------------------------------------------------------------
# G. Regression
# ---------------------------------------------------------------------------


class TestRegression:
    def test_preview_does_not_publish(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            _get_preview(ctx["client"], draft.lab_id)
            stored = ctx["draft_repo"].get(draft.lab_id)
            assert stored.publish_status != PublishStatus.PUBLISHED

    def test_preview_does_not_change_publish_status(self):
        draft = _make_valid_draft(publish_status=PublishStatus.PUBLISH_BLOCKED)
        with _preview_ctx(draft=draft) as ctx:
            _get_preview(ctx["client"], draft.lab_id)
            stored = ctx["draft_repo"].get(draft.lab_id)
            assert stored.publish_status == PublishStatus.PUBLISH_BLOCKED

    def test_preview_does_not_start_lab(self):
        from backend.labgen.lab_session_repository import LabSessionRepository
        original_create = LabSessionRepository.create
        created = []

        def _spy_create(self, s):
            created.append(s)
            return original_create(self, s)

        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            LabSessionRepository.create = _spy_create
            try:
                _get_preview(ctx["client"], draft.lab_id)
            finally:
                LabSessionRepository.create = original_create

        assert created == [], "preview must not create lab sessions"

    def test_preview_does_not_create_audit_event(self):
        from backend.labgen.runtime_audit import RuntimeAuditRepository
        original_append = RuntimeAuditRepository.append
        appended = []

        def _spy_append(self, e):
            appended.append(e)
            return original_append(self, e)

        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            RuntimeAuditRepository.append = _spy_append
            try:
                _get_preview(ctx["client"], draft.lab_id)
            finally:
                RuntimeAuditRepository.append = original_append

        assert appended == [], "preview must not create audit events"

    def test_preview_does_not_persist_validator_results(self):
        # Draft with no cached validator_results: preview runs validator but must NOT save
        draft = _make_valid_draft(validator_results=[])
        with _preview_ctx(draft=draft) as ctx:
            _get_preview(ctx["client"], draft.lab_id)
            stored = ctx["draft_repo"].get(draft.lab_id)
            assert stored.validator_results == []

    def test_get_only_not_post(self):
        draft = _make_valid_draft()
        with _preview_ctx(draft=draft) as ctx:
            r = ctx["client"].post(f"/api/labgen/drafts/{draft.lab_id}/preview")
            assert r.status_code == 405

    def test_generate_api_still_works(self):
        # Smoke: POST /api/lab-drafts/generate still returns 201 (admin-only)
        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import require_admin_user

        saved = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: "admin"
        app.dependency_overrides[require_admin_user] = lambda: "admin"
        client = TestClient(app, raise_server_exceptions=True)
        try:
            r = client.post(
                "/api/lab-drafts/generate",
                json={"user_prompt": "Deploy nginx and expose it"},
            )
            assert r.status_code == 201
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)


# ---------------------------------------------------------------------------
# H. sanitize_value unit tests
# ---------------------------------------------------------------------------


class TestSanitizeValue:
    def test_string_redacts_bearer(self):
        result = sanitize_value("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.x.y")
        assert "eyJhbGciOiJSUzI1NiJ9" not in result

    def test_string_redacts_password(self):
        result = sanitize_value("password=hunter2")
        assert "hunter2" not in result

    def test_list_redacts_each_string(self):
        result = sanitize_value(["ok", "token=abc123", "clean"])
        assert "abc123" not in str(result)

    def test_dict_redacts_values(self):
        result = sanitize_value({"msg": "kubeconfig: /etc/kube/config"})
        assert "kubeconfig" not in str(result).lower()

    def test_nested_dict_list_redacted(self):
        payload = {"steps": [{"do": "password=secret123 kubectl apply"}]}
        result = sanitize_value(payload)
        assert "secret123" not in str(result)

    def test_non_string_scalar_unchanged(self):
        assert sanitize_value(42) == 42
        assert sanitize_value(True) is True
        assert sanitize_value(None) is None


# ---------------------------------------------------------------------------
# I. DraftPreviewService unit tests (service layer, no HTTP)
# ---------------------------------------------------------------------------


class TestDraftPreviewService:
    def _svc(self, repo=None) -> DraftPreviewService:
        return DraftPreviewService(
            repo=repo or _MemRepo(), validator=StaticValidator()
        )

    def test_build_snapshot_returns_none_for_missing_draft(self):
        svc = self._svc()
        assert svc.build_snapshot("nonexistent") is None

    def test_build_snapshot_returns_snapshot_for_existing_draft(self):
        repo = _MemRepo()
        draft = _make_valid_draft()
        repo.create(draft)
        svc = self._svc(repo)
        snapshot = svc.build_snapshot(draft.lab_id)
        assert snapshot is not None
        assert isinstance(snapshot, DraftPreviewSnapshot)

    def test_snapshot_draft_id_matches(self):
        repo = _MemRepo()
        draft = _make_valid_draft()
        repo.create(draft)
        snapshot = self._svc(repo).build_snapshot(draft.lab_id)
        assert snapshot.draft_id == draft.lab_id

    def test_snapshot_objectives_match_step_why_fields(self):
        repo = _MemRepo()
        steps = [_make_step("s1", why="Goal One"), _make_step("s2", why="Goal Two")]
        draft = _make_valid_draft(steps=steps)
        repo.create(draft)
        snapshot = self._svc(repo).build_snapshot(draft.lab_id)
        assert snapshot.objectives == ["Goal One", "Goal Two"]

    def test_snapshot_validation_status_not_validated_when_no_results(self):
        # A draft with no validator_results and cleanup=None will actually run the
        # validator — this test verifies a valid draft with no cached results
        # gets a non-"not_validated" status (validator runs inline)
        repo = _MemRepo()
        draft = _make_valid_draft(validator_results=[])
        repo.create(draft)
        snapshot = self._svc(repo).build_snapshot(draft.lab_id)
        # Validator ran inline — status should be "passed" or "failed"
        assert snapshot.validation_status in ("passed", "failed")

    def test_snapshot_validation_status_failed_when_cached_fail(self):
        repo = _MemRepo()
        results = [
            ValidatorResult(
                check_id="some_check",
                status=ValidatorStatus.FAILED,
                blocking_level=BlockingLevel.PUBLISH_BLOCKING,
                field_path="steps",
                message="fail",
            )
        ]
        draft = _make_valid_draft(validator_results=results)
        repo.create(draft)
        snapshot = self._svc(repo).build_snapshot(draft.lab_id)
        assert snapshot.validation_status == "failed"

    def test_snapshot_has_repair_history_always_false(self):
        repo = _MemRepo()
        draft = _make_valid_draft()
        repo.create(draft)
        snapshot = self._svc(repo).build_snapshot(draft.lab_id)
        assert snapshot.summary.has_repair_history is False

    def test_snapshot_source_type_always_unknown(self):
        repo = _MemRepo()
        draft = _make_valid_draft()
        repo.create(draft)
        snapshot = self._svc(repo).build_snapshot(draft.lab_id)
        assert snapshot.source_info.source_type == "unknown"

    def test_snapshot_repair_applied_always_none(self):
        repo = _MemRepo()
        draft = _make_valid_draft()
        repo.create(draft)
        snapshot = self._svc(repo).build_snapshot(draft.lab_id)
        assert snapshot.source_info.repair_applied is None

    def test_snapshot_draft_not_persisted(self):
        repo = _MemRepo()
        draft = _make_valid_draft(validator_results=[])
        original_update = repo.update
        calls = []

        def spy_update(d):
            calls.append(d)
            return original_update(d)

        repo.update = spy_update
        repo.create(draft)
        self._svc(repo).build_snapshot(draft.lab_id)
        assert calls == [], "build_snapshot must not call repo.update"
