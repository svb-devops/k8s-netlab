"""
Regression: LinuxWorkspaceManager.make_directory()/write_file()/chmod_file() left
newly-created paths root-owned even when owner_uid/owner_gid were set at
construction time — only create_session() itself chowned the session root
(see the module docstring's own explanation of why that chown exists).

This is the same bug class fixed for `>` redirect files in lab_kubectl_ws.py
during Privilege Separation v0.1 (LINUX_SANDBOX_NONROOT_RUNTIME_ACCEPTANCE_v0.1.md
§A) — found again while building Golden Topic #1's fixture (a directory that a
non-root learner is expected to chmod must actually be owned by that learner's
identity, or a real non-root process would get "Operation not permitted" on
chmod regardless of workspace path containment).

Fix: make_directory()/write_file() chown their result to owner_uid/owner_gid
(when set), mirroring create_session()'s existing pattern. chmod_file() doesn't
need its own chown (it only changes mode of an already-existing path).
"""

from __future__ import annotations

import os
import shutil
import uuid

import pytest

pytestmark = pytest.mark.static

from backend.labgen.linux_runner_identity import resolve_runner_identity
from backend.labgen.linux_workspace import _SPIKE_SANDBOX_ROOT, LinuxWorkspaceManager

RUNNER_IDENTITY = resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")


@pytest.fixture()
def owned_workspace():
    mgr = LinuxWorkspaceManager(
        sandbox_root=_SPIKE_SANDBOX_ROOT,
        owner_uid=RUNNER_IDENTITY.uid,
        owner_gid=RUNNER_IDENTITY.gid,
    )
    session = mgr.create_session(f"ownertest-{uuid.uuid4().hex[:8]}")
    yield mgr, session
    shutil.rmtree(session.workspace_path, ignore_errors=True)


class TestMakeDirectoryOwnership:

    def test_make_directory_chowned_to_owner_when_set(self, owned_workspace):
        mgr, session = owned_workspace
        abs_path = mgr.make_directory(session, "case")
        st = os.stat(abs_path)
        assert st.st_uid == RUNNER_IDENTITY.uid
        assert st.st_gid == RUNNER_IDENTITY.gid

    def test_nested_make_directory_chowned(self, owned_workspace):
        mgr, session = owned_workspace
        abs_path = mgr.make_directory(session, "case/vault")
        st = os.stat(abs_path)
        assert st.st_uid == RUNNER_IDENTITY.uid

    def test_make_directory_without_owner_stays_root(self):
        # Back-compat: no owner_uid/gid set — old behavior unchanged.
        from backend.labgen.linux_workspace import _SPIKE_SANDBOX_ROOT as ROOT
        mgr = LinuxWorkspaceManager(sandbox_root=ROOT)
        session = mgr.create_session(f"nochown-{uuid.uuid4().hex[:8]}")
        try:
            abs_path = mgr.make_directory(session, "d")
            assert os.stat(abs_path).st_uid == os.getuid()
        finally:
            shutil.rmtree(session.workspace_path, ignore_errors=True)


class TestWriteFileOwnership:

    def test_write_file_chowned_to_owner_when_set(self, owned_workspace):
        mgr, session = owned_workspace
        abs_path = mgr.write_file(session, "note.txt", "hi")
        st = os.stat(abs_path)
        assert st.st_uid == RUNNER_IDENTITY.uid
        assert st.st_gid == RUNNER_IDENTITY.gid

    def test_write_file_creates_and_chowns_parent_dirs(self, owned_workspace):
        mgr, session = owned_workspace
        abs_path = mgr.write_file(session, "case/vault/report.txt", "secret\n")
        st = os.stat(abs_path)
        assert st.st_uid == RUNNER_IDENTITY.uid
        parent_st = os.stat(os.path.dirname(abs_path))
        assert parent_st.st_uid == RUNNER_IDENTITY.uid

    def test_write_file_without_owner_stays_root(self):
        from backend.labgen.linux_workspace import _SPIKE_SANDBOX_ROOT as ROOT
        mgr = LinuxWorkspaceManager(sandbox_root=ROOT)
        session = mgr.create_session(f"nochown-{uuid.uuid4().hex[:8]}")
        try:
            abs_path = mgr.write_file(session, "note.txt", "hi")
            assert os.stat(abs_path).st_uid == os.getuid()
        finally:
            shutil.rmtree(session.workspace_path, ignore_errors=True)


class TestFixtureChmodByRunnerNowPossible:
    """The actual scenario this bug blocked: a real non-root process (the
    runner) chmod'ing a directory it owns."""

    def test_runner_can_chmod_directory_it_owns(self, owned_workspace):
        from backend.labgen.linux_command_executor import LinuxCommandExecutor
        mgr, session = owned_workspace
        mgr.make_directory(session, "case/vault")
        exe = LinuxCommandExecutor(
            timeout_seconds=5, runner_uid=RUNNER_IDENTITY.uid, runner_gid=RUNNER_IDENTITY.gid
        )
        result = exe.execute(["chmod", "600", "case/vault"], session.workspace_path)
        assert not result.policy_rejected
        assert result.returncode == 0, result.stderr
