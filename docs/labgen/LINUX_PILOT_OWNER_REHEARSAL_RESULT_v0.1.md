# Linux Pilot Owner Rehearsal — Result v0.1

**Gate**: Linux Pilot Owner Full Rehearsal  
**Final Decision**: LINUX_PILOT_OWNER_REHEARSAL_READY_FOR_USER  
**Date**: 2026-06-23  
**Executed by**: Claude Code (senior dev + ops role)  
**Real trusted reader invited**: NO  
**Real pilot started**: NO  
**LLM calls**: 0  

---

## A. Executive Summary

| Item | Result |
|------|--------|
| VM 401 started | YES — running (STOPPED → running) |
| VM tracker owner fixed | YES — `pilot_reader` → `lnx-rehearsal-01` |
| Owner rehearsal account ready | YES — `lnx-rehearsal-01` / `LinuxRehearsal@2026` |
| Test steps document ready | YES — `docs/labgen/LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md` |
| Health check PASS | YES — all 12 checks pass |
| Negative checks PASS | YES — unsafe commands/paths all rejected |
| K8s Lab 5 regression | NONE |
| Service restarted (G-48 code loaded) | YES — experiment_background + check_count now correct |
| Real trusted reader invited | **NO — strictly prohibited** |
| Real pilot started | **NO — awaiting owner rehearsal completion + user approval** |
| User may now start owner rehearsal | **YES** |

**Final decision**: `LINUX_PILOT_OWNER_REHEARSAL_READY_FOR_USER`

Owner may follow `docs/labgen/LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md` to complete the rehearsal.  
**Real trusted reader pilot will NOT start until owner rehearsal passes and user provides explicit YES approval.**

> **BLOCKER resolved (2026-06-23, post-result)**: Linux learner terminal showed `credential_error` because
> `lab_kubectl_ws.py` routed all sessions through the K8s kubeconfig path. Fix: Linux sessions
> (`vm_id='linux-sandbox'`) now route to `_handle_linux_terminal()` which uses `LinuxRuntimeAdapter`
> for policy-enforced local command execution with `>` redirection support.
> 24 regression tests added. Full suite: 4335 passed, 92.26% coverage. Service restarted.

---

## B. North Star Alignment

| Check | Status |
|-------|--------|
| 读了能练，练完即熟 | ✅ Linux article CTA → lab → complete = core mission |
| Owner rehearsal before real pilot | ✅ Confirmed — this task is prep only |
| Guided Practice Lab (not Assessment) | ✅ Reader follows guided steps, system verifies state |
| No public launch | ✅ Confirmed |
| No live LLM | ✅ 0 LLM calls enforced |
| No public article upload | ✅ Not available |
| K8s domain proof preserved | ✅ K8s Lab 5 unaffected |
| Cleanup contract intact | ✅ cleanup_verified=True enforced |

---

## C. Ops Pre-action Results

### C.1 VM 401

| Item | Before | After |
|------|--------|-------|
| Status | STOPPED | running |
| IP | 172.16.100.90 | same |
| K3s nodes | unknown | Ready (k8s-template v1.34.4+k3s1) |
| SSH via QEMU agent | — | `kubectl get nodes` → Ready confirmed |
| Action taken | `qm start 401` | ✅ running |

### C.2 VM Tracker Owner

| Item | Before | After |
|------|--------|-------|
| VM 401 owner | `pilot_reader` | `lnx-rehearsal-01` |
| Action | `VMTracker.track_vm(401, 'lnx-rehearsal-01', created_at=preserved)` | ✅ |
| K8s Lab 5 affected | NO | — |
| Production VMID 500-599 affected | NO | — |

### C.3 Owner Account

| Item | Status |
|------|--------|
| Username | `lnx-rehearsal-01` (16 chars, within 20-char limit) |
| Password | `LinuxRehearsal@2026` |
| Account created | ✅ via `AuthManager.register_user()` |
| Login verified | ✅ `{"success":true,...,"username":"lnx-rehearsal-01","is_admin":null}` |
| Can see Linux lab in catalog | ✅ — 6 labs visible, Linux lab `is_startable=true` |
| Is admin | NO (learner role) |
| Exposes internal endpoints | NO |

