"""
Real kernel-level access-check verifier: path_access_condition.

Golden Topic #1 ("chmod correct, still Permission Denied") depends on a
verifier that can distinguish "file mode looks fine" from "the kernel
actually refuses access to the runner identity because a parent directory
lacks the execute/traverse bit" — file_mode_matches (os.lstat, pure bit
comparison, executed in-process as root) cannot do this; see
linux_verifier_client.py's LinuxVerifyClientAdapter.file_mode_matches().

path_access_condition reuses the exact same production privilege-drop
mechanism as learner commands (LinuxCommandExecutor with runner_uid/gid,
subprocess kwargs not preexec_fn) to run `cat` as the non-root runner and
read the real returncode/stderr — never simulated, never inferred from mode
bits alone. It fails closed (never silently checks as root) if no
privilege-separated executor is wired in.
"""

from __future__ import annotations

import os
import shutil
import uuid

import pytest

pytestmark = pytest.mark.static

from backend.labgen.linux_command_executor import LinuxCommandExecutor
from backend.labgen.linux_runner_identity import resolve_runner_identity
from backend.labgen.linux_verifier_client import LinuxVerifierService
from backend.labgen.linux_workspace import _SPIKE_SANDBOX_ROOT, LinuxWorkspaceManager
from backend.labgen.models import LinuxVerifyTemplate, LinuxVerifyType

RUNNER_IDENTITY = resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")


def _access_tmpl(
    path: str,
    expected_access: bool,
    expected_errno: str | None = None,
    access_operation: str = "read_file",
    verify_id: str = "v-pac",
) -> LinuxVerifyTemplate:
    return LinuxVerifyTemplate(
        verify_id=verify_id,
        type=LinuxVerifyType.LINUX_PATH_ACCESS_CONDITION,
        target_path=path,
        access_operation=access_operation,
        expected_access=expected_access,
        expected_errno=expected_errno,
    )


@pytest.fixture()
def priv_sep_workspace():
    mgr = LinuxWorkspaceManager(
        sandbox_root=_SPIKE_SANDBOX_ROOT,
        owner_uid=RUNNER_IDENTITY.uid,
        owner_gid=RUNNER_IDENTITY.gid,
    )
    session_id = f"pactest-{uuid.uuid4().hex[:8]}"
    session = mgr.create_session(session_id)
    yield mgr, session
    shutil.rmtree(session.workspace_path, ignore_errors=True)


@pytest.fixture()
def denied_fixture(priv_sep_workspace):
    """vault/report.txt with correct file mode (0644) but vault itself missing
    the execute/traverse bit — the exact Golden Topic #1 scenario."""
    mgr, session = priv_sep_workspace
    vault_path = mgr.make_directory(session, "vault")
    report_path = mgr.write_file(session, "vault/report.txt", "secret content\n")
    os.chown(vault_path, RUNNER_IDENTITY.uid, RUNNER_IDENTITY.gid)
    os.chown(report_path, RUNNER_IDENTITY.uid, RUNNER_IDENTITY.gid)
    os.chmod(report_path, 0o644)
    os.chmod(vault_path, 0o600)
    return mgr, session


class TestRealAccessCheckWithRunnerIdentity:

    def test_denied_scenario_passes_when_expected_false(self, denied_fixture):
        mgr, session = denied_fixture
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("vault/report.txt", False, "EACCES"))
        assert result.passed, result.detail

    def test_allowed_scenario_passes_when_expected_true(self, denied_fixture):
        mgr, session = denied_fixture
        os.chmod(os.path.join(session.workspace_path, "vault"), 0o700)
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("vault/report.txt", True))
        assert result.passed, result.detail

    def test_mismatch_fails_when_expected_true_but_actually_denied(self, denied_fixture):
        mgr, session = denied_fixture
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("vault/report.txt", True))
        assert not result.passed
        assert result.failure_reason == "linux.access_condition_mismatch"

    def test_mismatch_fails_when_expected_false_but_actually_allowed(self, denied_fixture):
        mgr, session = denied_fixture
        os.chmod(os.path.join(session.workspace_path, "vault"), 0o700)
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("vault/report.txt", False, "EACCES"))
        assert not result.passed
        assert result.failure_reason == "linux.access_condition_mismatch"


class TestFailClosedNeverChecksAsRoot:

    def test_no_cmd_executor_fails_closed(self, priv_sep_workspace):
        mgr, session = priv_sep_workspace
        svc = LinuxVerifierService(mgr)  # no cmd_executor at all
        result = svc.check(session.session_id, _access_tmpl("nonexistent.txt", True))
        assert not result.passed
        assert result.failure_reason == "linux.access_check_requires_runner"

    def test_cmd_executor_without_runner_uid_fails_closed(self, priv_sep_workspace):
        mgr, session = priv_sep_workspace
        exe = LinuxCommandExecutor(timeout_seconds=5)  # no runner_uid — old root behavior
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("nonexistent.txt", True))
        assert not result.passed
        assert result.failure_reason == "linux.access_check_requires_runner"

    def test_root_runner_uid_zero_fails_closed(self, priv_sep_workspace):
        mgr, session = priv_sep_workspace
        exe = LinuxCommandExecutor(timeout_seconds=5, runner_uid=0, runner_gid=0)
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("nonexistent.txt", True))
        assert not result.passed
        assert result.failure_reason == "linux.access_check_requires_runner"


