# Day 2: K8S 模板创建和 WebSocket 终端开发指南

> **目标**: 创建生产级 K8s 模板 + 实现 WebSocket 终端功能
> **预计时间**: 8 小时（上午 4h 模板 + 下午 4h 开发）
> **前提条件**: Day 1 完成，后端 API 和前端界面可用

---

## 📋 Day 2 时间表

| 时间 | 任务 | 预计时长 | 状态 |
|------|------|---------|------|
| 09:00-09:10 | 准备工作和环境检查 | 10分钟 | ⏸️ |
| 09:10-09:40 | 创建基础 VM | 30分钟 | ⏸️ |
| 09:40-11:10 | 安装 K3s 和必需工具 | 1.5小时 | ⏸️ |
| 11:10-11:40 | 优化和清理 | 30分钟 | ⏸️ |
| 11:40-11:50 | 转换为模板 | 10分钟 | ⏸️ |
| 11:50-12:00 | 测试验证 | 10分钟 | ⏸️ |
| **午休** | | 1小时 | |
| 13:00-14:30 | WebSocket 后端实现 | 1.5小时 | ⏸️ |
| 14:30-16:00 | 前端终端集成 | 1.5小时 | ⏸️ |
| 16:00-17:00 | 测试和调试 | 1小时 | ⏸️ |

---

# 上午: 创建完美的 K8s 模板

## 🔧 第1步: 准备工作 (10分钟)

### 1.1 清理现有 VM 100

```bash
# 检查 VM 100 状态
qm status 100

# 如果正在运行，停止它
qm stop 100

# 等待完全停止
sleep 5

# 删除现有 VM 100
qm destroy 100

# 验证删除成功
qm list | grep 100
# 预期输出: (空，没有输出)
```

### 1.2 检查磁盘空间

```bash
# 检查存储空间
df -h | grep -E "local-lvm|Filesystem"

# 预期输出示例:
# Filesystem              Size  Used Avail Use% Mounted on
# /dev/mapper/pve-root     94G   15G   74G  17% /

# 至少需要 20GB 可用空间
```

### 1.3 下载 Ubuntu 22.04 云镜像

```bash
# 进入 ISO 存储目录
cd /var/lib/vz/template/iso/

# 下载 Ubuntu 22.04 云镜像 (约 700MB)
wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img

# 验证下载
ls -lh jammy-server-cloudimg-amd64.img
# 预期输出: -rw-r--r-- 1 root root 700M ... jammy-server-cloudimg-amd64.img
```

**检查点 ✓**:
- [ ] VM 100 已删除
- [ ] 磁盘空间充足 (>20GB)
- [ ] Ubuntu 镜像已下载

---

## 🖥️ 第2步: 创建基础 VM (30分钟)

### 2.1 创建 VM 配置

```bash
# 创建 VM 100
qm create 100 \
  --name "k8s-template" \
  --memory 4096 \
  --cores 2 \
  --net0 virtio,bridge=vmbr0 \
  --serial0 socket \
  --vga serial0

# 验证创建
qm config 100
# 预期输出: cores: 2, memory: 4096, name: k8s-template
```

### 2.2 导入磁盘镜像

```bash
# 导入云镜像到 VM 100
qm importdisk 100 \
  /var/lib/vz/template/iso/jammy-server-cloudimg-amd64.img \
  local-lvm

# 预期输出:
# importing disk '/var/lib/vz/template/iso/jammy-server-cloudimg-amd64.img' to VM 100 ...
# Successfully imported disk as 'unused0:local-lvm:vm-100-disk-0'

# 附加磁盘到 VM
qm set 100 --scsi0 local-lvm:vm-100-disk-0

# 设置启动盘
qm set 100 --boot c --bootdisk scsi0

# 扩展磁盘到 32GB
qm resize 100 scsi0 32G

# 验证磁盘配置
qm config 100 | grep scsi0
# 预期输出: scsi0: local-lvm:vm-100-disk-0,size=32G
```

### 2.3 配置 Cloud-Init

