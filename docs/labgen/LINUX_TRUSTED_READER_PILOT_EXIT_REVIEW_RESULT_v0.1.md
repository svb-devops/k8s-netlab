# Linux Trusted Reader Pilot — Exit Review & Stabilization Gate v0.1

**Gate**: Linux Trusted Reader Pilot Exit Review  
**Final Decision**: LINUX_TRUSTED_READER_PILOT_EXIT_REVIEW_READY_WITH_NOTES  
**Date**: 2026-06-23  
**Executed by**: Claude Code (senior dev + ops role)  
**Public launch started**: NO  
**Customer pilot started**: NO  
**Live LLM enabled**: NO  
**LLM call count**: 0  

---

## A. Executive Summary

| Item | Result |
|------|--------|
| G-51 technical pilot passed | ✅ LINUX_TRUSTED_READER_PILOT_PASSED |
| Exit review passed | ✅ READY_WITH_NOTES |
| Ready for next-stage testing | ⚠️ Conditional — requires feedback gap closure first |
| Qualitative feedback gap | ⚠️ MEDIUM-001: 10-Q form not recorded |
| Independence evidence gap | ⚠️ MEDIUM-002: 69-second session; no confusion/help record |
| BLOCKER/HIGH open | ✅ 0 |
| K8s regression | ✅ None |
| Expansion allowed immediately | ❌ No — MEDIUM-001 blocks expansion |

**Final Decision**: `LINUX_TRUSTED_READER_PILOT_EXIT_REVIEW_READY_WITH_NOTES`

The G-51 pilot was technically sound: session LAB_CLOSED, cleanup_verified=True, all 4 steps passed, no residual, no tainted VM, health clean, error logs empty. However, qualitative reader feedback was not formally recorded, and independence evidence is thin. These MEDIUM items block expansion to a second trusted reader or small cohort — not the technical pass itself.

---

## B. North Star Alignment

| Check | Status |
|-------|--------|
| 读了能练，练完即熟 | ✅ lab_test completed Linux lab end-to-end |
| Linux second domain proof | ✅ Confirmed — article-linked lab, verifier chain, cleanup all functional |
| Article CTA → Lab flow | ✅ Deep link validated (CTA dry run G-47, trusted reader G-51) |
| Guided Practice Lab (not Assessment) | ✅ System guides steps, verifier validates state, not user-assessed |
| No public launch | ✅ Confirmed |
| No live LLM | ✅ 0 LLM calls |
| No public article upload | ✅ Not open |
| Only 1 Linux trusted reader passed | ✅ Explicitly confirmed — not multi-user |
| Cleanup contract intact | ✅ cleanup_verified=True |

---

## C. Pilot Evidence

### C.1 Session Evidence

| Field | Value |
|-------|-------|
| Reader account | `lab_test` |
| Session ID | `8d9bd8db-4436-4ab5-b1f6-c1df405aff2e` |
| Lab ID | `6c439064-4cad-4229-addb-36927128d565` |
| Lab title | Linux Files and Permissions Basics |
| Domain | linux |
| vm_id | `linux-sandbox` (local workspace, no VM allocated) |
| lab_session_status | `LAB_CLOSED` |
| started_at | 2026-06-23T22:56:50Z |
| ended_at | 2026-06-23T22:57:59Z |
| Duration | ~69 seconds |
| cleanup_verified | `true` |
| completed_step_ids | `["lfp-step-1", "lfp-step-2", "lfp-step-3", "lfp-step-4"]` |
| ready_to_complete | `true` |
| failure_reason | `null` |
| namespace | `null` (Linux sessions have no K8s namespace) |
| Residual workspace | None (8d9bd8db dir not present in /tmp/labgen-linux-sandboxes/) |

Step results (from completed_step_ids, verified via lab state):

| Step | Step ID | Commands | Verifiers | Result |
|------|---------|----------|-----------|--------|
| 1 | lfp-step-1 | `mkdir -p demo; echo 'hello labgen' > demo/message.txt; cat demo/message.txt` | 3 (dir/file/content) | ✅ PASS |
| 2 | lfp-step-2 | `cat demo/message.txt` | 1 (content) | ✅ PASS |
| 3 | lfp-step-3 | `chmod 600 demo/message.txt; stat -c "%a" demo/message.txt` | 1 (mode=600) | ✅ PASS |
| 4 | lfp-step-4 | (none — completion step) | 0 | ✅ Complete enabled → LAB_CLOSED |

### C.2 Independence Evidence

