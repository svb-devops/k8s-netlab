# Official Article Final Draft — ImagePullBackOff / ErrImagePull v1.0

## 标题

Pod 卡在 ImagePullBackOff？从 Events 看镜像拉取失败原因

## 正文草稿

### 症状

`kubectl apply` 或 `kubectl create deployment` 命令很快返回了成功——但这只说明这个对象被 Kubernetes 接收了，不代表容器已经稳定运行。等了一会儿回来看，Pod 还是迟迟起不来：`kubectl get pods` 显示 `STATUS` 是 `ImagePullBackOff` 或 `ErrImagePull`（两者会交替出现，是同一个故障在不同重试阶段的表现）。

很多人这时候会下意识地怀疑是 CrashLoopBackOff——毕竟都是"Pod 不 Ready"。但看一眼 `RESTARTS` 列就能大概率排除这个猜测：ImagePullBackOff 的 `RESTARTS` 大多数情况下会长时间保持为 `0`，因为镜像根本没有拉取成功，容器压根没有启动过，谈不上"重启"。这个判断依据比记住两个状态名字本身更重要——真实排查里，先分流"容器起来过没有"，能省掉一大半误判。

### 先看 READY 与 RESTARTS 两列

```
kubectl get pods
```

```
NAME                              READY   STATUS             RESTARTS   AGE
image-pull-demo-9ffd84674-bqdgt   0/1     ImagePullBackOff   0          15s
```

`READY=0/1` 且 `RESTARTS=0` 是 ImagePullBackOff 的判定特征。如果 `RESTARTS` 在增加，那大概率是 CrashLoopBackOff，排查路径完全不同——应该看 `kubectl logs`，而不是这里讲的 `kubectl describe`。

### 为什么这里查日志是死路

```
kubectl logs <pod-name>
```

这条命令在这里会返回空输出或"找不到已终止容器"之类的报错。日志是容器运行时产生的，容器从未运行过，自然没有日志。真正有用的命令是 `kubectl describe pod`。

### 用 describe 的 Events 段落定位根因

```
kubectl describe pod <pod-name>
```

重点看 `Events` 部分（不是 `Status` 或 `Conditions`）。真实的 Events 记录会比较长，摘要下来核心信息是这样：

```
Failed to pull image "...": ...resolve reference "...": ... not found
```

`... not found` 是 registry 对一个不存在的镜像/tag 的标准响应。持续观察还会看到 `Pulling`/`Failed` 事件反复出现——kubelet 在用指数退避（`Back-off`）策略反复重试同一个错误的镜像引用，这个重试不会让问题自愈，等多久都一样。

镜像拉取失败常见的四类根因：镜像名拼错、tag 不存在、registry 不可达、pull secret 缺失或权限不对。本文聚焦最常见的一种——tag 写错。

### 核对配置的镜像引用和容器名

```
kubectl get deployment <name> -o wide
```

`IMAGES` 列会显示实际配置的镜像引用，方便核对是否是 tag 拼写或版本号问题。`CONTAINERS` 列同样值得注意——`kubectl create deployment --image=...` 默认用**镜像名**（而不是 Deployment 名）作为容器名，下一步修复命令需要精确匹配这个名字，是很容易被忽略的细节。

### 修复：非交互式替换镜像

```
kubectl set image deployment/<name> <container-name>=<correct-image>
```

`kubectl set image` 是非交互式命令，只替换指定容器的镜像字段，不需要 `kubectl edit` 打开编辑器，也不需要手写 JSON Patch，修复动作可审计、可复现、可在脚本/CI 里直接调用。

### 验证修复

```
kubectl rollout status deployment/<name> --timeout=90s
kubectl get pods
```

看到 `successfully rolled out` 且 `READY=1/1`、`STATUS=Running`，说明新镜像拉取成功，Deployment 已恢复正常。

### 排查心智模型（与 CrashLoopBackOff 互补）

- **RESTARTS 持续增加** → 大概率是 CrashLoopBackOff，查 `kubectl logs`/`logs --previous`
- **RESTARTS 大多数情况下长时间为 0** → ImagePullBackOff/ErrImagePull，查 `describe` 的 Events，不要查日志（容器从未正式启动过，没有日志）

---

## 配套实验

本文章配套一个可动手操作的实验，实验环境会预置一个真实引用了不存在镜像 tag 的 Deployment，你可以亲手用上面的步骤诊断和修复它，而不只是看文字。

以下保留两个版本的引导文案，供发布时按当时的实际开放状态二选一使用，**当前只有 internal_preview_version 版本生效**，public_publish_version 是提前写好的占位草稿，尚未启用：

**internal_preview_version（当前生效）**

> **当前状态**：该实验目前处于内部验证阶段，尚未对外开放注册用户访问。

**public_publish_version（发布后启用，当前未生效，仅作占位草稿保留）**

> 想亲手试一次吗？点击「进入实验」，几秒钟内就能拿到一个预置了这个镜像拉取问题的 Deployment，用上面讲的每一条命令亲自诊断、亲自修复。
