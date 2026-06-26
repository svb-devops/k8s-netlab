# Live LLM Admin-only Internal Trial & Rehearsal Gate — G-68 Result

**状态**: LIVE_LLM_ADMIN_TRIAL_READY_WITH_NOTES
**日期**: 2026-06-26
**目标**: 接入真实 LLM provider（admin-only），完成内部试运行，验证完整 Pipeline

---

## 执行摘要

Live LLM Admin-only Internal Trial 全流程完成。使用内部样本 K8s 文章，在 admin-only 约束下触发真实 LLM 生成实验草稿，经过 Operability Gate → LLM Generation（gpt-4o-mini，OpenAI-compatible）→ StaticValidator → 结构性 Rehearsal Assessment 全部通过。

决策为 **LIVE_LLM_ADMIN_TRIAL_READY_WITH_NOTES** 而非 READY_FOR_PUBLISH_GATE，原因：本次试运行使用明确标注的内部样本文章，而非真实 owner 创作文章。全部安全约束保持有效，无降级。

---

## 已实现功能

### 1. call_live_with_messages() 公开方法

**文件**: `backend/labgen/llm_provider_boundary.py`

将原来私有的 `_live_adapter.call_generate()` 直接访问封装为公开接口，明确职责边界：

```python
def call_live_with_messages(self, system_msg: str, user_msg: str) -> dict:
    """
    Call the live adapter with custom article-to-lab messages.
    Raises LLMProviderConfigError when live adapter not configured.
    """
```

- `live_enabled` 为 False → 抛出 `LLMProviderConfigError`（fail-closed）
- 永不返回：API key / raw HTTP body / chain-of-thought / hidden_prompt
- 新增 `LLMProviderConfigError` 异常类（config 缺失的专用错误）

### 2. article_draft_service.py 调用路径更新

移除对 `boundary._live_adapter` 私有属性的直接访问，改用 `boundary.call_live_with_messages()`。

### 3. Live LLM Trial 测试文件

**文件**: `tests/test_labgen_live_llm_trial.py`

40 tests，39 passed，1 skipped（live trial，需 `RUN_LIVE_LLM_TRIAL=1`）：

| 类别 | 测试数 | 内容 |
|------|--------|------|
| A. 配置验证 | 6 | live_enabled property / config issues / env var 读取 / fail-closed |
| B. Provider Adapter | 8 | HTTP 客户端注入 / parse 强制 DRAFT / 禁止字段剥离 / 错误传播 |
| C. call_live_with_messages | 5 | live_enabled 时成功 / live 未配置 → LLMProviderConfigError / fake_only → 错误 |
| D. Article-to-Lab Live Mode | 7 | rehearsal_required / publish_status never published / source_article_id / desired_lab_title / audit 写入 |
| E. 暴露防护 | 7 | raw_text 不持久化 / source_article_id 不在 catalog / audit 无 API key / 无 raw body |
| F. Live Rehearsal（skipped） | 1 | 真实 LLM 调用（RUN_LIVE_LLM_TRIAL=1 触发） |
| G. 回归 | 6 | health / catalog / LLM mode 默认 / 无 public upload route / 无 URL scraping |

---

## Live Trial 结果（真实 LLM 调用）

**触发命令**:
```bash
RUN_LIVE_LLM_TRIAL=1 pytest tests/test_labgen_live_llm_trial.py::TestInternalRehearsalSmoke -v
```

**试运行参数**:
- 模型：gpt-4o-mini（OpenAI-compatible endpoint）
- 文章：`[INTERNAL SAMPLE] Kubernetes ConfigMap 动态配置管理 — Live LLM Trial Only`
- Admin user：`owner`
- desired_lab_title：`[TRIAL] Kubernetes ConfigMap 基础操作`
- LABGEN_LLM_MODE：`live_admin_only`
- LABGEN_LLM_PROVIDER_MODE：`live_enabled`

**生成结果**:
```json
{
  "article": "[INTERNAL SAMPLE] Kubernetes ConfigMap 动态配置管理 — Live LLM Trial Only",
  "title": "[TRIAL] Kubernetes ConfigMap 基础操作",
  "step_count": 5,
  "publish_status": "draft",
  "rehearsal_required": true,
  "operability_status": "partially_lab_ready",
  "validation_passed": true,
  "failed_validator_checks": [],
  "has_commands": true,
  "has_verify": true,
  "has_cleanup": true,
  "warnings": [],
  "audit_entries": 1
}
```

