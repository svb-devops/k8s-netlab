# Linux Verifier Adapter Hardening — Result v0.1

**Gate:** LINUX_VERIFIER_ADAPTER_HARDENED_WITH_NOTES
**Date:** 2026-06-22
**Task:** Linux Domain Proof Task 4 of 7 (Hardening sprint, not Guided Practice Draft Template)
**Executed by:** Claude Code (senior dev + ops)

---

## A. Executive Summary

| Item | Value |
|------|-------|
| Final Decision | **LINUX_VERIFIER_ADAPTER_HARDENED_WITH_NOTES** |
| TOCTOU MEDIUM (from Spike) | **CLOSED** — three-layer mitigation implemented |
| Residual Risk | Intermediate path component TOCTOU — **downgraded to LOW** (workspace not exposed to concurrent learner processes) |
| Linux Lab Published | **No** |
| K8s Path Changed | **No** |
| LLM Call Count | **0** |
| Tests Added | 64 new tests (hardening + inside-workspace symlink) |
| Pre-push security scan | PASS |
| Codex | PASS (P1 found and fixed: lstat on original path, not realpath) |
| safety-reviewer | PASS (no BLOCKER/HIGH; 2 MEDIUM found and fixed before commit) |

---

## B. TOCTOU Resolution

### Spike-era finding

The Spike (G-38) documented a MEDIUM TOCTOU window between `resolve_path()` (which calls `os.path.realpath()`) and the subsequent `open()` on the resolved absolute path. The concern: if a symlink is inserted into the workspace between those two calls, the open would follow it.

### Three-layer mitigation implemented

| Layer | Mechanism | What it catches |
|-------|-----------|-----------------|
| L1 (inherited) | `resolve_path()` → `os.path.realpath()` | Pre-existing symlinks at check time |
| L2 (new) | `os.lstat()` on resolved path | Symlinks added **after** resolve_path() at the target |
| L3 (new) | `_recheck_containment()` before open | Re-resolves and re-validates workspace containment |
| L4 (new) | `O_NOFOLLOW` via `_open_nofollow()` | OS-level: final-component symlink rejected at open time |

All four layers are now in production code. Layers 2–4 directly close the TOCTOU window documented in the spike.

### Residual limitation (downgraded to LOW)

**Intermediate path component TOCTOU**: if an intermediate directory in the resolved path is replaced with a symlink _after_ `resolve_path()` but _before_ `open()`, neither `_recheck_containment()` nor `O_NOFOLLOW` can catch it without OS-level `openat()`.

**Why LOW (not MEDIUM):**
- The workspace sandbox root (`/tmp/labgen-linux-sandboxes/`) is not exposed to learner processes in v0.1.
- There are no concurrent write-capable processes (lab session is single-threaded).
- The window is microseconds between Python operations, not a prolonged check-use gap.
- Production hardening path: OS-level container isolation (user namespaces) or Python `openat()`-based traversal.

This limitation is documented in the module docstring.

---

## C. Hardening Changes

### `backend/labgen/linux_verifier_client.py`

**New module-level helpers:**
- `_recheck_containment(abs_path, workspace_path)` — re-resolves abs_path via `os.path.realpath()` and checks workspace containment; raises `WorkspacePathEscapeError` on escape
- `_open_nofollow(abs_path, max_bytes)` — opens file with `O_RDONLY | O_NOFOLLOW`; maps `ELOOP` → `WorkspacePathEscapeError`
- `_validate_octal_mode(mode_str)` — validates octal format before stat calls

**Hardened primitives:**

| Primitive | Before | After |
|-----------|--------|-------|
| `file_exists` | `os.path.isfile()` (follows symlinks) | `os.lstat()` + `S_ISLNK` check |
| `directory_exists` | `os.path.isdir()` (follows symlinks) | `os.lstat()` + `S_ISLNK` check |
| `file_content_matches` | `open()` | `os.lstat()` + `_recheck_containment()` + `_open_nofollow()` |
| `file_mode_matches` | `os.stat()` (follows symlinks) | `os.lstat()` |
| `no_residual_files` | `os.walk()` (symlink-to-dirs invisible) | `os.walk()` + lstat loop; symlink-to-dirs counted as residuals |

