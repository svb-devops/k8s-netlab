# DNS Service Discovery Lab Design Brief v0.1

## 与原始任务书设计的偏差说明（必读，先读代码不猜测）

任务书原始设计是"学员自己创建 target namespace + client namespace，跨 namespace 观察短名称解析失败"。实际读 `backend/labgen/learner_credentials.py`（`LEARNER_ALLOWED_PERMISSIONS`）后确认：**学员 RBAC 完全不包含 `namespaces` 资源的任何权限**（create/get/list 都没有）——学员的会话 namespace 是平台在 `NAMESPACE_CREATING` 状态里代为创建的，从未、也不应该允许学员自己创建第二个 namespace（这是安全边界，不是遗漏）。

同时确认 `LEARNER_ALLOWED_PERMISSIONS` 里也没有 `pods`/`batch/jobs` 的 `create` 权限——学员能创建的工作负载类型只有 `deployments`（`apps` API group，`create/get/list/watch/delete/update/patch`）。这意味着任务书里提到的"用 Job/Pod + kubectl logs"方案在当前 RBAC 下不可行：学员既不能建第二个 namespace，也不能直接建 Pod/Job。

**实际设计**：

1. 目标 Service 部署在一个平台预先建好的共享 namespace `labgen-dns-target`（`api` Service + Deployment，镜像 `172.16.100.1:5000/library/busybox:1`，`sleep 3600` 保活），性质上类似平台已有的 registry mirror / kube-dns——由运维一次性创建维护，不属于任何学员会话生命周期，不随会话清理。
2. DNS 解析本身是网络层查询（CoreDNS 集群内可达任意 namespace 的 Service 记录），**不需要跨 namespace 的 RBAC 权限**——学员只需要在自己的 namespace 里创建一个诊断 Deployment 发起 nslookup 查询即可，完全在既有 RBAC 范围内。
3. 诊断 Deployment 容器启动命令一次性执行两条 nslookup（短名称 + FQDN），把判断结果打印成稳定标记后 `sleep 3600` 保活，避免依赖被禁止的 `kubectl exec`。

已在真实 K3s（VM 401）验证：从其他 namespace 用短名称 `api` 查询 `labgen-dns-target` 里的 `api` Service 确实 NXDOMAIN，用 FQDN `api.labgen-dns-target.svc.cluster.local` 确实解析成功（IP 与该 Service 的 ClusterIP 一致）。

## 实验步骤

| Step | 内容 | Verify |
|---|---|---|
| s1-create-diagnostic-deployment | 创建诊断 Deployment，容器一次性跑两条 nslookup 并打印标记后保活 | `deployment_ready(dns-check)` |
| s2-confirm-short-name-fails | `kubectl logs -l app=dns-check` 确认短名称失败标记 | `pod_log_contains(dns-check, "SHORT_NAME_FAILED_AS_EXPECTED")` |
| s3-confirm-fqdn-succeeds | 同上，确认 FQDN 成功标记 | `pod_log_contains(dns-check, "SERVICE_FQDN_RESOLVED")` |
| s4-cleanup | 删除诊断 Deployment | 无（namespace 整体回收在会话结束时统一处理） |

## 新增 verifier 能力

- `pod_succeeded`：读 Pod `status.phase == Succeeded`（本 lab 未使用——诊断容器用 `sleep 3600` 保活以配合已有的 `deployment_ready`，避免学员 RBAC 不支持的 Job/裸 Pod；`pod_succeeded` 作为通用能力保留给未来一次性诊断任务场景复用）
- `pod_log_contains`：读 Pod 日志（`read_namespaced_pod_log`，list+get on `pods/log`，不是 `kubectl exec`）确认包含指定标记字符串

## BLOCKER 修复：verifier ClusterRole 缺少 `pods/log:get`

`pod_log_contains` 首次在真实集群跑 rehearsal 时因为 `lab-verifier-namespace-readonly` ClusterRole 没有 `pods/log` 权限而 500（`Forbidden: cannot get resource "pods/log"`）。`backend/labgen/verifier_credentials.py` 的 `_CLUSTER_ROLE_MANIFEST` 和 `PlatformVerifierInitializer.ensure_verifier_identity` 里的 `V1PolicyRule` 都补充了 `pods/log: [get]`（日志读取没有 list 语义等价物，这是唯一一处不得不用 `get` verb 的例外，已在两处保持一致并有交叉校验测试 `test_sdk_object_matches_manifest_string` 覆盖）。修复后对 VM 401 重跑 `initialize_verifier_for_vm_host_side`（幂等）使 RBAC 生效，两轮真实 rehearsal 全部通过。

## 资产沉淀

- `pod_log_contains` / `pod_succeeded` verifier 能力可复用于任何"无法用 `kubectl exec` 观察容器内部状态、但结果能通过日志或 Pod 终止状态体现"的场景
- verifier ClusterRole 缺少某个资源权限导致的 500（而非 403 静默失败）是这类新增 verifier 类型的通用坑——下次新增只读 verifier 类型时，先确认 `lab-verifier-namespace-readonly` ClusterRole 是否已覆盖对应资源/verb，再做 rehearsal
