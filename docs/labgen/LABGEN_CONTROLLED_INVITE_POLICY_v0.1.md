# LabGen Controlled Invite Policy — 设计文档 v0.1

## 状态

`design_only` —— **本文档不执行任何操作**。不修改 `LABGEN_ENABLED_LAB_IDS`，不新增任何学生访问权限，不启动任何邀测。这是为下一次"是否重启 Controlled Soft Launch"决策准备的执行方案，供用户/CEO-CTO 角色审阅后再决定是否触发。

## 背景

`LABGEN_ENABLED_LAB_IDS` 当前为空（`backend/config.py:346-351`），两个已发布的 internal lab（CrashLoopBackOff、Service-no-Endpoints）均对真实学生返回 403（`backend/labgen/routes.py:1153`）。此前的软发布已被主动收紧为仅 admin 可见，本文档设计的是"未来如果决定重新开放"时需要满足的 gate，不代表决定重新开放。

## 1. allowed_users model

- 不采用全局开关（"所有注册用户可用"），采用**白名单账号名单**：新增 `LABGEN_ENABLED_USERNAMES`（与 `LABGEN_ENABLED_LAB_IDS` 同构，逗号分隔环境变量 → frozenset）
- 邀测阶段账号必须是已知的、可追责的测试账号（复用 `sfl-test-01`/`sfl-test-02` 这类命名约定），不接受生产环境注册用户自助加入
- 白名单校验应在 `create_lab_session`（`routes.py:1143`）里与 `LABGEN_ENABLED_LAB_IDS` 做**逻辑与**：必须同时满足"lab 在白名单" AND "用户在白名单"，缺一不可

## 2. allowed_labs model

- 沿用现有 `LABGEN_ENABLED_LAB_IDS` 机制，不新增数据结构
- 邀测重启时**逐个 lab 单独开放**，不批量开放全部已发布 lab —— 优先级：先开 CrashLoopBackOff（已通过 8 位试点用户验证，历史记录见 `FIRST_PILOT_USER_ONBOARDING_RESULT_v0.1.md` 等系列文档），Service-no-Endpoints 因缺少 `service_has_endpoints` verify 原语（见 Known Gap），建议延后到该原语补齐之后再开放，避免学生在核心验证点上卡住却得不到机器化反馈

## 3. learner-only permission model

已有实现，本次不新增：
- `SessionType.INTERNAL_REHEARSAL` 会话对学员不可见（`routes.py:1214/1236/1262`）
- 学员 RBAC 权限见 `backend/labgen/learner_credentials.py::LEARNER_ALLOWED_PERMISSIONS`，本 sprint 新增的 services（无 update/patch）+ endpoints（只读）权限已经是邀测重启后学员会实际使用的最终权限集，无需再改

## 4. forbidden endpoints（邀测期间对非 admin 用户维持关闭）

- LabGen generation 相关端点（`article-drafts`、`generate-lab`）—— 邀测只开放"使用已发布 lab"，不开放"生成新 lab"
- reader upload / URL scraping 相关端点 —— 同上，产品面未就绪
- 任何 admin-only 的 draft review / publish 端点（已有 `require_internal_token`/`is_admin` 校验，维持现状）

## 5. max active sessions per user

- 复用现有 VM 配额机制（`MAX_VMS_PER_USER`，`config.py:217`），不新增专门的 LabGen session 上限
- 邀测阶段建议追加应用层软限制：单用户同时只能有 1 个 active learner session（防止测试账号并发开多个 session 导致 VM 池被过量占用），可在 `create_lab_session` 里对 `svc.list_sessions(student_username=username, active_only=True)` 做 count 校验后拒绝——**本文档只设计，不实现**

## 6. cleanup failure handling

- 沿用现有 `cleanup_verified` 字段和 `DataRetentionService` 的 zombie draft 归档机制（本次 sprint 已验证生产可用，清理过 155+23 个 zombie draft）
- 邀测期间新增：任何 `cleanup_verified=false` 的学员 session，视为 P1 事件，人工介入前不允许把对应命名空间的 VM 位重新分配给下一个学员（防止残留资源冲突），触发方式建议接入 `/api/health` 的 `sessions.warnings` 字段做轮询告警，复用本次 sprint 新增的 email 告警基础设施模式（`_check_email_health()`）

## 7. monitoring requirements

- `/api/health` 的 `labgen`/`sessions`/`email` 三个字段已具备邀测所需的基础可观测性，邀测重启前应确认：`missing_credentials` 为空、`tainted_vm_count` 为 0、`zombie_draft_count` 处于低位
- 建议邀测期间每日人工检查一次 `/api/health`，而不是等到告警触发才看（试点用户规模小，人工巡检成本可接受，暂不需要接入外部监控系统）

## 8. rollback plan

- 单点回滚：把出问题的 lab_id 从 `LABGEN_ENABLED_LAB_IDS` 移除并重启服务（`systemctl restart k8s-netlab`），已购买/进行中的学员 session 不受影响（新建 session 才受门禁拦截），已有 session 走正常完成/超时流程
- 全量回滚：`LABGEN_ENABLED_LAB_IDS` 清空，等价于回到当前状态（两个 lab 均 internal-only），这是一个纯配置回滚，不涉及代码变更或数据迁移，回滚成本极低
- 回滚不需要 `git revert`，只需改环境变量 + 重启服务，遵循 `deploy.md` 规则重启后必须跑 health check

## 9. go/no-go checklist（未来触发邀测前必须逐项确认）

- [ ] 用户/CEO-CTO 角色明确决策"现在开放邀测"（本文档不能替代该决策）
- [ ] 至少一个 lab 完成过真实人类学员（非 admin/owner smoke）的完整闭环验证
- [ ] `service_has_endpoints` verify 原语已补齐，或该 lab 明确从本轮邀测范围排除
- [ ] `/api/health` 三项核心指标（missing_credentials/tainted_vm_count/zombie_draft_count）均为健康值
- [ ] `LABGEN_ENABLED_USERNAMES`（本文档第 1 节设计，当前未实现）已实现并测试覆盖
- [ ] 单用户并发 session 软限制（本文档第 5 节设计，当前未实现）已实现并测试覆盖
- [ ] 回滚步骤已在非生产环境演练过一次
- [ ] official article 已满足其自身的发布 blockers（见 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 底部）

## 明确声明

本文档产出后，`LABGEN_ENABLED_LAB_IDS`、`LABGEN_ENABLED_USERNAMES`（尚不存在）均未发生任何变化。第 1 节和第 5 节提到的机制**均为设计提案，尚未实现代码**，go/no-go checklist 前两项未完成也是如此。
