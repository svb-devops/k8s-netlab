"""
Tests for backend/websocket.py — SSHTerminal and VM setup helpers.
"""

import asyncio
import logging
import threading
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


# ============================================================
# S1 回归：SSHTerminal.receive() 不得使用 get_event_loop()
# ============================================================

@pytest.mark.asyncio
async def test_ssh_terminal_receive_uses_get_running_loop(monkeypatch):
    """SSHTerminal.receive() 必须用 get_running_loop()，不得用已废弃的 get_event_loop()（S1 回归）。"""
    from backend.websocket import SSHTerminal

    terminal = SSHTerminal.__new__(SSHTerminal)

    # 伪造 SSH channel
    mock_channel = MagicMock()
    mock_channel.recv_ready.return_value = True
    mock_channel.recv.return_value = b"hello"
    terminal.channel = mock_channel
    terminal.ssh_client = None

    calls: list[str] = []

    original_get_running_loop = asyncio.get_running_loop

    def track_get_running_loop():
        calls.append("get_running_loop")
        return original_get_running_loop()

    monkeypatch.setattr(asyncio, "get_running_loop", track_get_running_loop)
    # get_event_loop should NOT be called
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: (_ for _ in ()).throw(
        AssertionError("get_event_loop() must not be called — use get_running_loop()")
    ))

    result = await terminal.receive()

    assert result == "hello"
    assert "get_running_loop" in calls, "receive() did not call get_running_loop()"


# ============================================================
# wait_for_k3s 回归：ssh_client 为 None 时应优雅退出
# ============================================================

@pytest.mark.asyncio
async def test_wait_for_k3s_none_ssh_client_returns_false():
    """wait_for_k3s 在 ssh_client 为 None 时应返回 False 而不是 AssertionError（assert guard 回归）。"""
    from backend.websocket import SSHTerminal, wait_for_k3s

    terminal = SSHTerminal.__new__(SSHTerminal)
    terminal.channel = None
    terminal.ssh_client = None  # 模拟 SSH 连接未建立

    mock_ws = AsyncMock()

    result = await wait_for_k3s(terminal, mock_ws, max_wait=5)

    assert result is False, "Expected False when ssh_client is None"


# ============================================================
# A 类回归：get_vm_ip / sync_vm_password 不得阻塞 event loop
# ============================================================

@pytest.mark.asyncio
async def test_get_vm_ip_does_not_block_event_loop():
    """get_vm_ip() 必须通过 run_in_executor 调用 Proxmox API，不得在 event loop 线程执行阻塞 I/O（A 类异步安全）。"""
    main_thread_id = threading.get_ident()
    proxmox_call_thread_ids: list[int] = []

    def recording_get(*args, **kwargs):
        proxmox_call_thread_ids.append(threading.get_ident())
        return {"result": []}

    mock_agent = MagicMock()
    mock_agent.get.side_effect = recording_get
    mock_proxmox = MagicMock()
    mock_proxmox.nodes.return_value.qemu.return_value.agent = mock_agent

    from backend.websocket import get_vm_ip
    with patch("backend.websocket.connect_proxmox", return_value=mock_proxmox):
        await get_vm_ip(500)

    assert proxmox_call_thread_ids, "connect_proxmox was never called"
    assert main_thread_id not in proxmox_call_thread_ids, (
        "get_vm_ip() called Proxmox API on the event loop thread — "
        "must use run_in_executor to avoid blocking all requests"
    )


@pytest.mark.asyncio
async def test_sync_vm_password_does_not_block_event_loop():
    """sync_vm_password() 必须通过 run_in_executor 调用 Proxmox API，不得在 event loop 线程执行阻塞 I/O（A 类异步安全）。"""
    main_thread_id = threading.get_ident()
    proxmox_call_thread_ids: list[int] = []

    def recording_post(*args, **kwargs):
        proxmox_call_thread_ids.append(threading.get_ident())
        return {}

    mock_agent = MagicMock()
    mock_agent.post.side_effect = recording_post
    mock_proxmox = MagicMock()
    mock_proxmox.nodes.return_value.qemu.return_value.agent = mock_agent

    from backend.websocket import sync_vm_password
    with patch("backend.websocket.connect_proxmox", return_value=mock_proxmox), \
         patch("backend.websocket.config") as mock_config:
        mock_config.PROXMOX_NODE = "pve"
        mock_config.VM_SSH_USER = "user"
        mock_config.VM_SSH_PASSWORD = "example"
        await sync_vm_password(500)

    assert proxmox_call_thread_ids, "connect_proxmox was never called"
    assert main_thread_id not in proxmox_call_thread_ids, (
        "sync_vm_password() called Proxmox API on the event loop thread — "
        "must use run_in_executor to avoid blocking all requests"
    )


@pytest.mark.asyncio
async def test_ssh_terminal_connect_invoke_shell_does_not_block_event_loop():
    """SSHTerminal.connect() 的 invoke_shell() 必须在 executor 线程执行，不得阻塞 event loop（A 类异步安全）。"""
    main_thread_id = threading.get_ident()
    invoke_shell_thread_ids: list[int] = []

    mock_channel = MagicMock()

    def recording_invoke_shell(**kwargs):
        invoke_shell_thread_ids.append(threading.get_ident())
        return mock_channel

    mock_client = MagicMock()
    mock_client.connect.return_value = None
    mock_client.invoke_shell.side_effect = recording_invoke_shell

    from backend.websocket import SSHTerminal
    terminal = SSHTerminal.__new__(SSHTerminal)
    terminal.vm_id = 500
    terminal.vm_ip = "172.16.100.50"
    terminal.ssh_client = None
    terminal.channel = None
    terminal.last_error = None

    with patch("backend.websocket.paramiko") as mock_paramiko:
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.AutoAddPolicy.return_value = MagicMock()
        await terminal.connect(username="root", password="example")

    assert invoke_shell_thread_ids, "invoke_shell() was never called"
    assert main_thread_id not in invoke_shell_thread_ids, (
        "invoke_shell() called on event loop thread — must be inside run_in_executor"
    )