**Note**: First account name `linux-owner-rehearsal-01` (24 chars) was rejected by API (max_length=20). Corrected to `lnx-rehearsal-01`.

### C.4 Service Restart

Service was running code from before G-48 commit (last restart: 09:52 AM, G-48 commit: 11:39 AM).  
G-48 added:
- `experiment_background` to `LearnerLabDetail`
- `completion_summary` to `LearnerLabDetail`
- Fixed `check_count` bug for Linux steps

Service restarted (`systemctl restart k8s-netlab`). Health check passed immediately.  
**Post-restart API verification**: `experiment_background` ✅, `check_counts=[3,1,1,0]` ✅.

### C.5 Post-Ops Health Check

| Check | Result |
|-------|--------|
| Service health | ✅ `{"status":"healthy","proxmox":{"connected":true}}` |
| Linux lab `6c439064` published | ✅ |
| Catalog count | ✅ 6 (5 K8s + 1 Linux) |
| Active sessions | ✅ 0 |
| Tainted VMs | ✅ `{}` |
| LLM calls | ✅ 0 |
| VMID 500-599 in sessions | ✅ 0 |
| VM 401 running | ✅ |
| VM 401 K3s Ready | ✅ k8s-template Ready, v1.34.4+k3s1 |
| Feature flag active | ✅ `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS=6c439064-...` in .env |
| K8s Lab 5 published | ✅ `cf019133` publish_status=published, `is_startable=true` |
| Error logs (post-restart) | ✅ `-- No entries --` |

---

## D. Owner Test Manual

**Document**: [LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md](LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md)

### Account

| Item | Value |
|------|-------|
| Username | `lnx-rehearsal-01` |
| Password | `LinuxRehearsal@2026` |
| Role | Learner (non-admin) |
| Assigned VM | 401 (via VM tracker) |

### Exact URLs

| Entry point | URL |
|-------------|-----|
| Base URL | `https://lab.cloudnetops.tech` |
| Login page | `https://lab.cloudnetops.tech/app` |
| Catalog page | `https://lab.cloudnetops.tech/app` (post-login) |
| Linux lab deep link | `https://lab.cloudnetops.tech/labgen-lab.html?labId=6c439064-4cad-4229-addb-36927128d565` |
| Mock article CTA | Same as deep link (LOW-002: no embedded CTA in article.html — accepted) |
| Feedback form | Questions listed in `LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md` Section I |

### Full Test Flow

```
Login (lnx-rehearsal-01)
  → Catalog or deep link → Linux lab detail page
  → Verify: title, background card, 4 objectives, 4 step previews, Start button enabled
  → Start Lab → LAB_ACTIVE
  → Step 1: mkdir -p demo; echo 'hello labgen' > demo/message.txt; cat demo/message.txt
    → Check: 3 verifiers (directory/file/content) → all PASS
  → Step 2: cat demo/message.txt
    → Check: 1 verifier (content) → PASS
  → Step 3: chmod 600 demo/message.txt; stat -c "%a" demo/message.txt
    → Check: 1 verifier (mode=600) → PASS
  → Step 4: no commands → Complete Lab
    → LAB_CLOSED, cleanup_verified=True, residual=0
  → Fill feedback form (10 questions in test steps doc)
  → Operator runs post-run audit
```

### Expected Results Per Step

| Step | Commands | Check Count | Expected |
|------|----------|-------------|----------|
| 1 | `mkdir -p demo` + `echo 'hello labgen' > demo/message.txt` | 3 | dir/file/content PASS |
| 2 | `cat demo/message.txt` | 1 | content PASS |
| 3 | `chmod 600 demo/message.txt` + `stat -c "%a" demo/message.txt` | 1 | mode=600 PASS |
| 4 | none | 0 | Complete button enabled → LAB_CLOSED |

