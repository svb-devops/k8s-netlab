# LabGen MVP — Production Readiness Release Candidate Gate v0.1

> **Gate date**: 2026-06-11  
> **Auditor**: Claude Sonnet 4.6 (claude-sonnet-4-6)  
> **Contract version**: MVP Engineering Contract v0.1 (docs/labgen/MVP_ENGINEERING_CONTRACT_v0.1.md)  
> **Basis**: Full audit against Contract v0.1, production blocker closure evidence, RC smoke test results.

---

## A. Current Baseline

| Item | Value |
|------|-------|
| Current commit | `d90fb95` — feat(labgen): LAB_TIMEOUT VM Tracker Expiry Integration v0.1 |
| Remote sync status | **In sync** — `origin/main` at `d90fb95` |
| Backend tests passed | **2317 passed, 0 failed** |
| Backend coverage | **94.00%** (threshold: 90%) |
| Frontend tests | 118/118 passed (as of audit baseline) |
| safety-reviewer | PASS (all A/B-class changes reviewed) |
| Codex review | PASS — "I did not find any discrete, actionable defects" (Gap 4) |
| pre-commit hook | Configured and operational (sensitive info scan) |
| pre-push hook | Configured and operational (8-item scan + pytest gate) |
| Contract version | MVP Engineering Contract v0.1 (18 sections, not modified) |
| RC smoke test | **46 tests passing** (`tests/test_labgen_production_readiness_rc.py`) |

---

## B. Production Blocker Closure Matrix

All four production-blocking gaps identified in the MVP Engineering Contract Audit are now closed.

| Gap ID | Original Risk | Closure Commit | Closure Status | Evidence | Tests | Remaining Risk |
|--------|--------------|----------------|----------------|----------|-------|----------------|
| **Gap 1** — StubNamespaceLifecycleAdapter wired as default in production | Production sessions create fake namespaces; no real K8s namespace created | `a5b87a9` | **CLOSED** | `RuntimeAdapterSelectionService` guards `create_session()`; production+stub → `LAB_START_FAILED`; `GET /api/labgen/runtime/adapter-status` for ops visibility | `tests/test_labgen_runtime_adapter_selection.py`, `tests/test_labgen_runtime_adapter_routes.py` (~62 tests) | Low: K3sNamespaceLifecycleAdapter still NotImplementedError — must implement before live student use |
| **Gap 2** — Verifier credential file not deleted on VM reclaim | Stale `creds/vm_creds/{vm_id}_verifier.yaml` persists after VM reassignment; credential leak risk | `139e767` | **CLOSED** | `VerifierCredentialReclaimer` in `_do_cleanup()` Phase 2; credential deletion failure → `LAB_CLEANUP_FAILED` + `mark_vm_tainted` | `tests/test_labgen_verifier_credential_reclaim.py` (35 tests) | None for demo; low for production (real kubectl delete calls require K3s) |
| **Gap 3** — VM_PRECHECK_RUNNING conditions 4+6 not checked | Student could start lab on VM with stuck Terminating namespace or uncleaned cluster-scoped resources | `252a618` | **CLOSED** | `RuntimePrecheckService` in `create_session()`; Condition 4 (namespace stuck >5min); Condition 6 (cluster-scoped cleanup_verified=False); fail-closed; audit metadata safe | `tests/test_labgen_runtime_precheck.py`, `tests/test_labgen_runtime_start_precheck.py` (~67 tests) | Low: K3sNamespaceLifecycleAdapter.is_namespace_stuck_terminating() is NotImplementedError — conditions 4 only fires with stub config |
| **Gap 4** — LAB_TIMEOUT not wired to vm_tracker expiry | Session TTL never enforced; timed-out labs stay LAB_ACTIVE indefinitely; no cleanup triggered | `d90fb95` | **CLOSED** | `VMExpiryService` + `LabSessionService.timeout_session()`; `POST /api/labgen/runtime/expire-sessions` (admin-only, dry_run support); failure_reason=lab_timeout preserved through cleanup; VM tainted on cleanup failure | `tests/test_labgen_vm_expiry.py` (30 tests), `tests/test_labgen_lab_timeout_integration.py` (44 tests) | None for production use; admin-triggered expiry (cron or on-demand call to `/runtime/expire-sessions`) |

---

## C. Remaining Non-Blocking Gaps

