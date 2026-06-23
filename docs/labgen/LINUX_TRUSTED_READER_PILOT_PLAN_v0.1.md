# Linux Trusted Reader Pilot Plan v0.1

**Status**: PLANNING_READY_WITH_NOTES — awaiting user approval  
**Gate**: Linux Trusted Reader Pilot Planning & Approval Gate  
**Date**: 2026-06-23  
**Prepared by**: Claude Code (senior dev + ops role)  
**Pilot started**: NO  
**User approval**: PENDING_USER_APPROVAL  

---

## A. Pilot Scope

| Item | Value |
|------|-------|
| Lab ID | `6c439064-4cad-4229-addb-36927128d565` |
| Lab title | Linux Files and Permissions Basics |
| Lab domain | linux |
| Reader count | 1 (first run) |
| Account type | Controlled single account (operator-created) |
| Max concurrent sessions | 1 |
| Public signup | NO |
| Customer pilot | NO |
| Broad launch | NO |
| Live LLM | NO — 0 LLM calls enforced |
| Article upload | NO — admin-curated only |
| Second Linux lab | NO |
| Production VMID 500-599 | NOT touched |
| Concurrency raise | NO |

**Restrictions**:
- One lab only: `6c439064`
- One trusted reader only for the first run
- One session at a time
- No K8s runtime changes
- No K8s Lab 5 disruption
- No public CTA (direct deep link only)

---

## B. Reader Criteria

**Trusted reader must satisfy ALL of the following:**

✅ Basic terminal operation: willing and able to copy-paste commands  
✅ Can provide feedback before and after the test  
✅ Understands this is a testing environment, not production  
✅ Will NOT enter real secrets/passwords/tokens  
✅ Will NOT run commands outside the guided steps  
✅ Can accept test window and rollback policy  
✅ Does NOT require production stability guarantees  

**NOT eligible:**
- Paying customers
- Large-scale users
- Ordinary users who are unaware of the testing nature
- Users who require production stability

**Suggested candidates (in priority order):**
1. A developer colleague who has used Linux terminals before
2. A student learner from the existing cohort who has completed K8s labs
3. A technical friend willing to do a 30-min structured test

---

## C. Account Plan

| Item | Value |
|------|-------|
| Account username | `linux-trusted-reader-01` (to be created) |
| Account type | New account (fresh, no prior sessions) |
| Linux lab allowlist | `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` already contains `6c439064-...` |
| VM assignment | VM 401 (staging, home_lab_mvp, 172.16.100.153) — needs ops start + tracker reassignment |
| Max active session | 1 |
| Cleanup expectation | cleanup_verified=True, residual=0 after Complete |
| Rollback flag | `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS=""` disables Linux learner immediately |
| Post-test | Disable account or leave as-is (non-paying, non-customer) |

**Pre-pilot ops actions required:**
1. Start VM 401: `qm start 401`
2. Wait for K3s ready (check kubectl or SSH)
3. Reassign VM 401 tracker ownership to `linux-trusted-reader-01`
4. Create user account `linux-trusted-reader-01` with VM 401 assigned
5. Communicate account credentials to trusted reader via secure channel

**Existing pilot accounts available (do not reuse for new pilot):**
- `pilot_reader` — assigned to VM 401 tracker (will be reassigned)
- `linux-smoke-learner` — used for G-46 smoke
- `linux-cta-dry-run` — used for G-47 dry run

---

## D. Test Flow

Reader executes the following sequence without operator guidance after initial setup:

1. **CTA / Deep Link entry**  
   Open: `https://lab.cloudnetops.tech/labgen-lab.html?labId=6c439064-4cad-4229-addb-36927128d565`  
   (or: login → lab catalog → Linux Files and Permissions Basics)

2. **Lab Detail landing**  
   Reader reads:  
   - Experiment Background (blue card)  
   - Learning Objectives  
   - 4-step preview with check counts  

3. **Start Lab**  
   Click "Start Lab" button  
   Expected: `LAB_ACTIVE`, session created

