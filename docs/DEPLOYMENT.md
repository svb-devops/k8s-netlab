# K8S NetLab 部署指南

## 🚀 快速开始（10分钟）

### 自动部署（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/k8s-netlab.git
cd k8s-netlab

# 2. 运行自动部署脚本
bash scripts/bootstrap.sh

# 3. 访问
# http://localhost:8000
```

脚本会自动：
- ✅ 检查Python版本（需要3.10+）
- ✅ 创建虚拟环境
- ✅ 安装所有依赖
- ✅ 引导创建配置文件
- ✅ 启动服务

### 手动部署

如果需要逐步控制每个环节：

```bash
# 1. 安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. 配置
cp .env.example .env
nano .env  # 至少填写 PROXMOX_HOST / PROXMOX_TOKEN_ID / PROXMOX_TOKEN_SECRET / VM_SSH_PASSWORD

# 3. 启动
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

---

## 环境要求

### 硬件要求
- CPU: 4核以上
- 内存: 8GB以上
- 磁盘: 50GB以上

### 软件要求
- Ubuntu 22.04 LTS（推荐）
- Python 3.10+
- Proxmox VE 7.0+（含K3s VM模板）

---

## 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/your-username/k8s-netlab.git
cd k8s-netlab
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置文件
nano .env
```

**必须配置的变量：**

| 变量 | 说明 | 示例 |
|------|------|------|
| `PROXMOX_HOST` | Proxmox服务器地址 | `192.168.1.10` |
| `PROXMOX_TOKEN_ID` | API Token（推荐）| `k8s-netlab@pve!netlab-token` |
| `PROXMOX_TOKEN_SECRET` | Token Secret | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `PROXMOX_NODE` | Proxmox节点名称 | `pve` |
| `VM_SSH_USER` | VM SSH用户名 | `root` |
| `VM_SSH_PASSWORD` | VM SSH密码 | （与模板保持一致） |
| `ALLOWED_ORIGINS` | CORS允许的域名 | `https://lab.example.com` |

> 若暂不使用 Token，可用旧密码认证作为过渡：
> `PROXMOX_USER=root@pam` + `PROXMOX_PASSWORD=...`（不推荐生产使用）

---

## Proxmox 认证配置

### 方式一：API Token（推荐，最小权限）⭐

API Token 是生产部署的最佳实践，不暴露 root 密码，且可随时吊销。

**在 PVE Shell 执行以下命令（一次性操作）：**

```bash
# 1. 创建专用服务账户
pveum user add k8s-netlab@pve --comment "K8S NetLab Service Account"

# 2. 创建最小权限角色
pveum role add K8SNetLab -privs \
  "VM.Audit VM.PowerMgmt VM.Clone VM.Allocate \
   VM.Config.Disk VM.Config.CPU VM.Config.Memory VM.Config.Network \
   Datastore.AllocateSpace"

# 3. 将角色分配给专用用户
pveum acl modify / -user k8s-netlab@pve -role K8SNetLab

# 4. 生成 API Token（secret 只显示一次，立即保存）
pveum user token add k8s-netlab@pve netlab-token --privsep 0
```

命令输出示例：
```
┌──────────────┬──────────────────────────────────────┐
│ key          │ value                                │
├──────────────┼──────────────────────────────────────┤
│ full-tokenid │ k8s-netlab@pve!netlab-token          │
│ value        │ xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx │
└──────────────┴──────────────────────────────────────┘
```

**在 `.env` 中配置：**

```bash
PROXMOX_TOKEN_ID=k8s-netlab@pve!netlab-token
PROXMOX_TOKEN_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# 无需 PROXMOX_USER / PROXMOX_PASSWORD
```

**验证 Token 生效：**

重启服务后，查看启动日志中应出现：
```
Auth: token (k8s-netlab@pve!netlab-token)
```

### 方式二：用户名 + 密码（仅开发/过渡期）⚠️

```bash
PROXMOX_USER=root@pam
PROXMOX_PASSWORD=your-password
```

