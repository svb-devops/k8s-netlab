# Owner Soft Launch Article #1 Publish Gate — G-69 Result

**状态**: OWNER_SOFT_LAUNCH_ARTICLE1_NEEDS_ITERATION
**日期**: 2026-06-26
**目标**: 使用真实 owner 文章完成第一篇 soft launch article 的 publish gate

---

## A. Executive Summary

| 项目 | 结果 |
|------|------|
| Final Decision | **OWNER_SOFT_LAUNCH_ARTICLE1_NEEDS_ITERATION** |
| Owner article used | ❌ 无真实 owner 文章提供 |
| Article is real owner-authored | ❌ |
| Live LLM generation run | ❌（无文章输入，未触发） |
| Draft generated | ❌ |
| StaticValidator run | ❌ |
| Admin Review snapshot | ❌ |
| Internal Rehearsal | ❌ |
| Publish gate status | ❌ BLOCKED — 缺真实 owner 文章 |
| Final publish executed | ❌ |
| No public upload | ✅ 保持 |
| No reader LLM | ✅ 保持 |
| No URL scraping | ✅ 保持 |
| No direct publish | ✅ 保持 |

决策原因：本任务要求使用真实 owner 创作文章进入 publish gate。任务输入中未提供实际文章内容。根据任务规则，不得使用 [INTERNAL SAMPLE] 文章代替，不得伪造 owner 文章，最终决策只能为 NEEDS_ITERATION 或 BLOCKED。

**NEEDS_ITERATION（非 BLOCKED）原因**：
- Pipeline 技术架构完整（G-68 已证明 live LLM 链路可用）
- Owner Article Gate 已实现并测试（新增 [INTERNAL SAMPLE] 拦截器）
- 唯一阻塞：缺真实 owner 文章
- 提供文章后可立即进入完整 publish gate 流程

---

## B. North Star Alignment

| 约束 | 状态 |
|------|------|
| 读了能练：Article → Lab 闭环 | ✅ 目标保持，待文章提供后执行 |
| Admin-curated Article-to-Lab | ✅ 架构保持 |
| LLM drafts only（非直接发布） | ✅ 架构保持 |
| Admin review required | ✅ 架构保持 |
| Internal rehearsal required | ✅ 架构保持 |
| No reader generation | ✅ 保持 |
| No URL scraping | ✅ 保持 |
| No direct publish | ✅ 保持 |

---

## C. Owner Article Input

**状态**：未提供

任务输入中未包含以下格式的 owner 文章：

```yaml
owner_article_1:
  article_title: <标题>
  article_text: <文章正文>
  target_domain: k8s | linux
  publish_channel: official_site
  copyright_confirmed: true
  intended_reader: <目标读者>
  safety_notes: <安全说明>
  desired_lab_title: <期望实验标题>
  owner_publish_intent: soft_launch_article_1
```

**不允许替代方案**：
- ❌ 不得使用 [INTERNAL SAMPLE] 文章（G-68 内部样本，明确标注）
- ❌ 不得伪造 owner 文章
- ❌ 不得进入 publish gate

---

## D. Pipeline Result（Readiness Check）

| 步骤 | 状态 | 说明 |
|------|------|------|
| Owner Article Input Gate | ✅ 已实现 | copyright_confirmed + domain + channel + [INTERNAL SAMPLE] 拦截 |
| Operability Gate | ✅ 就绪 | StubFeasibilityClassifier 可处理 k8s/linux 文章 |
| LLM Generation（live_admin_only） | ✅ 就绪 | G-68 已验证 gpt-4o-mini 可用 |
| Schema Parse | ✅ 就绪 | ArticleDraftService + LabDraftGeneratorStub/Live |
| StaticValidator | ✅ 就绪 | 13 项 publish-gate 检查 |
| Admin Review Snapshot | ✅ 就绪 | AdminReviewDiffRepository append-only |
| Internal Rehearsal | ✅ 就绪 | lab_session_service.py 完整状态机 |
| Cleanup Verification | ✅ 就绪 | cleanup_verified + taint 机制 |
| Publish Gate | ✅ 就绪 | PublishService.publish() + RehearsalNotCompleted 守卫 |
| Owner YES Confirmation | 待定 | 需 owner 明确 YES |

**执行阻断**：缺真实 owner 文章输入，以上步骤均未实际执行。

---

## E. Internal Rehearsal Evidence

无执行记录。

**原因**：无文章输入，未触发 LLM 生成，未创建实验草稿，未执行 rehearsal session。

---

## F. Safety / Exposure

已验证（via readiness check tests）：

