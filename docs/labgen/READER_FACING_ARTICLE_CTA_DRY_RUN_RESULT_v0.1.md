# Reader-facing Article CTA Dry Run v0.1 — RESULT

**Status**: READER_FACING_ARTICLE_CTA_DRY_RUN_READY_WITH_NOTES
**Date**: 2026-06-21
**Executed by**: Claude Sonnet 4.6 (senior dev + ops)

---

## A. Executive Summary

| 维度 | 结论 |
|------|------|
| Reader-facing dry run 通过 | ✅ 是 |
| CTA 路径有效 | ✅ 是（mock CTA → article-linked lab） |
| Lab 可启动 | ✅ 是（LAB_ACTIVE，namespace 创建成功） |
| Guided Practice step check 通过 | ✅ 是（step_1 configmap_exists PASS，step_2 namespace_exists PASS） |
| Cleanup 通过 | ✅ 是（LAB_CLOSED，cleanup_verified=True，residual=0） |
| 已准备 trusted reader pilot | ⚠️ WITH_NOTES（内容质量 TODO 占位须改进） |
| LabGen LLM 调用次数 | 0 ✅ |
| 生产 VMID 500-599 触碰 | 否 ✅ |
| 原始文章文本持久化 | 否 ✅ |

---

## B. North Star Alignment

- 读了能练，练完即熟 ✅
- Admin-curated Article-to-Lab（admin 提供文章，admin 审核 draft） ✅
- Article CTA → LabGen（路径已验证） ✅
- Guided Practice Lab（非 Assessment Lab）：lab 结构存在但内容含 TODO 占位（MEDIUM） ⚠️
- AI 助手保留（DeepSeek AI tutor，独立于 LabGen 生成 pipeline） ✅
- K8s as domain proof ✅
- 不声称 arbitrary Article-to-Lab 已实现 ✅（stub pipeline，stub 生成）
- 不声称 production ready / public launch ✅

---

## C. Technical Debt Closure

### C.1 IP / Kubeconfig Drift Check

**实际使用路径**（服务从 `.env` 加载，非 `/etc/labgen/`）：

| 文件 | Server IP | 状态 |
|------|-----------|------|
| `creds/platform_kubeconfig.yaml` | `172.16.100.153:6443` | ✅ 正确 |
| `creds/vm_creds/401/kubeconfig.yaml` | `172.16.100.153:6443` | ✅ 正确 |
| VM 401 实际 IP（QEMU agent 查询） | `172.16.100.153` | ✅ 一致 |

**文档中的旧 IP 172.16.100.147**：仅出现在历史结果文档中（记录彼时 IP），非活跃配置，无需修改。

**澄清**：`/etc/labgen/home_lab_mvp.kubeconfig` 和 `/var/lib/labgen-staging/` 路径不是生产服务的实际路径，之前的 memory 记录有误。真正的配置由 `EnvironmentFile=/root/k8s-netlab/.env` 加载，kubeconfig 路径为 `creds/`。

### C.2 Catalog Isolation

- Published labs 对 learner 可见：5 个 ✅
- Draft/internal rehearsal labs 对 learner 不可见（404）✅
- article-linked lab 不暴露 `source_article_id`（UUID 类型，非原文）✅
- article-linked lab 不暴露 raw article text ✅
- catalog 仅 1 个 article-linked lab ✅（cf019133）
- 4 个 existing labs 未被影响 ✅

### C.3 Publish Gate Invariants

- 未经 rehearsal 不可 publish（409 REHEARSAL_REQUIRED）✅
- cleanup_verified=True 后才允许 publish ✅
- non-admin 不可 publish（401/403）✅
- learner 不可 publish ✅
- learner 不可访问 internal rehearsal 端点 ✅
- learner 不可启动 DRAFT generated lab（precheck 阻断）✅

### C.4 Guided Practice Content

**现状（stub pipeline 产出）**：