> ⚠️ 生产环境不推荐：暴露 root 密码，权限过大，无法精确审计。

---

## SSL 证书验证

### 开发环境（自签名证书）

```bash
PROXMOX_VERIFY_SSL=false
```

### 生产环境（强烈推荐）

```bash
PROXMOX_VERIFY_SSL=true
```

⚠️ **生产环境安全建议：**

1. **使用受信任 CA 证书**：从可信 CA 获取证书，或使用 Let's Encrypt
2. **使用自签名证书**：需先将 CA 证书安装到系统信任链，再设置 `PROXMOX_VERIFY_SSL=true`
3. **`VERIFY_SSL=false` 的风险**：禁用证书验证，可能遭受中间人攻击，仅用于隔离的开发环境

**配置示例：**

```bash
# 生产环境（推荐）
PROXMOX_HOST=pve.example.com
PROXMOX_VERIFY_SSL=true

# 开发环境（自签名证书）
PROXMOX_HOST=10.0.0.110
PROXMOX_VERIFY_SSL=false
```

---

## CORS 配置

CORS 控制哪些外部域名可以跨域调用 API。

### 生产环境（需要设置）

```bash
# .env 中设置你的实际域名
ALLOWED_ORIGINS=https://lab.example.com

# 多域名（逗号分隔，无空格）
ALLOWED_ORIGINS=https://lab.example.com,https://admin.example.com
```

### 开发环境

```bash
ALLOWED_ORIGINS=http://localhost:8000
```

### 不设置（默认）

留空 = 拒绝所有跨域请求。适合通过 Nginx 反向代理且前后端同域的场景。

```bash
ALLOWED_ORIGINS=
```

**验证 CORS 生效：**

重启服务后，启动日志会显示：
- 已配置：`CORS allowed origins: ['https://lab.example.com']`
- 未配置：`CORS: ALLOWED_ORIGINS not set — all cross-origin requests will be blocked`

### 3. 安装依赖

```bash
pip install -r requirements.txt --break-system-packages
# 或在虚拟环境中
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. 启动服务

```bash
# 开发环境
python backend/main.py

# 或指定端口
APP_PORT=8000 python backend/main.py
```

### 5. 访问应用

```
http://your-server-ip:8000
```

---

## 生产环境部署

### 使用 systemd 管理服务

创建服务文件：

```bash
sudo nano /etc/systemd/system/k8s-netlab.service
```

内容：

```ini
[Unit]
Description=K8S NetLab Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/k8s-netlab
EnvironmentFile=/opt/k8s-netlab/.env
ExecStart=/usr/bin/python3 /opt/k8s-netlab/backend/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable k8s-netlab
sudo systemctl start k8s-netlab
sudo systemctl status k8s-netlab
```

### 配置 Nginx 反向代理（可选）

```bash
sudo nano /etc/nginx/sites-available/k8s-netlab
```

内容：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/k8s-netlab /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 安全建议

1. **环境变量**
   - 使用强密码（12位以上，含大小写字母、数字、特殊字符）
   - 定期更换密码
   - 永远不要将 `.env` 文件提交到 Git

2. **网络安全**
   - 配置防火墙，只开放必要端口（8000 或 80/443）
   - 使用 HTTPS（推荐使用 Let's Encrypt）
   - 限制 Proxmox API 的访问来源

3. **Proxmox 安全**
   - 使用 API Token 认证（`PROXMOX_TOKEN_ID` / `PROXMOX_TOKEN_SECRET`），避免暴露 root 密码
   - Token 对应专用用户 `k8s-netlab@pve`，仅分配 `K8SNetLab` 最小权限角色
   - 生产环境禁止使用 `PROXMOX_USER=root@pam` + 密码方式

4. **VM 模板安全**
   - 在 `.env` 中为 `VM_SSH_PASSWORD` 设置强密码
   - 创建 VM 模板时使用此密码，保持一致
   - 定期更换模板密码并重建模板

---

## 监控和维护

### 查看日志

```bash
# systemd 日志
sudo journalctl -u k8s-netlab -f

