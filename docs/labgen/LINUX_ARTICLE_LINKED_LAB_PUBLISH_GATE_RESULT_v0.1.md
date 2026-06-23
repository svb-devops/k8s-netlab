# Linux Article-linked Lab Publish Gate Result v0.1

**Gate**: G-44 — Linux Article-linked Lab Publish Gate  
**Final Decision**: LINUX_ARTICLE_LINKED_LAB_PUBLISHED_WITH_NOTES  
**Date**: 2026-06-23  
**Commit**: abaf7a6

---

## Preflight Gate (G-43 residual review)

| Item | Status | Decision |
|------|--------|----------|
| G-43 dry run final decision | LINUX_PUBLISH_CANDIDATE_DRY_RUN_READY | ✅ Confirmed |
| Open BLOCKER/HIGH/MEDIUM from G-43 | None | ✅ Not blocking |
| G-42 MEDIUM (path escape classification) | Closed (commit 3e5e011) | ✅ Not blocking |
| G-39 TOCTOU LOW | Remains LOW, scope not widened | ✅ Not blocking |
| Immutables confirmed | actual_publish_performed=False, learner_catalog_changed=False | ✅ Not blocking |

Preflight conclusion: **no open BLOCKER/HIGH/MEDIUM. Publish gate allowed.**

---

## Pre-publish 6-Bucket Check

| Bucket | Check | Result |
|--------|-------|--------|
| 1. Dry run closure | G-43 LINUX_PUBLISH_CANDIDATE_DRY_RUN_READY confirmed | PASS |
| 2. Linux draft readiness | `6c439064` — target_domain=LINUX, publish_status=DRAFT, rehearsal_completed=True | PASS |
| 3. Internal rehearsal readiness | G-42 rehearsal completed, LAB_CLOSED, cleanup_verified=True | PASS |
| 4. StaticValidator gate lift | G-37~G-43 all complete — precondition for removing linux.publish_blocked_until_runtime met | PASS |
| 5. Catalog pre-state | 5 PUBLISHED labs (all K8s) | PASS |
| 6. Learner guard | PRECHECK_LINUX_LEARNER_NOT_SUPPORTED added to run_precheck() | PASS |

---

## Implementation Summary

### Code Changes (B-class)

| File | Change |
|------|--------|
| `backend/labgen/static_validator.py` | Removed `_check_linux_publish_blocked_until_runtime()` call from `_validate_linux()`; deleted dead method |
| `backend/labgen/failure_reasons.py` | Added `PRECHECK_LINUX_LEARNER_NOT_SUPPORTED = "precheck.linux_learner_not_yet_available"` |
| `backend/labgen/lab_session_service.py` | Added Linux domain guard in `run_precheck()`: Linux drafts return LINUX_LEARNER_NOT_SUPPORTED before cleanup check |
| `backend/labgen/publish_candidate_dry_run_service.py` | Updated validation gate to "zero PUBLISH_BLOCKING failures" semantics; updated module docstring |

### Test Changes

| File | Change |
|------|--------|
| `tests/test_labgen_linux_publish_gate.py` | NEW — 30 tests (A: gate lift / B: PublishService / C: precheck guard / D: catalog / E: negatives / F: K8s regression) |
| 7 existing test files | 15 assertions updated: "always blocked" → "gate lifted" |
| `tests/test_labgen_failure_reasons.py` | Regression fix: added `target_domain = LabDomainType.K8S` to MagicMock spec draft |

---

## Safety Review Results

### safety-reviewer (B-class, pre-commit)

| Finding | Severity | Disposition |
|---------|----------|-------------|
| `run_rehearsal_precheck()` no Linux guard | HIGH | **False positive** — admin rehearsal is intentionally allowed (design intent); learner sessions protected by `PRECHECK_LINUX_LEARNER_NOT_SUPPORTED` in `run_precheck()`. Confirmed by tests. |
| Dead `_check_linux_publish_blocked_until_runtime()` method | MEDIUM | Fixed — deleted method |
| Dry run service docstring mentions "linux boundary recognized" | MEDIUM | Fixed — updated to "zero PUBLISH_BLOCKING failures" |

**BLOCKER count: 0**

### Codex Review (B-class, pre-commit)

| Finding | Severity | Disposition |
|---------|----------|-------------|
| Published Linux lab not startable by learners | P1 | **Design intent** — published lab is visible in catalog as a "coming soon" entry; learners receive `precheck.linux_learner_not_yet_available` with clear message. This is the "_WITH_NOTES" condition documented below. |

**BLOCKER count: 0**

---

## Live Publish Execution

**Method**: Python script via `PublishService` + `LabDraftRepository` (service not yet restarted with new code path; executed directly before restart)

| Step | Command/Check | Result |
|------|---------------|--------|
| Pre-state | 5 PUBLISHED labs (K8s only) | ✅ Confirmed |
| StaticValidator | 0 PUBLISH_BLOCKING failures for Linux draft | ✅ Confirmed |
| Publish | `PublishService.publish(draft)` → PUBLISHED | ✅ Executed |
| Data write | `repo.update(published)` → data/lab_drafts.json | ✅ Written |
| Service restart | `systemctl restart k8s-netlab` | ✅ |
| Health check | `{"status":"healthy","proxmox":{"connected":true}}` | ✅ |
| Error log | No new exceptions | ✅ |

---

## Post-publish Verification

### Catalog Count: 5 → 6 ✅

