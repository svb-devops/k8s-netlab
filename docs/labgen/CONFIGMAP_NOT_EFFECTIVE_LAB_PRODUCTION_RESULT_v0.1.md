# Second Wave Sprint #1 — 生产结果报告 v0.1

## 元信息

- Lab: `ce793f9b-e416-44e2-9a32-c79b6488cfa2`（ConfigMap 修改后不生效排查实验）
- Article draft (LabGen 内部，非 Directus): `beb57754-1370-41d1-9aa8-c79c4371942b`
- 状态：`overall_status = CONFIGMAP_LAB_READY_FOR_OWNER_DOGFOOD`
- 设计文档：`docs/labgen/CONFIGMAP_NOT_EFFECTIVE_LAB_DESIGN_BRIEF_v0.1.md`
- Topic Brief：`docs/labgen/CONFIGMAP_NOT_EFFECTIVE_TOPIC_BRIEF_v0.1.md`
- Article Draft：`docs/labgen/articles/CONFIGMAP_NOT_EFFECTIVE_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md`

## 交付清单核对

| # | 交付项 | 状态 | 证据 |
|---|--------|------|------|
| 1 | Topic Brief | 完成 | `CONFIGMAP_NOT_EFFECTIVE_TOPIC_BRIEF_v0.1.md` |
| 2 | Lab Design Brief/Contract | 完成 | `CONFIGMAP_NOT_EFFECTIVE_LAB_DESIGN_BRIEF_v0.1.md`，含 VM 401 实测验证记录 |
| 3 | 新增最小可复用 verifier | 完成 | `configmap_value_equals`（直接读 ConfigMap.data 比较）+ `deployment_restart_triggered`/`deployment_restart_not_triggered`（读 Deployment 的 restartedAt 注解），均只读、无写操作，复用既有 RBAC |
| 4 | StaticValidator 识别新 verify type | 完成 | `verify.type_implemented` 自动通过（读 `_SUPPORTED_TYPES`）；新增 `verify.configmap_value_equals_fields` 检查防止 config_key/expected_value 缺失 |
| 5 | generated/curated lab draft | 完成 | `article-drafts` + `generate-lab` 拿 stub 骨架（fake_only 模式）→ 人工 PATCH 替换为真实内容，路径与 First Wave 三个 lab 一致 |
| 6 | static validation PASS | 完成 | 21/21 |
| 7 | 真实 K3s rehearsal PASS | 完成 | VM 401，session `3bd9d4ce-7b88-499f-90dc-89cc5fd623ef`，8/8 步骤通过，`cleanup_verified=true` |
| 8 | learner smoke PASS | 完成 | session `47e93449-4608-4eb5-9393-565b54afd718`（`session_type=learner`），8/8 步骤通过，`cleanup_verified=true` |
| 9 | published internal soft launch | 完成 | `publish_status=published`；**不**在 `LABGEN_ENABLED_LAB_IDS` 白名单 |
| 10 | CTA verified | 完成 | `GET /api/labgen/drafts/{id}/cta` 返回正确 lab_url/markdown_cta/html_cta；`cta_enabled=false`；`topic_consistency_warning=null` |
| 11 | Phase 1 Series Alignment 更新 | 完成 | `PHASE1_SERIES_ALIGNMENT_v0.1.md` ConfigMap 主题标记为已完成 |
| 12 | 回归确认 | 完成 | 见下节 |

## 核心工程冲突与设计决策：为什么不能直接验证"Pod 里的环境变量值"

这是本 sprint 调研阶段发现的真实约束，完整记录在 Design Brief 里，这里复述结论：`kubectl_executor.py` 禁止 `exec` 子命令，学员和 verifier 都无法进入运行中的容器读取 `printenv` 的实际输出；而 K8s API 层面，Pod 的 `spec.containers[].envFrom`/`env[].valueFrom.configMapKeyRef` 存储的始终是对 ConfigMap key 的**引用**，不是 kubelet 解析出的字面值，查 Pod 对象本身在 ConfigMap 更新前后看到的都是同一份引用文本。

改用"Deployment 自创建以来是否发生过一次 rollout restart"这一逻辑等价、且可通过 K8s API 直接机器化验证的信号（`spec.template.metadata.annotations` 是否含 `kubectl.kubernetes.io/restartedAt`）。已在 VM 401 真实 K3s 集群上实测验证：仅 `kubectl patch configmap` 不会触发这个注解出现或产生新 Pod，只有 `kubectl rollout restart` 才会——这是完全可复现、非近似的机器可验证事实。

## 本主题的核心误区（诚实记录，供未来同类主题参考）

**"ConfigMap 对象已经更新" 不能被当作 "运行中 Pod 已经加载新配置" 的充分条件。** 这两者是完全独立的事件：前者是对 K8s API 对象的一次写操作，立即生效；后者依赖 kubelet 在**容器创建时**做的一次性环境变量解析，此后不会重新触发，除非有新的容器被创建（rollout restart 或其它导致 Pod 模板变化的操作）。

这个误区之所以值得单独记录，是因为它和 First Wave 三个"Pod 状态类"故障（CrashLoopBackOff/Service 无 Endpoints/ImagePullBackOff）的排查心智模型完全不同——那三个都能从 `kubectl get pods`/`kubectl describe` 直接看出"有什么不对"，而这一类故障的判断起点根本不在 Pod/Service 状态上，而在于"引用的配置对象是否在容器创建之后才被修改"这一时序判断。这也是 Second Wave 相对 First Wave 引入的新维度，值得在系列排期时对后续"配置类"主题（如 Secret 更新、CRD spec 变更）保持警觉：**只要修复路径涉及"改配置对象但不改 Pod 模板"，就大概率会撞到同一个"改了但不生效"的坑，需要同样的 rollout restart（或等价的强制重建）才能解决**。

