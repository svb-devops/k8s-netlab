# Pod Pending Topic Brief v0.1

## 现象

`kubectl create deployment` 或 `kubectl apply` 之后，Pod 状态一直停在 `Pending`，`READY` 是 `0/1`，且永远不会变化。没有 `RESTARTS` 计数增长（因为容器从未启动过），`kubectl logs` 直接报错"容器还没启动，没有日志"。

## 关键判定：Pending 不是"容器起不来"，是"还没被调度到任何节点"

`CrashLoopBackOff`/`ImagePullBackOff` 都发生在 **容器已经被调度到某个节点、kubelet 正在尝试启动它** 之后；而 `Pending` 发生在更早的阶段——**调度器（scheduler）还没有为这个 Pod 选出一个可用节点**。这个阶段性差异决定了排查路径完全不同：

- `CrashLoopBackOff`/`ImagePullBackOff` → 看 `kubectl logs`、看容器退出码
- `Pending`（未分配节点）→ 看 `kubectl get pod -o wide` 的 `NODE` 列是否为空、看 `status.conditions` 里的 `PodScheduled` 状态、看 `kubectl describe pod` 的 Events

`kubectl logs` 对一个从未被调度、从未创建容器的 Pod 完全没有意义——kubelet 根本没有在任何节点上为它分配运行时，日志无从谈起。这是本主题最容易被误判的地方：习惯了先查日志的排查路径，在这里会直接扑空。

## 常见触发原因（本 lab 聚焦 nodeSelector 一类）

调度失败的常见原因包括：nodeSelector/nodeAffinity 不匹配、资源请求超过所有节点可用容量、taint 没有对应 toleration、PVC 无法绑定。本 lab 聚焦最容易复现、最不需要碰生产敏感配置（不改真实 Node label/taint、不涉及存储子系统）的一种：**Deployment 的 Pod 模板里配置了一个集群里不存在的 `nodeSelector` 键值对**。

## 判定依据

- `kubectl get pod -o wide` 的 `NODE` 列为空、`STATUS` 为 `Pending` → 尚未被调度，不要去查日志
- `kubectl describe pod` 的 `Conditions` 里 `PodScheduled=False`，`Events` 里出现 `FailedScheduling` → 明确是调度阶段失败
- Events/Condition 的 message 提到 "didn't match Pod's node affinity/selector" → 具体定位为 nodeSelector/nodeAffinity 不匹配（而非资源不足或 taint）
- 检查 Deployment 的 `spec.template.spec.nodeSelector`，确认其中的键值对确实在集群任何节点上都不存在
