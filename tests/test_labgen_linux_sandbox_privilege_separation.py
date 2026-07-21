"""
Real privilege-separation verification for the Linux sandbox executor.

Bug (see docs/labgen/linux/LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED_v0.1.md): the
Linux command executor previously ran learner commands under the same UID as
the root API process, so root's CAP_DAC_OVERRIDE bypassed the exact directory
execute/traverse permission check the "chmod despite correct mode" Golden
Topic depends on — proven with a live subprocess.run() reproduction that read
a file through a directory with its execute bit removed, with returncode 0.

Fix: LinuxCommandExecutor(runner_uid=..., runner_gid=...) drops privileges via
native subprocess.Popen user=/group=/extra_groups=/umask= kwargs (Python 3.9+,
implemented in C — no preexec_fn, deliberately avoided since this executor is
called via run_in_executor from a thread pool, where preexec_fn's fork-safety
warnings are a real risk here, not a hypothetical one).

These tests use the exact same production code path
(LinuxWorkspaceManager + LinuxCommandExecutor wired with the real installed
labgen-linux-runner system account), not a raw `sudo -u` shell-out — this is
the scenario the runtime blocked-gate result explicitly asked to be proven
with production-equivalent code, not a separate manual check.
"""

from __future__ import annotations

import os
import shutil
import uuid

import pytest

from backend.labgen.linux_command_executor import LinuxCommandExecutor
from backend.labgen.linux_runner_identity import resolve_runner_identity
from backend.labgen.linux_workspace import _SPIKE_SANDBOX_ROOT, LinuxWorkspaceManager

pytestmark = pytest.mark.static

RUNNER_IDENTITY = resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")


@pytest.fixture()
def priv_sep_workspace():
    """A real session workspace, chowned to the runner identity — mirrors
    exactly what LinuxRuntimeAdapter wires in production."""
    mgr = LinuxWorkspaceManager(
        sandbox_root=_SPIKE_SANDBOX_ROOT,
        owner_uid=RUNNER_IDENTITY.uid,
        owner_gid=RUNNER_IDENTITY.gid,
    )
    session_id = f"privtest-{uuid.uuid4().hex[:8]}"
    session = mgr.create_session(session_id)
    yield mgr, session
    shutil.rmtree(session.workspace_path, ignore_errors=True)


class TestWorkspaceOwnership:

    def test_workspace_directory_owned_by_runner_not_root(self, priv_sep_workspace):
        mgr, session = priv_sep_workspace
        st = os.stat(session.workspace_path)
        assert st.st_uid == RUNNER_IDENTITY.uid
        assert st.st_gid == RUNNER_IDENTITY.gid
        assert st.st_uid != 0

    def test_workspace_without_owner_uid_stays_root_owned(self):
        # Back-compat: existing callers that don't pass owner_uid/gid keep
        # the old root-owned behavior — this is what every pre-existing test
        # in test_labgen_linux_runtime_adapter_spike.py relies on.
        mgr = LinuxWorkspaceManager(sandbox_root=_SPIKE_SANDBOX_ROOT)
        session_id = f"privtest-nochown-{uuid.uuid4().hex[:8]}"
        session = mgr.create_session(session_id)
        try:
            st = os.stat(session.workspace_path)
            assert st.st_uid == os.getuid()
        finally:
            shutil.rmtree(session.workspace_path, ignore_errors=True)


