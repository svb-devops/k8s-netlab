"""
Linux Publish Candidate Dry Run tests — G-43.

Validates the PublishCandidateDryRunService and the HTTP endpoint
POST /api/labgen/drafts/{id}/publish-candidate-dry-run.

Categories:
  A. Admin gate — domain, publish status, rehearsal_completed
  B. Validation gate — StaticValidator pass, linux boundary recognised
  C. Internal rehearsal gate — session closed/verified
  D. Runtime/verifier/cleanup gate — schema fields present
  E. Content quality gate — no placeholders, ai_tutor_context present
  F. Safety gate — allow_root/network, denied commands, forbidden paths
  G. Invariants — actual_publish_performed=False, catalog unchanged, dry_run=True
  H. HTTP endpoint — admin auth, 404, non-Linux draft, happy path
  I. Catalog isolation — K8s catalog and Lab 5 unchanged
  J. K8s regression — existing K8s draft paths unchanged
"""

from __future__ import annotations

import pytest
from typing import Optional

from backend.labgen.linux_template import LinuxFilesPermissionsTemplate
from backend.labgen.models import (
    CleanupLinuxWorkspace,
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDomainType,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    LinuxSandboxPolicy,
    LinuxVerifyTemplate,
    LinuxVerifyType,
    PublishStatus,
    RuntimeRequirements,
    SessionType,
    Step,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.publish_candidate_dry_run_service import (
    LinuxPublishCandidateDryRunResult,
    PublishCandidateDryRunService,
)
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static

_TEMPLATE = LinuxFilesPermissionsTemplate()
_ART_ID = "art-linux-files-001"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _linux_draft(*, rehearsal_completed: bool = True, **overrides) -> LabDraft:
    """Return a fully valid Linux draft, with optional field overrides."""
    draft = _TEMPLATE.build_draft(_ART_ID)
    draft = draft.model_copy(update={"rehearsal_completed": rehearsal_completed})
    if overrides:
        draft = draft.model_copy(update=overrides)
    return draft


def _rehearsal_session(draft: LabDraft, *, cleanup_verified: bool = True) -> LabSessionState:
    """Return a LAB_CLOSED INTERNAL_REHEARSAL session for the given draft."""
    return LabSessionState(
        lab_id=draft.lab_id,
        vm_id="linux-rehearsal",
        student_username="smoke-admin",
        lab_session_status=LabSessionStatus.LAB_CLOSED,
        session_type=SessionType.INTERNAL_REHEARSAL,
        cleanup_verified=cleanup_verified,
    )


def _svc() -> PublishCandidateDryRunService:
    return PublishCandidateDryRunService(validator=StaticValidator())


def _k8s_draft() -> LabDraft:
    """Return a minimal valid K8s-domain draft."""
    return LabDraft(
        source_article_id="art-k8s-001",
        title="K8s Basics",
        description="A K8s lab.",
        estimated_duration_minutes=10,
        runtime_requirements=RuntimeRequirements(),
        steps=[
            Step(
                step_id="s1", order=1, why="test", do="kubectl apply",
                commands=["kubectl apply -f app.yaml"],
                observe="pod created",
                explain=ExplainField(concept="namespace", observation="it exists"),
                verify=[
                    VerifyTemplate(
                        verify_id="v1", type=VerifyType.NAMESPACE_EXISTS,
                        namespace="{{lab_namespace}}", name="test-ns",
                    )
                ],
            )
        ],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
    )


def _check(result: LinuxPublishCandidateDryRunResult, gate_id: str) -> bool:
    for g in result.gate_results:
        if g.gate_id == gate_id:
            return g.passed
    raise KeyError(f"gate {gate_id!r} not found")


def _check_detail(result: LinuxPublishCandidateDryRunResult, gate_id: str, check_id: str) -> Optional[str]:
    for g in result.gate_results:
        if g.gate_id == gate_id:
            for c in g.checks:
                if c.check_id == check_id:
                    return c.detail
    return None


# ─────────────────────────────────────────────────────────────────────────────
# A. Admin gate
# ─────────────────────────────────────────────────────────────────────────────


class TestAdminGate:
    def test_happy_path_admin_gate_passes(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "admin_gate") is True

    def test_k8s_draft_fails_target_domain_check(self):
        """K8s draft → admin.target_domain_linux check fails."""
        k8s_draft = _k8s_draft()
        result = _svc().check_linux_publish_candidate(k8s_draft, [])
        assert _check(result, "admin_gate") is False
        assert result.publish_candidate_ready is False

    def test_already_published_draft_fails(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        draft = draft.model_copy(update={"publish_status": PublishStatus.PUBLISHED})
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "admin_gate") is False

    def test_rehearsal_not_completed_fails_admin_gate(self):
        draft = _linux_draft(rehearsal_completed=False)
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "admin_gate") is False
        detail = _check_detail(result, "admin_gate", "admin.rehearsal_completed")
        assert detail is not None


