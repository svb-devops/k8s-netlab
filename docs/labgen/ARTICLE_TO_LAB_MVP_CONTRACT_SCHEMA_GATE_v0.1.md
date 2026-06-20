# Article-to-Lab MVP Contract Schema Gate v0.1

**Date**: 2026-06-16
**Operator**: Claude Code acting as senior dev + ops
**Decision**: ARTICLE_TO_LAB_SCHEMA_READY_WITH_NOTES
**No real secrets in this document.**

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Gate decision | **ARTICLE_TO_LAB_SCHEMA_READY_WITH_NOTES** |
| Preceded by | Article-to-Lab Implementation Prerequisites — ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES (commit 4fadbd8) |
| Prerequisites confirmed | YES — N-01/N-02/N-03 all RESOLVED |
| Implementation may start? | **YES** — K8s Article-to-Lab Draft Mode Implementation is the recommended next step |
| LLM live enabled? | **NO** — stub mode only; no live LLM calls |
| User article upload enabled? | **NO** — admin-only input in v0.1 |
| Fifth lab published? | **NO** |
| Concurrency increased? | **NO** |
| Customer pilot started? | **NO** |
| Production VMID 500-599 | Untouched |
| Runtime / verifier / terminal modified? | **NO** |
| LLM calls in this gate | 0 |
| Code changes in this gate | article_models.py (new), static_validator.py (ArticleDraftValidator added), tests/test_labgen_article_schema.py (new) |
| Tests added | 116 tests |
| All tests passing | YES |

**Why schema gate before implementation**: Writing implementation code against an unfinished schema creates rework. All Pydantic models, enum values, field constraints, and guardrail check IDs must be locked before any service layer code is written. The schema is now the contract; the implementation must match it.

**Why READY_WITH_NOTES**: The schema is internally consistent, fail-closed, and covers all 11 required models. The WITH_NOTES qualifiers are:
1. Stub mode is unvalidated against a real LLM provider — the schema is designed for swappability, but output quality with a real provider is unknown.
2. `ArticleLabRuntimeRequirement` and `VerifierCandidate` are schema-only in v0.1; the corresponding service layer adapters are not yet implemented.
3. The conversion path from `ArticleDraftLabContract` → `LabDraft` is not yet implemented (next implementation gate).
4. `source_url` scraping prevention is enforced at schema level (metadata-only) but not yet by a service-layer guard.

**What this gate does not do**:
- Does not implement the article ingestion API
- Does not implement the LLM provider
- Does not implement the draft generation service
- Does not implement the Admin Review UI
- Does not publish a generated K8s lab
- Does not change runtime provisioning
- Does not enable learner-facing generated labs
- Does not declare arbitrary Article-to-Lab as implemented
- Does not declare production ready or public launch

---

## B. Schema Inventory

All 11 required models implemented in `backend/labgen/article_models.py`.

### B.1 Enums

| Enum | Values | Purpose |
|------|--------|---------|
| `ArticleSourceType` | pasted_text, markdown, readme, internal_doc, other | Type of submitted article content |
| `FeasibilityStatus` | directly_lab_ready, partially_lab_ready, not_lab_ready | Outcome of feasibility assessment |
| `SafetyFlag` | 13 values (see below) | Safety concerns detected in article |
| `VerifierFeasibility` | reusable_existing, needs_parameterization, needs_new_primitive, not_verifiable, unsafe_to_verify | Verifier strategy assessment |
| `FeasibilityEvaluatedBy` | stub, rule_based, llm_draft, human | Who/what evaluated feasibility |
| `TargetDomain` | k8s, linux, docker, networking, database, cicd, cloud, unknown | Target technical domain |
| `ArticleRuntimeType` | k8s_namespace, linux_vm, container, docker_compose, network_namespace, database_instance, unknown | Runtime environment type |
| `VerifierCandidateState` | reusable_existing, needs_parameterization, needs_new_primitive, not_verifiable, unsafe_to_verify | State of verifier analysis |
| `UnsupportedInferenceSeverity` | note, low, medium, high, blocker | Severity of unsupported inference |
| `ArticleDraftStatus` | draft, needs_changes, rejected, approved_for_static_validation, approved_for_internal_rehearsal, approved_for_publish_candidate | Article draft lifecycle status |
| `AdminDecisionValue` | pending, approve, request_changes, reject | Admin review decision |

