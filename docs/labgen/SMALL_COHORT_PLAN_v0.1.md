# Small Cohort Plan v0.1

**Date**: 2026-06-25
**Operator**: Claude Code — senior dev + ops
**Status**: AWAITING_OWNER_APPROVAL
**No real secrets in this document.**

---

## A. Cohort Scope

| 项目 | 说明 |
|------|------|
| 规模 | 3–5 人 |
| 类型 | trusted learners / trusted readers（技术从业者，首次使用本系统） |
| 入口 | 真实文章页面 CTA |
| 实验 | 仅使用已 published labs |
| 并发 | 默认不提高并发（系统 max active sessions = 1/user） |

**推荐方案：Option A — 保守 lab 小组**

所有 3–5 名 learner 均从同一篇文章 CTA 进入同一个 Linux lab，验证同一闭环的 repeatability。

---

## B. Article / Lab Assignment

| 字段 | 值 |
|------|----|
| 文章 slug | `linux-files-permissions-basics` |
| 文章 URL | `https://lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics` |
| 文章标题 | Linux 文件与权限基础：创建、查看并修改权限 |
| article_channel | `official_site` |
| lab_id | `6c439064-4cad-4229-addb-36927128d565` |
| lab 标题 | Linux Files and Permissions Basics |
| cta_enabled | True |
| 步骤数 | 4（lfp-step-1 / lfp-step-2 / lfp-step-3 / lfp-step-4） |
| 预计耗时 | 约 20 分钟 |

---

## C. Execution Mode

| 项目 | 说明 |
|------|------|
| 模式 | 错峰（staggered）——每次 1 人，各自独立完成 |
| 时间窗口 | 由 owner 在 approval gate 中提供 |
| 并发 | 不提高，默认 max 1 active session/user |
| operator 在场 | 由 owner 决定（onsite 或 remote 均可） |

---

## D. Account Plan

| 项目 | 规则 |
|------|------|
| 账号模式 | 每位 learner 独立账号 |
| username 规则 | 格式建议：`cohort-<handle>`（如 cohort-alice） |
| email | 必填（G-62 email registration 已实现） |
| 密码 | operator 预设，通过安全渠道传递给 learner；不得写入本文档 |
| 权限 | learner only；无 admin；无 draft/internal 访问 |
| 账号何时创建 | **仅在 owner 提供 approval gate 所需的 learner identities + test window + 明确 YES 后** |
| cohort 后账号处置 | 由 owner 决定（保留或禁用）；Claude Code 不自行决定 |

---

## E. Staggered Execution Plan

推荐执行顺序（owner 可调整）：

```
Day 1: Learner 1
  - Operator 提前创建账号，通过安全渠道分发
  - Learner 从文章页面阅读 → 点击 CTA → 注册/登录 → Start Lab
  - 完成 4 个步骤 → Complete → cleanup_verified=True
  - 立即收集 10-Q 反馈

Day 1-2: Learner 2（Learner 1 完成后再开始）
  同上流程

Day 2-3: Learner 3–5（错峰）
  同上流程
```

**严格约束**：
- 不同时运行多个 learner（同一时间段内只有 1 人活跃）
- 每位 learner 完成并 cleanup_verified=True 后再开始下一位
- 任何 BLOCKER 立即停止 cohort

---

## F. Feedback Capture Plan

### 系统自动记录（session 数据）

| 指标 | 来源 |
|------|------|
| learner_id | `student_username` |
| article_slug | `linux-files-permissions-basics` |
| lab_id | `6c439064` |
| session_id | `LabSessionState.session_id` |
| start_time | `started_at` |
| complete_time | `ended_at` |
| duration | `ended_at - started_at` |
| step pass/fail | `completed_step_ids` / `last_verify_results` |
| cleanup_verified | `cleanup_verified` |
| residual | post-run audit（active sessions = 0, tainted_vms = {}）|

### operator 需手动记录

| 指标 | 方式 |
|------|------|
| retry count | operator 观察 step check 调用次数 |
| operator intervention count | operator 记录 |
| Need Help usage | frontend "需要帮助" 点击 |

### 10-Q 反馈表（每位 learner 在 Complete 后立即填写）

1. 你是否能顺利从文章找到实验入口？
2. CTA 按钮文案是否清楚？
3. 注册 / 登录是否顺利？
4. 实验背景是否解释清楚了为什么要做？
5. 步骤是否清楚？
6. 命令是否容易复制 / 执行？
7. Check 反馈是否帮助你判断进度？
8. 哪一步最困难？
9. 是否需要人工帮助？（需要哪一步？）
10. 是否愿意继续做类似实验？为什么？