# 应用日志
tail -f logs/k8s-netlab.log
```

### 重启服务

```bash
sudo systemctl restart k8s-netlab
```

---

## 故障排查

### 问题1：服务启动失败

```bash
# 检查环境变量
cat .env

# 手动运行检查错误
python backend/main.py

# 检查依赖
pip install -r requirements.txt --break-system-packages
```

### 问题2：无法连接 Proxmox

```bash
# 验证 Proxmox 可访问性
curl -k https://$PROXMOX_HOST:8006/api2/json/version

# 检查凭据
echo "Host: $PROXMOX_HOST, User: $PROXMOX_USER"
```

### 问题3：VM 创建失败

- 检查 VM 模板是否存在（`VM_TEMPLATE_ID`）
- 检查 Proxmox 资源是否充足
- 查看 Proxmox 日志：`journalctl -u pve-manager`

---

## 获取帮助

- GitHub Issues: [项目地址]/issues
- 快速入门: [docs/QUICK-START.md](QUICK-START.md)
- 实验文档: [docs/experiments/](experiments/)

---

## 网络隔离

### 安全架构

K8S NetLab 使用独立网段 (`172.16.100.0/24`) 运行实验 VM，与家庭网络 (`10.0.0.0/24`) 完全隔离。

**网络拓扑：**

```
互联网
  |
家庭路由器 (<GATEWAY_IP>)
  |
  +-- 家庭 WiFi 网段 (10.0.0.0/24)  # example network
  |     |-- 手机、电脑、IoT 设备
  |     |
  |     +-- PVE 宿主机 (<HOST_IP>)
  |           |
  |           +-- vmbr0 (管理网络, <HOST_IP>/24)
  |           |
  |           +-- vmbr1 (隔离网桥, 172.16.100.1/24)
  |                 |
  |                 +-- K8S NetLab VMs (172.16.100.10-254, DHCP)
  |                       |
  |                       +-- ✅ 可访问外网 (via NAT)
  |                       +-- ❌ 不可访问家庭网络
```

**防火墙规则（iptables FORWARD 链）：**

| 规则 | 源             | 目标            | 动作   |
|------|----------------|-----------------|--------|
| 1    | vmbr1 → vmbr1  | any             | ACCEPT |
| 2    | 172.16.100.0/24 | 10.0.0.0/24    | DROP   |
| 3    | 10.0.0.0/24    | 172.16.100.0/24 | DROP   |
| 4    | vmbr1 → vmbr0  | any             | ACCEPT |
| 5    | vmbr0 → vmbr1  | ESTABLISHED     | ACCEPT |

**NAT：** `172.16.100.0/24 → MASQUERADE`（VM 通过 PVE 宿主机出口访问外网）

### PVE 配置

**vmbr1（/etc/network/interfaces）：**

```
auto vmbr1
iface vmbr1 inet static
    address 172.16.100.1/24
    bridge-ports none
    bridge-stp off
    bridge-fd 0
```

**DHCP 服务（/etc/dnsmasq.d/vmbr1-dhcp.conf）：**

- 地址池：`172.16.100.10` – `172.16.100.254`
- 租约：12小时
- DNS：`8.8.8.8`, `8.8.4.4`

### 验证隔离效果

在任意实验 VM 内运行：

```bash
# ✅ 应该通（外网访问）
ping -c 3 8.8.8.8

# ❌ 应该不通（家庭网络隔离）
ping -c 3 <GATEWAY_IP>

# ✅ 应该通（网关）
ping -c 3 172.16.100.1
```

第2个 ping 超时无响应，说明隔离配置正确。

### 环境变量

在 `.env` 中配置：

```env
VM_NETWORK=172.16.100.0/24
VM_GATEWAY=172.16.100.1
VM_BRIDGE=vmbr1
VM_IP_START=10
VM_IP_END=254
```