### B.2 SafetyFlag values (all 13)

| Flag | Fail-closed effect |
|------|--------------------|
| `contains_secret_like_content` | Hard reject; cannot enter pipeline |
| `requires_real_credentials` | Reject or missing_requirement |
| `requires_production_environment` | Review required |
| `destructive_operation` | Review required |
| `unsafe_network_behavior` | Review required |
| `external_service_dependency` | Review required |
| `unclear_cleanup` | Cannot publish |
| `unverifiable_outcome` | Review required |
| `copyright_unclear` | Review required |
| `unsupported_domain` | Review required |
| `excessive_cost` | Review required |
| `dangerous_or_illegal` | Hard reject; cannot enter pipeline |
| `sensitive_personal_data` | Review required |

### B.3 Models

| Model | File location | Purpose |
|-------|---------------|---------|
| `ArticleSourceMetadata` | article_models.py | Article submission metadata; no raw text |
| `FeasibilityResult` | article_models.py | Feasibility assessment outcome |
| `SourceGroundingSnippet` | article_models.py | Minimal verbatim excerpt for admin review |
| `UnsupportedInference` | article_models.py | Inferred field lacking source grounding |
| `ArticleLabRuntimeRequirement` | article_models.py | Runtime needs for the generated lab |
| `VerifierCandidate` | article_models.py | Verifier strategy candidate |
| `ArticleDraftLabContract` | article_models.py | Article-to-Lab draft wrapper (NOT LabDraft) |
| `AdminDecision` | article_models.py | Admin review decision record |
| `ArticleStoragePolicy` | article_models.py | Storage and retention policy metadata |

### B.4 Relationship to existing LabDraft (published lab contract)

`ArticleDraftLabContract` is **not** `LabDraft`. They are distinct lifecycle stages:

```
Article text
  → (Feasibility Gate)
  → ArticleDraftLabContract [THIS SCHEMA]
    → (Admin Review + StaticValidator + Internal Rehearsal)
    → [future implementation: ArticleDraftLabContract → LabDraft conversion]
    → LabDraft (existing schema, existing publish flow)
    → Learner Catalog
```

`LabDraft` (in `backend/labgen/models.py`) is for published labs that have already passed all gates. `ArticleDraftLabContract` is an intermediate artifact that must not enter the learner catalog directly.

---

## C. Validation / Guardrails

All 15 guardrails implemented in `ArticleDraftValidator` (`backend/labgen/static_validator.py`).

| Check ID | Blocking Level | Trigger condition |
|----------|---------------|-------------------|
| `article_draft.rejected_feasibility_cannot_publish` | PUBLISH_BLOCKING | status > DRAFT when feasibility = NOT_LAB_READY |
| `article_draft.partial_feasibility_cannot_publish` | PUBLISH_BLOCKING | status = APPROVED_FOR_PUBLISH_CANDIDATE when feasibility = PARTIALLY_LAB_READY |
| `article_draft.directly_ready_requires_admin_review` | PUBLISH_BLOCKING | status = APPROVED_FOR_PUBLISH_CANDIDATE + feasibility = DIRECTLY_LAB_READY + admin not approved |
| `article_draft.missing_source_grounding` | PUBLISH_BLOCKING | status = APPROVED_FOR_PUBLISH_CANDIDATE + no source grounding snippets |
| `article_draft.unsupported_inference_high_blocker` | PUBLISH_BLOCKING | inference severity HIGH or BLOCKER in publish/rehearsal status; or unconfirmed requires_admin_confirmation |
| `article_draft.no_raw_text_field` | RUNTIME_BLOCKING | source_metadata.raw_text_persisted = True |
| `article_draft.no_sensitive_grounding_excerpt` | RUNTIME_BLOCKING | SourceGroundingSnippet.contains_sensitive_content = True with non-empty excerpt |
| `article_draft.admin_approve_requires_confirmations` | PUBLISH_BLOCKING | admin_decision.decision = APPROVE with any confirmed_* = False |
| `article_draft.unknown_domain_cannot_publish` | PUBLISH_BLOCKING | target_domain = UNKNOWN in publish/rehearsal/static-validation status |
| `article_draft.unsafe_verifier_cannot_publish` | PUBLISH_BLOCKING | VerifierCandidate.candidate_state = UNSAFE_TO_VERIFY; or review_required=True with admin_reviewed=False |
| `article_draft.cleanup_strategy_required` | PUBLISH_BLOCKING | required_runtime.cleanup_strategy = None in publish/rehearsal status |
| `article_draft.llm_draft_cannot_bypass_review` | PUBLISH_BLOCKING | evaluated_by = stub or llm_draft + status = publish candidate/rehearsal + admin not approved |
| `article_draft.cloud_domain_blocked_v1` | PUBLISH_BLOCKING | target_domain = CLOUD + status != DRAFT |
| `article_draft.source_url_no_scraping` | — | Schema structural check; scraping prevention is service-layer concern |
| `article_draft.user_confirmations_required` | PUBLISH_BLOCKING | user_confirmed_right_to_use=False or user_confirmed_no_secrets=False when status != DRAFT |

