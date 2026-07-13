# Phase 1 First Wave Sprint #3 — 生产结果报告 v0.1

## 元信息

- Lab: `eb78afaa-f7fb-422e-8eb9-98644f59527f`（Kubernetes ImagePullBackOff 排查实验：用 describe 的 Events 定位镜像拉取失败原因）
- Article draft (LabGen 内部，非 Directus): `da282651-f66f-405b-abc1-b3dc563feb6a`
- 状态：`overall_status = IMAGE_PULL_BACKOFF_LAB_READY_WITH_ARTICLE_DRAFT_AND_ASSETS`
- 设计文档：`docs/labgen/IMAGE_PULL_BACKOFF_LAB_DESIGN_BRIEF_v0.1.md`
- Topic Brief：`docs/labgen/IMAGE_PULL_BACKOFF_TOPIC_BRIEF_v0.1.md`
- Article Draft：`docs/labgen/IMAGE_PULL_BACKOFF_OFFICIAL_ARTICLE_DRAFT_v0.1.md`

## 交付清单核对

| # | 交付项 | 状态 | 证据 |
|---|--------|------|------|
| 1 | Topic Brief | 完成 | `IMAGE_PULL_BACKOFF_TOPIC_BRIEF_v0.1.md` |
| 2 | Lab Design Brief/Contract | 完成 | `IMAGE_PULL_BACKOFF_LAB_DESIGN_BRIEF_v0.1.md` |
| 3 | generated/curated lab draft | 完成 | `article-drafts` + `generate-lab` 拿 stub 骨架（fake_only 模式）→ 人工 PATCH 替换为真实内容，路径与 lab #1/#2 一致 |
| 4 | static validation PASS | 完成 | 20/20，`image_resolution` 留空（设计原因见 Design Brief），无需新增校验 |
| 5 | internal rehearsal PASS | 完成（两轮） | 第一轮 session `168f9f01-f607-4967-b184-7496632c6d58` 发现两处内容缺陷（见下节）；第二轮 session `ff32289f-a891-4cbe-a70d-2a947724b06b` 在修正后 7/7 步骤通过，`cleanup_verified=true` |
| 6 | cleanup_verified=true | 完成 | rehearsal 第二轮与 learner smoke 均 `cleanup_verified: true` |
| 7 | published internal soft launch article/lab | 完成 | `publish_status=published`；**不**在 `LABGEN_ENABLED_LAB_IDS` 白名单（真实学生仍 403，与 lab #1/#2 访问策略一致） |
| 8 | CTA verified | 完成 | `GET /api/labgen/drafts/{id}/cta` 返回正确的 lab_url/markdown_cta/html_cta；`cta_enabled=false`；`topic_consistency_warning=null` |
| 9 | one owner/learner smoke | 完成 | session `d5a6abfe-f6b0-43a2-a57d-56657250ff42`（`session_type=learner`），7/7 步骤 + `complete()` 成功，`cleanup_verified=true` |
| 10 | Phase 1 Series Alignment 更新 | 完成 | `PHASE1_SERIES_ALIGNMENT_v0.1.md` ImagePullBackOff 标记为 done |
| 11 | 回归确认 | 完成 | 见下节 |

## Rehearsal 中发现并修正的两处真实内容缺陷

第一轮 rehearsal（真实 K3s，VM 401，172.16.100.140，K3s v1.34.4）逐步执行 lab 草稿里的命令，发现两处与真实环境不符：

1. **Step 3 的 observe 文本假设过**：镜像拉取失败的 Events 消息是 `manifest unknown: manifest unknown`。真实环境返回的实际消息是：
   ```
   Failed to pull image "...": rpc error: code = NotFound desc = failed to pull and unpack image "...": failed to resolve reference "...": ... not found
   Error: ErrImagePull
   ```
   已修正为真实观察到的措辞，不再使用推测性的错误消息文本。

