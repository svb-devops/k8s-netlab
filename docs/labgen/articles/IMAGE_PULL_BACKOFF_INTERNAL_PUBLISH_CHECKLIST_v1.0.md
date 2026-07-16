# Internal Publish Checklist — ImagePullBackOff / ErrImagePull v1.0

**用途**：本文档是 `IMAGE_PULL_BACKOFF_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md` 的配套内部笔记，承载所有不该出现在对外文章正文里的部署元数据、发布 blockers 和验证依据。对外文章正文经过 2026-07-15 First Wave Article Publish Polish 清理后已不再包含这些内容，本文档是它们的唯一保留位置（与另外两篇文章的 `*_INTERNAL_PUBLISH_CHECKLIST_v1.0.md` 同一模式）。

---

## 元数据

```
article_status: ready_to_publish_draft   # 不是 published，也不是 cta_enabled
article_url: null
cta_enabled: false
target_directus_article_id: null   # 未创建 Directus 记录，本文档是内容草稿，不是已上线内容
lab_id: eb78afaa-f7fb-422e-8eb9-98644f59527f
source_article_id (LabGen 内部草稿, 非 Directus): da282651-f66f-405b-abc1-b3dc563feb6a
lab_title: Kubernetes ImagePullBackOff 排查实验：用 describe 的 Events 定位镜像拉取失败原因
lab publish_status（2026-07-15 核对）: published
```

本文档只是内部笔记，**不**通过 Directus/CTA 工具对外发布，不修改任何生产 lab/article-draft 字段。

---

## 发布前 blockers（未满足，不允许标记为 published）

1. `article_url` 为空 —— 尚未在 Directus 创建正式文章记录
2. `cta_enabled=false` —— CTA 未对外暴露，对外文章"配套实验"段落里的引导文字是占位性质，不能上线成死链接或误导性 CTA
3. 真实学生对该 lab 仍 403（`LABGEN_ENABLED_LAB_IDS` 未包含此 lab_id）—— 文章一旦公开发布但学生点不进实验，会造成负面体验，因此文章发布必须晚于或同步于白名单开放决策，不能抢跑
4. 对外文章正文未经过真实读者可读性 review（不同于 lab #2 已完成的 dry-run review）——正文措辞、代码块格式、CTA 文案均需在发布前人工二次编辑
5. 与另外两篇文章一起排版发布时，需人工确认三篇文章互相引用链接（正文"排查心智模型"段落分别提到了对方）不出现死链接

## CTA / 白名单 / student 403 状态（2026-07-15 核对）

| 项 | 值 |
|----|-----|
| `cta_enabled` | `false` |
| `article_url` | `null` |
| `LABGEN_ENABLED_LAB_IDS` 是否包含本 lab | 否（当前为空） |
| 真实学生访问该 lab | 403 |

## 与 lab 功能性验证的关系（诚实记录）

对外文章描述的每一条命令、每一段 `describe` 输出示例，均来自两轮真实 K3s rehearsal（VM 401，K3s v1.34.4）与一次 owner-as-learner smoke 的实际执行结果，不是凭经验编写的推测性内容。第一轮 rehearsal 发现并修正了两处与真实环境不符的地方：

1. 原稿假设 Events 消息是 `manifest unknown`，真实环境返回的是 `... not found`
2. 原稿假设 `kubectl set image` 的容器名等于 Deployment 名，真实环境里 `kubectl create deployment --image=` 默认用镜像名作为容器名，导致修复命令会报 `unable to find container named ...`

已在正文和 lab 内容中一并修正，详见 `IMAGE_PULL_BACKOFF_LAB_PRODUCTION_RESULT_v0.1.md`。本轮 Publish Polish 未修改任何技术表述的准确性，只调整了行文结构（正文改为"是什么/为什么/怎么查/怎么修"的文章体裁标题，而非"第一步/第二步"的实验手册体裁标题）、开头场景化改写（同步应用 CrashLoopBackOff 一致的"apply 成功不代表容器稳定"表述）、心智模型改为决策树格式、Events 长输出行改为摘要展示（完整真实输出见本节上方"与真实环境不符的地方"记录及 lab 内容本身），以及新增 dual CTA 版本。

---

## Article-Lab Alignment（本次 Publish Polish 复核）

| 对外文章段落 | 对应 lab step | 一致性 |
|--------------|---------------|--------|
| 症状 + 判定依据 | step-1（创建）+ step-2（观察 READY/RESTARTS） | 一致 |
| 为什么查日志是死路 | 对应真实行为（容器未启动，无日志） | 一致 |
| describe 的 Events | step-3（describe，Events） | 一致；正文 Events 输出已摘要展示，未改变其含义 |
| 核对镜像引用和容器名 | step-4 | 一致，含"容器名默认取镜像名"的已验证细节 |
| 修复：kubectl set image | step-5 | 一致 |
| 验证修复 | step-6 | 一致 |

**结论**：PASS，本轮行文结构改写与 Events 输出摘要化未引入与 lab 的不一致。

## Publish Polish 检查结果（2026-07-15）

| 检查项 | 结果 |
|--------|------|
| title_style | PASS — "Pod 卡在 ImagePullBackOff？从 Events 看镜像拉取失败原因"，与另外两篇一致的"疑问句+排查线索"结构 |
| pain_point_opening | PASS — "kubectl apply 返回成功"表述同步修正为"只说明对象被接收，不代表容器稳定运行"，与 CrashLoopBackOff 保持一致 |
| code_block_readability | PASS — 原本很长的单行 Events 输出（`Warning Failed kubelet Failed to pull image ...: rpc error: code = NotFound desc = ...`）改为摘要展示，避免横向滚动，完整真实输出记录保留在本文档"与 lab 功能性验证的关系"一节 |
| cta_dual_version | PASS — 新增 internal_preview_version / public_publish_version 两个版本 |
| no_internal_metadata | PASS — 元信息块、blockers、rehearsal 历史、source_article_id 等已全部移至本文档 |
| lab_alignment | PASS（见上表） |
| publish_ready_for_owner_review | PASS |
