# Lab Design Contract — ImagePullBackOff / ErrImagePull v0.1

## 元信息

- Sprint: Phase 1 First Wave Sprint #3 — 第三个 internal soft launch lab
- 生成路径：Admin 人工 curated（`LABGEN_LLM_PROVIDER_MODE=fake_only`，无真实 LLM 凭证）——通过 `article-drafts`/`generate-lab` API 拿 stub 骨架后，由 Claude（本次执行者）人工编写真实内容并 PATCH 替换，路径与 lab #1（CrashLoopBackOff）、lab #2（Service 无 Endpoints）一致
- target_domain: `k8s`
- runtime: `dedicated_vm`（复用现有 K3s 单命名空间实验模型，不涉及多 VM）

## 范围约束（本 sprint 明确不做）

- 只做单命名空间 / single runtime 实验
- 不涉及多 VM
- 不涉及 reader upload / URL scraping（内容为人工原创）
- 不做面向真实学生的 growth/expansion（`LABGEN_ENABLED_LAB_IDS` 保持不加入，仅 admin/owner 可见）
- 不重复 CrashLoopBackOff / Service 无 Endpoints 主题
- 不覆盖 pull secret 缺失场景（需要私有 registry 配置，超出本次范围，记入 Known Gap）
- 不新增 verify 原语、不扩大学员 RBAC（`deployments` 的 create/get/list/watch/delete/update/patch 已在 lab #1 时授予，`kubectl set image` 复用同一权限面，无需变更）

## 学习目标

学生能够：
1. 识别 ImagePullBackOff/ErrImagePull 状态的关键特征：`READY=0/1` 且 `RESTARTS=0`（与 CrashLoopBackOff 的"反复重启"区分）
2. 理解为什么 `kubectl logs` 在这类故障下无效（容器从未启动）
3. 用 `kubectl describe pod` 的 Events 段落读出镜像拉取失败的具体原因（`Failed to pull image` / `manifest unknown`）
4. 用 `kubectl get deployment -o wide` 核对 Deployment 中配置的镜像引用
5. 用 `kubectl set image` 非交互式修正镜像 tag（不需要 patch/edit）
6. 验证修复后 Pod 变为 Running 且 Deployment available

## 步骤设计（7 步，对齐 lab #1/#2 的结构与 verify 密度）

| Step | 动作 | 命令类型 | verify |
|------|------|---------|--------|
| 1 | 创建 Deployment（`image-pull-demo`），镜像引用一个内部 registry 上真实不存在的 tag（`172.16.100.1:5000/library/busybox:v0-nonexistent-tag`） | `kubectl create deployment` | `namespace_exists` |
| 2 | 观察 `kubectl get pods`：`STATUS=ImagePullBackOff`（或短暂的 `ErrImagePull`），`READY=0/1`，`RESTARTS=0` | 只读观察 | `deployment_unavailable` |
| 3 | `kubectl describe pods -l app=image-pull-demo` 读 Events：`Failed to pull image ... manifest unknown` / `Back-off pulling image` | 只读观察 | `deployment_unavailable` |
| 4 | `kubectl get deployment image-pull-demo -o wide` 核对当前配置的镜像引用，确认 tag 拼写问题 | 只读观察 | `deployment_unavailable` |
| 5 | 修复：`kubectl set image deployment/image-pull-demo image-pull-demo=172.16.100.1:5000/library/busybox:latest -- sleep 3600`\* | 非交互式，无 patch | `deployment_ready` |
| 6 | 确认修复：`kubectl rollout status` + `kubectl get pods` | 只读观察 | `deployment_ready` |
| 7 | 清理：`kubectl delete deployment image-pull-demo` | 清理 | 无（命名空间由系统回收，同 lab #1/#2 模式） |

\* `kubectl set image` 不支持追加容器启动命令，Step 5 只改镜像；容器默认命令沿用 Step 1 创建 Deployment 时指定的 `-- /bin/sh -c "sleep 3600"`，修复后无需重新指定命令。

## 为什么用"tag 不存在"而不是"registry 不可达"或"pull secret 缺失"

- **可复现、无副作用**：内部 registry（`172.16.100.1:5000`）已确认存在 `library/busybox` 的完整合法 tag 列表；使用一个真实不存在的 tag（如 `v0-nonexistent-tag`）会触发 registry 返回真实的 `404 manifest unknown`，不需要额外配置或临时关闭 registry 制造网络故障
- **不引入新的资源类型或权限面**：pull secret 场景需要 `imagePullSecrets`/`Secret` 绑定到 ServiceAccount，涉及额外的 RBAC 设计和安全审查（类比 lab #2 的 Service type 升级风险讨论），超出本 sprint"工程范围最小"的定位，记入 Known Gap 留给未来 sprint
- **教学效果最强**：tag 拼错是新手最常犯、也最容易在 Step 4 通过肉眼核对发现的错误，修复路径直观（改一个字符串），适合作为系列第三课

## Known Gap（诚实记录，不假装已解决）

- 不覆盖 registry 不可达（网络分区）和 pull secret 缺失/权限错误两类根因，这两类需要更复杂的环境搭建（临时防火墙规则 / 私有 registry + Secret），留给 second wave 之后视排期评估是否值得单独立项
- `VerifyType` 没有 `pod_waiting_reason` 这样的原语可以直接断言"Pod 处于 ImagePullBackOff 状态"（只能通过 `deployment_unavailable` 间接确认"不可用"，不区分具体原因）。本 sprint 认为这不构成阻塞：`deployment_unavailable` 已经能机器化验证 Step 2-4 的"故障存在"这个核心断言，具体故障原因（ImagePullBackOff vs 其他）由学生在 Step 2-3 的 observe 环节人工确认，与 lab #2 的 `service_has_endpoints` 缺口（已在上一个 sprint 补齐）性质不同——那里缺的是"修复是否生效"的核心断言，这里缺的只是"故障具体分类"的细粒度断言，不影响 Step 5-6 修复验证的机器化程度

## Cleanup Contract

`cleanup.namespace_cleanup.type = delete_namespace`，命名空间由 `complete_session()`/rehearsal complete 路径回收，与 lab #1/#2 完全一致模式，不引入新的清理逻辑。

## Publish Contract

- 内部发布：`publish_status = published`，但**不**写入 `LABGEN_ENABLED_LAB_IDS` 白名单 → 真实学生仍然 403（与 lab #1/#2 保持一致的锁定状态）
- CTA：仅在内部/admin 可见的文章草稿上打开 `cta_enabled`，不面向公开 Directus 文章
- `image_resolution` 字段留空（与 lab #1/#2 先例一致）：Step 1 的镜像引用是本 lab 教学设计里刻意制造的"不可解析"依赖，不是需要被追踪为"已解析依赖"的真实镜像，把它注册进 `image_resolution` 会导致 `StaticValidator._check_image_all_resolved` 误判为 PUBLISH_BLOCKING 失败——这个字段的语义是"lab 依赖的、应当可用的镜像清单"，不是"lab 命令里出现过的所有镜像字符串"