| 字段 | 状态 |
|------|------|
| 实验背景（experiment_background） | ❌ [TODO: Add description] |
| 实验目标 | ❌ [TODO: explain why this step matters] × 2 |
| 步骤指令（do field） | ✅ 有真实命令（创建 ConfigMap） |
| 步骤预期输出（observe field） | ❌ [TODO: describe what to observe] |
| Verify 检查 | ✅ 存在（step_1: configmap_exists，step_2: namespace_exists） |
| AI tutor context | ✅ 可用（DeepSeek，系统提示含 K8s 范围限制） |
| check_count | ✅ 正确（step_1=1，step_2=1） |

**评级**：MEDIUM — 内容骨架正确，关键 TODO 占位阻碍真实学习体验。

---

## D. Article CTA Dry Run

**Mock CTA 设计**（方案 A：文档模拟）：

```
标题：在 Kubernetes 中用 ConfigMap 管理应用配置
摘要：本文介绍如何创建和使用 ConfigMap 管理应用配置。

CTA 文案："读完这篇文章？用 5 分钟在隔离 K8s 环境中亲手验证一下。"
[立即进入实验] → /labs/cf019133-3a50-444d-8870-a84c25391cb7

目标 lab：cf019133-3a50-444d-8870-a84c25391cb7（"Untitled Lab (from article)"）
Route：GET /api/labs/cf019133... → 202 lab detail（含步骤预览）
```

**Reader 预期路径**：
1. 点击 CTA → 进入 lab catalog / detail 页面
2. 看到 lab 标题 + 步骤预览（2 steps）
3. 点击 Start Lab → POST /api/lab-sessions
4. 进入 Guided Practice 页面
5. 执行 kubectl 命令（由平台 terminal 支持）
6. Step Check PASS
7. Complete → LAB_CLOSED

---

## E. Learner Session Result

| 字段 | 值 |
|------|----|
| Learner 账号 | k8s_test |
| Session ID | 1e8c5309-b45a-4b0e-82f5-cc95ff6edc90 |
| Lab ID | cf019133-3a50-444d-8870-a84c25391cb7 |
| VM ID | 401 |
| Namespace | lab-1e8c5309-b45a-4b0e-82f5-cc95ff6edc90 |
| step_1 check（before ConfigMap） | FAIL（configmap_exists: not found）✅ 正确 |
| 执行命令 | `kubectl create configmap app-config --from-literal=APP_ENV=production` |
| step_1 check（after ConfigMap） | PASS ✅ |
| step_2 check（namespace_exists） | PASS ✅ |
| ready_to_complete | True |
| Complete 结果 | LAB_CLOSED，cleanup_verified=True |
| Namespace 残留 | 0（kubectl get ns 确认 NotFound）✅ |
| RoleBinding 残留 | 0 ✅ |
| Tainted VMs | 0 ✅ |

---

## F. AI Tutor Context Result

| 项目 | 状态 |
|------|------|
| AI tutor endpoint 可访问 | ✅ /api/ai/chat |
| LLM provider | DeepSeek（`deepseek-chat` model，已有平台功能） |
| LabGen pipeline LLM | ❌ 未调用（`mode=fake_only, live_enabled=false`） |
| AI tutor safety 约束 | ✅ 系统提示限定 K8s 范围，不给出完整命令 |
| AI tutor context 来自文章 | ❌（AI tutor 是通用 K8s 助手，无 per-lab 上下文注入） |
| 未透露实验答案 | ✅（系统提示禁止） |

**NOTE**：当前 AI tutor 是通用 K8s 问答助手（DeepSeek），未接入 per-lab 上下文（文章背景、当前步骤、预期输出）。为完整 Guided Practice 体验，AI tutor 应注入当前 lab 的 context。

---

## G. Catalog Verification

| # | lab_id | title | type |
|---|--------|-------|------|
| 1 | 67fca5e4 | Kubernetes Basics | regular |
| 2 | b0b97742 | Kubernetes ConfigMap Basics | regular |
| 3 | d9f44383 | Kubernetes Secret Basics | regular |
| 4 | e52b8b80 | Kubernetes Deployment Basics | regular |
| 5 | cf019133 | Untitled Lab (from article) | article-linked |

Draft labs 不可见（验证通过：GET /api/labs/{draft_id} → 404）。

---

## H. Safety Invariants

