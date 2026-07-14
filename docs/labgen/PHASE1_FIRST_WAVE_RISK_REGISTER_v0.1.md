# Phase 1 First Wave — Risk Register v0.1

## 状态

`documentation_only`（首次冻结时）；2026-07-14 追加一次 HIGH-01 保守对齐修复（见下方 RESOLVED，纯数据修复，不涉及代码/发布策略变更）。

---

## RESOLVED

### HIGH-01（已修复 2026-07-14）：CrashLoopBackOff 文章 Directus 状态与 LabDraft CTA 字段不同步

- **原状态**：`OWNER_SOFT_LAUNCH_ARTICLE1_PUBLISHED_VERIFIED_v0.1.md`（2026-06-28）记录该文章已 `PUBLISHED_VERIFIED`、`cta_enabled=true`。2026-07-13 RC 检查发现 Directus 实际记录（article id=4，slug=`crashloopbackoff-describe-logs`）当前 `status=draft`，公开 API（`GET /api/articles`、`GET /api/articles/{slug}`）均确认匿名访客无法读取该文章。但 LabDraft 层（`bb4fe651-...`）的 `cta_enabled=true`、`article_url` 仍然指向这个不可访问的文章
- **根因确认（2026-07-14）**：查询 Directus `activity`/`revisions`：2026-07-01T20:25:36Z，同一 admin 账号对 article id=4 执行了一次显式 `update`，delta 为 `{"status": "draft"}`（`published_at` 保留 06-28 原值未清）。确认为一次明确的字段更新，而非数据损坏或自动化误删；具体操作者的意图/入口未追查（超出范围）。LabDraft 的 CTA 字段此后未同步降级，导致状态漂移持续到 07-13 才被发现
- **修复**：采用保守对齐方向 (b)——通过 `PATCH /api/labgen/drafts/bb4fe651-7687-4457-9056-885172d9017b` 将 `cta_enabled` 降回 `false`，`article_url`/`article_title`/`article_channel`/`article_published_at` 全部清空，与 Service No Endpoints / ImagePullBackOff 两个 lab 完全一致。未触碰 Directus 文章状态（是否/何时重新发布仍是方向 (a)，留给 owner 单独决策），未修改 `LABGEN_ENABLED_LAB_IDS`，未新增用户，未开放公开访问
- **验证**：targeted tests（`cta`/`lab_draft`/`article_bind` 相关，124 passed）、生产 health 全绿、`git status` clean（`data/*.json` 不入库，此次为纯数据修复，无代码改动）
- **遗留（不阻塞，转普通决策事项）**：三篇 first wave 文章正式发布顺序/时机，仍需 owner 决策

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
