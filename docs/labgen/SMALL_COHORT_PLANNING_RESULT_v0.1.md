# Small Cohort Planning Gate Result v0.1

**Date**: 2026-06-25
**Operator**: Claude Code — senior dev + ops (senior dev + ops 双角色)
**Task**: Small Cohort Planning Gate v0.1
**No real secrets in this document.**

---

## A. Executive Summary

| 项目 | 状态 |
|------|------|
| Planning Gate 完成？ | ✅ YES |
| Cohort 已启动？ | ❌ NO（等待 owner 审批） |
| Accounts 已创建？ | ❌ NO（等待 owner 审批） |
| MEDIUM-001 (CTA redirect missing ?next=) 已修复？ | ✅ YES — article.js 已修复，回归测试通过 |
| 等待 owner 提供什么？ | learner identities + test window + 明确 YES |

**Final Decision**: `SMALL_COHORT_PLANNING_READY_WITH_NOTES`

**WITH_NOTES 原因**：
1. Owner 尚未提供 learner identities / test window / 明确 YES
2. 两个 LAB_START_FAILED stale dev 账号 sessions（非 learner sessions，terminal 状态）（NOTE）

---

## B. North Star Alignment

| 原则 | 状态 |
|------|------|
| 读了能练，练完即熟 | ✅ Article CTA → Lab → Practice 链路完整 |
| Admin-curated Article-to-Lab | ✅ 管理员提供文章，普通用户不上传 |
| Article CTA → lab | ✅ linux-files-permissions-basics CTA 正确绑定 6c439064 |
| Reader 只练习，不上传文章 | ✅ 无 public upload 端点 |
| 无 public upload | ✅ |
| 无 live LLM | ✅ fake_only 模式 |
| 无 URL scraping | ✅ |

---

## C. Current Readiness

| 检查项 | 状态 | 详情 |
|--------|------|------|
| G-63 real article binding | ✅ DONE | owner 确认 official_site |
| Article slug | ✅ | `linux-files-permissions-basics` |
| Lab id | ✅ | `6c439064-4cad-4229-addb-36927128d565` |
| CTA status | ✅ | `has_cta=True`, `cta_url` 正确, `source_article_id` 未暴露 |
| Registration email | ✅ | G-62 实现，`register-email` input 存在 |
| Cleanup status | ✅ | G-63 E2E: cleanup_verified=True, residual=0 |

---

## D. Cohort Scope

| 项目 | 规划值 |
|------|--------|
| 规模 | 3–5 人 |
| 类型 | trusted learners（技术从业者） |
| 分配策略 | Option A — 所有人做同一篇文章 + 同一 lab（linux-files-permissions-basics → 6c439064） |
| 执行模式 | staggered（错峰，每次 1 人） |
| 并发 | 不提高（系统默认 1/user） |

---

## E. Feedback Plan

### 自动记录

- session_id / student_username / started_at / ended_at / completed_step_ids / last_verify_results / cleanup_verified

### 手动记录（operator）

- retry count / operator intervention count / Need Help 使用次数

### 10-Q 表（Complete 后立即收集）

1. 能否顺利从文章找到实验入口？
2. CTA 文案是否清楚？
3. 注册 / 登录是否顺利？
4. 实验背景是否解释为什么要做？
5. 步骤是否清楚？
6. 命令是否容易复制执行？
7. Check 反馈是否帮助判断进度？
8. 哪一步最困难？
9. 是否需要人工帮助？（哪一步？）
10. 是否愿意继续做类似实验？为什么？

**规定**：完成后立即收集；不得事后追补；缺少 feedback 的 learner 不计入完整样本。

---

## F. Success / Failure Criteria

### Success（推荐执行标准）

| 标准 | 阈值 |
|------|------|
| 所有 learner 打开文章页面 | 100% |
| 所有 learner 看到 CTA | 100% |
| 所有 learner 能注册 / 登录 | 100% |
| Start 成功率 | ≥ 80% |
| Complete 成功率 | ≥ 80% |
| completed sessions: cleanup_verified=True | 100% |
| residual=0 | 100% |
| active sessions after run = 0 | 100% |
| taint state clean | 100% |
| 所有安全暴露检查 | 100% PASS |
| 每位 learner 有 feedback | 100% |
| 无 BLOCKER / HIGH | 100% |

