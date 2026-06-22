# Linux Guided Practice Draft Template v0.1 — Result

**Task**: 5 of 7 in Linux Domain Proof sequence  
**Date**: 2026-06-22  
**Decision**: `LINUX_GUIDED_PRACTICE_DRAFT_TEMPLATE_READY_WITH_NOTES`  
**Commit**: (pending push — see git log after push)

---

## A. Summary

This task implements a deterministic, LLM-free Linux Guided Practice Draft Template for the article "Linux Files and Permissions Basics". The template produces a complete, reviewable, verifiable, and cleanable `LabDraft` with `target_domain=LINUX`. It can be generated, validated, and inspected by an admin, but **publish is always blocked** by `StaticValidator` (`linux.publish_blocked_until_runtime`) and will remain so until the Linux runtime adapter is fully implemented and rehearsal-gated.

---

## B. What Was Implemented

### New Files

| File | Description |
|------|-------------|
| `backend/labgen/linux_template.py` | `LinuxFilesPermissionsTemplate` — 4 guided steps, all 5 Linux verifier primitives, `LinuxSandboxPolicy`, `CleanupLinuxWorkspace`, `ai_tutor_context`. ~395 lines. |
| `tests/test_labgen_linux_guided_practice_draft_template.py` | 68 tests across 5 categories |

### Modified Files

| File | Change |
|------|--------|
| `backend/labgen/models.py` | Added `ai_tutor_context: Optional[str] = None` to `LabDraft` |
| `backend/labgen/stub_generator.py` | Added `generate_linux()` delegating to `LinuxFilesPermissionsTemplate` |
| `backend/labgen/stub_feasibility_classifier.py` | Added 4 Linux signal pattern lists; MEDIUM fix: /etc write vectors expanded |
| `backend/labgen/static_validator.py` | Added `_check_linux_verifiers_present()` to `_validate_linux()` |

---

## C. Template Design

### Lab: "Linux Files and Permissions Basics"

4 guided steps:

| Step | ID | Commands | Verifiers Used |
|------|----|----------|----------------|
| Create directory + file | `lfp-step-1` | `mkdir -p demo`, `printf 'hello labgen\n' > demo/message.txt` | `linux_directory_exists`, `linux_file_exists`, `linux_file_content_matches` |
| View file content | `lfp-step-2` | `cat demo/message.txt` | `linux_file_content_matches` |
| Change permissions | `lfp-step-3` | `chmod 600 demo/message.txt`, `stat -c "%a" demo/message.txt` | `linux_file_mode_matches` |
| Completion | `lfp-step-4` | (none — click Complete) | `linux_no_residual_files` |

All 5 Linux verifier primitives are exercised across the 4 steps.

### Sandbox Policy

- `allow_root=False`, `allow_network=False` (model-level validators, enforced by `LinuxSandboxPolicy.field_validator`)
- `workspace_root=/home/learner/workspace`
- Allowed commands: `mkdir`, `printf`, `echo`, `cat`, `chmod`, `stat`, `ls`, `rm`
- Denied commands: `sudo`, `su`, `apt-get`, `apt`, `yum`, `dnf`, `apk`, `systemctl`, `service`, `ssh`, `scp`, `curl`, `wget`
- Forbidden paths: `/etc`, `/root`, `/var`, `/proc`, `/sys`, `/dev`, `/boot`, `/home`

### Cleanup Contract

- `CleanupLinuxWorkspace(workspace_root=/home/learner/workspace)`
- `cleanup_paths=["/home/learner/workspace"]`
- `taint_on_cleanup_failure=True`
- `residual_checks`: workspace_removed_or_empty, no_session_owned_processes, credentials_revoked, terminal_closed
- `forbidden_cleanup_paths`: `/`, `/home`, `/tmp`, `/etc`, `/var`, `/root`

---

## D. Test Coverage

| Category | Tests | Description |
|----------|-------|-------------|
| A: Template Generation | 25 | build_draft output, all 5 primitives, sandbox policy fields, cleanup fields, ai_tutor_context, no placeholders |
| B: FeasibilityClassifier | 8 | directly_ready, partially_ready, reject (sudo, systemctl, /etc, curl), K8s not confused with Linux |
| C: StaticValidator | 14 | all Linux checks including new `linux.verifiers_present`; publish blocked; valid draft passes all except publish gate |
| D: Catalog/Publish Isolation | 5 | publish_status always DRAFT, never in LearnerCatalogService, StaticValidator publish gate |
| E: K8s Regression | 16 | ai_tutor_context=None for K8s labs, K8s validation unchanged, no cross-contamination |