4. **Execute Step 1**  
   `mkdir -p demo && printf "Hello Linux\n" > demo/message.txt && cat demo/message.txt`  
   Click Check → Expected: all 3 checks pass (directory_exists + file_exists + file_content_matches)

5. **Execute Step 2**  
   `chmod 644 demo/message.txt && cat demo/message.txt`  
   Click Check → Expected: 1 check passes (file_content_matches)

6. **Execute Step 3**  
   `chmod 600 demo/message.txt`  
   Click Check → Expected: 1 check passes (file_mode_matches 600)

7. **Execute Step 4 (completion step)**  
   No commands to run. Click "Complete Lab"  
   Expected: `LAB_CLOSED`, cleanup_verified=True

8. **Confirm completion**  
   Reader sees completion message / cleanup confirmation

9. **Fill feedback form**  
   Reader answers the feedback questions (see Section H)

---

## E. Success Criteria

**ALL of the following must be true for pilot to be declared PASSED:**

| Criterion | Required |
|-----------|----------|
| Reader can reach lab from CTA/deep link | YES |
| Start Lab succeeds (LAB_ACTIVE) | YES |
| Reader can read and understand background/objectives | YES (self-reported) |
| All step commands can be followed without operator intervention | YES |
| Step 1 Check passes (3 verifiers) | YES |
| Step 2 Check passes (1 verifier) | YES |
| Step 3 Check passes (1 verifier) | YES |
| Step 4 Complete succeeds (ready_to_complete=True) | YES |
| LAB_CLOSED state reached | YES |
| cleanup_verified=True | YES |
| residual=0 | YES |
| Reader reports content is understandable | YES (self-reported) |
| No unsafe command accepted | YES |
| No K8s regression | YES (catalog still 6, K8s labs unaffected) |
| LLM call count = 0 | YES |
| Production VMID 500-599 untouched | YES |

---

## F. Failure Criteria

**Any of the following triggers PILOT_FAILED:**

| Failure | Action |
|---------|--------|
| Reader cannot access lab (CTA/login broken) | Abort, record, triage |
| Start Lab fails (precheck error) | Abort, fix, re-plan |
| Step command instructions unclear (reader cannot proceed) | Mark UX_FAIL, triage |
| Check fails despite correct command execution | Mark VERIFIER_FAIL, triage |
| Complete Lab fails | Abort, check logs |
| cleanup_verified=False | Inspect VM, potential taint |
| residual workspace remains | Run manual cleanup, inspect adapter |
| Unsafe command accepted (sudo/su/path escape) | SECURITY_FAIL — immediate halt |
| Internal error leaks stack trace / host path | SECURITY_FAIL — immediate halt |
| Reader needs admin/internal endpoint help | Mark SCOPE_EXCEED |
| K8s lab regression (catalog broken) | REGRESSION_FAIL — halt |
| LLM called (count > 0) | POLICY_FAIL — halt |
| Reader confusion severe enough to abandon | Mark ABANDON, triage UX |

---

## G. Observation Metrics

Operator records the following during/after pilot:

| Metric | Record |
|--------|--------|
| Session ID | UUID from session start response |
| Start timestamp | ISO8601 |
| Complete/abort timestamp | ISO8601 |
| Total duration (minutes) | end - start |
| Step 1 check pass/fail | pass / fail (retry count) |
| Step 2 check pass/fail | pass / fail (retry count) |
| Step 3 check pass/fail | pass / fail (retry count) |
| Step 4 complete outcome | pass / fail |
| Total retry count | integer |
| failure_reason (if any) | from FailureReason enum |
| cleanup_verified | True / False |
| residual | 0 / count |
| User feedback summary | qualitative |
| Operator intervention count | 0 is ideal |
| Unsafe command attempts | 0 is required |
| Post-run audit: active sessions | must be 0 |
| Post-run audit: stale workspaces | must be 0 |
| Post-run audit: tainted VMs | must be 0 |
| Post-run audit: K8s catalog | must be 6 |
| Error logs (journalctl) | any ERR/CRITICAL |
| LLM call count | must be 0 |

---

## H. Feedback Questions

Prepared as a short structured questionnaire for the trusted reader:

