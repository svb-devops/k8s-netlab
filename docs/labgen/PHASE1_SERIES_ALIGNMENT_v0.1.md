# Phase 1 Series Alignment v0.1

## 状态

`documentation_only` —— 本文档不改变任何代码行为、不开放任何访问权限。目的是把已经产出的三个 lab（CrashLoopBackOff、Service 无 Endpoints、ImagePullBackOff）放进一个明确的系列结构里，为后续排期提供依据。

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
| 4 | ConfigMap 修改后不生效 | 未生产 |
| 5 | DNS 服务发现失败 | 未生产 |
| 6 | Pod Pending | 未生产 |

## first_wave（优先生产顺序，与已完成的 lab 保持连续）

1. CrashLoopBackOff（已完成）
2. Service 没有 Endpoints（已完成）
3. ImagePullBackOff（已完成 —— 与前两个共享"Pod 状态类"故障诊断心智模型，学习曲线平滑；三者共同覆盖"起不来 / 起来了没流量 / 从没起来"三条互补诊断路径）

first_wave 全部完成，下一步排期进入 second_wave。

## second_wave

4. ConfigMap 修改后不生效
5. DNS 服务发现失败
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
