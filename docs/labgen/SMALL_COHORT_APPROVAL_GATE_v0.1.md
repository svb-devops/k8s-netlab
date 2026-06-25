# Small Cohort Approval Gate v0.1

**Date**: 2026-06-25
**Operator**: Claude Code — senior dev + ops
**Status**: AWAITING_OWNER_INPUT
**No real secrets in this document.**

---

## A. Purpose

本文件定义 Small Cohort Execution 的 owner 审批边界。

**任何下列操作在收到明确 YES 之前绝对禁止**：
- 创建 cohort learner 账号
- 邀请 learner
- 启动 cohort execution
- 向任何人分发实验链接

---

## B. Owner 必须提供的输入

请填写以下内容后回复 operator：

```yaml
small_cohort:
  cohort_size:                        # 数字，3–5
  learner_identities:
    - name_or_handle:                 # 可用 handle / 昵称，不需要真实姓名
      contact_channel:                # 如何联系（微信 / 邮件 / 电话）
      technical_background:           # 简述（如：Linux 基础用户 / 运维从业者）
    - name_or_handle:
      contact_channel:
      technical_background:
    # ... 重复至 cohort_size 条

  test_window:
    date:                             # 格式：YYYY-MM-DD
    start_time:                       # 格式：HH:MM（24h）
    expected_duration:                # 如：每人约 30 分钟，全组预计 2 天
    timezone:                         # 如：UTC+8

  lab_assignment:
    article_slug: linux-files-permissions-basics
    lab_id: 6c439064-4cad-4229-addb-36927128d565

  execution_mode:
    staggered_or_parallel: staggered  # 推荐 staggered；如选 parallel 请说明理由

  operator_presence:
    onsite_or_remote:                 # operator 是否在线陪同

  explicit_approval: |
    YES, approve Small Cohort Execution.
```

---

## C. 约束声明

**收到明确 YES 前，Claude Code 绝对不会**：

| 操作 | 约束 |
|------|------|
| 创建 cohort 账号 | 禁止 |
| 邀请 learner | 禁止 |
| 启动 cohort execution | 禁止 |
| 提高系统并发 | 禁止 |
| 发布新 lab | 禁止 |
| 开放普通用户上传文章 | 禁止 |
| 启用 live LLM | 禁止 |
| 启动 customer pilot | 禁止 |
| public launch | 禁止 |
| 触碰 production VMID 500-599 | 禁止 |

**需要 owner 提供但缺失的情况**：

- 若 learner identities 缺失 → final decision 可以是 `SMALL_COHORT_PLANNING_READY_WITH_NOTES`，但下一步必须等待 owner input，不得开始任何 execution
- 若 test window 缺失 → 同上
- 若 YES 明确表述缺失 → 不得开始

---

## D. 明确 YES 的格式

只接受以下格式的明确批准（字面量）：

```
YES, approve Small Cohort Execution.
```

不接受：
- "可以"、"同意"、"ok"、"proceed"
- 模糊表述
- 省略 learner identities 或 test window 的批准

---

## E. 批准后下一步

Owner 提供完整 input + 明确 YES 后，Claude Code 将：

1. 确认 readiness checks 全部 PASS（article, CTA, lab, sessions, residual, taint, health）
2. 逐位创建 learner 账号（按 account plan）
3. 将账号凭证通过 owner 指定的安全渠道传递
4. 按 staggered 计划启动 cohort execution
5. 执行完毕后生成 `SMALL_COHORT_EXECUTION_RESULT_v0.1.md`

---

## F. Owner Input 接收记录

**当前状态**: ⏳ 等待 owner 提供

| 字段 | 状态 |
|------|------|
| cohort_size | ⏳ 待提供 |
| learner_identities | ⏳ 待提供 |
| test_window | ⏳ 待提供 |
| lab_assignment | ✅ 已确定（linux-files-permissions-basics → 6c439064）|
| execution_mode | ✅ 推荐 staggered |
| explicit_approval YES | ⏳ 待提供 |

---

*This gate document contains no real credentials, no learner PII, and no account passwords.*
*All credentials will be transmitted via secure channel after owner approval, never written in this file.*