**Service layer additions:**
- `"symlink_rejected"` reason → `FailureReason.LINUX_PATH_ESCAPE` (all 4 path-taking primitives)
- `_validate_octal_mode()` called before `file_mode_matches` → `LINUX_VERIFY_TYPE_NOT_SUPPORTED` on invalid format
- `"permission_error_during_scan"` → `LINUX_RESIDUAL_FILES_FOUND`

### `backend/labgen/linux_workspace.py`

**`list_files_recursive()` aligned with `no_residual_files()`:**
- Added `followlinks=False` to `os.walk()`
- Added symlink-to-dir detection loop (same pattern as `no_residual_files()`)
- Eliminates semantic inconsistency flagged by safety-reviewer

---

## D. Codex Review Finding and Resolution

Codex review ran against `main` before commit and found one P1:

| Severity | Finding | Resolution |
|----------|---------|------------|
| P1 | `lstat()` ran on `resolve_path()` return value (realpath-resolved target), not the original unresolved path. Inside-workspace symlinks (`link.txt → ./real.txt`) were followed by `resolve_path()`, so `lstat` saw a regular file and returned `True` — bypassing the symlink-rejected contract. | **Fixed**: `lstat()` now runs on `os.path.join(ws_path, rel_path)` (original unresolved path). `resolve_path()` is still called first for traversal/escape validation. All symlinks — including inside-workspace — are now rejected fail-closed. |

3 new tests added: `TestSymlinkInsideWorkspace` (inside-workspace symlink rejected for file_exists, directory_exists, file_content_matches).

---

## E. Safety-Reviewer Findings and Resolutions

safety-reviewer result: **No BLOCKER, No HIGH**

| Severity | Finding | Resolution |
|----------|---------|------------|
| MEDIUM | Dead code `if not os.path.exists()` in `file_mode_matches()` after `lstat` success — semantic inconsistency risk | **Removed** before commit |
| MEDIUM | `list_files_recursive()` in linux_workspace.py didn't include symlink-to-dirs, inconsistent with `no_residual_files()` | **Fixed** — aligned with same lstat loop pattern |
| LOW | permission_denied test wouldn't cover `permission_error_during_scan` path when running as root | **Fixed** — replaced chmod test with `monkeypatch` on `os.walk` to inject `PermissionError` |
| LOW | Subprocess guard test used relative path — fails if CWD is not project root | **Fixed** — replaced with `Path(__file__).parent.parent / ...` absolute path |

---

## E. Test Suite

### New: `tests/test_labgen_linux_verifier_hardening.py` (61 tests)

| Category | Tests | Result |
|----------|-------|--------|
| A. TOCTOU — lstat layer (monkeypatch bypass resolve_path) | 8 | PASS |
| B. O_NOFOLLOW layer (`_open_nofollow` direct) | 4 | PASS |
| C. `_recheck_containment` | 3 | PASS |
| D. `file_content_matches` three-layer integration | 6 | PASS |
| E. Symlink-to-dir in `no_residual_files` | 5 | PASS |
| F. `permission_error_during_scan` (mocked) | 1 | PASS |
| G. `_validate_octal_mode` | 5 | PASS |
| H. Workspace absolute path not in reason | 2 | PASS |
| I. Result redaction | 8 | PASS |
| J. StaticValidator Linux publish still blocked | 2 | PASS |
| K. K8s regression | 7 | PASS |
| L. No subprocess import (AST check) | 1 | PASS |
| Misc | 9 | PASS |

### Full suite

| Metric | Value |
|--------|-------|
| Total tests | ~4000+ |
| Coverage | ≥ 93% |
| Pre-push security scan | PASS |
| Codex | PASS |
| safety-reviewer | PASS |

