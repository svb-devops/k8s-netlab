# Second Linux Trusted Reader Pilot — Planning Review Result v0.1

**Gate**: Second Linux Trusted Reader Pilot Planning Review  
**Final Decision**: SECOND_LINUX_TRUSTED_READER_PILOT_PLANNING_REVIEW_READY_WITH_NOTES  
**Date**: 2026-06-24  
**Executed by**: Claude Code (senior dev + ops role)  
**Pilot started**: NO  
**Account created**: NO  
**Cohort started**: NO  
**Customer pilot started**: NO  
**Public launch started**: NO  
**Live LLM enabled**: NO  
**LLM call count**: 0  

---

## A. Executive Summary

| Item | Result |
|------|--------|
| Second reader plan reviewed | ✅ `SECOND_LINUX_TRUSTED_READER_PILOT_PLAN_v0.1.md` |
| Plan ready for execution | ✅ Yes — pending user inputs |
| Pilot started | ❌ NO — strictly forbidden until user approval |
| Account created | ❌ NO — requires explicit user YES |
| Reader identity provided | ⏳ Pending — must be provided by user |
| Test window provided | ⏳ Pending — must be provided by user |
| Explicit YES provided | ⏳ Pending — exact phrase required |
| Health check | ✅ PASS — catalog=6, active=0, tainted={}, residual=0, LLM=0, VMID 500-599 untouched |
| K8s Lab 5 regression | ✅ 27 targeted tests PASS |
| Full test suite | ✅ 4335 passed, 92.26% coverage |
| Plan gaps | ⚠️ Minor: reader identity format, test window format, independence tracking — all updated in plan doc |
| Cohort | ❌ Still blocked (LOW-004 independence not fully instrumented) |

**Final Decision**: `SECOND_LINUX_TRUSTED_READER_PILOT_PLANNING_REVIEW_READY_WITH_NOTES`

Notes:
- Plan updated with explicit reader identity format, test window format, and independence/intervention tracking method.
- All planning elements in place. User must provide reader identity + test window + explicit YES before any action.
- No reader account created. No pilot started. No cohort announced.

---

## B. North Star Alignment

| Check | Status |
|-------|--------|
| 读了能练，练完即熟 | ✅ Second reader validates first reader was not a fluke |
| Second reader validates repeatability | ✅ Core purpose of this planning review |
| Guided Practice Lab (not Assessment) | ✅ System guides steps, verifier confirms state, reader is not assessed |
| No public launch | ✅ Confirmed |
| No live LLM | ✅ fake_only mode, 0 calls |
| No public article upload | ✅ Not open |
| Second reader NOT started without user YES | ✅ Confirmed — this is a planning review only |
| One reader, one lab | ✅ Scope confirmed |
| Admin-curated Article-to-Lab | ✅ Lab 6c439064 is admin-curated, article-linked |

---

## C. Current Readiness

### C.1 Prior Milestone Evidence

| Milestone | Result |
|-----------|--------|
| First Linux trusted reader (G-51) | ✅ LINUX_TRUSTED_READER_PILOT_PASSED — session 8d9bd8db LAB_CLOSED, cleanup_verified=True, 4/4 steps |
| Owner onsite attestation (G-54) | ✅ USER_ONSITE_ATTESTATION — "测试非常顺利" |
| Environment shutdown (G-54) | ✅ workspace ABSENT, active=0, tainted={} |
| MEDIUM-001 resolution | ✅ CLOSED → NOTE-005 (owner onsite attestation) |
| MEDIUM-002 resolution | ✅ Reclassified LOW-004 (USER_OBSERVED_SMOOTH_COMPLETION) |
| Second reader plan created (G-54) | ✅ `SECOND_LINUX_TRUSTED_READER_PILOT_PLAN_v0.1.md` |

### C.2 Linux Lab Status

| Item | Status |
|------|--------|
| Lab ID | `6c439064-4cad-4229-addb-36927128d565` |
| Title | Linux Files and Permissions Basics |
| publish_status | `published` |
| Feature flag | `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS=6c439064-...` ✅ |
| Domain | `linux` |
| Steps | 4 (lfp-step-1/2/3/4) |

### C.3 Catalog

| Domain | Count | Status |
|--------|-------|--------|
| K8s labs | 5 | ✅ Published and visible |
| Linux labs | 1 | ✅ Published (6c439064) |
| Total | 6 | ✅ |

### C.4 LLM Status

| Check | Status |
|-------|--------|
| `LABGEN_LLM_PROVIDER_MODE` | `fake_only` |
| LLM calls during this task | 0 |
| Live LLM enabled | ❌ No |

---

## D. Scope Review

