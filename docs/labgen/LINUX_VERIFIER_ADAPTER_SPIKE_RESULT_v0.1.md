# Linux Verifier Adapter Spike — Result v0.1

**Gate:** LINUX_VERIFIER_ADAPTER_SPIKE_READY_WITH_NOTES  
**Date:** 2026-06-22  
**Task:** Linux Domain Proof Task 3 of 7  
**Executed by:** Claude Code (senior dev + ops)

---

## A. Executive Summary

| Item | Value |
|------|-------|
| Final Decision | **LINUX_VERIFIER_ADAPTER_SPIKE_READY_WITH_NOTES** |
| Adapter Implemented | `LinuxVerifyClientAdapter` + `LinuxVerifierService` |
| Primitives Supported | 5 of 5 (file_exists, directory_exists, file_content_matches, file_mode_matches, no_residual_files) |
| Linux Lab Published | **No** |
| K8s Path Changed | **No** |
| LLM Call Count | **0** |
| Tests Added | 48 new tests |
| Coverage | 93.38% (3933 total tests) |
| Pre-push | PASS |
| Codex | PASS |
| safety-reviewer | PASS (no BLOCKER/HIGH) |

---

## B. North Star Alignment

> 读了能做，做了就懂

This spike proves the verifier layer is replaceable by domain:

- `LinuxVerifierService` is the exact structural peer of `VerifierService` (K8s)
- General Experiment Core (`StepProgressionService`) dispatches based on `draft.target_domain`
- Neither verifier knows about the other; domain selection is clean
- K8s domain proof path: unchanged
- Linux labs: never published, never learner-visible, never catalog-visible
- No live LLM, no public launch, no customer pilot, no production VM touched

The Linux verifier spike confirms that **General Experiment Core + Replaceable Domain Verifier** is architecturally viable.

---

## C. Adapter Design

### Adapter Class

**`LinuxVerifyClientAdapter`** (`backend/labgen/linux_verifier_client.py`)
- Bound to a single `WorkspaceSession` + `LinuxWorkspaceManager`
- All path resolution via `self._wm.resolve_path(self._ws, rel_path)`
- `WorkspacePathEscapeError` propagates (not swallowed); `LinuxVerifierService` catches it
- No subprocess, no shell=True, no arbitrary command execution
- Pure Python stdlib: `os`, `os.stat`, `open`, `os.walk(followlinks=False)`

**`LinuxVerifierService`** (`backend/labgen/linux_verifier_client.py`)
- Orchestration layer: workspace session lookup → path pre-validation → primitive dispatch → `VerifyResult`
- `workspace_session_id` = lab `session_id` by convention (same key)
- `detail` field never contains host absolute paths, tokens, kubeconfig, or raw file content
- Content mismatch: "content redacted" message (never echoes actual content)
- All detail strings capped at 256 chars

### Path Resolver

- Source: `LinuxWorkspaceManager.resolve_path()` (from linux_workspace.py Task 2)
- Rejects: empty path, absolute path, `..` traversal, symlink escape (via `os.path.realpath` + containment check), sibling prefix escape
- Pre-validation in `LinuxVerifierService.check()` before any primitive call
- Secondary guard: `WorkspacePathEscapeError` caught in dispatch try/except

### Primitive Handlers

| Primitive | Pass Condition | FAIL Safety |
|-----------|---------------|-------------|
| `linux_file_exists` | path is regular file | "exists_but_not_file" if dir; "not_found" if missing |
| `linux_directory_exists` | path is directory | "exists_but_not_directory" if file; "not_found" if missing |
| `linux_file_content_matches` | file contains expected string | content redacted on mismatch; file_too_large if > max_output_bytes |
| `linux_file_mode_matches` | octal mode matches expected | safe diff (expected vs actual mode only, no content) |
| `linux_no_residual_files` | workspace removed or empty | count + max 3 relative paths |

### Result Format

All results use existing `VerifyResult` model (no schema change):

