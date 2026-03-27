"""
Tests for backend/websocket.py — SSHTerminal and VM setup helpers.
"""

import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================
# C1 回归：reset_k3s_via_agent 中步骤失败应记录 warning
# ============================================================

@pytest.mark.asyncio
async def test_hostname_failure_is_logged(caplog):
    """hostname 设置失败时应记录 warning 而非静默丢弃（C1 回归）。"""
    # post side_effects: hostname raises, rest succeed
    post_effects = [
        Exception("hostname agent exec failed"),  # Step 1: hostname → raises
        {"pid": 200},                              # Step 2: registry mirror
        {"pid": 300},                              # Step 3: health check
        {"pid": 400},                              # Step 4: etcd reset
    ]

    mock_agent = MagicMock()
    mock_agent.post.side_effect = post_effects
    # exec-status always returns exited; health check out-data is not "ok" → triggers reset
    mock_agent.get.return_value = {"exited": True, "out-data": ""}

    mock_proxmox = MagicMock()
    mock_proxmox.nodes.return_value.qemu.return_value.agent = mock_agent

    mock_ws = AsyncMock()

    from backend.websocket import reset_k3s_via_agent
    with patch("backend.websocket.connect_proxmox", return_value=mock_proxmox):
        with caplog.at_level(logging.WARNING, logger="backend.websocket"):
            await reset_k3s_via_agent(500, mock_ws)

    # After fix: a warning about hostname failure must appear
    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("hostname" in m.lower() or "500" in m for m in warning_messages), (
        f"Expected hostname failure warning for VM 500. Got warnings: {warning_messages}"
    )


@pytest.mark.asyncio
async def test_registry_failure_is_logged(caplog):
    """registry mirror 写入失败时应记录 warning 而非静默丢弃（C1 回归）。"""
    post_effects = [
        {"pid": 100},                                     # Step 1: hostname OK
        Exception("registry mirror write failed"),        # Step 2: registry → raises
        {"pid": 300},                                     # Step 3: health check
        {"pid": 400},                                     # Step 4: etcd reset
    ]

    mock_agent = MagicMock()
    mock_agent.post.side_effect = post_effects
    mock_agent.get.return_value = {"exited": True, "out-data": ""}

    mock_proxmox = MagicMock()
    mock_proxmox.nodes.return_value.qemu.return_value.agent = mock_agent

    mock_ws = AsyncMock()

    from backend.websocket import reset_k3s_via_agent
    with patch("backend.websocket.connect_proxmox", return_value=mock_proxmox):
        with caplog.at_level(logging.WARNING, logger="backend.websocket"):
            await reset_k3s_via_agent(500, mock_ws)

    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("registry" in m.lower() or "mirror" in m.lower() for m in warning_messages), (
        f"Expected registry mirror failure warning. Got warnings: {warning_messages}"
    )
