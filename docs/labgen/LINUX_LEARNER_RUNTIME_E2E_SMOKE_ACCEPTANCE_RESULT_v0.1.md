# Linux Learner Runtime E2E Smoke Acceptance — Result v0.1

**Gate**: Linux Learner Runtime E2E Smoke Acceptance  
**Status**: LINUX_LEARNER_RUNTIME_E2E_SMOKE_PASSED_WITH_NOTES  
**Date**: 2026-06-23  
**Executed by**: Claude Code (senior dev + ops role)  
**Branch**: main  

---

## A. Executive Summary

| Item | Result |
|------|--------|
| Real learner smoke passed | YES |
| Learner Start succeeded | YES — LAB_ACTIVE, vm_id=linux-sandbox |
| Step Check passed | YES — all 4 steps all_passed=True |
| Cleanup passed | YES — cleanup_verified=True, residual=0 |
| Abort path passed | YES — LAB_CLOSED, cleanup_verified=True |
| Negative checks passed | YES — all 8 checks rejected as expected |
| Post-run audit clean | YES — 0 active sessions, 0 residuals, 0 tainted VMs |
| K8s Lab 5 unaffected | YES — catalog=6, K8s path zero regression |
| Ready for Linux Reader-facing CTA Dry Run | YES (with NOTES) |
| Is this Trusted Reader Pilot | NO — controlled operator smoke only |
| Is this public launch | NO |

**NOTES**:  
- BLOCKER fixed: `lfp-step-4` had an incorrect `linux_no_residual_files` verifier. See Section I.

---

## B. North Star Alignment

- **读了能练，练完即熟** — Linux Files and Permissions Basics proves second-domain learner path.
- Linux domain proves the Guided Practice Lab pattern: learner follows guided steps, system verifies filesystem state, lab completes with cleanup.
- This is a **Guided Practice Lab**, NOT an Assessment Lab.
- No public launch, no live LLM, no ordinary user article upload.
- Catalog now has 5 K8s + 1 Linux published lab (6 total).

---

## C. Previous Code Enablement Summary (G-45)

| Component | Change |
|-----------|--------|
| `backend/config.py` | `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` (frozenset from comma-sep env) + `LABGEN_LINUX_SANDBOX_ROOT` |
| `backend/labgen/failure_reasons.py` | `LINUX_LEARNER_WORKSPACE_CREATE_FAILED` + `LINUX_LEARNER_CLEANUP_FAILED` |
| `backend/labgen/lab_session_service.py` | Linux learner precheck (allowlist), `_do_create_linux_session()`, `_do_cleanup_linux()`, `_do_cleanup()` sentinel dispatch (vm_id anchor), fail-closed when adapter=None |
| `backend/labgen/routes.py` | Singleton `_linux_runtime_adapter`, `LinuxVerifierService` injection, route branch for Linux learner |
| Safety-reviewer fixes | M1: cleanup dispatch anchored on vm_id (not draft.target_domain); M2: route checks adapter not None |
| Codex P1 fix | Sentinel session + adapter=None → LAB_CLEANUP_FAILED, never falls through to K8s namespace cleanup |

---

## D. Preflight Result

### D.1 Catalog
- catalog count = 6 ✅
- Linux lab (`6c439064-4cad-4229-addb-36927128d565`) visible ✅
- `is_startable = true` ✅
- K8s 5 labs visible ✅
- No draft/internal lab visible ✅
- No duplicate Linux lab ✅

### D.2 Enablement State
- `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS=6c439064-4cad-4229-addb-36927128d565` in `.env` ✅
- Feature flag set for controlled scope (1 lab only) ✅
- Broad Linux enablement absent ✅
- Non-allowlisted lab blocked (returns `precheck_failures: no_vm_assigned` for fake lab id) ✅
- Active Linux sessions = 0 ✅

### D.3 Runtime Readiness
- `LinuxRuntimeAdapter` initialized (lazy on first Start request) ✅
- `LinuxVerifierService` available ✅
- Cleanup sentinel dispatch anchored on `vm_id == "linux-sandbox"` ✅
- adapter=None fail-closed (verified by unit test) ✅
- allow_root=True policy rejected at model validation ✅
- allow_network=True policy rejected at model validation ✅
- Stale sandbox dirs = test artifacts from pytest (active=0) ✅
- Taint state = none ✅

### D.4 Safety
- LLM call count = 0 ✅
- Public upload disabled ✅
- URL scraping disabled ✅
- Production VMID 500-599 untouched ✅
- Concurrency unchanged ✅

---

## E. Learner Smoke Result

### E.1 Session Identity
- **Learner account**: `linux-smoke-learner` (operator-controlled test account)
- **Session ID**: `0a38c7c5-0f71-4268-9b39-717d8a02303f`
- **Lab ID**: `6c439064-4cad-4229-addb-36927128d565` (Linux Files and Permissions Basics)

