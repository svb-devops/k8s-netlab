# K8S Article-to-Lab Internal Rehearsal to Publish Candidate Result v0.1

**Gate**: K8S_ARTICLE_TO_LAB_INTERNAL_REHEARSAL_TO_PUBLISH_CANDIDATE_RESULT  
**Date**: 2026-06-20  
**Decision**: **PUBLISH_CANDIDATE_BLOCKED_BY_MISSING_REHEARSAL_BRIDGE**

---

## A. Executive Summary

An admin-curated K8s ConfigMap article was run through the full Article-to-Lab pipeline:
Feasibility Gate → ArticleDraftLabContract → Admin Review → ArticleDraftValidator →
`APPROVED_FOR_INTERNAL_REHEARSAL` → `APPROVED_FOR_PUBLISH_CANDIDATE` → `convert_to_lab_draft`.

All six pipeline stages passed. The resulting `LabDraft` (lab_id `3d9e3331-d65e-43d9-83bf-8247feaca462`)
has `publish_status=DRAFT`, is isolated to a temp repo, and is absent from the production learner
catalog.

**Bridge gap found**: `LabSessionService.run_precheck()` (line 259) requires
`draft.publish_status == PublishStatus.PUBLISHED`. The converted draft is always `DRAFT`. Publishing
it to satisfy the precheck would add it to the learner catalog — which is forbidden by a hard
invariant. Therefore no real lab session can be created from a generated article draft without a
dedicated rehearsal bridge.

**Final decision**: `PUBLISH_CANDIDATE_BLOCKED_BY_MISSING_REHEARSAL_BRIDGE`  
**Whether next step may proceed**: Yes — pending implementation of the Internal Rehearsal Bridge
(see Section L).

---

## B. North Star Alignment

> "读了能练，练完即熟" (primary slogan)  
> Auxiliary: "读了能做，做了就懂"  
> Alt expression: "读完即练，结果说话"

| Check | Status |
|-------|--------|
| K8s used as domain proof, not final boundary | ✅ |
| No claim that arbitrary Article-to-Lab is implemented | ✅ |
| Linux / multi-domain schema portability preserved | ✅ |
| Cloud domain remains blocked | ✅ |
| No live LLM called at any stage | ✅ |
| No generated draft entered learner catalog | ✅ |
| No customer pilot started | ✅ |
| No 5th lab published | ✅ |

---

## C. Input Article Summary

**Source type**: INTERNAL_DOC (admin-curated; not from learner upload or URL scraping)  
**Content length**: 644 characters  
**Topic**: K8s ConfigMap — creating and verifying a ConfigMap via `kubectl`  
**Raw text persisted**: No (SHA-256 hash only: content_hash stored)  
**Sanitized**: No real secrets; no real credentials  