### Failure Criteria（BLOCKER）

文章页面 CTA 不显示 / CTA 指向错误 lab / 注册登录普遍失败 / Start 普遍失败 / Check 错误 / Complete 失败 / cleanup failure / residual remains / draft/internal lab 暴露 / source_article_id 泄露 / raw article 泄露 / password_hash 泄露 / public upload route 出现 / live LLM 被调用 / URL scraping 被触发 / production VMID 500-599 被触碰

---

## G. Rollback Plan

出现 BLOCKER → 立即执行：
1. 停止 cohort
2. 禁用 / 移除 cohort learner 账号
3. `POST /api/lab-sessions/{id}/abort` 中止所有 active sessions
4. 验证 active=0, tainted={}, residual=0
5. 视需要 admin PATCH `cta_enabled=false`
6. catalog 保持稳定（不回滚 published labs）
7. 记录 incident

---

## H. Approval Boundary

| 要求 | 状态 |
|------|------|
| learner_identities | ⏳ 待 owner 提供 |
| test_window | ⏳ 待 owner 提供 |
| 明确 YES | ⏳ 待 owner 提供 |

**缺少任何一项 → 不得创建账号 / 不得邀请 learner / 不得启动 execution。**

明确 YES 格式：`YES, approve Small Cohort Execution.`

详见 `docs/labgen/SMALL_COHORT_APPROVAL_GATE_v0.1.md`

---

## I. Readiness Check Result

| 检查项 | 状态 | 详情 |
|--------|------|------|
| Article page reachable | ✅ PASS | `200 OK` |
| Embedded CTA visible | ✅ PASS | `has_cta=True`, `cta_url=/labgen-lab.html?labId=6c439064...` |
| Lab CTA endpoint returns safe data | ✅ PASS | `source_article_id` 未在响应中 |
| Registration form has email | ✅ PASS | `register-email` input 存在（1 处）|
| Login redirect (CTA→register→lab) | ✅ PASS (post-fix) | MEDIUM-001 已修复，btn.href 现含 `?next=encodeURIComponent(ctaUrl)` |
| Target lab published | ✅ PASS | 6 labs published，6c439064 存在，cta_enabled=True |
| cta_enabled=true | ✅ PASS | |
| Active real learner sessions | ✅ PASS | 0（LAB_START_FAILED 为 terminal stale dev sessions） |
| Residual = 0 | ✅ PASS | tainted_vms={} |
| Taint clean | ✅ PASS | tainted_vms.json: {} |
| Catalog visible (auth required) | ✅ PASS | 正确需要认证 |
| K8s Lab 5 unaffected | ✅ PASS | cf019133 仍 published |
| Linux lab 6c439064 unaffected | ✅ PASS | cta_enabled=True |
| No LLM calls | ✅ PASS | LABGEN_LLM_PROVIDER_MODE default=fake_only |
| No URL scraping | ✅ PASS | zero HTTP external calls |
| VMID 500-599 untouched | ✅ PASS | sessions.json 确认无 production VMID |
| No public upload route | ✅ PASS | POST /api/articles → 404/405 |
| source_article_id not exposed | ✅ PASS | CTA 响应字段确认 |
| raw article text not exposed | ✅ PASS | /api/articles 仅含 id/slug/title/excerpt/published_at |
| email not exposed in article API | ✅ PASS | 无 email 字段 |
| password_hash not exposed | ✅ PASS | 未认证 401 |
| Health | ✅ PASS | `{"status":"healthy","proxmox":{"connected":true}}` |

---

## J. Issue Triage

| 级别 | 数量 | 说明 |
|------|------|------|
| BLOCKER | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 1 | ✅ FIXED — CTA redirect missing `?next=` param（MEDIUM-001）|
| LOW | 0 | — |
| NOTE | 1 | 2 个 LAB_START_FAILED stale dev sessions（k8s_test, smoke-admin；terminal 状态，started_at=None，无 K8s 资源残留）|

### MEDIUM-001 详情（已修复）

**问题**：`article.js` 中未认证用户点击 CTA 时，`btn.href = '/login.html'`（无 `?next=` 参数）。新 learner 注册/登录后被重定向到 `/app`，而非目标 lab，Article → CTA → Register → Lab UX 链路断裂。

