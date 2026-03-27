"""
K8S NetLab - WebSocket Terminal Handler

Provides WebSocket-based SSH terminal access to VMs.
"""

import asyncio
import ipaddress
import logging
from typing import Optional

import paramiko  # type: ignore[import-untyped]
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

    async def connect(self, username: Optional[str] = None, password: Optional[str] = None):
        """Connect to VM via SSH."""
        username = username or config.VM_SSH_USER
        password = password or config.VM_SSH_PASSWORD
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507 — internal lab VMs only

            # Connect to VM
            client = self.ssh_client  # local ref so mypy knows it's non-None in lambda
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.connect(
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


async def reset_k3s_via_agent(vm_id: int, websocket: WebSocket) -> None:
    """
    Clear stale K3s etcd via QEMU guest agent, BEFORE SSH is established.

    Running via agent (not SSH) is critical: `systemctl stop k3s` cleans up
    iptables rules which resets existing TCP connections, which would kill
    our SSH session if we ran this command over SSH.

    Skipped if K3s API is already healthy to avoid disrupting a running cluster.
    Waits for the reset command to complete so K3s is already starting up by
    the time the SSH connection is attempted.
    """
    import time as _time

    loop = asyncio.get_event_loop()

    def _check_and_reset() -> str:
        proxmox = connect_proxmox()
        agent = proxmox.nodes(config.PROXMOX_NODE).qemu(vm_id).agent
        hostname = f"k8s-lab-{vm_id}"

        # Step 1: Set hostname
        try:
            r = agent.post("exec", command=["bash", "-c",
                f"hostnamectl set-hostname {hostname}"
                f" && sed -i 's/k8s-template/{hostname}/g' /etc/hosts 2>/dev/null || true"])
            pid = r.get("pid")
            for _ in range(10):
                _time.sleep(0.5)
                s = agent.get("exec-status", pid=pid)
                if s.get("exited"):
                    break
        except Exception:
            pass

        # Step 2: Configure registry mirror so K3s pulls via local cache, not directly from internet
        mirror_url = config.VM_REGISTRY_MIRROR or f"http://{config.VM_GATEWAY}:5000"
        _REGISTRIES_YAML = (
            'mirrors:\n'
            '  "docker.io":\n'
            '    endpoint:\n'
            f'      - "{mirror_url}"\n'
        )
        try:
            r = agent.post("exec", command=[
                "python3", "-c",
                "import os; os.makedirs('/etc/rancher/k3s', exist_ok=True);"
                f"open('/etc/rancher/k3s/registries.yaml','w').write({repr(_REGISTRIES_YAML)})"
            ])
            pid = r.get("pid")
            for _ in range(10):
                _time.sleep(0.5)
                s = agent.get("exec-status", pid=pid)
                if s.get("exited"):
                    break
        except Exception:
            pass

        # Check K3s health via agent exec
        try:
            r = agent.post("exec", command=["bash", "-c",
                "curl -sk --max-time 3 https://127.0.0.1:6443/healthz"])
            pid = r.get("pid")
            for _ in range(10):
                _time.sleep(0.5)
                s = agent.get("exec-status", pid=pid)
                if s.get("exited"):
                    if s.get("out-data", "").strip() == "ok":
                        return "healthy"
                    break
        except Exception:
            pass

        # K3s unhealthy — wipe etcd and restart via agent
        r = agent.post("exec", command=["bash", "-c",
            "systemctl stop k3s"
            " && rm -rf /var/lib/rancher/k3s/server/db"
            " && systemctl start k3s"])
        pid = r.get("pid")
        # Wait up to 90s for the reset command to complete
        for _ in range(90):
            _time.sleep(1)
            try:
                s = agent.get("exec-status", pid=pid)
                if s.get("exited"):
                    return "reset"
            except Exception:
                pass
        return "reset-timeout"

    try:
        await websocket.send_json({"type": "waiting", "message": "正在初始化 K3s 环境..."})
        result = await loop.run_in_executor(None, _check_and_reset)
        if result == "healthy":
            logger.info(f"VM {vm_id}: K3s already healthy, skipping etcd reset")
        else:
            logger.info(f"VM {vm_id}: K3s state reset via QEMU agent ({result})")
    except Exception as e:
        logger.warning(f"VM {vm_id}: K3s reset via agent failed (non-fatal): {e}")


async def wait_for_k3s(terminal: SSHTerminal, websocket: WebSocket, max_wait: int = 150) -> bool:
    """Wait until K3s API is stable: core pods Running/Completed, confirmed twice."""
    loop = asyncio.get_event_loop()
    consecutive_ok = 0
    for elapsed in range(0, max_wait, 5):
        try:
            assert terminal.ssh_client is not None
            ssh = terminal.ssh_client
            _, stdout, _ = await loop.run_in_executor(
                None,
                lambda: ssh.exec_command(  # nosec B601 — hardcoded command, no user input
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

        # Fresh VM: clear stale etcd via QEMU agent BEFORE SSH is established.
        # Must run before SSH because `systemctl stop k3s` flushes iptables,
        # which would reset any live SSH TCP connection.
        if not skip_k3s_wait:
            await reset_k3s_via_agent(vm_id, websocket)

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
            # etcd reset already ran via QEMU agent before SSH was established.
            # K3s is starting up — wait for it to become ready.
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
                except Exception:
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
        except Exception:
            pass

    finally:
        if terminal:
            terminal.close()
        try:
            await websocket.close()
        except Exception:
            pass