---

## E. Negative Checks

All checks passed before owner rehearsal was cleared to start.

| Check | Method | Result |
|-------|--------|--------|
| `sudo whoami` | `LinuxCommandExecutor.execute(['sudo','whoami'])` | ✅ `policy_rejected=True, rejection_reason=command_denied` |
| `su - root` | executor | ✅ `policy_rejected=True, rejection_reason=command_denied` |
| `bash -c "sudo whoami"` | executor | ✅ `policy_rejected=True, rejection_reason=command_denied` |
| `env sudo whoami` | executor | ✅ `policy_rejected=True, rejection_reason=command_not_allowed` |
| `cat /etc/passwd` | executor | ✅ `policy_rejected=True, rejection_reason=forbidden_path` |
| `cat ../etc/passwd` | executor | ✅ `policy_rejected=True, rejection_reason=path_traversal` |
| `mkdir -p demo` (legit) | executor | ✅ allowed |
| `chmod 600 demo/test.txt` (legit) | executor | ✅ allowed |
| Draft/internal Linux lab visible | API catalog (authenticated) | ✅ Only 1 published Linux lab visible |
| `source_article_id` exposed in catalog | API response inspection | ✅ NOT present |
| Raw article text exposed | API response inspection | ✅ NOT present |
| Internal endpoint accessible to learner | HTTP 405 on `/internal/*` | ✅ Internal endpoints blocked |
| K8s Lab 5 affected | catalog + detail check | ✅ unaffected, `is_startable=true` |

---

## F. Approval Boundary

**This task prepared the rehearsal. The real pilot has NOT started.**

After owner completes the rehearsal, they must:

1. **Complete the full test flow** (Sections D–H in test steps doc)
2. **Fill the feedback form** (Section I in test steps doc)
3. **Confirm: YES / NO** — ready to invite real trusted reader?
4. **Identify the trusted reader**: name or handle
5. **Specify the test time window**: date + time range

**Only after all 5 items are provided will the Linux Trusted Reader Pilot Execution begin.**

No real reader has been contacted. No reader account exists. No pilot is running.

---

## G. Known Limitations

| Limitation | Status |
|------------|--------|
| Owner rehearsal ≠ trusted reader pilot | CONFIRMED — this is preparation only |
| Not public launch | CONFIRMED |
| Live LLM disabled | CONFIRMED — 0 calls |
| Ordinary user article input not open | CONFIRMED |
| LOW-002: article.html no embedded CTA | OPEN — deep link sufficient for rehearsal and pilot |
| VM 401 actual IP is 172.16.100.90 (not .153) | NOTE — memory corrected; irrelevant to learner flow |
| Service restart required (G-48 code gap) | RESOLVED — service restarted, all new fields active |
| Step 2 instruction says "cat" but no `cat` in terminal directly | DESIGN — learner must type command manually; expected |

---

## H. Issue Triage

### BLOCKER (resolved)

| ID | Description | Resolution |
|----|-------------|------------|
| BLOCKER-001 | Linux terminal shows `credential_error` — `lab_kubectl_ws.py` routed Linux sessions through K8s kubeconfig path | Fixed: Linux sessions now route to `_handle_linux_terminal()` via `LinuxRuntimeAdapter`. 24 regression tests. |

### HIGH
_None._

### MEDIUM
_None._

### LOW

| ID | Description | Action |
|----|-------------|--------|
| LOW-002 | article.html has no embedded lab CTA | Accepted for pilot; future task |

### NOTE

