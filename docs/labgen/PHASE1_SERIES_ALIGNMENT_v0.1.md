# Phase 1 Series Alignment v0.1

## 状态

`documentation_only` —— 本文档不改变任何代码行为、不开放任何访问权限。目的是把已经产出的三个 lab（CrashLoopBackOff、Service 无 Endpoints、ImagePullBackOff）放进一个明确的系列结构里，为后续排期提供依据。

## 2026-07-18 更新（DNS Service Discovery Owner Dogfood 完成）

Owner 用真实非 admin 账号（`owner-test-01`）亲自完成了完整 dogfood：临时开启访问（allowlist + 命名邀请）、`publish_status` 补齐为 `published`（此前遗留为 `draft`，已修复）、Start Lab 自动 provisioning、4 步全部通过（`kubectl logs` 实测确认 `SHORT_NAME_FAILED_AS_EXPECTED`/`SERVICE_FQDN_RESOLVED` 两个标记）、`LAB_CLOSED`+`cleanup_verified=true`、namespace 真实回收。过程中 Owner 报告了一次"命令输入闪一下无输出"，排查后定位为与 ConfigMap 那次 verifier vm_id BLOCKER 完全无关的独立前端 bug（`labgen-kubectl-terminal.js` 粘贴以裸 LF 结尾的命令时静默丢弃、不发送），已修复并补齐回归测试，Owner 在同一次会话里验证了修复后命令可以正常执行。测试结束后已恢复 baseline（allowlist/invite 全部回滚，`owner-test-01` 重新验证为 `LAB_NOT_ENABLED`）。详见 commit `5359364`。

## 2026-07-18 更新（Second Wave Sprint #2 — DNS Service Discovery）

DNS 服务发现失败已完成生产：`lab_id=39b87766-a7eb-460d-a8d3-ac5a31319d4a`，`publish_status=draft`（internal soft launch，未加入 `LABGEN_ENABLED_LAB_IDS`/`LABGEN_AUTO_VM_PROVISION_LAB_IDS`），StaticValidator 22 项检查全部通过。两轮独立的真实 K3s rehearsal（VM 401，`session_id=a405bfe3-...`/`7751e825-...`）全部 4 步通过，`cleanup_verified=true`，namespace 均确认真实回收。

设计相对任务书原始方案有一处必要偏差：读 `learner_credentials.py` 确认学员 RBAC 不含 `namespaces`/`pods`/`batch/jobs` 的 create 权限后，改为用平台预先建好的共享 namespace `labgen-dns-target`（类似已有的 registry mirror/kube-dns，运维维护、不随会话清理）作为跨 namespace 目标，学员侧只需在自己的 namespace 内创建一个诊断 Deployment 发起 nslookup（DNS 查询本身不需要跨 namespace RBAC）。真实集群上验证了短名称 NXDOMAIN、FQDN 正确解析两个核心现象。

新增两个可复用只读 verifier：`pod_succeeded`（Pod phase Succeeded）、`pod_log_contains`（读 Pod 日志确认包含指定标记，非 `kubectl exec`）。rehearsal 过程中发现并修复一个 BLOCKER：`lab-verifier-namespace-readonly` ClusterRole 缺少 `pods/log:get`，导致首次 `pod_log_contains` 调用 500；已在 `_CLUSTER_ROLE_MANIFEST` 和 `PlatformVerifierInitializer` 两处补齐并保持交叉校验测试同步，对 VM 401 重跑幂等的 `initialize_verifier_for_vm_host_side` 使其生效。详见 `DNS_SERVICE_DISCOVERY_LAB_DESIGN_BRIEF_v0.1.md`。

Official article draft 已撰写（`docs/labgen/articles/DNS_SERVICE_DISCOVERY_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md`），`article_status=ready_to_publish_draft`，未发布、未公开、未加入 CTA。按计划本轮只做到 internal soft launch + owner dogfood 就绪，不发布、不公开，不启动 Pod Pending（Second Wave 第三个主题）。

## 2026-07-18 更新（Second Wave #1 Minimal Publish）

ConfigMap 修改后不生效正式面向公开读者发布：Directus article `configmap-not-effective-rollout-restart`（`status=published`，公开可访问 200），`lab_id=ce793f9b-e416-44e2-9a32-c79b6488cfa2` 已加入 `LABGEN_ENABLED_LAB_IDS` 与 `LABGEN_AUTO_VM_PROVISION_LAB_IDS`，`cta_enabled=true`，CTA 正确指向该 lab。这是系列第四篇正式公开发布的文章/实验。发布后用一个全新注册、非 admin、无预分配 VM 的账号（`cm-e2e-fresh-01`）走完整公开路径验证：文章 → CTA → Start Lab → 自动 provisioning → `LAB_ACTIVE` → 8 步全部通过 → cleanup → `LAB_CLOSED` → `cleanup_verified=true`；额外用平台管理员权限（非学员/verifier 路径）直接 `kubectl exec` 核对了三个核心教学语义在真实 Pod 进程里确实成立（重启前读 old、ConfigMap 改成 new 后运行中 Pod 仍读 old、rollout restart 后新 Pod 读 new）。同一账号依次对 First Wave 三个已发布 lab 做了代表性 verifier 回归（CrashLoopBackOff 的 `deployment_unavailable`、Service No Endpoints 修复后的 `service_has_endpoints`、ImagePullBackOff 的 `deployment_unavailable`），均 PASS + `cleanup_verified=true`，确认上一轮修复的 verifier vm_id pin 对整个系列都生效。测试用账号与 VM 已清理。详见 `CONFIGMAP_MINIMAL_PUBLISH_RESULT_v0.1.md`。

