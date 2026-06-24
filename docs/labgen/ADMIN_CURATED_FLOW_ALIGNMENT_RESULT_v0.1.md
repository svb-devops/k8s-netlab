# Admin-Curated Article-to-Lab Flow Alignment Result v0.1

**Date**: 2026-06-24
**Operator**: Claude Code acting as senior dev + ops
**Task**: G-57 — Admin-curated Article-to-Lab Flow Final Alignment & P0 Gap Plan
**No real secrets in this document.**

---

## A. Executive Summary

**Final Decision**: `ADMIN_CURATED_ARTICLE_TO_LAB_FLOW_ALIGNED_WITH_NOTES`

| Alignment Question | Answer |
|-------------------|--------|
| Phase 1 完成对齐？ | ✅ YES |
| 确认普通用户不上传文章？ | ✅ YES — Phase 1 绝对禁止 |
| 确认 admin-curated flow？ | ✅ YES — 唯一合法发布路径 |
| 确认现有 6 个 lab 是模板资产？ | ✅ YES — 不是 demo，是 Phase 1 标准模板 |
| 确认 P0/P1 gap 并排好优先级？ | ✅ YES — 见 Section C |
| WITH_NOTES 原因？ | 2 个 P0 gap 未实现（article_url + CTA 工具），但不 BLOCK 当前已有实验的正常运行 |

---

## B. Existing Capabilities（已有，不需重建）

### B.1 Article-to-Lab Admin Pipeline

| 步骤 | 实现 | 验证里程碑 |
|------|------|----------|
| Admin 输入文章文本 | `POST /api/labgen/article-drafts` | G-29 |
| 生成草稿（Stub，0 LLM 调用） | `LabDraftGeneratorStub` | G-30 |
| Admin 审核 + 编辑草稿 | `PATCH /api/labgen/drafts/{id}` + `labgen-admin.html` | G-31 |
| StaticValidator 发布门控 | `POST /api/labgen/drafts/{id}/validate`（13 项检查） | G-31 |
| 内部排练门控 | `rehearsal_required / rehearsal_completed` 字段 | G-30, G-41 |
| 发布 lab | `POST /api/labgen/drafts/{id}/publish` | G-31, G-44 |

### B.2 Reader Learning Path

| 步骤 | 实现 | 验证里程碑 |
|------|------|----------|
| 读者目录页 | `GET /api/labs` + `labgen-catalog.html` | G-45 |
| CTA deep link 格式 | `/labgen-lab.html?labId=<uuid>` | G-32, G-47 |
| 启动 lab session | `POST /api/lab-sessions`（6 条 precheck） | G-34 |
| 步骤检查 K8s | K8sVerifierClientAdapter | G-34 |
| 步骤检查 Linux | LinuxVerifierAdapter | G-51 |
| 完成 + cleanup | `POST /api/lab-sessions/{id}/complete` → LAB_CLOSED | G-34, G-51 |
| VM taint 恢复 | `data/tainted_vms.json` + precheck 拦截 | G-39 |

### B.3 Homepage Article System

| 组件 | 实现 |
|------|------|
| 公开首页 | `frontend/landing.html` — 文章列表，无需登录 |
| 文章详情页 | `frontend/article.html` — 正文 + 评论 |
| 文章 API | `GET /api/articles`（Directus CMS，filter published） |
| 文章管理 | Directus admin `127.0.0.1:8055` — `status=published` 即上线 |
| 读者评论 | `POST /api/articles/{slug}/comments`（需登录） |

### B.4 Published Lab Template Assets（6 个，两个 domain 均验证）

| Lab | Domain | Steps | 验证方式 |
|-----|--------|-------|---------|
| Kubernetes Basics | K8s | 1 | G-34 真实学习者 PASS |
| Kubernetes ConfigMap Basics | K8s | 2 | G-34 真实学习者 PASS |
| Kubernetes Secret Basics | K8s | 2 | G-34 真实学习者 PASS |
| Kubernetes Deployment Basics | K8s | 2 | G-34 真实学习者 PASS |
| Kubernetes ConfigMap 实战 | K8s | 2 | G-47 CTA dry run PASS |
| Linux Files and Permissions Basics | Linux | 4 | G-51 Trusted reader PASS |

**这 6 个 lab 是 Phase 1 的标准模板资产，不是临时 demo，不可弃用。新 lab 必须复用此格式。**

