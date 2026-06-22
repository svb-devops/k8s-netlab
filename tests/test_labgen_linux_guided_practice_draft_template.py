"""
Linux Guided Practice Draft Template — test suite.

Covers:
  A. Template generation (LinuxFilesPermissionsTemplate / generate_linux)
  B. Feasibility classifier (Linux signals, reject, partial, direct)
  C. StaticValidator Linux checks (sandbox, cleanup, verifiers, placeholder, publish-blocked)
  D. Catalog / publish isolation (no learner visibility, publish blocked)
  E. Regression (K8s draft generation, Lab 5, verifier hardening, runtime spike)
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def template():
    from backend.labgen.linux_template import LinuxFilesPermissionsTemplate
    return LinuxFilesPermissionsTemplate()


@pytest.fixture()
def generated_draft(template):
    return template.build_draft(source_article_id="test-linux-article-001")


@pytest.fixture()
def stub_generator():
    from backend.labgen.stub_generator import LabDraftGeneratorStub
    return LabDraftGeneratorStub()


@pytest.fixture()
def linux_draft_via_stub(stub_generator):
    return stub_generator.generate_linux(source_article_id="test-linux-stub-001")


@pytest.fixture()
def classifier():
    from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
    return StubFeasibilityClassifier()


@pytest.fixture()
def validator():
    from backend.labgen.static_validator import StaticValidator
    return StaticValidator()


def _valid_linux_draft():
    """Return a valid Linux draft from the template for validator tests."""
    from backend.labgen.linux_template import LinuxFilesPermissionsTemplate
    return LinuxFilesPermissionsTemplate().build_draft("test-article-validator")


# ---------------------------------------------------------------------------
# A. Template generation tests
# ---------------------------------------------------------------------------


class TestLinuxTemplateGeneration:
    def test_target_domain_is_linux(self, generated_draft):
        from backend.labgen.models import LabDomainType
        assert generated_draft.target_domain == LabDomainType.LINUX

    def test_has_experiment_background_in_description(self, generated_draft):
        assert generated_draft.description
        assert len(generated_draft.description) > 20
        assert "placeholder" not in generated_draft.description.lower()
        assert "TODO" not in generated_draft.description

    def test_has_learning_objectives_in_prerequisites(self, generated_draft):
        assert generated_draft.prerequisites
        assert len(generated_draft.prerequisites) >= 1
        full_text = " ".join(generated_draft.prerequisites)
        assert len(full_text) > 20

    def test_has_at_least_three_guided_steps(self, generated_draft):
        assert len(generated_draft.steps) >= 3

    def test_all_steps_have_why(self, generated_draft):
        for step in generated_draft.steps:
            assert step.why and len(step.why) > 10, f"Step {step.step_id} missing why"

    def test_all_steps_have_do(self, generated_draft):
        for step in generated_draft.steps:
            assert step.do and len(step.do) > 10, f"Step {step.step_id} missing do"

    def test_first_three_steps_have_commands(self, generated_draft):
        for step in generated_draft.steps[:3]:
            assert step.commands, f"Step {step.step_id} has no commands"

    def test_all_steps_have_observe(self, generated_draft):
        for step in generated_draft.steps:
            assert step.observe and len(step.observe) > 5, \
                f"Step {step.step_id} missing observe"

    def test_all_steps_have_explain_concept(self, generated_draft):
        for step in generated_draft.steps:
            assert step.explain.concept and len(step.explain.concept) > 10, \
                f"Step {step.step_id} missing explain.concept"

    def test_all_steps_have_explain_observation_as_troubleshooting(self, generated_draft):
        for step in generated_draft.steps:
            assert step.explain.observation and len(step.explain.observation) > 10, \
                f"Step {step.step_id} missing explain.observation"

    def test_all_steps_have_linux_verifiers(self, generated_draft):
        for step in generated_draft.steps:
            assert step.linux_verify, f"Step {step.step_id} has no linux_verify"

    def test_linux_sandbox_policy_present(self, generated_draft):
        assert generated_draft.linux_sandbox_policy is not None

    def test_cleanup_linux_workspace_present(self, generated_draft):
        assert generated_draft.linux_cleanup is not None

    def test_ai_tutor_context_present(self, generated_draft):
        assert generated_draft.ai_tutor_context is not None
        ctx = generated_draft.ai_tutor_context
        assert "sudo" in ctx.lower()
        assert "LLM" in ctx or "llm" in ctx.lower()

    def test_no_placeholder_text_in_draft(self, generated_draft):
        import re
        placeholder_re = re.compile(
            r"\[TODO[^\]]*\]|(?<!\w)TODO(?!\w)|\bTBD\b|\bPLACEHOLDER\b",
            re.IGNORECASE,
        )
        for field in [generated_draft.title, generated_draft.description]:
            assert not placeholder_re.search(field), \
                f"Placeholder found in field: {field}"
        for step in generated_draft.steps:
            for text in [step.why, step.do, step.observe]:
                assert not placeholder_re.search(text), \
                    f"Placeholder in step {step.step_id}: {text}"

    def test_all_five_linux_verifier_primitives_used(self, generated_draft):
        from backend.labgen.models import LinuxVerifyType
        used_types = {
            lv.type
            for step in generated_draft.steps
            for lv in step.linux_verify
        }
        assert LinuxVerifyType.LINUX_DIRECTORY_EXISTS in used_types
        assert LinuxVerifyType.LINUX_FILE_EXISTS in used_types
        assert LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES in used_types
        assert LinuxVerifyType.LINUX_FILE_MODE_MATCHES in used_types
        assert LinuxVerifyType.LINUX_NO_RESIDUAL_FILES in used_types

    def test_sandbox_policy_no_root_no_network(self, generated_draft):
        policy = generated_draft.linux_sandbox_policy
        assert policy.allow_root is False
        assert policy.allow_network is False

    def test_sandbox_policy_has_workspace_root(self, generated_draft):
        policy = generated_draft.linux_sandbox_policy
        assert policy.workspace_root
        assert "/home" in policy.workspace_root or "/tmp" in policy.workspace_root \
            or "workspace" in policy.workspace_root

    def test_sandbox_policy_denies_sudo_systemctl(self, generated_draft):
        policy = generated_draft.linux_sandbox_policy
        denied = " ".join(policy.denied_commands).lower()
        assert "sudo" in denied
        assert "systemctl" in denied

    def test_cleanup_workspace_root_not_system_dir(self, generated_draft):
        cleanup = generated_draft.linux_cleanup
        forbidden = {"/", "/home", "/tmp", "/etc", "/var", "/root"}
        assert cleanup.workspace_root not in forbidden

    def test_cleanup_taint_on_failure(self, generated_draft):
        assert generated_draft.linux_cleanup.taint_on_cleanup_failure is True

    def test_cleanup_has_all_required_residual_checks(self, generated_draft):
        required = {
            "workspace_removed_or_empty",
            "no_session_owned_processes",
            "credentials_revoked",
            "terminal_closed",
        }
        actual = set(generated_draft.linux_cleanup.residual_checks)
        assert required.issubset(actual)

    def test_verifier_candidates_present_in_step1(self, generated_draft):
        from backend.labgen.models import LinuxVerifyType
        step1 = generated_draft.steps[0]
        types = {lv.type for lv in step1.linux_verify}
        assert LinuxVerifyType.LINUX_DIRECTORY_EXISTS in types
        assert LinuxVerifyType.LINUX_FILE_EXISTS in types
        assert LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES in types

    def test_content_matches_verifier_has_expected_content(self, generated_draft):
        from backend.labgen.models import LinuxVerifyType
        for step in generated_draft.steps:
            for lv in step.linux_verify:
                if lv.type == LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES:
                    assert lv.expected_content, \
                        f"linux_file_content_matches missing expected_content in {lv.verify_id}"

    def test_mode_matches_verifier_has_expected_mode(self, generated_draft):
        from backend.labgen.models import LinuxVerifyType
        for step in generated_draft.steps:
            for lv in step.linux_verify:
                if lv.type == LinuxVerifyType.LINUX_FILE_MODE_MATCHES:
                    assert lv.expected_mode, \
                        f"linux_file_mode_matches missing expected_mode in {lv.verify_id}"
                    assert lv.expected_mode == "600"

    def test_generate_linux_via_stub_generator(self, linux_draft_via_stub):
        from backend.labgen.models import LabDomainType
        assert linux_draft_via_stub.target_domain == LabDomainType.LINUX
        assert linux_draft_via_stub.linux_sandbox_policy is not None
        assert linux_draft_via_stub.linux_cleanup is not None
        assert linux_draft_via_stub.ai_tutor_context is not None

    def test_generate_linux_stub_title_override(self, stub_generator):
        draft = stub_generator.generate_linux(
            source_article_id="art-001",
            title="My Custom Title",
        )
        assert draft.title == "My Custom Title"

    def test_generate_linux_stub_description_override(self, stub_generator):
        draft = stub_generator.generate_linux(
            source_article_id="art-001",
            description="Custom description text",
        )
        assert draft.description == "Custom description text"

    def test_k8s_verifiers_absent_in_linux_draft(self, generated_draft):
        for step in generated_draft.steps:
            assert not step.verify, \
                f"Step {step.step_id} has K8s verifiers (verify) in Linux draft"

    def test_no_k8s_cleanup_in_linux_draft(self, generated_draft):
        assert generated_draft.cleanup is None


# ---------------------------------------------------------------------------
# B. Feasibility classifier tests
# ---------------------------------------------------------------------------


class TestLinuxFeasibilityClassifier:
    def _linux_article(self, extra: str = "") -> str:
        return (
            "# Linux Files and Permissions\n\n"
            "Learn how to create directories and set file permissions in Linux.\n\n"
            "## Step 1: Create a directory\n\n"
            "```bash\n"
            "mkdir -p demo\n"
            "printf 'hello labgen\\n' > demo/message.txt\n"
            "```\n\n"
            "Expected output: the file demo/message.txt now exists.\n\n"
            "## Step 2: Change permissions\n\n"
            "```bash\n"
            "chmod 600 demo/message.txt\n"
            'stat -c "%a" demo/message.txt\n'
            "```\n\n"
            "Expected output: 600\n\n"
            + extra
        )

    def test_safe_linux_article_directly_lab_ready(self, classifier):
        from backend.labgen.article_models import FeasibilityStatus, TargetDomain
        result = classifier.classify(self._linux_article())
        assert result.status == FeasibilityStatus.DIRECTLY_LAB_READY
        assert TargetDomain.LINUX in result.target_domain_candidates

    def test_linux_article_missing_commands_partially_ready(self, classifier):
        from backend.labgen.article_models import FeasibilityStatus
        text = (
            "# Linux Permissions\n\n"
            "Linux file permissions control read, write, and execute access. "
            "chmod and chown are useful tools for managing permissions."
        )
        result = classifier.classify(text)
        assert result.status == FeasibilityStatus.PARTIALLY_LAB_READY

    def test_linux_article_with_sudo_rejected(self, classifier):
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        text = self._linux_article(extra="\nsudo chmod 600 /etc/file\n")
        result = classifier.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.DANGEROUS_OR_ILLEGAL in result.safety_flags

    def test_linux_article_with_systemctl_rejected(self, classifier):
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        text = (
            "# Managing Services\n\n"
            "Use systemctl to start and stop services.\n\n"
            "```bash\n"
            "systemctl start nginx\n"
            "```\n\n"
            "chmod 644 /etc/nginx/nginx.conf\n"
        )
        result = classifier.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.DANGEROUS_OR_ILLEGAL in result.safety_flags

    def test_linux_article_with_su_dash_rejected(self, classifier):
        """Regression: su - (no trailing word char) must be caught by unsafe pattern."""
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        for text in [
            self._linux_article(extra="\nsu -\n"),
            self._linux_article(extra="\nsu - root\n"),
            self._linux_article(extra="\nsudo su -\n"),
        ]:
            result = classifier.classify(text)
            assert result.status == FeasibilityStatus.NOT_LAB_READY, f"su - variant not rejected: {text!r}"
            assert SafetyFlag.DANGEROUS_OR_ILLEGAL in result.safety_flags

    def test_linux_article_modifying_etc_rejected(self, classifier):
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        text = (
            "# Linux Config\n\n"
            "Edit /etc/hosts to add entries.\n\n"
            "```bash\n"
            "echo '127.0.0.1 myapp' > /etc/hosts\n"
            "```\n\n"
            "chmod 644 /etc/hosts\n"
        )
        result = classifier.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.REQUIRES_PRODUCTION_ENVIRONMENT in result.safety_flags

    def test_linux_article_with_curl_network_rejected(self, classifier):
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        text = (
            "# Downloading Files\n\n"
            "Use curl to download files.\n\n"
            "```bash\n"
            "mkdir demo\n"
            "curl https://example.com/file.txt > demo/file.txt\n"
            "chmod 600 demo/file.txt\n"
            "```\n"
        )
        result = classifier.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.UNSAFE_NETWORK_BEHAVIOR in result.safety_flags

    def test_linux_article_with_secrets_rejected(self, classifier):
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        text = (
            "# Config\nchmod 600 config.txt\napi_key = my-super-secret-key-abcdef123456"
        )
        result = classifier.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT in result.safety_flags

    def test_k8s_article_not_confused_with_linux(self, classifier):
        from backend.labgen.article_models import TargetDomain
        text = (
            "# Kubernetes ConfigMap\n\n"
            "kubectl apply -f configmap.yaml -n mynamespace\n"
            "kubectl get configmap myconfig\n"
        )
        result = classifier.classify(text)
        assert TargetDomain.K8S in result.target_domain_candidates
        assert TargetDomain.LINUX not in result.target_domain_candidates


# ---------------------------------------------------------------------------
# C. StaticValidator tests
# ---------------------------------------------------------------------------


class TestStaticValidatorLinuxGuidedPractice:
    def _check_ids(self, results) -> set[str]:
        return {r.check_id for r in results}

    def _failed_ids(self, results) -> set[str]:
        from backend.labgen.models import ValidatorStatus
        return {r.check_id for r in results if r.status == ValidatorStatus.FAILED}

    def _passed_ids(self, results) -> set[str]:
        from backend.labgen.models import ValidatorStatus
        return {r.check_id for r in results if r.status == ValidatorStatus.PASSED}

    def test_valid_linux_draft_passes_all_checks_except_publish(self, validator):
        from backend.labgen.models import ValidatorStatus
        draft = _valid_linux_draft()
        results = validator.validate(draft)
        failed = [r for r in results if r.status == ValidatorStatus.FAILED]
        # Only publish-blocked gate should fail
        assert len(failed) == 1
        assert failed[0].check_id == "linux.publish_blocked_until_runtime"

    def test_missing_sandbox_policy_fails(self, validator):
        draft = _valid_linux_draft()
        draft.linux_sandbox_policy = None
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "linux.sandbox_policy_required" in failed_ids

    def test_missing_cleanup_fails(self, validator):
        draft = _valid_linux_draft()
        draft.linux_cleanup = None
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "linux.cleanup_required" in failed_ids

    def test_missing_verifiers_fails(self, validator):
        draft = _valid_linux_draft()
        for step in draft.steps:
            step.linux_verify = []
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "linux.verifiers_present" in failed_ids

    def test_valid_draft_passes_verifiers_present(self, validator):
        draft = _valid_linux_draft()
        results = validator.validate(draft)
        passed_ids = self._passed_ids(results)
        assert "linux.verifiers_present" in passed_ids

    def test_placeholder_content_fails(self, validator):
        draft = _valid_linux_draft()
        draft.title = "TODO: fill this in"
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "content.no_placeholders" in failed_ids

    def test_unsafe_absolute_path_in_verifier_fails(self, validator):
        from backend.labgen.models import LinuxVerifyTemplate, LinuxVerifyType
        draft = _valid_linux_draft()
        draft.steps[0].linux_verify.append(
            LinuxVerifyTemplate(
                verify_id="evil-v1",
                type=LinuxVerifyType.LINUX_FILE_EXISTS,
                target_path="/etc/passwd",
            )
        )
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "linux.verifiers_safe" in failed_ids

    def test_allow_root_true_fails_at_model_validation(self, validator):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            from backend.labgen.models import LinuxSandboxPolicy
            LinuxSandboxPolicy(
                workspace_root="/home/learner/workspace",
                allow_root=True,
            )

    def test_allow_network_true_fails_at_model_validation(self, validator):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            from backend.labgen.models import LinuxSandboxPolicy
            LinuxSandboxPolicy(
                workspace_root="/home/learner/workspace",
                allow_network=True,
            )

    def test_linux_publish_always_blocked(self, validator):
        from backend.labgen.models import ValidatorStatus
        draft = _valid_linux_draft()
        results = validator.validate(draft)
        publish_blocked = [
            r for r in results
            if r.check_id == "linux.publish_blocked_until_runtime"
            and r.status == ValidatorStatus.FAILED
        ]
        assert len(publish_blocked) == 1

    def test_missing_expected_content_for_content_matcher_fails(self, validator):
        from backend.labgen.models import LinuxVerifyTemplate, LinuxVerifyType
        draft = _valid_linux_draft()
        draft.steps[0].linux_verify.append(
            LinuxVerifyTemplate(
                verify_id="bad-content",
                type=LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES,
                target_path="demo/file.txt",
                expected_content=None,
            )
        )
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "linux.verifiers_safe" in failed_ids

    def test_missing_expected_mode_for_mode_matcher_fails(self, validator):
        from backend.labgen.models import LinuxVerifyTemplate, LinuxVerifyType
        draft = _valid_linux_draft()
        draft.steps[0].linux_verify.append(
            LinuxVerifyTemplate(
                verify_id="bad-mode",
                type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                target_path="demo/file.txt",
                expected_mode=None,
            )
        )
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "linux.verifiers_safe" in failed_ids

    def test_k8s_verifiers_in_linux_draft_fail(self, validator):
        from backend.labgen.models import VerifyTemplate, VerifyType
        draft = _valid_linux_draft()
        draft.steps[0].verify.append(
            VerifyTemplate(
                verify_id="k8s-bad",
                type=VerifyType.CONFIGMAP_EXISTS,
                name="myconfig",
                namespace="{{lab_namespace}}",
            )
        )
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "linux.no_k8s_verifiers" in failed_ids

    def test_missing_cleanup_residual_check_fails(self, validator):
        from backend.labgen.models import CleanupLinuxWorkspace
        draft = _valid_linux_draft()
        draft.linux_cleanup = CleanupLinuxWorkspace(
            workspace_root="/home/learner/workspace",
            cleanup_paths=["/home/learner/workspace"],
            residual_checks=["workspace_removed_or_empty"],  # missing 3 required
            taint_on_cleanup_failure=True,
        )
        results = validator.validate(draft)
        failed_ids = self._failed_ids(results)
        assert "linux.cleanup_safe" in failed_ids

    def test_pollution_level_set_to_namespace_only_for_linux(self, validator):
        from backend.labgen.models import PollutionLevel
        draft = _valid_linux_draft()
        validator.validate(draft)
        assert draft.pollution_level == PollutionLevel.NAMESPACE_ONLY


# ---------------------------------------------------------------------------
# D. Catalog / publish isolation tests
# ---------------------------------------------------------------------------


class TestLinuxCatalogAndPublishIsolation:
    def test_linux_draft_publish_blocked_by_static_validator(self, validator):
        from backend.labgen.models import BlockingLevel, ValidatorStatus
        draft = _valid_linux_draft()
        results = validator.validate(draft)
        publish_blocking_failures = [
            r for r in results
            if r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        assert publish_blocking_failures, "Expected at least one publish-blocking failure"
        check_ids = {r.check_id for r in publish_blocking_failures}
        assert "linux.publish_blocked_until_runtime" in check_ids

    def test_linux_draft_not_in_learner_catalog(self):
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.static_validator import StaticValidator
        from pathlib import Path
        import tempfile, os

        draft = _valid_linux_draft()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            repo = LabDraftRepository(path=Path(path))
            repo.create(draft)
            svc = LearnerCatalogService(draft_repo=repo, validator=StaticValidator())
            entries = svc.list_published_labs(actor_user="test-learner")
            linux_entries = [
                e for e in entries
                if getattr(e, "target_domain", None) == "linux"
            ]
            assert not linux_entries, "Linux labs must not appear in learner catalog"
        finally:
            os.unlink(path)

    def test_linux_draft_publish_status_is_draft(self):
        from backend.labgen.models import PublishStatus
        draft = _valid_linux_draft()
        assert draft.publish_status == PublishStatus.DRAFT

    def test_publish_gate_blocks_linux_draft_via_static_validator(self):
        """StaticValidator (the publish gate) always blocks Linux labs."""
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.models import BlockingLevel, ValidatorStatus

        draft = _valid_linux_draft()
        results = StaticValidator().validate(draft)
        publish_blocking = [
            r for r in results
            if r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        assert publish_blocking, "StaticValidator must return at least one publish-blocking failure"
        check_ids = {r.check_id for r in publish_blocking}
        assert "linux.publish_blocked_until_runtime" in check_ids

    def test_linux_draft_target_domain_linux_not_k8s(self):
        """Linux draft target_domain must be LINUX, never K8S."""
        from backend.labgen.models import LabDomainType
        draft = _valid_linux_draft()
        assert draft.target_domain == LabDomainType.LINUX
        assert draft.target_domain != LabDomainType.K8S


# ---------------------------------------------------------------------------
# E. Regression tests
# ---------------------------------------------------------------------------


class TestRegressionK8sAndLinuxPrevious:
    def test_k8s_stub_generate_unchanged(self):
        from backend.labgen.stub_generator import LabDraftGeneratorStub
        from backend.labgen.models import LabDomainType
        stub = LabDraftGeneratorStub()
        draft = stub.generate(
            source_article_id="k8s-001",
            title="K8s Test",
            description="K8s description",
        )
        assert draft.target_domain == LabDomainType.K8S
        assert draft.linux_sandbox_policy is None
        assert draft.linux_cleanup is None

    def test_k8s_static_validator_unchanged(self, validator):
        from backend.labgen.models import (
            CleanupNamespace,
            CleanupSpec,
            ExplainField,
            LabDraft,
            RuntimeRequirements,
            Step,
        )
        step = Step(
            step_id="s1",
            order=1,
            why="why",
            do="do",
            observe="observe",
            explain=ExplainField(concept="c", observation="o"),
        )
        draft = LabDraft(
            source_article_id="k8s-art",
            title="K8s Lab",
            description="K8s lab description",
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            steps=[step],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
        results = validator.validate(draft)
        # K8s validator must still run (not Linux path)
        check_ids = {r.check_id for r in results}
        assert "cleanup.declared" in check_ids
        assert "linux.publish_blocked_until_runtime" not in check_ids

    def test_linux_verifier_hardening_tests_still_importable(self):
        import importlib
        mod = importlib.import_module("tests.test_labgen_linux_verifier_hardening")
        assert mod is not None

    def test_linux_runtime_spike_tests_still_importable(self):
        import importlib
        mod = importlib.import_module("tests.test_labgen_linux_runtime_adapter_spike")
        assert mod is not None

    def test_k8s_configmap_article_feasibility_unchanged(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus, TargetDomain
        text = (
            "# Kubernetes ConfigMap Basics\n\n"
            "```bash\n"
            "kubectl apply -f configmap.yaml -n mynamespace\n"
            "kubectl get configmap myconfig -n mynamespace\n"
            "```\n\n"
            "Expected: ConfigMap myconfig exists in the namespace.\n"
        )
        clf = StubFeasibilityClassifier()
        result = clf.classify(text)
        assert result.status == FeasibilityStatus.DIRECTLY_LAB_READY
        assert TargetDomain.K8S in result.target_domain_candidates
        assert TargetDomain.LINUX not in result.target_domain_candidates

    def test_linux_domain_schema_tests_still_importable(self):
        import importlib
        mod = importlib.import_module("tests.test_labgen_linux_domain_schema")
        assert mod is not None

    def test_template_id_is_set(self):
        from backend.labgen.linux_template import LinuxFilesPermissionsTemplate
        tmpl = LinuxFilesPermissionsTemplate()
        assert tmpl.template_id == "LINUX_FILES_PERMISSIONS"

    def test_display_name_present(self):
        from backend.labgen.linux_template import LinuxFilesPermissionsTemplate
        tmpl = LinuxFilesPermissionsTemplate()
        assert tmpl.display_name
        assert "Linux" in tmpl.display_name

    def test_ai_tutor_context_field_defaults_none_for_k8s(self):
        from backend.labgen.stub_generator import LabDraftGeneratorStub
        stub = LabDraftGeneratorStub()
        draft = stub.generate("art-k8s", "K8s", "K8s desc")
        assert draft.ai_tutor_context is None

    def test_linux_draft_ai_tutor_context_not_none(self):
        from backend.labgen.stub_generator import LabDraftGeneratorStub
        stub = LabDraftGeneratorStub()
        draft = stub.generate_linux("art-linux")
        assert draft.ai_tutor_context is not None
