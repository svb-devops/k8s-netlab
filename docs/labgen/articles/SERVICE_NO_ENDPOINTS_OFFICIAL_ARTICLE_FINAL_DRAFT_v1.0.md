# Official Article Final Draft — Service 无 Endpoints v1.0

## 标题

Service 建好了但访问不通？先检查 Endpoints 和 selector

## 正文草稿

### 症状

你部署了一个 Deployment，`kubectl get pods` 看到 Pod 状态是 `Running`；又建了一个 ClusterIP Service 指向它，一切看起来都该通了。但从集群内其他 Pod 用 Service 名去访问，连接不是超时就是直接被拒绝。更让人摸不着头脑的是：目标 Pod 的日志里什么错误都没有——因为压根没有一个请求真正到达过它。

### 为什么这不是"Pod 的问题"

第一反应通常是去查 Pod：重启一下、看看日志、检查健康探针。但如果 Pod 本身是 `Running` 且日志安静，说明问题很可能根本不在 Pod 这一层，而在 Service 和 Pod 之间的那层路由——Service 有没有真的找到这个 Pod。这一步判断能帮你省掉大量在错误方向上的排查时间。

### 先查 Endpoints，不是查 Pod 日志

```
kubectl get endpoints web-svc
```

如果 `ENDPOINTS` 列是空的（`<none>`），说明 Kubernetes 从未找到任何 Pod 满足这个 Service 的 selector——这才是问题真正发生的地方。这一步比查 Pod 日志更快定位问题：Pod 日志此时是"健康但沉默"的，不会给你任何线索。

> 提醒：`kubectl describe service` 里的 Endpoints 字段在部分 K3s 版本下可能不可靠（曾在 K3s v1.34.4 上观察到该字段持续显示 `<none>` 而 `kubectl get endpoints` 显示正确值），排查时以 `kubectl get endpoints` 为准。

### 对比 Service 的 selector 和 Pod 的标签

```
kubectl describe service web-svc
```

关注 `Selector` 那一行，例如 `app=web-svc`。再看 Pod 实际的标签：

```
kubectl get pods --show-labels
```

对比一下：如果 Pod 的标签是 `app=web-backend`，而 Service 的 selector 是 `app=web-svc`，两者对不上——这就是根因。`kubectl create service clusterip` 在不显式指定 `--selector` 时的默认值，不会自动跟 `kubectl create deployment` 生成的标签对齐，这是本故障最常见的触发路径。

### 修复：重建比手动改更稳妥

不建议手动 `kubectl patch service` 改 selector——容易再打错一次字，而且在真实生产集群里，Service 相关的写权限通常受限。更稳妥的做法是删掉重建，让 `kubectl expose` 直接从 Deployment 的真实标签生成 selector：

```
kubectl delete service web-svc
kubectl expose deployment web-backend --port=80 --name=web-svc
```

### 验证修复

```
kubectl get endpoints web-svc
```

`ENDPOINTS` 列此时应该出现 Pod 的 IP:端口，说明 Service 已经能正确路由流量了。

### 排查心智模型（与 CrashLoopBackOff / ImagePullBackOff 互补）

- **`kubectl get endpoints` 为空** → 对比 selector（`describe service`）与 labels（`get pods --show-labels`），大概率是两者不匹配
- **`kubectl get endpoints` 不为空但仍连不通** → 问题不在 Service 层，去查 NetworkPolicy / DNS / 应用本身
- **连不通的其实是 Pod 本身起不来** → 看的是另外两篇文章：`RESTARTS` 持续增加查 CrashLoopBackOff，`RESTARTS` 大多数情况下长时间为 0 查 ImagePullBackOff

---

## 配套实验

本文章配套一个可动手操作的实验，实验环境会预置一个真实存在这个 bug 的 Service，你可以亲手用上面的步骤诊断和修复它，而不只是看文字。

以下保留两个版本的引导文案，供发布时按当时的实际开放状态二选一使用，**当前只有 internal_preview_version 版本生效**，public_publish_version 是提前写好的占位草稿，尚未启用：

**internal_preview_version（当前生效）**

> **当前状态**：该实验目前处于内部验证阶段，尚未对外开放注册用户访问。

**public_publish_version（发布后启用，当前未生效，仅作占位草稿保留）**

> 想亲手试一次吗？点击「进入实验」，几秒钟内就能拿到一个预置了这个 selector/labels 不匹配问题的 Service，用上面讲的每一条命令亲自诊断、亲自修复。