| ID | Description |
|----|-------------|
| NOTE-001 | VM 401 was STOPPED — started as part of this task's pre-action |
| NOTE-002 | VM tracker owner was `pilot_reader` — corrected to `lnx-rehearsal-01` |
| NOTE-003 | G-48 code changes required service restart — executed; all fields now correct |
| NOTE-004 | VM 401 real IP is 172.16.100.90 (not .153 as in stale memory); SSH via QEMU agent works |
| NOTE-005 | `linux-owner-rehearsal-01` (24 chars) rejected by API; renamed to `lnx-rehearsal-01` (16 chars) |
| NOTE-006 | Step 4 has 0 verify checks — intentional completion step, no commands |
| NOTE-007 | Step 1 command changed from `printf 'hello labgen\n'` to `echo 'hello labgen'` — `printf` contains `\n` (backslash) which is a `DENIED_COMMANDS` metacharacter; `echo` produces identical output and is in `ALLOWED_COMMANDS` |

---

## I. Final Decision

**`LINUX_PILOT_OWNER_REHEARSAL_READY_FOR_USER`**

All ops pre-actions complete. Health checks pass. Negative checks pass. Owner account ready. Test steps document ready. Service running with correct G-48 code.

The owner may now execute the full rehearsal following [LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md](LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md).

**Real trusted reader pilot will NOT start until owner confirms rehearsal passed and provides explicit YES approval.**

---

## J. Recommended Next Step

**Owner Executes Linux Pilot Rehearsal**

1. Owner logs in as `lnx-rehearsal-01` / `LinuxRehearsal@2026`
2. Owner follows `docs/labgen/LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md` Section A–H
3. Owner fills feedback form (Section I)
4. Owner reports result to operator
5. If ALL steps pass and feedback shows no blockers → owner provides YES + reader identity + time window
6. Operator proceeds to Linux Trusted Reader Pilot Execution

**If rehearsal reveals issues**:
→ Linux Pilot Owner Rehearsal Round 2 (fix issues, re-run)

---

## K. Anti-Bullshit Self-Audit

| Check | Result |
|-------|--------|
| No TODO/FIXME | ✅ |
| No placeholder-as-success | ✅ |
| No real reader invited | ✅ |
| No pilot started | ✅ |
| Owner rehearsal NOT declared as trusted reader pilot | ✅ |
| No customer pilot | ✅ |
| No public launch | ✅ |
| No ordinary user upload | ✅ |
| No live LLM call | ✅ |
| No URL scraping | ✅ |
| Production VMID 500-599 untouched | ✅ |
| Concurrency unchanged | ✅ |
| VM 401 state clearly stated (running) | ✅ |
| VM tracker owner clearly stated (lnx-rehearsal-01) | ✅ |
| User test steps complete | ✅ |
| User has unambiguous URLs | ✅ |
| User has unambiguous account | ✅ |
| User has exact commands per step | ✅ |
| User knows expected output per step | ✅ |
| User knows how to report failure | ✅ |
| User knows Complete requires no manual cleanup | ✅ |
| Rollback path documented | ✅ (in PILOT_PLAN Section I; flag disable + restart < 2 min) |
| Feedback plan documented | ✅ (Section I in test steps doc) |
| Approval gate documented | ✅ (Section F above) |
| No unsafe command recommendation | ✅ |
| No raw article text exposure | ✅ |
| No source_article_id exposure | ✅ |
| No secret/token exposure | ✅ |
| No K8s regression | ✅ |
| No Lab 5 regression | ✅ |
| No catalog regression | ✅ |
| No unclassified risk | ✅ |
| No BLOCKER/HIGH/MEDIUM downgraded to NOTE | ✅ |

---

## L. Artifacts Produced by This Task

| File | Status |
|------|--------|
| `docs/labgen/LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md` | ✅ Created |
| `docs/labgen/LINUX_PILOT_OWNER_REHEARSAL_RESULT_v0.1.md` | ✅ This document |
| `docs/labgen/LINUX_TRUSTED_READER_PILOT_PLANNING_RESULT_v0.1.md` | ✅ Updated (NOTE-003 added, ops notes updated) |
| `docs/labgen/LINUX_TRUSTED_READER_PILOT_APPROVAL_GATE_v0.1.md` | ✅ Updated (VM 401 now running; tracker fixed) |
| `deploy/labgen/staging_ops_ticket_status.md` | ✅ Updated |
| `CHANGELOG.md` | ✅ Updated |
