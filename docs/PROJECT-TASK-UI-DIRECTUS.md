# 项目任务书：UI 重构 + Directus 后端升级

**版本**：v0.1  
**日期**：2026-06-06  
**状态**：待排期  

---

## 背景

当前 k8s-netlab 平台存在两个独立问题：

1. **界面拥挤**：实验文档、终端、导航在同一屏挤在一起，学生体验差
2. **基础设施不足**：用户管理依赖 JSON 文件、无管理后台、实验内容写死在代码里

两个问题独立解决，分两个阶段推进。

---

## 阶段一：UI 重构（低风险，优先上线）

### 目标

终端是主角，文档是辅角。消除三栏挤压，让终端占据主视图，实验文档以侧边 drawer 形式按需展开。

### 参考

iximiuz Labs 布局策略：左侧可折叠导航 + 终端主区域 + 文档 overlay。

### 具体任务

#### T1-1：引入可拖拽分割线

- 引入 [Split.js](https://split.js.org/)（2KB，零依赖）
- 左侧内容面板（实验文档/背景/AI 助教）默认占 35%
- 右侧终端默认占 65%
- 分割线可拖拽，位置存 `localStorage` 记住用户偏好
- 验收：拖拽后刷新，位置保持

#### T1-2：实验文档改为侧边 Drawer

- 默认状态：文档 drawer 收起，终端占全宽
- 顶部工具栏：「实验文档」按钮，点击展开 drawer（从左侧滑入）
- Drawer 宽度：固定 420px，不压缩终端（改用 CSS `position: fixed`）
- 三个 tab（实验文档 / 实验背景 / AI 助教）保留在 drawer 内
- 验收：关闭 drawer 后终端全宽，xterm.js `fitAddon.fit()` 正确触发

#### T1-3：终端全宽时自动 fit

- 监听 drawer open/close 事件，每次状态变化后调用 `fitAddon.fit()`
- 避免 xterm.js 字符宽度错位
- 验收：drawer 展开/收起时终端字符不错位

#### T1-4：移动端最小适配

- 屏幕宽度 < 768px 时：隐藏文档 drawer，仅保留终端
- 顶部显示 「查看文档」按钮，点击全屏覆盖显示
- 验收：手机横屏可用终端，不出现横向滚动条

#### T1-5：视觉细节优化

- 导航栏高度压缩（当前过高）
- 实验状态（难度、预计时长）移到 drawer 顶部，减少左侧导航占用
- 字体大小、行高、间距对齐 Tailwind 规范

### 技术选型

| 工具 | 用途 | 引入方式 |
|------|------|---------|
| Split.js 1.6.x | 可拖拽分割线 | CDN |
| CSS `position: fixed` | Drawer 不影响布局流 | 手写 |
| localStorage | 记住分割位置 | 原生 JS |

### 不引入

- React / Vue / 任何前端框架（保持现有纯 HTML + Tailwind 架构）
- 新的 CSS 框架（继续用 Tailwind CDN）

### 测试要求

- 补前端 playwright/cypress E2E 测试（或手动测试清单）
- 终端 fit 行为：每个 drawer 状态变化后验证一次
- 覆盖率不影响现有 Python 测试基线（90%+）

### 工作量估算

| 任务 | 估计 |
|------|------|
| T1-1 Split.js 集成 | 2h |
| T1-2 Drawer 重构 | 4h |
| T1-3 终端 fit 联动 | 1h |
| T1-4 移动端适配 | 2h |
| T1-5 视觉细节 | 2h |
| 测试 + 验收 | 3h |
| **合计** | **~14h** |

---

## 阶段二：Directus 后端升级（中等工程量）

### 目标

用 Directus 替代当前 JSON 文件用户系统，获得：管理后台、RBAC、实验内容 CMS、Webhook 集成。FastAPI 保留 VM 管理 + WebSocket SSH。

### 架构

```
前端 (HTML/JS)
  ├── 认证：Directus JWT → 颁发 / 刷新 / 校验
  ├── 实验内容：Directus REST API（读取实验文档、背景、步骤）
  └── VM 终端：FastAPI WebSocket（不变）

Directus（新增）
  ├── PostgreSQL（替代 data/*.json）
  ├── 用户集合：用户、角色（学生 / 管理员）
  ├── 实验集合：实验列表、步骤、背景、标签
  ├── Admin UI：非技术人员可直接管理内容
  └── Flow / Webhook：内容发布触发通知

FastAPI（保留，改动最小）
  ├── 删除：AuthManager + 自定义 JWT 签发
  ├── 新增：验证 Directus JWT 的 middleware（verify_directus_token）
  ├── 保留：Proxmox VM 生命周期、WebSocket SSH、VM tracker、rate limiter
  └── 保留：storage_utils（仅用于 VM 状态数据，不用于用户/内容）
```

### 具体任务

#### T2-1：Directus 部署

- 编写 `docker-compose.directus.yml`（Directus + PostgreSQL）
- 资源：2 vCPU + 1GB RAM（宿主机新增，或复用现有 VM）
- 端口：Directus 内部 8055，通过 Cloudflare Tunnel 暴露（子域名：`admin.cloudnetops.tech`）
- 持久化：PostgreSQL data volume + uploads volume
- 验收：`https://admin.cloudnetops.tech` 可访问 Directus Admin

#### T2-2：数据 Schema 设计

Directus 集合设计：

```
users（Directus 内置）
  - email, password, role, status, last_login

roles（Directus 内置）
  - student（默认）
  - admin

experiments
  - id, slug, title, difficulty(1-5), duration_min
  - category（网络实验 / 部署案例）
  - status（draft / published）
  - sort_order

experiment_steps
  - experiment_id (M2O)
  - step_number, title, content (Markdown), hints

experiment_backgrounds
  - experiment_id (O2O)
  - content (Markdown), references (JSON)

vm_sessions（可选，迁移自 data/sessions.json）
  - user_id, vm_id, created_at, expires_at, status
```

#### T2-3：迁移现有数据

- `data/users.json` → Directus users（bcrypt 密码直接迁入，Directus 支持自定义 hash）
- 实验内容（`docs/experiments/*.md`）→ Directus `experiments` + `experiment_steps`
- 编写迁移脚本：`scripts/migrate_to_directus.py`
- 验收：所有现有用户可正常登录，实验内容完整显示

#### T2-4：FastAPI 认证改造

- 删除 `backend/auth.py` 中 JWT 签发逻辑
- 新增 `backend/auth_directus.py`：
  ```python
  async def verify_directus_token(token: str) -> DirectusUser:
      # 调用 Directus /users/me，验证 token 有效性
      # 返回用户信息（id, role, email）
  ```
- 所有现有 `Depends(get_current_user)` 改为 `Depends(verify_directus_token)`
- 保留速率限制逻辑（改为基于 user_id，而非自定义 session）
- 验收：现有全部 API 测试通过，覆盖率不低于 90%

#### T2-5：前端认证改造

- 登录：调用 `POST /directus/auth/login` → 获取 access_token + refresh_token
- Token 刷新：静默刷新（access_token 15min 过期，refresh_token 7 天）
- 所有 API 请求带 `Authorization: Bearer <directus_token>`
- 管理员入口：`/admin` 直接跳转 Directus Admin UI

#### T2-6：实验内容 API 改造

- 删除当前 FastAPI 中返回实验内容的路由（或保留为 proxy）
- 前端直接调用 Directus REST API 获取实验列表、步骤、背景
- Directus 配置 Public role 只读权限（无需 token 即可读取已发布实验）

#### T2-7：管理员功能

- Directus Admin UI 即为管理员后台
- 学生管理：查看 / 禁用用户、修改 quota
- 实验管理：增删改实验内容、发布 / 下线
- VM 监控：保留现有 FastAPI `/admin` 端点（Directus 无法替代 Proxmox 操作）

#### T2-8：回归测试

- 覆盖 `verify_directus_token` 的 mock 测试（不真实调用 Directus）
- 所有现有测试用例通过（378+ passed, 90%+ coverage）
- 新增：实验内容 API 测试（Directus mock）

### 技术选型

| 组件 | 版本 | 用途 |
|------|------|------|
| Directus | 11.x | CMS + 用户管理 |
| PostgreSQL | 16 | Directus 数据库 |
| httpx（已有） | - | FastAPI → Directus token 验证 |

### 不引入

- 不引入 Directus SDK（直接 REST API，减少依赖）
- 不迁移 VM 状态数据到 Directus（VM tracker 继续用 JSON + flock）
- 不做 SSO（学生直接在平台注册，不接 GitHub/Google 登录）

### 工作量估算

| 任务 | 估计 |
|------|------|
| T2-1 Directus 部署 | 3h |
| T2-2 Schema 设计 | 4h |
| T2-3 数据迁移脚本 | 4h |
| T2-4 FastAPI 认证改造 | 6h |
| T2-5 前端认证改造 | 4h |
| T2-6 实验内容 API | 3h |
| T2-7 管理员功能验收 | 2h |
| T2-8 回归测试 | 6h |
| **合计** | **~32h** |

---

## 依赖关系

```
阶段一（UI 重构）
  └── 无外部依赖，可独立开始

阶段二（Directus）
  ├── 依赖：宿主机有空余资源（1GB RAM）
  ├── 依赖：PostgreSQL 持久化方案确认
  └── 不依赖阶段一完成
```

两个阶段可并行，但建议先完成阶段一上线，再启动阶段二（降低同时变动的风险）。

---

## 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| xterm.js fit 在 drawer 切换时错位 | 中 | 低 | 在 drawer transition 结束后延迟 100ms 调用 fit |
| Directus token 验证延迟增加 API 响应时间 | 低 | 中 | 在 FastAPI 侧缓存 token 验证结果（TTL 60s） |
| 数据迁移丢失用户密码 | 低 | 高 | 迁移前完整备份，灰度验证（先迁管理员账号） |
| Directus 资源占用超预期 | 低 | 中 | 提前在测试 VM 上 benchmark，确认宿主机余量 |

---

## 验收标准

### 阶段一上线标准

- [ ] 终端全宽时不出现字符错位
- [ ] drawer 展开/收起动画流畅（< 300ms）
- [ ] 分割线位置刷新后保持
- [ ] 移动端（768px 以下）可正常使用终端
- [ ] 现有 Python 测试全部通过

### 阶段二上线标准

- [ ] 所有现有用户可正常登录（密码未变）
- [ ] 管理员可通过 Directus Admin 管理实验内容
- [ ] FastAPI 所有 VM 操作 API 正常（覆盖率 ≥ 90%）
- [ ] 实验内容（11 个实验）完整展示
- [ ] Directus Admin 地址可访问

---

## 开始条件

**阶段一**：随时可以开始，只需确认「drawer 还是 split 哪种 UI 形态优先」。

**阶段二**：需要确认：
1. 宿主机可用 RAM 余量（`free -h`）
2. Directus Admin 域名（`admin.cloudnetops.tech` 还是其他）
3. 是否保留现有 `/admin` FastAPI 端点（双入口 or 迁移到 Directus）