### Gap 5 — Cleanup state sequence skips CLEANUP_VERIFICATION_RUNNING

**Description**: Contract §11 specifies the full state sequence: `CLEANUP_REQUESTED → NAMESPACE_TERMINATING_WAIT → CLEANUP_VERIFICATION_RUNNING → CLEANUP_VERIFIED → LAB_CLOSED`. The actual `_do_cleanup()` transitions directly to `LAB_CLOSED` (or `LAB_CLEANUP_FAILED`) without entering `CLEANUP_VERIFICATION_RUNNING`. The `cleanup_verified` field is set correctly; only the intermediate state is skipped.

| Question | Answer |
|----------|--------|
| Why not blocking RC | The observable outcome is correct (`cleanup_verified=True`/`False`, final state `LAB_CLOSED`/`LAB_CLEANUP_FAILED`). The missing intermediate state is a sequence-fidelity issue, not a safety or data-loss issue. |
| Risk level | Low — functional correctness not affected; frontend polling would see `LAB_CLOSED` transition without passing through `CLEANUP_VERIFICATION_RUNNING`. |
| Recommended later task | Implement the full state sequence in `_do_cleanup()` when a frontend session status progress bar is built. |
| Blocks demo | No — demo sessions show correct end states. |
| Blocks production-prep | No — cleanup outcome is correct. |
| Blocks actual production deployment | No — students see correct final state. |

---

### Gap 7 — verifier_credentials.py real K8s paths at 63% coverage

**Description**: Lines 309–414 of `verifier_credentials.py` implement `VerifierIdentityManager.ensure()` and `export()` which make real subprocess calls (`kubectl apply`, `kubectl create token`). These require a live K8s cluster and are correctly excluded from the static test suite.

| Question | Answer |
|----------|--------|
| Why not blocking RC | The covered paths (credential store read/write, smoke validation, path-traversal guards, reclaim) are at 98%+. The uncovered lines are clearly marked as requiring live K8s — a test infrastructure gap, not a safety gap. |
| Risk level | Medium for production verifier use — live credential initialization paths are untested against a real cluster. |
| Recommended later task | Write integration tests against a real K3s cluster (separate test suite, `pytest.mark.vm` marker). |
| Blocks demo | No — demo sessions use `FakeK8sVerifierClient`. |
| Blocks production-prep | No — credential store paths are covered; live issuance paths need real-K3s integration tests. |
| Blocks actual production deployment | Partial — verifier-dependent step checking requires live K3s; currently blocked by K3sNamespaceLifecycleAdapter being NotImplementedError anyway. |

---

## D. RC Decision

### Verdict: **RC_READY_WITH_NOTES**

**Basis for RC_READY**:

1. All four production-blocking gaps are closed with tests and safety reviews.
2. The full generation-to-publish pipeline is end-to-end connected: draft creation → LLM generation → repair loop → static validation → image readiness gate → publish decision → publish.
3. All publish-blocking checks (§10, 14 checks) enforced at both decision layer and service layer.
4. Learner-facing APIs never expose draft existence for unpublished labs, never return credential material, kubeconfig, raw provider output, or stack traces.
5. LLM provider: `live_enabled=False` hardcoded; no path to activate live mode without code change.
6. Admin-only endpoints correctly protected (`require_admin_user` / `require_internal_token`).
7. 2317 backend tests at 94% coverage; 118 frontend tests passing; RC smoke test (46 tests) passing.
8. safety-reviewer PASS and Codex PASS on all A/B-class changes.

**Notes (do not block RC)**:

- K3sNamespaceLifecycleAdapter is NotImplementedError — required before live student sessions. The production safety guard (Gap 1) correctly blocks session creation in production mode until this is implemented.
- No real K3s E2E tests — expected for MVP RC; K3s integration test suite is a separate milestone.
- `live_enabled` for LLM provider cannot be set to True via configuration alone — code change required. This is intentional for MVP.
- Expiry service is admin-triggered only — a cron-based automatic trigger is a post-RC enhancement.

**What RC_READY_WITH_NOTES means**: The system is ready for demo use, admin review, and integration testing. It is NOT ready for live student production sessions until K3sNamespaceLifecycleAdapter is implemented (wires real K3s namespace lifecycle) and verified with real K3s E2E tests.

---

## E. RC Smoke Test Coverage

