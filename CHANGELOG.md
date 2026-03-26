# Changelog

所有版本变更记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased]

### Added
- feat: CDN SRI integrity 属性 — xterm.js / marked / highlight.js 所有 jsdelivr 资源加 sha384 哈希，防 CDN 投毒
- feat: 结构化 JSON 日志 — `backend/middleware.py` JsonFormatter，每条日志一行 JSON（timestamp/level/logger/message/exc_info）
- feat: X-Request-ID middleware — 每个 HTTP 请求自动注入 UUID4，客户端可自带，响应头回显
- feat: ruff + mypy 接入 CI — 每次推送自动 lint + 类型检查；pyproject.toml 固化规则
- fix: 修复 smart_logger/websocket/docs_routes 中 8 处 mypy 类型注解错误（Optional、union-attr）
- fix: 修复 websocket.py 3 处 bare except → except Exception
- feat: 优雅关闭 — backend/task_registry.py 追踪 in-flight VM 操作，lifespan shutdown 等待 30s 后才退出，防止孤儿 VM
- feat: pip-tools 依赖锁文件 — requirements.lock 固定所有传递依赖版本，CI 验证锁文件与 requirements.txt 同步

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
