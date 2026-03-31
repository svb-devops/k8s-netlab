# Changelog

所有版本变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased]

### Changed
- refactor: pre-commit hook 加 CHANGELOG 机械门禁（有代码变更未更新 CHANGELOG 则阻断 commit）；bug-fix.md / feature.md 重构为"3-4 项必做 + 延伸阅读"结构，区分机械门禁和 Claude 自律，消除安全感幻觉
- test: 补全 storage_utils 锁模式和嵌套路径测试 — 验证读用 LOCK_SH、写用 LOCK_EX、父目录自动创建
- chore: 对齐 opsreplay 最佳实践 — settings.json 加 deny 列表、CI 覆盖率门禁提升至 90%、mypy 加严 warn_return_any/check_untyped_defs、新增 smoke-test skill 和 Makefile

### Fixed
- test: 补全 storage_utils/rate_limiter/auth_deps 未覆盖路径 — 覆盖率 88.84% → 91.19%（storage_utils 错误路径全覆盖、rate_limiter is_over_limit/record 独立单元测试、auth_deps invalid session/optional 依赖新增 test_auth_deps.py）
- fix: auth_routes.py register 接口速率限制仅在注册成功时记录，注册失败（用户名已存在）不消耗限速槽 — 允许攻击者无限探测用户名；将 rate_limiter.record() 移至 register_user() 调用之前，无论结果均记录；补回归测试防止重现
- fix: middleware.py JsonFormatter.format() 缺少 default=str — 当 extra 包含非 JSON 可序列化字段（如 datetime）时 json.dumps 抛 TypeError，Python logging 静默丢弃整条记录；补回归测试防止重现
- fix: websocket.py get_vm_ip/sync_vm_password 直接在 event loop 调用阻塞 Proxmox I/O — 提取同步 helper，通过 run_in_executor + wait_for(timeout) 包裹，防止终端建立期间阻塞所有请求；SSHTerminal.connect() 的 invoke_shell() 同样移入 executor；修复 invoke_shell 失败时 SSH 连接泄漏；补4条回归测试防止重现
- fix: smart_logger.py generate_report() 调用 print() 破坏结构化 JSON 日志一致性 — 改为 self.logger.info()；补回归测试防止重现
- fix: DELETE /api/vms/{id} 403 响应泄露 VM owner 用户名 — 从 detail 中移除 owner 用户名（信息泄露），owner 仍记录在服务端日志；补回归测试防止重现
- refactor: 移除 auth.py 中从未被调用的 _save_users / _save_sessions 死代码（全部写操作均走 safe_update_json）
- fix: test_serial_second_creation_blocked_by_quota 死锁 — iter([...]) side_effect 耗尽抛 StopIteration，Python 3.7+ 禁止将 StopIteration 设入 asyncio.Future，导致 run_in_executor await 永不返回；改为 side_effect 函数避免抛 StopIteration；同时补充第 3 次 list_vms 调用（req1-_find_available_vm_id 遗漏）
- feat: 引入 safety-reviewer subagent — 9 项检查清单 + A/B/C 分级触发 + 硬/软失败策略 + 外部升级条件
- fix: create_vm 配额检查前对账 tracker 与 Proxmox，自动清除孤儿条目，彻底杜绝假性 429 配额超限（孤儿 VM 回归，出现两次）；补回归测试防止重现
- fix: 点击"终端"按钮无反应 — terminal.js 在 terminal-section 仍为 display:none 时调用 xterm.js open()/fitAddon.fit()，导致终端无法初始化；改为先 remove('hidden') 再 open/fit；无后端回归测试（纯前端 bug）
- fix: CSP style-src 缺 'unsafe-inline' 导致 Tailwind Play CDN 样式注入被拦截 — 页面所有布局/颜色/尺寸完全失效，SVG 图标全宽渲染；script-src 保持严格；补回归测试防止重现
- fix: HEAD /api/health 返回 405 导致 UptimeRobot 监控持续误报 — 新增 HEAD 路由返回 200 空响应；补回归测试防止重现
- fix: admin_routes.py GET /api/admin/status 当 sessions.json 存在损坏条目（缺 username/created_at/expires_at）时整个端点 500 崩溃 — 改为跳过损坏条目并记录 warning，正常条目继续返回；补回归测试防止重现
- fix: main.py auto_cleanup_task 匹配 "VM 不存在" 时 warning 日志缺失原始 Proxmox 错误串 — 加入 reason 字段便于跨版本调试；补回归测试防止重现