详见 [EXISTING_LAB_TEMPLATE_EXTRACTION_v0.1.md](EXISTING_LAB_TEMPLATE_EXTRACTION_v0.1.md)。

### B.5 Test & Security Baseline

- 测试：4339 tests PASS，92.26% coverage
- pre-push: 8 项安全扫描 + pytest 全量门禁
- GitHub Actions: pip-audit + bandit + ruff + mypy + pytest

---

## C. Real Gaps（真正缺失的内容）

### C.1 P0：Article → Lab 绑定（article_url 字段缺失）

**问题**：`LabDraft` 无 `article_url` 字段，Admin 无法在系统中记录外部发布文章链接。

**影响**：
- 系统无法追踪 lab 与外部文章的绑定关系
- 读者完成实验后看不到"回到原文"链接
- Admin 无法在后台验证 CTA 指向的 lab 是正确的

**验证**（确认缺失）：
```bash
# 检查 LabDraft schema
grep -n "article_url" backend/labgen/models.py
# 结果：无输出（字段不存在）

# 检查 6 个 published lab
# 结果：所有 6 个 lab 均无 article_url 字段
```

**修复计划**：见 [PHASE1_GAP_PRIORITIZATION_v0.1.md](PHASE1_GAP_PRIORITIZATION_v0.1.md) P0 Gap 1。

### C.2 P0：Admin CTA 工具（无标准生成/复制工具）

**问题**：Admin 每次发文章都需手工拼接 CTA URL，无标准文案模板，无 admin 界面工具。

**影响**：
- 发布效率低，容易出错（UUID 手工拼接）
- 无标准文案，各渠道 CTA 风格不一致
- 无法规模化（10 篇文章 = 10 次手工拼接）

**验证**（确认缺失）：
```bash
# 检查 admin 页面
grep -n "cta\|CTA\|copy" frontend/labgen-admin.html
# 结果：无 CTA 相关代码

grep -n "cta\|CTA\|copyLink" frontend/js/labgenViews.js
# 结果：无 CTA 生成工具
```

**修复计划**：见 [PHASE1_GAP_PRIORITIZATION_v0.1.md](PHASE1_GAP_PRIORITIZATION_v0.1.md) P0 Gap 2。

### C.3 P1：邮箱注册字段缺失

**问题**：用户模型无 `email` 字段，注册仅支持用户名+密码。

**影响**：
- 无法推送新文章/实验通知
- 读者忘记密码无法自助找回
- 无法按用户群体分层运营

**为什么是 P1 不是 P0**：email 是 reader growth/retention 基础设施，不是 Article→Lab 闭环的阻塞点。P0 两个 gap 实现后，读者仍然可以完成完整的 lab 学习流程。

**验证**（确认缺失）：
```bash
# 检查用户模型
grep -n "email" backend/auth.py
# 结果：无 email 相关代码

# 检查 users.json 字段
# 结果：{password_hash, created_at, assigned_vm} — 无 email
```

**修复计划**：见 [PHASE1_GAP_PRIORITIZATION_v0.1.md](PHASE1_GAP_PRIORITIZATION_v0.1.md) P1 Gap 3。

---

## D. Non-Goals（Phase 1 明确不做）

以下内容不属于 Phase 1 范围，任何提案包含这些内容均应被拒绝：

| Non-Goal | 理由 |
|----------|------|
| 开放普通用户上传文章 | Phase 2+ only；需要内容安全、版权确认、可行性分类器 |
| UGC（用户生成内容） | 需要内容审核流水线，Phase 1 未建 |
| Live LLM pipeline | 当前 fake_only 模式；LLM 输出不可控 |
| URL scraping | 法律和内容质量风险 |
| Auto-publishing generated drafts | Admin 人工审核是 Phase 1 硬性要求 |
| Docker domain | 未验证，Phase 1 forbidden |
| 新增 domain expansion | 仅 K8s + Linux 已验证 |
| Customer pilot / public launch | BLOCKED (NO_SUITABLE_SMALL_CUSTOMER) |
| Concurrency increase | 无性能需求本阶段 |
| 触碰 production VMID 500-599 | K8s learner VM 专用 |
| 发布新 lab | P0 gap 修复前暂停 |
| 宣称 arbitrary Article-to-Lab 已实现 | 未验证，不实 |
| 宣称 production ready | 未经 production readiness gate |

---

## E. Phase 1 vs Phase 2 Boundary

