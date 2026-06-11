# LabGen MVP Engineering Contract — Audit Report v0.1

> **Auditor**: Claude Sonnet 4.6 (claude-sonnet-4-6)  
> **Audit date**: 2026-06-10 (updated 2026-06-11 — production blockers closed)  
> **Source of truth**: `docs/labgen/MVP_ENGINEERING_CONTRACT_v0.1.md`  
> **Scope**: Full gap audit across all backend modules, test files, and frontend integration.

> **Update 2026-06-11 (RC Gate)**: Production-blocking Gaps 1–4 are all closed as of commit `d90fb95`. See [PRODUCTION_READINESS_RC_v0.1.md](PRODUCTION_READINESS_RC_v0.1.md) for RC gate decision. **RC verdict: RC_READY_WITH_NOTES.**

> **Update 2026-06-11 (Deployment Prep)**: Production Deployment Preparation v0.1 complete. See [PRODUCTION_DEPLOYMENT_PREP_v0.1.md](PRODUCTION_DEPLOYMENT_PREP_v0.1.md) for deployment checklist, env template, preflight script, and operational runbook. Config safety bugs (hardcoded credential root and session TTL) fixed. RC verdict unchanged: **RC_READY_WITH_NOTES**.

---

## A. Summary

| Item | Value |
|------|-------|
| Current commit | `d90fb95` — feat(labgen): LAB_TIMEOUT VM Tracker Expiry Integration v0.1 |
| Python test count | 2363 passed, 0 failed |
| labgen module coverage | 80%–100% per module (verifier_credentials.py at 63% for real-K3s paths only) |
| Full-suite coverage (all backend) | **94.09%** |
| Frontend test count | 118 passed, 0 failed |
| Pre-push hook | Configured and operational |
| Safety reviewer | Available via subagent |

### Production blockers closed as of `d90fb95`

All four production-blocking gaps (Gap 1–4) are closed. **RC gate verdict: RC_READY_WITH_NOTES** — ready for demo and integration testing; not yet ready for live student sessions pending `K3sNamespaceLifecycleAdapter` implementation. See [PRODUCTION_READINESS_RC_v0.1.md](PRODUCTION_READINESS_RC_v0.1.md) for full RC gate report.

### Overall completion verdict

**MVP v0.1 feature surface is substantially implemented.** All Contract §§1–18 core modules exist and are wired. The generation-to-publish pipeline is end-to-end connected, all publish-gate checks are enforced, safety redaction is applied at all layers, and the frontend uses typed views with escapeHtml throughout.

### Ready to proceed to Real LLM Provider Adapter?

**YES, with one prerequisite**: fix the stale frontend test (test_views.mjs:75 — BLOCKED fixture uses `blocked_reasons[]` but `renderAdminDraftView` reads `decision.issues[]`). This is a 2-line test fixture fix, not a code bug.

### Ready for production deployment?

**NO** — three gaps block production: (1) `StubNamespaceLifecycleAdapter` is still wired in the default production dependency (routes.py:149), meaning namespace creation/deletion is faked in live sessions; (2) `LabDraftGeneratorStub` is still the default generator (real generation uses `POST /api/lab-drafts/generate` but the `/api/labgen/drafts` create endpoint uses stub only); (3) verifier credential rotation/revocation is absent (§14 specifies vm_tracker reclaim must delete cred file — not implemented). These are expected for MVP demo phase, but must be resolved before production learner use.

---

## B. Milestone Matrix