```bash
# 添加 Cloud-Init 驱动
qm set 100 --ide2 local-lvm:cloudinit

# 配置 Cloud-Init (网络、用户等)
qm set 100 --ciuser root
qm set 100 --cipassword <your-vm-ssh-password>
qm set 100 --ipconfig0 ip=dhcp
qm set 100 --sshkeys ~/.ssh/authorized_keys

# 验证 Cloud-Init 配置
qm cloudinit dump 100 user
# 预期输出: 包含用户配置的 YAML
```

### 2.4 启动 VM 进行配置

```bash
# 启动 VM 100
qm start 100

# 等待启动完成 (约 30-60 秒)
sleep 60

# 获取 VM IP 地址
qm guest cmd 100 network-get-interfaces

# 或者通过 Proxmox 界面查看
# 预期 IP: 10.0.0.x (DHCP 分配)
```

**检查点 ✓**:
- [ ] VM 100 已创建
- [ ] 磁盘已扩展到 32GB
- [ ] Cloud-Init 已配置
- [ ] VM 已启动并获取 IP

---

## 🚀 第3步: 安装 K3s 和工具 (1.5小时)

### 3.1 SSH 连接到 VM

```bash
# 获取 VM IP (假设是 10.0.0.150)
VM_IP=$(qm guest cmd 100 network-get-interfaces | grep -oP '10\.0\.0\.\d+' | head -1)

# SSH 连接
ssh root@$VM_IP
# 密码: <your-vm-ssh-password>（在 .env 中配置 VM_SSH_PASSWORD）

# 验证连接成功
hostname
# 预期输出: k8s-template
```

### 3.2 系统更新和基础包

```bash
# 在 VM 内执行以下命令

# 更新软件包列表
apt update

# 升级现有软件包 (可选，但建议)
apt upgrade -y

# 安装基础工具
apt install -y \
  curl \
  wget \
  vim \
  git \
  htop \
  net-tools \
  iputils-ping \
  dnsutils \
  traceroute \
  tcpdump \
  iptables \
  jq \
  bash-completion

# 验证安装
which curl wget vim git jq
# 预期输出: 所有工具的路径
```

### 3.3 安装 K3s (轻量级 Kubernetes)

```bash
# 安装 K3s (约 5-10 分钟)
curl -sfL https://get.k3s.io | sh -

# 等待 K3s 启动
sleep 30

# 验证 K3s 安装
systemctl status k3s
# 预期输出: active (running)

# 配置 kubectl
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
echo 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml' >> ~/.bashrc

# 验证 Kubernetes 集群
kubectl get nodes
# 预期输出:
# NAME           STATUS   ROLES                  AGE   VERSION
# k8s-template   Ready    control-plane,master   30s   v1.28.x+k3s1

kubectl get pods -A
# 预期输出: 所有系统 pods 运行中
```

### 3.4 安装网络工具和 CNI 插件

```bash
# 安装 bridge-utils (网络桥接)
apt install -y bridge-utils

# 安装 Calico CLI (网络策略)
cd /usr/local/bin
curl -L https://github.com/projectcalico/calico/releases/latest/download/calicoctl-linux-amd64 -o calicoctl
chmod +x calicoctl

# 验证 Calico
calicoctl version
```

### 3.5 安装实验所需工具

