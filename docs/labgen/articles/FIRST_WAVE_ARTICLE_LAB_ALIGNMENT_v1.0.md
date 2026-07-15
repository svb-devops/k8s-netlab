# First Wave Article-Lab Alignment Check v1.0

**检查时间**：2026-07-15
**检查依据**：`data/lab_drafts.json` 中三个 lab 的当前生产实际字段（非文档记忆，本次逐一重新读取校验）
**检查范围**：三篇 `*_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md` 与其对应 lab 的一致性

---

## 1. CrashLoopBackOff

| 检查项 | 结果 |
|--------|------|
| article title | Pod 一直重启？从 CrashLoopBackOff 学会用 describe 和 logs 定位根因 |
| lab_id | `bb4fe651-7687-4457-9056-885172d9017b` |
| lab title | Kubernetes CrashLoopBackOff 排查实验：用 describe 和 logs 定位容器启动失败原因 |
| lab status | `published` |
| article status | `ready_to_publish_draft`（未创建 Directus 记录） |
| CTA target | 占位，无实际跳转目标；`cta_enabled=false` |
| 文章现象是否和 lab 一致 | 一致。文章"症状"段描述的 `STATUS=CrashLoopBackOff` + `RESTARTS` 持续增加，与 lab step-2 的 `observe` 字段（"STATUS 列显示 CrashLoopBackOff，RESTARTS 列显示大于 0 的次数，且数字会随时间持续增加"）完全对应 |
| 文章命令是否和 lab 一致 | **基本一致，有 1 处刻意改写**：文章第一步用 `<registry>/library/busybox:latest` 占位符替代了 lab step-1 中实际的内网 registry 地址 `172.16.100.1:5000/library/busybox:latest`——这是有意为之（公开文章不暴露内网基础设施细节），核心命令结构、`kubectl patch` 的 JSON Patch 内容、`kubectl describe`/`kubectl logs --previous`/`kubectl rollout status` 均与 lab step-2~6 逐字一致 |
| 修复路径是否和 lab 一致 | 一致。`kubectl patch deployment --type=json` 替换 `command` 字段为 `sleep 3600`，与 lab step-5 完全一致；验证用 `kubectl rollout status` + `kubectl get pods`，与 lab step-6 完全一致 |
| 是否有实验措辞夸大风险 | 无。文章明确写"该实验目前处于内部验证阶段，尚未对外开放注册用户访问" |
| 是否有夸大能力风险 | 无。文章未对 LabGen/AI 生成能力做任何宣传性表述，纯粹是排查方法论内容 |
| 是否暗示普通用户可自由启动实验 | 无。CTA 段落明确标注为占位，未提供任何可点击的开始入口 |
| **特别提示** | 该 lab 对应文章曾于 2026-06-28 短暂发布（`cta_enabled=true`）后于 2026-07-01 被回退（HIGH-01，已修复），本文档在元信息区块中已如实披露该历史，不隐瞒 |

**结论**：PASS，无 blocking 项。

---

## 2. Service 无 Endpoints

| 检查项 | 结果 |
|--------|------|
| article title | Service 建好了但访问不通？先检查 Endpoints 和 selector |
| lab_id | `2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86` |
| lab title | Kubernetes Service 无 Endpoints 排查实验：selector 与 labels 不匹配 |
| lab status | `published` |
| article status | `ready_to_publish_draft`（未创建 Directus 记录） |
| CTA target | 占位，无实际跳转目标；`cta_enabled=false` |
| 文章现象是否和 lab 一致 | 一致。v0.1 已完成过一轮内容可读性 dry-run review，本次 v1.0 未改动技术表述，仅重新核对未发现新的不一致 |
| 文章命令是否和 lab 一致 | 一致，与 v0.1 相同（`kubectl get endpoints` / `kubectl describe service` / `kubectl get pods --show-labels` / `kubectl delete service` + `kubectl expose`） |
| 修复路径是否和 lab 一致 | 一致 |
| 是否有实验措辞夸大风险 | 无 |
| 是否有夸大能力风险 | 无 |
| 是否暗示普通用户可自由启动实验 | 无 |
| **特别提示** | v0.1 阶段发现的 HIGH-001（`LearnerCatalogService` 目录 `is_startable` 计算未纳入 `LABGEN_ENABLED_LAB_IDS`）经本次代码复核（`backend/labgen/learner_catalog.py:184-190` `_is_access_denied` 已正确引用 `self._enabled_lab_ids`）确认已修复，不再是发布 blocker |

**结论**：PASS，无 blocking 项。

---

## 3. ImagePullBackOff

| 检查项 | 结果 |
|--------|------|
| article title | Pod 卡在 ImagePullBackOff？从 Events 看镜像拉取失败原因 |
| lab_id | `eb78afaa-f7fb-422e-8eb9-98644f59527f` |
| lab title | Kubernetes ImagePullBackOff 排查实验：用 describe 的 Events 定位镜像拉取失败原因 |
| lab status | `published` |
| article status | `ready_to_publish_draft`（未创建 Directus 记录） |
| CTA target | 占位，无实际跳转目标；`cta_enabled=false` |
| 文章现象是否和 lab 一致 | 一致。文章内容与 v0.1 相同，v0.1 已经过两轮真实 K3s rehearsal 校验 |
| 文章命令是否和 lab 一致 | 一致 |
| 修复路径是否和 lab 一致 | 一致，含"容器名默认取镜像名而非 Deployment 名"这一已被真实 rehearsal 验证过的细节 |
| 是否有实验措辞夸大风险 | 无 |
| 是否有夸大能力风险 | 无 |
| 是否暗示普通用户可自由启动实验 | 无 |

**结论**：PASS，无 blocking 项。

---

## 4. 跨文章一致性检查

| 检查项 | 结果 |
|--------|------|
| 三篇标题风格是否统一 | 一致，均为"[症状疑问句]？[排查线索动作]"结构 |
| 三篇"排查心智模型"互相引用是否形成闭环、无死链接 | 结构上一致（CrashLoopBackOff ↔ ImagePullBackOff 互相提及对方判定依据；Service 无 Endpoints 提及"如果连不通的是 Pod 本身起不来，看另外两篇"）。**当前均为文字提及，非可点击超链接**——三篇文章均未创建 Directus 记录，此时不存在可用的 `article_url` 可供互链，待真正发布时需人工补充实际链接（三篇 final draft 文档均已在各自"发布前 blockers"中标注此项） |
| 三篇 `cta_enabled`/`article_url` 是否一致 | 一致，均为 `false` / `null` |
| 三篇 lab 是否均为 `published` | 是，三个 lab 均为 `published` |
| 是否有任何一篇隐含"现在就能免费试用"的误导性表述 | 无，三篇文章"配套实验"段落文案完全一致（"该实验目前处于内部验证阶段，尚未对外开放注册用户访问"） |

**结论**：三篇文章整体 PASS，无 blocking 项。真正发布时需人工补充三篇之间的互链 URL（当前为占位阶段，不构成本次交付的 blocker）。