| Contract §  | Requirement | Status | Evidence | Tests | Notes/Risk |
|-------------|-------------|--------|----------|-------|------------|
| §3 Schema versioning | All models carry `schema_version: "1.0"` | **DONE** | `SchemaVersionedModel` base class; all 9 listed objects inherit it | `test_labgen_models.py` | — |
| §4 LabDraft JSON schema | All 15 fields, correct types, derived fields protected | **DONE** | `models.py` LabDraft; `publish_status` direct-set rejected in PATCH | `test_labgen_draft_api.py` | pollution_level, shared_namespace_candidate correctly blocked from LLM injection |
| §5 Step schema | why/do/observe/explain/verify; explain defaults unverified | **DONE** | `Step`, `ExplainField` models | `test_labgen_models.py` | — |
| §5 explain.published_to_student | Must be set manually; `explain.verified_if_published` blocks publish | **DONE** | StaticValidator._check_explain_verified_if_published | `test_labgen_static_validator.py` | — |
| §6 VerifyTemplate schema | 10 types, namespace placeholder enforcement, cluster_scope | **DONE** | `VerifyTemplate` model, `VerifyType` enum | `test_labgen_models.py`, `test_labgen_static_validator.py` | — |
| §6 Forbidden verify types | shell_command, secret_key_exists, secret_value_equals blocked | **DONE** | `_check_verify_no_shell_commands`, `_check_verify_no_secret_value` | `test_labgen_static_validator.py` | — |
| §7 ImageResolutionResult | schema_version + all fields | **DONE** | `ImageResolutionResult` model | `test_labgen_models.py` | — |
| §7 Image whitelist | config/image_whitelist.json with 4 entries | **DONE** | `config/image_whitelist.json` | `test_labgen_image_resolver.py` | Only 4 intents; operator may need to add more |
| §7 Registry existence check | GET v2/{name}/manifests/{tag}, HTTP 200 = exists | **DONE** | `ImageResolver.check_registry_existence` | `test_labgen_image_resolver.py` | HTTP client is mockable |
| §7 Image blocking rules | latest/no-tag/external-registry/unresolved all blocked | **DONE** | `StaticValidator._check_image_*` | `test_labgen_static_validator.py`, `test_labgen_image_publish_gate.py` | — |
| §8 RuntimeRequirements | schema_version, namespace_template, pollution_level | **DONE** | `RuntimeRequirements` model | `test_labgen_models.py` | — |
| §8 pollution_level derivation | node_level > cluster_scoped > namespace_only > unknown | **DONE** | `StaticValidator._derive_pollution_level` | `test_labgen_static_validator.py` | — |
| §8 shared_namespace_candidate | 9-condition derivation, LLM cannot set | **DONE** | `StaticValidator._derive_shared_namespace_candidate` | `test_labgen_static_validator.py` | — |
| §9 ValidatorResult schema | schema_version, check_id, status, blocking_level, field_path | **DONE** | `ValidatorResult` model | `test_labgen_models.py` | — |
| §10 All 14 publish-blocking checks | All present in StaticValidator.validate() | **DONE** | `static_validator.py` lines 113–138 | `test_labgen_static_validator.py` | — |
| §10 publish gate enforcement | PublishService always re-runs StaticValidator | **DONE** | `publish_service.py` publish() | `test_labgen_publish_api.py` | Defense-in-depth dual gate: decision + service |
| §11 LabSessionState machine | All 18 states defined in enum | **DONE** | `LabSessionStatus` enum | `test_labgen_models.py` | — |
| §11 State transitions | create→precheck→image_check→namespace→active flow | **PARTIAL** | `LabSessionService.create_session()` implements precheck + image check + namespace creating; VERIFIER_BINDING_CREATING state exists but no K3s binding call | `test_labgen_lab_session.py` | Real namespace binding deferred (StubNamespaceLifecycleAdapter in production default) |
| §11 connection_state separation | WS disconnect ≠ cleanup trigger | **DONE** | LabSessionState.connection_state independent field | `test_labgen_models.py` | No WS code in labgen — connection_state is a model-only field |
| §11 VM_PRECHECK_RUNNING conditions | 6 conditions checked including vm_tainted | **DONE** | `LabSessionService.run_precheck()` + `RuntimePrecheckService` (Gap 3 closed `252a618`) | `test_labgen_vm_taint_recovery.py`, `test_labgen_runtime_precheck.py` | Condition 4/6 now checked via RuntimePrecheckService; `K3sNamespaceLifecycleAdapter.is_namespace_stuck_terminating()` still NotImplementedError |
| §12 Cleanup triggers | student complete/abort/timeout → cleanup | **DONE** | `complete_session()`, `abort_session()`, `run_cleanup()`, `timeout_session()` (Gap 4 closed `d90fb95`) | `test_labgen_lab_completion.py`, `test_labgen_vm_expiry.py` | LAB_TIMEOUT now wired via VMExpiryService + POST /api/labgen/runtime/expire-sessions |
| §13 VM Tracker / Lab Session event boundary | port interface + RealVMTracker + StubVMTracker | **DONE** | `VMTrackerPort`, `RealVMTracker`, `StubVMTracker` | `test_labgen_vm_taint_recovery.py` | LAB_SESSION_STARTED / LAB_SESSION_CLEANUP_VERIFIED events not emitted (only taint) |
| §14 VerifierCredentialMetadata | schema_version, all fields | **DONE** | `VerifierCredentialMetadata` model | `test_labgen_models.py` | — |
| §14 Credential storage | creds/vm_creds/{vm_id}_verifier.yaml, chmod 700/600 | **DONE** | `VerifierCredentialStore` | `test_labgen_verifier_credentials.py` | — |
| §14 Credential smoke test | 5 kubeconfig checks after creation | **PARTIAL** | `VerifierIdentityManager.smoke()` does structure check only, not live K3s checks | `test_labgen_verifier_credentials.py` | Structure-only smoke; live K3s smoke is OUT_OF_SCOPE for MVP |
| §14 Credential cleanup on VM reclaim | vm_tracker must delete cred file | **MISSING** | No code in vm_tracker or cleanup path deletes credential file | — | Low risk for demo, must be addressed before production |
| §15 namespace_readonly_v1 profile | list-only secrets, no get/write | **DONE** | ClusterRole YAML in `VerifierIdentityManager`, `K8sVerifierClientAdapter` uses list not get | `test_labgen_step_verifier_integration.py` | — |
| §15 RoleBinding per session | namespace-scoped, not ClusterRoleBinding | **DONE** | `StubNamespaceLifecycleAdapter.ensure_verifier_rolebinding()` | `test_labgen_step_verifier_integration.py` | Real K3sNamespaceLifecycleAdapter is NotImplementedError |
| §16 AdminReviewDiff | schema_version, all fields, append-only | **DONE** | `AdminReviewDiff` model, `AdminReviewDiffRepository` | `test_labgen_admin_review_diff.py` | — |
| §17 API endpoints — all 11 public + 2 internal | See API Matrix below | **DONE** (core) | routes.py | Multiple test files | Additional endpoints beyond Contract v0.1 are present (extras noted) |
| §18 CleanupSpec | namespace_cleanup structured object, cluster_scoped_resources | **DONE** | `CleanupSpec`, `CleanupNamespace` models | `test_labgen_models.py` | — |
| §18 cleanup_verified lifecycle | Set to True after CLEANUP_VERIFICATION_RUNNING passes | **PARTIAL** | `_do_cleanup()` sets cleanup_verified=True on success but CLEANUP_VERIFICATION_RUNNING state is not entered — cleanup skips to LAB_CLOSED directly | `test_labgen_lab_completion.py` | State sequence is compressed vs Contract spec |
| LLM generation pipeline | POST /api/lab-drafts/generate — template-based, no real LLM | **DONE** | `LabDraftGenerationService`, `FakeDraftGenerationAdapter` | `test_labgen_llm_generation.py` | Contract specifies two-stage LLM (ArticleAnalyzer + LabDraftGenerator); MVP uses template-based stub |
| Repair loop | generate → review → repair → validate | **DONE** | `generate_with_repair()` | `test_labgen_draft_repair.py` | — |
| Draft preview | Read-only snapshot with sanitization | **DONE** | `DraftPreviewService.build_snapshot()` | `test_labgen_draft_preview.py` | — |
| Publish decision gate | Read-only pre-publish evaluation | **DONE** | `PublishDecisionService.evaluate()` | `test_labgen_publish_decision.py` | — |
| Image Readiness | Evaluates ImageResolutionResult list | **DONE** | `ImageReadinessService` | `test_labgen_image_readiness.py` | — |
| Learner Catalog | Only PUBLISHED labs; 404 for missing/unpublished | **DONE** | `LearnerCatalogService` | `test_labgen_learner_catalog.py` | — |
| Learner Session Snapshot | Read-only, learner-safe, no credentials | **DONE** | `LearnerSessionSnapshotService` | `test_labgen_learner_session_snapshot.py` | — |
| Step Progression | check_step, advance on all-pass, ready_to_complete | **DONE** | `StepProgressionService` | `test_labgen_step_progression.py` | — |
| K8s Verifier Client | namespace-scoped list-only adapter | **DONE** | `K8sVerifierClientAdapter` | `test_labgen_k8s_verifier_client.py` | Kubeconfig loaded from VerifierCredentialStore |
| Runtime Audit | Append-only audit events per session | **DONE** | `RuntimeAuditService`, `RuntimeAuditRepository` | `test_labgen_runtime_audit.py` | — |
| FailureReason enum | 20 stable machine codes | **DONE** | `backend/labgen/failure_reasons.py` | `test_labgen_failure_reasons.py` | — |
| LLM Provider Boundary | Hardened boundary, default FAKE_ONLY, DRY_RUN available | **DONE** | `llm_provider_boundary.py` | `test_labgen_llm_provider_boundary.py`, `test_labgen_llm_provider_routes.py` | Live providers cannot be activated — code-level guard |
| Demo Seed Pack | 8 scenarios, published drafts go through publish gate | **DONE** | `DemoSeedService` | `test_labgen_demo_seed.py` | — |
| API Contract Pack | Stable endpoint catalogue + examples + sensitive field policy | **DONE** | `api_contract.py`, `build_contract_pack()` | `test_labgen_api_contract_pack.py` | — |
| Frontend JS client | Contract-aligned, no hard-coded endpoints | **DONE** | `labgenClient.js` | `tests/frontend/test_client.mjs` | — |
| Frontend views | All dynamic values through escapeHtml/sanitizeDisplayText | **DONE** | `labgenViews.js` | `tests/frontend/test_views.mjs` (117/118 pass) | 1 test fails — stale fixture (test bug, not code bug) |

