# K8S Article-to-Lab Admin Review Rehearsal Result v0.1

**Gate**: K8S_ARTICLE_TO_LAB_ADMIN_REVIEW_REHEARSAL_RESULT  
**Date**: 2026-06-17  
**Decision**: **K8S_ARTICLE_TO_LAB_ADMIN_REHEARSAL_PASSED_WITH_NOTES**

---

## A. Executive Summary

End-to-end admin rehearsal of the Article-to-Lab draft pipeline has been executed with 4 controlled
K8s article input samples. All core safety invariants passed. One MEDIUM workflow gap (MEDIUM-001)
was found and fixed during the rehearsal. Two lower-severity findings are documented.

**What was rehearsed:**
- Admin-only access enforcement (all 9 endpoints)
- Feasibility classification for all 4 article types
- Raw text non-persistence (verified via API response + JSON file inspection)
- Sensitive content hard-rejection without persistence
- Admin review confirmed_* gate enforcement
- StaticValidator bridge (ArticleDraftValidator, 15 checks)
- Full happy path to APPROVED_FOR_PUBLISH_CANDIDATE and LabDraft conversion
- Catalog isolation (generated drafts never in learner catalog)
- LLM-call invariant (evaluated_by == stub for all samples)

**Whether next step may proceed**: Yes — K8s Article-to-Lab Internal Rehearsal to Publish Candidate
may proceed once findings are acknowledged.

---

## B. North Star Alignment

> "读了能练，练完即熟" (primary slogan, updated 2026-06-20; secondary: "读完即练，结果说话")

- Article-to-Lab direction confirmed as the platform's north star
- K8s used as domain proof (not final boundary)
- Linux / multi-domain portability preserved (no K8s hardcoding in shared schema)
- No claim that arbitrary Article-to-Lab is implemented
- Cloud domain remains blocked (stub classifier returns NOT_LAB_READY + rejection_code=stub.cloud_domain_blocked_v1)
- No live LLM called at any stage
- No generated draft entered learner catalog

---

## C. Rehearsal Scope

| Dimension | Status |
|-----------|--------|
| Admin-only entry point | ✅ verified |
| Stub/rule-based classifier | ✅ verified (evaluated_by=stub for all samples) |
| No live LLM | ✅ verified (0 LLM calls) |
| No publish | ✅ verified (all generated LabDrafts are DRAFT) |
| No learner catalog entry | ✅ verified |
| No runtime changes | ✅ no VM/K3s/namespace side effects |
| No customer pilot | ✅ not started |

---

## D. Input Samples