1. 你能从文章入口（链接）找到实验吗？（是/否/有困难）
2. 实验背景是否解释清楚了为什么要做这个实验？（清楚/一般/不清楚）
3. 每一步的命令是否容易理解和执行？（容易/一般/有困难）
4. "预期输出"部分是否有帮助？（有帮助/一般/没帮助）
5. "Need help?" 折叠提示是否有用？（有用/没看到/没用）
6. 哪一步最难完成？（填写步骤编号或"都不难"）
7. 是否需要额外的人工帮助才能完成？（是/否——如是，请说明）
8. 完成实验后，你是否理解了 Linux 文件权限的基本概念？（是/部分理解/否）
9. 你愿意继续做类似的实验吗？（愿意/不确定/不愿意）
10. 还有什么其他建议或问题？（开放回答）

---

## I. Safety / Privacy Boundary

| Constraint | Policy |
|------------|--------|
| Real secrets/keys | NOT collected — workspace is ephemeral sandbox |
| Personal file upload | NOT requested |
| Real production environment | NOT used — isolated sandbox VM |
| Arbitrary command targets | NOT exposed — ALLOWED_COMMANDS frozenset enforced |
| Live LLM | NOT enabled — LLM call count = 0 enforced |
| Feedback scope | Records UX experience only, not personal data |
| Raw article text | NOT exposed in learner API |
| Source article ID | NOT exposed in learner API |
| Cleanup after session | Automatic — workspace deleted, cleanup_verified=True |
| Session data retention | data/sessions.json on host — controlled environment |

---

## J. Rollback Plan

**If a serious issue is detected during or after pilot:**

| Step | Action |
|------|--------|
| 1. Disable Linux learner | Set `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS=""` in `.env` + restart service |
| 2. Remove lab from allowlist | Already done by step 1 (env var is the gate) |
| 3. Hide Linux lab (if severe) | `PATCH /api/labgen/drafts/{id}` publish_status=draft (admin) |
| 4. Abort active session (if stuck) | `POST /api/lab-sessions/{id}/abort` or `POST /internal/lab-sessions/{id}/cleanup` |
| 5. Cleanup workspace (if residual) | SSH to VM 401, `rm -rf /tmp/lab-workspace/lab-{session_id}` |
| 6. Verify residual=0 | `ls /tmp/lab-workspace/` must be empty |
| 7. Confirm K8s catalog working | `GET /api/labs` still returns 5 K8s + 0 Linux (if hidden) |
| 8. Record incident | Add to triage doc with severity, root cause, evidence |
| 9. Triage | Classify as BLOCKER/HIGH/MEDIUM/LOW and plan fix |

**VM rollback:**
- VM 401 stopped: `qm stop 401`
- VM 401 rebuild: follow Runbook D.5 from `docs/labgen/HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md`

**Re-enable path:** Fix issue → re-run G-48-equivalent quality check → re-run operator smoke → re-plan pilot.

---

## K. Pre-Pilot Ops Checklist

Before inviting trusted reader, operator must complete:

- [ ] `qm start 401` — start staging K3s VM
- [ ] Verify VM 401 is Running: `qm status 401`
- [ ] SSH to VM 401 and verify K3s ready: `kubectl get nodes`
- [ ] Reassign VM 401 tracker: update `data/vm_creation_times.json` owner to `linux-trusted-reader-01`
- [ ] Create user account: `linux-trusted-reader-01` with `assigned_vm=401`
- [ ] Verify `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` in running service env
- [ ] Run pre-pilot health check (see Approval Gate)
- [ ] Re-initialize verifier credentials for VM 401 (if stale): `initialize_verifier_for_vm(401, ...)`
- [ ] Communicate credentials to reader via secure channel (not via public message)
- [ ] Confirm pilot time window with reader
- [ ] Operator monitoring station ready (tail journalctl, watch session state)

---

## L. Time Window

| Item | Value |
|------|-------|
| Planned window | `[TBD — awaiting user specification]` |
| Duration estimate | 45–90 minutes (reader session + debrief) |
| Operator availability | Required throughout session |
| Rollback window | Immediate (env var + service restart = < 2 min) |