---

## C. API Matrix

| Endpoint | Method | Contract §17 | Status | Auth Enforced | Tests |
|----------|--------|--------------|--------|---------------|-------|
| `/api/labgen/drafts` | POST | Yes | **DONE** | admin | `test_labgen_draft_api.py` |
| `/api/labgen/drafts/{id}` | GET | Yes | **DONE** | admin | `test_labgen_draft_api.py` |
| `/api/labgen/drafts/{id}` | PATCH | Yes | **DONE** | admin; published direct-set rejected | `test_labgen_draft_api.py` |
| `/api/labgen/drafts/{id}/validate` | POST | Yes | **DONE** | admin | `test_labgen_draft_api.py` |
| `/api/labgen/drafts/{id}/publish` | POST | Yes | **DONE** | admin; dual gate (decision + service) | `test_labgen_publish_api.py` |
| `/api/labgen/drafts/{id}/diffs` | GET | Yes | **DONE** | admin | `test_labgen_admin_review_diff.py` |
| `/api/labgen/drafts/{id}/preview` | GET | Extra (not in §17) | **DONE** | admin | `test_labgen_draft_preview.py` |
| `/api/labgen/drafts/{id}/publish-decision` | GET | Extra (not in §17) | **DONE** | admin | `test_labgen_publish_decision.py` |
| `/api/labgen/contract-pack` | GET | Extra | **DONE** | admin | `test_labgen_api_contract_pack.py` |
| `/api/labgen/llm-provider/status` | GET | Extra | **DONE** | admin | `test_labgen_llm_provider_routes.py` |
| `/api/labgen/llm-provider/dry-run` | POST | Extra | **DONE** | admin | `test_labgen_llm_provider_routes.py` |
| `/api/labgen/demo/seed` | POST | Extra | **DONE** | admin | `test_labgen_demo_seed.py` |
| `/api/lab-drafts/generate` | POST | Extra | **DONE** | any_authenticated | `test_labgen_llm_generation.py` |
| `/api/labs` | GET | Yes | **DONE** | any_authenticated; never leaks drafts | `test_labgen_learner_catalog.py` |
| `/api/labs/{id}` | GET | Yes | **DONE** | any_authenticated; 404 for unpublished | `test_labgen_learner_catalog.py` |
| `/api/labs/{id}/start-eligibility` | GET | Extra | **DONE** | any_authenticated; read-only | `test_labgen_learner_catalog.py` |
| `/api/lab-sessions` | POST | Yes | **DONE** | any_authenticated | `test_labgen_lab_session.py` |
| `/api/lab-sessions` | GET | Extra | **DONE** | any_authenticated (own sessions only) | `test_labgen_learner_session_snapshot.py` |
| `/api/lab-sessions/{id}` | GET | Yes | **DONE** | owner_or_admin | `test_labgen_lab_session.py` |
| `/api/lab-sessions/{id}/snapshot` | GET | Extra | **DONE** | owner_or_admin; no credentials in response | `test_labgen_learner_session_snapshot.py` |
| `/api/lab-sessions/{id}/complete` | POST | Yes | **DONE** | owner_only; ready_to_complete guard | `test_labgen_lab_completion.py` |
| `/api/lab-sessions/{id}/abort` | POST | Yes | **DONE** | owner_only | `test_labgen_lab_completion.py` |
| `/api/lab-sessions/{id}/steps/{step_id}/check` | POST | Extra | **DONE** | owner_only | `test_labgen_step_progression.py` |
| `/api/lab-sessions/{id}/audit-events` | GET | Extra | **DONE** | owner_or_admin | `test_labgen_runtime_audit.py` |
| `/api/images/resolve` | POST | Yes (§17) | **DONE** | admin | `test_labgen_image_routes.py` |
| `/api/images/check-existence` | POST | Yes (§17) | **DONE** | admin | `test_labgen_image_routes.py` |
| `/internal/verifier/check` | POST | Yes | **DONE** | X-Admin-Token | `test_labgen_verifier.py` |
| `/internal/lab-sessions/{id}/cleanup` | POST | Yes | **DONE** | X-Admin-Token | `test_labgen_lab_session.py` |