- fix: 登录/注册 IP 提取忽略 Cloudflare Tunnel 转发头 — _get_client_ip() 在受信任代理（loopback）连接时优先读 CF-Connecting-IP/X-Forwarded-For，防止速率限制所有用户共享同一个 IP 桶；补 6 条回归测试防止重现
- refactor: api_health_check() 去掉重复 Proxmox version.get() 调用（connect_proxmox 内部已验证，改为直接调 connect_proxmox）
- refactor: 删除 get_node_status() 死代码及其 3 个测试（proxmox_api.py，无 API endpoint 无调用者）
- feat: SecurityHeadersMiddleware 新增 Permissions-Policy: geolocation=(), camera=(), microphone=() 头，限制浏览器敏感 API 访问

### Fixed
- fix: change_password/reset_password 后未作废现有 session — 密码变更后立即清除该用户所有 session，防止泄露的 cookie 在 24h 内继续有效；补回归测试防止重现
- refactor: 删除 start_vm() 死代码 — 无 API endpoint 无调用点，vm_manager.py 覆盖率从 72% 升至 90%
- refactor: _find_available_vm_id() 和 api_health_check() 改走 run_in_executor，避免同步 Proxmox HTTP 请求阻塞 asyncio 事件循环
- refactor: FastAPI app version 从 "0.1.0" 改为 "1.1.0"，与 git tag 一致
- refactor: CORS allow_headers 移除 Authorization（本应用不使用该 header）

