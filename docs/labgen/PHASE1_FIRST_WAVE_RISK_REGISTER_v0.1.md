# Phase 1 First Wave — Risk Register v0.1

## 状态

`documentation_only`。只记录当前真实存在的风险，不扩展新任务、不预先设计修复方案（除非风险本身要求立即止损，本次没有这类情况）。

---

## HIGH

### HIGH-01：CrashLoopBackOff 文章 Directus 状态与 LabDraft CTA 字段不同步

- **现状**：`OWNER_SOFT_LAUNCH_ARTICLE1_PUBLISHED_VERIFIED_v0.1.md`（2026-06-28）记录该文章已 `PUBLISHED_VERIFIED`、`cta_enabled=true`。本次 RC 检查（2026-07-13）发现 Directus 实际记录（article id=4，slug=`crashloopbackoff-describe-logs`）当前 `status=draft`，公开 API（`GET /api/articles`、`GET /api/articles/{slug}`）均确认匿名访客当前无法读取该文章。但 LabDraft 层（`bb4fe651-...`）的 `cta_enabled=true`、`article_url` 仍然指向这个现在实际不可访问的文章
- **影响**：如果任何流程（人工或未来自动化）依赖 `cta_enabled=true` 作为"这篇文章可以安全对外引用"的信号，会产生误导——CTA 技术上是开的，但目标内容实际拿不到。当前没有真实公开流量访问这个链接（lab 本身仍被 `LABGEN_ENABLED_LAB_IDS` 挡住，article.html 页面也没有被任何入口链接进去），所以**当前没有真实用户会撞见这个问题**，但状态本身是错误的，且随时可能因为"看到 cta_enabled=true 就以为可以安全推广"而被误用
- **根因**：未知，超出本次只读 RC 快照的调查范围——不清楚是谁、在什么操作下把 Directus 文章从 published 改回 draft，也不清楚 LabDraft 的 `cta_enabled`/`article_url` 字段为何没有同步降级
- **不在本次处理**：本次任务边界明确禁止"发布公开文章"和修改 draft/published 状态，因此不主动把 Directus 文章改回 published，也不主动把 LabDraft 的 CTA 字段降级对齐——两个方向都是"改变当前状态"，都超出 RC 快照的只读边界
- **建议下一步**：owner 决定两个方向之一——(a) 重新审查这篇文章内容后正式发布（对齐 Directus status=published），或 (b) 把 LabDraft 的 `cta_enabled` 降回 `false`、`article_url` 清空，与另外两个 lab 保持一致的"完全内部"状态，直到三篇一起做统一发布决策

## MEDIUM

### MEDIUM-01：三篇文章标题风格不统一

- CrashLoopBackOff 用"溯查体"（更像正式对外稿），Service/ImagePullBackOff 用"排查实验体"（更像内部工作稿）
- 不阻塞 RC 冻结，但正式对外发布前建议统一，避免系列感割裂
- 详见 `PHASE1_FIRST_WAVE_RELEASE_CANDIDATE_v0.1.md` 一致性检查表

### MEDIUM-02：CTA 默认文案未按白名单状态调整

- 三个 lab 的 CTA 文案（`markdown_cta`/`html_cta`）都写"本文配套实操实验已上线"，但真实学生点进去会被 403（因为不在 `LABGEN_ENABLED_LAB_IDS`）
- 当前不构成问题，因为 CTA 本身对 CrashLoopBackOff 以外的两个 lab 都是 `cta_enabled=false`（未对外暴露），CrashLoopBackOff 虽然 `cta_enabled=true` 但目标文章拿不到（见 HIGH-01），两个问题互相抵消导致当前无真实曝光
- 一旦 owner 决定开放任何一篇文章的 CTA，必须先解决这条——沿用 lab #2/#3 sprint 里已经识别过的同一个既有 gap（详见 `SERVICE_NO_ENDPOINTS_LAB_PRODUCTION_RESULT_v0.1.md`）

## LOW

### LOW-01：26 个 xfailed demo_seed 技术债

- `generation_templates.py` 三个 demo 模板（`PYTHON_BASICS`/`HTTP_API_BASICS`/`DATA_TRANSFORM_BASICS`）使用未实现的 verify 类型 + 引用不存在的 manifest 文件
- 与 first wave 三个 lab 完全无关（demo_seed 是独立的测试夹具数据），已用 `xfail(strict=True)` 标记，不静默隐藏，不影响测试门禁
- backlog，不阻塞 Phase 1

### LOW-02：health 端点 sessions 段 degraded（19 个 zombie draft）

- `DataRetentionService.run(dry_run=True)` 已确认这 19 个 draft 均可安全归档（三个 first wave lab 因 `publish_status=published`/`rehearsal_completed=true` 被保护，不会被误清理）
- 本次严格遵循任务边界，只记录不执行
- 建议下次有"数据维护"类任务窗口时统一处理，不需要专门开一个 sprint

---

## BLOCKER

无。

---

## 与本次 First Wave RC Freeze 范围的关系

上述四项风险中，只有 HIGH-01 是本次 RC 检查中新发现的（此前的 sprint 汇报均未提及 Directus 状态漂移）；MEDIUM-01/02、LOW-01/02 均是此前 sprint 已经识别、写入过各自文档的既有事项，本次只是在 RC 快照里统一汇总，不是本次新引入。**没有任何一项构成阻塞 First Wave RC 冻结的理由**——三个 lab 本身的功能正确性、访问收紧策略、生产健康度均未受影响。