```bash
# 11个实验需要的工具包

# 1. Docker (容器运行时 - K3s 自带 containerd，但 docker CLI 有用)
apt install -y docker.io
systemctl enable docker
systemctl start docker

# 2. etcdctl (etcd 管理工具)
ETCD_VER=v3.5.10
wget https://github.com/etcd-io/etcd/releases/download/${ETCD_VER}/etcd-${ETCD_VER}-linux-amd64.tar.gz
tar xzvf etcd-${ETCD_VER}-linux-amd64.tar.gz
mv etcd-${ETCD_VER}-linux-amd64/etcdctl /usr/local/bin/
rm -rf etcd-${ETCD_VER}-linux-amd64*

# 3. Helm (Kubernetes 包管理器)
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# 4. kubens/kubectx (命名空间切换工具)
git clone https://github.com/ahmetb/kubectx /opt/kubectx
ln -s /opt/kubectx/kubectx /usr/local/bin/kubectx
ln -s /opt/kubectx/kubens /usr/local/bin/kubens

# 5. stern (多 pod 日志查看)
wget https://github.com/stern/stern/releases/download/v1.28.0/stern_1.28.0_linux_amd64.tar.gz
tar xzvf stern_1.28.0_linux_amd64.tar.gz
mv stern /usr/local/bin/
rm stern_1.28.0_linux_amd64.tar.gz

# 6. k9s (Kubernetes TUI)
wget https://github.com/derailed/k9s/releases/download/v0.31.0/k9s_Linux_amd64.tar.gz
tar xzvf k9s_Linux_amd64.tar.gz
mv k9s /usr/local/bin/
rm k9s_Linux_amd64.tar.gz

# 7. crictl (容器运行时 CLI)
VERSION="v1.29.0"
wget https://github.com/kubernetes-sigs/cri-tools/releases/download/$VERSION/crictl-$VERSION-linux-amd64.tar.gz
tar zxvf crictl-$VERSION-linux-amd64.tar.gz -C /usr/local/bin
rm crictl-$VERSION-linux-amd64.tar.gz

# 8. nmap (网络扫描)
apt install -y nmap

# 9. netcat (网络调试)
apt install -y netcat-openbsd

# 10. iperf3 (带宽测试)
apt install -y iperf3

# 11. mtr (网络诊断)
apt install -y mtr

# 验证所有工具安装
echo "=== 工具版本检查 ==="
kubectl version --client
docker --version
etcdctl version
helm version
kubectx --version
stern --version
k9s version
crictl --version
nmap --version
nc -h 2>&1 | head -1
iperf3 --version
mtr --version
```

### 3.6 配置自动补全和别名

```bash
# Kubectl 自动补全
kubectl completion bash > /etc/bash_completion.d/kubectl

# 添加常用别名
cat >> ~/.bashrc << 'EOF'

# Kubernetes 别名
alias k='kubectl'
alias kgp='kubectl get pods'
alias kgs='kubectl get svc'
alias kgn='kubectl get nodes'
alias kd='kubectl describe'
alias kdel='kubectl delete'
alias kl='kubectl logs'
alias ke='kubectl exec -it'

# 网络工具别名
alias ll='ls -lah'
alias watch='watch -n 1'
EOF

# 重新加载配置
source ~/.bashrc
```

**检查点 ✓**:
- [ ] K3s 安装成功并运行
- [ ] 所有 11 个工具已安装
- [ ] kubectl 可以访问集群
- [ ] 自动补全已配置

---

## 🧹 第4步: 优化和清理 (30分钟)

### 4.1 清理日志和缓存

```bash
# 清理 APT 缓存
apt clean
apt autoclean
apt autoremove -y

# 清理系统日志
journalctl --vacuum-time=1d

# 清理临时文件
rm -rf /tmp/*
rm -rf /var/tmp/*

# 清理下载的安装包
rm -rf ~/etcd-*
rm -rf ~/stern_*
rm -rf ~/k9s_*
rm -rf ~/crictl-*
```

### 4.2 清理 SSH 密钥 (重要!)

```bash
# 清理 SSH 主机密钥 (克隆后会重新生成)
rm -f /etc/ssh/ssh_host_*

# 清理 root 用户的 SSH authorized_keys (可选)
# 如果你想要克隆的 VM 没有 SSH 密钥，取消注释下一行
# rm -f /root/.ssh/authorized_keys

# 清理 bash 历史
history -c
rm -f ~/.bash_history
```

### 4.3 重置 Cloud-Init

```bash
# 清理 Cloud-Init 状态 (使克隆的 VM 可以重新运行 Cloud-Init)
cloud-init clean --logs

# 验证清理
ls /var/lib/cloud/instances/
# 预期输出: (空目录)
```

### 4.4 清理网络配置

```bash
# 清理 Machine ID (克隆后会重新生成)
truncate -s 0 /etc/machine-id
rm /var/lib/dbus/machine-id
ln -s /etc/machine-id /var/lib/dbus/machine-id

# 清理 netplan 生成的配置
rm -f /etc/netplan/50-cloud-init.yaml
```

### 4.5 优化磁盘空间

