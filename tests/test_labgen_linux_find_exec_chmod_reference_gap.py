"""
Regression tests for a real security gap found during the Golden Lab #1
security preflight (CEO brief: "Linux Golden Lab #1 Production").

_check_path_arg() in linux_command_executor.py explicitly skips any argument
starting with "-" (treating it as an opaque option flag), so `find`'s
`-exec`/`-execdir`/`-ok`/`-okdir` clauses and `chmod --reference=FILE` were
never inspected. The `+`-terminated form of `-exec`/`-execdir` doesn't
require a `;` argument at all, so it doesn't even trip the shell-metachar
check — it runs an arbitrary allowlisted-looking command as the runner
identity, completely defeating ALLOWED_COMMANDS/DENIED_COMMANDS.

Fix: _check_policy() rejects `find` argv containing a bare
`-exec`/`-execdir`/`-ok`/`-okdir` token, and `chmod` argv containing any
`--reference`/`--reference=...` argument.
"""

import os

import pytest

pytestmark = pytest.mark.static


@pytest.fixture
def sbox(tmp_path):
    return str(tmp_path)


class TestFindIndirectExecutionBlocked:

    def test_find_exec_plus_terminator_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["find", ".", "-name", "x", "-exec", "echo", "PWNED", "+"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "find_indirect_execution_denied"

    def test_find_execdir_plus_terminator_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["find", ".", "-execdir", "cat", "secret.txt", "+"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "find_indirect_execution_denied"

    def test_find_ok_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["find", ".", "-ok", "echo", "hi"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "find_indirect_execution_denied"

    def test_find_okdir_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["find", ".", "-okdir", "echo", "hi"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "find_indirect_execution_denied"

    def test_plain_find_still_allowed(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        with open(os.path.join(sbox, "a.txt"), "w") as f:
            f.write("x")
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["find", ".", "-name", "a.txt"], sbox)
        assert not result.policy_rejected
        assert result.returncode == 0


class TestChmodReferenceBlocked:

    def test_chmod_reference_equals_form_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        with open(os.path.join(sbox, "f.txt"), "w") as f:
            f.write("x")
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["chmod", "--reference=/etc/passwd", "f.txt"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "chmod_reference_denied"

    def test_chmod_reference_bare_form_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        with open(os.path.join(sbox, "f.txt"), "w") as f:
            f.write("x")
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["chmod", "--reference", "/etc/passwd", "f.txt"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "chmod_reference_denied"

    def test_plain_chmod_still_allowed(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        with open(os.path.join(sbox, "f.txt"), "w") as f:
            f.write("x")
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["chmod", "600", "f.txt"], sbox)
        assert not result.policy_rejected
        assert result.returncode == 0