## 2026-07-17 更新（Second Wave Sprint #1）

ConfigMap 修改后不生效已完成生产：`publish_status=published`（internal soft launch，未加入 `LABGEN_ENABLED_LAB_IDS`），一轮真实 K3s rehearsal（VM 401）+ 一次 owner-as-learner smoke 全部通过，`cleanup_verified=true`。新增两个最小可复用 verifier（`configmap_value_equals`、`deployment_restart_triggered`/`deployment_restart_not_triggered`）——因 `kubectl exec` 对学员和 verifier 均被禁止，无法直接验证容器内运行进程的实际环境变量值，改用"Deployment 是否发生过 rollout restart"这一 K8s API 可直接观测、且逻辑等价的信号，已在真实集群上实测验证。详见 `CONFIGMAP_NOT_EFFECTIVE_LAB_PRODUCTION_RESULT_v0.1.md`。至此 second_wave 第一个主题完成，第二、三个主题（DNS 服务发现失败、Pod Pending）尚未开始。

## 2026-07-13 更新（Phase 1 First Wave Sprint #3）

ImagePullBackOff 已完成生产：`publish_status=published`（internal soft launch，未加入 `LABGEN_ENABLED_LAB_IDS`），两轮真实 K3s rehearsal + 一次 owner-as-learner smoke 全部通过，`cleanup_verified=true`。详见 `IMAGE_PULL_BACKOFF_LAB_PRODUCTION_RESULT_v0.1.md`。至此 first_wave 三个 lab 全部完成，second_wave 尚未开始。

## 系列定义

```
series_name: Kubernetes 常见故障排查实战系列 / Kubernetes Troubleshooting Guided Labs
runtime_scope: 单命名空间、single K3s runtime（不涉及多 VM / 多节点）
```

## first_batch（系列全量范围）

| # | 主题 | 状态 |
|---|------|------|
| 1 | CrashLoopBackOff | 已发布（internal soft launch，未对外） |
| 2 | Service 没有 Endpoints（selector 与 labels 不匹配） | 已发布（internal soft launch，未对外） |
| 3 | ImagePullBackOff | 已发布（internal soft launch，未对外） |
| 4 | ConfigMap 修改后不生效 | 已正式公开发布 |
| 5 | DNS 服务发现失败 | 已发布（internal soft launch，未对外） |
| 6 | Pod Pending | 未生产 |

## first_wave（优先生产顺序，与已完成的 lab 保持连续）

1. CrashLoopBackOff（已完成）
2. Service 没有 Endpoints（已完成）
3. ImagePullBackOff（已完成 —— 与前两个共享"Pod 状态类"故障诊断心智模型，学习曲线平滑；三者共同覆盖"起不来 / 起来了没流量 / 从没起来"三条互补诊断路径）

first_wave 全部完成，下一步排期进入 second_wave。

## second_wave

4. ConfigMap 修改后不生效（已完成 —— Second Wave 第一个"配置类"故障，与 First Wave 三个"Pod 状态类"故障互补，验证了"没有报错但行为不符合预期"这类新的判断分支；新增 configmap_value_equals/deployment_restart_triggered/deployment_restart_not_triggered 三个 verifier，为未来同类"配置生效时机"主题打下可复用基础）
5. DNS 服务发现失败（已完成生产、internal soft launch —— Second Wave 第二个主题，与前四个"workload/配置类"故障互补，覆盖"namespace 隔离导致的服务发现失败"这一新判断分支；新增 pod_succeeded/pod_log_contains 两个 verifier，为未来"无法用 kubectl exec 观察、需要读日志/终止状态判断"的场景打下可复用基础；发现并修复了 verifier ClusterRole 权限缺口的 BLOCKER，对整个系列的只读 verifier 类型扩展都有参考价值）
6. Pod Pending

## deferred（明确排除在 Phase 1 之外）

- PVC Pending（涉及存储子系统，超出单命名空间范围）
- Ingress 404/502（依赖 Ingress Controller，当前 K3s 环境未标准化部署）
- NetworkPolicy（依赖 CNI 插件能力，K3s 默认 flannel 不支持）
- multi-VM / multi-node Kubernetes（超出 Phase 1 单 VM runtime 假设）
- BGP / OSPF（属于网络实验系列而非 K8s 故障排查系列，跨系列话题）

## Phase 1 约束（重申，供后续 sprint 对照）

- Lab-to-Article 顺序固定：**先有已通过 rehearsal 验证的 lab，再基于 lab 实操写 official article**，不允许倒序（先写文章再补 lab 容易导致文章描述与实际实验步骤脱节）
- 文章不允许无病呻吟式营销开头，正文必须基于真实的排查点、真实报错信息、真实修复路径、可验证的学习路径价值
- Phase 1 默认场景为 k8s_namespace / single runtime，不新增 VM 类型

## 与已有产品文档的关系

- 本文档是 `PROJECT_NORTH_STAR_v0.1.md` 之下、单个 lab 设计文档之上的中间层，用于回答"下一个该做哪个 lab"这个排期问题
- 不替代、不修改 `SERVICE_NO_ENDPOINTS_LAB_DESIGN_CONTRACT_v0.1.md` 等已有单 lab 文档
