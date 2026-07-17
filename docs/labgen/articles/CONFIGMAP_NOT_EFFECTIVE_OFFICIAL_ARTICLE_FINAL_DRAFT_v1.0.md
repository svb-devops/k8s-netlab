# Official Article Final Draft — ConfigMap 修改后不生效 v1.0

## 标题

ConfigMap 改了但应用为什么还是旧配置？

## 正文草稿

### 症状

你用 `kubectl patch configmap` 或 `kubectl edit configmap` 把一个配置值改了，命令立刻返回成功；用 `kubectl describe configmap` 再确认一遍，Data 段里确确实实已经是新值。但应用的实际行为——不管是接口返回、日志输出还是任何可观察的表现——完全没变，就像这次修改从未发生过一样。

这类故障最反直觉的地方在于：**没有任何报错**。不是 CrashLoopBackOff，不是 Pending，不是 ImagePullBackOff——`kubectl get pods` 看到的一切都很正常，Pod 是 `Running`，`READY` 是 `1/1`。习惯了"看报错、看状态"的排查路径在这里完全用不上。

### 为什么"配置对象已更新"不等于"运行中容器已应用新配置"

根因在于 Kubernetes 处理 ConfigMap 引用的方式：通过 `envFrom` 或 `env.valueFrom.configMapKeyRef` 注入到容器里的环境变量，**只在容器被创建的那一刻由 kubelet 解析一次**，解析结果直接写死进这个容器的进程环境。之后不管你把 ConfigMap 对象本身改成什么，这个已经在运行的容器都不会重新读取——它不知道 ConfigMap 变了，也没有任何机制通知它去重新读。

这不是 bug，是 Kubernetes 的既有设计：Pod 一旦创建，容器的进程环境就是不可变的。要让新配置真正生效，唯一的办法是让 Kubernetes 创建一个新的容器。

（题外话：如果 ConfigMap 是以卷（Volume）的方式挂载进容器而不是作为环境变量，kubelet 会周期性同步卷内容，通常一分钟左右生效，行为和这里完全不同——但这是另一个话题，本文只讲环境变量注入这一种最常见的方式。）

### 判定依据：什么时候该往这个方向想

当你发现"配置对象本身确实已经更新，但应用行为没有任何变化"时，不要去看 Pod 状态或 Service 状态——它们大概率都完全正常。该检查的是：**这个配置对象是不是在当前运行的这个 Pod 创建之后才被修改的**。判断方法很直接：对比一下当前 Pod 的存在时间（`AGE`）和你上一次修改配置的时间，如果 Pod 比这次修改还早，答案就已经很明显了。

```
kubectl get pods -l app=demo
```

```
NAME                    READY   STATUS    RESTARTS   AGE
demo-86549bf9fc-p7lqp   1/1     Running   0          2m
```

如果你确认几分钟前才改的配置，而这个 Pod 已经存在了更长时间，它读到的必然还是旧值。

### 修复：用 rollout restart 强制创建新 Pod

```
kubectl rollout restart deployment/demo
```

`kubectl rollout restart` 会在 Deployment 的 Pod 模板上写入一个 `kubectl.kubernetes.io/restartedAt` 注解。这个注解本身没有业务含义，但它改变了 Pod 模板的内容——而 Pod 模板一旦变化，Kubernetes 就会认为需要一次新的滚动更新，进而创建新的 ReplicaSet 和新的 Pod。新 Pod 在创建时会重新解析 ConfigMap，这次读到的就是最新值。

这是非交互式、可脚本化、生产环境安全的标准做法，不需要 `kubectl edit`（会打开交互式编辑器），也不需要手动删除 Pod 再重建（Deployment 会立刻按旧模板补一个新的，白费功夫）。

### 用 rollout status 确认新 Pod 已经生效

```
kubectl rollout status deployment/demo
kubectl get pods -l app=demo
```

`rollout status` 会阻塞直到滚动更新完全完成才返回 `successfully rolled out`；`get pods` 应该能看到一个全新的 Pod 名字，`AGE` 从几秒重新开始计时——这个新 Pod 是在配置更新之后才被创建的，它读到的必然是新值。

### 排查心智模型

- **配置对象已确认更新，但应用行为完全没变，也没有任何报错** → 先别怀疑 Pod/Service 状态，检查这个配置是不是在当前运行的容器创建之后才改的
- **确认是"创建时机早于配置变更"** → 用 `kubectl rollout restart` 强制触发新 Pod 创建，而不是等待、删除重建或去改 Pod 本身（Pod 的多数字段创建后不可变，这条路走不通）
- **生产环境提醒**：本文演示的手工 `patch` + 手工 `rollout restart` 是为了教学上更容易观察这个现象。生产环境中，这类配置变更通常是通过修改 Deployment YAML、Helm values 或者 GitOps 流水线来触发一次正式的滚动更新，而不是运维人员手工执行这两条命令

---

## 配套实验

本文章配套一个可动手操作的实验，实验环境会预置一个真实的"ConfigMap 已更新但 Pod 未生效"场景，你可以亲手用上面的步骤观察这个现象、并用 `rollout restart` 修复它，而不只是看文字。

以下保留两个版本的引导文案，供发布时按当时的实际开放状态二选一使用，**当前只有 internal_preview_version 版本生效**，public_publish_version 是提前写好的占位草稿，尚未启用：

**internal_preview_version（当前生效）**

> **当前状态**：该实验目前处于内部验证阶段，尚未对外开放注册用户访问。

**public_publish_version（发布后启用，当前未生效，仅作占位草稿保留）**

> 想亲手试一次吗？点击「进入实验」，几秒钟内就能拿到一个预置了这个场景的 Kubernetes 环境，用上面讲的每一条命令亲自观察、亲自修复。