| 项目 | 值 |
|------|----|
| LabGen pipeline LLM 调用次数 | 0 ✅ |
| 原始文章文本持久化 | 否 ✅ |
| Secret / kubeconfig 泄漏 | 否 ✅ |
| 生产 VMID 500-599 触碰 | 否 ✅（仅使用 VM 401） |
| 并发未提高 | ✅ |
| Customer pilot 未启动 | ✅ |
| public article upload 未开放 | ✅ |
| source_article_id 在 catalog 中 | 不暴露（learner API 不返回此字段）✅ |

---

## I. Issue Triage

### BLOCKER
无。

### HIGH
无。

### MEDIUM
- **M-01 [内容质量] Guided Practice 含 TODO 占位**
  - 所有 `why` 字段（步骤目标）= `[TODO: explain why this step matters]`
  - `description` = `[TODO: Add description]`
  - `observe` = `[TODO: describe what to observe after completing this step]`
  - 根因：stub pipeline 不生成真实内容，LLM 集成待实现
  - 影响：真实读者看到 TODO 会认为平台未完成
  - 推荐修复：实现 LLM 生成，或 admin 手动填写关键字段

- **M-02 [Lab 标题] "Untitled Lab (from article)"**
  - stub pipeline 不生成标题
  - 影响：CTA 点击后看到无标题 lab，不吸引人
  - 推荐修复：admin 在 Directus 或 admin API 编辑草稿标题

### LOW
- **L-01 [step_2 verify] manual_review_required=true**
  - `namespace_exists` verify 被标记 manual_review_required（由 stub 生成时 `[TODO: configure verifier]` 注释引入）
  - 实际执行无误（namespace_exists 是可自动验证的），但标记不准确
  - 推荐修复：stub generator 完善后自动设置正确值；或 admin PATCH 修正

### NOTE
- **N-01 [VM ownership staging 限制]**
  - home_lab_mvp staging 只有 1 个 VM（401），归属 smoke-admin
  - 真实 learner dry run 需临时修改 vm_creation_times.json
  - trusted reader pilot 前需确认学员账号的 VM assignment 流程
  - 现有 Runbook §K 已有 VM assignment 说明

- **N-02 [AI tutor 无 per-lab context]**
  - 当前 AI tutor 是通用 K8s 助手，无法感知当前 lab 的步骤、文章背景
  - 不阻断 dry run，但影响 Guided Practice 体验完整性

- **N-03 [/etc/labgen/ 路径文档错误]**
  - 历史 memory/docs 中记录了 `/etc/labgen/home_lab_mvp.kubeconfig`，但实际服务使用 `creds/platform_kubeconfig.yaml`
  - 已更新 memory；ops runbook 中此路径章节需确认

---

## J. Final Decision

**READER_FACING_ARTICLE_CTA_DRY_RUN_READY_WITH_NOTES**

完整 reader path 在技术层面闭环。核心 gate（precheck、namespace lifecycle、step verify、cleanup）全部工作正常。MEDIUM 问题（TODO 占位内容）不阻断 dry run 本身，但必须在 trusted reader pilot 前修复。

---

## K. Recommended Next Step

**Guided Practice Quality Iteration**

将 article-linked lab（cf019133）的 `why`/`description`/`observe` 从 TODO 占位替换为真实内容，并验证 Step Check PASS。可由 admin 手动 PATCH（无需 LLM）：

```
PATCH /api/labgen/drafts/cf019133.../
{
  "title": "Kubernetes ConfigMap 实战：从文章到实验",
  "description": "通过本实验，你将在隔离的 K8s 环境中亲手创建并验证 ConfigMap，巩固文章中的核心概念。"
}
```

然后验证 publish（已 published，只需重新验证内容是否通过 StaticValidator）。

---

## L. Test Coverage

新增 3 个测试（`tests/test_labgen_article_publish_gate.py::TestRegression`）：

| 测试名 | 验证内容 |
|--------|---------|
| `test_published_article_linked_lab_allows_learner_precheck` | learner precheck PASS for published article lab |
| `test_published_article_lab_step_preview_has_do_instruction` | step preview 有 instructions_summary |
| `test_published_article_lab_step_check_count_matches_verify_list` | check_count = len(step.verify) |

全量结果：3571 passed，93.26% coverage。