class TestExecutorRealPrivilegeDrop:

    def test_learner_command_effective_uid_is_runner_not_root(self, priv_sep_workspace):
        # `touch` creates a NEW file — its owner reflects the identity of the
        # process that created it, which is a real process-identity probe
        # (unlike `stat`'ing a pre-existing path, which only reports that
        # path's ownership metadata regardless of who is running `stat`).
        mgr, session = priv_sep_workspace
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        result = exe.execute(["touch", "created_by_runner.txt"], session.workspace_path)
        assert not result.policy_rejected
        created = os.stat(os.path.join(session.workspace_path, "created_by_runner.txt"))
        assert created.st_uid == RUNNER_IDENTITY.uid
        assert created.st_uid != 0

    def test_learner_command_without_runner_uid_stays_root(self):
        # Back-compat: existing tests construct LinuxCommandExecutor() with
        # no runner_uid at all and must keep working exactly as before.
        base = os.path.join(_SPIKE_SANDBOX_ROOT, f"privtest-nochown-{uuid.uuid4().hex[:8]}")
        os.makedirs(base, mode=0o700, exist_ok=True)
        try:
            exe = LinuxCommandExecutor(timeout_seconds=5)
            result = exe.execute(["touch", "created_by_process.txt"], base)
            assert not result.policy_rejected
            created = os.stat(os.path.join(base, "created_by_process.txt"))
            assert created.st_uid == 0  # root — old, unchanged behavior
        finally:
            shutil.rmtree(base, ignore_errors=True)


class TestRealEaccesReproduction:
    """The exact fixture and reproduction chain required by the Golden Lab #1
    Sandbox Privilege Separation brief §六 — using the production executor
    path, not a manual `sudo -u` shell-out."""

    def test_directory_missing_execute_bit_produces_real_eacces(self, priv_sep_workspace):
        mgr, session = priv_sep_workspace
        vault_path = mgr.make_directory(session, "vault")
        report_path = mgr.write_file(session, "vault/report.txt", "secret content\n")
        os.chown(vault_path, RUNNER_IDENTITY.uid, RUNNER_IDENTITY.gid)
        os.chown(report_path, RUNNER_IDENTITY.uid, RUNNER_IDENTITY.gid)
        os.chmod(report_path, 0o644)
        os.chmod(vault_path, 0o600)  # no execute/traverse bit for anyone, including owner

        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )

        # 1. effective identity is the runner, not root — proven by
        #    TestExecutorRealPrivilegeDrop.test_learner_command_effective_uid_is_runner_not_root
        #    via a real `touch`-created file's ownership (see that test's
        #    docstring for why `stat` on a pre-existing path is the wrong
        #    probe for process identity).

        # 2 & 3. real kernel EACCES, not a simulated/hand-written error string.
        result = exe.execute(["cat", "vault/report.txt"], session.workspace_path)
        assert not result.policy_rejected
        assert result.returncode != 0, (
            "cat succeeded despite vault/ lacking execute bit — privilege "
            "separation is not actually in effect"
        )
        assert "Permission denied" in result.stderr

        # 4. file's own mode is untouched and was already correct.
        assert oct(os.stat(report_path).st_mode & 0o777) == oct(0o644)

        # 5. re-chmod'ing the file itself does not fix access (root cause is
        #    the parent directory, not the file).
        exe.execute(["chmod", "644", "vault/report.txt"], session.workspace_path)
        still_failing = exe.execute(["cat", "vault/report.txt"], session.workspace_path)
        assert still_failing.returncode != 0

        # 6. fixing the actual root cause (parent directory execute bit)
        #    restores real access under the same non-root identity.
        os.chmod(vault_path, 0o700)
        fixed = exe.execute(["cat", "vault/report.txt"], session.workspace_path)
        assert fixed.returncode == 0
        assert "secret content" in fixed.stdout

    def test_root_bypasses_the_same_fixture_confirming_the_original_bug(self, priv_sep_workspace):
        """Negative control: without runner_uid (the old behavior), the exact
        same fixture does NOT deny access — this is the original bug,
        preserved here as a regression guard so nobody accidentally "fixes"
        it back to root without this test failing loudly."""
        mgr, session = priv_sep_workspace
        vault_path = mgr.make_directory(session, "vault")
        report_path = mgr.write_file(session, "vault/report.txt", "secret content\n")
        os.chmod(report_path, 0o644)
        os.chmod(vault_path, 0o600)

        exe = LinuxCommandExecutor(timeout_seconds=5)  # no runner_uid = old root behavior
        result = exe.execute(["cat", "vault/report.txt"], session.workspace_path)
        assert result.returncode == 0, "expected root's CAP_DAC_OVERRIDE to bypass the check"
