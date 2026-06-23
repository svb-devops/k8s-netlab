"""
Tests for Linux Runtime Adapter Spike v0.1 (Task 2 of 7).

Coverage:
A. LinuxWorkspaceManager — create, path safety, file ops, cleanup
B. LinuxCommandExecutor — allowlist, deny list, path policy, execution
C. LinuxCleanupAdapter — cleanup, residual scan, forbidden roots, taint
D. LinuxRuntimeAdapter — session lifecycle, spike scenario, negative tests
E. NamespaceAdapterKind.LINUX — selection, production rejection, build
F. LinuxContainerLifecycleAdapter — skeleton, NotImplementedError
G. Regression — K8s path unchanged, Linux publish still blocked
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid

import pytest

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Fixtures — use the allowed spike sandbox root, not pytest tmp_path
# (tmp_path is under /tmp which is a forbidden root for custom sandbox_roots;
#  /tmp/labgen-linux-sandboxes is the explicitly allowed exception)
# ---------------------------------------------------------------------------


@pytest.fixture()
def sbox(request):
    """Per-test sandbox directory under /tmp/labgen-linux-sandboxes."""
    from backend.labgen.linux_workspace import _SPIKE_SANDBOX_ROOT
    base = os.path.join(_SPIKE_SANDBOX_ROOT, f"pytest-{uuid.uuid4().hex[:8]}")
    os.makedirs(base, mode=0o700, exist_ok=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(sandbox_root: str) -> object:
    """Return an enabled LinuxRuntimeAdapter backed by sandbox_root."""
    from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
    return LinuxRuntimeAdapter(enabled=True, sandbox_root=sandbox_root)


# ---------------------------------------------------------------------------
# A. LinuxWorkspaceManager
# ---------------------------------------------------------------------------


class TestLinuxWorkspaceManager:

    def test_create_session_returns_valid_session(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("abc-123")
        assert session.session_id == "abc-123"
        assert os.path.isdir(session.workspace_path)
        assert session.workspace_path.startswith(sbox)
        assert session.is_active()

    def test_create_session_auto_uuid_when_none(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        s = mgr.create_session()
        assert s.session_id  # non-empty
        assert os.path.isdir(s.workspace_path)

    def test_reject_unsafe_session_id_slash(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager, WorkspaceError
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        with pytest.raises(WorkspaceError):
            mgr.create_session("../escape")

    def test_reject_empty_session_id(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager, WorkspaceError
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        with pytest.raises(WorkspaceError):
            mgr.create_session("")

    def test_resolve_path_allows_subpath(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s1")
        resolved = mgr.resolve_path(session, "demo/file.txt")
        assert resolved.startswith(session.workspace_path)
        assert "demo/file.txt" in resolved

    def test_resolve_path_rejects_dotdot(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager, WorkspacePathEscapeError
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s2")
        with pytest.raises(WorkspacePathEscapeError) as exc_info:
            mgr.resolve_path(session, "../escape.txt")
        assert "traversal" in str(exc_info.value).lower()

    def test_resolve_path_rejects_absolute(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager, WorkspacePathEscapeError
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s3")
        with pytest.raises(WorkspacePathEscapeError) as exc_info:
            mgr.resolve_path(session, "/etc/passwd")
        assert "absolute" in str(exc_info.value).lower()

    def test_resolve_path_rejects_empty(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager, WorkspacePathEscapeError
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s4")
        with pytest.raises(WorkspacePathEscapeError):
            mgr.resolve_path(session, "")

    def test_write_and_read_file(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s5")
        mgr.write_file(session, "hello.txt", "hello labgen\n")
        content = mgr.read_file(session, "hello.txt")
        assert content == "hello labgen\n"

    def test_chmod_and_stat_mode(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s6")
        mgr.write_file(session, "secret.txt", "x")
        mgr.chmod_file(session, "secret.txt", 0o600)
        mode = mgr.stat_mode(session, "secret.txt")
        assert mode == "600"

    def test_make_directory(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s7")
        abs_path = mgr.make_directory(session, "subdir/nested")
        assert os.path.isdir(abs_path)

    def test_file_exists_true_false(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s8")
        assert not mgr.file_exists(session, "nope.txt")
        mgr.write_file(session, "yes.txt", "y")
        assert mgr.file_exists(session, "yes.txt")

    def test_directory_exists(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s9")
        assert not mgr.directory_exists(session, "mydir")
        mgr.make_directory(session, "mydir")
        assert mgr.directory_exists(session, "mydir")

    def test_list_files_recursive(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("s10")
        mgr.write_file(session, "a.txt", "a")
        mgr.write_file(session, "sub/b.txt", "b")
        files = mgr.list_files_recursive(session)
        assert "a.txt" in files
        assert os.path.join("sub", "b.txt") in files

    def test_mark_tainted(self, sbox):
        from backend.labgen.linux_workspace import LinuxWorkspaceManager
        mgr = LinuxWorkspaceManager(sandbox_root=sbox)
        session = mgr.create_session("tainted-1")
        mgr.mark_tainted(session, "test_taint")
        assert session.tainted
        assert session.taint_reason == "test_taint"
        assert session.closed


# ---------------------------------------------------------------------------
# B. LinuxCommandExecutor
# ---------------------------------------------------------------------------


class TestLinuxCommandExecutor:

    def test_allowed_command_ls(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["ls"], sbox)
        assert not result.policy_rejected
        assert result.returncode == 0

    def test_allowed_command_mkdir(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        workspace = sbox
        result = exe.execute(["mkdir", "testdir"], workspace)
        assert not result.policy_rejected
        assert os.path.isdir(os.path.join(workspace, "testdir"))

    def test_allowed_command_cat(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        with open(os.path.join(sbox, "hello.txt"), "w") as f:
            f.write("hello\n")
        result = exe.execute(["cat", "hello.txt"], sbox)
        assert not result.policy_rejected
        assert "hello" in result.stdout

    def test_allowed_command_chmod(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        with open(os.path.join(sbox, "f.txt"), "w") as f:
            f.write("x")
        result = exe.execute(["chmod", "600", "f.txt"], sbox)
        assert not result.policy_rejected
        assert result.returncode == 0

    def test_allowed_command_stat(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        fpath = os.path.join(sbox, "f.txt")
        with open(fpath, "w") as f:
            f.write("x")
        os.chmod(fpath, 0o600)
        result = exe.execute(["stat", "-c", "%a", "f.txt"], sbox)
        assert not result.policy_rejected
        assert "600" in result.stdout

    def test_denied_sudo(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["sudo", "ls"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "command_denied"

    def test_denied_su(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["su", "-", "root"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "command_denied"

    def test_denied_systemctl(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["systemctl", "restart", "sshd"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "command_denied"

    def test_denied_service(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["service", "nginx", "stop"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "command_denied"

    def test_denied_curl(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["curl", "http://example.com"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "command_denied"

    def test_denied_wget(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["wget", "http://example.com"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "command_denied"

    def test_denied_apt(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["apt", "install", "vim"], sbox)
        assert result.policy_rejected

    def test_denied_pip(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["pip", "install", "requests"], sbox)
        assert result.policy_rejected

    def test_denied_bash(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["bash", "-c", "id"], sbox)
        assert result.policy_rejected

    def test_unknown_command_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["unknowncmd123"], sbox)
        assert result.policy_rejected
        assert result.rejection_reason == "command_not_allowed"

    def test_path_traversal_in_arg_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["cat", "../../../etc/passwd"], sbox)
        assert result.policy_rejected
        assert "traversal" in result.rejection_reason

    def test_forbidden_absolute_path_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["cat", "/etc/passwd"], sbox)
        assert result.policy_rejected
        assert "forbidden_path" in result.rejection_reason or "absolute" in result.rejection_reason

    def test_shell_metachar_semicolon_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute(["ls", ";", "rm", "-rf", "/"], sbox)
        assert result.policy_rejected
        assert "metachar" in result.rejection_reason

    def test_empty_argv_rejected(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor()
        result = exe.execute([], sbox)
        assert result.policy_rejected

    def test_max_output_bytes_enforced(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        with open(os.path.join(sbox, "big.txt"), "w") as f:
            f.write("x" * 1000)
        exe = LinuxCommandExecutor(timeout_seconds=5, max_output_bytes=100)
        result = exe.execute(["cat", "big.txt"], sbox)
        assert not result.policy_rejected
        assert len(result.stdout) <= 100

    def test_pwd_returns_workspace(self, sbox):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        exe = LinuxCommandExecutor(timeout_seconds=5)
        result = exe.execute(["pwd"], sbox)
        assert not result.policy_rejected
        assert sbox in result.stdout


# ---------------------------------------------------------------------------
# C. LinuxCleanupAdapter
# ---------------------------------------------------------------------------


class TestLinuxCleanupAdapter:

    def test_cleanup_removes_workspace(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        workspace = os.path.join(sbox, "session-1")
        os.makedirs(workspace)
        with open(os.path.join(workspace, "file.txt"), "w") as f:
            f.write("hello")
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        result = adapter.cleanup(workspace)
        assert result.success
        assert not os.path.exists(workspace)

    def test_cleanup_idempotent_when_already_gone(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        workspace = os.path.join(sbox, "gone-session")
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        result = adapter.cleanup(workspace)
        assert result.success

    def test_cleanup_rejects_root(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        result = adapter.cleanup("/")
        assert not result.success
        assert "forbidden" in result.failure_reason or "outside" in result.failure_reason

    def test_cleanup_rejects_etc(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        result = adapter.cleanup("/etc")
        assert not result.success

    def test_cleanup_rejects_home_toplevel(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        result = adapter.cleanup("/home")
        assert not result.success

    def test_cleanup_rejects_outside_sandbox_root(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        # Use an absolute path that is clearly outside sbox
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        outside_path = "/usr/local/labgen-test-outside"
        result = adapter.cleanup(outside_path)
        assert not result.success
        assert "outside" in result.failure_reason

    def test_residual_scan_no_residual(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        workspace = os.path.join(sbox, "clean-session")
        os.makedirs(workspace)
        shutil.rmtree(workspace)
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        scan = adapter.residual_scan(workspace)
        assert not scan.has_residual
        assert not scan.exists

    def test_residual_scan_detects_leftover_file(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        workspace = os.path.join(sbox, "dirty-session")
        os.makedirs(workspace)
        with open(os.path.join(workspace, "leftover.txt"), "w") as f:
            f.write("oops")
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        scan = adapter.residual_scan(workspace)
        assert scan.has_residual
        assert scan.exists
        assert "leftover.txt" in scan.residual_files


# ---------------------------------------------------------------------------
# D. LinuxRuntimeAdapter — session lifecycle + spike scenario
# ---------------------------------------------------------------------------


class TestLinuxRuntimeAdapterDisabledByDefault:

    def test_disabled_by_default(self, sbox):
        from backend.labgen.linux_runtime_adapter import (
            LinuxRuntimeAdapter,
            LinuxSpikeDisabledError,
        )
        adapter = LinuxRuntimeAdapter(enabled=False, sandbox_root=sbox)
        with pytest.raises(LinuxSpikeDisabledError):
            adapter.create_session("disabled-session")


class TestLinuxRuntimeAdapterSessionLifecycle:

    def test_create_session(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter, LinuxSpikeStatus
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        state = adapter.create_session("session-1")
        assert state.session_id == "session-1"
        assert state.status == LinuxSpikeStatus.ACTIVE
        assert os.path.isdir(state.workspace_path)

    def test_duplicate_session_id_raises(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        adapter.create_session("dup-id")
        with pytest.raises(ValueError):
            adapter.create_session("dup-id")

    def test_close_session_cleanup_verified(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter, LinuxSpikeStatus
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        state = adapter.create_session("close-1")
        workspace = state.workspace_path
        result = adapter.close_session("close-1")
        assert result.success
        state_after = adapter.get_session("close-1")
        assert state_after.cleanup_verified
        assert state_after.status == LinuxSpikeStatus.CLOSED
        assert not os.path.exists(workspace)

    def test_close_session_idempotent(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter, LinuxSpikeStatus
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        adapter.create_session("idem-1")
        adapter.close_session("idem-1")
        r2 = adapter.close_session("idem-1")
        assert r2.success
        assert adapter.get_session("idem-1").status == LinuxSpikeStatus.CLOSED

    def test_policy_allow_root_false_enforced(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        from backend.labgen.models import LinuxSandboxPolicy
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        # allow_root is a Pydantic field_validator that cannot be set to True
        # Try constructing with allow_root=True — should raise Pydantic validation error
        with pytest.raises(Exception):
            LinuxSandboxPolicy(
                workspace_root="/home/learner/workspace",
                allow_root=True,
            )

    def test_policy_allow_network_false_enforced(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        from backend.labgen.models import LinuxSandboxPolicy
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        with pytest.raises(Exception):
            LinuxSandboxPolicy(
                workspace_root="/home/learner/workspace",
                allow_network=True,
            )


class TestLinuxSpikeScenario:
    """Full spike scenario: Linux Files and Permissions workspace smoke."""

    def test_full_spike_scenario(self, sbox):
        """
        Spike scenario:
        1. Create sandbox session
        2. mkdir -p demo (via Python API)
        3. echo "hello labgen" > demo/message.txt (via write_file)
        4. cat demo/message.txt → verify content
        5. chmod 600 demo/message.txt
        6. stat → verify mode 600
        7. file_exists checks
        8. close session → cleanup
        9. residual scan → 0 files
        """
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter, LinuxSpikeStatus

        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        session = adapter.create_session("spike-scenario-001")

        # Step 2: mkdir -p demo
        adapter.make_directory("spike-scenario-001", "demo")
        assert adapter.directory_exists("spike-scenario-001", "demo")

        # Step 3: write file (echo > redirect equivalent)
        adapter.write_file("spike-scenario-001", "demo/message.txt", "hello labgen\n")
        assert adapter.file_exists("spike-scenario-001", "demo/message.txt")

        # Step 4: cat file — verify content
        content = adapter.read_file("spike-scenario-001", "demo/message.txt")
        assert content == "hello labgen\n"

        # Step 5: chmod 600
        adapter.chmod_file("spike-scenario-001", "demo/message.txt", 0o600)

        # Step 6: stat — verify mode
        mode = adapter.stat_mode("spike-scenario-001", "demo/message.txt")
        assert mode == "600"

        # Step 7: subprocess ls (allowed command)
        result = adapter.execute_command("spike-scenario-001", ["ls", "demo"])
        assert not result.policy_rejected
        assert "message.txt" in result.stdout

        # Step 8: close session → cleanup
        workspace_path = session.workspace_path
        cleanup = adapter.close_session("spike-scenario-001")
        assert cleanup.success

        # Step 9: residual scan → 0
        state = adapter.get_session("spike-scenario-001")
        assert state.cleanup_verified
        assert state.status == LinuxSpikeStatus.CLOSED
        assert not os.path.exists(workspace_path)

    def test_negative_sudo_rejected(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        adapter.create_session("neg-sudo")
        result = adapter.execute_command("neg-sudo", ["sudo", "ls"])
        assert result.policy_rejected
        assert result.rejection_reason == "command_denied"

    def test_negative_network_tool_rejected(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        adapter.create_session("neg-curl")
        result = adapter.execute_command("neg-curl", ["curl", "http://example.com"])
        assert result.policy_rejected

    def test_negative_path_escape_rejected(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        adapter.create_session("neg-path")
        result = adapter.execute_command("neg-path", ["cat", "../../../etc/passwd"])
        assert result.policy_rejected

    def test_negative_forbidden_absolute_path(self, sbox):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        adapter.create_session("neg-abs")
        result = adapter.execute_command("neg-abs", ["cat", "/etc/passwd"])
        assert result.policy_rejected

    def test_negative_cleanup_root_rejected(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        adapter = LinuxCleanupAdapter(sandbox_root=sbox)
        result = adapter.cleanup("/")
        assert not result.success

    def test_negative_cleanup_outside_workspace(self, sbox):
        from backend.labgen.linux_cleanup import LinuxCleanupAdapter
        adapter = LinuxCleanupAdapter(sandbox_root="/tmp/labgen-linux-sandboxes")
        result = adapter.cleanup("/usr/local/labgen-outside-test")
        assert not result.success

    def test_taint_on_cleanup_failure(self, sbox, monkeypatch):
        """Simulate cleanup failure → session must be tainted."""
        from backend.labgen.linux_cleanup import CleanupResult, LinuxCleanupAdapter
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter, LinuxSpikeStatus

        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        state = adapter.create_session("taint-fail-1")

        # Monkeypatch cleanup to fail
        def _fail_cleanup(workspace_path: str) -> CleanupResult:
            return CleanupResult(
                workspace_path=workspace_path,
                success=False,
                failure_reason="simulated_rmtree_failure",
            )
        monkeypatch.setattr(adapter._cleanup_adapter, "cleanup", _fail_cleanup)

        result = adapter.close_session("taint-fail-1")
        assert not result.success
        assert not state.cleanup_verified
        assert state.tainted
        assert state.taint_reason == "simulated_rmtree_failure"
        assert state.status == LinuxSpikeStatus.CLEANUP_FAILED

    def test_session_not_found_raises(self, sbox):
        from backend.labgen.linux_runtime_adapter import (
            LinuxRuntimeAdapter,
            LinuxSpikeSessionNotFoundError,
        )
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        with pytest.raises(LinuxSpikeSessionNotFoundError):
            adapter.get_session("nonexistent")

    def test_execute_on_closed_session_raises(self, sbox):
        from backend.labgen.linux_runtime_adapter import (
            LinuxRuntimeAdapter,
            LinuxSpikeSessionNotActiveError,
        )
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)
        adapter.create_session("closed-cmd")
        adapter.close_session("closed-cmd")
        with pytest.raises(LinuxSpikeSessionNotActiveError):
            adapter.execute_command("closed-cmd", ["ls"])


# ---------------------------------------------------------------------------
# E. NamespaceAdapterKind.LINUX — selection logic
# ---------------------------------------------------------------------------


class TestNamespaceAdapterKindLinux:

    def test_linux_kind_exists(self):
        from backend.labgen.runtime_adapter_selection import NamespaceAdapterKind
        assert NamespaceAdapterKind.LINUX.value == "linux"

    def test_select_linux_in_test_mode_gives_warning_not_blocking(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select("test", "linux")
        blocking = [i for i in result.issues if i.severity == "blocking"]
        warnings = [i for i in result.issues if i.severity == "warning"]
        assert not blocking
        assert warnings  # NON_PRODUCTION_STUB_ALLOWED warning

    def test_select_linux_in_dev_mode_gives_warning(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select("dev", "linux")
        assert any(i.severity == "warning" for i in result.issues)
        assert not any(i.severity == "blocking" for i in result.issues)

    def test_select_linux_in_home_lab_mvp_is_blocking(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select("home_lab_mvp", "linux")
        blocking = [i for i in result.issues if i.severity == "blocking"]
        assert blocking
        assert not result.production_safe

    def test_select_linux_in_production_is_blocking(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select("production", "linux")
        blocking = [i for i in result.issues if i.severity == "blocking"]
        assert blocking
        assert not result.production_safe

    def test_select_linux_in_cloud_is_blocking(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select("cloud", "linux")
        blocking = [i for i in result.issues if i.severity == "blocking"]
        assert blocking
        assert not result.production_safe

    def test_linux_production_safe_always_false(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        for mode in ["test", "dev", "demo", "home_lab_mvp", "cloud", "production"]:
            result = RuntimeAdapterSelectionService.select(mode, "linux")
            assert not result.production_safe, f"production_safe must be False for mode={mode}"

    def test_build_adapter_linux_returns_linux_adapter(self):
        from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
        from backend.labgen.runtime_adapter_selection import (
            NamespaceAdapterKind,
            RuntimeAdapterSelectionResult,
            RuntimeAdapterSelectionService,
            RuntimeMode,
        )
        result = RuntimeAdapterSelectionResult(
            runtime_mode=RuntimeMode.TEST,
            namespace_adapter_kind=NamespaceAdapterKind.LINUX,
            production_safe=False,
        )
        adapter = RuntimeAdapterSelectionService.build_adapter(result)
        assert isinstance(adapter, LinuxContainerLifecycleAdapter)

    def test_build_adapter_linux_in_production_raises(self):
        """LINUX adapter must raise RuntimeError in production-like modes, not silently return broken adapter."""
        from backend.labgen.runtime_adapter_selection import (
            NamespaceAdapterKind,
            RuntimeAdapterSelectionResult,
            RuntimeAdapterSelectionService,
            RuntimeMode,
        )
        for prod_mode in [RuntimeMode.HOME_LAB_MVP, RuntimeMode.PRODUCTION, RuntimeMode.CLOUD]:
            result = RuntimeAdapterSelectionResult(
                runtime_mode=prod_mode,
                namespace_adapter_kind=NamespaceAdapterKind.LINUX,
                production_safe=False,
            )
            with pytest.raises(RuntimeError, match="not production-ready"):
                RuntimeAdapterSelectionService.build_adapter(result)

    def test_k8s_selection_unchanged_by_linux_addition(self):
        from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select("test", "stub")
        adapter = RuntimeAdapterSelectionService.build_adapter(result)
        assert isinstance(adapter, StubNamespaceLifecycleAdapter)


# ---------------------------------------------------------------------------
# F. LinuxContainerLifecycleAdapter skeleton
# ---------------------------------------------------------------------------


class TestLinuxContainerLifecycleAdapter:

    def test_instantiation_succeeds(self):
        from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
        adapter = LinuxContainerLifecycleAdapter()
        assert adapter is not None

    def test_create_namespace_raises_not_implemented(self):
        from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
        adapter = LinuxContainerLifecycleAdapter()
        with pytest.raises(NotImplementedError):
            adapter.create_namespace("lab-test")

    def test_namespace_exists_raises_not_implemented(self):
        from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
        adapter = LinuxContainerLifecycleAdapter()
        with pytest.raises(NotImplementedError):
            adapter.namespace_exists("lab-test")

    def test_delete_namespace_raises_not_implemented(self):
        from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
        adapter = LinuxContainerLifecycleAdapter()
        with pytest.raises(NotImplementedError):
            adapter.delete_namespace("lab-test")

    def test_is_namespace_deleted_raises_not_implemented(self):
        from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
        adapter = LinuxContainerLifecycleAdapter()
        with pytest.raises(NotImplementedError):
            adapter.is_namespace_deleted("lab-test")

    def test_ensure_verifier_rolebinding_raises_not_implemented(self):
        from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
        adapter = LinuxContainerLifecycleAdapter()
        with pytest.raises(NotImplementedError):
            adapter.ensure_verifier_rolebinding("lab-test")

    def test_verifier_rolebinding_exists_raises_not_implemented(self):
        from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
        adapter = LinuxContainerLifecycleAdapter()
        with pytest.raises(NotImplementedError):
            adapter.verifier_rolebinding_exists("lab-test")


# ---------------------------------------------------------------------------
# G. Regression — K8s path unchanged, Linux publish still blocked
# ---------------------------------------------------------------------------


class TestRegressionK8sUnchanged:

    def test_k8s_adapter_kind_unchanged(self):
        from backend.labgen.runtime_adapter_selection import NamespaceAdapterKind
        assert NamespaceAdapterKind.K8S.value == "k8s"
        assert NamespaceAdapterKind.STUB.value == "stub"

    def test_k8s_selection_in_home_lab_mvp_requires_kubeconfig(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select(
            "home_lab_mvp", "k8s", k8s_kubeconfig_path=""
        )
        blocking = [i for i in result.issues if i.severity == "blocking"]
        assert blocking
        assert not result.production_safe

    def test_k8s_selection_in_home_lab_mvp_with_kubeconfig_is_safe(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select(
            "home_lab_mvp", "k8s", k8s_kubeconfig_path="/path/to/kubeconfig"
        )
        blocking = [i for i in result.issues if i.severity == "blocking"]
        assert not blocking
        assert result.production_safe

    def test_stub_in_test_mode_unchanged(self):
        from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
        result = RuntimeAdapterSelectionService.select("test", "stub")
        blocking = [i for i in result.issues if i.severity == "blocking"]
        assert not blocking
        assert not result.production_safe

    def test_linux_publish_gate_lifted_by_static_validator(self):
        """After G-44 gate lift, StaticValidator must NOT block a complete Linux draft."""
        from backend.labgen.models import BlockingLevel, LabDomainType, ValidatorStatus
        from backend.labgen.static_validator import StaticValidator
        from tests.test_labgen_linux_domain_schema import _linux_lab_draft

        draft = _linux_lab_draft()
        assert draft.target_domain == LabDomainType.LINUX

        validator = StaticValidator()
        results = validator.validate(draft)

        # linux.publish_blocked_until_runtime must NOT exist after gate lift
        blocked_check = next(
            (r for r in results if r.check_id == "linux.publish_blocked_until_runtime"), None
        )
        assert blocked_check is None, "linux.publish_blocked_until_runtime must be removed after G-44"
        # And no other blocking failures for a complete Linux draft
        other_blocking = [
            r for r in results
            if r.status == ValidatorStatus.FAILED and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        assert other_blocking == [], f"Unexpected: {[(r.check_id, r.message) for r in other_blocking]}"

    def test_no_linux_lab_in_catalog(self):
        """Linux domain draft cannot be published — catalog remains K8s only."""
        from backend.labgen.models import LabDomainType
        from tests.test_labgen_linux_domain_schema import _linux_lab_draft

        draft = _linux_lab_draft()
        assert draft.target_domain == LabDomainType.LINUX
        # published status cannot be set on Linux draft without bypass
        assert draft.publish_status.value != "published"

    def test_static_validator_allow_root_backstop_via_model_construct(self):
        """Defense-in-depth: StaticValidator.sandbox_safe rejects allow_root=True
        even when constructed via model_construct() bypassing Pydantic validators.
        This guards against future weakening of StaticValidator checks."""
        from backend.labgen.models import (
            BlockingLevel,
            LinuxSandboxPolicy,
            ValidatorStatus,
        )
        from backend.labgen.static_validator import StaticValidator
        from tests.test_labgen_linux_domain_schema import _linux_lab_draft

        # Bypass Pydantic validators using model_construct()
        policy_bypass = LinuxSandboxPolicy.model_construct(
            workspace_root="/home/learner/workspace",
            allow_root=True,
            allow_network=False,
        )
        draft = _linux_lab_draft(sandbox=policy_bypass)
        results = StaticValidator().validate(draft)
        failed_ids = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        # StaticValidator backstop must catch this even when model_construct bypasses validator
        assert "linux.sandbox_safe" in failed_ids

    def test_static_validator_allow_network_backstop_via_model_construct(self):
        """Defense-in-depth: StaticValidator.sandbox_safe rejects allow_network=True
        even when constructed via model_construct() bypassing Pydantic validators."""
        from backend.labgen.models import LinuxSandboxPolicy, ValidatorStatus
        from backend.labgen.static_validator import StaticValidator
        from tests.test_labgen_linux_domain_schema import _linux_lab_draft

        policy_bypass = LinuxSandboxPolicy.model_construct(
            workspace_root="/home/learner/workspace",
            allow_root=False,
            allow_network=True,
        )
        draft = _linux_lab_draft(sandbox=policy_bypass)
        results = StaticValidator().validate(draft)
        failed_ids = {r.check_id for r in results if r.status == ValidatorStatus.FAILED}
        assert "linux.sandbox_safe" in failed_ids

    def test_command_executor_sibling_session_prefix_confusion_rejected(self, sbox):
        """Sibling session path /sandbox/session-abc-evil must NOT match session-abc workspace."""
        from backend.labgen.linux_command_executor import LinuxCommandExecutor

        workspace_abc = os.path.join(sbox, "session-abc")
        os.makedirs(workspace_abc)

        # Create sibling directory that shares prefix with session-abc
        sibling_evil = os.path.join(sbox, "session-abc-evil")
        os.makedirs(sibling_evil)

        exe = LinuxCommandExecutor(timeout_seconds=5)
        # Attempt to cat a file from the sibling session using its absolute path
        evil_file = sibling_evil + "/secret.txt"
        with open(evil_file, "w") as f:
            f.write("sibling secret")
        result = exe.execute(["cat", evil_file], workspace_abc)
        # Must be rejected — absolute path is not within workspace_abc
        assert result.policy_rejected, (
            "Sibling session path must be rejected by executor policy"
        )

    def test_workspace_root_deep_forbidden_path_rejected(self):
        """sandbox_root deep inside forbidden path (e.g. /home/user/sandbox) is rejected at construction."""
        from backend.labgen.linux_workspace import (
            LinuxWorkspaceManager,
            WorkspaceRootForbiddenError,
        )
        # /home/user/custom-sandboxes is under /home — must be rejected at construction time
        with pytest.raises(WorkspaceRootForbiddenError):
            LinuxWorkspaceManager(sandbox_root="/home/user/custom-sandboxes")
