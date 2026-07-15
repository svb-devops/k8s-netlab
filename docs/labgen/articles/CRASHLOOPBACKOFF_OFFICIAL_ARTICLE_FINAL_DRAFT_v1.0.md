# Official Article Final Draft — CrashLoopBackOff v1.0

## 元信息

```
article_status: ready_to_publish_draft   # 不是 published，也不是 cta_enabled
article_url: null
cta_enabled: false
target_directus_article_id: null   # 未创建/复用任何 Directus 记录，本文档是内容草稿，不是已上线内容
lab_id: bb4fe651-7687-4457-9056-885172d9017b
source_article_id (LabGen 内部草稿, 非 Directus): e6d58c93-e093-4b32-9bee-04e2758f3ef1
lab_title: Kubernetes CrashLoopBackOff 排查实验：用 describe 和 logs 定位容器启动失败原因
lab publish_status（当前生产实际值）: published
```

本文档只是文字草稿，**不**通过 Directus/CTA 工具对外发布，不修改任何生产 lab/article-draft 字段。

> **历史记录（诚实披露）**：该 lab 对应的文章曾于 2026-06-28 短暂发布过一版（`OWNER_SOFT_LAUNCH_ARTICLE1_PUBLISHED_VERIFIED_v0.1.md`，`cta_enabled=true`），随后在 2026-07-01 被人工/脚本改回 draft 状态、`published_at` 未同步清空，形成数据漂移，已于 2026-07-14 作为 HIGH-01 修复（详见项目内部记录）。当前生产状态是 `cta_enabled=false`、`article_url=null`，与另外两篇文章完全一致。本文档是基于当前真实 lab 内容重新整理的最终定稿，**不假设**旧版已发布文章的文字仍然准确，正文全部依据 `data/lab_drafts.json` 中当前生效的 7 个步骤重新核对。

---

## 标题

Pod 一直重启？从 CrashLoopBackOff 学会用 describe 和 logs 定位根因

## 正文草稿

### 症状

部署了一个 Deployment，`kubectl get pods` 显示 Pod 存在，但 `STATUS` 是 `CrashLoopBackOff`，而且 `RESTARTS` 列的数字还在不断增加。容器好像"活过"又"死了"，一直循环。

这是 Kubernetes 里最常见的故障状态之一，根因几乎总是同一件事：容器启动后立刻退出。Kubernetes 的默认行为是不断尝试重启它，每次重启之间的等待时间会指数增长（这个退避机制正是"Back-off"名字的由来），但只要根因不解决，重启多少次都不会自愈。

### 第一步：创建一个会崩溃的 Deployment（用于本实验演示）

```
kubectl create deployment crash-demo --image=<registry>/library/busybox:latest \
  -- /bin/sh -c "echo starting; /app/missing-command"
```

这条命令让容器尝试执行一个根本不存在的路径 `/app/missing-command`。容器启动后立刻因为找不到命令而退出——这正是本文要排查的典型场景的人为复现版本。

### 第二步：用 kubectl get pods 确认状态与重启次数

```
kubectl get pods
```

```
NAME                          READY   STATUS             RESTARTS   AGE
crash-demo-xxxxxxxxxx-xxxxx   0/1     CrashLoopBackOff   3          45s
```

`STATUS=CrashLoopBackOff` 且 `RESTARTS` 会随时间持续增加，是这个故障状态的判定特征——这一点和 `ImagePullBackOff`（`RESTARTS` 恒为 `0`，容器从未启动过）正好相反，是两者最快的区分方法：**先看 RESTARTS 是不是在涨，涨就是 CrashLoopBackOff，不涨就该去查 describe 的 Events**。

### 第三步：用 describe 看 Last State 和退出码

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

### 第四步：用 logs 和 logs --previous 看真实错误输出

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

### 第五步：非交互式修复——kubectl patch

```
kubectl patch deployment crash-demo --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["/bin/sh","-c","echo fixed; sleep 3600"]}]'
```

很多人第一反应是 `kubectl edit`，但那会打开一个交互式编辑器，不适合脚本化、不可审计、也不方便在 CI 里复用。`kubectl patch` 用 JSON Patch 格式非交互式地替换容器的启动命令，修复动作本身就是一条可复制、可审计、可回放的命令。

### 第六步：用 rollout status 确认真正修复

```
kubectl rollout status deployment/crash-demo --timeout=90s
kubectl get pods
```

`patch` 命令返回成功不等于 Pod 已经真的稳定运行——滚动更新需要时间，新 Pod 也可能因为别的原因再次失败。`rollout status` 会阻塞直到 Deployment 完全就绪才返回，看到 `successfully rolled out` 加上 `kubectl get pods` 里 `READY=1/1`、`STATUS=Running`，才是修复真正生效的确认。

### 排查心智模型（与 ImagePullBackOff 互补）

```
Pod 不 Ready
  → RESTARTS 是否在增加？
      是 → CrashLoopBackOff，查 kubectl describe 的 Last State/Exit Code，再查 kubectl logs --previous
      否（恒为 0） → ImagePullBackOff/ErrImagePull，查 kubectl describe 的 Events，不要查日志（容器从未运行过，没有日志）
```

---

## 配套实验

本文章配套一个可动手操作的实验，实验环境会预置一个真实会持续崩溃的 Deployment，你可以亲手用上面的步骤诊断和修复它，而不只是看文字。

> **当前状态**：该实验目前处于内部验证阶段，尚未对外开放注册用户访问。

---

## 发布前 blockers（未满足，不允许标记为 published）

1. `article_url` 为空 —— 尚未在 Directus 创建正式文章记录（该 lab 此前有过一次已发布又被回退的历史，本次为重新起草，不复用旧的 Directus 文章记录）
2. `cta_enabled=false` —— CTA 未对外暴露，"配套实验"段落里的引导文字是占位性质，不能上线成死链接或误导性 CTA
3. 真实学生对该 lab 仍 403（`LABGEN_ENABLED_LAB_IDS` 未包含此 lab_id）—— 文章一旦公开发布但学生点不进实验，会造成负面体验，因此文章发布必须晚于或同步于白名单开放决策，不能抢跑
4. 本文档未经过真实读者可读性 review（不同于 lab #2 已完成的 dry-run review）——正文措辞、代码块格式、CTA 文案均需在发布前人工二次编辑
5. 与已发布的 Service 无 Endpoints / ImagePullBackOff 两篇文章一起排版发布时，需人工确认三篇文章之间的互相引用链接（"排查心智模型"段落分别提到了对方）不出现死链接
6. **历史遗留提醒**：该 lab 曾在 2026-06-28 短暂 `cta_enabled=true` 发布过一版旧文章，后于 2026-07-01 回退为 draft（HIGH-01），2026-07-14 已修复数据漂移。若未来重新发布，需人工确认旧的 Directus 文章记录（slug `crashloopbackoff-describe-logs`，若仍存在）与本次新草稿的关系（复用改写还是弃用新建），不能默认沿用旧记录的 `published_at`/`cta` 字段

## 与 lab 功能性验证的关系（诚实记录）

本文档描述的每一条命令、每一段 `describe`/`logs` 输出示例，均来自 `data/lab_drafts.json` 中当前生效的 7 个步骤（`rehearsal_completed: true`，全部 19 项 `validator_results` 为 `passed`，含 `explain.verified_if_published` 检查），退出码 127、`Back-off restarting failed container` 等具体细节直接取自该 lab 各步骤的 `observe`/`explain.observation` 字段，不是凭经验编写的推测性内容。本文档未新增或修改任何 lab 内容，仅将既有的、已验证的 lab 步骤数据转写为面向读者的文章体裁。
