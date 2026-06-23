"""
Tests for G-45 — Linux Learner Runtime Enablement Gate v0.1

Covers:
A. Feature flag / allowlist precheck
B. Learner session create (workspace, domain dispatch)
C. Step check (Linux verifier dispatch)
D. Complete (cleanup, residual=0, LAB_CLOSED)
E. Abort (cleanup path)
F. Negative checks (unsafe commands, path escape, non-allowlisted)
G. Catalog isolation (draft/internal not exposed)
H. K8s regression (K8s Lab 5 path unaffected)
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.lab_session_service import (
    LINUX_LEARNER_VM_SENTINEL,
    LabSessionService,
    PrecheckFailed,
    StubVMTracker,
)
from backend.labgen.linux_runtime_adapter import (
    LinuxRuntimeAdapter,
    LinuxSpikeDisabledError,
    LinuxSpikeStatus,
)
from backend.labgen.linux_verifier_client import LinuxVerifierService
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
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
from backend.labgen.image_resolver import ImageResolver
from backend.labgen.step_progression_service import StepProgressionService, StepAccessDenied


pytestmark = pytest.mark.static

_SANDBOX_ROOT = "/tmp/labgen-linux-sandboxes"


def _test_sandbox() -> str:
    """Return a unique subdirectory under the allowed sandbox root."""
    path = os.path.join(_SANDBOX_ROOT, f"learner-test-{uuid.uuid4().hex[:12]}")
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


LINUX_LAB_ID = "6c439064-test-linux-learner-enablement-0001"
K8S_LAB_ID = "cf019133-test-k8s-lab5-regression-000000001"
STUDENT = "learner-smoke-test"


def _explain() -> ExplainField:
    return ExplainField(concept="concept", observation="observation")


def _linux_step(step_id: str, order: int, commands: list, linux_verify: list) -> Step:
    return Step(
        step_id=step_id,
        order=order,
        why="why",
        do="do",
        observe="observe",
        explain=_explain(),
        commands=commands,
        linux_verify=linux_verify,
    )


def _linux_sandbox_policy() -> LinuxSandboxPolicy:
    return LinuxSandboxPolicy(
        allow_network=False,
        allow_root=False,
        workspace_root="/home/learner/workspace",
        max_session_seconds=1800,
    )


def _linux_cleanup() -> CleanupLinuxWorkspace:
    return CleanupLinuxWorkspace(
        workspace_root="/home/learner/workspace",
        cleanup_paths=["/home/learner/workspace"],
        kill_session_processes=True,
        revoke_credentials=False,
        close_terminal=False,
        taint_on_cleanup_failure=True,
    )


def _linux_draft(lab_id: str = LINUX_LAB_ID, published: bool = True) -> LabDraft:
    """Return a minimal published Linux draft with steps matching the smoke flow."""
    return LabDraft(
        lab_id=lab_id,
        source_article_id="art-linux-test-001",
        title="Linux Files and Permissions Basics",
        description="Learn basic Linux file operations.",
        estimated_duration_minutes=20,
        runtime_requirements=RuntimeRequirements(),
        publish_status=PublishStatus.PUBLISHED if published else PublishStatus.DRAFT,
        target_domain=LabDomainType.LINUX,
        rehearsal_completed=True,
        linux_sandbox_policy=_linux_sandbox_policy(),
        linux_cleanup=_linux_cleanup(),
        steps=[
            _linux_step("step_1", 1, ["mkdir -p demo"], [
                LinuxVerifyTemplate(
                    verify_id="v1",
                    type=LinuxVerifyType.LINUX_DIRECTORY_EXISTS,
                    target_path="demo",
                ),
            ]),
            _linux_step("step_2", 2, ["printf 'hello labgen\\n' > demo/message.txt"], [
                LinuxVerifyTemplate(
                    verify_id="v2",
                    type=LinuxVerifyType.LINUX_FILE_EXISTS,
                    target_path="demo/message.txt",
                ),
                LinuxVerifyTemplate(
                    verify_id="v3",
                    type=LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES,
                    target_path="demo/message.txt",
                    expected_content="hello labgen\n",
                ),
            ]),
            _linux_step("step_3", 3, ["chmod 600 demo/message.txt"], [
                LinuxVerifyTemplate(
                    verify_id="v4",
                    type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                    target_path="demo/message.txt",
                    expected_mode="600",
                ),
            ]),
        ],
    )


def _k8s_draft(lab_id: str = K8S_LAB_ID) -> LabDraft:
    """Minimal published K8s draft (Lab 5 regression target)."""
    return LabDraft(
        lab_id=lab_id,
        source_article_id="art-k8s-test-005",
        title="Kubernetes ConfigMap 实战",
        description="K8s lab 5",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        publish_status=PublishStatus.PUBLISHED,
        target_domain=LabDomainType.K8S,
        rehearsal_completed=True,
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        steps=[
            Step(
                step_id="step_1",
                order=1,
                why="why",
                do="do",
                observe="observe",
                explain=_explain(),
                commands=["kubectl apply -f configmap.yaml"],
                verify=[
                    VerifyTemplate(
                        verify_id="k8s_v1",
                        type=VerifyType.NAMESPACE_EXISTS,
                        name="configmap-check",
                        namespace="{{lab_namespace}}",
                    )
                ],
            ),
        ],
    )


class InMemoryDraftRepo:
    def __init__(self, drafts: dict[str, LabDraft]) -> None:
        self._drafts = drafts

    def get(self, lab_id: str) -> LabDraft | None:
        return self._drafts.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._drafts[draft.lab_id] = draft
        return draft

    def list_published(self) -> list[LabDraft]:
        return [d for d in self._drafts.values() if d.publish_status == PublishStatus.PUBLISHED]


class InMemorySessionRepo:
    def __init__(self) -> None:
        self._sessions: dict[str, LabSessionState] = {}

    def get(self, session_id: str) -> LabSessionState | None:
        return self._sessions.get(session_id)

    def create(self, session: LabSessionState) -> LabSessionState:
        self._sessions[session.session_id] = session
        return session

    def update(self, session: LabSessionState) -> LabSessionState:
        self._sessions[session.session_id] = session
        return session

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._sessions.values() if s.student_username == username]


def _make_linux_service(
    draft_map: dict[str, LabDraft] | None = None,
    allowed_lab_ids: frozenset | None = None,
    sandbox_root: str | None = None,
) -> tuple[LabSessionService, InMemorySessionRepo, LinuxRuntimeAdapter]:
    if draft_map is None:
        draft_map = {LINUX_LAB_ID: _linux_draft()}
    if allowed_lab_ids is None:
        allowed_lab_ids = frozenset({LINUX_LAB_ID})
    if sandbox_root is None:
        sandbox_root = _test_sandbox()

    session_repo = InMemorySessionRepo()
    draft_repo = InMemoryDraftRepo(draft_map)
    linux_adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sandbox_root)
    svc = LabSessionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        vm_tracker=StubVMTracker(),
        ns_lifecycle=StubNamespaceLifecycleAdapter(),
        image_resolver=ImageResolver(),
        linux_adapter=linux_adapter,
        linux_learner_enabled_lab_ids=allowed_lab_ids,
    )
    return svc, session_repo, linux_adapter


# ---------------------------------------------------------------------------
# A. Feature flag / allowlist precheck
# ---------------------------------------------------------------------------


class TestLinuxAllowlistPrecheck:
    def test_linux_lab_in_allowlist_precheck_passes(self) -> None:
        svc, _, _ = _make_linux_service()
        result = svc.run_precheck(LINUX_LAB_ID, "any-vm", STUDENT)
        assert result.passed
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value not in result.failures

    def test_linux_lab_not_in_allowlist_blocked(self) -> None:
        svc, _, _ = _make_linux_service(allowed_lab_ids=frozenset())
        result = svc.run_precheck(LINUX_LAB_ID, "any-vm", STUDENT)
        assert not result.passed
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value in result.failures

    def test_linux_lab_adapter_none_blocked(self) -> None:
        """Linux lab in allowlist but adapter=None → still blocked."""
        session_repo = InMemorySessionRepo()
        draft_repo = InMemoryDraftRepo({LINUX_LAB_ID: _linux_draft()})
        svc = LabSessionService(
            session_repo=session_repo,
            draft_repo=draft_repo,
            vm_tracker=StubVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=ImageResolver(),
            linux_adapter=None,
            linux_learner_enabled_lab_ids=frozenset({LINUX_LAB_ID}),
        )
        result = svc.run_precheck(LINUX_LAB_ID, "any-vm", STUDENT)
        assert not result.passed
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value in result.failures

    def test_linux_lab_not_published_blocked(self) -> None:
        svc, _, _ = _make_linux_service(
            draft_map={LINUX_LAB_ID: _linux_draft(published=False)}
        )
        result = svc.run_precheck(LINUX_LAB_ID, "any-vm", STUDENT)
        assert not result.passed
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value in result.failures

    def test_vm_tracker_not_called_for_allowlisted_linux(self) -> None:
        """Allowlisted Linux lab skips VM tracker — vm_exists is never called."""
        svc, _, _ = _make_linux_service()
        mock_tracker = MagicMock()
        mock_tracker.vm_exists.return_value = False
        mock_tracker.is_vm_tainted.return_value = False
        svc._vm_tracker = mock_tracker
        result = svc.run_precheck(LINUX_LAB_ID, "any-vm", STUDENT)
        assert result.passed
        mock_tracker.vm_exists.assert_not_called()

    def test_non_linux_lab_unaffected_by_linux_allowlist(self) -> None:
        """K8s lab precheck unchanged — Linux allowlist does not break K8s path."""
        svc, _, _ = _make_linux_service(
            draft_map={K8S_LAB_ID: _k8s_draft(), LINUX_LAB_ID: _linux_draft()}
        )
        result = svc.run_precheck(K8S_LAB_ID, "500", STUDENT)
        assert result.passed

    def test_second_linux_lab_not_in_allowlist_blocked(self) -> None:
        """A second Linux lab not in allowlist is still blocked."""
        other_linux_id = "9999aaaa-linux-not-allowed-000000000000"
        other_draft = LabDraft(
            lab_id=other_linux_id,
            source_article_id="art-other",
            title="Other Linux Lab",
            description="Not allowed",
            estimated_duration_minutes=10,
            runtime_requirements=RuntimeRequirements(),
            publish_status=PublishStatus.PUBLISHED,
            target_domain=LabDomainType.LINUX,
            linux_sandbox_policy=_linux_sandbox_policy(),
            linux_cleanup=_linux_cleanup(),
            steps=[],
        )
        svc, _, _ = _make_linux_service(
            draft_map={LINUX_LAB_ID: _linux_draft(), other_linux_id: other_draft}
        )
        result = svc.run_precheck(other_linux_id, "any-vm", STUDENT)
        assert not result.passed
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value in result.failures


# ---------------------------------------------------------------------------
# B. Learner session create
# ---------------------------------------------------------------------------


class TestLinuxLearnerSessionCreate:
    def test_create_session_succeeds_for_allowlisted_linux_lab(self) -> None:
        svc, session_repo, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        assert session.session_type == SessionType.LEARNER
        assert session.vm_id == LINUX_LEARNER_VM_SENTINEL
        assert session.student_username == STUDENT
        ws = linux_adapter.workspace_manager.get_session(session.session_id)
        assert ws is not None

    def test_create_session_raises_precheckfailed_if_not_allowlisted(self) -> None:
        svc, _, _ = _make_linux_service(allowed_lab_ids=frozenset())
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_session(LINUX_LAB_ID, "any-vm", STUDENT)
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value in exc_info.value.failures

    def test_create_session_no_k8s_namespace_created(self) -> None:
        """Linux session must NOT create a K8s namespace."""
        svc, _, _ = _make_linux_service()
        svc._ns_lifecycle.create_namespace = MagicMock(return_value=True)
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        svc._ns_lifecycle.create_namespace.assert_not_called()

    def test_session_type_is_learner_not_rehearsal(self) -> None:
        svc, _, _ = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert session.session_type == SessionType.LEARNER

    def test_vm_id_is_linux_sentinel(self) -> None:
        svc, _, _ = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert session.vm_id == LINUX_LEARNER_VM_SENTINEL

    def test_workspace_adapter_disabled_gives_lab_start_failed(self) -> None:
        """If LinuxRuntimeAdapter is disabled (create_session raises) → LAB_START_FAILED."""
        svc, _, linux_adapter = _make_linux_service()
        linux_adapter._enabled = False
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert session.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert session.failure_reason == FailureReason.LINUX_LEARNER_WORKSPACE_CREATE_FAILED.value

    def test_namespace_field_is_none_for_linux_session(self) -> None:
        """Linux sessions have no K8s namespace — namespace field should be None."""
        svc, _, _ = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert session.namespace is None


# ---------------------------------------------------------------------------
# C. Step check (Linux verifier dispatch)
# ---------------------------------------------------------------------------


class TestLinuxLearnerStepCheck:
    def _setup(self) -> tuple[LabSessionService, InMemorySessionRepo, LinuxRuntimeAdapter, LabSessionState, StepProgressionService]:
        svc, session_repo, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        draft_repo = InMemoryDraftRepo({LINUX_LAB_ID: _linux_draft()})
        step_svc = StepProgressionService(
            session_repo=session_repo,
            draft_repo=draft_repo,
            verifier_svc=MagicMock(),
            linux_verifier_svc=LinuxVerifierService(linux_adapter.workspace_manager),
        )
        return svc, session_repo, linux_adapter, session, step_svc

    def test_step1_directory_exists_passes_after_mkdir(self) -> None:
        _, _, linux_adapter, session, step_svc = self._setup()
        linux_adapter.make_directory(session.session_id, "demo")
        result = step_svc.check_step(session.session_id, "step_1", STUDENT)
        assert result.all_passed
        assert result.advanced

    def test_step1_directory_exists_fails_before_mkdir(self) -> None:
        _, _, _, session, step_svc = self._setup()
        result = step_svc.check_step(session.session_id, "step_1", STUDENT)
        assert not result.all_passed
        assert not result.advanced

    def test_step2_file_content_matches(self) -> None:
        _, session_repo, linux_adapter, session, step_svc = self._setup()
        linux_adapter.make_directory(session.session_id, "demo")
        step_svc.check_step(session.session_id, "step_1", STUDENT)
        linux_adapter.write_file(session.session_id, "demo/message.txt", "hello labgen\n")
        result = step_svc.check_step(session.session_id, "step_2", STUDENT)
        assert result.all_passed
        assert result.advanced

    def test_step2_wrong_content_fails(self) -> None:
        _, session_repo, linux_adapter, session, step_svc = self._setup()
        linux_adapter.make_directory(session.session_id, "demo")
        step_svc.check_step(session.session_id, "step_1", STUDENT)
        linux_adapter.write_file(session.session_id, "demo/message.txt", "wrong content\n")
        result = step_svc.check_step(session.session_id, "step_2", STUDENT)
        assert not result.all_passed

    def test_step3_file_mode_matches(self) -> None:
        _, session_repo, linux_adapter, session, step_svc = self._setup()
        linux_adapter.make_directory(session.session_id, "demo")
        step_svc.check_step(session.session_id, "step_1", STUDENT)
        linux_adapter.write_file(session.session_id, "demo/message.txt", "hello labgen\n")
        step_svc.check_step(session.session_id, "step_2", STUDENT)
        linux_adapter.chmod_file(session.session_id, "demo/message.txt", 0o600)
        result = step_svc.check_step(session.session_id, "step_3", STUDENT)
        assert result.all_passed
        assert result.ready_to_complete

    def test_step3_wrong_mode_fails(self) -> None:
        _, session_repo, linux_adapter, session, step_svc = self._setup()
        linux_adapter.make_directory(session.session_id, "demo")
        step_svc.check_step(session.session_id, "step_1", STUDENT)
        linux_adapter.write_file(session.session_id, "demo/message.txt", "hello labgen\n")
        step_svc.check_step(session.session_id, "step_2", STUDENT)
        linux_adapter.chmod_file(session.session_id, "demo/message.txt", 0o644)
        result = step_svc.check_step(session.session_id, "step_3", STUDENT)
        assert not result.all_passed

    def test_step_check_access_denied_for_other_user(self) -> None:
        _, _, linux_adapter, session, step_svc = self._setup()
        with pytest.raises(StepAccessDenied):
            step_svc.check_step(session.session_id, "step_1", "other-user")

    def test_all_steps_to_ready_to_complete(self) -> None:
        _, session_repo, linux_adapter, session, step_svc = self._setup()
        linux_adapter.make_directory(session.session_id, "demo")
        step_svc.check_step(session.session_id, "step_1", STUDENT)
        linux_adapter.write_file(session.session_id, "demo/message.txt", "hello labgen\n")
        step_svc.check_step(session.session_id, "step_2", STUDENT)
        linux_adapter.chmod_file(session.session_id, "demo/message.txt", 0o600)
        result = step_svc.check_step(session.session_id, "step_3", STUDENT)
        assert result.ready_to_complete


# ---------------------------------------------------------------------------
# D. Complete (cleanup, LAB_CLOSED)
# ---------------------------------------------------------------------------


class TestLinuxLearnerComplete:
    def _run_full_smoke(self) -> tuple[LabSessionService, InMemorySessionRepo, LinuxRuntimeAdapter, LabSessionState]:
        svc, session_repo, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        draft_repo = InMemoryDraftRepo({LINUX_LAB_ID: _linux_draft()})
        step_svc = StepProgressionService(
            session_repo=session_repo,
            draft_repo=draft_repo,
            verifier_svc=MagicMock(),
            linux_verifier_svc=LinuxVerifierService(linux_adapter.workspace_manager),
        )
        linux_adapter.make_directory(session.session_id, "demo")
        step_svc.check_step(session.session_id, "step_1", STUDENT)
        linux_adapter.write_file(session.session_id, "demo/message.txt", "hello labgen\n")
        step_svc.check_step(session.session_id, "step_2", STUDENT)
        linux_adapter.chmod_file(session.session_id, "demo/message.txt", 0o600)
        step_svc.check_step(session.session_id, "step_3", STUDENT)
        session = session_repo.get(session.session_id)
        assert session.ready_to_complete
        return svc, session_repo, linux_adapter, session

    def test_complete_session_gives_lab_closed(self) -> None:
        svc, _, _, session = self._run_full_smoke()
        closed = svc.complete_session(session.session_id)
        assert closed.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_complete_session_cleanup_verified_true(self) -> None:
        svc, _, _, session = self._run_full_smoke()
        closed = svc.complete_session(session.session_id)
        assert closed.cleanup_verified is True

    def test_complete_session_workspace_closed(self) -> None:
        """After complete, adapter session is CLOSED — no residual workspace."""
        svc, _, linux_adapter, session = self._run_full_smoke()
        session_id = session.session_id
        svc.complete_session(session_id)
        spike_state = linux_adapter._sessions.get(session_id)
        if spike_state is not None:
            assert spike_state.status == LinuxSpikeStatus.CLOSED

    def test_complete_before_ready_raises_lab_not_ready(self) -> None:
        from backend.labgen.lab_session_service import LabNotReadyToComplete
        svc, _, _, = _make_linux_service()[:3]
        svc2, _, _ = _make_linux_service()
        session = svc2.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        with pytest.raises(LabNotReadyToComplete):
            svc2.complete_session(session.session_id)

    def test_no_k8s_namespace_deleted_on_linux_complete(self) -> None:
        svc, _, _, session = self._run_full_smoke()
        svc._ns_lifecycle.delete_namespace = MagicMock(return_value=True)
        svc.complete_session(session.session_id)
        svc._ns_lifecycle.delete_namespace.assert_not_called()

    def test_sentinel_vm_not_tainted_on_success(self) -> None:
        svc, _, _, session = self._run_full_smoke()
        svc.complete_session(session.session_id)
        assert not svc._vm_tracker.is_vm_tainted(LINUX_LEARNER_VM_SENTINEL)


# ---------------------------------------------------------------------------
# E. Abort
# ---------------------------------------------------------------------------


class TestLinuxLearnerAbort:
    def test_abort_session_gives_lab_closed(self) -> None:
        svc, _, _ = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        closed = svc.abort_session(session.session_id)
        assert closed.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert closed.cleanup_verified is True

    def test_abort_no_k8s_namespace_deleted(self) -> None:
        svc, _, _ = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        svc._ns_lifecycle.delete_namespace = MagicMock(return_value=True)
        svc.abort_session(session.session_id)
        svc._ns_lifecycle.delete_namespace.assert_not_called()

    def test_abort_workspace_closed(self) -> None:
        svc, _, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        session_id = session.session_id
        svc.abort_session(session_id)
        spike_state = linux_adapter._sessions.get(session_id)
        if spike_state is not None:
            assert spike_state.status == LinuxSpikeStatus.CLOSED


# ---------------------------------------------------------------------------
# F. Negative checks
# ---------------------------------------------------------------------------


class TestLinuxNegativeChecks:
    def test_unsafe_sudo_command_rejected(self) -> None:
        svc, _, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        result = linux_adapter.execute_command(session.session_id, ["sudo", "id"])
        assert result.policy_rejected

    def test_unsafe_su_command_rejected(self) -> None:
        svc, _, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        result = linux_adapter.execute_command(session.session_id, ["su", "-"])
        assert result.policy_rejected

    def test_path_escape_rejected_by_workspace_manager(self) -> None:
        from backend.labgen.linux_workspace import WorkspacePathEscapeError
        svc, _, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        with pytest.raises(WorkspacePathEscapeError):
            linux_adapter.write_file(session.session_id, "../escape_attempt.txt", "evil")

    def test_etc_write_rejected(self) -> None:
        from backend.labgen.linux_workspace import WorkspacePathEscapeError
        svc, _, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        with pytest.raises(WorkspacePathEscapeError):
            linux_adapter.write_file(session.session_id, "/etc/shadow", "hack")

    def test_non_allowlisted_linux_lab_start_blocked(self) -> None:
        other_id = "bbbbbbbb-linux-not-in-allowlist-00000000"
        other_draft = LabDraft(
            lab_id=other_id,
            source_article_id="art-not-allowed",
            title="Not Allowed Linux Lab",
            description=".",
            estimated_duration_minutes=10,
            runtime_requirements=RuntimeRequirements(),
            publish_status=PublishStatus.PUBLISHED,
            target_domain=LabDomainType.LINUX,
            linux_sandbox_policy=_linux_sandbox_policy(),
            linux_cleanup=_linux_cleanup(),
            steps=[],
        )
        svc, _, _ = _make_linux_service(
            draft_map={LINUX_LAB_ID: _linux_draft(), other_id: other_draft},
        )
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_session(other_id, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value in exc_info.value.failures

    def test_draft_lab_not_startable(self) -> None:
        svc, _, _ = _make_linux_service(
            draft_map={LINUX_LAB_ID: _linux_draft(published=False)}
        )
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value in exc_info.value.failures

    def test_allow_root_policy_rejected(self) -> None:
        """LinuxSandboxPolicy rejects allow_root=True at model validation time."""
        with pytest.raises(Exception, match="allow_root must always be False"):
            LinuxSandboxPolicy(allow_root=True, allow_network=False, workspace_root="/tmp/x")

    def test_allow_network_policy_rejected(self) -> None:
        """LinuxSandboxPolicy rejects allow_network=True at model validation time."""
        with pytest.raises(Exception, match="allow_network must always be False"):
            LinuxSandboxPolicy(allow_root=False, allow_network=True, workspace_root="/tmp/x")

    def test_disabled_adapter_raises_on_create(self) -> None:
        """Disabled LinuxRuntimeAdapter raises LinuxSpikeDisabledError."""
        adapter = LinuxRuntimeAdapter(enabled=False, sandbox_root=_test_sandbox())
        with pytest.raises(LinuxSpikeDisabledError):
            adapter.create_session("any-session")

    def test_sentinel_vm_never_routes_to_k8s_cleanup_when_adapter_gone(self) -> None:
        """If adapter becomes None after session creation, sentinel session must fail
        with LAB_CLEANUP_FAILED — never fall through to K8s namespace cleanup path."""
        svc, session_repo, _ = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        # Simulate adapter gone (e.g. env var toggled, process config change)
        svc._linux_adapter = None
        svc._ns_lifecycle.delete_namespace = MagicMock(return_value=True)
        # Abort should hit the fail-closed sentinel path, not K8s namespace deletion
        closed = svc.abort_session(session.session_id)
        assert closed.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED
        assert closed.failure_reason == FailureReason.LINUX_LEARNER_CLEANUP_FAILED.value
        assert closed.cleanup_verified is False
        # K8s namespace cleanup must NOT have been called
        svc._ns_lifecycle.delete_namespace.assert_not_called()


# ---------------------------------------------------------------------------
# G. Catalog isolation
# ---------------------------------------------------------------------------


class TestCatalogIsolation:
    def _make_k8s_lab_draft(self, lab_id: str, title: str) -> LabDraft:
        return LabDraft(
            lab_id=lab_id,
            source_article_id=f"art-{lab_id}",
            title=title,
            description=".",
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            publish_status=PublishStatus.PUBLISHED,
            target_domain=LabDomainType.K8S,
            steps=[],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )

    def test_catalog_shows_published_labs_including_linux(self) -> None:
        draft_map = {
            "k8s-1": self._make_k8s_lab_draft("k8s-1", "K8s 1"),
            "k8s-2": self._make_k8s_lab_draft("k8s-2", "K8s 2"),
            LINUX_LAB_ID: _linux_draft(),
            "draft-linux-hidden": LabDraft(
                lab_id="draft-linux-hidden",
                source_article_id="art-hidden",
                title="Hidden Draft",
                description=".",
                estimated_duration_minutes=10,
                runtime_requirements=RuntimeRequirements(),
                publish_status=PublishStatus.DRAFT,
                target_domain=LabDomainType.LINUX,
                steps=[],
            ),
        }
        repo = InMemoryDraftRepo(draft_map)
        published = repo.list_published()
        ids = {d.lab_id for d in published}
        assert LINUX_LAB_ID in ids
        assert "draft-linux-hidden" not in ids
        assert "k8s-1" in ids

    def test_draft_linux_lab_not_startable_even_if_in_allowlist(self) -> None:
        """Draft Linux lab always blocked even if in allowlist — publish_status check."""
        draft_id = "draft-hidden-linux-lab"
        svc, _, _ = _make_linux_service(
            draft_map={draft_id: LabDraft(
                lab_id=draft_id,
                source_article_id="art-hidden-draft",
                title="Hidden Draft",
                description=".",
                estimated_duration_minutes=10,
                runtime_requirements=RuntimeRequirements(),
                publish_status=PublishStatus.DRAFT,
                target_domain=LabDomainType.LINUX,
                linux_sandbox_policy=_linux_sandbox_policy(),
                linux_cleanup=_linux_cleanup(),
                steps=[],
            )},
            allowed_lab_ids=frozenset({draft_id}),
        )
        result = svc.run_precheck(draft_id, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert not result.passed
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value in result.failures

    def test_source_article_id_does_not_block_learner_precheck(self) -> None:
        """Linux learner precheck does not require rehearsal_completed (learner path)."""
        svc, _, _ = _make_linux_service()
        # The _linux_draft() has rehearsal_completed=True which is fine for published labs.
        # Key check: no special source_article_id or article-pipeline check for learner path.
        result = svc.run_precheck(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert result.passed


# ---------------------------------------------------------------------------
# H. K8s regression (Lab 5 path unaffected)
# ---------------------------------------------------------------------------


class TestK8sRegression:
    def _make_k8s_service(self) -> tuple[LabSessionService, InMemorySessionRepo]:
        session_repo = InMemorySessionRepo()
        draft_repo = InMemoryDraftRepo({
            K8S_LAB_ID: _k8s_draft(),
            LINUX_LAB_ID: _linux_draft(),
        })
        linux_adapter = LinuxRuntimeAdapter(
            enabled=True, sandbox_root=_test_sandbox()
        )
        svc = LabSessionService(
            session_repo=session_repo,
            draft_repo=draft_repo,
            vm_tracker=StubVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=ImageResolver(),
            linux_adapter=linux_adapter,
            linux_learner_enabled_lab_ids=frozenset({LINUX_LAB_ID}),
        )
        return svc, session_repo

    def test_k8s_precheck_unaffected(self) -> None:
        svc, _ = self._make_k8s_service()
        result = svc.run_precheck(K8S_LAB_ID, "500", STUDENT)
        assert result.passed

    def test_k8s_session_create_uses_k8s_path(self) -> None:
        """K8s lab session create goes through K8s namespace path (stub)."""
        svc, session_repo = self._make_k8s_service()
        session = svc.create_session(K8S_LAB_ID, "500", STUDENT)
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        assert session.vm_id == "500"
        assert session.namespace is not None

    def test_linux_adapter_not_called_for_k8s_session(self) -> None:
        """K8s lab cleanup goes through ns_lifecycle path, not linux_adapter."""
        svc, session_repo = self._make_k8s_service()
        session = svc.create_session(K8S_LAB_ID, "500", STUDENT)
        original_close = svc._linux_adapter.close_session
        svc._linux_adapter.close_session = MagicMock(side_effect=AssertionError("linux cleanup called for K8s session"))
        session.ready_to_complete = True
        session_repo.update(session)
        closed = svc.complete_session(session.session_id)
        assert closed.lab_session_status == LabSessionStatus.LAB_CLOSED
        svc._linux_adapter.close_session.assert_not_called()

    def test_k8s_and_linux_labs_both_visible_in_catalog(self) -> None:
        draft_map = {K8S_LAB_ID: _k8s_draft(), LINUX_LAB_ID: _linux_draft()}
        repo = InMemoryDraftRepo(draft_map)
        published = repo.list_published()
        ids = {d.lab_id for d in published}
        assert K8S_LAB_ID in ids
        assert LINUX_LAB_ID in ids


# ---------------------------------------------------------------------------
# I. Full learner smoke (end-to-end in-process)
# ---------------------------------------------------------------------------


class TestLinuxLearnerSmokeE2E:
    def test_full_smoke_start_check_complete(self) -> None:
        """Full learner smoke flow: Start → step check × 3 → Complete → LAB_CLOSED."""
        svc, session_repo, linux_adapter = _make_linux_service()
        draft_repo = InMemoryDraftRepo({LINUX_LAB_ID: _linux_draft()})
        step_svc = StepProgressionService(
            session_repo=session_repo,
            draft_repo=draft_repo,
            verifier_svc=MagicMock(),
            linux_verifier_svc=LinuxVerifierService(linux_adapter.workspace_manager),
        )

        # 1. Start
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        assert session.session_type == SessionType.LEARNER
        session_id = session.session_id

        # 2. Step 1: mkdir -p demo
        linux_adapter.make_directory(session_id, "demo")
        r1 = step_svc.check_step(session_id, "step_1", STUDENT)
        assert r1.all_passed, f"step_1 failed: {[v.error_code for v in r1.verify_results]}"
        assert r1.advanced

        # 3. Step 2: printf 'hello labgen\n' > demo/message.txt
        linux_adapter.write_file(session_id, "demo/message.txt", "hello labgen\n")
        r2 = step_svc.check_step(session_id, "step_2", STUDENT)
        assert r2.all_passed, f"step_2 failed: {[v.error_code for v in r2.verify_results]}"
        assert r2.advanced

        # 4. Step 3: chmod 600 demo/message.txt
        linux_adapter.chmod_file(session_id, "demo/message.txt", 0o600)
        r3 = step_svc.check_step(session_id, "step_3", STUDENT)
        assert r3.all_passed, f"step_3 failed: {[v.error_code for v in r3.verify_results]}"
        assert r3.ready_to_complete

        # 5. Complete
        session = session_repo.get(session_id)
        assert session.ready_to_complete
        closed = svc.complete_session(session_id)

        # 6. Verify result
        assert closed.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert closed.cleanup_verified is True
        assert closed.session_type == SessionType.LEARNER
        assert closed.vm_id == LINUX_LEARNER_VM_SENTINEL

    def test_full_smoke_abort_path(self) -> None:
        svc, _, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        linux_adapter.make_directory(session.session_id, "partial-work")
        closed = svc.abort_session(session.session_id)
        assert closed.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert closed.cleanup_verified is True

    def test_no_llm_calls_during_smoke(self) -> None:
        """No LLM calls during the entire learner smoke (gate: live LLM禁止)."""
        # If any LLM provider is imported and called, this test would error at the mock level.
        # We verify no LLM module is imported during session lifecycle.
        import sys
        llm_modules_before = {k for k in sys.modules if "openai" in k or "anthropic" in k or "llm" in k.lower()}
        svc, _, linux_adapter = _make_linux_service()
        session = svc.create_session(LINUX_LAB_ID, LINUX_LEARNER_VM_SENTINEL, STUDENT)
        svc.abort_session(session.session_id)
        llm_modules_after = {k for k in sys.modules if "openai" in k or "anthropic" in k or "llm" in k.lower()}
        new_llm_imports = llm_modules_after - llm_modules_before
        assert not new_llm_imports, f"LLM modules imported during smoke: {new_llm_imports}"


# ---------------------------------------------------------------------------
# J. Config: LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS parsing
# ---------------------------------------------------------------------------


class TestConfigParsing:
    def test_empty_env_gives_empty_frozenset(self, monkeypatch) -> None:
        monkeypatch.delenv("LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", raising=False)
        import importlib
        import backend.config as cfg_mod
        importlib.reload(cfg_mod)
        assert cfg_mod.LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS == frozenset()

    def test_single_lab_id_parsed(self, monkeypatch) -> None:
        monkeypatch.setenv("LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", LINUX_LAB_ID)
        import importlib
        import backend.config as cfg_mod
        importlib.reload(cfg_mod)
        assert LINUX_LAB_ID in cfg_mod.LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS

    def test_multiple_lab_ids_parsed(self, monkeypatch) -> None:
        ids = f"{LINUX_LAB_ID},other-id-1234"
        monkeypatch.setenv("LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", ids)
        import importlib
        import backend.config as cfg_mod
        importlib.reload(cfg_mod)
        assert LINUX_LAB_ID in cfg_mod.LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS
        assert "other-id-1234" in cfg_mod.LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS

    def test_whitespace_trimmed(self, monkeypatch) -> None:
        monkeypatch.setenv("LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", f"  {LINUX_LAB_ID}  , another ")
        import importlib
        import backend.config as cfg_mod
        importlib.reload(cfg_mod)
        assert LINUX_LAB_ID in cfg_mod.LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS
        assert "another" in cfg_mod.LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS


# ---------------------------------------------------------------------------
# K. Failure reason stability
# ---------------------------------------------------------------------------


class TestFailureReasonStability:
    def test_linux_learner_cleanup_failed_value(self) -> None:
        assert FailureReason.LINUX_LEARNER_CLEANUP_FAILED.value == "linux_learner.cleanup_failed"

    def test_linux_learner_workspace_create_failed_value(self) -> None:
        assert FailureReason.LINUX_LEARNER_WORKSPACE_CREATE_FAILED.value == "linux_learner.workspace_create_failed"

    def test_precheck_linux_learner_not_supported_unchanged(self) -> None:
        assert FailureReason.PRECHECK_LINUX_LEARNER_NOT_SUPPORTED.value == "precheck.linux_learner_not_yet_available"
