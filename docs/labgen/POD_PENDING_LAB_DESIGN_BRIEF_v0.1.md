# Pod Pending Lab Design Brief v0.1

## 实验步骤（已在真实 K3s VM 401 上逐条实测验证）

| Step | 内容 | Verify |
|---|---|---|
| s1-create-baseline-deployment | `kubectl create deployment demo --image=172.16.100.1:5000/library/busybox:1 -- sh -c "sleep 3600"`，确认正常调度成功 | `deployment_ready(demo)` |
| s2-configure-bad-node-selector | `kubectl patch deployment demo --type=merge -p '{"spec":{"template":{"spec":{"nodeSelector":{"labgen.example/worker":"missing"}}}}}'`，触发新 Pod 无法调度 | `pod_phase_equals(name=demo, label_selector="app=demo", expected_phase="Pending")` |
| s3-confirm-unschedulable-reason | `kubectl describe pod -l app=demo`，确认 `PodScheduled=False`/`reason=Unschedulable`/message 提到 node selector 不匹配 | `pod_scheduling_unschedulable(name=demo, label_selector="app=demo", message_contains="node(s) didn't match Pod's node affinity/selector")` |
| s4-fix-node-selector | `kubectl patch deployment demo --type=json -p '[{"op":"remove","path":"/spec/template/spec/nodeSelector"}]'`，非交互式移除错误 selector（不用 `kubectl edit`） | `deployment_ready(demo)` |
| s5-cleanup | `kubectl delete deployment demo` | 无（namespace 整体回收在会话结束时统一处理） |

## 关键实测结果（VM 401，真实 K3s v1.34.4）

- Step1 后：Pod 立即 `Running`（无 nodeSelector，正常调度）
- Step2 后（`kubectl patch --type=merge` 注入 `nodeSelector`）：触发新 ReplicaSet，新 Pod `phase=Pending`；旧 Pod 因默认 RollingUpdate 策略（`maxSurge=1`/`maxUnavailable=0`，1 副本时优先起新的再退旧的）继续 `Running` 直到新 Pod Ready——两个 Pod 短暂共存，新 Pod 一直 `Pending`（因为永远无法 Ready）
- Step3 实测 `status.conditions`：
  ```json
  {"type": "PodScheduled", "status": "False", "reason": "Unschedulable",
   "message": "0/1 nodes are available: 1 node(s) didn't match Pod's node affinity/selector. ..."}
  ```
  `kubectl describe pod` 的 Events 里同样出现 `Warning FailedScheduling ... node(s) didn't match Pod's node affinity/selector`
- Step4 后（json patch 移除 `nodeSelector`）：Pod 模板与最初的 ReplicaSet 完全一致，Kubernetes 直接把原 ReplicaSet 缩容回 1（不是创建第三个 ReplicaSet），`kubectl rollout status` 返回 `successfully rolled out`

## 与既有 verifier 的复用关系

- `deployment_ready`（已实现，Step1/Step4 直接复用）
- 新增 `pod_phase_equals`：检查任意匹配 label_selector 的 Pod 是否处于指定 phase——与 `pod_running`/`pod_succeeded` 保持一致的"任一匹配即算"语义（Step2 时 namespace 里同时存在一个 Running 旧 Pod 和一个 Pending 新 Pod，必须能正确挑出符合条件的那个，而不是只看第一个）
- 新增 `pod_scheduling_unschedulable`：检查任意匹配 Pod 的 `status.conditions` 中是否存在 `type=PodScheduled, status=False, reason=Unschedulable`；`message_contains` 为可选参数，用于进一步确认失败原因具体是 node selector 不匹配（而非资源不足/taint），避免只依赖 Events 文本（Events 有 TTL 会过期，Pod condition 是当前状态的权威来源，更稳定）

## 学员 RBAC 边界确认（先读代码不猜测）

读 `backend/labgen/learner_credentials.py` 确认：`deployments` 已授予 `create/get/list/watch/delete/update/patch`（`patch` 覆盖 Step2/Step4 的两次 `kubectl patch`），`pods`/`events` 已授予 `get/list/watch`（覆盖 `kubectl describe pod`）。整个实验流程不需要任何超出既有 First Wave/ConfigMap/DNS 系列已验证过的 RBAC 权限，不需要新增任何授权。

## 严格遵守的约束

- 不使用真实 Node label/taint/scheduler 配置——`labgen.example/worker` 是一个平台/集群里任何节点都不会有的自造键，不触碰任何真实调度策略
- 不使用 PVC/StorageClass
- 不使用多 VM/多节点——K3s 单节点集群上即可稳定复现（调度器在单节点集群里同样会对 nodeSelector 不匹配的 Pod 返回 Unschedulable）
- 不依赖外网镜像——沿用系列统一使用的内部 registry mirror busybox 镜像
- 不使用 `kubectl edit`——两次配置变更均用非交互式 `kubectl patch`（merge 类型注入、json 类型的 remove 操作移除），与 ConfigMap lab 里"不用 kubectl edit"的先例一致