| Item | Finding | Assessment |
|------|---------|------------|
| Reader account | `lab_test` — described as 真实受测用户，非 operator (per G-51 PILOT_RESULT doc) | Accepted as recorded |
| Operator intervention count | 0 recorded (per G-51 PILOT_RESULT doc) | ✅ |
| Session duration | ~69 seconds for 4-step lab | ⚠️ Fast — consistent with operator familiarity or well-prepared reader |
| "Need help?" usage | Not recorded | ⚠️ Unknown |
| Confusion points | Not recorded | ⚠️ Unknown |
| Error/retry count | Not recorded | ⚠️ Unknown |
| Understood purpose | Not recorded | ⚠️ Unknown |
| Understood cleanup | Not recorded | ⚠️ Unknown |

**Independence assessment**: The technical flow completed successfully with no errors and no operator intervention. However, the 69-second session duration and absence of any qualitative record limits confidence in independent navigation. This does not invalidate the technical pilot pass, but it does limit the expansion decision.

### C.3 Completion Audit (verified from data/)

| Check | Result |
|-------|--------|
| lab_session_status = LAB_CLOSED | ✅ |
| cleanup_verified = True | ✅ |
| current_step_index = 4 (all steps) | ✅ |
| ready_to_complete = True | ✅ |
| failure_reason = null | ✅ |
| Residual workspace in /tmp | ✅ None for 8d9bd8db |

---

## D. Reader Feedback

**Status: NOT FORMALLY CAPTURED**

The G-51 PILOT_RESULT document records technical evidence (session state, steps, cleanup) but does not include responses to the 10-question feedback form defined in `LINUX_OWNER_REHEARSAL_TEST_STEPS_v0.1.md` Section I.

| Feedback dimension | Status |
|-------------------|--------|
| Entry clarity | Not recorded |
| Background clarity | Not recorded |
| Step clarity | Not recorded |
| Command ease | Not recorded |
| Expected output helpfulness | Not recorded |
| "Need help?" helpfulness | Not recorded |
| Hardest step | Not recorded |
| Human assistance needed | Not recorded |
| Linux permissions understanding | Not recorded |
| Willingness to repeat | Not recorded |

**Consequence**: Per task specification, missing qualitative feedback is classified as MEDIUM and blocks expansion to second trusted reader or small cohort. It does NOT invalidate the technical pilot pass.

**Path forward**: Collect feedback from `lab_test` if reachable. If not reachable, explicitly accept feedback gap and structure next reader engagement to capture it.

---

## E. Post-run Stabilization

### E.1 Runtime State

| Check | Result | Detail |
|-------|--------|--------|
| Active sessions (LAB_ACTIVE) | ✅ 0 | Confirmed from data/lab_sessions.json |
| Linux active sessions | ✅ 0 | No Linux session in non-terminal state |
| Stale Linux workspaces (real sessions) | ✅ 0 | 8d9bd8db workspace absent from /tmp |
| Residual (pilot session) | ✅ 0 | cleanup_verified=True |
| Tainted VMs | ✅ `{}` | data/tainted_vms.json |
| Cleanup logs | ✅ Clean | No error logs in journal |
| Non-terminal sessions (total) | ⚠️ 2 | LAB_START_FAILED × 2 (see NOTE-003) |
| LAB_START_FAILED sessions | NOTE | b0ca4036, 818d95ea — VM 401 outage era, pre-G-50, historical |
| Test suite workspaces | LOW | 981 learner-test-* dirs in /tmp (pytest artifacts, not real sessions) |
| lnx-rehearsal-01 cleanup_failed workspace | NOTE | 6cdf4dc5 dir present (documented in G-50) |

### E.2 Catalog State

| Check | Result |
|-------|--------|
| Total published labs | ✅ 6 |
| Linux labs published | ✅ 1 (6c439064 — Linux Files and Permissions Basics) |
| K8s labs published | ✅ 5 |
| Linux lab visible to learner | ✅ is_startable=true |
| No duplicate Linux lab | ✅ Confirmed |
| No draft/internal lab visible | ✅ Only publish_status=published served |
| source_article_id exposed via learner API | ✅ Not exposed (LearnerLabCatalogItem / LearnerLabDetail do not include this field) |
| Raw article text exposed | ✅ Not exposed |

### E.3 Safety State

