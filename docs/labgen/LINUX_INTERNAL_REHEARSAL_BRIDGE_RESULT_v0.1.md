# Linux Internal Rehearsal Bridge — Result v0.1

**Gate ID**: G-41  
**Date**: 2026-06-22  
**Decision**: LINUX_INTERNAL_REHEARSAL_BRIDGE_READY_WITH_NOTES  
**Coverage**: 92.44% (4136 tests, +70 new)

---

## A. What Was Built

Admin-only internal rehearsal bridge for Linux domain DRAFT LabDrafts.
Proves the complete chain: Linux workspace creation → guided command execution
→ Linux verifier checks → complete → cleanup → residual=0 → LAB_CLOSED + rehearsal_completed.

### New files
- `backend/labgen/linux_rehearsal_service.py` — LinuxRehearsalService
- `tests/test_labgen_linux_internal_rehearsal_bridge.py` — 70 tests (A-F categories)

### Modified files
- `backend/labgen/failure_reasons.py` — 18 new `linux_rehearsal.*` codes
- `backend/labgen/linux_runtime_adapter.py` — `workspace_manager` property
- `backend/labgen/routes.py` — `linux_rehearsal_router` (5 endpoints, dual-auth)
- `backend/main.py` — router registration

---

## B. Rehearsal Chain Proof

| Step | Result |
|------|--------|
| Draft ID | `LinuxFilesPermissionsTemplate` (lab_id from art-linux-files-001) |
| Rehearsal session ID | UUID, session_type=INTERNAL_REHEARSAL, vm_id="linux-rehearsal" |
| Step 1: mkdir demo + write message.txt | PASS (make_directory + write_file) |
| Step 2: cat demo/message.txt + content check | PASS (file_content_matches) |
| Step 3: chmod 600 + mode check | PASS (file_mode_matches) |
| ready_to_complete after step 3 | YES (step 4 is cleanup-phase only) |
| complete → cleanup | cleanup_verified=True |
| residual scan | has_residual=False |
| Final session status | LAB_CLOSED |
| rehearsal_completed on draft | True |

---

## C. Safety Invariants (all verified)

| Invariant | Status |
|-----------|--------|
| Linux publish still blocked | YES — StaticValidator `linux.publish_blocked_until_runtime` |
| Linux catalog entry created | NO — never appears in LearnerCatalogService |
| Learner visible | NO — INTERNAL_REHEARSAL session_type excluded |
| K8s path unchanged | YES — 4066 pre-existing tests still pass |
| LLM call count | 0 |
| VMID 500-599 touched | NO — vm_id="linux-rehearsal" sentinel |
| shell=True used | NO — all commands Python-native or execute_command(argv) |
| Path escape possible | NO — workspace_manager containment + verifier path guard |

---

## D. Command Safety Policy

`_safe_exec_command` intercepts in priority order:

1. `printf '...' > file` → `write_file()` (Python-native)
2. `echo '...' > file` → `write_file()` (Python-native)
3. Shell metachar scan (`|`, `;`, `&`, `` ` ``, `$`, etc.) → `policy_rejected`
4. `mkdir [-p] <dir>` → `make_directory()` (Python-native)
5. `chmod <mode> <file>` → `chmod_file()` (Python-native)
6. Denied commands (`sudo`, `su`, `systemctl`, `curl`, `wget`, `nc`, ...) → `policy_rejected`
7. Safe allowlist (`cat`, `stat`, `ls`, ...) → `execute_command(argv)` (shell=False)

---

## E. Security Review

### safety-reviewer (B-class)
- Found HIGH: Cross-admin session mutation — 3 mutating endpoints lacked session ownership check.
- **Fixed**: Added `session.student_username != admin → 403` to execute/complete/abort endpoints.

### Codex (P2)
- Found P2: K8s session ID could be passed to Linux rehearsal paths — no session_type guard.
- **Fixed**: `LinuxRehearsalService.get_session()` now validates `session_type == INTERNAL_REHEARSAL`.

Both issues fixed before commit. No remaining BLOCKER or HIGH.

---

## F. Test Categories

| Category | Tests | Description |
|----------|-------|-------------|
| A. Auth | 8 | Admin allowed, session isolation, cross-admin guard (service layer) |
| B. Draft state | 11 | Missing/unsafe sandbox policy, missing cleanup, missing verifiers, placeholder rejection |
| C. Rehearsal flow | 13 | Full lifecycle: create → 3 steps → complete → cleanup → LAB_CLOSED |
| D. Safety | 20 | sudo/systemctl/curl/wget/pipe/semicolon/backtick/$ rejected; path escape rejected; publish blocked; abort non-rehearsal_completed |
| D2. Safe-exec unit | 15 | Per-command intercept verification (empty, mkdir, printf, chmod, cat, stat, policy rejects) |
| E. Catalog isolation | 5 | Linux draft invisible before/after rehearsal; catalog count unchanged; K8s Lab 5 unaffected |
| F. Regression | 8 | Template construct, K8s domain rejection, StaticValidator unchanged, workspace_manager property, FailureReason codes |

---

## G. Notes

- **TOCTOU LOW** inherited from G-39, attack surface unchanged by this task.
- Step 4 (`linux_no_residual_files` verifier) is a cleanup-phase check, not a regular step check. `ready_to_complete` is set after step 3 when only cleanup-phase verifiers remain.
- Singleton `_linux_rehearsal_svc` in routes uses CPython GIL for init-race safety (acceptable for this admin-only path).
- Rehearsal sessions share `LabSessionRepository` with K8s sessions; `get_session()` session_type guard prevents K8s sessions from leaking into Linux paths.

---

## H. Next Step

**Linux Trusted Reader Pilot** (Task 7 of 7) — run the complete rehearsal chain as a live admin operation against the real service, then produce the final Linux Domain Proof closure report.