```bash
# 填充空闲空间为零 (压缩磁盘镜像)
# 注意: 这会占用所有可用空间，需要时间
dd if=/dev/zero of=/tmp/zero bs=1M || true
rm -f /tmp/zero

# 同步文件系统
sync

# 检查磁盘使用
df -h
# 预期: 使用率应该在 20-30% 左右
```

### 4.6 最终验证

```bash
# 验证 K3s 仍在运行
kubectl get nodes
kubectl get pods -A

# 验证工具可用
k9s version
helm version
stern --version

# 记录当前磁盘使用
du -sh /
# 预期: 约 6-8 GB

echo "✅ 清理完成！准备关机并转换为模板"
```

### 4.7 关机准备

```bash
# 在 VM 内执行
shutdown -h now
```

**检查点 ✓**:
- [ ] 缓存和日志已清理
- [ ] SSH 主机密钥已删除
- [ ] Cloud-Init 已重置
- [ ] Machine ID 已清零
- [ ] VM 已关机

---

## 📦 第5步: 转换为模板 (10分钟)

### 5.1 在 Proxmox 主机上执行

```bash
# 等待 VM 完全关机
sleep 10

# 验证 VM 已停止
qm status 100
# 预期输出: status: stopped

# 转换为模板
qm template 100

# 验证模板创建成功
qm config 100 | grep template
# 预期输出: template: 1

# 查看模板信息
qm config 100
```

### 5.2 测试从模板克隆

```bash
# 克隆测试 VM (ID 999)
qm clone 100 999 --name test-k8s-clone --full 1

# 等待克隆完成 (约 1-2 分钟)
# 监控克隆进度
watch -n 1 'qm list | grep 999'

# 克隆完成后，启动测试 VM
qm start 999

# 等待启动
sleep 60

# 获取测试 VM IP
TEST_VM_IP=$(qm guest cmd 999 network-get-interfaces | grep -oP '10\.0\.0\.\d+' | head -1)

# SSH 连接测试
ssh root@$TEST_VM_IP "kubectl get nodes"
# 预期输出: 节点列表，状态 Ready

# 测试成功后，删除测试 VM
qm stop 999
qm destroy 999

echo "✅ 模板测试成功！"
```

**检查点 ✓**:
- [ ] VM 100 已转换为模板
- [ ] 克隆测试成功
- [ ] 克隆的 VM 可以正常启动
- [ ] K3s 在克隆的 VM 中正常运行

---

# 下午: WebSocket 终端开发

## 🔌 第6步: WebSocket 后端实现 (1.5小时)

### 6.1 安装依赖

```bash
# 在项目根目录
cd /root/k8s-netlab

# 安装 WebSocket 和 SSH 客户端库
pip3 install websockets paramiko --break-system-packages
```

### 6.2 创建 WebSocket 处理器

创建文件: `backend/websocket.py`

```python
"""
K8S NetLab - WebSocket Terminal Handler

Provides WebSocket-based SSH terminal access to VMs.
"""

import asyncio
import logging
from typing import Dict, Optional

import paramiko
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from backend import config
from backend.vm_manager import list_vms
from backend.proxmox_api import connect_proxmox

logger = logging.getLogger(__name__)


class SSHTerminal:
    """SSH terminal session manager."""

    def __init__(self, vm_id: int, vm_ip: str):
        self.vm_id = vm_id
        self.vm_ip = vm_ip
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.channel: Optional[paramiko.Channel] = None

    async def connect(self, username: str = "root", password: str = None):
        """Connect to VM via SSH."""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # 使用默认密码或从配置读取
            if password is None:
                password = config.VM_SSH_PASSWORD  # 从环境变量读取

            # 连接到 VM
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

            # 获取交互式 shell
            self.channel = self.ssh_client.invoke_shell(term="xterm-256color")
            self.channel.setblocking(False)

            logger.info(f"SSH connected to VM {self.vm_id} at {self.vm_ip}")
            return True

        except Exception as e:
            logger.error(f"SSH connection failed to VM {self.vm_id}: {e}")
            return False

    async def send(self, data: str):
        """Send data to SSH channel."""
        if self.channel:
            self.channel.send(data)

    async def receive(self) -> Optional[str]:
        """Receive data from SSH channel."""
        if self.channel and self.channel.recv_ready():
            data = self.channel.recv(4096)
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

        # 获取 VM 网络接口信息
        interfaces = node.qemu(vm_id).agent.get("network-get-interfaces")

        # 查找第一个非 lo 接口的 IP
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
        # 获取 VM IP
        vm_ip = await get_vm_ip(vm_id)
        if not vm_ip:
            await websocket.send_json({
                "type": "error",
                "message": f"无法获取 VM {vm_id} 的 IP 地址"
            })
            await websocket.close()
            return

        # 创建 SSH 终端
        terminal = SSHTerminal(vm_id, vm_ip)

        # 连接到 VM
        if not await terminal.connect():
            await websocket.send_json({
                "type": "error",
                "message": f"无法连接到 VM {vm_id}"
            })
            await websocket.close()
            return

        # 发送连接成功消息
        await websocket.send_json({
            "type": "connected",
            "vm_id": vm_id,
            "vm_ip": vm_ip
        })

        # 双向数据转发
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
                    data = await terminal.receive()
                    if data:
                        await websocket.send_text(data)
                    await asyncio.sleep(0.01)  # 避免 CPU 占用过高
            except (WebSocketDisconnect, ConnectionClosed):
                pass

        # 并发运行双向转发
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
```