```
VerifyResult:
  session_id: str
  verify_id: str
  verify_type: str          # e.g. "linux_file_exists"
  passed: bool
  error_code: Optional[str] # stable FailureReason value
  failure_reason: Optional[str]
  detail: str               # safe, learner-visible, ≤256 chars
```

### New FailureReason Codes (11)

| Code | Trigger |
|------|---------|
| `linux.workspace_not_found` | Workspace session not in manager |
| `linux.workspace_not_active` | Session closed or tainted |
| `linux.path_escape` | Absolute path / traversal / symlink escape |
| `linux.file_not_found` | File missing or exists-but-not-file |
| `linux.directory_not_found` | Dir missing or exists-but-not-directory |
| `linux.content_mismatch` | Content does not contain expected string |
| `linux.file_too_large` | File exceeds max_output_bytes |
| `linux.mode_mismatch` | Octal mode differs from expected |
| `linux.residual_files_found` | Workspace has files after cleanup |
| `linux.verify_type_not_supported` | Missing required field or unknown type |
| `linux.verifier_not_configured` | StepProgressionService has no linux_verifier_svc |

### StepProgressionService Update

- New optional param: `linux_verifier_svc: Optional[LinuxVerifierService] = None`
- When `draft.target_domain == LabDomainType.LINUX`:
  - If `linux_verifier_svc is None` → early return with `LINUX_VERIFIER_NOT_CONFIGURED`
  - Else → dispatch `current_step.linux_verify` templates to `linux_verifier_svc`
- K8s path (`else` branch): **zero changes**

---

## D. Spike Scenario Result

**Scenario:** Linux Files and Permissions verifier smoke

| Check | Type | Expected | Result |
|-------|------|----------|--------|
| `demo/` exists | `linux_directory_exists` | PASS | **PASS** |
| `demo/message.txt` exists | `linux_file_exists` | PASS | **PASS** |
| `demo/message.txt` contains "hello labgen" | `linux_file_content_matches` | PASS | **PASS** |
| `demo/message.txt` mode = 600 | `linux_file_mode_matches` | PASS | **PASS** |
| Content mismatch "wrong content" | `linux_file_content_matches` | FAIL safe | **FAIL** (`linux.content_mismatch`, detail: "[content redacted]") |
| Path escape `../message.txt` | — | REJECT safe | **FAIL** (`linux.path_escape`) |
| Forbidden absolute `/etc/passwd` | — | REJECT safe | **FAIL** (`linux.path_escape`, `/etc/passwd` not in detail) |
| After cleanup + session close | `linux_no_residual_files` | session not active | **FAIL** (`linux.workspace_not_active`) |
| Verify workspace dir removed | external check | not exist | **PASS** (dir removed) |

---

## E. Safety Validation

| Check | Result |
|-------|--------|
| Path escape via `..` | Rejected before adapter call |
| Absolute path `/etc/passwd` | Rejected before adapter call |
| `/root/.bashrc` | Rejected before adapter call |
| Sibling prefix `/tmp/labgen-.../sess_evil` | Rejected by `startswith(workspace + os.sep)` |
| Symlink to outside workspace | Rejected by `os.path.realpath` + containment check |
| Shell glob `*.txt` treated as literal | Safe — no glob expansion |
| No subprocess in LinuxVerifyClientAdapter | Confirmed by AST import analysis |
| No shell=True call | Confirmed (no subprocess import) |
| No sensitive content in detail | Confirmed — content mismatch uses "[content redacted]" |
| No host absolute path in detail | Confirmed — only `rel_path` and fixed strings |
| max_output_bytes cap | Enforced in `file_content_matches` |
| `os.walk(followlinks=False)` | Explicit — no symlink traversal in residual scan |

**MEDIUM (spike limitation, documented):** TOCTOU window between `resolve_path()` and `open()` on the resolved absolute path. Only exploitable if a concurrent lab user process has write access to the workspace. Not applicable to spike (workspace is never exposed to learner processes). Requires `O_NOFOLLOW` or `os.fstat` re-verification for production hardening.

---

## F. K8s Regression