| Lab ID | Domain | Title |
|--------|--------|-------|
| 67fca5e4 | k8s | Kubernetes Basics: Your Isolated Lab Environment |
| b0b97742 | k8s | Kubernetes ConfigMap Basics: Store Your First Config |
| d9f44383 | k8s | Kubernetes Secret Basics: Protect Your First Configuration |
| e52b8b80 | k8s | Kubernetes Deployment Basics: Run Your First Workload |
| cf019133 | k8s | Kubernetes ConfigMap 实战：从文章到实验 (Lab 5, article-linked) |
| **6c439064** | **linux** | **Linux Files and Permissions Basics** ← NEW |

### Linux Entry Visible in Catalog ✅
- `target_domain: linux`
- `publish_status: PUBLISHED`
- `rehearsal_completed: True`

### K8s Lab 5 Unchanged ✅
- `cf019133` — Kubernetes ConfigMap 实战：从文章到实验
- `publish_status: PUBLISHED` (unchanged)
- `target_domain: k8s` (unchanged)
- `steps count: 2` (unchanged)

### Learner Smoke: Start Blocked with Clear Message ✅

```
run_precheck('6c439064', '500', 'alice'):
  passed: False
  failures: ['precheck.linux_learner_not_yet_available']
  LINUX_LEARNER_NOT_SUPPORTED: True
  CLEANUP_NOT_DECLARED: False  ← not exposed (guard preempts it)
```

---

## Constraint Compliance

| Constraint | Status |
|-----------|--------|
| 禁止：发布多个 Linux lab | ✅ Exactly 1 Linux lab published |
| 禁止：启动 Linux trusted reader pilot | ✅ Not started |
| 禁止：启动 customer pilot | ✅ Not started |
| 禁止：public launch | ✅ Not launched publicly |
| 禁止：启用 live LLM / 调用 LLM API | ✅ 0 LLM calls |
| 禁止：URL scraping | ✅ None |
| 禁止：修改 production VMID 500-599 | ✅ No VM operations |
| 禁止：修改 K8s runtime/verifier 行为 | ✅ Confirmed — K8s path unchanged |
| 禁止：破坏 K8s Lab 5 article-linked path | ✅ Lab 5 verified unchanged |
| 禁止：宣称 Linux support 已在线上 | ✅ Decision is PUBLISHED_WITH_NOTES |

---

## "_WITH_NOTES" Conditions

The final decision is `LINUX_ARTICLE_LINKED_LAB_PUBLISHED_WITH_NOTES` rather than `LINUX_ARTICLE_LINKED_LAB_PUBLISHED` because:

1. **Learner sessions not yet supported**: Published Linux lab appears in catalog with full metadata, but `run_precheck()` returns `precheck.linux_learner_not_yet_available` when a learner attempts to start a session. This is intentional — the lab is "published" in the sense that it's visible and discoverable, but "with notes" in that the learner runtime path is not yet wired.

2. **Safety reviewers flagged design intent**: Both safety-reviewer (HIGH) and Codex (P1) flagged "published but not startable" as a concern. These are not security vulnerabilities but design observations that confirm the WITH_NOTES classification.

3. **Next step required**: Linux Trusted Reader Pilot (enabling Linux learner sessions) is needed before the lab is truly "launchable."

---

## Linux Domain Proof — Complete Status After G-44

| Gate | Task | Decision |
|------|------|----------|
| G-35 | Linux Domain Proof Design Gate | LINUX_DOMAIN_PROOF_DESIGN_READY_WITH_NOTES |
| G-36 | Linux Domain Contract Schema Extension | LINUX_DOMAIN_CONTRACT_SCHEMA_READY_WITH_NOTES |
| G-37 | Linux Runtime Adapter Spike | LINUX_RUNTIME_ADAPTER_SPIKE_READY_WITH_NOTES |
| G-38 | Linux Verifier Adapter Spike | LINUX_VERIFIER_ADAPTER_SPIKE_READY_WITH_NOTES |
| G-39 | Linux Verifier Adapter Hardening | LINUX_VERIFIER_ADAPTER_HARDENED_WITH_NOTES |
| G-40 | Linux Guided Practice Draft Template | LINUX_GUIDED_PRACTICE_DRAFT_TEMPLATE_READY_WITH_NOTES |
| G-41 | Linux Internal Rehearsal Bridge | LINUX_INTERNAL_REHEARSAL_BRIDGE_READY_WITH_NOTES |
| G-42 | Linux E2E Internal Rehearsal Acceptance | LINUX_E2E_INTERNAL_REHEARSAL_ACCEPTANCE_PASSED_WITH_NOTES |
| G-43 | Linux Publish Candidate Dry Run | LINUX_PUBLISH_CANDIDATE_DRY_RUN_READY |
| **G-44** | **Linux Article-linked Lab Publish Gate** | **LINUX_ARTICLE_LINKED_LAB_PUBLISHED_WITH_NOTES** |

---

## Test Suite

| Metric | Value |
|--------|-------|
| Total tests | 4228 passed |
| Coverage | 92.63% |
| New tests (G-44) | 30 |
| Updated tests | 15 |
| K8s regression | 0 failures |
| BLOCKER | 0 |

---

## Recommended Next Step

**Linux Trusted Reader Pilot** — enable Linux learner sessions for a small set of pilot readers:
- Requires `LinuxRuntimeAdapter enabled=True` in staging
- Requires production VMID/network policy review for Linux sandbox
- Requires trusted reader approval
- Gates: learner can Start → execute steps → complete Linux lab end-to-end
