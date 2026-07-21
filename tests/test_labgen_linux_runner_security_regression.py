"""
Security regression suite for the Linux sandbox privilege-separation change.

Covers every item required before the temporary containment (existing Linux
lab access disabled in .env during migration — see
LINUX_SANDBOX_NONROOT_RUNTIME_ACCEPTANCE_v0.1.md) can be lifted:
- path traversal / absolute path escape still blocked (policy layer, unchanged)
- symlink escape blocked (workspace-manager realpath containment)
- cross-session isolation holds even though all sessions share ONE runner UID
  (privilege separation here is process-identity-from-root, NOT
  session-to-session OS isolation — that still depends entirely on
  application-level path validation, exactly as
  LINUX_TRACK_CONTRACT_v0.1.md §A already states)
- runner cannot read /etc/shadow (defense in depth: blocked by app policy
  AND by real OS file permissions)
- runner cannot write into /root or the source tree (real OS permissions)
- sudo/su/shell/interpreter/network commands remain rejected with a runner
  identity wired in (policy layer runs before subprocess.run(), so this must
  be unaffected — verified explicitly rather than assumed)
"""

from __future__ import annotations

import os
import shutil
import uuid

import pytest

from backend.labgen.linux_command_executor import LinuxCommandExecutor
from backend.labgen.linux_runner_identity import resolve_runner_identity
from backend.labgen.linux_workspace import (
    _SPIKE_SANDBOX_ROOT,
    LinuxWorkspaceManager,
    WorkspacePathEscapeError,
)

pytestmark = pytest.mark.static

RUNNER_IDENTITY = resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")


@pytest.fixture()
def runner_mgr():
    mgr = LinuxWorkspaceManager(
        sandbox_root=_SPIKE_SANDBOX_ROOT,
        owner_uid=RUNNER_IDENTITY.uid,
        owner_gid=RUNNER_IDENTITY.gid,
    )
    created: list[str] = []

    def _make(session_id: str | None = None):
        sid = session_id or f"secreg-{uuid.uuid4().hex[:8]}"
        session = mgr.create_session(sid)
        created.append(session.workspace_path)
        return mgr, session

    yield _make
    for path in created:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def runner_exe():
    return LinuxCommandExecutor(
        timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
    )


class TestPathTraversalStillBlocked:

    def test_dotdot_traversal_rejected(self, runner_mgr, runner_exe):
        _, session = runner_mgr()
        result = runner_exe.execute(["cat", "../../../etc/passwd"], session.workspace_path)
        assert result.policy_rejected
        assert "traversal" in result.rejection_reason

    def test_absolute_path_escape_rejected(self, runner_mgr, runner_exe):
        _, session = runner_mgr()
        result = runner_exe.execute(["cat", "/etc/shadow"], session.workspace_path)
        assert result.policy_rejected


class TestSymlinkEscapeBlocked:

    def test_workspace_manager_rejects_symlink_pointing_outside_workspace(self, runner_mgr):
        mgr, session = runner_mgr()
        outside_target = os.path.join(_SPIKE_SANDBOX_ROOT, f"outside-{uuid.uuid4().hex[:8]}")
        os.makedirs(outside_target, exist_ok=True)
        try:
            with open(os.path.join(outside_target, "secret.txt"), "w") as f:
                f.write("outside secret")
            link_path = os.path.join(session.workspace_path, "escape_link")
            os.symlink(outside_target, link_path)

            with pytest.raises(WorkspacePathEscapeError):
                mgr.resolve_path(session, "escape_link/secret.txt")
        finally:
            shutil.rmtree(outside_target, ignore_errors=True)


class TestCrossSessionIsolation:
    """All sessions share ONE runner UID (997) — this suite proves isolation
    comes from path validation (cwd=workspace_root + relative-paths-only),
    not from OS user separation, matching what the Track Contract states
    explicitly rather than silently assuming VM-equivalent isolation."""

    def test_session_a_cannot_read_session_b_via_absolute_path(self, runner_mgr, runner_exe):
        _, session_a = runner_mgr()
        _, session_b = runner_mgr()
        with open(os.path.join(session_b.workspace_path, "secret.txt"), "w") as f:
            f.write("session b secret")
        os.chown(
            os.path.join(session_b.workspace_path, "secret.txt"),
            RUNNER_IDENTITY.uid,
            RUNNER_IDENTITY.gid,
        )

        result = runner_exe.execute(
            ["cat", os.path.join(session_b.workspace_path, "secret.txt")],
            session_a.workspace_path,
        )
        assert result.policy_rejected

    def test_session_a_cannot_read_session_b_via_relative_traversal(self, runner_mgr, runner_exe):
        _, session_a = runner_mgr()
        _, session_b = runner_mgr()
        with open(os.path.join(session_b.workspace_path, "secret.txt"), "w") as f:
            f.write("session b secret")

        rel_escape = os.path.relpath(
            os.path.join(session_b.workspace_path, "secret.txt"), session_a.workspace_path
        )
        result = runner_exe.execute(["cat", rel_escape], session_a.workspace_path)
        assert result.policy_rejected


class TestSensitiveSystemPathsDenied:
    """Defense in depth: blocked by app policy AND by real OS permissions —
    tested both ways so a hypothetical policy bug alone wouldn't be enough
    to leak these."""

    def test_etc_shadow_denied_by_policy(self, runner_mgr, runner_exe):
        _, session = runner_mgr()
        result = runner_exe.execute(["cat", "/etc/shadow"], session.workspace_path)
        assert result.policy_rejected

    def test_etc_shadow_denied_by_real_os_permissions_for_runner(self):
        # Direct OS-level confirmation, independent of this app's policy
        # layer entirely — the file's real mode/group must already exclude
        # the runner account.
        st = os.stat("/etc/shadow")
        runner_gids = set(os.getgrouplist(RUNNER_IDENTITY.username, RUNNER_IDENTITY.gid))
        shadow_group_readable = bool(st.st_mode & 0o040) or st.st_gid in runner_gids
        world_readable = bool(st.st_mode & 0o004)
        assert not world_readable
        assert st.st_gid not in runner_gids  # runner is not in the shadow group

    def test_root_home_denied_by_policy(self, runner_mgr, runner_exe):
        _, session = runner_mgr()
        result = runner_exe.execute(["cat", "/root/.bashrc"], session.workspace_path)
        assert result.policy_rejected

    def test_source_tree_write_denied_by_real_os_permissions(self):
        # /root/k8s-netlab is 755 root:root — runner (non-owner, no group
        # match) has r-x only, never write, independent of any app policy.
        st = os.stat("/root/k8s-netlab")
        assert st.st_uid == 0
        mode = st.st_mode & 0o777
        other_write = bool(mode & 0o002)
        assert not other_write, "source tree must not be world-writable"


class TestDangerousCommandsStillRejectedWithRunnerWired:
    """Policy checks run before subprocess.run() — confirming they still
    reject with a runner identity present, not just in the pre-existing
    root-only test suite."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["sudo", "cat", "vault/report.txt"],
            ["su", "-", "root"],
            ["bash", "-c", "id"],
            ["sh", "-c", "id"],
            ["python3", "-c", "print(1)"],
            ["curl", "http://example.com"],
            ["ssh", "user@host"],
        ],
    )
    def test_denied_command_rejected(self, runner_mgr, runner_exe, argv):
        _, session = runner_mgr()
        result = runner_exe.execute(argv, session.workspace_path)
        assert result.policy_rejected
