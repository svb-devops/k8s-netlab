# Official Article Draft — Service 无 Endpoints v0.1

## 元信息

```
article_status: ready_to_publish_draft   # 不是 published，也不是 cta_enabled
article_url: null
cta_enabled: false
target_directus_article_id: null   # 未创建 Directus 记录，本文档是内容草稿，不是已上线内容
```

本文档只是文字草稿，**不**通过 Directus/CTA 工具对外发布，不修改 `article_draft_id=1414ac25-054c-4b03-8bf2-535a1da27bee` 的任何字段。

---

## 标题

Kubernetes Service 建好了但访问不通？大概率是 Endpoints 为空

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

### 排查心智模型（可复用）

```
Service 连不通
  → kubectl get endpoints 是否为空？
      是 → 对比 selector（describe service）与 labels（get pods --show-labels）
      否 → 问题不在 Service 层，去查 NetworkPolicy / DNS / 应用本身
```

---

## 配套实验

本文章配套一个可动手操作的实验，实验环境会预置一个真实存在这个 bug 的 Service，你可以亲手用上面的步骤诊断和修复它，而不只是看文字。

> **当前状态**：该实验目前处于内部验证阶段，尚未对外开放注册用户访问。

---

## 发布前 blockers（未满足，不允许标记为 published）

1. `article_url` 为空 —— 尚未在 Directus 创建正式文章记录
2. `cta_enabled=false` —— CTA 未对外暴露，"配套实验"段落里的引导文字是占位性质，不能上线成死链接或误导性 CTA
3. 真实学生对该 lab 仍 403（`LABGEN_ENABLED_LAB_IDS` 未包含此 lab_id）—— 文章一旦公开发布但学生点不进实验，会造成负面体验，因此文章发布必须晚于或同步于白名单开放决策，不能抢跑
4. 本文档从未经过真实读者可读性 review（对照 lab #1 CrashLoopBackOff 走过的 `LINUX_READER_FACING_CTA_DRY_RUN` 一类 dry-run 流程），本次 sprint 范围不包含该 review 步骤