**修复**：
```javascript
// 修复前
btn.href = '/login.html';

// 修复后
btn.href = '/login.html?next=' + encodeURIComponent(ctaUrl);
```

**文件**：`frontend/js/article.js` line 241

**回归测试**：`tests/test_article_embedded_cta.py::TestArticleHtmlStaticSafety::test_article_js_unauthenticated_cta_includes_next_param`

**安全分析**：`ctaUrl` 已经过 `_validateCtaUrl()` 校验（强制 `/labgen-lab.html?labId=` 前缀，拒绝外部 URL / javascript:），无 open redirect 风险。

---

## K. Final Decision

```
SMALL_COHORT_PLANNING_READY_WITH_NOTES
```

**理由**：
1. ✅ Phase 1 Article → CTA → Register/Login → Lab → Cleanup 闭环已验证（G-63）
2. ✅ MEDIUM-001 CTA redirect 已修复（4503 tests PASS, 92.23% coverage）
3. ✅ 全部 22 项 readiness checks 通过
4. ✅ 无 BLOCKER / HIGH 遗留
5. ✅ Cohort plan 完整（规模 / assignment / execution / account / feedback / success criteria / rollback / runbook）
6. ✅ Approval gate 明确（owner input template + 明确 YES 格式）
7. WITH_NOTES：cohort NOT started；accounts NOT created；等待 owner 提供 learner identities + test window + 明确 YES

---

## L. Recommended Next Step

```
Small Cohort Execution
```

前提：owner 提供 `SMALL_COHORT_APPROVAL_GATE_v0.1.md` 所需全部字段 + 明确 YES。

其他候选：
- Small Cohort Planning Round 2（如 owner 有调整要求）
- Email Verification / Password Recovery Planning
- Hold Expansion

---

## M. Modified Files

| 文件 | 变更 |
|------|------|
| `frontend/js/article.js` | MEDIUM-001 修复：unauthenticated CTA btn.href 加 `?next=encodeURIComponent(ctaUrl)` |
| `tests/test_article_embedded_cta.py` | 新增回归测试 `test_article_js_unauthenticated_cta_includes_next_param` |
| `docs/labgen/SMALL_COHORT_PLAN_v0.1.md` | 新增（cohort scope / assignment / execution / account / feedback / success / failure / rollback / runbook）|
| `docs/labgen/SMALL_COHORT_APPROVAL_GATE_v0.1.md` | 新增（owner input template + YES 格式 + 约束声明）|
| `docs/labgen/SMALL_COHORT_PLANNING_RESULT_v0.1.md` | 本文件 |
| `deploy/labgen/staging_ops_ticket_status.md` | G-64 条目追加 |
| `CHANGELOG.md` | [Unreleased] 更新 |

---

## N. Technical Self-Check

| 检查项 | 状态 |
|--------|------|
| 无 TODO/FIXME | ✅ |
| 无 placeholder-as-success | ✅ |
| cohort 未启动 | ✅ |
| cohort accounts 未创建 | ✅ |
| learner 未受邀 | ✅ |
| customer pilot 未启动 | ✅ |
| public launch 未启动 | ✅ |
| 普通用户上传未开放 | ✅ |
| live LLM call=0 | ✅ |
| URL scraping 未启用 | ✅ |
| production VMID 500-599 未触碰 | ✅ |
| 并发未提高 | ✅ |
| article CTA 状态明确 | ✅ |
| registration email 状态明确 | ✅ |
| feedback capture 明确 | ✅ |
| success/failure criteria 明确 | ✅ |
| rollback plan 明确 | ✅ |
| approval gate 明确 | ✅ |
| 无 raw article text 暴露 | ✅ |
| 无 source_article_id 暴露 | ✅ |
| 无 email 暴露 | ✅ |
| 无 password_hash 暴露 | ✅ |
| 无 K8s regression | ✅ 4503 tests PASS |
| 无 Linux regression | ✅ |
| 无 catalog regression | ✅ |
| 无 BLOCKER/HIGH/MEDIUM 被降级为 NOTE | ✅（MEDIUM-001 已修复，未降级）|

---

*Artifact created: 2026-06-25. MEDIUM-001 fixed (CTA redirect). Planning Gate complete. Awaiting owner approval for execution.*