### Fixed
- fix: 注册接口无速率限制 — POST /register 加 3次/IP/60s 限制，防 bcrypt CPU 耗尽 DoS；补回归测试防止重现
- fix: SmartLogger 重复创建同名实例会累积 FileHandler 泄漏 FD — _setup_logging() 先 close/remove 旧 handler 再添新 handler；补回归测试防止重现
- fix: CI ADMIN_TOKEN 仅 14 字符，与 config.py ≥32 校验不符 — 改为 38 字符占位值
- fix: app.js vm.name + admin.js login_ip/login_location 直接插入 innerHTML — 加 escapeHtml() 防第三方数据注入
- fix: DOMPurify 加入 marked.js 渲染管道 — index.html 引入 DOMPurify@3.2.6（SRI sha384），docs.js renderMarkdown() 用 DOMPurify.sanitize() 包裹输出，防御 Markdown 注入的非脚本 payload（meta refresh 等）
- fix: bootstrap.sh + cleanup_test_vms.sh 改用 set -euo pipefail，与其余脚本保持一致，管道失败不再静默忽略
- fix: SSHTerminal.receive() 中 asyncio.get_event_loop() 改为 get_running_loop()（S1，第七轮漏网之鱼）；补回归测试防止重现
- fix: wait_for_k3s 中 assert ssh_client is not None 改为显式 if guard + break，避免 -O 模式下 assert 被剥离
- fix: _fetch_geo() 静默吞掉所有异常改为 logger.debug 记录，便于调试地理位置解析失败
- fix: create_vm/delete_vm run_in_executor 加 asyncio.wait_for 超时（360s/120s），Proxmox 挂起时返回 504 而非永久阻塞线程池（B2）；补回归测试防止重现
- fix: websocket.py 静默异常（except Exception: pass）改为记录 warning（C1）；get_event_loop() 改为 get_running_loop()（S）；补回归测试防止重现
- fix: ADMIN_TOKEN 长度不足 32 字符时启动抛 RuntimeError，防止弱 token 被暴力破解（H3）；补回归测试防止重现
- fix: Cookie SameSite 从 lax 改为 strict，消除 CSRF 攻击面（I2）；补回归测试防止重现
- fix: proxmox_api INFO 日志移除 token_user/token_name，防止凭据泄漏到日志系统（A1）；补回归测试防止重现
- fix: GET /api/vms/{vm_id}/status 非归属用户返回 Forbidden 而非 "You do not own this VM"，防止 VM ID 枚举（A2）；补回归测试防止重现
- fix: VM_REGISTRY_MIRROR 未配置时记录 WARNING，提示 HTTP fallback 不安全（H1）；补回归测试防止重现
- fix: CSP 移除 'unsafe-inline' — 将三个 HTML 页面内联脚本/样式提取到外部文件（tailwind-config.js、app.css、ui-init.js、admin.js），SecurityHeadersMiddleware CSP 不再含 script-src/style-src unsafe-inline；补回归测试防止重现
- fix: health 不健康时不暴露原始异常（改为通用错误字符串），同时清理 version_info 死代码
- fix: auto_cleanup_task 中 asyncio.get_event_loop() 改为 get_running_loop()（避免 Python 3.10 废弃警告）
- fix: GET /api/vms 和 GET /api/vms/{vm_id}/status 中阻塞 Proxmox I/O 改用 run_in_executor，防止高并发时阻塞 event loop
- fix: GET /api 端点移除 version 字段，与 health 端点去指纹精神一致
- refactor: list_vms() 从 SmartLogger 改为普通 logger，避免频繁轻量调用产生大量磁盘 report 文件
- fix: config.py 启动交叉校验 — VM_TEMPLATE_ID 不得落在 VM_ID_MIN..MAX 范围内；MAX_VMS_PER_USER 不得超过 MAX_TOTAL_VMS；补 2 个回归测试防止重现
- fix: health 端点移除指纹信息 — 不再返回 version/host/node，只返回 {status, proxmox.connected}；补 1 个回归测试防止重现
- fix: vm_tracker._load_data 对非数字 key 用 isdigit() 过滤 — 文件损坏时不再崩溃；补 2 个回归测试防止重现
- fix: create_vm handler 显式校验 vm_id 范围 — 超出 VM_ID_MIN..VM_ID_MAX 返回 422；补 1 个回归测试防止重现
- fix: docs_routes 路径遍历防御 — 读实验文件前加 .resolve() + 前缀校验；补 1 个回归测试防止重现
- fix: auto_cleanup_task 每轮调用 cleanup_expired_sessions() — 过期 session 不再残留；补 1 个回归测试防止重现
- fix: RequestIDMiddleware 记录请求日志含 duration_ms + status_code；JsonFormatter 支持 extra 字段；补 2 个回归测试防止重现
- ops: CI 加 pip-audit + bandit 安全扫描门禁 — pip-audit 检测依赖 CVE，bandit -lll 阻断 HIGH 级别静态漏洞；websocket.py 已知可接受风险标注 nosec
- fix: 生产环境 500 响应泄露内部异常信息 — `APP_DEBUG=False` 时统一返回 `"Internal server error"`，细节只写入日志；补 2 个回归测试防止重现
- fix: LoginRequest.username 缺 pattern 校验 — 登录接口补齐与注册相同的 `^[a-zA-Z0-9_-]+$` 约束，特殊字符返回 422；补 1 个回归测试防止重现
- fix: vm_tracker 旧格式迁移 bug — `track_vm()` 对已有条目覆盖 `created_at` 为 `now()`，改为保留原始时间戳；补 3 个回归测试防止重现

### Security
- fix: GET /api/vms/{vm_id}/status 无认证 — 加 `get_current_user` 依赖 + 归属校验，未登录返回 401，非归属用户返回 403；补 2 个回归测试防止重现
- fix: 孤儿 VM 自动认领不检查配额 — 认领前验证 `len(user_vm_ids) < MAX_VMS_PER_USER`，配额满时记录 warning 并跳过；补 1 个回归测试防止重现
- fix: session cookie `secure` 硬编码 False — 改为读 `SESSION_COOKIE_SECURE` env var（默认 True），本地开发 .env 设 false；补 1 个回归测试防止重现
- feat: HTTP 安全响应头 — `SecurityHeadersMiddleware` 全局注入 X-Content-Type-Options/X-Frame-Options/Referrer-Policy/CSP；5 个测试覆盖
- fix: 升级 CVE 依赖 — fastapi 0.104.1→0.135.2, starlette 0.27→0.52.1, python-multipart 0.0.6→0.0.22, requests 2.31→2.33.0, pydantic 2.5→2.12.5；清除 9 个 CVE（pygments CVE-2026-4539 暂无修复版本）
- fix: 重新生成 requirements.lock 锁定所有传递依赖版本