**Total new tests**: 68  
**Full suite result**: 4065 passed, 93.27% coverage

---

## E. Security Review

### Safety-reviewer (B-class change) — PASSED

No BLOCKER/HIGH findings.

**MEDIUM found and fixed**: `_LINUX_SYSTEM_MODIFY_PATTERNS` was missing `/etc` write vectors via `cp`, `mv`, `tee`, `sed -i`, `truncate`, `install`. Added 4 additional patterns to cover all indirect write methods.

Final patterns (8 total in `_LINUX_SYSTEM_MODIFY_PATTERNS`):
- `(edit|modify|change|write to|update) /etc/\w`
- `(echo|printf|>>|>) .../etc/\w`
- `chmod \S+ /etc/\w`
- `chown \S+ /etc/\w`
- `(cp|mv) \S+ /etc/\w`
- `tee .../etc/\w`
- `sed (-i|--in-place) .../etc/\w`
- `(truncate|install) .../etc/\w`

### TOCTOU LOW (inherited from G-39)

This task does **not** expand the TOCTOU attack surface. The LOW residual from G-39 (`lstat()` on intermediate path components is not atomic with final `_recheck_containment()`) applies only to the `LinuxVerifyClientAdapter` file-read operations, which are not invoked here (template generation is pure Python model construction). The `LinuxFilesPermissionsTemplate` calls no filesystem operations.

**Attack surface delta**: None. The LOW limitation is documented and inherited unchanged.

---

## F. Invariants Preserved

| Invariant | Status |
|-----------|--------|
| Linux lab never published | ✅ `linux.publish_blocked_until_runtime` always fires |
| Linux lab never in learner catalog | ✅ publish_status=DRAFT, LearnerCatalogService filters DRAFT |
| No Linux catalog entry created | ✅ confirmed by catalog isolation tests |
| No Linux internal rehearsal started | ✅ not implemented in this task |
| No Linux trusted reader pilot | ✅ not implemented in this task |
| No live LLM calls | ✅ `LinuxFilesPermissionsTemplate.build_draft()` is pure Python |
| LLM call count = 0 | ✅ verified by test (`test_generate_linux_makes_no_lm_calls`) |
| K8s path zero regression | ✅ 16 regression tests; existing test suite unchanged |
| Production VMID 500-599 untouched | ✅ no VM operations |
| K8s verifier/runtime behavior unchanged | ✅ `linux_verifier_svc` param default=None, K8s path unchanged |
| No public article upload | ✅ no new endpoint added |
| `ai_tutor_context` backward compatible | ✅ defaults to `None` for all existing K8s labs |

---

## G. Known Limitations

### NOTES

- **N-01 (ai_tutor_context)**: The `ai_tutor_context` field is populated by the template but the live LLM integration is not active. Context-only mode is declared in the field content. This is by design for v0.1.
- **N-02 (stub generate_linux)**: `LabDraftGeneratorStub.generate_linux()` currently only supports the `LINUX_FILES_PERMISSIONS` template. Future articles will require new template classes or a parameterizable generator.

### LOW (inherited, unchanged)

- **L-01 (TOCTOU intermediate paths)**: As documented in G-39 Hardening result, `lstat()` on intermediate path components is not atomic with `_recheck_containment()`. No concurrent learner processes exist at this stage, so exploitability is nil. This LOW carries forward.

---

## H. Next Steps (Contract Section 7, Task 6 of 7)

**Task 6**: Linux Internal Rehearsal Bridge  
- Admin-only `POST /internal/linux-rehearsal-sessions` or extend existing `POST /internal/rehearsal-sessions` to support LINUX domain
- Linux runtime not yet available → rehearsal can be conducted in "static review mode" (admin reads draft, confirms content without live execution)
- Purpose: enable admin to mark `rehearsal_completed=True` on a Linux draft before any publish gate decision

**Task 7**: Linux Trusted Reader Pilot (blocked until Task 6 + Linux runtime available)

---

## I. Decision

`LINUX_GUIDED_PRACTICE_DRAFT_TEMPLATE_READY_WITH_NOTES`

The template is complete, all tests pass, safety-reviewer cleared (no BLOCKER/HIGH), MEDIUM fixed, K8s regression clean, LLM=0, production VMID untouched, publish permanently blocked by StaticValidator. NOTES are non-blocking documentation of known v0.1 constraints.