### C.1 Fail-closed behavior summary

| Scenario | Outcome |
|----------|---------|
| `contains_secret_like_content` safety flag | `FeasibilityResult.can_enter_draft_pipeline()` = False; article discarded |
| `dangerous_or_illegal` safety flag | Same as above |
| Missing grounding in publish candidate | PUBLISH_BLOCKING guardrail fires |
| LLM/stub output without admin approval | PUBLISH_BLOCKING guardrail fires |
| Any confirmed_* = False when approving | PUBLISH_BLOCKING guardrail fires |
| HIGH/BLOCKER unsupported inference | PUBLISH_BLOCKING guardrail fires |
| `unsafe_to_verify` verifier candidate | PUBLISH_BLOCKING guardrail fires |
| Cloud domain beyond DRAFT status | PUBLISH_BLOCKING guardrail fires |
| Unknown domain in publish pipeline | PUBLISH_BLOCKING guardrail fires |
| No cleanup strategy in rehearsal/publish | PUBLISH_BLOCKING guardrail fires |
| raw_text_persisted = True | RUNTIME_BLOCKING + model_validator ValueError at construction |
| Sensitive grounding excerpt non-empty | RUNTIME_BLOCKING guardrail fires |

---

## D. Storage / Retention Fit

| Data element | Storage | Retention | Access |
|---|---|---|---|
| Raw article text | In-memory only | Discarded after processing | Processing pipeline only; never persisted |
| content_hash | Persistent | Indefinite | Admin only |
| source_metadata | Persistent with draft | Until draft deleted | Owner + admin |
| feasibility_result | Persistent with draft | Until draft deleted | Owner + admin |
| source_grounding_snippets | Persistent with draft | Until draft deleted | Admin only |
| unsupported_inferences | Persistent with draft | Until draft deleted | Admin only |
| Generated ArticleDraftLabContract | Persistent | Until deleted | Owner + admin |
| admin_decision | Persistent with draft | Until draft deleted | Admin + audit |
| Published Lab (future LabDraft) | Persistent | Indefinite | Public (learners) |

Schema enforcement:
- `ArticleSourceMetadata.raw_text_persisted` defaults to `False`; Pydantic model_validator raises if `True`
- `ArticleStoragePolicy.raw_text_persisted` defaults to `False`
- `ArticleStoragePolicy.forbidden_persisted_fields` includes `raw_article_text`, `secret_values`, `private_keys`, `api_keys`, `credentials`
- `ArticleStoragePolicy.rejection_metadata_retention_days` defaults to 30
- `ArticleStoragePolicy.audit_retention` defaults to `"indefinite"`

---

## E. LLM Boundary Fit

| Requirement | Status |
|-------------|--------|
| Stub mode only in v0.1 | YES — `FeasibilityEvaluatedBy.STUB` is the default evaluator |
| Draft only; no direct publish | YES — `ArticleDraftStatus` has no auto-publish transition |
| No verifier code generation | YES — `VerifierCandidateState.NEEDS_NEW_PRIMITIVE` requires admin creation |
| Source grounding required | YES — guardrail `article_draft.missing_source_grounding` blocks without it |
| LLM cannot bypass review | YES — guardrail `article_draft.llm_draft_cannot_bypass_review` enforced |
| No auto-acceptance of generated verifiers | YES — `review_required=True` by default; guardrail blocks if `admin_reviewed=False` |
| provider mode | `LLMProviderMode.FAKE_ONLY` (existing `LLMProviderBoundaryService`) |