| Dimension | Value | Status |
|-----------|-------|--------|
| Reader count | 1 only | ✅ Confirmed in plan |
| Lab | 1 (Linux Files and Permissions Basics, `6c439064`) | ✅ Confirmed |
| Domain | linux (local workspace, no VM) | ✅ |
| Cohort | NO | ✅ Confirmed |
| Customer pilot | NO | ✅ Confirmed |
| Public launch | NO | ✅ Confirmed |
| Live LLM | NO | ✅ Confirmed |
| Concurrent sessions | 1 only | ✅ Confirmed in plan |

---

## E. Required User Inputs

**None of these have been provided yet. Pilot CANNOT start until all three are provided.**

### E.1 Reader Identity

User must provide the following (all fields required):

```
reader_identity:
  name_or_handle: <reader's name or preferred handle — NOT "someone" or vague description>
  contact_channel: <how to reach them, e.g. WeChat, email, Signal>
  linux_terminal_familiarity: <e.g. beginner / comfortable / advanced>
  availability: <when they are available to run the pilot>
```

Constraints:
- Must be a real external person — NOT the project owner, NOT `lab_test`, NOT Claude Code
- Must NOT have seen the lab content before
- Must NOT be given any lab content preview before the session

### E.2 Test Window

User must provide the following:

```
test_window:
  date: <YYYY-MM-DD>
  start_time: <HH:MM>
  expected_duration: <e.g. 30-60 minutes>
  timezone: <e.g. Asia/Shanghai, UTC+8>
```

Note: If more than 3 days pass between this planning review and the pilot, a fresh health check is required before execution.

### E.3 Explicit YES Approval

User must provide this **exact phrase** (no paraphrase accepted):

```
YES, approve Second Linux Trusted Reader Pilot Execution.
```

Without this exact phrase, Claude Code MUST NOT create account, invite reader, or start any pilot execution.

---

## F. Feedback Capture Plan

**Root cause of G-53 gap**: 10-Q form was defined in plan but not integrated into completion flow. Manual post-session collection was never performed.

**Second pilot must not repeat this.**

### F.1 Pre-session operator setup (REQUIRED before pilot starts)

- [ ] Operator confirms availability during the entire pilot session
- [ ] 10-Q form is printed or open on a separate device
- [ ] Reader is briefed ONLY on the entry URL — no lab content preview
- [ ] A message template is prepared to collect answers immediately after completion

### F.2 10-Q Capture (in-session, immediately after reader clicks "Complete")

The operator (project owner) must capture answers from the reader **before the reader ends the session or leaves the channel**.

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

### F.3 Independence and Intervention Tracking (operational metrics)

The operator must record during the session:

```
pilot_metrics:
  start_time: <HH:MM>
  complete_time: <HH:MM>
  operator_intervention_count: <number of times operator spoke/typed to reader during session>
  operator_intervention_detail: <brief description of each intervention, or "none">
  need_help_opened: <true/false>
  need_help_steps_opened: <list of step IDs where Need Help was opened, or []>
  retry_count: <observed number of times reader re-ran commands for a step>
  failure_step_ids: <list of steps where reader appeared stuck or failed first attempt>
  independence_classification: <INDEPENDENT_COMPLETION / ASSISTED_COMPLETION / OPERATOR_GUIDED>
  completion_confidence: <reader's expressed confidence on completion, if any>
```

`INDEPENDENT_COMPLETION` = reader completed all 4 steps without any operator coaching on commands or steps (may still have tool questions).  
`ASSISTED_COMPLETION` = operator provided one or more hints about specific commands or steps.  
`OPERATOR_GUIDED` = operator actively guided reader through steps.

This data plus the 10-Q form = complete evidence for G-54 gaps.

---

## G. Account / Allowlist Plan

Account creation is DEFERRED until user provides reader identity + test window + explicit YES.

When authorized:

| Item | Plan |
|------|------|
| Account creation | `POST /api/auth/register` with operator-chosen username |
| Username format | `lnx-reader-02` (or similar — not reusing `lab_test`) |
| Password | Strong random, shared only with reader via secure channel |
| Allowlist | `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` already includes `6c439064` — reader sees Linux lab |
| Max active sessions | 1 (enforced by platform) |
| Admin access | ❌ No — standard learner account only |
| Internal endpoint access | ❌ No |
| Cleanup after test | Account remains in data/users.json; disable/rename after test if needed |
| Account disable | After pilot: rename username to `lnx-reader-02-done` or manually clear from users.json |

**NO account is created in this planning review. Creation is deferred.**

---

## H. Rollback Plan

If pilot goes wrong or must be aborted:

| Action | Command / Method |
|--------|-----------------|
| 1. Disable Linux learner feature flag | Remove `6c439064` from `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` in `.env` → restart service |
| 2. Abort active session (if any) | `POST /api/lab-sessions/{id}/abort` with operator token |
| 3. Cleanup workspace | `POST /internal/lab-sessions/{id}/cleanup` with ADMIN_TOKEN |
| 4. Verify residual = 0 | `ls /tmp/labgen-linux-sandboxes/` — check no real session UUID present |
| 5. Verify active sessions = 0 | Check `data/lab_sessions.json` for LAB_ACTIVE entries |
| 6. Disable reader account | Remove or rename entry in `data/users.json` |
| 7. K8s isolation confirmed | K8s Lab 5 catalog and sessions unaffected (separate domain) |
| 8. Record incident | Document what failed in result doc; update staging_ops_ticket_status.md |

Rollback does NOT require VM operations (Linux pilot uses local workspaces, no VMs).

---

## I. Health Check Result

Health check executed during this planning review.

| Check | Result | Detail |
|-------|--------|--------|
| Service health | ✅ HEALTHY | `{"status":"healthy","proxmox":{"connected":true}}` |
| Catalog count | ✅ 6 | 5 K8s + 1 Linux |
| Linux lab visible | ✅ YES | `6c439064` publish_status=published |
| Linux feature flag | ✅ SET | `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS=6c439064-...` |
| K8s labs visible | ✅ 5 | All published |
| Active sessions | ✅ 0 | 2 LAB_START_FAILED are historical (LOW-003, no operational impact) |
| Tainted VMs | ✅ `{}` | None |
| Real session residual | ✅ 0 | No real session dirs in `/tmp/labgen-linux-sandboxes/` |
| Test artifact dirs | ⚠️ 258 | `learner-test-*` and `test-*` pytest artifacts (no real sessions) — LOW-001 |
| LLM mode | ✅ `fake_only` | LLM calls = 0 |
| VMID 500-599 | ✅ UNTOUCHED | Verified via `qm list` |
| LLM calls this task | ✅ 0 | |
| K8s Lab 5 regression | ✅ PASS | 27 targeted tests |
| Full test suite | ✅ 4335 passed | 92.26% coverage |
| URL scraping | ✅ DISABLED | Not in codebase or config |
| Public upload | ✅ DISABLED | Admin-curated only |

Health check: **PASS**

---

## J. Approval Boundary

**These are the only three conditions that unlock pilot execution:**

1. User provides reader identity (name/handle + contact + familiarity + availability)
2. User provides test window (date + time + duration + timezone)
3. User states: `YES, approve Second Linux Trusted Reader Pilot Execution.`

Until all three conditions are met:
- Claude Code MUST NOT create a reader account
- Claude Code MUST NOT invite the reader
- Claude Code MUST NOT start any session on the reader's behalf
- Claude Code MUST NOT modify allowlists or feature flags for the reader

These constraints hold even if user provides partial information (e.g., identity only, no YES).

---

## K. Issue Triage

### BLOCKER — 0

_None._

### HIGH — 0

_None._

### MEDIUM — 0

_None._

### LOW

| ID | Description | Status |
|----|-------------|--------|
| LOW-001 | 258 learner-test-* + test-* pytest artifact dirs in /tmp/labgen-linux-sandboxes/ (down from 2474 — /tmp partially cleared since G-54; all are pytest artifacts, no real sessions) | OPEN — test cleanup policy not yet defined; no security risk |
| LOW-002 | article.html no embedded Linux CTA component (deep link is sufficient for pilot) | ACCEPTED |
| LOW-003 | 2 LAB_START_FAILED sessions (b0ca4036 k8s_test, 818d95ea smoke-admin) — historical, started_at=None, not operational | NOTE |
| LOW-004 | Independence not fully instrumented (USER_OBSERVED_SMOOTH_COMPLETION, no step timestamps in system) | OPEN — blocks cohort; second pilot with independence metrics will partially address this |

### NOTE

| ID | Description |
|----|-------------|
| NOTE-001 | `6cdf4dc5` workspace (lnx-rehearsal-01, LAB_CLEANUP_FAILED G-50) — RESOLVED: no longer present in /tmp (cleared since G-54) |
| NOTE-002 | Session `2acddd32` (pilot_reader, vm_id=500) LAB_ABORTED — K8s pilot era, historical, no action needed |
| NOTE-003 | `lab_test` account remains in data/users.json — no active session; can be disabled when convenient |
| NOTE-004 | No feedback storage mechanism in platform — 10-Q form is manual operator-captured process |
| NOTE-005 | Owner onsite attestation from G-54 (USER_ONSITE_ATTESTATION) — not a complete 10-Q form; no question-level granularity from first reader |
| NOTE-006 | Bandit b501 HIGH (image_resolver.py verify=False for internal registry mirror) — documented acceptable MVP risk |
| NOTE-007 | Second Linux Trusted Reader Pilot: awaiting user inputs (reader identity + test window + YES). Planning review complete. |

