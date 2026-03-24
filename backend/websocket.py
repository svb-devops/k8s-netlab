"""
K8S NetLab - WebSocket Terminal Handler

Provides WebSocket-based SSH terminal access to VMs.
"""

import asyncio
import ipaddress
import logging
from typing import Optional

import paramiko
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from backend import config
from backend.proxmox_api import connect_proxmox

logger = logging.getLogger(__name__)


class SSHTerminal:
    """SSH terminal session manager."""

    def __init__(self, vm_id: int, vm_ip: str):
        self.vm_id = vm_id
        self.vm_ip = vm_ip
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.channel: Optional[paramiko.Channel] = None
        self.last_error: Optional[str] = None

    async def connect(self, username: str = None, password: str = None):
        """Connect to VM via SSH."""
        username = username or config.VM_SSH_USER
        password = password or config.VM_SSH_PASSWORD
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect to VM
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.ssh_client.connect(
                    self.vm_ip,
                    username=username,
                    password=password,
                    timeout=10,
                    allow_agent=False,
                    look_for_keys=False,
                ),
            )

            # Get interactive shell
            self.channel = self.ssh_client.invoke_shell(
                term="xterm-256color",
                width=120,
                height=30
            )
            self.channel.setblocking(False)

            logger.info(f"SSH connected to VM {self.vm_id} at {self.vm_ip}")
            return True

        except Exception as e:
            logger.error(f"SSH connection failed to VM {self.vm_id} ({self.vm_ip}): {e}")
            self.last_error = str(e)
            return False

    async def send(self, data: str):
        """Send data to SSH channel."""
        if self.channel:
            # Paramiko channel.send() requires bytes, not string
            data_bytes = data.encode('utf-8') if isinstance(data, str) else data
            await asyncio.get_event_loop().run_in_executor(
                None, self.channel.send, data_bytes
            )

    async def receive(self) -> Optional[str]:
        """Receive data from SSH channel."""
        if self.channel and self.channel.recv_ready():
            # Receive up to 8192 bytes at a time for better performance
            data = await asyncio.get_event_loop().run_in_executor(
                None, self.channel.recv, 8192
            )
            return data.decode("utf-8", errors="replace")
        return None

    def close(self):
        """Close SSH connection."""
        if self.channel:
            self.channel.close()
        if self.ssh_client:
            self.ssh_client.close()
        logger.info(f"SSH connection closed for VM {self.vm_id}")


async def get_vm_ip(vm_id: int) -> Optional[str]:
    """
    Get VM IP address from Proxmox QEMU agent.

    Filters to return only IPs within the configured VM_NETWORK range
    (e.g. 172.16.100.0/24), skipping k3s/flannel/CNI virtual interfaces
    that would not be reachable from the host.
    """
    try:
        proxmox = connect_proxmox()
        node = proxmox.nodes(config.PROXMOX_NODE)

        # Get VM network interfaces via QEMU guest agent
        interfaces = node.qemu(vm_id).agent.get("network-get-interfaces")

        # Build VM network object for filtering
        try:
            vm_network = ipaddress.ip_network(config.VM_NETWORK, strict=False)
        except ValueError:
            vm_network = None
            logger.warning(f"Invalid VM_NETWORK config '{config.VM_NETWORK}', IP filtering disabled")

        for iface in interfaces.get("result", []):
            if iface.get("name") == "lo":
                continue

            for ip_addr in iface.get("ip-addresses", []):
                if ip_addr.get("ip-address-type") != "ipv4":
                    continue
                ip = ip_addr.get("ip-address")
                if not ip:
                    continue

                # Prefer IPs within the configured VM network (skips flannel/CNI IPs)
                if vm_network:
                    try:
                        if ipaddress.ip_address(ip) in vm_network:
                            logger.info(f"VM {vm_id} IP found: {ip} (iface: {iface.get('name')})")
                            return ip
                    except ValueError:
                        pass
                elif not ip.startswith("127."):
                    # Fallback when VM_NETWORK is not configured
                    return ip

        return None

    except Exception as e:
        logger.error(f"Failed to get VM {vm_id} IP: {e}")
        return None