### E.2 Start Result
```json
{
  "session_id": "0a38c7c5-0f71-4268-9b39-717d8a02303f",
  "lab_session_status": "LAB_ACTIVE",
  "vm_id": "linux-sandbox",
  "session_type": "learner",
  "student_username": "linux-smoke-learner",
  "lab_id": "6c439064-4cad-4229-addb-36927128d565",
  "started_at": "2026-06-23T16:58:42.814921Z",
  "cleanup_verified": false,
  "namespace": null,
  "kubeconfig": null
}
```

### E.3 Guided Commands Executed (operator-side)
Safe form (no shell redirection; equivalent to learner terminal execution):
```
mkdir -p demo                           # via filesystem API
write_file demo/message.txt "hello labgen\n"  # Python write (safe form of printf >)
cat demo/message.txt                    # output: "hello labgen"
chmod 600 demo/message.txt              # via chmod()
stat -c "%a" demo/message.txt           # output: 600
```
No shell=True. No unsafe commands. No command policy bypassed.

### E.4 Step Check Results

| Step | verify_id | verify_type | passed | advanced | ready_to_complete |
|------|-----------|-------------|--------|----------|-------------------|
| lfp-step-1 | lfp-s1-v1 | linux_directory_exists(demo) | ✅ | ✅ | — |
| lfp-step-1 | lfp-s1-v2 | linux_file_exists(demo/message.txt) | ✅ | ✅ | — |
| lfp-step-1 | lfp-s1-v3 | linux_file_content_matches("hello labgen") | ✅ | ✅ | — |
| lfp-step-2 | — | (no templates) | ✅ | ✅ | — |
| lfp-step-3 | — | (no templates) | ✅ | ✅ | — |
| lfp-step-4 | — | (no templates, after BLOCKER fix) | ✅ | ✅ | **True** |

### E.5 Complete Result
```json
{
  "lab_session_status": "LAB_CLOSED",
  "cleanup_verified": true,
  "failure_reason": null
}
```
Workspace `/tmp/labgen-linux-sandboxes/0a38c7c5-...` removed. residual=0.

### E.6 Abort Path Result
- Abort session: `4db7365f-52ae-4421-b2ae-39d070dd2b25`
- Status: LAB_CLOSED, cleanup_verified=True
- Workspace removed, residual=0

---

## F. Negative Checks

| # | Check | Result |
|---|-------|--------|
| N1 | Non-existent lab start | Blocked (precheck_failures: no_vm_assigned) ✅ |
| N2 | `sudo` command | policy_rejected=True, reason=command_denied ✅ |
| N3 | `su -` command | policy_rejected=True, reason=command_denied ✅ |
| N4 | `cat ../etc/passwd` path traversal | policy_rejected=True, reason=path_traversal ✅ |
| N5 | `cat /etc/shadow` forbidden path | policy_rejected=True, reason=forbidden_path ✅ |
| N6 | adapter=None fail-closed | LAB_CLEANUP_FAILED, never K8s path (unit test) ✅ |
| N7 | `LinuxSandboxPolicy(allow_root=True)` | ValidationError at model level ✅ |
| N8 | K8s Lab 5 (cf019133) catalog | Still visible, unaffected ✅ |

---

## G. Post-run Audit

| Item | Result |
|------|--------|
| Active Linux sessions | 0 ✅ |
| Linux workspace residual | 0 (both smoke workspaces removed) ✅ |
| Tainted Linux sandbox | none ✅ |
| Catalog count | 6 (5 K8s + 1 Linux) ✅ |
| Linux lab visible | YES ✅ |
| No duplicate Linux lab | ✅ |
| K8s labs visible | 5 ✅ |
| No draft/internal lab visible | ✅ |
| No raw article text exposed | ✅ |
| No source_article_id exposed | ✅ |
| No host absolute path exposed | ✅ |
| No secret/token leakage | ✅ |
| LLM call count | 0 ✅ |
| Production VMID 500-599 untouched | ✅ |
| Concurrency unchanged | ✅ |
| K8s Lab 5 path unchanged | ✅ |
| Service health | `{"status":"healthy","proxmox":{"connected":true}}` ✅ |
| Error log (2 min window) | No entries ✅ |

---

## H. Known Limitations

- **Not Trusted Reader Pilot** — this smoke used an operator-controlled test account, not an external reader.
- **Not public launch** — feature flag `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` controls which labs are accessible.
- **Live LLM disabled** — 0 LLM calls, stub pipeline only.
- **Ordinary user article upload not open** — admin-curated pipeline only.
- **LinuxRuntimeAdapter remains allowlisted** — env var must be set with explicit lab UUIDs.
- **No OS-level process isolation** — workspace isolation is filesystem-level only (spike-level, not production-ready).
- **Intermediate path component TOCTOU** — LOW severity, no concurrent learner processes in v0.1.
- **Step 4 linux_no_residual_files removed** — this verifier belonged to post-complete verification, not a pre-complete step check. Cleanup is verified by `cleanup_verified=True` in `complete()`. See Section I.