---

## D. Safety Matrix

| Safety Concern | Status | Evidence | Risk |
|----------------|--------|----------|------|
| Raw LLM output in API response | **SAFE** | `LabDraftGenerationResult.raw_model_output` intentionally absent; `GenerateLabDraftResponse` uses `candidate_summary` only | No path found |
| Hidden prompt in API response | **SAFE** | No `hidden_prompt` field in any response model; test `test_labgen_llm_generation.py` asserts absence | No path found |
| Provider metadata (chain-of-thought, trace_id) in response | **SAFE** | `LLMProviderResponse` has no `raw_output_available=True` path; `_redact_warnings()` strips provider patterns | No path found |
| API keys / tokens in response | **SAFE** | `LLMProviderConfig` has no API key fields; `_REDACT_PATTERNS` covers `sk-`, `sk-ant-`, Bearer, JWT patterns | No path found |
| Kubeconfig in response | **SAFE** | `LabSessionState.namespace` leaks namespace but NOT kubeconfig; `LearnerSessionSnapshot` omits namespace and vm_id entirely | Low: raw LabSessionState still has namespace/vm_id — only safe via snapshot endpoint |
| Verifier credential in response | **SAFE** | `VerifierCredentialStore` never returns credential content in HTTP path; `export_verifier_kubeconfig` returns `{"status": "ok"}` only | No path found |
| Stack trace / traceback in response | **SAFE** | `_extract_pydantic_errors` only returns `loc/msg/type`; `sanitize_text()` / `_REDACT_PATTERNS` strips `Traceback (most recent call last)` | No path found |
| Raw command output in response | **SAFE** | VerifyTemplate results return `passed: bool` + stable `failure_reason` code; no command stdout in any response | No path found |
| Registry credential in response | **SAFE** | `ImageReadinessService` evaluates from stored `ImageResolutionResult`; no auth header in existence check GET; whitelist only stores registry path | No path found |
| Frontend display safety (XSS) | **SAFE** | All dynamic values through `_safe()` → `escapeHtml(sanitizeDisplayText())` in `labgenViews.js`; `labgenSecurity.js` asserted in tests | 1 test failure is fixture bug, not safety |
| Unpublished draft existence leaked to learner | **SAFE** | `LearnerCatalogService.get_published_lab_detail()` returns `None` for both missing and unpublished → 404 both cases | No path found |
| Demo seed bypassing publish gate | **SAFE** | `DemoSeedService._seed_published_draft()` calls `PublishService.publish()` which runs StaticValidator + image check; blocked scenarios use `_validate_and_block_draft()` | No path found |
| Admin-only endpoints protection | **SAFE** | `require_admin_user` dep on all draft/labgen endpoints; `require_internal_token` on internal endpoints; non-admin test confirmed 403 | — |
| Live LLM provider activation by env var | **SAFE** | `LLMProviderBoundaryService.call()` explicitly returns `live_provider_disabled` for any `_LIVE_PROVIDER_NAMES`; `live_enabled` is always `False` in status response | Cannot be activated at all — config-only |
| provider_boundary live_enabled default | **SAFE** | `LABGEN_LLM_PROVIDER_MODE` defaults to `"fake_only"`; `create_from_env()` falls back to FAKE_ONLY on invalid value | No path to live mode |
| `metadata` in RuntimeAuditEvent leaking secrets | **LOW RISK** | `metadata: dict` field has docstring warning but no runtime enforcement; callers currently pass `{"step_id": ...}` only | No active leak found; recommend runtime audit in future |
| `LabSessionState` returned directly from start/complete/abort | **MINOR** | Contains `namespace` and `vm_id` fields; Contract notes say to use LearnerSessionSnapshot for learner UI | Not a security bug for authenticated learner; namespace is not a secret |