async def sync_vm_password(vm_id: int) -> bool:
    """
    Set the VM user's SSH password via QEMU guest agent so it matches
    VM_SSH_PASSWORD in config, regardless of what was on the template.

    Called after the QEMU agent is confirmed running (i.e. after get_vm_ip
    succeeds).  Failure is non-fatal: SSH is still attempted with the
    configured credentials.

    Note: Proxmox 8.x proxmoxer sets the password value as-is (no
    base64 decoding on the server side despite what older API docs say).
    Pass the raw password directly.
    """
    try:
        proxmox = connect_proxmox()
        node = proxmox.nodes(config.PROXMOX_NODE)

        # Set SSH password
        node.qemu(vm_id).agent.post(
            "set-user-password",
            username=config.VM_SSH_USER,
            password=config.VM_SSH_PASSWORD,
        )
        logger.info(f"VM {vm_id} SSH password synced via QEMU agent (user: {config.VM_SSH_USER})")

        # If logging in as root, ensure password auth is permitted
        # (cloud-init templates default to prohibit-password for root)
        if config.VM_SSH_USER == "root":
            r = node.qemu(vm_id).agent.post(
                "exec",
                command=["bash", "-c",
                    "echo 'PermitRootLogin yes' > /etc/ssh/sshd_config.d/60-root-login.conf"
                    " && systemctl restart ssh || service ssh restart"],
            )
            logger.info(f"VM {vm_id} PermitRootLogin enabled (pid={r.get('pid')})")

        return True

    except Exception as e:
        logger.warning(f"VM {vm_id} QEMU agent password sync failed: {e}")
        return False


async def reset_k3s_state(terminal: SSHTerminal, websocket: WebSocket) -> None:
    """
    Clear stale K3s etcd data and restart K3s, but only if K3s API is unhealthy.

    Templates may carry old etcd state (pod records, node registrations) from
    when they were created. This causes K3s to fail reconciliation on first boot,
    leading to intermittent API server crashes. Wiping the DB forces a clean init.

    Skipped if K3s is already healthy to avoid disrupting a working cluster.
    Waits for the reset command to fully complete before returning.
    """
    loop = asyncio.get_event_loop()

    # Check if K3s API is already responding — skip reset if healthy.
    def _check_healthy() -> bool:
        try:
            _, stdout, _ = terminal.ssh_client.exec_command(
                "curl -sk --max-time 3 https://127.0.0.1:6443/healthz",
                timeout=5,
            )
            return stdout.read().decode().strip() == "ok"
        except Exception:
            return False

    healthy = await loop.run_in_executor(None, _check_healthy)
    if healthy:
        logger.info(f"VM {terminal.vm_id}: K3s already healthy, skipping etcd reset")
        return

    # K3s API is not responding — wipe stale etcd and restart.
    await websocket.send_json({"type": "waiting", "message": "正在初始化 K3s 环境（首次启动）..."})
    try:
        def _do_reset():
            _, stdout, _ = terminal.ssh_client.exec_command(
                "systemctl stop k3s"
                " && rm -rf /var/lib/rancher/k3s/server/db"
                " && systemctl start k3s",
                timeout=60,
            )
            stdout.channel.recv_exit_status()  # block until command finishes

        await loop.run_in_executor(None, _do_reset)
        logger.info(f"VM {terminal.vm_id}: K3s state reset (etcd cleared, service restarted)")
    except Exception as e:
        logger.warning(f"VM {terminal.vm_id}: K3s state reset failed (non-fatal): {e}")


async def wait_for_k3s(terminal: SSHTerminal, websocket: WebSocket, max_wait: int = 150) -> bool:
    """Wait until K3s API is stable: core pods Running/Completed, confirmed twice."""
    loop = asyncio.get_event_loop()
    consecutive_ok = 0
    for elapsed in range(0, max_wait, 5):
        try:
            _, stdout, _ = await loop.run_in_executor(
                None,
                lambda: terminal.ssh_client.exec_command(
                    "kubectl get pods -n kube-system --no-headers 2>/dev/null"
                    " | grep -cE '(Running|Completed)'",
                    timeout=5,
                ),
            )
            running = int(stdout.read().decode().strip() or "0")
            if running >= 3:
                consecutive_ok += 1
                if consecutive_ok >= 2:
                    await asyncio.sleep(10)  # brief cool-down before handing over shell
                    return True
            else:
                consecutive_ok = 0
        except Exception:
            consecutive_ok = 0
        await websocket.send_json({
            "type": "waiting",
            "message": f"等待 K3s 就绪... ({elapsed + 5}s / {max_wait}s)",
        })
        await asyncio.sleep(5)
    return False


