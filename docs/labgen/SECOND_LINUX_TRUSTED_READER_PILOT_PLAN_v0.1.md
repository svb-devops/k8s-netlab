# Second Linux Trusted Reader Pilot — Plan v0.1

**Document Type**: Planning Document (Preparation Only — NOT Execution Authorization)  
**Gate**: Second Linux Trusted Reader Pilot Planning  
**Date**: 2026-06-23  
**Status**: PLANNING_ONLY — execution requires explicit user approval  
**Prepared by**: Claude Code (senior dev + ops role)  

---

## A. Context

The first Linux Trusted Reader Pilot (G-51) passed technically. The exit review (G-52) identified MEDIUM-001 (no qualitative feedback) and MEDIUM-002 (independence evidence thin). G-53 could not close them programmatically. G-54 resolved MEDIUM-001 via owner onsite attestation and reclassified MEDIUM-002 to LOW.

A second trusted reader is needed before any cohort or expansion is considered. This plan prepares for that second engagement when the user is ready.

---

## B. Scope

| Dimension | Value |
|-----------|-------|
| Reader count | 1 only |
| Lab count | 1 (Linux Files and Permissions Basics, `6c439064`) |
| Domain | Linux (local workspace, `linux-sandbox`) |
| Cohort | NO — single reader only |
| Customer pilot | NO |
| Public launch | NO |
| Live LLM | NO — stub mode only |

---

## C. Rationale

| Reason | Detail |
|--------|--------|
| First reader passed (G-51) | Session `8d9bd8db`, LAB_CLOSED, all 4 steps, cleanup_verified=True |
| Owner onsite feedback positive | "测试非常顺利" — G-54 USER_ONSITE_ATTESTATION |
| Independence not fully instrumented | MEDIUM-002 reclassified to LOW — need second sample for confidence |
| Still need second sample before cohort | Policy: no cohort without ≥2 independent trusted reader passes |
| Feedback capture gap must not repeat | G-53 showed: manual post-session feedback collection failed; must be captured in-band |

---

## D. Reader Requirements

| Requirement | Detail |
|-------------|--------|
| Identity | Provided by user when ready (not pre-assigned in this plan) |
| Has NOT seen the lab before | Must be a first-time reader of this specific lab |
| Technical background | Basic Linux familiarity expected (the lab covers file/permission basics) |
| Independence | Must complete lab without operator coaching during session |
| Not current operator / Claude Code | Reader must be a real external person, not the project owner in disguise |

---

## E. Pre-Pilot Checklist

Before execution, operator must verify:

- [ ] Linux lab `6c439064` still published and is_startable=true
- [ ] Linux feature flag `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` includes `6c439064`
- [ ] Service healthy (`curl https://lab.cloudnetops.tech/api/health`)
- [ ] Active sessions = 0
- [ ] Tainted VMs = {} (though Linux pilot does not use VMs)
- [ ] Reader account created (username + password, not operator account)
- [ ] Reader briefed only on entry URL — no lab content preview
- [ ] Feedback capture method confirmed (see Section F)
- [ ] K8s Lab 5 regression verified (211 tests pass)
- [ ] No BLOCKER/HIGH open

---

## F. Improved Feedback Capture

**Root cause of G-53 gap**: 10-Q form defined in plan but not integrated into completion flow. Manual post-session collection was not performed.

**Required improvement**: Feedback must be captured BEFORE or DURING the pilot, not after.

Two acceptable methods:

### F.1 In-session capture (operator-assisted, preferred)

1. Operator is available (not coaching the reader on commands) during or immediately after session
2. Immediately after reader clicks "Complete", operator asks the 10-Q questions verbally or in writing
3. Responses recorded before reader leaves the session

### F.2 Built-in completion prompt (engineering, optional)

If time allows, integrate a feedback form into the `complete()` flow:
- After reader clicks "Complete" and session moves to LAB_CLOSED
- Platform displays a 10-Q feedback form
- Responses stored as `feedback` field in session record
- Only then does session confirmation show "Lab completed"

Method F.1 is sufficient for second reader pilot without code changes.
Method F.2 is the right long-term solution for scaling.

### 10-Q Feedback Form (for reference)

Adapted from `LINUX_TRUSTED_READER_PILOT_PLAN_v0.1.md`:

| Q# | Question |
|----|----------|
| Q1 | 是否能从文章入口/CTA 顺利找到 Linux 实验？ |
| Q2 | 实验背景是否解释清楚了为什么要做这个实验？ |
| Q3 | 4 个步骤的顺序是否自然？ |
| Q4 | 每一步命令是否清楚、可复制、可执行？ |
| Q5 | 预期输出是否帮助你判断自己做对了？ |
| Q6 | "Need Help?" / troubleshoot 提示是否有帮助？你是否打开过？ |
| Q7 | 哪一步最容易卡顿，为什么？ |
| Q8 | 完成实验时，你是否理解了 Linux 文件、权限和内容的关系？ |
| Q9 | 你是否需要 operator / 我们的人工帮助？如果需要，是在哪一步？ |
| Q10 | 如果这是你第一次使用这个平台，你是否愿意继续做类似实验？有什么建议？ |

Closure requirement: ≥8/10 questions answered with substantive responses.

---

## G. Success Criteria

| Criterion | Required |
|-----------|----------|
| Lab session reaches LAB_CLOSED | ✅ Required |
| cleanup_verified = True | ✅ Required |
| All 4 steps completed | ✅ Required |
| residual = 0 | ✅ Required |
| 10-Q feedback captured (≥8/10 answered) | ✅ Required — not optional |
| Independence confirmed (no operator coaching during session) | ✅ Required |
| Active sessions = 0 post-run | ✅ Required |
| Tainted VMs = {} post-run | ✅ Required |
| K8s Lab 5 unaffected | ✅ Required |
| LLM calls = 0 | ✅ Required |
| VMID 500-599 untouched | ✅ Required |

---

## H. What Second Reader Pilot DOES NOT Authorize

| Action | Authorized? |
|--------|-------------|
| Small cohort start | ❌ No — second reader must pass first |
| Customer pilot | ❌ No |
| Public launch | ❌ No |
| Publishing a second Linux lab | ❌ No |
| Adding a third domain | ❌ No |
| Increasing concurrency | ❌ No |
| Live LLM | ❌ No |

---

## I. Next Gate

After second trusted reader pilot execution:

- **If PASS + feedback captured + independence confirmed**:
  → Second Linux Trusted Reader Pilot Exit Review
  → If exit clean → Small Dual-domain Trusted Reader Cohort Planning is unblocked

- **If FAIL or feedback not captured**:
  → Hold Expansion — diagnose and iterate before cohort

---

## J. Requirements for Execution

This plan is not yet authorized for execution.

User must explicitly provide:
1. Reader identity (name or handle)
2. Test window (date + time slot)
3. Explicit YES to invite this reader

Claude Code will NOT invite reader or create account until user approves.

---

## K. Feedback capture note: Do not repeat G-53

G-53 failed because:
- 10-Q form was defined in plan but collection was never performed
- Claude Code cannot contact humans after-the-fact
- Session data has no feedback fields

For second reader:
- Operator MUST be available to capture 10-Q during or immediately after session
- OR feedback integration in platform must be implemented before pilot starts
- Do NOT proceed to post-session collection planning — capture it live