## Rehearsal 过程中发现并修复的一个真实基础设施 bug（与本 sprint 代码无关）

第一次调用 `check-step` 时，`configmap_exists` verify 返回 500 Internal Server Error，日志显示尝试连接 `172.16.100.153:6443` 超时（`No route to host`）。排查发现 `/var/lib/labgen-staging/verifier-credentials/401/`（VM 401 的 verifier 凭证，`LABGEN_VERIFIER_CREDENTIAL_ROOT` 指向的实际生产路径，与仓库内 `creds/vm_creds/` 是两个不同的目录）里保存的 kubeconfig 创建于 `2026-06-22`，指向的是 VM 401 当时的旧 IP（`172.16.100.153`），而 VM 401 当前的实际 IP 是 `172.16.100.140`（`/etc/labgen/home_lab_mvp.kubeconfig` 和 `creds/vm_creds/401/kubeconfig.yaml` 里都是这个新 IP，两者与实际连通性一致）。

用既有的 `scripts/provision_verifier_credentials.py --vm-id 401`（幂等重新 provision）修复，`credential_generation` 从 1 升到 2，`k3s_endpoint` 更新为正确的 `172.16.100.140`。修复后所有 verify 立即恢复正常。这个问题会影响**任何**依赖 VM 401 verifier 的 lab（不止本次新增的两个 type），此前之所以没被发现，是因为距离上一次真正需要 VM 401 verifier 的 rehearsal（ImagePullBackOff，2026-07-13）之后 VM 401 可能发生过一次 IP 变更（DHCP 租约或重启），而生产 verifier 凭证没有任何自动刷新机制，只在首次 provision 时写入一次。**这是一个值得记入 backlog 的真实运维缺口**：`health` 端点目前只检查 `credentials_present`（凭证文件是否存在），不检查凭证里的 endpoint 是否与 VM 当前实际 IP 一致，一次静默的 IP 漂移会让所有验证请求失败，但 health 端点会一直显示"绿色"直到有人真正跑一次 rehearsal 才会暴露。

## 为什么新增了两个 verifier 而不是复用已有的

`deployment_ready`/`deployment_unavailable`/`configmap_exists`（First Wave 已实现）都只能确认"资源存在/状态健康"，没有一个能表达"配置对象的具体值"或"是否发生过重启"这两个本 lab 教学核心需要的断言。这是 Second Wave 第一次真正需要扩展 verifier 能力（对比 ImagePullBackOff sprint 是三个 first wave lab 里工程范围最小、完全复用已有 verifier 的一次）——因为本主题的教学点本身就是"配置类"而非"状态类"故障，验证维度天然不同。

## 回归确认

- 三个 First Wave lab（CrashLoopBackOff/Service 无 Endpoints/ImagePullBackOff）`publish_status=published`，未受本次改动影响（本次未修改任何 First Wave lab 相关数据）
- `LABGEN_ENABLED_LAB_IDS`/`LABGEN_AUTO_VM_PROVISION_LAB_IDS` 全程保持不变，未新增任何白名单条目
- `data/labgen_invites.json` 全程不存在，Controlled Micro Invite 机制未被触发
- 未发布任何 Directus article，未打开任何公开 CTA
- 生产环境 health（`/api/health`）在整个 sprint 期间保持 `status=healthy`（除 verifier 凭证 bug 修复前那段短暂的 500，且那些请求全部来自本次 rehearsal 本身的探测调用，不影响任何真实用户）
- 全量测试 5077 passed，92.17% coverage，mypy 0 error（新增/修改 4 个测试文件，覆盖新 verifier 的所有分支 + StaticValidator 新检查）
- safety-reviewer 审查发现 2 个真实问题并已修复：`configmap_value_equals_fields` 检查错误地把合法的空字符串 `expected_value` 当作缺失字段拒绝（已改为显式 `is None` 判断）；`deployment_restart_not_triggered` 对同一个 Deployment 调用了两次 `list_namespaced_deployment`，存在窄 TOCTOU 窗口（已重构为单次调用 + 三态返回值，同时补充回归测试锁定"只调用一次"这一约束）

## 测试结果

全量测试（5077 passed / 1 skipped / 26 xfailed / 92.17% coverage）与 mypy（0 error）在 push 前的 pre-push hook 中自动重跑一次，与本节记录的结果一致。

## 遗留/下一步

1. **官方文章仍是草稿**：`article_url=null`，`cta_enabled=false`，未创建 Directus 记录，发布决策留给 owner
2. **VM 401 verifier 凭证无自动刷新机制**（本 sprint 发现并修复了一次实例，但根因未解决）：建议 backlog 里加一项——要么给 `health` 端点加一个真正的连通性探测（而非只查文件存在），要么给凭证加过期/自愈机制，避免下次 IP 漂移又要等到真正跑 rehearsal 才发现
3. **卷挂载 ConfigMap 的行为对比未覆盖**（记录在 Design Brief 的 Known Gap）：留给未来 Second Wave 后续主题或作为文章的一句话延伸提示
4. **Second Wave 后续两个主题**：DNS 服务发现失败、Pod Pending，按 `PHASE1_SERIES_ALIGNMENT_v0.1.md` 排期，本 sprint 未开始
