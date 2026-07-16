# Official Article Final Draft — CrashLoopBackOff v1.0

## 标题

Pod 一直重启？从 CrashLoopBackOff 学会用 describe 和 logs 定位根因

## 正文草稿

### 症状

你刚把一个新版本的 Deployment 推上测试环境，`kubectl apply` 很快返回了成功——但这只说明这个对象被 Kubernetes 接收了，不代表容器已经稳定运行。几分钟后回来看，服务还是没起来：`kubectl get pods` 里 `STATUS` 写着 `CrashLoopBackOff`，`RESTARTS` 那一列的数字比你离开前还要大。容器好像"活过"又"死了"，一直循环。

这是 Kubernetes 里最常见的故障状态之一，根因几乎总是同一件事：容器启动后立刻退出。Kubernetes 的默认行为是不断尝试重启它，每次重启之间的等待时间会指数增长（这个退避机制正是"Back-off"名字的由来），但只要根因不解决，重启多少次都不会自愈。

### 为什么这不是"重启一下就好"

看到"重启"两个字，很多人第一反应是等它自己恢复，或者手动删掉 Pod 让 Kubernetes 重新拉起一个。但 CrashLoopBackOff 的重启循环本身就是"容器每次启动都失败"的证据——Kubernetes 已经在不断重试了，如果重试能解决问题，它早就成功了。看到 RESTARTS 持续增加，正确的反应不是等待或删除重建，而是立刻切换到排查模式：容器启动后到底做了什么、为什么会退出。

### 判定依据：CrashLoopBackOff 与 ImagePullBackOff 的最快区分方式

`kubectl get pods` 里 `RESTARTS` 列持续增加，通常说明容器已经启动过并进入了重启循环——这时候应该继续查 `Last State`/`Exit Code`/`logs --previous`（下文会讲），而不是去查镜像拉取问题。这一点和 `ImagePullBackOff` 正好相反：`ImagePullBackOff` 大多数情况下 `RESTARTS` 会长时间保持为 `0`，因为镜像根本没有拉取成功，容器根本未曾正式启动过，也就谈不上"重启"。容器有没有真正启动过，决定了下一步该查日志还是查镜像拉取事件——这是两者最快的区分方法。

```
kubectl get pods
```

```
NAME                          READY   STATUS             RESTARTS   AGE
crash-demo-xxxxxxxxxx-xxxxx   0/1     CrashLoopBackOff   3          45s
```

### 用 describe 看 Last State 和退出码

```
kubectl describe pods -l app=crash-demo
```

重点看 `Last State` 段落，会看到类似：

```
Last State:     Terminated
  Reason:       Error
  Exit Code:    127
```

`Exit Code: 127` 是 shell 的标准约定，表示"命令未找到"。这一步比直接翻日志更快——退出码本身已经给出了强烈的方向性线索，不需要等日志才能猜测问题类型。`Events` 段落还会看到 `Back-off restarting failed container`，说明 Kubernetes 已经识别出这是一个持续失败的容器，进入了退避重试节奏。

### 用 logs 和 logs --previous 看真实错误输出

```
kubectl logs -l app=crash-demo
kubectl logs -l app=crash-demo --previous
```

`kubectl logs` 拿到的是当前（可能是刚重启的新）容器的输出；`--previous` 拿到的是上一次已经终止的容器的输出——即使容器此刻已经被重启过，历史崩溃时的真实报错依然可以取回。这里能看到类似：

```
starting
/bin/sh: /app/missing-command: not found
```

这条 `not found` 才是崩溃的直接原因，比退出码更具体：不是权限问题、不是镜像问题，就是命令路径写错了。

### 修复思路：非交互式，而且要修在源头

用一条 `kubectl patch` 命令，把容器的启动命令换成一条不会崩溃的命令：

```
kubectl patch deployment crash-demo --type=json -p='[ ... 替换 command 字段 ... ]'
```

完整的 JSON Patch 写法会比较长（这是 JSON Patch 格式本身的特点），配套实验里能直接复制完整版本。这条命令做的事情很直接：把容器原来那条会立刻崩溃的启动命令，替换成一条能正常运行的命令。很多人第一反应是 `kubectl edit`，但那会打开一个交互式编辑器，不适合脚本化、不可审计、也不方便在 CI 里复用；`kubectl patch` 非交互式地完成同一件事，修复动作本身就是一条可复制、可审计、可回放的命令。

### 用 rollout status 确认真正修复

```
kubectl rollout status deployment/crash-demo --timeout=90s
kubectl get pods
```

`patch` 命令返回成功不等于 Pod 已经真的稳定运行——滚动更新需要时间，新 Pod 也可能因为别的原因再次失败。`rollout status` 会阻塞直到 Deployment 完全就绪才返回，看到 `successfully rolled out` 加上 `kubectl get pods` 里 `READY=1/1`、`STATUS=Running`，才是修复真正生效的确认。

### 排查心智模型（与 ImagePullBackOff 互补）

- **RESTARTS 持续增加** → CrashLoopBackOff，查 `describe` 的 Last State/Exit Code，再查 `logs --previous`
- **RESTARTS 大多数情况下长时间为 0** → 大概率是 ImagePullBackOff/ErrImagePull，查 `describe` 的 Events，不要查日志（容器从未正式启动过，没有日志）

---

## 配套实验

本文章配套一个可动手操作的实验，实验环境会预置一个真实会持续崩溃的 Deployment，你可以亲手用上面的步骤诊断和修复它，而不只是看文字。

以下保留两个版本的引导文案，供发布时按当时的实际开放状态二选一使用，**当前只有 internal_preview_version 版本生效**，public_publish_version 是提前写好的占位草稿，尚未启用：

**internal_preview_version（当前生效）**

> **当前状态**：该实验目前处于内部验证阶段，尚未对外开放注册用户访问。

**public_publish_version（发布后启用，当前未生效，仅作占位草稿保留）**

> 想亲手试一次吗？点击「进入实验」，几秒钟内就能拿到一个预置了这个故障的 Kubernetes 环境，用上面讲的每一条命令亲自诊断、亲自修复。