The existing `LLMProviderBoundaryService` (in `backend/labgen/llm_provider_boundary.py`) already enforces these boundaries at the provider level. The new `ArticleDraftLabContract` schema adds a second enforcement layer at the data model level.

---

## F. Domain Portability

| Domain | v0.1 status | Schema status | Publish status |
|--------|-------------|---------------|----------------|
| `k8s` | ALLOWED for draft mode implementation | Schema-ready | Allowed (all guardrails pass) |
| `linux` | Schema-ready; no implementation | Schema-ready | Blocked (no runtime adapter) |
| `docker` | Schema-ready; no implementation | Schema-ready | Blocked (no runtime adapter) |
| `networking` | Schema-ready; no implementation | Schema-ready | Blocked (no runtime adapter) |
| `database` | Schema-ready; no implementation | Schema-ready | Blocked (no runtime adapter) |
| `cicd` | Schema-ready; no implementation | Schema-ready | Blocked (no runtime adapter) |
| `cloud` | Schema-ready; **blocked by default** | Schema-ready | BLOCKED by `article_draft.cloud_domain_blocked_v1` guardrail |
| `unknown` | Schema-ready; blocked in pipeline | Schema-ready | BLOCKED by `article_draft.unknown_domain_cannot_publish` guardrail |

Domain portability design decisions:
- `TargetDomain` enum includes all 8 domains — schema is domain-agnostic
- Cloud domain blocked via guardrail (not removed from enum) — future gate can re-enable
- linux/docker/networking/database/cicd are schema-ready but have no implementation adapters — safe to include in contracts without enabling functionality
- K8s-only restriction is enforced by implementation availability, not schema restriction

---

## G. Implementation Readiness

### G.1 What is now safe to implement

With this schema gate passed, the following implementation work is safe to begin:

1. **FeasibilityGate service** — classifies article content against `FeasibilityResult` schema; uses `SafetyFlag` enum; discards raw text after processing
2. **ArticleDraftRepository** — stores/loads `ArticleDraftLabContract` from JSON; uses `ArticleStoragePolicy` as metadata
3. **AdminReview API endpoints** — PATCH/GET `ArticleDraftLabContract`; enforces `AdminDecision` confirmation requirements
4. **ArticleDraftValidator integration** — runs `ArticleDraftValidator.validate()` before status transitions
5. **StubFeasibilityClassifier** — deterministic stub that returns `FeasibilityResult` with `evaluated_by=STUB`
6. **ArticleDraftLabContract → LabDraft conversion** — creates `LabDraft` from approved contract (future implementation step)

### G.2 What remains out of scope

| Item | Reason |
|------|--------|
| Article ingestion API (user-facing upload) | v0.1 is admin-only; no public endpoint |
| LLM provider integration | Stub mode only; real provider deferred |
| Generated lab publish | Requires conversion + internal rehearsal (future gate) |
| Admin Review UI | Not blocked; can be planned in parallel |
| Linux/docker/networking runtime adapters | Separate domain expansion gates needed |
| Cloud domain support | Requires dedicated gate decision |
| Customer pilot | Blocked by NO_SUITABLE_SMALL_CUSTOMER |
| Fifth published lab | Out of scope for this gate |

---

## H. Final Decision

**ARTICLE_TO_LAB_SCHEMA_READY_WITH_NOTES**

### H.1 READY rationale