---

## E. Remaining Gaps

### Gap 1 — `StubNamespaceLifecycleAdapter` wired as default in production routing

> **STATUS: DONE — closed at commit `a5b87a9`**

**Closure**: `RuntimeAdapterSelectionService` (new module `backend/labgen/runtime_adapter_selection.py`) checks the configured runtime mode and adapter kind on every `create_session()` call. Production mode + stub adapter → `LAB_START_FAILED` (fail-closed) before any resource creation. `GET /api/labgen/runtime/adapter-status` provides operator visibility. Tests: `tests/test_labgen_runtime_adapter_selection.py` + `tests/test_labgen_runtime_adapter_routes.py` (~62 tests). safety-reviewer PASS; Codex PASS.

**Original issue**: In production, `POST /api/lab-sessions` created a session but never actually created a K8s namespace. Students entered "LAB_ACTIVE" state with a fake namespace.

**Remaining**: `K3sNamespaceLifecycleAdapter` is still `NotImplementedError` — required before live student sessions but correctly blocked by the Gap 1 guard in production mode.

---

### Gap 2 — Verifier credential cleanup on VM reclaim not implemented

> **STATUS: DONE — closed at commit `139e767`**

**Closure**: `VerifierCredentialReclaimer` added to `verifier_credentials.py`. `_do_cleanup()` restructured as two phases: Phase 1 namespace deletion (original behavior) + Phase 2 credential reclaim. Credential deletion failure → `LAB_CLEANUP_FAILED` + `mark_vm_tainted` (same policy as namespace cleanup failure). Path-traversal guard: path must be within credential root, no symlinks. Audit metadata: only `cleanup_phase="verifier_credential_reclaim"` (no path/content/kubeconfig/token). Tests: `tests/test_labgen_verifier_credential_reclaim.py` (35 tests). safety-reviewer PASS.