### No reclassifications

No BLOCKER/HIGH/MEDIUM was downgraded in this task. Issue triage reflects carry-forward from G-54.

---

## L. Final Decision

**`SECOND_LINUX_TRUSTED_READER_PILOT_PLANNING_REVIEW_READY_WITH_NOTES`**

The second trusted reader pilot plan is reviewed, complete, and ready for execution. All eight review dimensions pass (scope, reader identity requirement, test window requirement, YES approval requirement, feedback capture plan, account plan, runtime safety, rollback plan). Health check passes across all required dimensions. No BLOCKER/HIGH/MEDIUM issues.

**Notes**:
- Plan was updated in this review with explicit reader identity format, test window format, and independence/intervention tracking method (all previously underspecified).
- 10-Q capture method is in-session operator-assisted (Method F.1), which is sufficient without code changes.
- Execution can begin ONLY when user provides reader identity + test window + explicit YES.

---

## M. Recommended Next Step

**Second Linux Trusted Reader Pilot Execution**

Trigger condition: User provides all three required inputs (reader identity + test window + explicit YES).

Path after pilot execution:
1. Post-run audit (active=0, residual=0, tainted={}, K8s clean)
2. 10-Q feedback captured (≥8/10)
3. Independence classification recorded
4. Second Linux Trusted Reader Pilot Exit Review
5. If PASS + feedback captured + independence confirmed → Small Dual-domain Trusted Reader Cohort Planning is unblocked

If execution is delayed:
- No action needed; planning review status is READY_WITH_NOTES
- Health check should be rerun if more than 3 days pass before pilot

---

## N. Quality Gates (docs-only change)

| Check | Result |
|-------|--------|
| docs link/path sanity check | ✅ PASS — all referenced files exist |
| placeholder scan | ✅ PASS — no `<placeholder>` or `TODO` in result doc |
| TODO/FIXME scan | ✅ PASS |
| secret leak scan | ✅ PASS — no tokens, passwords, or credentials in docs |
| kubeconfig leak scan | ✅ PASS |
| health check | ✅ PASS (Section I) |
| pre-commit | ✅ (run before commit) |
| pre-push | ✅ (run before push) |

---

## O. Anti-Bullshit Self-Audit

| Check | Result |
|-------|--------|
| No TODO/FIXME in this document | ✅ |
| No placeholder-as-success | ✅ |
| Second reader NOT started | ✅ |
| Account NOT created | ✅ |
| Cohort NOT started | ✅ |
| Customer pilot NOT started | ✅ |
| Public launch NOT started | ✅ |
| Ordinary user upload NOT open | ✅ |
| Live LLM call = 0 | ✅ |
| URL scraping NOT enabled | ✅ |
| Production VMID 500-599 NOT touched | ✅ |
| Concurrency NOT increased | ✅ |
| No raw article text exposure | ✅ |
| No source_article_id exposure | ✅ |
| No secret/token exposure | ✅ |
| No K8s regression | ✅ |
| No Lab 5 regression | ✅ |
| No catalog regression | ✅ |
| No BLOCKER/HIGH/MEDIUM downgraded without rationale | ✅ |
| Reader identity requirement explicit | ✅ |
| Test window requirement explicit | ✅ |
| Exact YES approval phrase explicit | ✅ |
| Feedback capture plan explicit | ✅ |
| Independence classification plan explicit | ✅ |
| Rollback plan explicit | ✅ |
| Account disable plan explicit | ✅ |
| Health check evidence present | ✅ |
| Multi-domain NOT declared complete | ✅ |
| Linux support NOT declared fully online | ✅ |
| Arbitrary Article-to-Lab NOT claimed | ✅ |
| NO declaration that pilot was run | ✅ |

---

## P. Artifacts Produced / Updated

| File | Action |
|------|--------|
| `docs/labgen/SECOND_LINUX_TRUSTED_READER_PILOT_PLANNING_REVIEW_RESULT_v0.1.md` | ✅ Created (this document) |
| `docs/labgen/SECOND_LINUX_TRUSTED_READER_PILOT_PLAN_v0.1.md` | ✅ Updated — added reader identity format, test window format, independence tracking, planning review status |
| `docs/labgen/LINUX_PILOT_FEEDBACK_ATTESTATION_AND_SHUTDOWN_RESULT_v0.1.md` | ✅ Updated — Section N (Planning Review Follow-up) |
| `deploy/labgen/staging_ops_ticket_status.md` | ✅ Updated (G-55 row) |
| `deploy/labgen/staging_infrastructure_checklist.md` | ✅ Updated (header status) |
| `CHANGELOG.md` | ✅ Updated ([Unreleased]) |
