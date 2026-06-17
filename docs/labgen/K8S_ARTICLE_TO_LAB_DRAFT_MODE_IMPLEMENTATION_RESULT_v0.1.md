# K8S Article-to-Lab Draft Mode Implementation Result v0.1

**Gate**: K8S_ARTICLE_TO_LAB_DRAFT_MODE_IMPLEMENTATION_RESULT  
**Date**: 2026-06-17  
**Decision**: **K8S_ARTICLE_TO_LAB_DRAFT_MODE_READY_WITH_NOTES**

---

## A. Executive Summary

Admin-only, stub-based Article-to-Lab draft pipeline has been implemented and validated.

An admin can now submit K8s article text via API, receive a feasibility assessment from a deterministic stub classifier, and obtain an `ArticleDraftLabContract` in `DRAFT` status. The contract then flows through an explicit human review/validation pipeline before it can be converted to a `LabDraft` (which is still DRAFT, not published).

**What was implemented:**
- Deterministic stub feasibility classifier (no LLM, fail-closed)
- Article draft persistence (flock JSON, raw text never stored)
- Admin-only draft management API (9 endpoints)
- Admin review decision recording with all 6 `confirmed_*` gates
- `ArticleDraftValidator` guardrail integration (15 checks)
- `ArticleDraftLabContract` → `LabDraft` conversion service (DRAFT only, never published)
- 60 new tests, all passing

**What remains out of scope (v0.1):**
- Live LLM classification
- Learner-facing article upload
- Auto-publish of generated drafts
- Linux / Docker / multi-domain implementation
- Customer pilot
- Frontend admin UI

**Next step may proceed**: K8s Article-to-Lab Admin Review Rehearsal.

---

## B. North Star Alignment

> "读完即练，结果说话"

- K8s is domain proof, not the final boundary
- Article → Feasibility Gate → Draft Contract → Admin Review → StaticValidator → LabDraft (DRAFT) chain is working end-to-end
- No claim that arbitrary Article-to-Lab is implemented — only K8s stub mode
- Linux / multi-domain schema portability preserved (no K8s hardcoding in shared schema)
- Cloud domain remains blocked (stub classifier returns NOT_LAB_READY + rejection_code=stub.cloud_domain_blocked_v1)

---

## C. Scope

| Dimension | Status |
|-----------|--------|
| Admin-only entry point | ✅ implemented |
| Stub/rule-based classifier | ✅ implemented |
| Template-assisted draft generator | ✅ implemented (stub, K8s patterns) |
| Draft persistence | ✅ implemented |
| Admin review hooks | ✅ implemented |
| StaticValidator bridge | ✅ integrated (ArticleDraftValidator.validate()) |
| Live LLM | ❌ not implemented, not called |
| Learner article upload | ❌ not implemented |
| Auto-publish | ❌ not implemented |
| Learner catalog entry | ❌ not created |
| Runtime/verifier/terminal changes | ❌ not modified |

---

## D. Implementation

### StubFeasibilityClassifier (`backend/labgen/stub_feasibility_classifier.py`)

Deterministic, no-LLM classifier. Output: `FeasibilityResult(evaluated_by=STUB)`.

**Tiers:**
1. Hard reject: secrets (API key / token / private key patterns) → `NOT_LAB_READY`, `rejection_code=stub.hard_reject_safety_flag`
2. Cloud domain: `NOT_LAB_READY`, `rejection_code=stub.cloud_domain_blocked_v1`
3. Unknown domain: `PARTIALLY_LAB_READY`
4. No operable content: `NOT_LAB_READY`, `rejection_code=stub.no_operable_content`
5. K8s + commands + verifiable outcomes: `DIRECTLY_LAB_READY`
6. Default fallback: `PARTIALLY_LAB_READY` with `missing_requirements`

**Safety patterns checked:** `_SECRET_PATTERNS`, `_REAL_CREDENTIAL_PATTERNS`, `_PRODUCTION_ENV_PATTERNS`, `_DESTRUCTIVE_PATTERNS`

### ArticleDraftRepository (`backend/labgen/article_draft_repository.py`)

- Flock JSON persistence to `data/article_drafts.json`
- Uses `safe_read_json` / `safe_update_json` (same pattern as all other repositories)
- Methods: `create`, `get`, `update`, `delete`, `list_all`
- Raw text never reaches this layer

### ArticleDraftService (`backend/labgen/article_draft_service.py`)

Status machine:
```
DRAFT → (admin review APPROVE) → APPROVED_FOR_STATIC_VALIDATION
      → (admin review REQUEST_CHANGES) → NEEDS_CHANGES
      → (admin review REJECT) → REJECTED
APPROVED_FOR_STATIC_VALIDATION → APPROVED_FOR_INTERNAL_REHEARSAL
APPROVED_FOR_INTERNAL_REHEARSAL → APPROVED_FOR_PUBLISH_CANDIDATE
APPROVED_FOR_PUBLISH_CANDIDATE → (convert) → LabDraft (DRAFT)
```

Key invariants enforced:
- APPROVE requires all 6 `confirmed_*` fields True
- APPROVE runs ArticleDraftValidator; any FAILED check → 409 guardrail_blocked
- `convert_to_lab_draft` only from `APPROVED_FOR_PUBLISH_CANDIDATE`
- Resulting `LabDraft.publish_status` is always `PublishStatus.DRAFT`