| 维度 | Phase 1（当前）| Phase 2（未来）|
|------|--------------|--------------|
| 谁提供文章 | 管理员 / 项目方 | 普通用户（受审核）|
| 内容来源 | Admin 手动提供 | 用户上传（带权限确认）|
| 审核方式 | Admin 人工审核 + StaticValidator | 可行性分类器 + Admin 二次确认 |
| LLM 模式 | fake_only（Stub 生成） | Live LLM（需质量门控）|
| 发布渠道 | Admin 手动发布 | 待定 |
| Reader 入口 | 文章 CTA deep link | 同 + 可能有 UGC 入口 |
| UGC | ❌ 明确禁止 | 未来考虑 |
| Public launch | ❌ 未就绪 | 待定 |

---

## F. Final Decision

```
ADMIN_CURATED_ARTICLE_TO_LAB_FLOW_ALIGNED_WITH_NOTES
```

**理由**：

1. ✅ Phase 1 产品方向对齐完成：Admin-curated Article-to-Lab，普通用户不上传文章
2. ✅ 现有 6 个 published labs 确认为标准模板资产（K8s + Linux 两个 domain 均有真实读者验证）
3. ✅ 网站首页 + 文章系统已有（landing.html + Directus + articles_routes.py）
4. ✅ Admin-to-Publish 完整流程已实现（draft → review → rehearsal → publish）
5. ✅ Reader 完整学习路径已实现（start → check → complete → cleanup）
6. ⚠️ WITH_NOTES：2 个 P0 gap 未实现（article_url 绑定 + CTA 工具）
7. ⚠️ P1 gap：邮箱注册字段缺失（不阻塞当前闭环）

---

## G. Recommended Next Step

**唯一建议的下一步**：

> **Article URL + CTA Tool Implementation**

具体实现：
1. `LabDraft` 模型加 `article_url`、`article_title`、`article_channel`、`article_published_at`、`cta_enabled` 5 个字段
2. `PATCH /api/labgen/drafts/{id}` 支持更新上述字段
3. `frontend/labgen-admin.html` 加 article URL 输入 + 4 种格式 CTA 复制按钮
4. 写回归测试（coverage ≥ 92% 维持）
5. safety-reviewer 审查（B 类变更）
6. pre-commit + pre-push PASS

**不做的**：
- ❌ 邮箱注册（P1，P0 完成后再规划）
- ❌ 新 lab 发布（P0 修复前暂停）
- ❌ 其他 non-goal 项目

---

## H. Technical Self-Check

- ✅ 不存在 TODO/FIXME
- ✅ 不存在 placeholder-as-success
- ✅ Phase 1 明确不开放普通用户上传文章
- ✅ Phase 1 是 admin-curated
- ✅ Reader 只消费实验，不生成实验
- ✅ Admin 提供文章
- ✅ Admin review required（rehearsal_completed=true 门控）
- ✅ Internal rehearsal required（rehearsal_required=true）
- ✅ No direct publish（StaticValidator + rehearsal 门控）
- ✅ No live LLM（fake_only 模式）
- ✅ No URL scraping
- ✅ No customer pilot
- ✅ No public launch
- ✅ No Docker domain
- ✅ No new lab in this task（本 task 无新 lab 发布）
- ✅ No concurrency increase
- ✅ Existing labs are reusable template assets（已抽象为模板文档）
- ✅ 无旧实验被当成弃用 demo
- ✅ 无 Docker domain 启动
- ✅ 无新 lab 发布
- ✅ 无并发提升
- ✅ 无触碰 production VMID 500-599
- ✅ 无 K8s / Linux regression
- ✅ 无声称 arbitrary Article-to-Lab 已实现
- ✅ 无声称 production ready
- ✅ 无 BLOCKER / HIGH / MEDIUM 被降级为 NOTE

---

## I. Modified Files

| 文件 | 变更类型 |
|------|---------|
| `docs/labgen/ADMIN_CURATED_ARTICLE_TO_LAB_FLOW_v0.1.md` | 新建 |
| `docs/labgen/EXISTING_LAB_TEMPLATE_EXTRACTION_v0.1.md` | 新建 |
| `docs/labgen/PHASE1_GAP_PRIORITIZATION_v0.1.md` | 新建 |
| `docs/labgen/ADMIN_CURATED_FLOW_ALIGNMENT_RESULT_v0.1.md` | 新建（本文件）|
| `CHANGELOG.md` | 更新 `[Unreleased]` 段 |
| `deploy/labgen/staging_ops_ticket_status.md` | 追加 G-57 记录 |