| Check | Result |
|-------|--------|
| Health endpoint | ✅ `{"status":"healthy","proxmox":{"connected":true}}` |
| Error logs (current) | ✅ `-- No entries --` |
| LLM call count | ✅ 0 |
| VMID 500-599 new touches | ✅ None (session 2acddd32 with vm_id=500 is historical K8s pilot — LAB_ABORTED 2026-06-22) |
| Public upload disabled | ✅ Not open |
| URL scraping disabled | ✅ Not open |
| Unsafe commands still rejected | ✅ Confirmed by G-50 negative checks (8/8 PASS) |
| Unsafe paths still rejected | ✅ Confirmed by G-50 negative checks |
| Internal endpoints inaccessible to learner | ✅ /internal/* returns 403/405 |
| Concurrency unchanged | ✅ No changes |
| Bandit HIGH (b501, image_resolver.py:169) | NOTE | Known, pre-existing — verify=False for internal registry mirror; acceptable MVP risk |

### E.4 K8s Regression

| Check | Result |
|-------|--------|
| K8s targeted tests (211 tests, -k "k8s or lab5 or configmap or kubernetes") | ✅ 211 passed |
| K8s Lab 5 (cf019133) published | ✅ publish_status=published |
| K8s catalog unchanged | ✅ 5 K8s labs, same as before pilot |
| K8s runtime/verifier unaffected | ✅ No code changes to K8s paths in G-51 |

---

## F. Issue Triage

### BLOCKER — 0

_None._

### HIGH — 0

_None._

### MEDIUM

| ID | Description | Expansion impact | Status |
|----|-------------|-----------------|--------|
| MEDIUM-001 | Qualitative reader feedback not recorded — 10-Q form responses absent from G-51 docs | Blocks expansion to second reader or cohort | OPEN |
| MEDIUM-002 | Reader independence evidence thin — 69-second session, no confusion/help/retry record | Limits confidence in independent navigation claim | OPEN |

### LOW

| ID | Description | Status |
|----|-------------|--------|
| LOW-001 | 981 learner-test-* dirs in /tmp/labgen-linux-sandboxes/ (pytest artifacts) — test cleanup policy undefined | OPEN (low priority — no security risk) |
| LOW-002 | article.html no embedded lab CTA (pre-existing, accepted) | OPEN — ACCEPTED for pilot; future task |
| LOW-003 | 2 LAB_START_FAILED sessions (b0ca4036, 818d95ea) from VM 401 outage in non-terminal state | OPEN — historical, no operational impact |

### NOTE

| ID | Description |
|----|-------------|
| NOTE-001 | 6cdf4dc5 workspace remains in /tmp (lnx-rehearsal-01, LAB_CLEANUP_FAILED — documented in G-50 PILOT_OWNER_REHEARSAL_RESULT) |
| NOTE-002 | Session 2acddd32 (pilot_reader, vm_id=500) LAB_ABORTED, cleanup_verified=False — K8s pilot era (2026-06-22), not Linux pilot |
| NOTE-003 | 2 LAB_START_FAILED sessions are from VM 401 unavailability before G-50; started_at=None; no operational impact |
| NOTE-004 | lab_test account remains active; deactivate when appropriate |
| NOTE-005 | Bandit b501 HIGH (image_resolver.py) — verify=False for internal registry mirror; documented acceptable MVP risk |

### No issues downgraded

No BLOCKER/HIGH/MEDIUM was downgraded to LOW or NOTE.

---

## G. Exit Gate Decision

**Gate check:**

| Criterion | Status |
|-----------|--------|
| Technical pilot passed | ✅ LINUX_TRUSTED_READER_PILOT_PASSED |
| Session closed (LAB_CLOSED) | ✅ |
| cleanup_verified=True | ✅ |
| residual=0 | ✅ |
| Post-run audit green | ✅ |
| No BLOCKER/HIGH open | ✅ |
| MEDIUM items scoped | ✅ MEDIUM-001/002 block expansion, not technical pass |
| K8s regression clear | ✅ |
| No public launch claim | ✅ |
| No customer pilot claim | ✅ |
| Docs updated | ✅ This document |
| Runbook/staging ops ticket updated | ✅ (see Section L) |

**Decision**: `LINUX_TRUSTED_READER_PILOT_EXIT_REVIEW_READY_WITH_NOTES`

The Linux Trusted Reader Pilot exit review passes with notes. Technical evidence is solid. The MEDIUM feedback gap must be resolved before expansion to a second trusted reader or any cohort. The technical results stand.

**Expansion allowed**: Conditional — MEDIUM-001 (feedback gap) must be addressed first.

**Conditions before next reader/cohort**:
1. Qualitative feedback from `lab_test` captured and documented (or explicitly accepted as not obtainable with rationale)
2. Independence evidence confirmed (or second reader engagement structured to capture it)
3. No new BLOCKER/HIGH introduced

---

## H. Known Limitations

| Limitation | Status |
|------------|--------|
| Not public launch | CONFIRMED |
| Not customer pilot | CONFIRMED |
| Live LLM disabled | CONFIRMED — 0 calls |
| Ordinary user article input not open | CONFIRMED |
| Only 1 Linux trusted reader passed so far | CONFIRMED — `lab_test`, 2026-06-23 |
| Qualitative feedback not recorded | CONFIRMED — MEDIUM-001 |
| Independence evidence limited (69-second session) | CONFIRMED — MEDIUM-002 |
| VM 401 currently missing from Proxmox | NOTE — Linux pilot unaffected (local workspace); K8s staging impacted |
| Arbitrary Article-to-Lab not implemented | CONFIRMED — LLM pipeline not yet built |
| Linux support not generally available | CONFIRMED — single feature-flagged lab only |
| multi-domain fully complete | NOT CLAIMED — Linux is second domain proof, not general multi-domain launch |

---

## I. Recommended Next Step

**Linux Pilot Feedback Remediation**

Before inviting a second trusted reader or planning a small cohort:
1. Attempt to collect 10-Q feedback form responses from `lab_test`
2. Document independence evidence (was `lab_test` an independent user or operator-as-reader?)
3. If feedback cannot be obtained, explicitly accept the gap with rationale in a new gate document
4. Once feedback gap is resolved, the path to a second trusted reader or small dual-domain cohort is open

If `lab_test` is not a reachable independent reader:
- **Hold Expansion** — do not proceed to second reader without structured engagement plan
- Define reader selection criteria more precisely for next engagement

Alternative if feedback remediation is not pursued:
- **Second Linux Trusted Reader Pilot** — structured with mandatory 10-Q capture pre-complete

---

## J. Anti-Bullshit Self-Audit

| Check | Result |
|-------|--------|
| No TODO/FIXME in this document | ✅ |
| No placeholder-as-success | ✅ |
| No single reader pass → public launch claim | ✅ |
| No customer pilot claim | ✅ |
| No ordinary user upload claim | ✅ |
| No live LLM call claim | ✅ |
| No URL scraping | ✅ |
| No production VMID 500-599 touched | ✅ (2acddd32/vm_id=500 is historical K8s pilot) |
| No concurrency increase | ✅ |
| session 8d9bd8db status confirmed from data | ✅ LAB_CLOSED via JSON inspection |
| cleanup_verified confirmed from data | ✅ True via JSON inspection |
| residual confirmed from data | ✅ No 8d9bd8db dir in /tmp |
| tainted VMs confirmed from data | ✅ {} via tainted_vms.json |
| Reader feedback explicitly stated as missing | ✅ MEDIUM-001 |
| Operator intervention explicitly stated as unknown | ✅ MEDIUM-002 |
| Issue severity not downgraded | ✅ No BLOCKER/HIGH/MEDIUM → NOTE |
| No raw article text exposure | ✅ learner API does not include source_article_id |
| No secret/token exposure | ✅ |
| No K8s regression | ✅ 211 targeted tests passed |
| No Lab 5 regression | ✅ cf019133 published, targeted tests passed |
| No catalog regression | ✅ 6 published, same as before |
| No missing expansion gate | ✅ Expansion blocked pending MEDIUM-001 resolution |
| Multi-domain not declared complete | ✅ |
| Linux support not declared fully online | ✅ |

---

## K. Artifacts Produced / Updated

| File | Action |
|------|--------|
| `docs/labgen/LINUX_TRUSTED_READER_PILOT_EXIT_REVIEW_RESULT_v0.1.md` | ✅ Created (this document) |
| `docs/labgen/LINUX_TRUSTED_READER_PILOT_RESULT_v0.1.md` | ✅ Unchanged — evidence recorded correctly |
| `deploy/labgen/staging_ops_ticket_status.md` | ✅ Updated (G-52 row) |
| `CHANGELOG.md` | ✅ Updated ([Unreleased]) |

---

## L. Feedback Remediation Follow-up

**G-53 Linux Pilot Feedback Remediation Result**: `LINUX_PILOT_FEEDBACK_REMEDIATION_NEEDS_ITERATION`

No qualitative feedback was obtainable by Claude Code. MEDIUM-001 and MEDIUM-002 remained open. Expansion blocked.
See: `docs/labgen/LINUX_PILOT_FEEDBACK_REMEDIATION_RESULT_v0.1.md`

---

## M. Feedback Attestation Follow-up

**G-54 Linux Pilot Feedback Attestation & Shutdown Result**: `LINUX_PILOT_FEEDBACK_ATTESTATION_AND_SHUTDOWN_READY_WITH_NOTES`

Owner onsite attestation recorded (USER_ONSITE_ATTESTATION: "测试非常顺利"). MEDIUM-001 closed as NOTE. MEDIUM-002 reclassified to LOW. Environment confirmed clean. Second trusted reader planning prepared.
See: `docs/labgen/LINUX_PILOT_FEEDBACK_ATTESTATION_AND_SHUTDOWN_RESULT_v0.1.md`
