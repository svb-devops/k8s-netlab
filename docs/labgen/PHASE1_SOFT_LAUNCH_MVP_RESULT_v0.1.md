# Phase 1 Soft Launch MVP Result — G-67

**状态**: PHASE1_SOFT_LAUNCH_MVP_COMPLETE_WITH_NOTES
**日期**: 2026-06-26
**目标**: Admin Article Upload + LLM Draft Generation + Publish Flow v0.1

---

## 执行摘要

Phase 1 Soft Launch MVP 完整落地。Admin 可上传文章 → 可操作性门禁评估 → LLM 生成实验草稿 → StaticValidator → Admin 审核 → 发布流程。全程 admin-only，无 public upload，无 reader LLM 触发。

---

## 已实现功能

### 1. Admin Article Upload（含 Phase 1 字段）

**端点**: `POST /api/labgen/article-drafts`（仅 admin）

**新增字段**:
- `copyright_confirmed: bool`（必须为 True，否则 422）
- `target_domain: Optional[str]`（k8s | linux，其他值 422）
- `intended_reader: Optional[str]`
- `publish_channel: Optional[str]`（official_site | wechat | zhihu | csdn | github | other）
- `safety_notes: Optional[str]`
- `desired_lab_title: Optional[str)`

**安全保证**:
- raw_text 仅用于 feasibility classification，不持久化
- source_metadata.raw_text_persisted 始终为 False
- copyright_confirmed 服务端校验（Pydantic 默认 False，omission 即拒绝）

### 2. Article Operability Gate

由 `StubFeasibilityClassifier` 实现，分级结果：

| 状态 | 含义 | LLM 生成 |
|------|------|---------|
| DIRECTLY_LAB_READY | 文章有完整可执行命令+验证点 | ✅ 允许 |
| PARTIALLY_LAB_READY | 文章部分可转化（含 DESTRUCTIVE_OPERATION 等） | ✅ 允许（加 NEEDS_REVIEW 注释） |
| NOT_LAB_READY | 无可操作内容/含密钥/理论文章/云平台文章 | ❌ 拒绝（422） |

**硬拒绝条件**:
- CONTAINS_SECRET_LIKE_CONTENT（API key / JWT / private key）
- DANGEROUS_OR_ILLEGAL
- 纯理论文章（无命令）
- Cloud domain（AWS/GCP/Azure，v0.1 已阻断）

### 3. LLM Draft Generation

**端点**: `POST /api/labgen/article-drafts/{draft_id}/generate-lab`（仅 admin）

**模式控制**（`LABGEN_LLM_MODE` env var）:
- `fake_only`（默认）: FakeDraftGenerationAdapter，无真实 LLM，无 API key
- `live_admin_only`: 调用 LLMProviderBoundaryService + OpenAI-compatible adapter

**不变量**:
- 生成结果 publish_status 永远不是 `published`（可能为 draft/publish_blocked/review_required）
- rehearsal_required=True 始终设置
- source_article_id=draft_id 始终设置
- 无效 LABGEN_LLM_MODE → fail-closed 回退到 fake_only
- live_admin_only 但 config 缺失 → LLMGenerationFailed（fail-closed）

**Prompt 安全**:
- article_text 经凭证脱敏（JWT/Bearer/token/key/private key 正则替换为 [REMOVED]）
- 截断到 4000 chars
- 系统消息明确禁止 chain-of-thought、secrets、publish=published
- Prompt 内容永不进入 API 响应或日志

**Audit 日志**（`data/llm_audit_log.json`）:
- 仅记录元数据（admin_user/article_draft_id/domain/mode/model/success/failure_reason）
- 永不记录：raw_text / LLM output / API key
- append() 永不抛出（safe for finally blocks）
- persist 失败时 audit 依然写入（try/finally 保证）

### 4. Admin Review Flow（回归验证）

- StaticValidator 在 generate-lab 后自动运行（作为 publish gate 前置检查）
- `POST /api/labgen/drafts/{id}/publish` 调用 PublishService.publish()
- rehearsal_required=True → 未完成 rehearsal → RehearsalNotCompleted（发布阻断）

---

## 安全约束全部满足