**Article characteristics:**
- Contains fenced code blocks (``` ` ``` blocks with `kubectl create configmap` and `kubectl get configmap`)
- Contains verifiable K8s outcomes (ConfigMap name, namespace pattern)
- Contains structured steps (## Step headings)
- No cloud-provider dependencies; no destructive operations
- No API keys, private keys, or connection strings

**Why this article was chosen**: Minimal viable K8s article — fewest content tokens needed
to trigger `DIRECTLY_LAB_READY` classification, maximum isolation from production data.

---

## D. Feasibility Result

| Field | Value |
|-------|-------|
| status | `DIRECTLY_LAB_READY` |
| evaluated_by | `STUB` (no LLM called) |
| target_domain_candidates | `[k8s]` |
| operability_score | `0.75` |
| verifier_feasibility | `NEEDS_PARAMETERIZATION` |
| cleanup_feasibility | `namespace_delete` |
| runtime_feasibility | `k8s_namespace` |
| rejection_code | (none) |
| safety_flags | `[]` |
| reasons | `["article contains k8s commands, structured steps, and verifiable outcomes"]` |

StubFeasibilityClassifier correctly identified this as K8s domain with operable content.
`evaluated_by=STUB` confirms zero LLM calls.

---

## E. Guided Practice Draft Review

**ArticleDraftLabContract fields after admin enrichment:**

| Field | Value |
|-------|-------|
| draft_id | `88adee20-1a50-4183-8879-046334bc144d` |
| target_domain | `K8S` |
| learning_objective | "Understand K8s ConfigMaps and practice creating/verifying using kubectl." |
| required_runtime.runtime_type | `K8S_NAMESPACE` |
| required_runtime.cleanup_strategy | `namespace_delete` |
| required_runtime.production_dependency | `False` |
| required_runtime.isolation_level | `namespace` |
| required_runtime.estimated_resource_cost | `low` |
| verifier_candidates count | 1 |
| verifier.primitive_name | `configmap_exists` |
| verifier.candidate_state | `REUSABLE_EXISTING` |
| verifier.parameters | `{name: my-app-config, namespace_template: lab-{session_id}}` |
| verifier.admin_reviewed | `True` |
| source_grounding count | 1 |
| source_grounding.excerpt | `kubectl create configmap my-app-config --from-literal=app.env=production` |
| source_grounding.source_section | `Step 1` |
| source_grounding.contains_sensitive_content | `False` |
| learner_steps count | 0 (stub generator placeholder) |
| review_notes | `["ConfigMap article: commands present, verifier feasible, namespace_delete cleanup, no secrets."]` |

**Gap**: `learner_steps` is empty. The stub generator does not produce step content —
this is expected for v0.1. An admin would need to author step details manually or iterate
with the generator before the LabDraft can pass StaticValidator for publish.

---

## F. Admin Review Result

| Check | Result |
|-------|--------|
| Admin-only access enforced | ✅ (service layer via `reviewer_id`) |
| admin_decision = APPROVE | ✅ |
| confirmed_source_grounding | ✅ True |
| confirmed_safety | ✅ True |
| confirmed_cleanup | ✅ True |
| confirmed_verifier_strategy | ✅ True |
| confirmed_no_raw_secret | ✅ True |
| confirmed_no_direct_publish | ✅ True |
| reviewer_id | `admin-rehearsal` |
| comments | `["ConfigMap article: directly_lab_ready. All criteria verified."]` |

All 6 `confirmed_*` gates passed. Admin review decision is recorded and immutable.

---

## G. Validator Result

**Advance to `APPROVED_FOR_INTERNAL_REHEARSAL`**: ✅ (status transition succeeded)  
**Advance to `APPROVED_FOR_PUBLISH_CANDIDATE`**: ✅ (status transition succeeded)  
**`can_proceed_to_publish_candidate()`**: `True`

Gate checks satisfied:
- `feasibility.status == DIRECTLY_LAB_READY` ✅
- all 6 `confirmed_*` fields True ✅
- `target_domain` not in BLOCKED_DOMAINS ✅
- `required_runtime.cleanup_strategy` set (`namespace_delete`) ✅
- `required_runtime.production_dependency == False` ✅
- All verifier_candidates with `review_required=True` have `admin_reviewed=True` ✅
- `source_grounding` non-empty ✅

No ArticleDraftValidator blocking failures. Full pipeline to `APPROVED_FOR_PUBLISH_CANDIDATE`
confirmed structurally sound.

---

## H. Internal Rehearsal Result

**`convert_to_lab_draft` result:**

| Field | Value |
|-------|-------|
| lab_id | `3d9e3331-d65e-43d9-83bf-8247feaca462` |
| source_article_id | `88adee20-1a50-4183-8879-046334bc144d` |
| publish_status | `DRAFT` |
| Stored in prod `data/lab_drafts.json` | No (isolated to `/tmp/rehearsal_lab_drafts.json`) |
| In learner catalog | No ✅ |

**Rehearsal bridge gap diagnosis:**

`LabSessionService.run_precheck()` (line 259 of `backend/labgen/lab_session_service.py`):

```python
if draft.publish_status != PublishStatus.PUBLISHED:
    failures.append(FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value)
```

This check exists to prevent learners from starting sessions on unpublished labs.
However, a lab generated from an article is never published at this stage:

- `convert_to_lab_draft()` always sets `publish_status=PublishStatus.DRAFT`
- Publishing would enter the draft into the learner catalog — a hard forbidden invariant
- Therefore `PRECHECK_DRAFT_NOT_PUBLISHED` will always fire for a generated lab at this stage

**Consequence**: A real `LabSession` cannot be created for a generated lab during internal
rehearsal without either (a) publishing the draft (forbidden) or (b) implementing a rehearsal
bridge that bypasses the publish_status check under controlled conditions.

**VERDICT**: `PUBLISH_CANDIDATE_BLOCKED_BY_MISSING_REHEARSAL_BRIDGE`

---

## I. Safety Invariants

| Invariant | Status |
|-----------|--------|
| LLM call count | 0 ✅ |
| evaluated_by == STUB | ✅ |
| raw article text not persisted | ✅ (SHA-256 hash only) |
| raw article text not in logs | ✅ |
| sensitive content not persisted | ✅ |
| generated LabDraft publish_status == DRAFT | ✅ |
| generated LabDraft not in prod `data/lab_drafts.json` | ✅ (verified: lab_id absent from production) |
| generated LabDraft not in learner catalog | ✅ |
| production VMID 500-599 not touched | ✅ |
| runtime/VM/K3s/namespace unchanged | ✅ |
| terminal/verifier behavior unchanged | ✅ |
| 5th lab not published | ✅ |
| customer pilot not started | ✅ |
| cloud domain not enabled | ✅ |
| no arbitrary Article-to-Lab 已实现 claim | ✅ |
| no production ready / public launch claim | ✅ |

All safety invariants satisfied. The bridge gap is a structural finding, not a safety violation.

---

## J. Issue Triage

### BLOCKER-001 — Internal Rehearsal Bridge Not Implemented

**Dimension**: lab session creation / rehearsal path  
**Severity**: BLOCKER  
**Description**: `LabSessionService.run_precheck()` line 259 requires
`draft.publish_status == PublishStatus.PUBLISHED`. A lab generated from an article always has
`publish_status=DRAFT`. Publishing it to satisfy the precheck would enter it into the learner
catalog — forbidden. There is no current mechanism to create a `LabSession` against a
`DRAFT` lab that bypasses this check under controlled admin conditions.

**Impact**: Cannot complete an end-to-end rehearsal session (step execution, verifier, cleanup)
for a generated lab without implementing the bridge.

**Proposed fix**: Implement an `InternalRehearsalBridge` that:
1. Allows admin-authenticated session creation against `DRAFT` labs with `source_article_id` set
2. Marks such sessions as `REHEARSAL_MODE` (separate from learner catalog sessions)
3. Does not add the lab to the learner catalog or advance publish_status
4. Runs cleanup identically to a real session (namespace_delete)

**Status**: Not fixed. Blocker for next gate.

---

### LOW-001 — Stub Generator Produces Empty learner_steps

**Dimension**: LabDraft content quality  
**Severity**: LOW  
**Description**: `LabDraftGeneratorStub._build_lab_draft_from_contract()` creates a LabDraft
with `steps=[]`. The StaticValidator will block this draft from being published due to missing
step content. This is expected for v0.1 (admin manual enrichment required), but documents the
gap between "passes pipeline" and "ready to publish."

**Impact**: Generated LabDrafts are not publishable without admin step authoring.
This is the intended design for v0.1.

**Status**: Documented. Deferred to LLM Provider Spike.

---

### NOTE-001 — learner_steps from article contract not mapped to LabDraft

**Dimension**: pipeline fidelity  
**Severity**: NOTE  
**Description**: `ArticleDraftLabContract.learner_steps` is 0 for this rehearsal. The stub
generator does not extract step content from article text (no NLP / no LLM). Admin would need
to author step text manually.

**Status**: Documented. Expected for stub mode.

---

## K. Final Decision

**PUBLISH_CANDIDATE_BLOCKED_BY_MISSING_REHEARSAL_BRIDGE**

The Article-to-Lab pipeline (Article → Contract → Admin Review → Validator → LabDraft) is
structurally sound and passes all safety invariants. However, the Internal Rehearsal itself
(LabSession creation, step execution, verifier, cleanup) cannot be completed because
`LabSessionService.run_precheck()` blocks DRAFT-status labs.

This is not a regression, safety failure, or pipeline design error. It is a structural gap
that was expected to surface at this rehearsal stage — the previous gate
(`K8S_ARTICLE_TO_LAB_ADMIN_REVIEW_REHEARSAL_PASSED_WITH_NOTES`) explicitly documented that
this rehearsal would "surface gaps in LabDraft quality for generated content" and identified
step-enrichment as the key next action.

**What this decision means:**
- The pipeline may be considered a `PUBLISH_CANDIDATE` at the schema/contract level ✅
- The pipeline cannot be considered a `PUBLISH_CANDIDATE` at the rehearsal level ❌ (bridge missing)
- The decision is `BLOCKED`, not `FAILED` — no invariants were violated
- The path forward is clear and bounded (see Section L)

---

## L. Recommended Next Step

**Internal Rehearsal Bridge Implementation**

Implement a dedicated rehearsal path that allows admin-authenticated lab sessions against
`DRAFT` labs with `source_article_id` set. Specifically:

1. **Add `InternalRehearsalBridge`** — a new service (or precheck bypass mode) that:
   - Accepts `session_mode=REHEARSAL` flag on `POST /api/lab-sessions`
   - Requires `X-Admin-Token` or admin role (not student-accessible)
   - Skips the `PRECHECK_DRAFT_NOT_PUBLISHED` check
   - Tags the session with `rehearsal_mode=True`
   - Does not add lab to learner catalog

2. **Run end-to-end rehearsal** with the generated LabDraft:
   - Create a rehearsal session (REHEARSAL_MODE)
   - Execute verifier (`configmap_exists`)
   - Test cleanup (namespace_delete)
   - Document verifier pass/fail results

3. **Assess generated content quality**:
   - Does the stub-generated LabDraft produce verifiable steps?
   - What percentage of StaticValidator checks pass without manual enrichment?
   - Document gap score (generated quality vs publishable quality)

4. **Decide next action** based on gap score:
   - Gap small → Iterate stub generator + admin enrichment workflow
   - Gap large → Proceed to LLM Provider Spike for content generation

---

## Technical Self-Check

- [x] No TODO/FIXME in new production code
- [x] No placeholder-as-success
- [x] No raw article text persisted
- [x] No raw article text in logs or artifacts
- [x] No sensitive content persisted
- [x] No sensitive content in response/log/artifact
- [x] No public article upload
- [x] No URL scraping
- [x] No live LLM call (evaluated_by=STUB throughout)
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
- [x] "读了能练，练完即熟" preserved as primary slogan
