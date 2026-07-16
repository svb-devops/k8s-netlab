# Internal Publish Checklist — Service 无 Endpoints v1.0

**用途**：本文档是 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md` 的配套内部笔记，承载所有不该出现在对外文章正文里的部署元数据、发布 blockers 和验证依据。对外文章正文经过 2026-07-15 First Wave Article Publish Polish 清理后已不再包含这些内容，本文档是它们的唯一保留位置（与 `CRASHLOOPBACKOFF_INTERNAL_PUBLISH_CHECKLIST_v1.0.md` 同一模式）。

---

## 元数据

```
article_status: ready_to_publish_draft   # 不是 published，也不是 cta_enabled
article_url: null
cta_enabled: false
target_directus_article_id: null   # 未创建 Directus 记录，本文档是内容草稿，不是已上线内容
lab_id: 2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86
source_article_id (LabGen 内部草稿, 非 Directus): 1414ac25-054c-4b03-8bf2-535a1da27bee
lab_title: Kubernetes Service 无 Endpoints 排查实验：selector 与 labels 不匹配
lab publish_status（2026-07-15 核对）: published
```

本文档只是内部笔记，**不**通过 Directus/CTA 工具对外发布，不修改 `article_draft_id=1414ac25-054c-4b03-8bf2-535a1da27bee` 的任何字段。

---

## 发布前 blockers（未满足，不允许标记为 published）

1. `article_url` 为空 —— 尚未在 Directus 创建正式文章记录
2. `cta_enabled=false` —— CTA 未对外暴露，对外文章"配套实验"段落里的引导文字是占位性质，不能上线成死链接或误导性 CTA
3. 真实学生对该 lab 仍 403（`LABGEN_ENABLED_LAB_IDS` 未包含此 lab_id）—— 文章一旦公开发布但学生点不进实验，会造成负面体验，因此文章发布必须晚于或同步于白名单开放决策，不能抢跑
4. 对外文章正文经过内容可读性 dry-run review（详见 `SERVICE_ARTICLE_PUBLISH_GATE_PREP_v0.1.md` 第 4 节：内容与真实 lab 一致、无夸大表述、无死链接，遗留 CTA 默认文案措辞需人工改写等 MEDIUM/LOW 项）——**该 review 通过不构成可以发布的理由**，blocker #1/#2/#3 仍未满足
5. 与另外两篇文章一起排版发布时，需人工确认三篇文章互相引用链接（正文"排查心智模型"段落分别提到了对方）不出现死链接

## HIGH-001 历史修复记录

v0.1 阶段发现的 HIGH-001（`SERVICE_ARTICLE_PUBLISH_GATE_PREP_v0.1.md` 第 6 节记录的"`LearnerCatalogService` 目录可见性未纳入 `LABGEN_ENABLED_LAB_IDS` 判断"问题）经代码复核（`backend/labgen/learner_catalog.py::_compute_is_startable` 已包含 `_is_access_denied`/`_is_not_invited` 校验）确认已修复，学生浏览目录不会再看到误导性的"可开始"标记。此项不再是 blocker，仅作历史记录保留。

## CTA / 白名单 / student 403 状态（2026-07-15 核对）

| 项 | 值 |
|----|-----|
| `cta_enabled` | `false` |
| `article_url` | `null` |
| `LABGEN_ENABLED_LAB_IDS` 是否包含本 lab | 否（当前为空） |
| 真实学生访问该 lab | 403 |

## 与 lab 功能性验证的关系（诚实记录）

对外文章描述的每一条命令、每一段输出示例均与 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 一致，该版本内容已完成过 dry-run review 与 lab 功能性验证（详见 `SERVICE_NO_ENDPOINTS_LAB_PRODUCTION_RESULT_v0.1.md`）。本轮 Publish Polish 未修改任何技术表述的准确性，只调整了行文结构（正文改为"是什么/为什么/怎么查/怎么修"的文章体裁标题，而非"第一步/第二步"的实验手册体裁标题）、开头场景化改写、心智模型改为决策树格式，以及新增 dual CTA 版本。

---

## Article-Lab Alignment（本次 Publish Polish 复核）

| 对外文章段落 | 对应 lab step | 一致性 |
|--------------|---------------|--------|
| 症状 + 为什么不是 Pod 的问题 | lab 症状设定 | 一致 |
| 先查 Endpoints | step-1（`kubectl get endpoints`） | 一致 |
| 对比 selector 和 labels | step-2/step-3（`describe service` / `get pods --show-labels`） | 一致 |
| 修复：重建 Service | step-4（`delete` + `expose`） | 一致 |
| 验证修复 | step-5（`get endpoints`） | 一致 |

**结论**：PASS，本轮行文结构改写未引入与 lab 的不一致。

## Publish Polish 检查结果（2026-07-15）

| 检查项 | 结果 |
|--------|------|
| title_style | PASS — "Service 建好了但访问不通？先检查 Endpoints 和 selector"，与另外两篇一致的"疑问句+排查线索"结构 |
| pain_point_opening | PASS — 本轮改写为更具体的场景描述（"一切看起来都该通了，但连不通"），并新增"为什么这不是 Pod 的问题"一节强化工程判断 |
| code_block_readability | PASS — 所有命令行均在合理长度内，无需简化 |
| cta_dual_version | PASS — 新增 internal_preview_version / public_publish_version 两个版本 |
| no_internal_metadata | PASS — 元信息块、blockers、HIGH-001 记录、source_article_id 等已全部移至本文档 |
| lab_alignment | PASS（见上表） |
| publish_ready_for_owner_review | PASS |