### Sample 1: Directly Lab-Ready ConfigMap Article
Article content: K8s ConfigMap tutorial with fenced code blocks (`kubectl create configmap`,
`kubectl get configmap`, `kubectl describe configmap`), headings (## Step 1, ## Step 2),
verifiable outcomes.

**Sanitized — no real secrets used.**

### Sample 2: Partially Lab-Ready K8s Article
Article content: Conceptual K8s ConfigMap and Deployment description with no executable commands
or shell prompts.

### Sample 3: Not Lab-Ready Theory Article
Article content: Pure theory ("This article discusses...") with K8s buzzwords but no executable
steps. Includes "In conclusion" non-operable signal.

### Sample 4: Sensitive Content (Fake Credentials)
Article content: Contains `api_key=sk-test-redacted-example-placeholder-value` (fake) and
`-----BEGIN PRIVATE KEY-----` (fake PEM block — clearly not a real key, content is placeholder).
**No real secrets were used in this rehearsal.**

---

## E. Results by Sample

### Sample 1: Directly Lab-Ready ConfigMap

| Check | Result |
|-------|--------|
| feasibility_status | `directly_lab_ready` |
| evaluated_by | `stub` |
| target_domain | `k8s` |
| verifier_feasibility | `needs_parameterization` |
| rejection_code | (none) |
| draft created | ✅ 201 |
| raw_text_persisted | `false` |
| content_hash | SHA-256 computed and stored ✅ |
| initial status | `draft` |
| admin_decision | `pending` (not auto-approved) |
| source_grounding (initial) | empty — admin must PATCH |
| learner catalog | absent ✅ |
| PATCH source_grounding | ✅ 200 (MEDIUM-001 fixed) |
| PATCH required_runtime | ✅ 200 (MEDIUM-001 fixed) |
| PATCH verifier_candidates | ✅ 200 (MEDIUM-001 fixed) |
| Full pipeline to publish_candidate | ✅ after enrichment |
| LabDraft converted | DRAFT (not published) ✅ |
| LabDraft in learner catalog | absent ✅ |

### Sample 2: Partially Lab-Ready K8s

| Check | Result |
|-------|--------|
| feasibility_status | `partially_lab_ready` |
| missing_requirements | populated (commands, verifiable outcomes, structured steps) |
| evaluated_by | `stub` |
| advance to publish_candidate | ❌ blocked by `can_proceed_to_publish_candidate()` |
| learner catalog | absent ✅ |

### Sample 3: Not Lab-Ready Theory

| Check | Result |
|-------|--------|
| feasibility_status | `not_lab_ready` |
| rejection_code | `stub.no_operable_content` |
| evaluated_by | `stub` |
| APPROVE from DRAFT | succeeds → APPROVED_FOR_STATIC_VALIDATION (see LOW-001) |
| advance to internal rehearsal | ❌ 409 blocked by validator |
| learner catalog | absent ✅ |

### Sample 4: Sensitive Content (Fake Credentials)

| Check | Result |
|-------|--------|
| feasibility_status | `not_lab_ready` |
| rejection_code | `stub.hard_reject_safety_flag` |
| safety_flags | `contains_secret_like_content` |
| fake key in response | absent ✅ |
| fake key in persisted JSON | absent ✅ |
| draft created | ✅ (rejection metadata only) |
| learner catalog | absent ✅ |

---

## F. Admin Review Findings

| Scenario | Result |
|----------|--------|
| APPROVE with 0 confirmed_* | ❌ 403 (correct) |
| APPROVE with 1/6 confirmed_* | ❌ 403 (correct) |
| APPROVE with all 6 confirmed_* | ✅ 200 → APPROVED_FOR_STATIC_VALIDATION |
| REQUEST_CHANGES | ✅ 200 → needs_changes |
| REJECT | ✅ 200 → rejected |

**confirmed_* gate**: All 6 required fields must be True:
- `confirmed_source_grounding`
- `confirmed_safety`
- `confirmed_cleanup`
- `confirmed_verifier_strategy`
- `confirmed_no_raw_secret`
- `confirmed_no_direct_publish`

**directly_lab_ready auto-approve**: ❌ not triggered — status starts as `draft`, admin_decision
starts as `pending`. Admin review is always required.

**Friction**: Admin must explicitly pass `user_confirmed_right_to_use=True` and
`user_confirmed_no_secrets=True` in the create request (see NOTE-001).

---

## G. StaticValidator Bridge Findings

| Check | Result |
|-------|--------|
| /validate endpoint returns results | ✅ |
| Result count (15 checks) | ✅ exactly 15 |
| All check_id fields present | ✅ |
| Validate does not publish | ✅ (catalog unchanged) |
| Guardrails block partial/rejected at APPROVED_FOR_INTERNAL_REHEARSAL | ✅ |
| source_grounding check fires at APPROVED_FOR_PUBLISH_CANDIDATE | ✅ |
| cloud domain check fires at non-DRAFT status | ✅ |

The StaticValidator bridge works correctly. Validator checks are status-scoped (many only fire
at APPROVED_FOR_PUBLISH_CANDIDATE or APPROVED_FOR_INTERNAL_REHEARSAL), which is the intended
layered-gates design.

---

## H. Storage / Safety Findings

| Invariant | Status |
|-----------|--------|
| raw_text_persisted always False | ✅ |
| content_hash persisted (SHA-256) | ✅ |
| fake secret not in API response | ✅ |
| fake secret not in JSON file | ✅ |
| source_grounding minimal (no full article copies) | ✅ (admin-entered excerpts only) |
| rejected draft storage: rejection metadata only | ✅ |

---

## I. Invariants

| Invariant | Status |
|-----------|--------|
| LLM call count | 0 ✅ |
| evaluated_by == stub (all 4 samples) | ✅ |
| runtime/VM/K3s unchanged | ✅ |
| terminal behavior unchanged | ✅ |
| verifier execution unchanged | ✅ |
| learner catalog unchanged after all 4 samples | ✅ |
| production VMID 500-599 not touched | ✅ |
| 5th lab not published | ✅ |
| customer pilot not started | ✅ |
| concurrency not changed | ✅ |

---

## J. Issue Triage

### MEDIUM-001 — Pipeline-critical PATCH fields missing
**Dimension**: admin review / draft generation  
**Severity**: MEDIUM  
**Description**: `PatchArticleDraftRequest` did not expose `source_grounding`, `required_runtime`,
or `verifier_candidates`. The `_ALLOWED_UPDATE_KEYS` set also lacked `source_grounding`. This meant
admins could not complete the pipeline to `APPROVED_FOR_PUBLISH_CANDIDATE` via API, because
`can_proceed_to_publish_candidate()` requires non-empty `source_grounding` and non-null
`required_runtime.cleanup_strategy`.  
**Fix applied**: Extended `PatchArticleDraftRequest` with typed Pydantic model fields for all
three. Changed PATCH extraction to `model_fields_set + getattr` to preserve Pydantic instances.
Added `source_grounding` to `_ALLOWED_UPDATE_KEYS`. Safety-reviewer B-class review: PASS.  
**Status**: ✅ Fixed + tested (53 rehearsal tests, 3623 total tests, 93.59% coverage)

### LOW-001 — NOT_LAB_READY article can be APPROVED from DRAFT status
**Dimension**: admin review / feasibility  
**Severity**: LOW  
**Description**: `ArticleDraftValidator._check_rejected_feasibility_cannot_publish` is
status-scoped — it only fires when contract.status is in the three APPROVED_FOR_* states. As a
result, an admin can APPROVE a NOT_LAB_READY article from DRAFT status (moving it to
APPROVED_FOR_STATIC_VALIDATION). However, the next advance step
(`advance_to_internal_rehearsal`) is blocked with 409 by the validator. The publish path is
effectively sealed — just one step later than expected.  
**UX impact**: Admin sees a misleading "approve succeeded" but then advance fails. Confusing.  
**Fix**: Not fixed in this commit — no safety risk. Future improvement: add a guardrail check
that fires during APPROVE review when feasibility is NOT_LAB_READY.  
**Status**: Documented.

### NOTE-001 — user_confirmed_* defaults to False, blocks advance
**Dimension**: UX / admin onboarding  
**Severity**: NOTE  
**Description**: `CreateArticleDraftRequest.user_confirmed_right_to_use` and
`user_confirmed_no_secrets` default to `False`. `ArticleDraftValidator._check_user_confirmations_required`
blocks any status advance beyond DRAFT if either is False. Admins submitting via the API must
explicitly set both to `True` in the POST body.  
**Fix**: Documentation note. The default-False behavior is correct (admin must consciously affirm).
API response could include a clearer error message noting which confirmation is missing.  
**Status**: Documented.

---

## K. Final Decision

**K8S_ARTICLE_TO_LAB_ADMIN_REHEARSAL_PASSED_WITH_NOTES**

Notes:
1. MEDIUM-001 was found and fixed during the rehearsal — the full pipeline now works end-to-end
2. LOW-001 does not compromise safety — the publish path is still blocked for NOT_LAB_READY
3. NOTE-001 is a UX friction point that does not affect correctness
4. The stub classifier is conservative — many K8s articles will be `PARTIALLY_LAB_READY`
   (intentional fail-closed behavior). Admin enrichment is always required.
5. Generated LabDrafts from the pipeline are always `DRAFT` — no learner-visible lab was created

---

## L. Recommended Next Step

**K8s Article-to-Lab Internal Rehearsal to Publish Candidate**

The pipeline has been validated end-to-end (Article → Contract → Admin Review → StaticValidator →
LabDraft DRAFT). The next step is to run an internal rehearsal where a generated LabDraft is
enriched by an admin to the point where it can pass StaticValidator and be considered for publish.
This will surface gaps in the LabDraft quality for generated content vs. hand-authored labs.

Specifically:
1. Take the LabDraft created in this rehearsal
2. Fill in step details, verifier parameters, commands, explain fields
3. Run StaticValidator (full LabDraft check, not ArticleDraftValidator)
4. Iterate until it passes all 13 StaticValidator checks
5. Document gaps between generated content and publishable quality
6. Decide: iterate on the stub generator OR proceed to LLM Provider Spike

---

## Technical Self-Check

- [x] No TODO/FIXME in new production code
- [x] No placeholder-as-success
- [x] No raw article text persisted
- [x] No raw article text in API response
- [x] No sensitive content persisted
- [x] No sensitive content in response/log/artifact
- [x] No public article upload
- [x] No URL scraping
- [x] No live LLM call
- [x] No LLM direct publish
- [x] No stub direct publish
- [x] No generated verifier code auto-accepted
- [x] No rejected/partial article publish path
- [x] No admin review bypass
- [x] No StaticValidator bypass
- [x] No cleanup strategy bypass
- [x] No K8s-only hardcoding into generic schema
- [x] No Linux/multi-domain portability regression
- [x] No cloud domain accidentally enabled
- [x] No learner catalog generated draft
- [x] No customer pilot started
- [x] No 5th lab published
- [x] No runtime/verifier/terminal behavior change
- [x] No production VM/pool/registry modified
- [x] No "arbitrary Article-to-Lab already implemented" claim
- [x] No "production ready / public launch" claim
- [x] "读完即练，结果说话" preserved
