# Guided Practice Quality Iteration — Lab 5 v0.1 — RESULT

**Status**: GUIDED_PRACTICE_QUALITY_READY_FOR_TRUSTED_READER  
**Date**: 2026-06-21  
**Executed by**: Claude Sonnet 4.6 (senior dev + ops)

---

## A. Executive Summary

| 维度 | 结论 |
|------|------|
| Lab 5 [TODO] 占位全部清除 | ✅ 是（placeholder scan CLEAN） |
| Reader path 重新验证通过 | ✅ 是（LAB_ACTIVE→PASS→LAB_CLOSED） |
| 是否 ready for trusted reader pilot | ✅ 是 |
| 剩余技术债 | LOW/NOTE 级别，不阻断 |
| LabGen LLM 调用 | 0 ✅ |
| 生产 VMID 500-599 触碰 | 否 ✅ |
| 原始文章文本持久化 | 否 ✅ |
| Trusted reader pilot 是否启动 | 否（由 ops 团队决定） |
| Customer pilot 是否启动 | 否 ✅ |

---

## B. North Star Alignment

- 读了能练，练完即熟 ✅（Lab 5 有真实 why/observe/troubleshooting）
- Admin-curated Article-to-Lab（admin 提供内容，admin 审核）✅
- Guided Practice Lab（非 Assessment Lab）✅
- 实验背景 = 文章内容摘要 ✅（ConfigMap 隔离 vs 镜像，多租户 namespace 隔离）
- AI tutor 保留（DeepSeek，独立于 LabGen pipeline）✅
- K8s as domain proof ✅
- 不声称 arbitrary Article-to-Lab 已实现 ✅（stub pipeline，admin-curated）
- 不声称 production ready / public launch ✅

---

## C. Previous Issue

**上一里程碑**：READER_FACING_ARTICLE_CTA_DRY_RUN_READY_WITH_NOTES（commit 000f3f7）

**MEDIUM 阻断项**（M-01、M-02）：

| 字段 | 旧值（stub 生成） |
|------|-----------------|
| title | "Untitled Lab (from article)" |
| description | "[TODO: Add description]" |
| step_1.why | "[TODO: explain why this step matters]" |
| step_1.observe | "[TODO: describe what to observe after completing this step]" |
| step_1.explain.concept | "[TODO: core concept]" |
| step_1.explain.observation | "[TODO: expected observation]" |
| step_2.why | "[TODO: explain why this step matters]" |
| step_2.observe | "[TODO: describe what to observe after completing this step]" |
| step_2.explain.concept | "[TODO: core concept]" |
| step_2.explain.observation | "[TODO: expected observation]" |
| step_2.verify.notes | "[TODO: configure verifier from article contract]" |
| step_2.verify.manual_review_required | true（错误标记） |

**为什么阻断 trusted reader pilot**：真实读者点击 CTA 后看到 `[TODO]` 占位会认为平台未完成，严重损害可信度。

---

## D. Content Changes

### D.1 变更字段汇总

| 字段 | 变更类型 | 读者体验改进 |
|------|---------|------------|
| `title` | "Untitled Lab (from article)" → "Kubernetes ConfigMap 实战：从文章到实验" | 标题可读，与 CTA 文章主题匹配 |
| `description` | [TODO] → 完整说明（隔离/创建/验证/自动回收） | 读者看到实验价值，有助于决定是否开始 |
| `step_1.why` | [TODO] → 解释 ConfigMap 与镜像解耦的价值 | 读者理解"为什么做"，不只是"做什么" |
| `step_1.observe` | [TODO] → `configmap/app-config created` 解释 | 读者知道成功的标志，不会迷失 |
| `step_1.explain.concept` | [TODO] → ConfigMap vs Secret 的区别 | 巩固文章概念，而非重复 |
| `step_1.explain.observation` | [TODO] → DATA 列显示键值对数量 | 帮助读者关联 K8s 对象结构 |
| `step_2.why` | [TODO] → 解释 namespace 隔离和零残留设计 | 读者理解平台多租户设计，建立信任 |
| `step_2.observe` | [TODO] → 平台自动验证，namespace 自动删除 | 消除"实验会不会占用资源"的顾虑 |
| `step_2.explain.concept` | [TODO] → namespace 隔离逻辑边界 + 自动删除 | 链接 K8s 基础知识 |
| `step_2.explain.observation` | [TODO] → namespace_exists 检查说明 | 理解平台后台验证机制 |
| `step_2.verify.notes` | [TODO] → null | 消除无效注释 |
| `step_2.verify.manual_review_required` | true → false | 修正错误标记（namespace_exists 可自动验证） |