### article_draft_routes.py

Prefix: `/api/labgen/article-drafts`  
Auth: all endpoints require `_require_admin` (get_current_user + auth_manager.is_admin())

| Method | Path | Action |
|--------|------|--------|
| POST | / | Create draft from raw_text |
| GET | / | List all drafts |
| GET | /{id} | Get draft |
| PATCH | /{id} | Update editable fields |
| POST | /{id}/review | Record admin decision |
| POST | /{id}/validate | Re-run ArticleDraftValidator |
| POST | /{id}/advance | Advance to next stage |
| POST | /{id}/convert | Convert to LabDraft (DRAFT) |
| DELETE | /{id} | Delete draft |

---

## E. Safety / Storage

| Invariant | Verified |
|-----------|---------|
| raw_text never persisted | ✅ |
| raw_text not in API response | ✅ |
| sensitive content causes hard reject | ✅ |
| `raw_text_persisted` always False | ✅ (model_validator + service layer) |
| content_hash computed and stored | ✅ (SHA-256 of raw_text) |
| source_grounding excerpts minimized | ✅ (no full article copies) |
| LLM never called | ✅ |
| generated draft not auto-published | ✅ |
| generated draft not in learner catalog | ✅ |
| cloud domain blocked | ✅ |
| rejected/partial cannot publish | ✅ (ArticleDraftValidator guardrails) |
| directly_lab_ready still requires admin review | ✅ |

---

## F. Validation / Tests

**Test file:** `tests/test_labgen_article_draft_api.py` — 60 tests

| Test class | Tests | Coverage |
|-----------|-------|---------|
| TestArticleDraftRepository | 10 | CRUD, raw_text not persisted, deserialization |
| TestStubFeasibilityClassifier | 14 | All tiers, safety flags, hash determinism |
| TestArticleDraftService | 17 | Full state machine, convert, guardrail blocking |
| TestArticleDraftEndpoints | 13 | All 9 endpoints, status codes, response shape |
| TestArticleDraftAdminAuthEnforcement | 3 | 403 for non-admin on create/list/get |

**Full test suite:**
- 3570 passed, 0 failed
- Coverage: 93.03% (≥ 92% target met)
- 8-item security scan: PASS (pre-push hook)
- Codex: PASS
- pre-commit: PASS

---

## G. Decision

**K8S_ARTICLE_TO_LAB_DRAFT_MODE_READY_WITH_NOTES**

Notes:
1. `StubFeasibilityClassifier` is conservative — many K8s articles will be `PARTIALLY_LAB_READY` rather than `DIRECTLY_LAB_READY` (intentional, fail-closed)
2. `_build_lab_draft_from_contract` creates minimal LabDraft stubs; admin must fill in step details before the LabDraft can pass StaticValidator for publish
3. `ArticleDraftValidator` will block most generated contracts at approval time because typical article-derived contracts lack `source_grounding_snippets`, `verifier_candidates`, `learning_objective`, and `cleanup_requirements` — this is expected and correct (admin must enrich the contract)
4. `ArticleStoragePolicy.excluded_fields` list (persisted) contains field name strings like `"raw_article_text"` — this is the exclusion manifest, not persisted content

---

## H. Recommended Next Step

**K8s Article-to-Lab Admin Review Rehearsal**

Perform an end-to-end admin rehearsal:
1. Submit a real K8s article via POST /api/labgen/article-drafts
2. Review the feasibility result and fill in missing fields (PATCH)
3. Run /validate and fix blocking guardrail failures
4. Record APPROVE decision with all confirmed_* = True
5. Advance through internal rehearsal → publish candidate
6. Convert to LabDraft
7. Verify LabDraft is in DRAFT status and not in learner catalog
8. Document gaps found for iteration

This rehearsal will surface real friction points before any external user flow is designed.

---

## Technical Self-Check

- [ ] No TODO/FIXME in new code: ✅ (TODO strings are content placeholders in generated lab steps, not code TODOs)
- [ ] No placeholder-as-success: ✅
- [ ] No raw article text persisted: ✅
- [ ] No raw article text in logs: ✅ (service logs only draft_id, status, feasibility status)
- [ ] No sensitive content persisted: ✅
- [ ] No user-facing public article upload: ✅
- [ ] No URL scraping: ✅
- [ ] No live LLM call: ✅
- [ ] No LLM direct publish: ✅
- [ ] No stub direct publish: ✅
- [ ] No generated verifier code auto-accepted: ✅ (manual_review_required=True on all stub verifiers)
- [ ] No rejected/partial article publish path: ✅
- [ ] No admin review bypass: ✅
- [ ] No StaticValidator bypass: ✅
- [ ] No K8s-only hardcoding into generic schema: ✅
- [ ] No Linux/multi-domain portability regression: ✅
- [ ] No cloud domain accidentally enabled: ✅
- [ ] No learner catalog generated draft: ✅
- [ ] No customer pilot started: ✅
- [ ] No fifth lab published: ✅
- [ ] No runtime/verifier/terminal behavior change: ✅
- [ ] No production VM/pool/registry modified: ✅
- [ ] No arbitrary Article-to-Lab 已实现 claim: ✅
- [ ] No public launch / production ready claim: ✅
- [ ] "读完即练，结果说话" preserved: ✅