| 约束 | 验证方式 | 状态 |
|------|---------|------|
| No raw article text in learner API | E 类暴露测试（/api/labs 无 raw_text） | ✅ |
| No source_article_id in learner API | E 类暴露测试（/api/labs 无 source_article_id） | ✅ |
| No prompt in learner API | E 类暴露测试（/api/labs 无 "prompt"） | ✅ |
| No public upload route | E5/G6 测试（404/405） | ✅ |
| No reader LLM trigger route | C4 测试（/api/labs/generate 等 → 404/405） | ✅ |
| No URL scraping route | E6 测试（/api/labgen/article-drafts/from-url → 404/405） | ✅ |
| No direct publish | D1 测试（rehearsal 缺失 → RehearsalNotCompleted） | ✅ |
| API key not in code | 代码审查 | ✅ |
| API key not in logs | 审计日志结构检查 | ✅ |
| [INTERNAL SAMPLE] blocked | A2/A3/G9 测试 | ✅ **新实现** |

---

## G. Test Results

### 新增测试：test_labgen_owner_article_gate.py（41 tests，全部通过）

| 类别 | 测试数 | 内容 |
|------|--------|------|
| A. Owner Article Gate | 10 | 内部样本拦截 / copyright / domain / channel / reader 无权限 |
| B. Pipeline Readiness | 5 | create_draft / fake_only 生成 / never published / rehearsal_required / raw_text 不持久化 |
| C. LLM Mode Guard | 5 | live_enabled default false / fail-closed / 默认非 live |
| D. Publish Pipeline Order | 3 | rehearsal 守卫 / draft status / source_article_id |
| E. Exposure Guard | 7 | catalog 无内部字段 / admin-only list / upload 不存在 / scraping 不存在 |
| F. E2E Gate Smoke | 2 | 文档 BLOCKED 状态 / pipeline readiness confirmed |
| G. Regression | 9 | health / catalog / registration / VMID / upload / draft list |

### 全量测试

- **4643 passed, 1 skipped, 92.14% coverage**（门禁：90%）
- 覆盖现有 4602 回归 + 41 新增 Owner Gate 测试

### 代码变更

- `backend/labgen/article_draft_routes.py`：新增 [INTERNAL SAMPLE] 标题拦截（+7 行，路由层 422）
- `tests/test_labgen_owner_article_gate.py`：新增 41 tests

---

## H. Known Limitations

1. **Publish not executed**: 无 owner 文章 → 无 LLM 生成 → 无 publish
2. **No real article input**: Owner 必须提供真实文章才能进入 publish gate
3. **Only k8s/linux supported**: Docker domain、cloud-only 文章不支持
4. **No URL scraping**: Owner 必须直接粘贴文章全文
5. **No public user upload**: 仅 admin（owner）可提交文章
6. **No public launch**: 平台仍处于 Phase 1 内部运营状态
7. **No customer pilot**: 当前无新 cohort 启动

---

## I. Issue Triage

| 级别 | 数量 | 说明 |
|------|------|------|
| BLOCKER | 0 | 无技术阻断 |
| HIGH | 0 | - |
| MEDIUM | 0 | - |
| LOW | 0 | - |
| NOTE | 1 | Pipeline readiness check 只能验证技术架构，无法替代真实 owner 文章流程 |

---

## J. Final Decision

**OWNER_SOFT_LAUNCH_ARTICLE1_NEEDS_ITERATION**

决策依据：
1. 无真实 owner 文章提供 → 无法执行 publish gate
2. Pipeline 技术架构已完整就绪（G-68 + G-69 readiness check 双重验证）
3. Owner Article Gate 新增 [INTERNAL SAMPLE] 拦截器，防止内部样本进入生产 pipeline
4. 只需 owner 提供真实文章，即可立即重启 publish gate 流程

不选 BLOCKED 原因：BLOCKED 意味着技术或架构有阻塞。当前无阻塞，只缺输入。

---

## K. Recommended Next Step

**Owner Article #1 提交** — 使用以下格式提供真实 owner 创作文章：

```yaml
owner_article_1:
  article_title: <文章标题（不得以 [INTERNAL SAMPLE] 开头）>
  article_text: |
    <文章完整正文>
    <包含可执行步骤、命令、预期输出>
  target_domain: k8s  # 或 linux
  publish_channel: official_site
  copyright_confirmed: true
  intended_reader: <例：intermediate k8s practitioner>
  safety_notes: <可选：安全说明>
  desired_lab_title: <期望实验标题>
  owner_publish_intent: soft_launch_article_1
```

提交后将执行：
1. Owner Article Gate 验证（copyright + domain + 内容检查）
2. Operability Gate（StubFeasibilityClassifier）
3. live_admin_only LLM 生成实验草稿（gpt-4o-mini）
4. StaticValidator（13 项检查）
5. Admin Review Snapshot
6. Real Internal Rehearsal Session（LAB_ACTIVE → LAB_CLOSED）
7. cleanup_verified + residual=0 确认
8. Publish Gate Decision
9. 等待 owner 明确 YES 后执行 final publish

---

## 约束声明

- VMID 500-599 untouched ✅
- 无 public upload ✅
- 无 URL scraping ✅
- 无 Docker domain ✅
- 无 customer pilot ✅
- 无 public launch ✅
- LLM API key 不进代码库 ✅
- 无 reader 可触发 LLM ✅
- 生成结果永不直接 publish ✅
- [INTERNAL SAMPLE] 文章无法通过 Owner Article Gate ✅（新增）
