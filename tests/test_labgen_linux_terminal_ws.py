"""
Linux learner terminal WebSocket — regression tests for credential_error bug fix.

Root cause: lab_kubectl_ws.py routed ALL sessions through the K8s credential path.
Linux sessions (vm_id='linux-sandbox', namespace=None) hit ensure_learner_credentials()
which fails → 'credential_error'. This file drives the fix.

Coverage:
  A. _parse_output_redirect() — redirection parsing
  B. _run_linux_cmd() — policy enforcement + output redirection
  C. Linux session WS routing — 'ready' not 'credential_error'
  D. Blocked command returns 'blocked' type
  E. K8s session regression — K8s path unchanged
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.labgen.models import LabSessionState, LabSessionStatus

pytestmark = pytest.mark.static

# ─── Sentinel ─────────────────────────────────────────────────────────────────

LINUX_VM_SENTINEL = "linux-sandbox"

# Must be within the allowed sandbox root (LinuxWorkspaceManager policy)
_SANDBOX_ROOT = "/tmp/labgen-linux-sandboxes"


def _test_sandbox() -> str:
    """Create a unique sandbox root path for one test (within the allowed root)."""
    path = os.path.join(_SANDBOX_ROOT, f"test-ws-{uuid.uuid4().hex[:12]}")
    os.makedirs(path, exist_ok=True)
    return path


# ─── Minimal async WebSocket mock ─────────────────────────────────────────────

class FakeWebSocket:
    """Async-compatible minimal mock for testing WebSocket handlers."""

    def __init__(self):
        self.sent: list[dict] = []
        self.accepted = False
        self.closed_code: Optional[int] = None
        self.cookies: dict = {}
        self._queue: asyncio.Queue = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    async def receive_text(self) -> str:
        return await self._queue.get()

    def push(self, msg: dict) -> None:
        self._queue.put_nowait(json.dumps(msg))

    def push_disconnect(self) -> None:
        from fastapi import WebSocketDisconnect
        self._queue.put_nowait(_Disconnect())

    def types_sent(self) -> list[str]:
        return [m.get("type") for m in self.sent]


class _Disconnect:
    """Sentinel that triggers disconnect when dequeued — not actually used; see _cancel approach."""


def _make_linux_session(
    session_id: Optional[str] = None,
    username: str = "linux-tester",
    status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
) -> LabSessionState:
    return LabSessionState(
        session_id=session_id or str(uuid.uuid4()),
        lab_id="test-linux-lab",
        student_username=username,
        vm_id=LINUX_VM_SENTINEL,
        lab_session_status=status,
        namespace=None,
    )


def _make_k8s_session(
    session_id: Optional[str] = None,
    username: str = "k8s-tester",
) -> LabSessionState:
    sid = session_id or str(uuid.uuid4())
    return LabSessionState(
        session_id=sid,
        lab_id="test-k8s-lab",
        student_username=username,
        vm_id="401",
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
        namespace=f"lab-{sid}",
    )


# ─── A. _parse_output_redirect ────────────────────────────────────────────────

class TestParseOutputRedirect:

    def _parse(self, cmd_str: str):
        from backend.labgen.lab_kubectl_ws import _parse_output_redirect
        return _parse_output_redirect(cmd_str)

    def test_simple_echo_redirect(self):
        cmd, out = self._parse("echo 'hello labgen' > demo/message.txt")
        assert cmd == "echo 'hello labgen'"
        assert out == "demo/message.txt"

    def test_no_redirect_returns_none(self):
        cmd, out = self._parse("mkdir -p demo")
        assert cmd == "mkdir -p demo"
        assert out is None

    def test_cat_no_redirect(self):
        cmd, out = self._parse("cat demo/message.txt")
        assert cmd == "cat demo/message.txt"
        assert out is None

    def test_chmod_no_redirect(self):
        cmd, out = self._parse("chmod 600 demo/message.txt")
        assert cmd == "chmod 600 demo/message.txt"
        assert out is None

    def test_nested_path_redirect(self):
        cmd, out = self._parse("echo hello > subdir/output.txt")
        assert cmd == "echo hello"
        assert out == "subdir/output.txt"

    def test_reject_redirect_with_spaces_in_file(self):
        cmd, out = self._parse("echo hi > file with spaces.txt")
        # Space in file name → rejected, no redirect
        assert out is None

    def test_reject_redirect_with_pipe_in_file(self):
        cmd, out = self._parse("echo hi > file|name.txt")
        assert out is None

    def test_reject_redirect_with_semicolon_in_file(self):
        cmd, out = self._parse("echo hi > file;name.txt")
        assert out is None


# ─── B. _run_linux_cmd ────────────────────────────────────────────────────────

class TestRunLinuxCmd:
    """Unit tests for the sync command runner, using a real LinuxRuntimeAdapter."""

    @pytest.fixture
    def adapter_and_session(self):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=_test_sandbox())
        sid = str(uuid.uuid4())
        adapter.create_session(sid)
        spike = adapter.get_session(sid)
        return adapter, sid, spike.workspace_path

    def _run(self, adapter, sid, workspace, cmd):
        from backend.labgen.lab_kubectl_ws import _run_linux_cmd
        return _run_linux_cmd(adapter, sid, workspace, cmd)

    def test_mkdir_succeeds(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        result = self._run(adapter, sid, ws, "mkdir -p demo")
        assert not result["blocked"]
        assert result["exit_code"] == 0
        assert Path(ws, "demo").is_dir()

    def test_echo_returns_output(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        result = self._run(adapter, sid, ws, "echo hello labgen")
        assert not result["blocked"]
        assert "hello labgen" in result["text"]

    def test_echo_with_redirect_creates_file(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        # Create the parent dir first
        Path(ws, "demo").mkdir()
        result = self._run(adapter, sid, ws, "echo 'hello labgen' > demo/message.txt")
        assert not result["blocked"]
        assert result["exit_code"] == 0
        content = (Path(ws) / "demo" / "message.txt").read_text()
        assert "hello labgen" in content

    def test_sudo_is_blocked(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        result = self._run(adapter, sid, ws, "sudo whoami")
        assert result["blocked"]
        assert result["exit_code"] == 1

    def test_bash_is_blocked(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        result = self._run(adapter, sid, ws, "bash -c 'id'")
        assert result["blocked"]

    def test_cat_etc_passwd_blocked_forbidden_path(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        result = self._run(adapter, sid, ws, "cat /etc/passwd")
        assert result["blocked"]

    def test_redirect_path_traversal_blocked(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        result = self._run(adapter, sid, ws, "echo hi > ../escape.txt")
        assert result["blocked"]

    def test_chmod_succeeds(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        Path(ws, "test.txt").write_text("test")
        result = self._run(adapter, sid, ws, "chmod 600 test.txt")
        assert not result["blocked"]
        assert result["exit_code"] == 0

    def test_stat_mode_returns_output(self, adapter_and_session):
        adapter, sid, ws = adapter_and_session
        Path(ws, "test.txt").write_text("test")
        import os
        os.chmod(Path(ws, "test.txt"), 0o600)
        result = self._run(adapter, sid, ws, 'stat -c "%a" test.txt')
        assert not result["blocked"]
        assert "600" in result["text"]

    def test_echo_redirect_sequential_full_step1_flow(self, adapter_and_session):
        """Simulate full Step 1: mkdir + echo > file + cat verification."""
        adapter, sid, ws = adapter_and_session

        r1 = self._run(adapter, sid, ws, "mkdir -p demo")
        assert not r1["blocked"]

        r2 = self._run(adapter, sid, ws, "echo 'hello labgen' > demo/message.txt")
        assert not r2["blocked"]
        assert r2["exit_code"] == 0

        r3 = self._run(adapter, sid, ws, "cat demo/message.txt")
        assert not r3["blocked"]
        assert "hello labgen" in r3["text"]


# ─── B.2 _run_linux_cmd with a privilege-separated (non-root) runner ──────────

class TestRunLinuxCmdWithRunnerIdentity:
    """Regression: redirect-created files must be chowned to the runner, or a
    later privileged-runner command (e.g. chmod) on that same file fails with
    'Operation not permitted' — found live while validating the existing
    Linux lab under the new non-root runner (see
    LINUX_SANDBOX_NONROOT_RUNTIME_ACCEPTANCE_v0.1.md). Root cause:
    _run_linux_cmd's `>` redirect handling wrote via `out_path.write_text()`
    in the (root) calling process, never through the privilege-dropped
    executor, leaving the file root-owned while the runner ran everything
    else."""

    @pytest.fixture
    def runner_identity(self):
        from backend.labgen.linux_runner_identity import resolve_runner_identity
        return resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")

    @pytest.fixture
    def adapter_and_session(self, runner_identity):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(
            enabled=True,
            sandbox_root=_test_sandbox(),
            runner_uid=runner_identity.uid,
            runner_gid=runner_identity.gid,
        )
        sid = str(uuid.uuid4())
        adapter.create_session(sid)
        spike = adapter.get_session(sid)
        return adapter, sid, spike.workspace_path

    def _run(self, adapter, sid, workspace, cmd):
        from backend.labgen.lab_kubectl_ws import _run_linux_cmd
        return _run_linux_cmd(adapter, sid, workspace, cmd)

    def test_redirect_created_file_owned_by_runner_not_root(
        self, adapter_and_session, runner_identity
    ):
        adapter, sid, ws = adapter_and_session
        r1 = self._run(adapter, sid, ws, "mkdir -p demo")
        assert not r1["blocked"]

        r2 = self._run(adapter, sid, ws, "echo 'hello labgen' > demo/message.txt")
        assert not r2["blocked"]
        assert r2["exit_code"] == 0

        created = os.stat(Path(ws, "demo", "message.txt"))
        assert created.st_uid == runner_identity.uid
        assert created.st_uid != 0

    def test_chmod_after_redirect_succeeds_under_runner_identity(
        self, adapter_and_session
    ):
        """The exact chain that surfaced the bug: mkdir -> echo > file ->
        chmod that file. Before the fix, chmod failed with 'Operation not
        permitted' because the redirect-created file was root-owned while
        chmod itself ran as the (non-owning, non-root) runner."""
        adapter, sid, ws = adapter_and_session
        self._run(adapter, sid, ws, "mkdir -p demo")
        r2 = self._run(adapter, sid, ws, "echo 'hello labgen' > demo/message.txt")
        assert r2["exit_code"] == 0

        r3 = self._run(adapter, sid, ws, "chmod 600 demo/message.txt")
        assert not r3["blocked"]
        assert r3["exit_code"] == 0, (
            f"chmod failed under runner identity: {r3['text']!r} — "
            "redirect-created file was likely not chowned to the runner"
        )

        r4 = self._run(adapter, sid, ws, 'stat -c "%a" demo/message.txt')
        assert "600" in r4["text"]


# ─── C. Linux WS routing ──────────────────────────────────────────────────────

class TestLinuxWsRouting:
    """Linux sessions get 'ready' message, not 'credential_error'."""

    @pytest.fixture
    def adapter_and_session(self):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=_test_sandbox())
        sid = str(uuid.uuid4())
        adapter.create_session(sid)
        return adapter, sid

    async def _call_handler(self, session_id, username, adapter, session_state):
        from backend.labgen.lab_kubectl_ws import lab_kubectl_websocket
        from backend.auth import auth_manager
        from unittest.mock import patch, MagicMock

        ws = FakeWebSocket()
        ws.cookies["session_token"] = auth_manager.create_session(username)

        mock_repo = MagicMock()
        mock_repo.get.return_value = session_state

        # Cancel the handler after first message (ready or error)
        task = asyncio.create_task(
            lab_kubectl_websocket(ws, session_id, mock_repo, adapter)
        )
        # Give the handler time to send 'ready' then cancel
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

        return ws

    async def test_linux_session_receives_ready_not_credential_error(self, adapter_and_session):
        adapter, sid = adapter_and_session
        session = _make_linux_session(session_id=sid, username="lnx-tester")
        ws = await self._call_handler(sid, "lnx-tester", adapter, session)

        types = ws.types_sent()
        assert "ready" in types, f"Expected 'ready' but got: {types}"
        assert "closed" not in types or all(
            m.get("reason") != "credential_error" for m in ws.sent if m.get("type") == "closed"
        )

    async def test_linux_session_ready_message_has_no_namespace(self, adapter_and_session):
        adapter, sid = adapter_and_session
        session = _make_linux_session(session_id=sid, username="lnx-tester")
        ws = await self._call_handler(sid, "lnx-tester", adapter, session)

        ready_msgs = [m for m in ws.sent if m.get("type") == "ready"]
        assert ready_msgs, "No 'ready' message sent"
        assert ready_msgs[0].get("namespace") is None

    async def test_linux_session_ready_message_has_no_security_notice(self, adapter_and_session):
        """Regression: the security notice used to be embedded in this server-sent
        msg (and separately duplicated by the client's now-removed
        _showSecurityNotice()) — both wrote it into the xterm.js scrollback buffer,
        which wraps at the terminal's current column width and reads as ragged.
        It's now a static HTML banner in labgen-session.html; this operational
        ready message should only contain operational text."""
        adapter, sid = adapter_and_session
        session = _make_linux_session(session_id=sid, username="lnx-tester")
        ws = await self._call_handler(sid, "lnx-tester", adapter, session)

        ready_msgs = [m for m in ws.sent if m.get("type") == "ready"]
        assert ready_msgs, "No 'ready' message sent"
        msg_text = (ready_msgs[0].get("msg") or "").lower()
        assert "secret" not in msg_text
        assert "do not enter" not in msg_text

    async def test_linux_session_no_adapter_returns_not_configured(self):
        """If linux_adapter=None, Linux sessions get 'not_configured' error."""
        from backend.labgen.lab_kubectl_ws import lab_kubectl_websocket
        from backend.auth import auth_manager

        sid = str(uuid.uuid4())
        session = _make_linux_session(session_id=sid, username="lnx-tester2")
        ws = FakeWebSocket()
        ws.cookies["session_token"] = auth_manager.create_session("lnx-tester2")

        mock_repo = MagicMock()
        mock_repo.get.return_value = session

        await lab_kubectl_websocket(ws, sid, mock_repo, None)

        closed = [m for m in ws.sent if m.get("type") == "closed"]
        assert closed, "Expected closed message"
        assert closed[0]["reason"] == "not_configured"

    async def test_linux_session_workspace_not_found_returns_workspace_error(self):
        """Adapter exists but session not in it → workspace_error."""
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        from backend.labgen.lab_kubectl_ws import lab_kubectl_websocket
        from backend.auth import auth_manager

        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=_test_sandbox())
        # Do NOT create the session in the adapter

        sid = str(uuid.uuid4())
        session = _make_linux_session(session_id=sid, username="lnx-tester3")
        ws = FakeWebSocket()
        ws.cookies["session_token"] = auth_manager.create_session("lnx-tester3")

        mock_repo = MagicMock()
        mock_repo.get.return_value = session

        await lab_kubectl_websocket(ws, sid, mock_repo, adapter)

        closed = [m for m in ws.sent if m.get("type") == "closed"]
        assert closed, "Expected closed message"
        assert closed[0]["reason"] == "workspace_error"


# ─── D. Blocked command type ──────────────────────────────────────────────────

class TestLinuxBlockedCommand:

    @pytest.fixture
    def adapter_and_session(self):
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter
        adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=_test_sandbox())
        sid = str(uuid.uuid4())
        adapter.create_session(sid)
        return adapter, sid

    async def test_sudo_returns_blocked_type(self, adapter_and_session):
        from backend.labgen.lab_kubectl_ws import lab_kubectl_websocket
        from backend.auth import auth_manager

        adapter, sid = adapter_and_session
        session = _make_linux_session(session_id=sid, username="lnx-block-tester")
        ws = FakeWebSocket()
        ws.cookies["session_token"] = auth_manager.create_session("lnx-block-tester")

        mock_repo = MagicMock()
        mock_repo.get.return_value = session

        task = asyncio.create_task(
            lab_kubectl_websocket(ws, sid, mock_repo, adapter)
        )
        # Wait for 'ready'
        await asyncio.sleep(0.05)
        # Send blocked command
        ws.push({"type": "command", "cmd": "sudo whoami"})
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

        blocked_msgs = [m for m in ws.sent if m.get("type") == "blocked"]
        assert blocked_msgs, f"Expected 'blocked' message but got: {[m['type'] for m in ws.sent]}"


# ─── E. K8s regression ────────────────────────────────────────────────────────

class TestK8sSessionRegression:
    """K8s sessions must still route through K8s credential path (no regression)."""

    async def test_k8s_session_with_no_kubeconfig_gets_not_configured(self):
        """
        K8s session with no platform kubeconfig → 'not_configured' (existing behavior).
        This confirms the Linux path does not intercept K8s sessions.
        """
        from backend.labgen.lab_kubectl_ws import lab_kubectl_websocket
        from backend.auth import auth_manager
        import os
        from unittest.mock import patch

        sid = str(uuid.uuid4())
        session = _make_k8s_session(session_id=sid, username="k8s-reg-tester")
        ws = FakeWebSocket()
        ws.cookies["session_token"] = auth_manager.create_session("k8s-reg-tester")

        mock_repo = MagicMock()
        mock_repo.get.return_value = session

        # Ensure platform kubeconfig is empty → K8s path hits 'not_configured'
        with patch("backend.labgen.lab_kubectl_ws.config") as mock_config:
            mock_config.LABGEN_K8S_PLATFORM_KUBECONFIG_PATH = ""
            await lab_kubectl_websocket(ws, sid, mock_repo, linux_adapter=None)

        closed = [m for m in ws.sent if m.get("type") == "closed"]
        assert closed, f"Expected 'closed' message, got: {ws.sent}"
        assert closed[0]["reason"] == "not_configured", (
            f"Expected 'not_configured' for K8s session, got {closed[0]['reason']!r}. "
            "This means the Linux routing check may be incorrectly intercepting K8s sessions."
        )
