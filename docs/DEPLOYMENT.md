# K8S NetLab 部署指南

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
| `PROXMOX_USER` | Proxmox用户名 | `root@pam` |
| `PROXMOX_PASSWORD` | Proxmox密码 | （使用强密码） |
| `PROXMOX_NODE` | Proxmox节点名称 | `pve` |
| `VM_SSH_USER` | VM SSH用户名 | `k8s_lab` |
| `VM_SSH_PASSWORD` | VM SSH密码 | （与模板保持一致） |

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
   - 为本项目创建专用用户（不要直接用 root）
   - 限制用户权限范围
   - 启用双因素认证

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
家庭路由器 (10.0.0.1)
  |
  +-- 家庭 WiFi 网段 (10.0.0.0/24)
  |     |-- 手机、电脑、IoT 设备
  |     |
  |     +-- PVE 宿主机 (10.0.0.110)
  |           |
  |           +-- vmbr0 (管理网络, 10.0.0.110/24)
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
ping -c 3 10.0.0.1

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
