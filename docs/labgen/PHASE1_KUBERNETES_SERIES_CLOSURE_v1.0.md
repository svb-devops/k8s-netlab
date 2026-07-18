# Phase 1 — Kubernetes 高频故障排查实战系列 收官报告 v1.0

## 状态

`PHASE1_STATUS: COMPLETE`

《Kubernetes 高频故障排查实战系列》六个主题全部完成生产并正式公开发布。本文档是 Phase 1 的最终收口记录，回答"系列做完了没有、每个 lab/文章现在处于什么状态、可复用了什么资产"。不替代、不修改任何单个 lab 的设计文档或已发布的教学内容。

## 六篇已发布主题

| # | 主题 | 文章 URL | lab_id | rehearsal | smoke | Owner dogfood |
|---|------|---------|--------|-----------|-------|---------------|
| 1 | CrashLoopBackOff | https://lab.cloudnetops.tech/article.html?slug=crashloopbackoff-describe-logs | `bb4fe651-7687-4457-9056-885172d9017b` | PASS | PASS | PASS |
| 2 | Service 无 Endpoints（selector 与 labels 不匹配） | https://lab.cloudnetops.tech/article.html?slug=service-no-endpoints-selector-labels | `2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86` | PASS | PASS | PASS |
| 3 | ImagePullBackOff | https://lab.cloudnetops.tech/article.html?slug=imagepullbackoff-events-diagnosis | `eb78afaa-f7fb-422e-8eb9-98644f59527f` | PASS | PASS | PASS |
| 4 | ConfigMap 修改后不生效 | https://lab.cloudnetops.tech/article.html?slug=configmap-not-effective-rollout-restart | `ce793f9b-e416-44e2-9a32-c79b6488cfa2` | PASS | PASS | PASS |
| 5 | DNS 服务发现失败 | https://lab.cloudnetops.tech/article.html?slug=dns-service-discovery-namespace-fqdn | `39b87766-a7eb-460d-a8d3-ac5a31319d4a` | PASS（2 轮） | PASS | PASS |
| 6 | Pod Pending | https://lab.cloudnetops.tech/article.html?slug=pod-pending-events-not-logs | `dcddf681-f906-491c-b126-efee40f3621c` | PASS（2 轮） | PASS | PASS（5/5） |

全部六个 lab 当前 `publish_status=published`、`is_startable=true`、`cta_enabled=true`，全部六篇文章 `status=published` 且匿名可访问 200，六个 CTA 与各自 lab 一一对应，系列互链（"系列文章"段落）覆盖全部 6×5=30 组互链、broken_links=0。

## 主要可复用 verifier 资产

系列生产过程中沉淀的只读 verifier 类型，均只依赖既有 `pods`/`deployments`/`configmaps`/`services`/`endpoints` RBAC，未引入超出学员权限模型之外的新授权（`pods/log:get` 是唯一例外，DNS Sprint 引入）：

| verifier 类型 | 首次引入主题 | 用途 |
|--------------|-------------|------|
| `deployment_unavailable` / `deployment_ready` | CrashLoopBackOff | Deployment 可用性判断 |
| `service_has_endpoints` | Service No Endpoints | Service/Endpoints 关联判断 |
| `configmap_value_equals` / `deployment_restart_triggered` / `deployment_restart_not_triggered` | ConfigMap | 配置生效时机判断（rollout restart 注解） |
| `pod_succeeded` / `pod_log_contains` | DNS Service Discovery | 终止状态 + 日志内容判断（学员/verifier 均禁 `kubectl exec` 场景下的替代方案） |
| `pod_phase_equals` / `pod_scheduling_unschedulable` | Pod Pending | 调度阶段判断（`status.conditions`，不依赖会过期的 Events 文本） |

## 新用户体验验证

- 自动 provisioning（"零跳转"体验，`LABGEN_AUTO_VM_PROVISION_LAB_IDS`）已对全部 6 个 lab 生效并逐一实测：新注册、无预分配 VM 的账号点击「进入实验」可直接拿到 `LAB_ACTIVE`，无需手动跳转老平台建号。
- 终端重连修复（commit `0962703`，2026-07-18）已实测验证：断线/页面刷新重连后，命令回显与 stdout/stderr 渲染正常，不再出现"命令一闪而过、无输出"的问题。本次 Pod Pending 发布回归中，5 个步骤均通过真实浏览器 + 全新账号验证，终端重连场景在真实操作节奏下零输出丢失。
- session TTL 30/90 分钟环境变量覆盖漂移已修复（同一 commit），生产环境实测 `session_ttl_minutes=90` 生效，`ops_smoke_check.sh` 新增检查项持续监控该类配置漂移。

## 当前运行边界

- Phase 1 场景范围严格限定于单 namespace / 单 K3s runtime（不涉及多 VM、多节点、PVC、Ingress、NetworkPolicy、BGP/OSPF，均在 `deferred` 列表中）
- 当前处于"车已停在线上，无主动 Growth"状态：系列内容已完整可用、可被任何已注册用户发现和使用，但未做任何主动引流/推广动作，是否/何时启动推广仍需 owner 另行决策
- Phase 1 设计范围内暂无下一个新主题排期

## Phase 1 状态

**COMPLETE** —— 六个主题、六篇文章、六个可运行实验，全部正式公开发布，全部通过 rehearsal/smoke/Owner dogfood 三轮验证，全新用户端到端体验（含终端重连场景）已实测确认可用。

## Backlog（仅记录，本次未处理）

- **abort cleanup retry budget**：约 28 秒，可能短于 K3s namespace 实际删除耗时，曾导致个别 session 被误判 `cleanup_failed` 并连带污染共享 VM（`tainted`）——真实命名空间已确认无残留，问题仅限状态误判，非资源泄漏。值得作为独立 sprint 处理。
- **DataRetentionService**：`zombie_draft_count`（当前 22）与 `lab_review_diffs.json`（当前约 1.5MB）持续缓慢增长，建议排期跑 `DataRetentionService.run(dry_run=False)` 清理。

## 相关文档

- `PHASE1_SERIES_ALIGNMENT_v0.1.md` —— 系列排期与逐主题生产记录（本文档的上游）
- `PROJECT_NORTH_STAR_v0.1.md` —— LabGen 产品权威文档
- `articles/POD_PENDING_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md` —— Pod Pending 正式发布文章原始草稿