### D.2 变更路径

- 通过 `PATCH /api/labgen/drafts/cf019133.../` admin 端点
- `publish_status=published` 保留（PATCH 不改变此字段）
- `rehearsal_required=True, rehearsal_completed=True` 保留
- `source_article_id` 保留
- 全部变更记录在 `AdminReviewDiff` 中（audit trail）

---

## E. Placeholder Scan Result

**方法**：Python + 正则 `\[TODO[^\]]*\]|(?<!\w)TODO(?!\w)|\bTBD\b|\bPLACEHOLDER\b|coming soon`

**扫描范围**：`data/lab_drafts.json` → Lab 5 对象完整 JSON

```
CLEAN — no placeholders in Lab 5 data
```

**结果**：0 个 placeholder 残留。

---

## F. Guided Practice Completeness

| 字段 | 状态 |
|------|------|
| 实验背景（description） | ✅ 真实内容（ConfigMap 实践背景） |
| 实验目标（step why） | ✅ step_1 + step_2 均有真实解释 |
| 步骤指令（do） | ✅ 真实 kubectl 命令 |
| 步骤预期输出（observe） | ✅ 具体输出描述 |
| 概念解释（explain.concept） | ✅ ConfigMap vs Secret 区别 |
| 观察解释（explain.observation） | ✅ kubectl 输出含义解释 |
| Verify 检查 | ✅ configmap_exists + namespace_exists，均无 TODO |
| AI tutor context | ✅（通用 K8s 助手，系统提示含范围限制）|
| 完成提示（通过 step check 流程体现） | ✅ ready_to_complete=True 后 Complete 可用 |

---

## G. Reader Re-validation

| 字段 | 值 |
|------|----|
| Learner 账号 | k8s_test |
| Session ID | 03e6a04b-4885-4c47-bf40-bc378f0016e0 |
| Lab ID | cf019133-3a50-444d-8870-a84c25391cb7 |
| VM ID | 401 |
| Namespace | lab-03e6a04b-4885-4c47-bf40-bc378f0016e0 |
| Catalog 显示 title | "Kubernetes ConfigMap 实战：从文章到实验" ✅ |
| Catalog 有 TODO | 否 ✅ |
| step_1 check（before ConfigMap） | FAIL（正确：configmap_exists: not found）✅ |
| 执行命令 | `kubectl create configmap app-config --from-literal=APP_ENV=production` |
| step_1 check（after ConfigMap） | PASS ✅ |
| step_2 check（namespace_exists） | PASS ✅ |
| ready_to_complete | True |
| Complete 结果 | LAB_CLOSED，cleanup_verified=True |
| Namespace 残留 | 0（NotFound 确认）✅ |
| Tainted VMs | 0 ✅ |

---

## H. Catalog Verification

| 项目 | 值 |
|------|----|
| Catalog 总数 | 5（不变） |
| Lab 5 可见 | ✅（已 published） |
| Draft/internal labs 不可见 | ✅ |
| Lab 5 title | "Kubernetes ConfigMap 实战：从文章到实验" |
| source_article_id 在 catalog 响应中 | 不暴露 ✅ |
| raw article text | 未持久化 ✅ |

---

## I. Safety Invariants