### Fixed
- fix: httpx 从 Testing 分组移至生产依赖 — admin_routes.py 在生产中用它做 IP 地理定位
- fix: vm_manager create_vm 部分失败无回滚 — clone 成功后 pool/config/start 任一步骤失败时自动删除孤儿 VM；补 5 个回归测试覆盖各失败场景
- fix: SmartLogger 日志文件在 root logger 已有 handler 时为空 — 改用直接挂 FileHandler 到子 logger，绕过 basicConfig 的 no-op 陷阱；补回归测试防止重现
- fix: pytest-asyncio 漏加进 requirements.txt — 补声明 + 重新生成 requirements.lock；pytest.ini 加 asyncio_mode=auto 消除隐式警告

### Added
- feat: CDN SRI integrity 属性 — xterm.js / marked / highlight.js 所有 jsdelivr 资源加 sha384 哈希，防 CDN 投毒
- feat: 结构化 JSON 日志 — `backend/middleware.py` JsonFormatter，每条日志一行 JSON（timestamp/level/logger/message/exc_info）
- feat: X-Request-ID middleware — 每个 HTTP 请求自动注入 UUID4，客户端可自带，响应头回显
- feat: ruff + mypy 接入 CI — 每次推送自动 lint + 类型检查；pyproject.toml 固化规则
- fix: 修复 smart_logger/websocket/docs_routes 中 8 处 mypy 类型注解错误（Optional、union-attr）
- fix: 修复 websocket.py 3 处 bare except → except Exception
- feat: 优雅关闭 — backend/task_registry.py 追踪 in-flight VM 操作，lifespan shutdown 等待 30s 后才退出，防止孤儿 VM
- feat: pip-tools 依赖锁文件 — requirements.lock 固定所有传递依赖版本，CI 验证锁文件与 requirements.txt 同步
- feat: Prometheus metrics 端点 — /metrics 暴露请求数、延迟分布等指标（prometheus-fastapi-instrumentator）

---

## [1.1.0] - 2026-03-25

### Added
- 数据自动备份：`scripts/backup-data.sh`，每日凌晨 3 点 cron，保留 30 天
- UptimeRobot 监控接入：`/api/health` 端点（已存在，正式纳入监控体系）
- 容量管理：`MAX_TOTAL_VMS=15`，满员返回 503 + 当前人数，前端显示 amber banner
- `scripts/prep-template.sh`：模板重建脚本（预拉镜像 + 清空 etcd）
- `scripts/test-experiment.sh`：11 个实验自动化端到端验证

### Fixed
- 登录时清除同用户旧 session，防止 sessions.json 无限堆积
- Pydantic V2 兼容：`class Config` 改为 `model_config = ConfigDict`
- 删除 VM 后联动关闭终端面板
- `CreateVMRequest` 移除 `template_id`，服务端通过 `config.VM_TEMPLATE_ID` 独占控制，防止模板被绕过克隆

### Tests
- 补回归测试：登录应清除旧 session（`test_login_evicts_previous_session`）
- 补回归测试：服务端独占 template_id（`test_create_vm_always_uses_config_template_id`）

---

## [1.0.0] - 2026-03-01

### Added
- K8S NetLab 初始版本上线
- FastAPI 后端，11 个 K8s 实验文档
- Proxmox VM 克隆/销毁（linked clone，秒级创建）
- WebSocket SSH 终端（xterm.js）
- 用户注册/登录，bcrypt 密码，SHA-256 自动迁移
- 滑动窗口登录频率限制（5 次/IP/60s）
- Session cookie（HttpOnly + Secure）
- Admin 观测面板：活跃 session、VM 归属、IP 地理位置
- K3s 模板重置（QEMU agent 执行，SSH 建立前）
- Registry mirror（宿主机 `registry:2`，隔绝外网依赖）
- Proxmox Pool 权限隔离（`k8s-netlab` pool）
- flock 原子 JSON 读写（防并发损坏）
- Git 双层安全 hooks（pre-commit + pre-push）
- GitHub Actions CI（pytest 门禁，覆盖率 ≥ 75%）
- 网络隔离：vmbr1（172.16.100.0/24），跨 bridge DROP 规则

---

[Unreleased]: https://github.com/svb-devops/k8s-netlab/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/svb-devops/k8s-netlab/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/svb-devops/k8s-netlab/releases/tag/v1.0.0
