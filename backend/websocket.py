"""
K8S NetLab - WebSocket Terminal Handler

Provides WebSocket-based SSH terminal access to VMs.
"""

import asyncio
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
            logger.error(f"SSH connection failed to VM {self.vm_id}: {e}")
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
    """Get VM IP address from Proxmox."""
    try:
        proxmox = connect_proxmox()
        node = proxmox.nodes(config.PROXMOX_NODE)

        # Get VM network interfaces
        interfaces = node.qemu(vm_id).agent.get("network-get-interfaces")

        # Find first non-lo interface IP
        for iface in interfaces.get("result", []):
            if iface.get("name") == "lo":
                continue

            for ip_addr in iface.get("ip-addresses", []):
                if ip_addr.get("ip-address-type") == "ipv4":
                    ip = ip_addr.get("ip-address")
                    if ip and not ip.startswith("127."):
                        return ip

        return None

    except Exception as e:
        logger.error(f"Failed to get VM {vm_id} IP: {e}")
        return None


async def websocket_terminal(websocket: WebSocket, vm_id: int):
    """
    WebSocket terminal handler.

    Args:
        websocket: FastAPI WebSocket connection
        vm_id: VM ID to connect to
    """
    await websocket.accept()
    terminal: Optional[SSHTerminal] = None

    try:
        # Get VM IP
        vm_ip = await get_vm_ip(vm_id)
        if not vm_ip:
            await websocket.send_json({
                "type": "error",
                "message": f"无法获取 VM {vm_id} 的 IP 地址"
            })
            await websocket.close()
            return

        # Create SSH terminal
        terminal = SSHTerminal(vm_id, vm_ip)

        # Connect to VM
        if not await terminal.connect():
            await websocket.send_json({
                "type": "error",
                "message": f"无法连接到 VM {vm_id}"
            })
            await websocket.close()
            return

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
            """Forward SSH data to WebSocket."""
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
                    else:
                        # Only sleep if no data available to avoid high CPU
                        await asyncio.sleep(0.001)  # 1ms instead of 10ms
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