| Check | Result |
|-------|--------|
| K8s verifier path untouched | **PASS** — only new `else` branch in StepProgressionService |
| K8s verifier tests | **PASS** — existing tests unchanged |
| Lab 5 article-linked K8s tests | **PASS** |
| Catalog count | **Unchanged** (5 published labs) |
| StaticValidator Linux publish block | **PASS** — Linux labs remain `publish_blocking` |
| LinuxVerifyType enum (5 values) | **PASS** |
| LabDomainType.LINUX | **PASS** |

---

## G. Limitations

- **Linux lab not published.** StaticValidator blocks Linux domain publish. This is by design.
- **Linux verifier not production-hardened.** TOCTOU (see §E) must be fixed before production use.
- **Linux terminal / full learner session not implemented.** No learner terminal, no catalog entry.
- **Linux internal rehearsal not yet done.** StepProgressionService now supports it, but no rehearsal was run.
- **LLM disabled.** All generation is stub or manual.
- **Workspace isolation is process-level only.** No OS-level cgroups, seccomp, user namespaces.
- **Routes.py not updated.** `linux_verifier_svc` is not wired into HTTP endpoints. Test uses direct service construction.
- **No concurrent workspace access testing.** Spike is single-threaded.

---

## H. Tests and Scans

| Category | Count | Result |
|----------|-------|--------|
| A. Primitive tests | 18 | PASS |
| B. Path safety tests | 10 | PASS |
| C. Adapter selection tests | 5 | PASS |
| D. Step progression integration-lite | 7 | PASS |
| D2. Full spike scenario | 1 | PASS |
| E. Regression tests | 7 | PASS |
| **Total new** | **48** | **PASS** |
| Full suite | 3933 | PASS |
| Coverage | 93.38% | PASS (≥75%) |
| 8-item security scan | — | PASS |
| Codex | — | PASS |
| pre-commit | — | PASS |
| pre-push | — | PASS |
| safety-reviewer | — | No BLOCKER/HIGH |

---

## I. Issue Triage

| Severity | Description | Status |
|----------|-------------|--------|
| MEDIUM | TOCTOU symlink race between resolve_path and open() | Documented, spike-era acceptable |
| LOW | `os.walk` should explicitly pass `followlinks=False` | **Fixed** before commit |
| NOTE | Domain dispatch in StepProgressionService: no K8s fallthrough | Confirmed |
| NOTE | Host absolute paths not in VerifyResult.detail | Confirmed |
| NOTE | detail capped at 256 chars | Confirmed |

---

## J. Final Decision

**LINUX_VERIFIER_ADAPTER_SPIKE_READY_WITH_NOTES**

Rationale:
- 5/5 verifier primitives implemented and tested
- Path safety fail-closed: all escape vectors caught
- No sensitive content leakage
- K8s regression: zero
- Linux lab never published
- LLM call count: 0
- TOCTOU is a documented spike limitation, not a blocker for the spike gate

---

## K. Recommended Next Step

**Linux Guided Practice Draft Template**

Rationale: Runtime (Task 2) + Verifier (Task 3) spikes are both READY_WITH_NOTES. The next logical step is to draft a complete Linux lab template (with all 5 verify primitives, cleanup, sandbox policy) and validate it through the admin review path — proving the full end-to-end loop without exposing to learners.

Alternative: **Linux Verifier Adapter Hardening** — fix TOCTOU before drafting labs.

Both are valid; recommend Guided Practice Draft Template first (parallel path), then Hardening before any real Linux lab exposure.

---

## L. Modified Files

| File | Change |
|------|--------|
| `backend/labgen/linux_verifier_client.py` | NEW — LinuxVerifyClientAdapter + LinuxVerifierService |
| `backend/labgen/failure_reasons.py` | MODIFIED — 11 new Linux failure reason codes |
| `backend/labgen/step_progression_service.py` | MODIFIED — linux_verifier_svc param + domain dispatch |
| `tests/test_labgen_linux_verifier_adapter_spike.py` | NEW — 48 tests |
| `docs/labgen/LINUX_VERIFIER_ADAPTER_SPIKE_RESULT_v0.1.md` | NEW — this document |
| `CHANGELOG.md` | MODIFIED — Unreleased entry |
