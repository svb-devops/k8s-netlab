# Official Article Final Draft — ImagePullBackOff / ErrImagePull v1.0

## 元信息

```
article_status: ready_to_publish_draft   # 不是 published，也不是 cta_enabled
article_url: null
cta_enabled: false
target_directus_article_id: null   # 未创建 Directus 记录，本文档是内容草稿，不是已上线内容
lab_id: eb78afaa-f7fb-422e-8eb9-98644f59527f
source_article_id (LabGen 内部草稿, 非 Directus): da282651-f66f-405b-abc1-b3dc563feb6a
lab_title: Kubernetes ImagePullBackOff 排查实验：用 describe 的 Events 定位镜像拉取失败原因
lab publish_status（当前生产实际值）: published
```

本文档只是文字草稿，**不**通过 Directus/CTA 工具对外发布，不修改任何生产 lab/article-draft 字段。

> 本文档是 `IMAGE_PULL_BACKOFF_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 的最终定稿版本（v1.0），改动仅限：① 标题改为与另外两篇文章统一的"疑问句+排查线索"风格（原标题"先看 RESTARTS 是不是 0"移入正文第一步作为判定依据）；② blockers 章节按 2026-07-15 三篇文章统一收口的最新状态重新核对。正文技术内容与 v0.1 一致，均来自两轮真实 K3s rehearsal 与一次 owner-as-learner smoke 的实际执行结果，未做实质性改写。

---

## 标题

Pod 卡在 ImagePullBackOff？从 Events 看镜像拉取失败原因

## 正文草稿

### 症状

`kubectl apply` 或 `kubectl create deployment` 命令本身返回成功，但 Pod 迟迟起不来。`kubectl get pods` 显示 `STATUS` 是 `ImagePullBackOff` 或 `ErrImagePull`（两者会交替出现，是同一个故障在不同重试阶段的表现）。

很多人这时候会下意识地怀疑是 CrashLoopBackOff——毕竟都是"Pod 不 Ready"。但看一眼 `RESTARTS` 列就能立刻排除这个猜测：ImagePullBackOff 的 `RESTARTS` 永远是 `0`，不会随时间增加。这是因为容器根本没有启动过，谈不上"重启"。这个判断依据比记住两个状态名字本身更重要——真实排查里，先分流"容器起来过没有"，能省掉一大半误判。

### 第一步：确认症状——READY 与 RESTARTS 两列

```
kubectl get pods
```

```
NAME                              READY   STATUS             RESTARTS   AGE
image-pull-demo-9ffd84674-bqdgt   0/1     ImagePullBackOff   0          15s
```

`READY=0/1` 且 `RESTARTS=0` 是 ImagePullBackOff 的判定特征。如果 `RESTARTS` 在增加，那是 CrashLoopBackOff，排查路径完全不同（应该看 `kubectl logs`，而不是这里讲的 `kubectl describe`）。

### 第二步：为什么不能查日志

```
kubectl logs <pod-name>
```

这条命令在这里是死路——会返回空输出或 `previous terminated container ... not found` 之类的报错。日志是容器运行时产生的，容器从未运行过，自然没有日志。真正有用的命令是 `kubectl describe pod`。

### 第三步：用 describe 的 Events 段落定位根因

```
kubectl describe pod <pod-name>
```

重点看 `Events` 部分（不是 `Status` 或 `Conditions`），会看到类似：

```
Warning  Failed  kubelet  Failed to pull image "...": rpc error: code = NotFound desc = failed to pull and unpack image "...": failed to resolve reference "...": ... not found
Warning  Failed  kubelet  Error: ErrImagePull
```

`... not found` 是 registry 对一个不存在的镜像/tag 的标准响应。持续观察还会看到 `Pulling`/`Failed` 事件反复出现——kubelet 在用指数退避（`Back-off`）策略反复重试同一个错误的镜像引用，这个重试不会让问题自愈，等多久都一样。

镜像拉取失败常见的四类根因：镜像名拼错、tag 不存在、registry 不可达、pull secret 缺失或权限不对。本文聚焦最常见的一种——tag 写错。

### 第四步：核对配置的镜像引用和容器名

```
kubectl get deployment <name> -o wide
```

`IMAGES` 列会显示实际配置的镜像引用，方便核对是否是 tag 拼写或版本号问题。`CONTAINERS` 列同样值得注意——`kubectl create deployment --image=...` 默认用**镜像名**（而不是 Deployment 名）作为容器名，下一步修复命令需要精确匹配这个名字，是本实验最容易被忽略的细节。

### 第五步：修复

```
kubectl set image deployment/<name> <container-name>=<correct-image>
```

`kubectl set image` 是非交互式命令，只替换指定容器的镜像字段，不需要 `kubectl edit` 打开编辑器，也不需要手写 JSON Patch，修复动作可审计、可复现、可在脚本/CI 里直接调用。

### 第六步：验证修复

```
kubectl rollout status deployment/<name> --timeout=90s
kubectl get pods
```

看到 `successfully rolled out` 且 `READY=1/1`、`STATUS=Running`，说明新镜像拉取成功，Deployment 已恢复正常。

### 排查心智模型（与 CrashLoopBackOff 互补）

```
Pod 不 Ready
  → RESTARTS 是否在增加？
      是 → CrashLoopBackOff，查 kubectl logs / logs --previous
      否（恒为 0） → ImagePullBackOff/ErrImagePull，查 kubectl describe 的 Events，不要查日志
```

---

## 配套实验

本文章配套一个可动手操作的实验，实验环境会预置一个真实引用了不存在镜像 tag 的 Deployment，你可以亲手用上面的步骤诊断和修复它，而不只是看文字。

> **当前状态**：该实验目前处于内部验证阶段，尚未对外开放注册用户访问。

---

## 发布前 blockers（未满足，不允许标记为 published）

1. `article_url` 为空 —— 尚未在 Directus 创建正式文章记录
2. `cta_enabled=false` —— CTA 未对外暴露，"配套实验"段落里的引导文字是占位性质，不能上线成死链接或误导性 CTA
3. 真实学生对该 lab 仍 403（`LABGEN_ENABLED_LAB_IDS` 未包含此 lab_id）—— 文章一旦公开发布但学生点不进实验，会造成负面体验，因此文章发布必须晚于或同步于白名单开放决策，不能抢跑
4. 本文档未经过真实读者可读性 review（不同于 lab #2 已完成的 dry-run review）——正文措辞、代码块格式、CTA 文案均需在发布前人工二次编辑
5. 与已发布的 CrashLoopBackOff / Service 无 Endpoints 两篇文章一起排版发布时，需人工确认三篇文章之间的互相引用链接（"排查心智模型"段落分别提到了对方）不出现死链接

## 与 lab 功能性验证的关系（诚实记录）

本文档描述的每一条命令、每一段 `describe` 输出示例，均来自两轮真实 K3s rehearsal（VM 401，K3s v1.34.4）与一次 owner-as-learner smoke 的实际执行结果，不是凭经验编写的推测性内容。第一轮 rehearsal 发现并修正了两处与真实环境不符的地方（原稿假设 Events 消息是 `manifest unknown`，真实环境返回的是 `... not found`；原稿假设 `kubectl set image` 的容器名等于 Deployment 名，真实环境里 `kubectl create deployment --image=` 默认用镜像名作为容器名，导致修复命令会报 `unable to find container named ...`）——已在正文和 lab 内容中一并修正，详见 `IMAGE_PULL_BACKOFF_LAB_PRODUCTION_RESULT_v0.1.md`。本次 v1.0 定稿未修改任何技术表述，仅统一了标题风格。