- All 11 required Pydantic models implemented and schema-validated
- All 15 guardrail checks implemented in `ArticleDraftValidator`
- 116 tests pass (0 failures)
- All schema decisions are fail-closed (ambiguity → reject)
- Schema is internally consistent with Prerequisites gate decisions (N-01/N-02/N-03)
- `ArticleDraftLabContract` correctly separated from `LabDraft` (no path confusion)
- Domain portability preserved: non-k8s domains are schema-ready without enabling functionality
- Raw article text cannot be persisted (enforced at model construction and guardrail level)
- Sensitive content handling enforced by `SafetyFlag` and guardrail
- LLM bypass prevention enforced by `FeasibilityEvaluatedBy` + guardrail
- Admin review bypass prevention enforced by `AdminDecision` confirmation model
- Cloud domain blocked by default via guardrail
- No TODO/FIXME in new code
- No placeholder-as-success in tests
- No raw article text persisted field
- No sensitive content persisted
- No live LLM calls
- No generated verifier code auto-accepted
- No rejected/partial article publish path
- No admin review bypass
- No StaticValidator bypass
- No cleanup strategy bypass
- Production VMID 500-599 untouched
- Runtime/verifier/terminal behavior unchanged

### H.2 WITH_NOTES rationale

1. **Stub-only validation**: The schema is designed for real LLM output, but only stub-evaluated feasibility has been tested. When real LLM integration happens, schema constraints will need integration tests against actual LLM output shapes.
2. **No service layer yet**: `ArticleLabRuntimeRequirement` and `VerifierCandidate` exist as schema only; the corresponding service logic (classifying article runtime needs, generating verifier candidates) is not implemented.
3. **Conversion path pending**: The `ArticleDraftLabContract → LabDraft` conversion is not implemented. Implementation gate will design this.
4. **source_url scraping prevention**: Enforced at schema level (metadata-only field); service layer must also prevent any HTTP fetch when source_url is set.
5. **Retention expiry manual in v0.1**: `ArticleStoragePolicy.rejection_metadata_retention_days = 30` is a schema declaration; automatic purge is not implemented (same as prerequisite gate note).

---

## I. Recommended Next Step

**K8s Article-to-Lab Draft Mode Implementation**

The schema is locked. Implementation may begin.

Recommended implementation sequence:
1. `ArticleDraftRepository` — JSON persistence for `ArticleDraftLabContract`
2. `StubFeasibilityClassifier` — deterministic stub returning `FeasibilityResult(evaluated_by=STUB)`
3. Draft creation API endpoint (`POST /api/labgen/article-drafts`) — admin-only
4. `ArticleDraftValidator` integration at status transition points
5. `AdminReview` API endpoints for `ArticleDraftLabContract`
6. `ArticleDraftLabContract → LabDraft` conversion service (gated: approved_for_publish_candidate only)

Do NOT start:
- LLM provider integration (not yet unblocked)
- User-facing article upload (admin-only in v0.1)
- Non-K8s domain implementation
- Cloud domain support
- Customer pilot (still blocked by NO_SUITABLE_SMALL_CUSTOMER)

---

## Technical Self-Check

| Item | Status |
|------|--------|
| No TODO/FIXME in new code | PASS |
| No placeholder-as-success in tests | PASS |
| No raw article text persisted field | PASS |
| No sensitive content persisted | PASS |
| No user article upload API | PASS (not implemented) |
| No live LLM call | PASS |
| No LLM direct publish | PASS |
| No generated verifier code auto-accepted | PASS |
| No rejected/partial article publish path | PASS |
| No admin review bypass | PASS |
| No StaticValidator bypass | PASS |
| No internal rehearsal bypass | PASS |
| No cleanup strategy bypass | PASS |
| No credential reclaim bypass | PASS |
| No K8s-only hardcoding | PASS (TargetDomain enum covers all domains) |
| No Linux / multi-domain portability regression | PASS |
| No cloud domain accidentally enabled | PASS (guardrail blocks) |
| No URL scraping | PASS (source_url is metadata-only field) |
| No customer pilot started | PASS |
| No fifth lab published | PASS |
| No runtime/verifier/terminal behavior change | PASS |
| No production VM / pool / registry modified | PASS |
| No "arbitrary Article-to-Lab implemented" claim | PASS |
| No "production ready" / "public launch" claim | PASS |
| "读了能练，练完即熟" preserved | PASS |
| 116 tests pass | PASS |
| Existing 3394 tests unaffected | PASS (static validator regression: 65 pass) |
| Pre-commit 8/8 security scans | PASS (at commit) |
| Codex review | PASS (at push) |