async def websocket_terminal(websocket: WebSocket, vm_id: int, skip_k3s_wait: bool = False):
    """
    WebSocket terminal handler (SSH bridge).

    Authentication and ownership checks are performed by the caller
    (terminal_endpoint in main.py) before this function is called.
    The WebSocket connection is already accepted when this is called.

    Args:
        websocket: FastAPI WebSocket connection (already accepted)
        vm_id: VM ID to connect to
    """
    terminal: Optional[SSHTerminal] = None

    try:
        # Get VM IP with retry (VM may still be booting)
        MAX_IP_RETRIES = 12
        IP_RETRY_INTERVAL = 5  # seconds between retries (12 * 5 = 60s total)
        vm_ip = None
        for attempt in range(MAX_IP_RETRIES):
            vm_ip = await get_vm_ip(vm_id)
            if vm_ip:
                break
            if attempt < MAX_IP_RETRIES - 1:
                await websocket.send_json({
                    "type": "waiting",
                    "message": f"等待 VM 网络就绪... ({attempt + 1}/{MAX_IP_RETRIES})",
                })
                await asyncio.sleep(IP_RETRY_INTERVAL)

        if not vm_ip:
            await websocket.send_json({
                "type": "error",
                "message": f"无法获取 VM {vm_id} 的 IP 地址（已等待 {MAX_IP_RETRIES * IP_RETRY_INTERVAL}s）"
            })
            await websocket.close()
            return

        # Sync SSH password via QEMU agent so credentials always match config
        # (handles templates whose original password differs from VM_SSH_PASSWORD)
        await sync_vm_password(vm_id)

        # Create SSH terminal
        terminal = SSHTerminal(vm_id, vm_ip)

        # Connect to VM with retries — SSH daemon may still be starting
        # (sync_vm_password restarts sshd, which causes a brief connection reset)
        MAX_SSH_RETRIES = 12
        SSH_RETRY_INTERVAL = 5  # seconds (12 × 5 = 60s total)
        ssh_connected = False
        for attempt in range(MAX_SSH_RETRIES):
            if await terminal.connect():
                ssh_connected = True
                break
            if attempt < MAX_SSH_RETRIES - 1:
                await websocket.send_json({
                    "type": "waiting",
                    "message": f"等待 SSH 就绪... ({(attempt + 1) * SSH_RETRY_INTERVAL}s / {MAX_SSH_RETRIES * SSH_RETRY_INTERVAL}s)",
                })
                await asyncio.sleep(SSH_RETRY_INTERVAL)

        if not ssh_connected:
            error_detail = terminal.last_error or "未知错误"
            await websocket.send_json({
                "type": "error",
                "message": f"SSH 连接失败 ({vm_ip}): {error_detail}"
            })
            await websocket.close()
            return

        # Wait for K3s to be ready before handing over the shell.
        # Skip when VM is mature (reconnect scenario) — K3s is already running.
        if skip_k3s_wait:
            logger.info(f"VM {vm_id}: skipping K3s wait (mature VM, reconnect)")
            await websocket.send_json({"type": "waiting", "message": "SSH 连接成功，正在开放终端..."})
        else:
            # Fresh VM: clear stale etcd state from template before waiting for K3s.
            # Templates may carry old pod/node records that cause the API server to
            # crash-loop on first boot. Wiping the DB forces a clean initialization.
            await reset_k3s_state(terminal, websocket)
            await websocket.send_json({"type": "waiting", "message": "等待 K3s 就绪，请稍候..."})
            k3s_ready = await wait_for_k3s(terminal, websocket)
            if not k3s_ready:
                await websocket.send_json({"type": "waiting", "message": "⚠ K3s 未在 150s 内就绪，已开放终端，部分命令可能需要稍等"})

        # Send connection success message
        await websocket.send_json({
            "type": "connected",
            "vm_id": vm_id,
            "vm_ip": vm_ip
        })

        # Bidirectional data forwarding
        async def forward_to_ssh():
            """Forward WebSocket data to SSH."""
            try:
                while True:
                    data = await websocket.receive_text()
                    await terminal.send(data)
            except (WebSocketDisconnect, ConnectionClosed):
                pass

        async def forward_from_ssh():
            """Forward SSH data to WebSocket with adaptive polling."""
            # Adaptive sleep: ramp up idle delay to reduce CPU when quiet,
            # snap back to fast polling as soon as data arrives.
            consecutive_empty = 0
            try:
                while True:
                    # Check if SSH channel is still open
                    if terminal.channel and terminal.channel.closed:
                        logger.info(f"SSH channel closed for VM {vm_id}")
                        await websocket.send_json({
                            "type": "disconnected",
                            "message": "SSH 连接已断开"
                        })
                        break

                    data = await terminal.receive()
                    if data:
                        await websocket.send_text(data)
                        consecutive_empty = 0   # reset: data is flowing
                        await asyncio.sleep(0.001)  # 1ms — stay responsive
                    else:
                        consecutive_empty += 1
                        if consecutive_empty < 10:
                            await asyncio.sleep(0.005)  # 5ms — brief idle
                        else:
                            await asyncio.sleep(0.010)  # 10ms — sustained idle
            except (WebSocketDisconnect, ConnectionClosed):
                pass
            except Exception as e:
                logger.error(f"Error forwarding from SSH: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"SSH 连接错误: {str(e)}"
                    })
                except:
                    pass

        # Run bidirectional forwarding concurrently
        await asyncio.gather(
            forward_to_ssh(),
            forward_from_ssh(),
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for VM {vm_id}")

    except Exception as e:
        logger.error(f"WebSocket error for VM {vm_id}: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass

    finally:
        if terminal:
            terminal.close()
        try:
            await websocket.close()
        except:
            pass