### 6.3 添加 WebSocket 路由到 main.py

编辑 `backend/main.py`，添加 WebSocket 端点：

```python
# 在 imports 部分添加
from fastapi import WebSocket
from backend.websocket import websocket_terminal

# 在路由部分添加 (在 app.include_router 之后)
@app.websocket("/ws/terminal/{vm_id}")
async def terminal_endpoint(websocket: WebSocket, vm_id: int):
    """
    WebSocket terminal endpoint.

    Args:
        websocket: WebSocket connection
        vm_id: VM ID to connect to
    """
    await websocket_terminal(websocket, vm_id)
```

**检查点 ✓**:
- [ ] WebSocket 依赖已安装
- [ ] websocket.py 已创建
- [ ] WebSocket 路由已添加
- [ ] 代码可以正常导入

---

## 🎨 第7步: 前端终端集成 (1.5小时)

### 7.1 更新 index.html

在 `frontend/index.html` 的 `<head>` 部分添加 xterm.js：

```html
<!-- xterm.js CDN -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.js"></script>
```

在 VM 列表表格中添加"连接终端"按钮。修改 `frontend/js/app.js` 中的 `createVMRow` 函数：

```javascript
// 在操作列添加终端按钮
<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
    ${vm.status === 'running' ? `
        <button onclick="app.handleConnectTerminal(${vm.vmid})"
                class="text-blue-600 hover:text-blue-900 transition duration-150">
            终端
        </button>
    ` : ''}
    <button onclick="app.handleDeleteVM(${vm.vmid})"
            class="text-red-600 hover:text-red-900 transition duration-150">
        删除
    </button>
</td>
```

### 7.2 创建终端管理器

创建文件: `frontend/js/terminal.js`