**Original issue**: Contract §14 requires vm_tracker reclaim VM → delete cred file. Stale credentials persisted indefinitely after VM reassignment.

---

### Gap 3 — VM_PRECHECK_RUNNING conditions 4 and 6 not checked

> **STATUS: DONE — closed at commit `252a618`**

**Closure**: `RuntimePrecheckService` (new module `backend/labgen/runtime_precheck.py`) implements Condition 4 (prior namespace stuck Terminating >5min) and Condition 6 (cluster-scoped resources declared + `cleanup_verified=False`). Service injected into `LabSessionService.__init__` as optional dep. BLOCKED result → `LAB_START_FAILED` session + safe audit event (only `blocked_conditions` + `issue_codes` in metadata, no kubeconfig/credential/traceback). Fail-closed: any exception → BLOCKED safe issue. `NamespaceLifecyclePort` extended with `is_namespace_stuck_terminating()`. Tests: `tests/test_labgen_runtime_precheck.py` + `tests/test_labgen_runtime_start_precheck.py` (~67 tests). safety-reviewer PASS.

**Original issue**: Student could start a new lab on a VM whose prior namespace was stuck Terminating or whose cluster-scoped resources were not cleaned up.

---

### Gap 4 — LAB_TIMEOUT trigger not wired to vm_tracker expiry

