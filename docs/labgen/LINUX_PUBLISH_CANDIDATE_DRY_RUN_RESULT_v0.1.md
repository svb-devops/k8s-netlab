# Linux Publish Candidate Dry Run Result v0.1

**Gate**: G-43 — Linux Publish Candidate Dry Run  
**Final Decision**: LINUX_PUBLISH_CANDIDATE_DRY_RUN_READY  
**Date**: 2026-06-23  
**Commit**: c0bc4ce

---

## Preflight Gate (G-42 residual review)

| Item | Status | Decision |
|------|--------|----------|
| G-42 MEDIUM (WorkspacePathEscapeError classification) | CLOSED — merged in commit 3e5e011 | ✅ Not blocking |
| G-39 TOCTOU LOW (inherited, not expanded) | Remains LOW, scope not widened | ✅ Not blocking |
| G-42 NOTE (779 test dirs) | Expected test infrastructure | ✅ Not blocking |

Preflight conclusion: no open BLOCKER/HIGH/MEDIUM. **Dry run allowed.**

---

## Implementation Summary

### New Files
- `backend/labgen/publish_candidate_dry_run_service.py` — `PublishCandidateDryRunService`, 6-gate read-only validation
- `tests/test_labgen_linux_publish_candidate_dry_run.py` — 58 tests (A–J categories)

### Modified Files
- `backend/labgen/routes.py` — `POST /api/labgen/drafts/{id}/publish-candidate-dry-run` (admin-only)

---

## 6-Gate Evaluation Results (against LinuxFilesPermissionsTemplate draft)

| Gate | ID | Result | Notes |
|------|----|--------|-------|
| 1 | admin_gate | PASS | target_domain=LINUX, publish_status=DRAFT, rehearsal_completed=True |
| 2 | validation_gate | PASS | linux.publish_blocked_until_runtime recognised as expected boundary; no unexpected PUBLISH_BLOCKING |
| 3 | internal_rehearsal_gate | PASS | rehearsal_completed=True + LAB_CLOSED INTERNAL_REHEARSAL session with cleanup_verified=True |
| 4 | runtime_verifier_cleanup_gate | PASS | linux_sandbox_policy + linux_cleanup + linux_verify present; no K8s verify entries |
| 5 | content_quality_gate | PASS | title/description/steps/ai_tutor_context all populated, no placeholders |
| 6 | safety_gate | PASS | allow_root=False, allow_network=False, no denied commands, no forbidden paths, no live LLM marker |

**publish_candidate_ready = True**

---

## Safety Review (B-class, pre-commit)

Two MEDIUM issues found and fixed before commit:

### MEDIUM-1: First-word-only command scan (safety gate)
- **Risk**: `env sudo cmd` / `bash -c "sudo..."` bypassed first-word check
- **Fix**: Changed to full token scan via `re.split(r"[\s\$\(\)\{\}\;\|\&\`\"\']+", cmd)` — all shell metacharacter separators split before checking against `_SAFETY_DENIED_COMMANDS`
- **Regression test**: `test_env_sudo_wrapper_caught_by_token_scan`, `test_bash_c_sudo_caught_by_token_scan`

### MEDIUM-2: Path traversal not caught by startswith (safety gate)
- **Risk**: `../etc/passwd` not caught because raw path doesn't start with `/etc`
- **Fix**: `os.path.normpath(os.path.join(_NOTIONAL_ROOT, raw_path))` resolves relative paths to absolute before prefix check; sibling false-positive (`/etcmalicious`) prevented by requiring `prefix + "/"` suffix
- **Regression test**: `test_path_traversal_to_etc_caught`, `test_sibling_path_not_falsely_blocked`

**safety-reviewer verdict after fixes**: No BLOCKER/HIGH/MEDIUM remaining.

### Codex Review
No BLOCKER. "No state mutation in the route... no regression or blocking issue introduced."

---

## Immutable Invariants (enforced in service + verified by tests)

| Invariant | Value | Test category |
|-----------|-------|---------------|
| `actual_publish_performed` | always `False` | G: Invariants |
| `learner_catalog_changed` | always `False` | G: Invariants |
| `dry_run` | always `True` | G: Invariants |
| `draft.publish_status` not mutated | confirmed | G: Invariants |
| Linux learner catalog entries | 0 (unchanged) | I: Catalog isolation |

---

## Test Coverage

| Category | Count | Notes |
|----------|-------|-------|
| A: Admin gate | 4 | K8s draft, already published, rehearsal not completed |
| B: Validation gate | 4 | boundary recognised, extra blocking failure, K8s isolation |
| C: Internal rehearsal gate | 7 | no session, wrong type, cleanup_verified=False, unrelated lab |
| D: Runtime/verifier/cleanup gate | 5 | missing policy, missing cleanup, no verifiers, K8s verifiers injected |
| E: Content quality gate | 8 | empty title/desc, placeholders, missing ai_tutor_context, explain.concept placeholder |
| F: Safety gate | 11 | allow_root/network, sudo/curl/wget/systemctl, env sudo wrapper, bash -c, path traversal, sibling false-positive, forbidden path |
| G: Invariants | 7 | all 3 immutables, publish_status unchanged, recommended_next_step, 6 gates present |
| H: HTTP endpoint | 4 | 200 happy path, 403 non-admin, 404 missing draft, K8s draft returns 200 not-ready |
| I: Catalog isolation | 3 | no Linux in catalog after dry run, failed dry run, publish_status unchanged |
| J: K8s regression | 3 | static validator unaffected, no cross-domain interference, boundary not recognized for K8s |
| **Total** | **58** | |

**Full suite**: 4198 passed, 92.64% coverage (≥90% gate ✅)

---

## Constraint Compliance

| Constraint | Status |
|-----------|--------|
| NOT publishing Linux lab | ✅ actual_publish_performed=False (hardcoded) |
| NOT creating Linux learner catalog entry | ✅ learner_catalog_changed=False (hardcoded) |
| NOT starting Linux trusted reader pilot | ✅ N/A — dry run only |
| NOT enabling LLM | ✅ 0 LLM calls |
| NOT touching production VMID 500-599 | ✅ No VM operations |
| NOT modifying K8s runtime/verifier behavior | ✅ Confirmed by J-category tests |
| NOT breaking Lab 5 K8s article-linked path | ✅ K8s regression suite all pass |
| NOT declaring Linux support launched | ✅ Decision is DRY_RUN_READY, not PUBLISHED |
| NOT allowing non-admin to run dry run | ✅ require_admin_user dependency enforced, 403 test confirms |

---

## Linux Domain Proof — Status After G-43

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
| **G-43** | **Linux Publish Candidate Dry Run** | **LINUX_PUBLISH_CANDIDATE_DRY_RUN_READY** |

---

## Recommended Next Step

**Linux Article-linked Lab Publish Gate** — the actual publish flow for a Linux lab, gated by all 6 dry-run checks passing in a live service call. Requires:
- Trusted reader pilot approval
- Runtime adapter `enabled=True` (currently `enabled=False` by design)
- Production VMID/network policy review