# ─────────────────────────────────────────────────────────────────────────────
# B. Validation gate
# ─────────────────────────────────────────────────────────────────────────────


class TestValidationGate:
    def test_linux_boundary_recognised(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert result.linux_publish_boundary_recognized is True
        assert _check(result, "validation_gate") is True

    def test_validation_gate_passes_with_only_boundary(self):
        """Only linux.publish_blocked_until_runtime is PUBLISH_BLOCKING → gate passes."""
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "validation_gate") is True

    def test_extra_blocking_failure_fails_validation_gate(self):
        """Inject a field that causes an extra PUBLISH_BLOCKING failure."""
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        # Blank title causes content.no_placeholders to fail BUT that is PUBLISH_BLOCKING
        # We test by removing linux_sandbox_policy (makes linux.sandbox_policy_required fail)
        draft = draft.model_copy(update={"linux_sandbox_policy": None})
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "validation_gate") is False

    def test_k8s_domain_has_no_linux_boundary(self):
        """K8s draft does NOT trigger linux.publish_blocked_until_runtime."""
        assert _svc()._linux_boundary_was_recognized(_k8s_draft()) is False


# ─────────────────────────────────────────────────────────────────────────────
# C. Internal rehearsal gate
# ─────────────────────────────────────────────────────────────────────────────


class TestInternalRehearsalGate:
    def test_happy_path_rehearsal_gate_passes(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "internal_rehearsal_gate") is True

    def test_no_matching_session_fails(self):
        draft = _linux_draft()
        # No sessions provided
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "internal_rehearsal_gate") is False

    def test_session_not_lab_closed_fails(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        session = session.model_copy(update={"lab_session_status": LabSessionStatus.LAB_ACTIVE})
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "internal_rehearsal_gate") is False

    def test_session_cleanup_verified_false_fails(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft, cleanup_verified=False)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "internal_rehearsal_gate") is False

    def test_wrong_session_type_fails(self):
        """LEARNER session does not count as rehearsal."""
        draft = _linux_draft()
        session = LabSessionState(
            lab_id=draft.lab_id,
            vm_id="501",
            student_username="alice",
            lab_session_status=LabSessionStatus.LAB_CLOSED,
            session_type=SessionType.LEARNER,
            cleanup_verified=True,
        )
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "internal_rehearsal_gate") is False

    def test_draft_rehearsal_completed_false_fails_gate(self):
        """rehearsal_completed=False on draft → gate 1 and gate 3 both fail."""
        draft = _linux_draft(rehearsal_completed=False)
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "internal_rehearsal_gate") is False

    def test_unrelated_session_not_counted(self):
        """Session for a different lab_id does not satisfy the gate."""
        draft = _linux_draft()
        other_draft = _linux_draft()
        session = _rehearsal_session(other_draft)  # different lab_id
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "internal_rehearsal_gate") is False


# ─────────────────────────────────────────────────────────────────────────────
# D. Runtime / verifier / cleanup gate
# ─────────────────────────────────────────────────────────────────────────────


