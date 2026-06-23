# Linux Trusted Reader Pilot — Approval Gate v0.1

**Date**: 2026-06-23 (updated after G-50 Owner Rehearsal Prep)  
**Status**: PENDING_USER_APPROVAL — Owner Rehearsal Ready  
**Pilot started**: NO — awaiting owner rehearsal completion + explicit user approval  

---

## Approval Checklist

| Item | Status | Evidence |
|------|--------|----------|
| All G-48 MEDIUM issues closed | ✅ CLOSED | MEDIUM-001/002 closed by G-48 (troubleshoot + experiment_background filled) |
| All G-48 LOW content issues closed | ✅ CLOSED | LOW-001/003 closed by G-48 (completion_summary + check_count fixed) |
| Pilot plan ready | ✅ READY | `docs/labgen/LINUX_TRUSTED_READER_PILOT_PLAN_v0.1.md` |
| Pre-planning health check PASS | ✅ PASS | See Section A below |
| Reader account plan defined | ✅ DEFINED | `linux-trusted-reader-01` (not yet created — ops pre-action) |
| Feedback form ready | ✅ READY | 10 questions in Pilot Plan Section H |
| Rollback plan ready | ✅ READY | Pilot Plan Section J |
| No open BLOCKER | ✅ NONE | 0 BLOCKER issues |
| No open HIGH | ✅ NONE | 0 HIGH issues |
| No open MEDIUM | ✅ NONE | All MEDIUM closed |
| User explicitly approves pilot | ⏳ PENDING | **Required before execution** |
| Trusted reader identified | ⏳ PENDING | User to specify |
| Test time window identified | ⏳ PENDING | User to specify |
| VM 401 started and K3s ready | ✅ DONE | `qm start 401` executed; K3s Ready (k8s-template v1.34.4+k3s1) |
| Owner rehearsal account created + VM assigned | ✅ DONE | `lnx-rehearsal-01` created; VM tracker owner=lnx-rehearsal-01 |
| Owner rehearsal test steps ready | ✅ DONE | `docs/labgen/LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md` |
| Owner rehearsal completed by user | ⏳ PENDING | User must complete rehearsal first |
| User explicitly approves pilot | ⏳ PENDING | **Required after rehearsal** |
| Trusted reader identified | ⏳ PENDING | User to specify |
| Test time window identified | ⏳ PENDING | User to specify |

**Result**: Gate items 1–12 all PASS. Items 13–15 pending owner rehearsal + user approval.  
**Pilot cannot start until owner rehearsal passes and user explicitly approves.**

---

## A. Pre-Planning Health Check Results (2026-06-23)

### A.1 Linux Lab Readiness

| Check | Result | Detail |
|-------|--------|--------|
| Linux lab `6c439064` exists | ✅ | Key: `6c439064-4cad-4229-addb-36927128d565` |
| publish_status = published | ✅ | Confirmed in `data/lab_drafts.json` |
| target_domain = linux | ✅ | `target_domain: "linux"` |
| catalog count = 6 | ✅ | 5 K8s + 1 Linux |
| Linux lab visible | ✅ | Appears in published lab list |
| No duplicate Linux lab | ✅ | Exactly 1 Linux published lab |
| No draft/internal Linux item visible | ✅ | 0 draft Linux items in learner API |
| No raw article text exposed | ✅ | Verified via API response inspection |
| No source_article_id exposed | ✅ | Not present in learner API response |
| No host path exposed | ✅ | Confirmed from previous dry run |

### A.2 Content Readiness

| Check | Result | Detail |
|-------|--------|--------|
| title present | ✅ | "Linux Files and Permissions Basics" |
| summary present | ✅ | Present in draft |
| experiment_background present | ✅ | 606 chars, real content, no TODO |
| objectives present | ✅ | Present in draft |
| 4 steps_preview present | ✅ | All 4 steps |
| step_troubleshoot present (steps 1-3) | ✅ | 293 / 255 / 264 chars |
| step_troubleshoot present (step 4) | ✅ | 298 chars (completion hint) |
| completion_summary present | ✅ | 399 chars, real content |
| AI tutor context present | ✅ | `ai_tutor_context` field set |
| No TODO/FIXME/placeholder | ✅ | Scanned clean |
| No unsafe troubleshooting advice | ✅ | No sudo/su/rm -rf in troubleshoot hints |