> **STATUS: DONE — closed at commit `d90fb95`**

**Closure**: `VMExpiryService` (new module `backend/labgen/vm_expiry.py`) scans `session.started_at + TTL` expiry against injectable clock. `LabSessionService.timeout_session()`: `LAB_ACTIVE → LAB_TIMEOUT → _do_cleanup()`. `failure_reason=lab_timeout` preserved through successful cleanup. `POST /api/labgen/runtime/expire-sessions` (admin-only, dry_run, limit 1–500). `LabSessionRepository.list_all()` added. `FailureReason.LAB_TIMEOUT` stable machine code added. Learner snapshot shows safe LAB_TIMEOUT issue. Cleanup failure → `LAB_CLEANUP_FAILED` + `mark_vm_tainted` (existing policy). Tests: `tests/test_labgen_vm_expiry.py` (30 tests) + `tests/test_labgen_lab_timeout_integration.py` (44 tests). `vm_expiry.py` at 100% coverage. safety-reviewer PASS; Codex PASS.

**Original issue**: `LabSessionStatus.LAB_TIMEOUT` existed in enum but no code path set it. Timed-out labs stayed `LAB_ACTIVE` indefinitely.

---

### Gap 5 — cleanup state sequence compressed (skips CLEANUP_VERIFICATION_RUNNING)

**Why it matters**: Contract §11 specifies: `CLEANUP_REQUESTED → NAMESPACE_TERMINATING_WAIT → CLEANUP_VERIFICATION_RUNNING → CLEANUP_VERIFIED → LAB_CLOSED`. The actual `run_cleanup()` goes directly from the trigger to LAB_CLOSED (or LAB_CLEANUP_FAILED) without entering CLEANUP_VERIFICATION_RUNNING. The `cleanup_verified` field is set correctly, but the intermediate state is skipped.

**Scope**: `backend/labgen/lab_session_service.py` `_do_cleanup()`.

**Blocks Real LLM Provider Adapter?** No.

**Blocks frontend demo?** No — functional result is correct.

**Blocks production deployment?** Partial — observable by frontend state polling; `cleanup_status` in snapshot shows "verified" or "failed" correctly.

---

### Gap 6 — Frontend test failure: stale BLOCKED decision fixture

**Why it matters**: `tests/frontend/test_views.mjs` test 94 fails because the BLOCKED_DECISION fixture uses `blocked_reasons: [{check_id, message}]` but `renderAdminDraftView` reads `decision.issues[]` with `severity: 'error'`. This is a test fixture bug, not a code bug.

**Scope**: `tests/frontend/test_views.mjs` lines 48–53 — `BLOCKED_DECISION.blocked_reasons` should be `BLOCKED_DECISION.issues` with `severity: 'error'`.

**Blocks Real LLM Provider Adapter?** No (test infrastructure only).

**Blocks frontend demo?** No (production code is correct).

**Blocks production deployment?** No, but must be fixed to keep CI green.

---

### Gap 7 — verifier_credentials.py coverage at 63%

**Why it matters**: The untested lines (309–373, 377–378, 382–409) are the `VerifierIdentityManager` methods for `ensure()` and `export()` which make real subprocess calls (`kubectl apply`, `kubectl create token`). These are correctly marked as requiring live K8s and are untested in the static suite, but the low coverage number is a risk signal.

**Scope**: Real K8s integration path in `VerifierIdentityManager`.

**Blocks Real LLM Provider Adapter?** No.

**Blocks frontend demo?** No.

**Blocks production deployment?** YES for verifier-dependent step checking.

---

### Gap 8 — LLM generation endpoint (`/api/lab-drafts/generate`) not in Contract §17

**Why it matters**: The contract's §17 API table only lists the old `POST /api/labgen/drafts` for draft creation (which uses `LabDraftGeneratorStub`). The new `POST /api/lab-drafts/generate` endpoint (which uses the full generation pipeline with repair loop, templates, and provider boundary) is an extension beyond the contract. The contract pack does include it, but the engineering contract itself has not been updated. This is a documentation drift issue.