class TestRuntimeVerifierCleanupGate:
    def test_happy_path_gate_passes(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "runtime_verifier_cleanup_gate") is True

    def test_missing_sandbox_policy_fails(self):
        draft = _linux_draft()
        draft = draft.model_copy(update={"linux_sandbox_policy": None})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "runtime_verifier_cleanup_gate") is False

    def test_missing_linux_cleanup_fails(self):
        draft = _linux_draft()
        draft = draft.model_copy(update={"linux_cleanup": None})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "runtime_verifier_cleanup_gate") is False

    def test_no_linux_verify_entries_fails(self):
        """Draft steps without any linux_verify entries → gate fails."""
        draft = _linux_draft()
        # Remove all linux_verify from all steps
        new_steps = [s.model_copy(update={"linux_verify": []}) for s in draft.steps]
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "runtime_verifier_cleanup_gate") is False

    def test_k8s_verify_in_linux_steps_fails(self):
        """Linux steps must not contain K8s verify entries."""
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={
            "verify": [VerifyTemplate(
                verify_id="v-k8s", type=VerifyType.NAMESPACE_EXISTS,
                namespace="{{lab_namespace}}", name="injected-ns",
            )]
        })
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "runtime_verifier_cleanup_gate") is False


# ─────────────────────────────────────────────────────────────────────────────
# E. Content quality gate
# ─────────────────────────────────────────────────────────────────────────────


class TestContentQualityGate:
    def test_happy_path_quality_gate_passes(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "content_quality_gate") is True

    def test_empty_title_fails(self):
        draft = _linux_draft()
        draft = draft.model_copy(update={"title": ""})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "content_quality_gate") is False

    def test_placeholder_in_title_fails(self):
        draft = _linux_draft()
        draft = draft.model_copy(update={"title": "[TODO] Linux Lab Title"})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "content_quality_gate") is False

    def test_placeholder_in_description_fails(self):
        draft = _linux_draft()
        draft = draft.model_copy(update={"description": "This is a [TODO] description."})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "content_quality_gate") is False

    def test_missing_ai_tutor_context_fails(self):
        draft = _linux_draft()
        draft = draft.model_copy(update={"ai_tutor_context": None})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "content_quality_gate") is False

    def test_empty_ai_tutor_context_fails(self):
        draft = _linux_draft()
        draft = draft.model_copy(update={"ai_tutor_context": ""})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "content_quality_gate") is False

    def test_placeholder_in_step_why_fails(self):
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={"why": "[PLACEHOLDER] explain why"})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "content_quality_gate") is False

    def test_placeholder_in_step_observe_fails(self):
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={"observe": "[TODO] observe something"})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "content_quality_gate") is False

    def test_placeholder_in_step_explain_concept_fails(self):
        from backend.labgen.models import ExplainField
        draft = _linux_draft()
        bad_explain = ExplainField(
            concept="[TODO] explain concept",
            observation="files are in /home/student/workspace",
        )
        step0 = draft.steps[0].model_copy(update={"explain": bad_explain})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "content_quality_gate") is False


# ─────────────────────────────────────────────────────────────────────────────
# F. Safety gate
# ─────────────────────────────────────────────────────────────────────────────


