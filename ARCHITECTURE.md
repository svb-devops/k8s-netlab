# K8S NetLab — 架构决策记录

本文记录每个重要设计决策的**原因**，而不是"是什么"。
代码告诉你"是什么"，这里告诉你"为什么"。

任何人（包括从未接触过本项目的 Claude 实例）读完本文，
应当能够理解系统的边界、取舍，以及不能随意更改的约束。

---

## 1. 存储：JSON 文件，而不是数据库

**决策**：用户、session、VM 归属均存在 `data/*.json`，用 flock 保证原子读写。

**为什么不用 SQLite / PostgreSQL / Redis：**
- 用户量极小（几十人级别），数据库的收益为零
- JSON 文件可以直接 `cat` 查看，出问题时不需要 SQL 知识
- 备份只需 `cp *.json`，无需 `pg_dump`
- 部署零依赖，不需要额外启动数据库进程

**代价**：
- 并发写入风险 → 用 `flock` + 原子 `os.replace()` 解决
- 不支持复杂查询 → 目前没有这个需求

**禁止随意更换**：如果用户量增长到数百人且出现性能瓶颈，再迁移数据库。现在不要动。

---

## 2. VM 克隆：Linked Clone，而不是 Full Clone

**决策**：`clone.post(full=0)` — 共享模板磁盘，不复制。

**为什么：**
- Full clone 需要 2–5 分钟复制整个磁盘镜像
- Linked clone 只需 3–10 秒（只写 CoW 差异层）
- 学生等待 VM 创建的体验从"无法接受"变成"可以接受"

**代价**：
- 所有 VM 依赖模板磁盘，模板被删除 → 所有 VM 损坏
- **因此：模板 VM（ID=100）绝对不能删除，操作前必须 `qm config 100` 确认**

**血泪教训**：曾误删 VM 100 导致所有用户环境损坏，根因是 VMID 全局共享。
参见 `RUNBOOK.md` 场景四。

---

## 3. K3s 重置：QEMU Agent，而不是 SSH

**决策**：新 VM 启动后，通过 `qemu-guest-agent` exec 接口清除 K3s stale etcd，而不是 SSH。

**为什么：**
- VM 刚克隆启动时，SSH 服务尚未就绪（需要 30–60 秒）
- QEMU agent 在 VM 启动后几秒内即可使用，比 SSH 早
- K3s 重置必须在 SSH 建立之前完成，否则 K3s 会带着旧 etcd 状态启动，
  导致 `kubectl` 命令报错或节点处于错误状态

**关键顺序**（不能调换）：
```
VM 克隆完成 → QEMU agent 重置 K3s → VM IP 就绪 → SSH 连接 → 终端开放给用户
```

---

## 4. Registry Mirror：宿主机本地缓存

**决策**：K8s 实验中拉取镜像走宿主机 `172.16.100.1:5000`（Docker Registry v2），不走公网。

**为什么：**
- VM 网络隔离在 `vmbr1`（172.16.100.0/24），对外访问受限
- 实验涉及 `kubectl apply` 拉取镜像（nginx、busybox 等），若每次走公网：
  - 速度慢（实验室带宽有限）
  - 可能因网络波动导致实验失败，与 K8s 知识点无关
- 宿主机预先 `docker pull` 并推到本地 registry，VM 从内网拉取，毫秒级

**配置**：`VM_REGISTRY_MIRROR` 环境变量，默认 `http://<VM_GATEWAY>:5000`。

---

## 5. 网络隔离：每项目独立 Bridge

**决策**：k8s-netlab 使用 `vmbr1`（172.16.100.0/24），与其他项目的 bridge 完全隔离。

**为什么：**
- 不同项目的 VM 之间必须无法互通（安全隔离）
- vmbr1 的 iptables 规则阻断了到 vmbr0（宿主管理网）和其他 bridge 的流量
- K8s 实验需要节点间互通，所以 vmbr1 内部允许 VM→VM 通信

**不能改的约束**：
- 不能把 k8s-netlab VM 挂到 vmbr0（宿主机管理网）
- 不能删除 iptables FORWARD DROP 规则
- 新项目必须分配新 bridge，参见全局 `CLAUDE.md` 中的桥接分配表