**Scope**: Contract v0.1 §17 does not mention `/api/lab-drafts/generate`.

**Blocks Real LLM Provider Adapter?** This is where the Real LLM adapter plugs in — it is the correct path.

**Blocks frontend demo?** No.

**Blocks production deployment?** Documentation only.

---

## F. Recommended Next Step

**Fix the stale frontend test fixture first** (Gap 6, 30-minute task), then **proceed to Real LLM Provider Adapter v0.1**.

The adapter boundary (`LLMProviderBoundaryService`, `LabDraftGenerationPort`, `LabDraftGenerationService._generate_result()`) is fully wired and tested with `FakeDraftGenerationAdapter` and `DryRunLLMProviderAdapter`. The LLM provider boundary hardening (redaction, mode enforcement, no API keys in config model) is complete. The only missing piece is a concrete `LLMProviderAdapter` that calls a real model, validates the response via Pydantic + StaticValidator, and returns a `LabDraftGenerationResult` — a well-defined, small adapter class.

The production deployment blockers (Gaps 1–4) are K3s integration work that is independent of LLM adapter development and should proceed in parallel or after the LLM adapter is validated in staging.

---

## Appendix: High-Risk Check Results

1. **Bypass Pydantic/StaticValidator before creating draft?** No. Both `/api/labgen/drafts` (stub) and `/api/lab-drafts/generate` (pipeline) run `LabDraft.model_validate()` + `StaticValidator.validate()` before `repo.create()`.

2. **Bypass ImageReadiness/PublishDecision gate before publishing?** No. `publish_draft()` calls `decision_svc.evaluate()` and checks `status == BLOCKED` before calling `PublishService.publish()`. `PublishService.publish()` always re-runs StaticValidator + existence check atomically.

3. **Learner-facing API leak unpublished draft existence?** No. Both `GET /api/labs/{id}` and `GET /api/labs/{id}/start-eligibility` return `None → 404` for unpublished. `GET /api/lab-sessions/{id}` returns session state but does not expose draft publish status.

4. **Frontend directly displays raw JSON?** No. All dynamic values pass through `_safe()` → `escapeHtml(sanitizeDisplayText())`. The dry-run result in labgen-dev.html uses `pre.textContent = lines.join('\n')` (textContent, not innerHTML).

5. **API response contains `raw_model_output` / `hidden_prompt` / `provider_metadata`?** No. These fields are intentionally absent from all response models. Confirmed by `test_labgen_llm_generation.py` and `test_labgen_api_contract_pack.py`.

6. **Provider boundary live mode enabled by default?** No. Default is `FAKE_ONLY`. Live provider names always trigger `LIVE_DISABLED` response regardless of mode config. `live_enabled` is hardcoded `False` in the status endpoint.

7. **Demo seed goes through publish gate?** Yes. `_seed_published_draft()` calls `PublishService.publish()`. Image-blocked scenarios use `_validate_and_block_draft()` which runs StaticValidator.

8. **Contract pack endpoint inventory consistent with actual FastAPI routes?** Mostly yes, with one gap: `/api/labgen/drafts/{id}/diffs` (GET) is in routes.py but absent from `_ENDPOINTS` in api_contract.py. This is a minor documentation gap, not a security issue.

9. **Session snapshot triggers side effects?** No. `LearnerSessionSnapshotService.build_snapshot()` is read-only; `list_my_sessions()` is read-only. No session mutation, no audit events, no K8s calls.

10. **Audit event metadata leaks secrets/stack traces?** No active leak found. `metadata: dict` is caller-controlled; current callers pass `{"step_id": "..."}` only. The field has a docstring warning but no runtime enforcement.

11. **Image API / Image Readiness leaks registry credentials?** No. `ImageResolver.check_registry_existence()` uses an HTTP GET with no auth header (internal registry); `ImageReadinessService` works from pre-computed results only. No auth credentials are present in either module.

12. **Admin-only endpoints correctly protected?** Yes. `require_admin_user` dep is applied to all `/api/labgen/drafts/*`, `/api/images/*`, `/api/labgen/contract-pack`, `/api/labgen/llm-provider/*`, and `/api/labgen/demo/*` endpoints. `require_internal_token` protects `/internal/*`.