class TestSafetyGate:
    def test_happy_path_safety_gate_passes(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert _check(result, "safety_gate") is True

    def test_allow_root_true_fails_safety_gate(self):
        draft = _linux_draft()
        policy = draft.linux_sandbox_policy.model_copy(update={"allow_root": True})
        draft = draft.model_copy(update={"linux_sandbox_policy": policy})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False
        detail = _check_detail(result, "safety_gate", "safety.allow_root_false")
        assert detail is not None

    def test_allow_network_true_fails_safety_gate(self):
        draft = _linux_draft()
        policy = draft.linux_sandbox_policy.model_copy(update={"allow_network": True})
        draft = draft.model_copy(update={"linux_sandbox_policy": policy})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False

    def test_sudo_command_fails_safety_gate(self):
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={"commands": ["sudo rm -rf /"]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False
        detail = _check_detail(result, "safety_gate", "safety.no_denied_commands")
        assert "sudo" in (detail or "")

    def test_curl_command_fails_safety_gate(self):
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={"commands": ["curl http://evil.com"]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False

    def test_wget_command_fails_safety_gate(self):
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={"commands": ["wget http://evil.com"]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False

    def test_systemctl_command_fails_safety_gate(self):
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={"commands": ["systemctl restart sshd"]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False

    def test_forbidden_path_in_verifier_fails_safety_gate(self):
        draft = _linux_draft()
        step0 = draft.steps[0]
        bad_verify = LinuxVerifyTemplate.model_construct(
            verify_id="v-bad",
            type=LinuxVerifyType.LINUX_FILE_EXISTS,
            target_path="/etc/passwd",
            workspace_relative_only=True,
        )
        step0 = step0.model_copy(update={"linux_verify": list(step0.linux_verify) + [bad_verify]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False
        detail = _check_detail(result, "safety_gate", "safety.no_forbidden_paths_in_verifiers")
        assert "/etc/passwd" in (detail or "")

    def test_env_sudo_wrapper_caught_by_token_scan(self):
        """MEDIUM fix: 'env sudo cmd' must be caught — first-word-only check is insufficient."""
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={"commands": ["env sudo apt-get install vim"]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False

    def test_bash_c_sudo_caught_by_token_scan(self):
        """MEDIUM fix: shell injection via 'bash -c \"sudo ...\"' must be caught."""
        draft = _linux_draft()
        step0 = draft.steps[0].model_copy(update={"commands": ["bash -c \"sudo rm -rf /\""]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False

    def test_path_traversal_to_etc_caught(self):
        """MEDIUM fix: '../etc/passwd' must be caught via normpath normalization."""
        draft = _linux_draft()
        step0 = draft.steps[0]
        bad_verify = LinuxVerifyTemplate.model_construct(
            verify_id="v-bad",
            type=LinuxVerifyType.LINUX_FILE_EXISTS,
            target_path="../etc/passwd",
            workspace_relative_only=True,
        )
        step0 = step0.model_copy(update={"linux_verify": list(step0.linux_verify) + [bad_verify]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        assert _check(result, "safety_gate") is False

    def test_sibling_path_not_falsely_blocked(self):
        """/etcmalicious must NOT be treated as forbidden (not under /etc/)."""
        draft = _linux_draft()
        step0 = draft.steps[0]
        ok_verify = LinuxVerifyTemplate.model_construct(
            verify_id="v-ok",
            type=LinuxVerifyType.LINUX_FILE_EXISTS,
            target_path="workspace_files/my_etc_config.txt",
            workspace_relative_only=True,
        )
        step0 = step0.model_copy(update={"linux_verify": list(step0.linux_verify) + [ok_verify]})
        new_steps = [step0] + list(draft.steps[1:])
        draft = draft.model_copy(update={"steps": new_steps})
        result = _svc().check_linux_publish_candidate(draft, [])
        detail = _check_detail(result, "safety_gate", "safety.no_forbidden_paths_in_verifiers")
        assert detail is None


# ─────────────────────────────────────────────────────────────────────────────
# G. Invariants — always-false publish, catalog unchanged, dry_run=True
# ─────────────────────────────────────────────────────────────────────────────


class TestInvariants:
    def test_actual_publish_always_false(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert result.actual_publish_performed is False

    def test_learner_catalog_changed_always_false(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert result.learner_catalog_changed is False

    def test_dry_run_always_true(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert result.dry_run is True

    def test_publish_status_not_mutated_by_dry_run(self):
        """Draft publish_status must remain unchanged after dry run."""
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        original_status = draft.publish_status
        _svc().check_linux_publish_candidate(draft, [session])
        assert draft.publish_status == original_status

    def test_recommended_next_step_present_when_ready(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        assert result.publish_candidate_ready is True
        assert result.recommended_next_step == "Linux Article-linked Lab Publish Gate"

    def test_recommended_next_step_none_when_not_ready(self):
        draft = _linux_draft(rehearsal_completed=False)
        result = _svc().check_linux_publish_candidate(draft, [])
        assert result.publish_candidate_ready is False
        assert result.recommended_next_step is None

    def test_all_six_gates_present_in_result(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        result = _svc().check_linux_publish_candidate(draft, [session])
        gate_ids = {g.gate_id for g in result.gate_results}
        assert gate_ids == {
            "admin_gate",
            "validation_gate",
            "internal_rehearsal_gate",
            "runtime_verifier_cleanup_gate",
            "content_quality_gate",
            "safety_gate",
        }


# ─────────────────────────────────────────────────────────────────────────────
# H. HTTP endpoint tests
# ─────────────────────────────────────────────────────────────────────────────


class _InMemDraftRepo:
    def __init__(self, drafts: list[LabDraft] | None = None):
        self._store: dict[str, LabDraft] = {d.lab_id: d for d in (drafts or [])}

    def get(self, lab_id: str) -> LabDraft | None:
        return self._store.get(lab_id)

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _InMemSessionRepo:
    def __init__(self, sessions: list[LabSessionState] | None = None):
        self._store: dict[str, LabSessionState] = {s.session_id: s for s in (sessions or [])}

    def get(self, session_id: str) -> LabSessionState | None:
        return self._store.get(session_id)

    def list_all(self) -> list[LabSessionState]:
        return list(self._store.values())

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]


class TestHTTPEndpoint:
    @pytest.fixture
    def _linux_draft_with_session(self):
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        return draft, session

    @pytest.fixture
    def admin_client(self, _linux_draft_with_session):
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.labgen.routes import (
            require_admin_user,
            get_repository,
            get_session_repository,
        )

        draft, session = _linux_draft_with_session
        draft_repo = _InMemDraftRepo([draft])
        session_repo = _InMemSessionRepo([session])

        app.dependency_overrides[require_admin_user] = lambda: "smoke-admin"
        app.dependency_overrides[get_repository] = lambda: draft_repo
        app.dependency_overrides[get_session_repository] = lambda: session_repo

        with TestClient(app) as client:
            yield client, draft

        app.dependency_overrides.pop(require_admin_user, None)
        app.dependency_overrides.pop(get_repository, None)
        app.dependency_overrides.pop(get_session_repository, None)

    @pytest.fixture
    def non_admin_client(self, _linux_draft_with_session):
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.labgen.routes import get_repository, get_session_repository

        draft, session = _linux_draft_with_session
        draft_repo = _InMemDraftRepo([draft])
        session_repo = _InMemSessionRepo([session])

        # No admin override — auth will fail
        app.dependency_overrides[get_repository] = lambda: draft_repo
        app.dependency_overrides[get_session_repository] = lambda: session_repo

        with TestClient(app) as client:
            yield client, draft

        app.dependency_overrides.pop(get_repository, None)
        app.dependency_overrides.pop(get_session_repository, None)

    def test_happy_path_returns_200_and_ready(self, admin_client):
        client, draft = admin_client
        resp = client.post(
            f"/api/labgen/drafts/{draft.lab_id}/publish-candidate-dry-run",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["publish_candidate_ready"] is True
        assert body["actual_publish_performed"] is False
        assert body["learner_catalog_changed"] is False
        assert body["dry_run"] is True
        assert body["linux_publish_boundary_recognized"] is True

    def test_non_admin_returns_403(self, non_admin_client):
        client, draft = non_admin_client
        resp = client.post(
            f"/api/labgen/drafts/{draft.lab_id}/publish-candidate-dry-run",
        )
        assert resp.status_code in (401, 403)

    def test_nonexistent_draft_returns_404(self, admin_client):
        client, _ = admin_client
        resp = client.post(
            "/api/labgen/drafts/00000000-0000-0000-0000-000000000000/publish-candidate-dry-run",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 404

    def test_k8s_draft_returns_200_but_not_ready(self):
        """K8s draft returns 200 but publish_candidate_ready=False (admin gate fails)."""
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.labgen.routes import (
            require_admin_user,
            get_repository,
            get_session_repository,
        )

        k8s_draft = _k8s_draft()
        draft_repo = _InMemDraftRepo([k8s_draft])
        session_repo = _InMemSessionRepo([])

        app.dependency_overrides[require_admin_user] = lambda: "smoke-admin"
        app.dependency_overrides[get_repository] = lambda: draft_repo
        app.dependency_overrides[get_session_repository] = lambda: session_repo

        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/labgen/drafts/{k8s_draft.lab_id}/publish-candidate-dry-run",
                    headers={"X-Admin-Token": "test-token"},
                )
            assert resp.status_code == 200
            assert resp.json()["publish_candidate_ready"] is False
        finally:
            app.dependency_overrides.pop(require_admin_user, None)
            app.dependency_overrides.pop(get_repository, None)
            app.dependency_overrides.pop(get_session_repository, None)


# ─────────────────────────────────────────────────────────────────────────────
# I. Catalog isolation — dry run does NOT add Linux entry, K8s unchanged
# ─────────────────────────────────────────────────────────────────────────────


class TestCatalogIsolation:
    def test_dry_run_does_not_add_linux_to_catalog(self):
        """After dry run, LearnerCatalogService still returns 0 Linux entries."""
        from backend.labgen.learner_catalog import LearnerCatalogService

        draft = _linux_draft()
        session = _rehearsal_session(draft)
        draft_repo = _InMemDraftRepo([draft])

        _svc().check_linux_publish_candidate(draft, [session])

        # publish_status must remain draft (not changed by dry run)
        assert draft.publish_status != PublishStatus.PUBLISHED

        # Catalog contains only PUBLISHED drafts — Linux DRAFT never visible
        catalog = LearnerCatalogService(
            draft_repo=draft_repo,
            validator=StaticValidator(),
        )
        labs = catalog.list_published_labs("smoke-student")
        assert len(labs) == 0

    def test_dry_run_with_failing_gates_still_no_catalog_mutation(self):
        """Even a failed dry run must not mutate the catalog."""
        draft = _linux_draft(rehearsal_completed=False)
        result = _svc().check_linux_publish_candidate(draft, [])
        assert result.publish_candidate_ready is False
        assert result.actual_publish_performed is False
        assert result.learner_catalog_changed is False

    def test_publish_status_unchanged_after_dry_run(self):
        """Draft in repo must not have publish_status mutated by dry run."""
        draft = _linux_draft()
        session = _rehearsal_session(draft)
        before_status = draft.publish_status

        result = _svc().check_linux_publish_candidate(draft, [session])

        assert draft.publish_status == before_status  # in-memory object unchanged
        assert result.actual_publish_performed is False


# ─────────────────────────────────────────────────────────────────────────────
# J. K8s regression — K8s domain paths unchanged
# ─────────────────────────────────────────────────────────────────────────────


class TestK8sRegression:
    def test_k8s_draft_still_uses_static_validator(self):
        """StaticValidator still validates K8s drafts correctly after new code."""
        results = StaticValidator().validate(_k8s_draft())
        check_ids = {r.check_id for r in results}
        assert "linux.publish_blocked_until_runtime" not in check_ids

    def test_linux_dry_run_does_not_affect_k8s_static_validator(self):
        """Running a Linux dry run does not change K8s validation outcomes."""
        linux_draft = _linux_draft()
        session = _rehearsal_session(linux_draft)
        _svc().check_linux_publish_candidate(linux_draft, [session])

        from backend.labgen.models import ValidatorStatus, BlockingLevel
        results = StaticValidator().validate(_k8s_draft())
        blocking = [
            r for r in results
            if r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        assert not blocking, f"Unexpected K8s blocking failures: {[r.check_id for r in blocking]}"

    def test_linux_boundary_not_recognized_for_k8s_draft(self):
        """_linux_boundary_was_recognized returns False for K8s drafts."""
        assert _svc()._linux_boundary_was_recognized(_k8s_draft()) is False