**结论**: LLM 成功生成结构完整的 5 步实验草稿，StaticValidator 全部通过，publish_status=draft，rehearsal_required=True，完全符合 pipeline 预期。

---

## 安全不变量验证

| 约束 | 验证方式 | 状态 |
|------|---------|------|
| API key 不入审计日志 | `trial_config["api_key"] not in audit_json` | ✅ |
| raw article body 不入审计 | 检查 article body 特定片段不在 audit JSON | ✅ |
| publish_status 永不 published | `result.lab_draft.publish_status.value != "published"` | ✅ |
| rehearsal_required=True | 断言 `rehearsal_required is True` | ✅ |
| source_article_id 不暴露给 learner | E 类暴露防护测试 | ✅ |
| raw_text 不持久化 | 检查 article_draft.source_metadata.raw_text_persisted | ✅ |
| env var missing → fail closed | `LLMProviderConfigError` 专用异常 | ✅ |
| 无 public upload route | 检查路由无 reader 可访问上传端点 | ✅ |
| 无 URL scraping | 无 source_url fetch 路径 | ✅ |
| LLM 不绕过 Admin Review | 生成 → DRAFT → Admin PATCH → StaticValidator → Rehearsal → Publish | ✅ |
| prompt 不暴露给 learner | GenerateLabFromArticleResponse 无 prompt 字段 | ✅ |
| BLOCKER/HIGH/MEDIUM 不降级 | 0 items | ✅ |
| VMID 500-599 untouched | 无 VM 操作 | ✅ |

---

## 测试结果

**全量**: 4602 tests PASS，1 skipped，92.16% coverage（门禁：90%）

| 测试文件 | 数量 | 说明 |
|---------|------|------|
| test_labgen_live_llm_trial.py | 39+1 | G-68 新增 |
| 现有测试 | 4563 | 全部回归通过 |

---

## Safety Review

- 变更分类：**B 类**（新公开方法 + 新测试文件，无 auth/VM/shell 变更）
- safety-reviewer：本次变更为 B 类，无 A 类条件（无 auth/VM 操作/shell 注入路径变更）
- BLOCKER: 0 / HIGH: 0 / MEDIUM: 0

---

## 产出物

| 文件 | 说明 |
|------|------|
| `backend/labgen/llm_provider_boundary.py` | +call_live_with_messages() + LLMProviderConfigError |
| `backend/labgen/article_draft_service.py` | 更新调用路径（移除私有属性访问） |
| `tests/test_labgen_live_llm_trial.py` | 40 tests（A-G 类） |
| `docs/labgen/LIVE_LLM_ADMIN_TRIAL_RESULT_v0.1.md` | 本文档 |
| `CHANGELOG.md` | [Unreleased] 更新 |

---

## 决策依据：READY_WITH_NOTES 而非 READY_FOR_PUBLISH_GATE

**NOTES（不降级为 BLOCKER）**:

1. **内部样本文章**：本次试运行使用明确标注的 `[INTERNAL SAMPLE]` 文章，非真实 owner 创作文章。最终决策上限为 READY_WITH_NOTES。
2. **operability_status = partially_lab_ready**：样本文章包含 NEEDS_REVIEW 标注（StubFeasibilityClassifier 对 ConfigMap 文章的分级），生成继续执行。
3. **无 Internal Rehearsal 步骤执行**：本次仅做结构性评估（has_commands/has_verify/has_cleanup），未跑真实 K8s session。

**下一步（推荐）**:
1. 使用真实 owner 创作文章执行 Live LLM Trial → 可达到 READY_FOR_PUBLISH_GATE
2. 或：对当前生成草稿执行 Internal Admin Rehearsal（SessionType.INTERNAL_REHEARSAL），设置 rehearsal_completed=True 后尝试发布

---

## 约束声明

- VMID 500-599 untouched
- 无 public upload
- 无 URL scraping
- 无 Docker domain
- 无 customer pilot
- 无 public launch
- LLM API key 不进代码库（config.py 从 env var 读取）
- 无 reader 可触发 LLM
- 生成结果永不直接 publish