| 约束 | 状态 |
|------|------|
| 无 public upload | ✅ 所有文章端点 admin-only |
| 无 reader 触发 LLM | ✅ generate-lab 端点 `_require_admin` |
| LLM 不得直接 publish | ✅ 强制 DRAFT + rehearsal_required=True |
| 无 URL scraping | ✅ source_url 仅作元数据存储，不 fetch |
| 无 Docker domain | ✅ StubFeasibilityClassifier 阻断 / target_domain 白名单仅 k8s|linux |
| 无 customer pilot | ✅ 无相关代码 |
| 无 public launch | ✅ 无相关代码 |
| BLOCKER/HIGH/MEDIUM 不降级 | ✅ safety-reviewer APPROVED_WITH_NOTES，MEDIUM 已修复 |
| LLM API key 不入代码库 | ✅ config.py 从 env var 读取，gitignored |
| secrets 不进日志 | ✅ audit 无 API key 字段，logger 无 key 引用 |
| LLM 不绕过 Admin Review | ✅ 生成 → 始终 DRAFT → Admin PATCH → StaticValidator → Rehearsal → Publish |
| raw article text 不暴露给 learner | ✅ LearnerLabCatalogItem/LearnerLabDetail 无 raw_text 字段 |
| source_article_id 不暴露给 learner | ✅ learner_catalog.py 显式排除 |
| prompt 不暴露给 learner | ✅ GenerateLabFromArticleResponse 无 prompt 字段 |
| 不触碰 VMID 500-599 | ✅ 无 VM 操作 |
| env var missing → fail closed | ✅ 验证 |

---

## 测试结果

**新增**: `tests/test_labgen_phase1_soft_launch.py`（55 tests）

| 类别 | 覆盖内容 |
|------|---------|
| A. Admin Article Upload | copyright_confirmed 门禁/非admin 403/空文本/unsupported domain/invalid channel |
| B. Operability Gate | k8s/linux 通过/理论文章拒绝/密钥文章拒绝/危险命令标记 |
| C. LLM Adapter | fake_only 模式/env 缺失 fail-closed/audit 写入/reader 路径不触发 LLM |
| D. Draft Generation | schema 验证/必填字段/NOT_LAB_READY 拒绝/never published/rehearsal_required/source_article_id/desired_lab_title |
| E. Publish Flow | RehearsalNotCompleted 阻断发布 |
| F. Exposure Guards | raw_text 不持久化/source_article_id 不在 catalog/audit 不含文章原文/无 public upload route |
| G. Prompt Builder | k8s/linux 消息结构/截断/凭证脱敏/partial 注释/desired_lab_title |
| H. Regression | 现有端点正常/无 URL scraping 字段/labgen catalog 可访问/health OK/LLM mode 默认 fake_only |

**现有测试更新**:
- `test_labgen_article_draft_api.py`: POST payload 加 `copyright_confirmed=True`（10 处）
- `test_labgen_admin_rehearsal.py`: `_create_payload` 加 `copyright_confirmed=True` + 2 个内联 payload

**全量结果**: 4563 tests PASS，92.01% coverage（门禁：90%）

---

## Safety Review

- 分类：B 类（新 endpoint + 新 feature）
- safety-reviewer 结论：**APPROVED_WITH_NOTES**
- MEDIUM（已修复）: "always DRAFT" docstring 不准确 → 修正为 "never published" + 改用 try/finally 保证 audit 写入
- LOW（已修复）: persist 失败时 audit 丢失 → try/finally 解决
- LOW（已记录）: base64 过宽正则可能导致过度脱敏（安全 > 完整性，不修复）
- BLOCKER: 0 / HIGH: 0

---

## 产出物

| 文件 | 说明 |
|------|------|
| `backend/config.py` | +LABGEN_LLM_MODE |
| `backend/labgen/llm_audit.py` | 新建，append-only LLM audit log |
| `backend/labgen/article_lab_prompt_builder.py` | 新建，文章→Lab 提示词构建 |
| `backend/labgen/article_draft_routes.py` | +Phase 1 字段 + /generate-lab 端点 |
| `backend/labgen/article_draft_service.py` | +exception classes + GenerateLabResult + generate_lab_from_article() |
| `tests/test_labgen_phase1_soft_launch.py` | 新建，55 tests |
| `CHANGELOG.md` | [Unreleased] 更新 |
| `docs/labgen/PHASE1_SOFT_LAUNCH_MVP_RESULT_v0.1.md` | 本文档 |

---

## 待实现（Phase 1 后续）

- Internal Rehearsal（admin 亲自跑实验，标记 rehearsal_completed=True）
- Article CTA 绑定（article_url → generate-lab 生成的 lab_id）
- Live LLM 接入（LABGEN_LLM_MODE=live_admin_only 实际测试）
- Cohort Launch（当前策略：admin-curated soft launch only）

---

## 约束声明

- VMID 500-599 untouched
- 无 live LLM（tests 及生产均为 fake_only）
- 无 URL scraping
- 无 public upload
- 无 Docker domain
- 无 customer pilot
- 无 public launch