class TestPathSafetyStillEnforced:

    def test_traversal_path_rejected(self, denied_fixture):
        mgr, session = denied_fixture
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("../../../etc/passwd", False, "EACCES"))
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_symlink_at_target_rejected(self, denied_fixture):
        mgr, session = denied_fixture
        link_path = os.path.join(session.workspace_path, "evil_link")
        os.symlink("/etc/passwd", link_path)
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("evil_link", True))
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_absolute_path_rejected(self, denied_fixture):
        mgr, session = denied_fixture
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("/etc/passwd", False, "EACCES"))
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_sibling_session_path_rejected(self, denied_fixture):
        """A path that escapes to a sibling session's workspace (same runner
        UID owns every session — isolation must come from path containment,
        not OS user separation) must never be treated as a valid check."""
        mgr, session = denied_fixture
        sibling = mgr.create_session(f"sibling-{uuid.uuid4().hex[:8]}")
        try:
            escape_path = os.path.join("..", os.path.basename(sibling.workspace_path), "x")
            exe = LinuxCommandExecutor(
                timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
            )
            svc = LinuxVerifierService(mgr, cmd_executor=exe)
            result = svc.check(session.session_id, _access_tmpl(escape_path, False, "EACCES"))
            assert not result.passed
            assert result.failure_reason == "linux.path_escape"
        finally:
            shutil.rmtree(sibling.workspace_path, ignore_errors=True)

    def test_enoent_never_treated_as_eacces_match(self, denied_fixture):
        """A nonexistent path must fail closed (inconclusive), never be
        silently treated as a successful expected_access=False/EACCES match —
        ENOENT and EACCES are different failure modes and must not be conflated."""
        mgr, session = denied_fixture
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        svc = LinuxVerifierService(mgr, cmd_executor=exe)
        result = svc.check(session.session_id, _access_tmpl("does/not/exist.txt", False, "EACCES"))
        assert not result.passed
        assert result.failure_reason == "linux.access_check_inconclusive"


class TestStaticValidatorSchemaChecks:

    def _draft_with_verify(self, lv: LinuxVerifyTemplate):
        from tests.test_labgen_linux_domain_schema import _linux_lab_draft, _linux_step
        return _linux_lab_draft(steps=[_linux_step(linux_verify=[lv])])

    def test_missing_access_operation_rejected(self):
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.models import ValidatorStatus

        draft = self._draft_with_verify(LinuxVerifyTemplate(
            verify_id="v1",
            type=LinuxVerifyType.LINUX_PATH_ACCESS_CONDITION,
            target_path="a.txt",
            expected_access=True,
        ))
        results = StaticValidator().validate(draft)
        assert any(
            r.check_id == "linux.verifiers_safe" and r.status == ValidatorStatus.FAILED and "access_operation" in r.message
            for r in results
        )

    def test_missing_expected_access_rejected(self):
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.models import ValidatorStatus

        draft = self._draft_with_verify(LinuxVerifyTemplate(
            verify_id="v1",
            type=LinuxVerifyType.LINUX_PATH_ACCESS_CONDITION,
            target_path="a.txt",
            access_operation="read_file",
        ))
        results = StaticValidator().validate(draft)
        assert any(
            r.check_id == "linux.verifiers_safe" and r.status == ValidatorStatus.FAILED and "expected_access" in r.message
            for r in results
        )

    def test_expected_false_without_eacces_errno_rejected(self):
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.models import ValidatorStatus

        draft = self._draft_with_verify(LinuxVerifyTemplate(
            verify_id="v1",
            type=LinuxVerifyType.LINUX_PATH_ACCESS_CONDITION,
            target_path="a.txt",
            access_operation="read_file",
            expected_access=False,
            expected_errno="ENOENT",
        ))
        results = StaticValidator().validate(draft)
        assert any(
            r.check_id == "linux.verifiers_safe" and r.status == ValidatorStatus.FAILED and "expected_errno" in r.message
            for r in results
        )

    def test_valid_path_access_condition_passes_static_validator(self):
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.models import ValidatorStatus

        draft = self._draft_with_verify(LinuxVerifyTemplate(
            verify_id="v1",
            type=LinuxVerifyType.LINUX_PATH_ACCESS_CONDITION,
            target_path="a.txt",
            access_operation="read_file",
            expected_access=False,
            expected_errno="EACCES",
        ))
        results = StaticValidator().validate(draft)
        verifiers_safe = [r for r in results if r.check_id == "linux.verifiers_safe"]
        assert verifiers_safe and all(r.status == ValidatorStatus.PASSED for r in verifiers_safe)