| 项目 | 值 |
|------|----|
| LabGen pipeline LLM 调用次数 | 0 ✅ |
| 原始文章文本持久化 | 否 ✅ |
| Secret / kubeconfig 泄漏 | 否 ✅ |
| 生产 VMID 500-599 触碰 | 否 ✅（仅 VM 401） |
| 并发未提高 | ✅ |
| Customer pilot 未启动 | ✅ |
| Trusted reader pilot 未启动 | ✅ |
| public article upload 未开放 | ✅ |
| 未直接篡改 data file（绕过 admin update gate） | ✅（全部通过 PATCH 端点） |
| publish_status 未被错误改变 | ✅（仍为 published） |
| article-linked metadata 未丢失 | ✅（source_article_id/rehearsal_required/rehearsal_completed 保留） |
| 新增 placeholder quality gate 不可绕过 | ✅（publish_blocking 级别）|

---

## J. Issue Triage

### BLOCKER
无。

### HIGH
无。

### MEDIUM
无（原 M-01、M-02 已关闭）。

### LOW
- **L-01 [AI tutor 无 per-lab context]**：当前 AI tutor 是通用 K8s 助手，无法感知当前 lab 的步骤、文章背景、正确答案。不阻断 reader pilot，但影响 Guided Practice 体验完整性。
  - 推荐修复：lab session 启动时注入 lab_id/step 上下文到 AI tutor 系统提示。

### NOTE
- **N-01 [VM ownership 仍需手动 staging 配置]**：trusted reader pilot 前需手动分配 VM 归属。
- **N-02 [/etc/labgen/ 路径文档]**：已在 memory 和 docs 中更正，ops runbook §K 中的路径描述待确认。
- **N-03 [step_2 do 字段偏向说明性，非命令式]**：step_2 无需用户执行命令（平台自动验证），已在 do 字段明确说明，不影响功能。

---

## K. Final Decision

**GUIDED_PRACTICE_QUALITY_READY_FOR_TRUSTED_READER**

Lab 5 article-linked lab 从"工程可运行"升级到"读者可体验"。所有 [TODO] 占位已清除，Guided Practice 字段有真实教学内容，reader path 端到端重新验证通过（LAB_CLOSED, cleanup_verified=True, residual=0）。placeholder quality gate 已加入 StaticValidator（publish_blocking 级别），防止未来 stub 内容误发布。

---

## L. Recommended Next Step

**Article-linked Lab Pilot With Trusted Reader**

技术条件已满足，可以邀请第一位 trusted reader（手动分配 VM，提供 Lab 5 CTA 链接）进行真实用户验证。

验证核心问题：
1. 读者是否能无辅助完成 Lab 5？
2. AI tutor 是否能回答步骤相关问题？
3. Guided Practice 内容是否清晰？
4. Cleanup 是否被注意到？

---

## M. Test Coverage

新增 27 个测试（`tests/test_labgen_guided_practice_quality.py`）：

| 类 | 测试数 | 验证内容 |
|----|-------|---------|
| TestPlaceholderQualityGate | 12 | [TODO] 触发 publish_blocking；多字段报告；patched 内容通过 |
| TestAdminPatchIntegrity | 7 | PATCH 保留 publish_status；保留 article-linked 元数据；audit diff；auth 拒绝 |
| TestReaderRegressionAfterPatch | 8 | learner precheck PASS；catalog count=5；draft 不可见；source_article_id 不暴露；step preview 无 TODO；namespace_exists 不需 manual review |

全量结果：3728 passed，93.28% coverage。

---

## N. Modified Files

| 文件 | 变更 |
|------|------|
| `backend/labgen/static_validator.py` | 新增 `_PLACEHOLDER_RE` + `_check_content_no_placeholders()` |
| `tests/test_labgen_guided_practice_quality.py` | 新建，27 个测试 |
| `data/lab_drafts.json` | Lab 5 所有 [TODO] 替换为真实内容（通过 admin PATCH） |
| `CHANGELOG.md` | 新增条目 |
| `deploy/labgen/staging_ops_ticket_status.md` | G-33 新增 |
| `docs/labgen/READER_FACING_ARTICLE_CTA_DRY_RUN_RESULT_v0.1.md` | 旧 MEDIUM 问题状态更新 |