**规定**：
- feedback 在 Complete 后立即通过 operator 指定渠道收集
- 不得事后追补
- 缺少 feedback 的 learner 不计入完整 product validation 样本

---

## G. Success Criteria

| 标准 | 阈值 |
|------|------|
| 所有 learner 能打开文章页面 | 100% |
| 所有 learner 能看到 CTA | 100% |
| 所有 learner 能注册 / 登录 | 100% |
| Start 成功率 | ≥ 80% |
| Complete 成功率 | ≥ 80% |
| completed sessions: cleanup_verified=True | 100% |
| completed sessions: residual=0 | 100% |
| cohort 结束后 active sessions = 0 | 100% |
| taint state clean | 100% |
| 无 raw article text 暴露 | 100% |
| 无 source_article_id 暴露 | 100% |
| 无 email / password_hash 暴露 | 100% |
| 无 public upload route | 100% |
| 无 live LLM 调用 | 100% |
| 无 URL scraping | 100% |
| 无 production VMID 500-599 触碰 | 100% |
| 每位 learner 有 feedback | 100% |
| 无 BLOCKER / HIGH | 100% |
| MEDIUM 有 remediation plan | 100% |

---

## H. Failure Criteria

### BLOCKER（立即停止 cohort）

- 文章页面 CTA 不显示
- CTA 指向错误 lab
- 注册 / 登录普遍失败
- Start 普遍失败
- Check 错误 PASS / FAIL
- Complete 失败
- cleanup failure（cleanup_verified=False）
- residual remains（活跃 K8s 资源残留）
- draft / internal lab 暴露
- source_article_id / raw article / password_hash 泄露
- public upload route 出现
- live LLM 被调用
- URL scraping 被触发
- production VMID 500-599 被触碰

### HIGH（停止后续 learner 直到修复）

- 多位 learner 无法理解 CTA
- 多位 learner 无法独立完成
- 多位 learner 需要 operator 才能继续
- feedback 缺失导致无法处理
- registration redirect 丢失 lab target
- Need Help 明显不足

### MEDIUM（记录并有 remediation plan，不停止 cohort）

- 单个步骤文案造成困惑
- CTA 文案不够清楚
- registration form 文案不够清楚
- completion summary 不够清楚
- operator runbook 不够清楚

### LOW

- UI polish
- 文案微调
- 样式问题

### NOTE

- 无危害的观察记录

---

## I. Rollback Plan

出现 BLOCKER 时立即执行：

1. 停止 cohort，不继续通知剩余 learner
2. 禁用或移除 cohort learner 账号
3. `POST /api/lab-sessions/{id}/abort` 中止所有 active sessions
4. 验证 cleanup：active sessions = 0, tainted_vms = {}, residual = 0
5. 如 lab / article 绑定错误，通过 admin PATCH 关闭 cta_enabled
6. catalog 保持稳定（不回滚 published labs）
7. 记录 incident（时间、触发条件、执行步骤、结论）
8. 不触碰 production VMID 500-599

---

## J. Operator Runbook Outline

### 准备（cohort 启动前）

1. 运行 readiness checks（article reachable, CTA present, lab published, active=0, residual=0, tainted={}）
2. 逐位创建 learner 账号（仅在 owner YES 后）
3. 通过安全渠道分发账号凭证（username + initial password）
4. 告知 learner：从文章 CTA 进入；勿跳过步骤；Complete 后立即填写反馈

### 每位 learner 执行中

1. 确认 learner 已开始（Start Lab → LAB_ACTIVE）
2. 不主动干预（观察即可）
3. 记录 retry count / Need Help 使用情况
4. 如出现 BLOCKER → 立即停止

### 每位 learner 完成后

1. 确认 cleanup_verified=True, residual=0
2. 收集 10-Q feedback（不得跳过）
3. 检查 error logs：`journalctl -u k8s-netlab -p err --since "10 minutes ago"`
4. 确认 active sessions = 0, tainted_vms = {} 后再允许下一位 learner 开始

### cohort 结束后

1. 验证所有 sessions LAB_CLOSED
2. 运行 post-run audit（active=0, tainted={}, residual=0, health OK）
3. 整理 feedback，分析 10-Q
4. 记录结论到 SMALL_COHORT_EXECUTION_RESULT_v0.1.md（下一任务）

---

*No real secrets in this document. Account credentials are transmitted via secure channel, never written here.*
