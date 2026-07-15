# Official Article Final Draft — Service 无 Endpoints v1.0

## 元信息

```
article_status: ready_to_publish_draft   # 不是 published，也不是 cta_enabled
article_url: null
cta_enabled: false
target_directus_article_id: null   # 未创建 Directus 记录，本文档是内容草稿，不是已上线内容
lab_id: 2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86
source_article_id (LabGen 内部草稿, 非 Directus): 1414ac25-054c-4b03-8bf2-535a1da27bee
lab_title: Kubernetes Service 无 Endpoints 排查实验：selector 与 labels 不匹配
lab publish_status（当前生产实际值）: published
```

本文档只是文字草稿，**不**通过 Directus/CTA 工具对外发布，不修改 `article_draft_id=1414ac25-054c-4b03-8bf2-535a1da27bee` 的任何字段。

> 本文档是 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 的最终定稿版本（v1.0），改动仅限：① 标题改为与另外两篇文章统一的"疑问句+排查线索"风格；② 补充与 CrashLoopBackOff / ImagePullBackOff 两篇文章统一的元信息区块格式；③ blockers 章节按 2026-07-15 三篇文章统一收口的最新状态重新核对。正文技术内容（症状、命令、排查步骤、心智模型）与 v0.1 一致，未做实质性改写——v0.1 已完成过一轮内容可读性 dry-run review，此处不重复变更已验证过的技术表述。

---

## 标题

Service 建好了但访问不通？先检查 Endpoints 和 selector

## 正文草稿

### 症状

部署了一个 Deployment，Pod 状态是 `Running`；建了一个 ClusterIP Service 指向它；但从集群内其他 Pod 用 Service 名访问，连接超时或直接拒绝。日志里什么错误都没有，因为压根没有请求到达 Pod。

### 第一步：确认症状——查 Endpoints，不是查 Pod 日志

```
kubectl get endpoints web-svc
```

如果 `ENDPOINTS` 列是空的（`<none>`），说明 Kubernetes 从未找到任何 Pod 满足这个 Service 的 selector。这一步比查 Pod 日志更快定位问题——Pod 日志此时是"健康但沉默"的，不会给你任何线索。

> 提醒：`kubectl describe service` 里的 Endpoints 字段在部分 K3s 版本下可能不可靠（本次实验环境 K3s v1.34.4 上观察到该字段持续显示 `<none>` 而 `kubectl get endpoints` 显示正确值），排查时以 `kubectl get endpoints` 为准。

### 第二步：读出 Service 认为的 selector

```
kubectl describe service web-svc
```

关注 `Selector` 那一行，例如 `app=web-svc`。

### 第三步：读出 Pod 实际的标签

```
kubectl get pods --show-labels
```

对比一下：如果 Pod 的标签是 `app=web-backend`，而 Service 的 selector 是 `app=web-svc`，两者对不上——这就是根因。`kubectl create service clusterip` 在不显式指定 `--selector` 时的默认值，不会自动跟 `kubectl create deployment` 生成的标签对齐，这是本故障最常见的触发路径。

### 第四步：修复

不建议手动 `kubectl patch service` 改 selector（容易再打错一次字，而且在真实生产集群里，Service 类型相关的写权限通常受限）。更稳妥的做法是删掉重建，让 `kubectl expose` 直接从 Deployment 的真实标签生成 selector：

```
kubectl delete service web-svc
kubectl expose deployment web-backend --port=80 --name=web-svc
```

### 第五步：验证修复

```
kubectl get endpoints web-svc
```

`ENDPOINTS` 列此时应该出现 Pod 的 IP:端口，说明 Service 已经能正确路由流量。

### 排查心智模型（与 CrashLoopBackOff / ImagePullBackOff 互补）

```
Service 连不通
  → kubectl get endpoints 是否为空？
      是 → 对比 selector（describe service）与 labels（get pods --show-labels）
      否 → 问题不在 Service 层，去查 NetworkPolicy / DNS / 应用本身
```

（如果连不通的是 Pod 本身起不来，看的是另外两篇文章：`RESTARTS` 持续增加查 CrashLoopBackOff，`RESTARTS` 恒为 0 查 ImagePullBackOff。）

---

## 配套实验

本文章配套一个可动手操作的实验，实验环境会预置一个真实存在这个 bug 的 Service，你可以亲手用上面的步骤诊断和修复它，而不只是看文字。

> **当前状态**：该实验目前处于内部验证阶段，尚未对外开放注册用户访问。

---

## 发布前 blockers（未满足，不允许标记为 published）

1. `article_url` 为空 —— 尚未在 Directus 创建正式文章记录
2. `cta_enabled=false` —— CTA 未对外暴露，"配套实验"段落里的引导文字是占位性质，不能上线成死链接或误导性 CTA
3. 真实学生对该 lab 仍 403（`LABGEN_ENABLED_LAB_IDS` 未包含此 lab_id）—— 文章一旦公开发布但学生点不进实验，会造成负面体验，因此文章发布必须晚于或同步于白名单开放决策，不能抢跑
4. ~~本文档从未经过真实读者可读性 review~~ —— 已于 Service Official Article Publish Gate 准备 sprint 完成内容可读性 dry-run review（非完整 learner session E2E，lab 功能性已在此前 sprint 验证），结论：内容与真实 lab 一致、无夸大表述、无死链接，遗留 MEDIUM/LOW 项（CTA 默认文案措辞需人工改写、配套实验段落需人工二次编辑），详见 `SERVICE_ARTICLE_PUBLISH_GATE_PREP_v0.1.md` 第 4 节。**该 review 通过不构成可以发布的理由**——blocker #1/#2/#3 仍未满足
5. **v0.1 时的 HIGH-001 已修复（2026-07-15 复核）**：`SERVICE_ARTICLE_PUBLISH_GATE_PREP_v0.1.md` 第 6 节记录的"`LearnerCatalogService` 目录可见性未纳入 `LABGEN_ENABLED_LAB_IDS` 判断"问题，经代码复核（`backend/labgen/learner_catalog.py::_compute_is_startable` 已包含 `_is_access_denied`/`_is_not_invited` 校验），当前 `is_startable` 计算已正确纳入白名单/邀请状态，学生浏览目录不会再看到误导性的"可开始"标记。此项不再是 blocker，仅作历史记录保留
6. 与另外两篇文章一起排版发布时，需人工确认三篇文章互相引用链接（"排查心智模型"段落分别提到了对方）不出现死链接

## 与 lab 功能性验证的关系（诚实记录）

本文档描述的每一条命令、每一段输出示例均与 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 一致，该版本内容已在此前 sprint 中完成过 dry-run review 与 lab 功能性验证（详见 `SERVICE_NO_ENDPOINTS_LAB_PRODUCTION_RESULT_v0.1.md`）。本次 v1.0 定稿未修改任何技术表述，仅统一了标题风格与元信息格式。