2. **Step 5 的修复命令用错了容器名**（真实内容 bug，会阻塞每一个学员）：草稿假设 `kubectl create deployment image-pull-demo --image=...` 会用 Deployment 名（`image-pull-demo`）作为容器名，实际上 kubectl 用**镜像名**（`busybox`）作为默认容器名。第一次执行 `kubectl set image deployment/image-pull-demo image-pull-demo=...` 直接报错 `error: unable to find container named "image-pull-demo"`。已修正 Step 4 的 observe 文本（新增 CONTAINERS 列核对指引）和 Step 5 的命令（改为 `busybox=...`），并在 troubleshoot 字段里把这个坑显式标注出来，帮助真实学员遇到同样错误时能自行定位。

两处修正后，用同样的命令序列重新跑了一次完整的 rehearsal（第二轮，session `ff32289f-...`），7/7 步骤全部通过，确认修正生效且不引入新问题。

## 为什么这次没有新增 verify 原语、没有扩大 RBAC

- `VerifyType.DEPLOYMENT_UNAVAILABLE`（Step 2-4，确认故障存在）和 `VerifyType.DEPLOYMENT_READY`（Step 5-6，确认修复生效）已在 lab #1（CrashLoopBackOff）时实现并验证过，直接复用，无需扩展 verifier
- `kubectl set image` 修改的是 Deployment 的 `update`/`patch` 权限范围，`deployments` 资源的这两个 verb 已在 lab #1 时授予学员 RBAC（`LEARNER_ALLOWED_PERMISSIONS`），无需新增
- `kubectl_executor.py` 的黑名单规则（`_BLOCKED_SUBCOMMANDS`/`_BLOCKED_PATTERNS`）未拦截 `set` 子命令或本 lab 用到的任何命令，无需变更执行器代码

这是三个 first wave lab 里工程范围最小的一个（Design Brief 中已预判），实际生产过程验证了这个判断。

## 回归确认

- `bb4fe651-7687-4457-9056-885172d9017b`（CrashLoopBackOff）：`publish_status=published`，未受本次改动影响（本次未修改任何 lab #1 相关代码/数据）
- `2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86`（Service 无 Endpoints）：`publish_status=published`，`service_has_endpoints` verifier 未受影响
- `LABGEN_ENABLED_LAB_IDS` 全程保持为空，未新增任何白名单条目
- `data/labgen_invites.json` 全程不存在，Controlled Micro Invite 机制未被触发
- 本次全程未修改任何后端代码（`backend/labgen/*.py` 无 diff）——纯内容生产 + 4 篇文档，不涉及权限/verifier/执行器变更，属于 C 类文档变更 + 内容生产操作，不触发 safety-reviewer A/B 类审查门槛
- 生产环境 health（`/api/health`）在整个 sprint 期间保持 `status=healthy`

## 测试结果

见下方"回归测试"章节（本次未改动测试相关代码，运行全量测试仅作为收尾确认，非本次改动直接触发）。

## 遗留/下一步

1. **官方文章仍是草稿**：`article_url=null`，`cta_enabled=false`，未创建 Directus 记录，发布决策留给 owner（参照 `SERVICE_ARTICLE_PUBLISH_GATE_PREP_v0.1.md` 同等模式，未来可为 ImagePullBackOff 复用同一套 gate 检查）
2. **Known Gap 未处理**（记录在 Design Brief）：不覆盖 registry 不可达和 pull secret 缺失两类根因；`VerifyType` 没有细粒度的 `pod_waiting_reason` 原语（`deployment_unavailable` 已足够覆盖本 lab 的核心断言，未阻塞）
3. **Phase 1 second wave**：ConfigMap 修改未生效、DNS 服务发现失败、Pod Pending，按 `PHASE1_SERIES_ALIGNMENT_v0.1.md` 排期，本 sprint 未开始
4. 三篇已完成 lab（CrashLoopBackOff / Service 无 Endpoints / ImagePullBackOff）共享的"Pod 状态类"故障排查心智模型已经形成一个完整闭环（起不来 → 反复重启看日志 / 起来了但没流量看 Endpoints / 从没起来看 Events），适合作为 series 首批三篇同时评估发布顺序，留给 owner 决策