---

## F. Security Guarantees (After Hardening)

| Attack Vector | Defense | Layer |
|---------------|---------|-------|
| Pre-existing symlink to outside workspace | `resolve_path()` → `realpath()` containment check | L1 (inherited) |
| Inside-workspace symlinks (any target) | `lstat()` on original unresolved path (Codex P1 fix) | L2 (new) |
| Symlink inserted after resolve_path | `lstat()` on original path sees new symlink | L2 (new) |
| Symlink inserted between lstat and open | `_recheck_containment()` re-resolves | L3 (new) |
| Final-component symlink at open time | `O_NOFOLLOW` → `ELOOP` | L4 (new) |
| Symlink-to-dir in residual scan | `lstat()` loop in `no_residual_files` | L2 (new) |
| Absolute paths in VerifyResult.detail | Only `rel_path` and fixed strings used | Inherited |
| File content in VerifyResult.detail | `[content redacted]` for mismatch | Inherited |
| Octal injection in mode check | `_validate_octal_mode()` format guard | New |

---

## G. Remaining Limitations

- **Linux lab not published.** StaticValidator still blocks. By design.
- **Intermediate path component TOCTOU.** Documented, downgraded to LOW.
- **O_NOFOLLOW on Windows.** Not applicable — this system runs on Linux only.
- **Workspace isolation is process-level only.** No OS-level cgroups, seccomp, user namespaces.
- **Routes.py not updated.** `linux_verifier_svc` is not wired into HTTP endpoints.
- **Linux internal rehearsal not yet done.**

---

## H. Issue Triage

| Severity | Description | Status |
|----------|-------------|--------|
| ~~MEDIUM~~ | TOCTOU symlink race between resolve_path and open() | **CLOSED** — three-layer mitigation |
| LOW | Intermediate path component TOCTOU | Documented in module docstring; production fix requires container isolation |
| NOTE | O_NOFOLLOW Linux-specific | Documented; Windows not in scope |
| NOTE | Linux lab publish remains blocked by StaticValidator | Confirmed — by design |

---

## I. K8s Regression

| Check | Result |
|-------|--------|
| K8s verifier path untouched | PASS |
| K8s verifier tests | PASS |
| Lab 5 article-linked K8s tests | PASS |
| Catalog count | Unchanged (5 published labs) |
| StaticValidator Linux publish block | PASS |

---

## J. Modified Files

| File | Change |
|------|--------|
| `backend/labgen/linux_verifier_client.py` | HARDENED — lstat, _recheck_containment, _open_nofollow, _validate_octal_mode |
| `backend/labgen/linux_workspace.py` | FIXED — list_files_recursive aligned with no_residual_files |
| `tests/test_labgen_linux_verifier_hardening.py` | NEW — 61 hardening tests |
| `CHANGELOG.md` | MODIFIED — Unreleased entry |

---

## K. Final Decision

**LINUX_VERIFIER_ADAPTER_HARDENED_WITH_NOTES**

Rationale:
- TOCTOU MEDIUM from spike: **closed** with three-layer mitigation (lstat + recheck_containment + O_NOFOLLOW)
- Residual intermediate-component TOCTOU: **legitimately LOW** (not exploitable without concurrent learner write access)
- safety-reviewer: no BLOCKER/HIGH; all MEDIUM findings fixed before commit
- Codex: PASS
- K8s regression: zero
- Linux lab never published, LLM call count: 0
- Coverage ≥ 93%

---

## L. Recommended Next Step

**Linux Guided Practice Draft Template** (Task 5 of 7)

The verifier is now hardened. The next logical step is drafting a complete Linux lab template using all 5 verifier primitives and validating it through the admin review path — proving the full end-to-end loop without exposing to learners.

Constraint: Linux lab must not be published; StaticValidator blocks it by design. Admin review path only.