### A.3 Runtime Readiness

| Check | Result | Detail |
|-------|--------|--------|
| Feature flag active | ✅ | `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS=6c439064-...` in running service env |
| LinuxRuntimeAdapter available | ✅ | Initialized on first Start request |
| Linux verifier available | ✅ | 5 primitives: file_exists/dir_exists/content/mode/residual |
| cleanup_verified works | ✅ | Verified in G-46 smoke + G-47 dry run |
| residual scan works | ✅ | residual=0 confirmed in previous runs |
| Unsafe commands rejected | ✅ | sudo/su/path-escape all policy_rejected |
| Unsafe paths rejected | ✅ | /etc access rejected |
| Active Linux sessions | ✅ | 0 active sessions |
| Stale Linux workspaces | ✅ | 0 stale workspaces (previous smoke clean) |
| Taint state | ✅ | `data/tainted_vms.json` = `{}` |
| **VM 401 running** | ✅ **running** | Started as part of Owner Rehearsal Prep (G-50); K3s Ready |
| VM 401 tracker owner | ✅ **lnx-rehearsal-01** | Reassigned from `pilot_reader` to `lnx-rehearsal-01` |
| Rollback path available | ✅ | Env var disable + service restart < 2 min |

### A.4 Safety

| Check | Result | Detail |
|-------|--------|--------|
| LLM call count | ✅ 0 | No LLM calls in Linux learner path |
| Public upload disabled | ✅ | Admin-curated only |
| URL scraping disabled | ✅ | Not implemented |
| Customer pilot not running | ✅ | 0 active pilot sessions |
| Production VMID 500-599 untouched | ✅ | 0 entries in 500-599 range in sessions |
| Concurrency unchanged | ✅ | No changes |
| K8s Lab 5 unchanged | ✅ | publish_status=published, cf019133 |
| K8s labs visible | ✅ | 5 K8s labs in catalog |

**Health Check Summary**: PASS — all ops notes resolved (VM 401 running, tracker reassigned, service restarted for G-48).  
Owner rehearsal account `lnx-rehearsal-01` ready.

---

## B. Open Issues

### BLOCKER
_None._

### HIGH
_None._

### MEDIUM
_None — all closed by G-48._

### LOW
| ID | Description | Impact | Action |
|----|-------------|--------|--------|
| LOW-002 | article.html has no embedded lab CTA component — deep link required | Reader must use direct link, not article-integrated CTA | Accepted for v0.1; future frontend task |

### NOTE
| ID | Description |
|----|-------------|
| NOTE-001 | VM 401 is stopped — requires ops start before pilot |
| NOTE-002 | VM tracker owner `pilot_reader` → needs reassignment to pilot account |
| NOTE-003 | Staging env (`home_lab_mvp.env`) does not include `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS`; covered by `.env` (loaded first, confirmed in running process env) |
| NOTE-004 | Step 4 has 0 verify checks (intentional — completion step, no commands required) |

---

## C. Approval Required

**This gate requires explicit user approval before pilot execution.**

The following decisions need user input:

| Decision | Required from User |
|----------|--------------------|
| Approve pilot execution | YES / NO |
| Identify trusted reader | Name or handle |
| Specify test time window | Date + time range |
| Confirm VM 401 ops actions | Acknowledge pre-actions |

**Until user provides explicit approval, pilot status = NOT_STARTED.**

---

## D. Approval Status

```
approval_status: PENDING_USER_APPROVAL
pilot_started: false
date_approved: [TBD]
approved_by: [TBD]
reader_identity: [TBD — user to specify]
test_window: [TBD — user to specify]
```

---

## E. Post-Approval Execution Trigger

Once user approves, operator proceeds in this order:

1. Complete pre-pilot ops checklist (Pilot Plan Section K)
2. Start operator monitoring (journalctl -f -u k8s-netlab)
3. Create account `linux-trusted-reader-01`
4. Send credentials to reader via secure channel
5. Reader executes test flow (Pilot Plan Section D)
6. Operator records observation metrics (Pilot Plan Section G)
7. Reader fills feedback form (Pilot Plan Section H)
8. Operator runs post-run audit
9. Record result → `docs/labgen/LINUX_TRUSTED_READER_PILOT_RESULT_v0.1.md`
10. Update staging_ops_ticket_status.md with G-49 entry

**Do NOT start pilot before this gate is signed off.**