```javascript
/**
 * K8S NetLab - Terminal Manager
 *
 * Manages WebSocket connections and xterm.js terminal instances.
 */

class TerminalManager {
    constructor() {
        this.terminal = null;
        this.fitAddon = null;
        this.websocket = null;
        this.currentVMId = null;
    }

    /**
     * Connect to VM terminal
     */
    async connect(vmId) {
        // 关闭现有连接
        this.disconnect();

        this.currentVMId = vmId;

        // 创建 xterm 实例
        this.terminal = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: 'Menlo, Monaco, "Courier New", monospace',
            theme: {
                background: '#1e1e1e',
                foreground: '#d4d4d4',
                cursor: '#ffffff',
                selection: '#264f78',
            },
            rows: 30,
            cols: 120,
        });

        // 添加 fit 插件 (自动调整大小)
        this.fitAddon = new FitAddon.FitAddon();
        this.terminal.loadAddon(this.fitAddon);

        // 添加 web links 插件
        this.terminal.loadAddon(new WebLinksAddon.WebLinksAddon());

        // 挂载到 DOM
        const terminalContainer = document.getElementById('terminal');
        terminalContainer.innerHTML = ''; // 清空
        this.terminal.open(terminalContainer);
        this.fitAddon.fit();

        // 显示终端区域
        document.getElementById('terminal-section').classList.remove('hidden');

        // 连接 WebSocket
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/terminal/${vmId}`;

        this.websocket = new WebSocket(wsUrl);

        // WebSocket 事件处理
        this.websocket.onopen = () => {
            console.log(`WebSocket connected to VM ${vmId}`);
            this.terminal.write('\r\n\x1b[32m✓ 已连接到 VM ' + vmId + '\x1b[0m\r\n');
        };

        this.websocket.onmessage = (event) => {
            try {
                // 尝试解析 JSON 消息
                const msg = JSON.parse(event.data);
                if (msg.type === 'error') {
                    this.terminal.write('\r\n\x1b[31m✗ 错误: ' + msg.message + '\x1b[0m\r\n');
                } else if (msg.type === 'connected') {
                    this.terminal.write('\r\n\x1b[32m✓ SSH 连接成功 (' + msg.vm_ip + ')\x1b[0m\r\n\r\n');
                }
            } catch {
                // 普通终端数据
                this.terminal.write(event.data);
            }
        };

        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.terminal.write('\r\n\x1b[31m✗ WebSocket 连接错误\x1b[0m\r\n');
        };

        this.websocket.onclose = () => {
            console.log('WebSocket closed');
            this.terminal.write('\r\n\x1b[33m✗ 连接已关闭\x1b[0m\r\n');
        };

        // 终端输入 -> WebSocket
        this.terminal.onData((data) => {
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                this.websocket.send(data);
            }
        });

        // 窗口大小调整
        window.addEventListener('resize', () => {
            if (this.fitAddon) {
                this.fitAddon.fit();
            }
        });
    }

    /**
     * Disconnect terminal
     */
    disconnect() {
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }

        if (this.terminal) {
            this.terminal.dispose();
            this.terminal = null;
        }

        this.currentVMId = null;

        // 隐藏终端区域
        document.getElementById('terminal-section').classList.add('hidden');
    }

    /**
     * Check if connected
     */
    isConnected() {
        return this.websocket && this.websocket.readyState === WebSocket.OPEN;
    }
}

// 创建全局终端管理器实例
const terminalManager = new TerminalManager();
```

### 7.3 更新 app.js

在 `frontend/js/app.js` 中添加终端连接方法：

```javascript
/**
 * Handle Connect Terminal
 */
async handleConnectTerminal(vmId) {
    if (this.isLoading) return;

    try {
        // 连接到 VM 终端
        await terminalManager.connect(vmId);

        // 滚动到终端区域
        document.getElementById('terminal-section').scrollIntoView({
            behavior: 'smooth'
        });

    } catch (error) {
        console.error('Failed to connect terminal:', error);
        this.showError('连接失败', error.message);
    }
}
```

### 7.4 更新 index.html 终端部分

找到终端占位符部分，更新为：

```html
<!-- Terminal Section -->
<div id="terminal-section" class="mt-8 hidden">
    <div class="bg-white rounded-lg shadow overflow-hidden">
        <div class="px-6 py-4 bg-gray-800 text-white flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                </svg>
                <h2 class="text-lg font-semibold">终端控制台</h2>
            </div>
            <button onclick="terminalManager.disconnect()"
                    class="text-sm hover:text-gray-300 transition duration-150">
                断开连接
            </button>
        </div>
        <div class="terminal-container p-4">
            <div id="terminal" class="w-full h-96"></div>
        </div>
    </div>
</div>
```

### 7.5 在 index.html 中引入 terminal.js

在 `</body>` 前添加：

```html
<script src="/js/api.js"></script>
<script src="/js/terminal.js"></script>
<script src="/js/app.js"></script>
```

**检查点 ✓**:
- [ ] xterm.js CDN 已添加
- [ ] terminal.js 已创建
- [ ] 终端按钮已添加到 VM 列表
- [ ] HTML 终端区域已更新

---

## 🧪 第8步: 测试和调试 (1小时)

### 8.1 重启后端服务器

```bash
# 停止旧服务器
pkill -f 'python3 -m backend.main'