File: `tests/test_labgen_production_readiness_rc.py` (46 tests)

| Group | Coverage | Tests |
|-------|----------|-------|
| A — Admin read endpoints | Contract pack (19 endpoints), LLM provider status (`live_enabled=False`, no API key), runtime adapter status | 10 |
| B — Publish pipeline | Demo seed, image-blocked draft cannot publish, 409 response no sensitive data | 5 |
| C — Learner catalog | Published labs visible, blocked/unresolved invisible, 404 for unpublished detail, start eligibility | 5 |
| D — Full session lifecycle | Start, step check, complete, snapshot (no vm_id/namespace), audit events — all no sensitive data | 9 |
| E — Expiry dry-run | Zero sessions in empty repo, finds expired session, does NOT clean (dry_run=True), live run cleans | 5 |
| F — Admin-only enforcement | 403 for non-admin on contract-pack, llm-provider/status, adapter-status, expire-sessions, demo/seed, draft create | 6 |
| G — LLM output safety | dry-run no raw_model_output/hidden_prompt, generation endpoint no raw output | 3 |

**All 46 tests pass. No real K3s, no real LLM, no external network.**

---

## F. Safety Summary

| Safety Property | Status | Evidence |
|----------------|--------|----------|
| Raw LLM output in API response | SAFE | `LabDraftGenerationResult.raw_model_output` absent from all response models |
| API key / Bearer token in response | SAFE | `LLMProviderConfig` has no API key field; `_REDACT_PATTERNS` covers `sk-`, Bearer, JWT |
| Kubeconfig in response | SAFE | `VerifierCredentialStore.export_verifier_kubeconfig()` returns `{"status":"ok"}` only |
| Verifier credential in response | SAFE | No credential content in any HTTP response path |
| Stack trace / raw exception | SAFE | `_sanitize_message()` strips Traceback patterns; `_extract_pydantic_errors` returns only loc/msg/type |
| Unpublished draft leaked to learner | SAFE | `LearnerCatalogService.get_published_lab_detail()` → `None → 404` for unpublished |
| Demo seed bypassing publish gate | SAFE | `DemoSeedService._seed_published_draft()` calls `PublishService.publish()` |
| Admin-only endpoints | SAFE | `require_admin_user` on all draft/labgen/image/runtime endpoints |
| LLM live mode | SAFE | `live_enabled=False` hardcoded; `LIVE_DISABLED` response always returned for live provider names |
| Production stub adapter | SAFE | Gap 1 guard: production+stub → `LAB_START_FAILED` before any resource creation |

---

---

## G. Production Deployment Preparation Status (2026-06-11)

> **Updated at commit `2c02478` → latest commit (Production Deployment Prep v0.1)**

| Item | Status |
|------|--------|
| Production Deployment Prep doc | `docs/labgen/PRODUCTION_DEPLOYMENT_PREP_v0.1.md` |
| Env template | `deploy/labgen/.env.production.example` |
| Preflight script | `scripts/labgen_production_preflight.py` |
| Preflight tests | `tests/test_labgen_production_preflight.py` (48 tests) |
| Admin diagnostics consistency tests | Added 19 tests to `tests/test_labgen_production_readiness_rc.py` |
| Config safety bug fixes | `LABGEN_VERIFIER_CREDENTIAL_ROOT` and `LABGEN_LAB_SESSION_TTL_MINUTES` now configurable via env |

### Config safety fixes

Two hardcoded values were identified and fixed during deployment prep:

- **`LABGEN_VERIFIER_CREDENTIAL_ROOT`** (new env var): Default is `creds/vm_creds` (relative path, safe for dev). Production must set an absolute path (e.g. `/var/lib/labgen/verifier-credentials`). Wired into `VerifierCredentialStore` in `routes.py` and `vm_manager.py`.
- **`LABGEN_LAB_SESSION_TTL_MINUTES`** (new env var): Default `30` minutes. Must be ≥ 1; `config.py` raises `RuntimeError` on startup if < 1. Wired into `VMExpiryService` in `routes.py`.

### Updated RC smoke test count

**67 tests passing** (was 48 at `2c02478`, +19 admin diagnostics consistency tests in Section H).

---

*This document records the RC gate decision at commit `d90fb95` and the Production Deployment Preparation milestone at commit (latest). It does not represent completed live production deployment or real K3s E2E integration.*