---

## I. Issue Triage

### BLOCKER (found and fixed)

**BLOCKER-001: `lfp-step-4` `linux_no_residual_files` permanently blocks learner completion**

- **Root cause**: Step 4 (`linux_no_residual_files`) requires the workspace to contain zero files. But steps 1–3 require creating `demo/message.txt`. The workspace cannot be empty during an active session. The step 4 `do` text says "No manual cleanup is required" — directly contradicting the verifier precondition.
- **Impact**: `all_passed=False` on step 4 → `ready_to_complete=False` → `complete()` returns HTTP 409 `lab_not_ready_to_complete` → learner permanently blocked.
- **Fix**: Removed `linux_no_residual_files` from `lfp-step-4.linux_verify` in `data/lab_drafts.json`. Cleanup correctness is already verified by `cleanup_verified=True` after `complete()`.
- **Status**: FIXED. Step 4 now passes with no verifiers (completion acknowledgment step only).

### HIGH — None

### MEDIUM — None

### LOW

- **LOW-001**: Step 4 in the G-40 template was designed with `linux_no_residual_files` conceptually valid (post-cleanup verification) but placed incorrectly as a pre-complete step verifier. The UX description ("No manual cleanup required") and the verifier expectation (empty workspace) were mutually exclusive. Future lab templates should use step 4 as a no-verifier completion step.

### NOTE

- **NOTE-001**: Guided commands were executed operator-side (direct filesystem writes) rather than via a learner-facing exec API (which does not exist). This is the intended design for v0.1: the learner would use a terminal attached to the workspace. Terminal integration is a future task.
- **NOTE-002**: LOW TOCTOU attack surface (intermediate path component) is unchanged from G-39. No expansion during this smoke.
- **NOTE-003**: `workspace_manager.get_session()` returns None when called from a different Python process (the manager is in-process to the service). This is expected; operator smoke manipulated the workspace filesystem directly.

---

## J. Final Decision

**LINUX_LEARNER_RUNTIME_E2E_SMOKE_PASSED_WITH_NOTES**

The full learner lifecycle (Start → Step Check ×4 → Complete → Cleanup) passed on real service.  
One BLOCKER (lab template error in lfp-step-4) was found and fixed.  
All safety invariants confirmed. No Trusted Reader involvement. No public launch.

---

## K. Recommended Next Step

**Linux Reader-facing CTA Dry Run**

The learner runtime is validated. The lab draft is fixed. The feature flag is set.  
Next: verify the end-to-end reader → article CTA → lab start → complete path with a Linux-specific  
article, mirroring what was done for K8s Lab 5 in the Reader-facing Article CTA Dry Run (G-31).

---

## L. Modified Files

| File | Change |
|------|--------|
| `.env` | Added `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS=6c439064-4cad-4229-addb-36927128d565` |
| `data/lab_drafts.json` | Removed `linux_no_residual_files` from lfp-step-4.linux_verify (BLOCKER fix) |
| `CHANGELOG.md` | Added E2E Smoke Acceptance entry |
| `docs/labgen/LINUX_LEARNER_RUNTIME_E2E_SMOKE_ACCEPTANCE_RESULT_v0.1.md` | This file |

---

## M. Self-Check Results (No Prohibited Items)

| Check | Status |
|-------|--------|
| No TODO/FIXME (learner path) | ✅ |
| No placeholder-as-success | ✅ |
| No broad Linux enablement | ✅ (allowlist: 1 lab only) |
| Rollback path documented | ✅ (remove env var = blocked) |
| Learner not using internal/admin endpoint | ✅ |
| Linux Start gated by feature flag + allowlist | ✅ |
| No non-allowlisted Linux lab start | ✅ |
| No draft/internal Linux exposure | ✅ |
| Cleanup failure not hidden | ✅ |
| Residual not ignored | ✅ (0 residual confirmed) |
| Session LAB_CLOSED only after cleanup success | ✅ |
| Unsafe commands rejected | ✅ |
| Unsafe paths rejected | ✅ |
| adapter=None fail-closed (no K8s fallthrough) | ✅ |
| root/network not allowed | ✅ |
| source_article_id not exposed | ✅ |
| No secret/token exposure | ✅ |
| LLM calls = 0 | ✅ |
| No public article upload | ✅ |
| No URL scraping | ✅ |
| No customer pilot | ✅ |
| Production VMID 500-599 untouched | ✅ |
| Concurrency unchanged | ✅ |
| K8s regression clean | ✅ |
| Lab 5 regression clean | ✅ |
| Catalog regression clean | ✅ (6 labs, correct) |
| LOW TOCTOU not expanded | ✅ |

---

## N. Test Suite

- **Full suite**: 4286 passed, 249 warnings
- **Coverage**: 92.48% (≥90% gate: PASS)
- **Linux learner enablement tests**: 58 passed (test_labgen_linux_learner_enablement.py)