---

## 6. Session 管理：无状态 Cookie + JSON 文件

**决策**：登录后生成 UUID token，存入 `sessions.json`，通过 HttpOnly cookie 传递。

**为什么不用 JWT：**
- JWT 无法主动吊销（token 在有效期内永远有效）
- 服务端 session 可以精确控制：登出即失效，强制下线即时生效
- 实现更简单，调试更直观

**为什么不用 Redis：**
- 见决策 1，零额外依赖原则

**一用户一 session 原则**：登录时清除该用户所有旧 session，防止 JSON 文件无限增长。
（这是曾经出现过的 bug，已有回归测试固化。）

---

## 7. 前端：原生 HTML/JS + CDN，而不是 React/Vue

**决策**：所有页面用 `index.html`、`login.html`、`admin.html`，JS 直接写，CSS 用 Tailwind CDN。

**为什么：**
- 没有构建步骤，改一行 HTML 刷新浏览器即生效
- 部署不需要 `npm build`，不存在"前端编译失败导致部署卡住"
- 功能简单（登录 + 终端 + 文档阅读），不需要组件框架
- xterm.js 和 marked.js 直接 CDN 引入，无需本地 node_modules

**代价**：
- 代码复用靠手动，没有组件化
- 随着功能增加，JS 文件会越来越长

**何时需要重构**：页面超过 5 个，或单个 JS 文件超过 1000 行。现在不需要。

---

## 8. Proxmox 权限：Token + Pool 隔离

**决策**：使用 Proxmox API Token（`k8s-netlab@pve!netlab-token`），权限仅限于 `k8s-netlab` pool。

**为什么不用 root 密码：**
- Token 可随时吊销，不影响 Proxmox 其他管理
- 权限最小化：即使 token 泄露，攻击者只能操作 k8s-netlab pool 内的 VM

**关键约束**：
- 模板 VM 必须加入 pool：`pvesh set /pools/k8s-netlab --vms 100`
- 忘记加 pool → 克隆报 403，参见 `MEMORY.md` 中的"Proxmox 权限关键规则"

---

## 9. 无 Staging 环境

**决策**：没有独立的测试环境，修改直接在生产部署。

**为什么：**
- 额外一套 Proxmox 环境成本高
- 用户量小，bug 影响范围有限，修复速度快
- 用 pytest 测试套件（256 tests，83% 覆盖率）+ 回归测试代替 staging 的验证作用

**补偿措施**：
- pre-push hook 强制通过全量测试才能 push
- 每次部署后必须检查 `/api/health` + 错误日志
- UptimeRobot 5 分钟告警

**何时需要 staging**：用户量达到数百人，或团队超过 2 人同时开发。

---

## 10. 异步 VM 操作：run_in_executor

**决策**：`create_vm` 和 `delete_vm` 通过 `asyncio.run_in_executor(None, ...)` 在线程池运行。

**为什么：**
- Proxmox API 调用是同步阻塞的（`proxmoxer` 库不支持 async）
- 如果直接在 async 函数中调用，会阻塞整个事件循环
- 阻塞事件循环意味着：VM 创建期间，所有其他用户的请求全部卡住

---

## 系统边界图

```
用户浏览器
    │
    │ HTTPS (lab.cloudnetops.tech)
    ▼
FastAPI (port 8000)
    │
    ├── 静态文件 (frontend/*.html, /js/*, /css/*)
    ├── REST API (/api/*)
    ├── WebSocket (/ws/terminal/{vm_id})
    │
    ├── data/*.json  ←→  flock 原子读写
    │
    └── Proxmox API (127.0.0.1:8006)
            │
            ├── VM 克隆/删除/状态查询
            ├── QEMU Agent (K3s重置、IP获取、密码同步)
            └── vmbr1 (172.16.100.0/24)
                    │
                    └── VM 100 (模板) + 用户 VM (101–199)
                            │
                            └── K3s + registry mirror (172.16.100.1:5000)
```