# 启动新服务器
cd /root/k8s-netlab
python3 -m backend.main > /tmp/k8s-netlab.log 2>&1 &

# 查看日志
tail -f /tmp/k8s-netlab.log
```

### 8.2 测试流程

1. **创建测试 VM**
   - 访问 http://10.0.0.110:8000
   - 点击"创建实验环境"
   - 等待 VM 创建完成（约 1-2 分钟）

2. **等待 VM 完全启动**
   - 等待约 2 分钟让 VM 完全启动
   - 确认 VM 状态为"运行中"

3. **连接终端**
   - 点击 VM 行的"终端"按钮
   - 终端应该出现并显示连接消息
   - 应该看到 SSH 登录提示

4. **测试命令**
   ```bash
   # 在终端中执行
   kubectl get nodes
   kubectl get pods -A
   k9s version
   docker --version
   ```

5. **测试完成后删除 VM**
   - 点击"删除"按钮
   - 确认删除

### 8.3 常见问题排查

**问题 1: WebSocket 连接失败**
```bash
# 检查 paramiko 是否安装
python3 -c "import paramiko; print('OK')"

# 检查 WebSocket 路由
curl http://localhost:8000/api
```

**问题 2: 无法获取 VM IP**
```bash
# 确认 QEMU Guest Agent 运行
qm agent <vm_id> ping

# 手动获取 IP
qm guest cmd <vm_id> network-get-interfaces
```

**问题 3: SSH 连接超时**
```bash
# 检查 VM 防火墙
ssh root@<vm_ip> "iptables -L"

# 检查 SSH 服务
ssh root@<vm_ip> "systemctl status sshd"
```

**检查点 ✓**:
- [ ] 服务器重启成功
- [ ] 可以创建 VM
- [ ] 终端连接成功
- [ ] 可以执行命令
- [ ] 可以删除 VM

---

## 📋 Day 2 最终检查清单

### 模板创建
- [ ] VM 100 已删除旧版本
- [ ] Ubuntu 22.04 镜像已下载
- [ ] 基础 VM 已创建并配置
- [ ] K3s 已安装并运行
- [ ] 所有 11 个工具已安装
- [ ] SSH 密钥已清理
- [ ] Cloud-Init 已重置
- [ ] VM 已转换为模板
- [ ] 克隆测试成功

### WebSocket 终端
- [ ] WebSocket 依赖已安装
- [ ] websocket.py 已创建
- [ ] WebSocket 路由已添加
- [ ] terminal.js 已创建
- [ ] 前端终端界面已集成
- [ ] 终端连接测试成功
- [ ] 可以执行 kubectl 命令

### 代码质量
- [ ] 所有代码遵守开发规范
- [ ] 完整的错误处理
- [ ] 日志记录完善
- [ ] Git 提交清晰

---

## 🎯 预期成果

**Day 2 结束时你将拥有：**

1. ✅ 生产级 K8s 模板
   - K3s 预装
   - 11 个网络工具
   - 32GB 磁盘空间
   - 优化和清理完毕

2. ✅ 功能完整的 WebSocket 终端
   - SSH 连接到 VM
   - xterm.js 实时终端
   - 双向数据传输
   - 连接/断开管理

3. ✅ 完整的 MVP 核心功能
   - VM 创建/删除
   - 实时终端访问
   - Web 界面管理
   - 准备添加实验内容

---

## 💡 下一步 (Day 3)

1. **添加实验内容**
   - Kubernetes Service 实验
   - NetworkPolicy 实验
   - Ingress 实验
   - DNS 调试实验

2. **优化和完善**
   - 添加用户认证
   - 实现 VM 自动清理（30 分钟）
   - 添加实验文档展示
   - 命令复制按钮

3. **生产部署**
   - Nginx 反向代理
   - Cloudflare Tunnel
   - SSL 证书
   - Systemd 服务

---

## 📚 参考资源

- [K3s 官方文档](https://docs.k3s.io/)
- [xterm.js 文档](https://xtermjs.org/)
- [Proxmox API 文档](https://pve.proxmox.com/pve-docs/api-viewer/)
- [WebSocket 协议](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [Paramiko SSH 库](https://www.paramiko.org/)

---

**祝 Day 2 顺利！🚀**
