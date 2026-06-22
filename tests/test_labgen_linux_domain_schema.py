"""
Linux Domain Contract Schema Extension Tests.

Coverage:
  A. LinuxVerifyType tests
  B. LinuxSandboxPolicy tests
  C. CleanupLinuxWorkspace tests
  D. StaticValidator Linux domain tests
  E. ArticleDraftValidator + StubFeasibilityClassifier Linux tests (H-01, H-02)
  F. K8s regression tests (existing behavior must not change)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

pytestmark = pytest.mark.static

from pydantic import ValidationError

from backend.labgen.models import (
    BlockingLevel,
    CleanupLinuxWorkspace,
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDomainType,
    LabDraft,
    LinuxSandboxPolicy,
    LinuxVerifyTemplate,
    LinuxVerifyType,
    PollutionLevel,
    RuntimeRequirements,
    Step,
    ValidatorStatus,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.static_validator import StaticValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _explain(**kw) -> ExplainField:
    d = dict(concept="file permissions concept", observation="mode changed as expected")
    d.update(kw)
    return ExplainField(**d)


def _linux_step(
    step_id: str = "s1",
    commands: list[str] | None = None,
    linux_verify: list[LinuxVerifyTemplate] | None = None,
    verify: list[VerifyTemplate] | None = None,
) -> Step:
    return Step(
        step_id=step_id,
        order=1,
        why="Learn file permissions",
        do="Create a file and chmod it",
        observe="Permission bits change as expected",
        commands=commands or ["touch workspace/hello.txt", "chmod 644 workspace/hello.txt"],
        linux_verify=linux_verify or [],
        verify=verify or [],
        explain=_explain(),
    )


def _linux_verify(
    verify_id: str = "v1",
    type: LinuxVerifyType = LinuxVerifyType.LINUX_FILE_EXISTS,
    target_path: str = "workspace/hello.txt",
    **kw,
) -> LinuxVerifyTemplate:
    return LinuxVerifyTemplate(
        verify_id=verify_id,
        type=type,
        target_path=target_path,
        **kw,
    )


def _default_sandbox() -> LinuxSandboxPolicy:
    return LinuxSandboxPolicy(
        workspace_root="/home/learner/workspace",
        working_directory="/home/learner/workspace",
    )


def _default_linux_cleanup() -> CleanupLinuxWorkspace:
    return CleanupLinuxWorkspace(
        workspace_root="/home/learner/workspace",
        cleanup_paths=["/home/learner/workspace"],
    )


_UNSET = object()


def _linux_lab_draft(
    steps: list[Step] | None = None,
    sandbox: object = _UNSET,
    cleanup: object = _UNSET,
    title: str = "Linux Files and Permissions Basics",
    description: str = "Practice Linux file permissions in a safe workspace.",
) -> LabDraft:
    resolved_sandbox = _default_sandbox() if sandbox is _UNSET else sandbox
    resolved_cleanup = _default_linux_cleanup() if cleanup is _UNSET else cleanup
    return LabDraft(
        source_article_id="article-linux-001",
        title=title,
        description=description,
        estimated_duration_minutes=20,
        target_domain=LabDomainType.LINUX,
        runtime_requirements=RuntimeRequirements(),
        steps=steps or [_linux_step(linux_verify=[_linux_verify()])],
        linux_sandbox_policy=resolved_sandbox,
        linux_cleanup=resolved_cleanup,
    )


def _k8s_step(step_id: str = "k8s-s1") -> Step:
    from backend.labgen.models import VerifyTemplate, VerifyType
    return Step(
        step_id=step_id,
        order=1,
        why="Deploy nginx",
        do="Apply the deployment",
        observe="Pod is running",
        commands=["kubectl apply -f deployment.yaml"],
        verify=[
            VerifyTemplate(
                verify_id="v1",
                type=VerifyType.POD_RUNNING,
                name="nginx",
                namespace="{{lab_namespace}}",
            )
        ],
        explain=_explain(
            concept="K8s deployment concept",
            observation="pod enters Running state",
        ),
    )


def _k8s_cleanup() -> CleanupSpec:
    return CleanupSpec(namespace_cleanup=CleanupNamespace())


def _k8s_lab_draft(steps: list[Step] | None = None) -> LabDraft:
    return LabDraft(
        source_article_id="article-k8s-001",
        title="Kubernetes ConfigMap Basics",
        description="Learn to create and use K8s ConfigMaps.",
        estimated_duration_minutes=30,
        target_domain=LabDomainType.K8S,
        runtime_requirements=RuntimeRequirements(),
        steps=steps or [_k8s_step()],
        cleanup=_k8s_cleanup(),
    )


# ---------------------------------------------------------------------------
# A. LinuxVerifyType tests
# ---------------------------------------------------------------------------


class TestLinuxVerifyType:
    def test_accepts_linux_file_exists(self):
        lv = _linux_verify(type=LinuxVerifyType.LINUX_FILE_EXISTS)
        assert lv.type == LinuxVerifyType.LINUX_FILE_EXISTS

    def test_accepts_linux_directory_exists(self):
        lv = _linux_verify(type=LinuxVerifyType.LINUX_DIRECTORY_EXISTS, target_path="workspace/mydir")
        assert lv.type == LinuxVerifyType.LINUX_DIRECTORY_EXISTS

    def test_accepts_linux_file_content_matches(self):
        lv = _linux_verify(
            type=LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES,
            expected_content="hello world",
        )
        assert lv.type == LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES
        assert lv.expected_content == "hello world"

    def test_accepts_linux_file_mode_matches(self):
        lv = _linux_verify(
            type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
            expected_mode="644",
        )
        assert lv.type == LinuxVerifyType.LINUX_FILE_MODE_MATCHES
        assert lv.expected_mode == "644"

    def test_accepts_linux_no_residual_files(self):
        lv = _linux_verify(type=LinuxVerifyType.LINUX_NO_RESIDUAL_FILES)
        assert lv.type == LinuxVerifyType.LINUX_NO_RESIDUAL_FILES

    def test_workspace_relative_only_invariant_enforced(self):
        with pytest.raises(ValidationError, match="workspace_relative_only"):
            LinuxVerifyTemplate(
                verify_id="v1",
                type=LinuxVerifyType.LINUX_FILE_EXISTS,
                target_path="workspace/file.txt",
                workspace_relative_only=False,
            )

    def test_rejects_linux_verifier_in_k8s_domain(self):
        """K8s domain lab must not contain linux_verify entries."""
        draft = _k8s_lab_draft()
        draft.steps[0].linux_verify = [_linux_verify()]  # inject Linux verifier
        validator = StaticValidator()
        results = validator.validate(draft)
        check_ids = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "k8s.no_linux_verifiers" in check_ids

    def test_rejects_k8s_verifier_in_linux_domain(self):
        """Linux domain lab must not contain K8s verify entries."""
        step = _linux_step(
            linux_verify=[_linux_verify()],
            verify=[  # inject K8s verifier
                VerifyTemplate(
                    verify_id="k8s-v1",
                    type=VerifyType.POD_RUNNING,
                    name="nginx",
                    namespace="{{lab_namespace}}",
                )
            ],
        )
        draft = _linux_lab_draft(steps=[step])
        validator = StaticValidator()
        results = validator.validate(draft)
        check_ids = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.no_k8s_verifiers" in check_ids

    def test_verify_id_and_description_preserved(self):
        lv = _linux_verify(verify_id="verify-chmod-001", description="Check file mode is 644")
        assert lv.verify_id == "verify-chmod-001"
        assert lv.description == "Check file mode is 644"


# ---------------------------------------------------------------------------
# B. LinuxSandboxPolicy tests
# ---------------------------------------------------------------------------


class TestLinuxSandboxPolicy:
    def test_default_deny_network(self):
        policy = LinuxSandboxPolicy(workspace_root="/home/learner/workspace")
        assert policy.allow_network is False

    def test_default_deny_root(self):
        policy = LinuxSandboxPolicy(workspace_root="/home/learner/workspace")
        assert policy.allow_root is False

    def test_default_denied_commands_present(self):
        policy = LinuxSandboxPolicy(workspace_root="/home/learner/workspace")
        assert "sudo" in policy.denied_commands
        assert "su" in policy.denied_commands
        assert "systemctl" in policy.denied_commands

    def test_accepts_safe_workspace(self):
        policy = LinuxSandboxPolicy(workspace_root="/home/learner/workspace")
        assert policy.workspace_root == "/home/learner/workspace"
        assert policy.learner_user == "learner"

    def test_rejects_etc_workspace_via_validator(self):
        """workspace_root=/etc must fail StaticValidator."""
        policy = LinuxSandboxPolicy(workspace_root="/etc/lab-workspace")
        draft = _linux_lab_draft(sandbox=policy)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.sandbox_safe" in failed

    def test_rejects_root_workspace_via_validator(self):
        """workspace_root=/root must fail StaticValidator."""
        policy = LinuxSandboxPolicy(workspace_root="/root/workspace")
        draft = _linux_lab_draft(sandbox=policy)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.sandbox_safe" in failed

    def test_rejects_path_traversal_in_workspace_root(self):
        """workspace_root with .. must fail StaticValidator."""
        policy = LinuxSandboxPolicy(workspace_root="/home/learner/../etc/workspace")
        draft = _linux_lab_draft(sandbox=policy)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.sandbox_safe" in failed

    def test_rejects_allow_root_via_model_validator(self):
        """allow_root=True is rejected at model construction (Pydantic field_validator)."""
        with pytest.raises(ValidationError, match="allow_root"):
            LinuxSandboxPolicy(workspace_root="/home/learner/workspace", allow_root=True)

    def test_rejects_allow_network_via_model_validator(self):
        """allow_network=True is rejected at model construction (Pydantic field_validator)."""
        with pytest.raises(ValidationError, match="allow_network"):
            LinuxSandboxPolicy(workspace_root="/home/learner/workspace", allow_network=True)

    def test_base_image_field_present(self):
        policy = LinuxSandboxPolicy(workspace_root="/home/learner/workspace")
        assert policy.base_image == "ubuntu:22.04"

    def test_custom_base_image_accepted(self):
        policy = LinuxSandboxPolicy(
            workspace_root="/home/learner/workspace",
            base_image="ubuntu:20.04",
        )
        assert policy.base_image == "ubuntu:20.04"


# ---------------------------------------------------------------------------
# C. CleanupLinuxWorkspace tests
# ---------------------------------------------------------------------------


class TestCleanupLinuxWorkspace:
    def test_accepts_workspace_scoped_cleanup(self):
        cleanup = CleanupLinuxWorkspace(
            workspace_root="/home/learner/workspace",
            cleanup_paths=["/home/learner/workspace"],
        )
        assert cleanup.taint_on_cleanup_failure is True
        assert "workspace_removed_or_empty" in cleanup.residual_checks

    def test_taint_on_cleanup_failure_invariant(self):
        with pytest.raises(ValidationError, match="taint_on_cleanup_failure"):
            CleanupLinuxWorkspace(
                workspace_root="/home/learner/workspace",
                taint_on_cleanup_failure=False,
            )

    def test_rejects_cleanup_root_slash(self):
        """cleanup_paths=['/'] must fail StaticValidator."""
        cleanup = CleanupLinuxWorkspace(
            workspace_root="/home/learner/workspace",
            cleanup_paths=["/"],
        )
        draft = _linux_lab_draft(cleanup=cleanup)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.cleanup_safe" in failed

    def test_rejects_cleanup_etc(self):
        cleanup = CleanupLinuxWorkspace(
            workspace_root="/home/learner/workspace",
            cleanup_paths=["/etc"],
        )
        draft = _linux_lab_draft(cleanup=cleanup)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.cleanup_safe" in failed

    def test_rejects_cleanup_home_top_level(self):
        cleanup = CleanupLinuxWorkspace(
            workspace_root="/home/learner/workspace",
            cleanup_paths=["/home"],
        )
        draft = _linux_lab_draft(cleanup=cleanup)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.cleanup_safe" in failed

    def test_rejects_cleanup_path_outside_workspace(self):
        cleanup = CleanupLinuxWorkspace(
            workspace_root="/home/learner/workspace",
            cleanup_paths=["/home/learner/other-dir"],
        )
        draft = _linux_lab_draft(cleanup=cleanup)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.cleanup_safe" in failed

    def test_requires_all_residual_checks(self):
        cleanup = CleanupLinuxWorkspace(
            workspace_root="/home/learner/workspace",
            residual_checks=["workspace_removed_or_empty"],  # missing 3 required checks
        )
        draft = _linux_lab_draft(cleanup=cleanup)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.cleanup_safe" in failed

    def test_requires_taint_on_cleanup_failure_true(self):
        """Model-level validator rejects taint_on_cleanup_failure=False."""
        with pytest.raises(ValidationError):
            CleanupLinuxWorkspace(
                workspace_root="/home/learner/workspace",
                taint_on_cleanup_failure=False,
            )

    def test_workspace_root_cannot_be_empty(self):
        cleanup = CleanupLinuxWorkspace(workspace_root="")
        draft = _linux_lab_draft(cleanup=cleanup)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.cleanup_safe" in failed


# ---------------------------------------------------------------------------
# D. StaticValidator Linux domain tests
# ---------------------------------------------------------------------------


class TestStaticValidatorLinux:
    def test_valid_minimal_linux_contract_passes_schema_validation(self):
        """A complete, safe Linux contract passes all schema checks (except publish gate)."""
        step = _linux_step(
            linux_verify=[
                _linux_verify(type=LinuxVerifyType.LINUX_FILE_EXISTS, target_path="workspace/hello.txt"),
                _linux_verify(
                    verify_id="v2",
                    type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                    target_path="workspace/hello.txt",
                    expected_mode="644",
                ),
            ]
        )
        draft = _linux_lab_draft(steps=[step])
        results = StaticValidator().validate(draft)
        # Only the publish-blocked check should fail
        failed = [r for r in results if r.status == ValidatorStatus.FAILED]
        check_ids = {r.check_id for r in failed}
        assert check_ids == {"linux.publish_blocked_until_runtime"}

    def test_missing_sandbox_policy_fails(self):
        draft = _linux_lab_draft(sandbox=None)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.sandbox_policy_required" in failed

    def test_missing_cleanup_policy_fails(self):
        draft = _linux_lab_draft(cleanup=None)
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.cleanup_required" in failed

    def test_unsafe_absolute_path_fails(self):
        step = _linux_step(linux_verify=[
            _linux_verify(target_path="/etc/passwd"),
        ])
        draft = _linux_lab_draft(steps=[step])
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.verifiers_safe" in failed

    def test_path_traversal_fails(self):
        step = _linux_step(linux_verify=[
            _linux_verify(target_path="workspace/../etc/shadow"),
        ])
        draft = _linux_lab_draft(steps=[step])
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.verifiers_safe" in failed

    def test_root_required_sandbox_model_enforces_false(self):
        """allow_root=True is blocked at model layer before StaticValidator can see it."""
        with pytest.raises(ValidationError, match="allow_root"):
            LinuxSandboxPolicy(workspace_root="/home/learner/workspace", allow_root=True)

    def test_network_required_sandbox_model_enforces_false(self):
        """allow_network=True is blocked at model layer before StaticValidator can see it."""
        with pytest.raises(ValidationError, match="allow_network"):
            LinuxSandboxPolicy(workspace_root="/home/learner/workspace", allow_network=True)

    def test_placeholder_content_fails(self):
        draft = _linux_lab_draft(title="Linux Files [TODO: add real title]")
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "content.no_placeholders" in failed

    def test_linux_publish_gate_always_blocked(self):
        """linux.publish_blocked_until_runtime always fails regardless of contract quality."""
        draft = _linux_lab_draft()
        results = StaticValidator().validate(draft)
        blocked = [r for r in results if r.check_id == "linux.publish_blocked_until_runtime"]
        assert len(blocked) == 1
        assert blocked[0].status == ValidatorStatus.FAILED
        assert blocked[0].blocking_level == BlockingLevel.PUBLISH_BLOCKING

    def test_missing_expected_content_for_content_matcher_fails(self):
        step = _linux_step(linux_verify=[
            _linux_verify(
                type=LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES,
                # expected_content intentionally omitted
            ),
        ])
        draft = _linux_lab_draft(steps=[step])
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.verifiers_safe" in failed

    def test_missing_expected_mode_for_mode_matcher_fails(self):
        step = _linux_step(linux_verify=[
            _linux_verify(
                type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                # expected_mode intentionally omitted
            ),
        ])
        draft = _linux_lab_draft(steps=[step])
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.verifiers_safe" in failed

    def test_empty_target_path_fails(self):
        step = _linux_step(linux_verify=[
            LinuxVerifyTemplate(
                verify_id="v1",
                type=LinuxVerifyType.LINUX_FILE_EXISTS,
                target_path="",
            )
        ])
        draft = _linux_lab_draft(steps=[step])
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.verifiers_safe" in failed

    def test_pollution_level_set_to_namespace_only_when_sandbox_present(self):
        draft = _linux_lab_draft()
        StaticValidator().validate(draft)
        assert draft.pollution_level == PollutionLevel.NAMESPACE_ONLY

    def test_pollution_level_unknown_when_sandbox_missing(self):
        draft = _linux_lab_draft(sandbox=None)
        StaticValidator().validate(draft)
        assert draft.pollution_level == PollutionLevel.UNKNOWN

    def test_minimal_linux_example_file_permissions_lab(self):
        """Verify the canonical Linux Files and Permissions Basics example passes schema."""
        steps = [
            Step(
                step_id="step_1",
                order=1,
                why="Create a workspace file to practice permissions",
                do="Create hello.txt and write content to it",
                commands=[
                    "mkdir -p workspace",
                    "echo 'hello world' > workspace/hello.txt",
                ],
                observe="File created in workspace/",
                explain=_explain(
                    concept="Linux files start with default permissions from umask",
                    observation="hello.txt appears in workspace/ with owner-write permissions",
                ),
                linux_verify=[
                    LinuxVerifyTemplate(
                        verify_id="step1_v1",
                        type=LinuxVerifyType.LINUX_FILE_EXISTS,
                        target_path="workspace/hello.txt",
                        description="Verify hello.txt was created",
                        failure_hint="Run: echo 'hello world' > workspace/hello.txt",
                    ),
                    LinuxVerifyTemplate(
                        verify_id="step1_v2",
                        type=LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES,
                        target_path="workspace/hello.txt",
                        expected_content="hello world",
                        description="Verify file content",
                        failure_hint="Run: echo 'hello world' > workspace/hello.txt",
                    ),
                ],
            ),
            Step(
                step_id="step_2",
                order=2,
                why="Practice chmod to set specific permission bits",
                do="Set hello.txt to read-only for owner",
                commands=["chmod 644 workspace/hello.txt"],
                observe="ls -l shows -rw-r--r-- for hello.txt",
                explain=_explain(
                    concept="chmod 644 sets owner=rw, group=r, others=r",
                    observation="permission string shows -rw-r--r-- after chmod",
                ),
                linux_verify=[
                    LinuxVerifyTemplate(
                        verify_id="step2_v1",
                        type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                        target_path="workspace/hello.txt",
                        expected_mode="644",
                        description="Verify permission mode is 644",
                        failure_hint="Run: chmod 644 workspace/hello.txt",
                    ),
                ],
            ),
        ]
        draft = LabDraft(
            source_article_id="article-linux-files-001",
            title="Linux Files and Permissions Basics",
            description=(
                "Practice creating files, reading permissions, and using chmod "
                "in a safe isolated workspace."
            ),
            estimated_duration_minutes=20,
            target_domain=LabDomainType.LINUX,
            runtime_requirements=RuntimeRequirements(),
            steps=steps,
            linux_sandbox_policy=LinuxSandboxPolicy(
                workspace_root="/home/learner/workspace",
                working_directory="/home/learner/workspace",
            ),
            linux_cleanup=CleanupLinuxWorkspace(
                workspace_root="/home/learner/workspace",
                cleanup_paths=["/home/learner/workspace"],
            ),
        )
        results = StaticValidator().validate(draft)
        failed = [r for r in results if r.status == ValidatorStatus.FAILED]
        # Only the runtime publish gate should fail
        assert len(failed) == 1
        assert failed[0].check_id == "linux.publish_blocked_until_runtime"


# ---------------------------------------------------------------------------
# E. Article pipeline Linux tests (H-01, H-02)
# ---------------------------------------------------------------------------


class TestLinuxArticlePipeline:
    def test_stub_classifier_detects_linux_domain(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import TargetDomain

        text = (
            "This tutorial covers Linux file permissions. "
            "We will use chmod and chown to manage file ownership. "
            "Step 1: mkdir workspace\n"
            "Step 2: touch workspace/file.txt\n"
            "Step 3: chmod 644 workspace/file.txt\n"
            "$ ls -l workspace/\n"
        )
        result = StubFeasibilityClassifier().classify(text)
        assert TargetDomain.LINUX in result.target_domain_candidates

    def test_stub_classifier_linux_article_not_not_lab_ready(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus

        text = (
            "Linux file permissions tutorial. "
            "chmod 755 myfile.txt\n"
            "ls -l shows drwxr-xr-x\n"
            "```bash\nchmod 644 file.txt\n```\n"
        )
        result = StubFeasibilityClassifier().classify(text)
        assert result.status != FeasibilityStatus.NOT_LAB_READY

    def test_stub_classifier_k8s_not_confused_with_linux(self):
        """K8s keywords should not be classified as Linux."""
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import TargetDomain

        text = "kubectl apply -f deployment.yaml\nkubectl get pods -n default"
        result = StubFeasibilityClassifier().classify(text)
        assert TargetDomain.K8S in result.target_domain_candidates
        assert TargetDomain.LINUX not in result.target_domain_candidates

    def test_pick_target_domain_returns_linux_for_linux_candidates(self):
        from backend.labgen.article_draft_service import _pick_target_domain
        from backend.labgen.article_models import (
            FeasibilityResult,
            FeasibilityStatus,
            TargetDomain,
            VerifierFeasibility,
        )

        result = FeasibilityResult(
            status=FeasibilityStatus.DIRECTLY_LAB_READY,
            target_domain_candidates=[TargetDomain.LINUX],
            verifier_feasibility=VerifierFeasibility.NEEDS_NEW_PRIMITIVE,
            evaluated_at=datetime.now(tz=timezone.utc),
        )
        assert _pick_target_domain(result) == TargetDomain.LINUX

    def test_pick_target_domain_prefers_k8s_over_linux(self):
        from backend.labgen.article_draft_service import _pick_target_domain
        from backend.labgen.article_models import (
            FeasibilityResult,
            FeasibilityStatus,
            TargetDomain,
            VerifierFeasibility,
        )

        result = FeasibilityResult(
            status=FeasibilityStatus.DIRECTLY_LAB_READY,
            target_domain_candidates=[TargetDomain.K8S, TargetDomain.LINUX],
            verifier_feasibility=VerifierFeasibility.REUSABLE_EXISTING,
            evaluated_at=datetime.now(tz=timezone.utc),
        )
        assert _pick_target_domain(result) == TargetDomain.K8S

    def test_linux_domain_not_blocked_in_article_draft_validator(self):
        """Linux domain articles must not be blocked by ArticleDraftValidator (only CLOUD is)."""
        from backend.labgen.static_validator import ArticleDraftValidator
        from backend.labgen.article_models import (
            AdminDecision,
            AdminDecisionValue,
            ArticleDraftLabContract,
            ArticleDraftStatus,
            ArticleLabRuntimeRequirement,
            ArticleRuntimeType,
            ArticleSourceMetadata,
            ArticleSourceType,
            FeasibilityEvaluatedBy,
            FeasibilityResult,
            FeasibilityStatus,
            TargetDomain,
            VerifierFeasibility,
        )
        import hashlib

        meta = ArticleSourceMetadata(
            submitted_by_user_id="admin-1",
            content_hash=hashlib.sha256(b"linux article").hexdigest(),
            content_length=200,
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
        )
        feasibility = FeasibilityResult(
            status=FeasibilityStatus.DIRECTLY_LAB_READY,
            target_domain_candidates=[TargetDomain.LINUX],
            verifier_feasibility=VerifierFeasibility.NEEDS_NEW_PRIMITIVE,
            evaluated_at=datetime.now(tz=timezone.utc),
        )
        contract = ArticleDraftLabContract(
            source_metadata=meta,
            feasibility_result=feasibility,
            target_domain=TargetDomain.LINUX,
            status=ArticleDraftStatus.DRAFT,
            required_runtime=ArticleLabRuntimeRequirement(
                domain=TargetDomain.LINUX,
                runtime_type=ArticleRuntimeType.LINUX_VM,
            ),
        )
        results = ArticleDraftValidator().validate(contract)
        # No check should be specifically for "linux blocked" — cloud is blocked, not linux
        fail_ids = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "article_draft.cloud_domain_blocked_v1" not in fail_ids


# ---------------------------------------------------------------------------
# F. K8s regression tests
# ---------------------------------------------------------------------------


class TestK8sRegression:
    def test_k8s_lab_target_domain_defaults_to_k8s(self):
        draft = LabDraft(
            source_article_id="art-1",
            title="K8s Lab",
            description="K8s lab description",
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            steps=[_k8s_step()],
            cleanup=_k8s_cleanup(),
        )
        assert draft.target_domain == LabDomainType.K8S

    def test_k8s_validator_runs_existing_checks_unchanged(self):
        """Existing K8s lab still gets all K8s-specific checks."""
        draft = _k8s_lab_draft()
        results = StaticValidator().validate(draft)
        check_ids = {r.check_id for r in results}
        # All expected K8s check_ids must be present
        expected = {
            "content.no_placeholders",
            "image.no_latest_tag",
            "image.no_unknown_registry",
            "image.all_resolved",
            "image.all_exist_in_registry",
            "explain.verified_if_published",
            "namespace.no_hardcoded",
            "verify.no_shell_commands",
            "verify.no_secret_value",
            "cleanup.declared",
            "cluster_scoped.cleanup_declared",
            "helm.no_generation",
            "service.nodeport",
            "operator.crd",
            "pollution.known",
        }
        assert expected.issubset(check_ids)

    def test_k8s_valid_lab_still_passes(self):
        draft = _k8s_lab_draft()
        results = StaticValidator().validate(draft)
        failed = [r for r in results if r.status == ValidatorStatus.FAILED]
        # Image checks fail (no image_resolution) but no PUBLISH_BLOCKING failures
        # that would not exist before this PR
        assert all(r.check_id.startswith("image.") for r in failed)

    def test_k8s_cleanup_declared_check_still_runs(self):
        """K8s lab with no cleanup still fails cleanup.declared."""
        draft = LabDraft(
            source_article_id="art-1",
            title="K8s Lab",
            description="K8s lab",
            estimated_duration_minutes=30,
            target_domain=LabDomainType.K8S,
            runtime_requirements=RuntimeRequirements(),
            steps=[_k8s_step()],
            cleanup=None,
        )
        results = StaticValidator().validate(draft)
        failed = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "cleanup.declared" in failed

    def test_k8s_no_linux_verifiers_passes_clean_lab(self):
        """Clean K8s lab with no linux_verify entries passes k8s.no_linux_verifiers."""
        draft = _k8s_lab_draft()
        results = StaticValidator().validate(draft)
        k8s_linux_check = [r for r in results if r.check_id == "k8s.no_linux_verifiers"]
        assert len(k8s_linux_check) == 1
        assert k8s_linux_check[0].status == ValidatorStatus.PASSED

    def test_k8s_lab_not_linux_publish_blocked(self):
        """K8s labs must not be blocked by the Linux publish gate."""
        draft = _k8s_lab_draft()
        results = StaticValidator().validate(draft)
        linux_blocked = [r for r in results if r.check_id == "linux.publish_blocked_until_runtime"]
        assert len(linux_blocked) == 0

    def test_lab_domain_type_enum_values(self):
        assert LabDomainType.K8S.value == "k8s"
        assert LabDomainType.LINUX.value == "linux"
        assert LabDomainType.DOCKER.value == "docker"

    def test_linux_verify_type_enum_values(self):
        assert LinuxVerifyType.LINUX_FILE_EXISTS.value == "linux_file_exists"
        assert LinuxVerifyType.LINUX_DIRECTORY_EXISTS.value == "linux_directory_exists"
        assert LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES.value == "linux_file_content_matches"
        assert LinuxVerifyType.LINUX_FILE_MODE_MATCHES.value == "linux_file_mode_matches"
        assert LinuxVerifyType.LINUX_NO_RESIDUAL_FILES.value == "linux_no_residual_files"

    def test_lab_draft_serialization_roundtrip_k8s(self):
        """LabDraft with target_domain=K8S serializes and deserializes correctly."""
        draft = _k8s_lab_draft()
        data = draft.model_dump()
        restored = LabDraft.model_validate(data)
        assert restored.target_domain == LabDomainType.K8S
        assert restored.linux_sandbox_policy is None
        assert restored.linux_cleanup is None

    def test_lab_draft_serialization_roundtrip_linux(self):
        """LabDraft with target_domain=LINUX serializes and deserializes correctly."""
        draft = _linux_lab_draft()
        data = draft.model_dump()
        restored = LabDraft.model_validate(data)
        assert restored.target_domain == LabDomainType.LINUX
        assert restored.linux_sandbox_policy is not None
        assert restored.linux_cleanup is not None
        assert restored.linux_sandbox_policy.workspace_root == "/home/learner/workspace"
