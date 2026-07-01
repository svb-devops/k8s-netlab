"""Tests for wait_for_k3s readiness logic (mocked SSH)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.websocket import wait_for_k3s, SSHTerminal


def _make_terminal(exec_outputs):
    """Build a mock SSHTerminal whose exec_command yields successive outputs."""
    terminal = MagicMock(spec=SSHTerminal)
    terminal.vm_id = 500
    terminal.vm_ip = "172.16.100.10"

    call_count = [0]

    def fake_exec(cmd, timeout=5):
        stdout = MagicMock()
        idx = min(call_count[0], len(exec_outputs) - 1)
        stdout.read.return_value = exec_outputs[idx].encode()
        call_count[0] += 1
        return (None, stdout, None)

    terminal.ssh_client = MagicMock()
    terminal.ssh_client.exec_command.side_effect = fake_exec
    return terminal


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


class TestWaitForK3s:
    async def test_returns_true_when_pods_ready_twice(self, mock_ws):
        # First call: 3 running pods; second call: 3 running pods → 2 consecutive → ready
        terminal = _make_terminal(["3", "3"])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_k3s(terminal, mock_ws, max_wait=30)
        assert result is True

    async def test_resets_consecutive_on_failure(self, mock_ws):
        # Pattern: ok, fail, ok, ok → needs 2 consecutive → passes on 3rd+4th
        terminal = _make_terminal(["3", "0", "3", "3"])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_k3s(terminal, mock_ws, max_wait=60)
        assert result is True

    async def test_returns_false_on_timeout(self, mock_ws):
        # Always returns 0 pods → never ready
        terminal = _make_terminal(["0"])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_k3s(terminal, mock_ws, max_wait=10)
        assert result is False

    async def test_handles_exec_exception_gracefully(self, mock_ws):
        terminal = MagicMock(spec=SSHTerminal)
        terminal.ssh_client = MagicMock()
        terminal.ssh_client.exec_command.side_effect = Exception("SSH error")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_k3s(terminal, mock_ws, max_wait=10)
        assert result is False

    async def test_sends_waiting_messages(self, mock_ws):
        terminal = _make_terminal(["3", "3"])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await wait_for_k3s(terminal, mock_ws, max_wait=30)
        assert mock_ws.send_json.called
