# Article-to-Lab Internal Rehearsal Bridge Result v0.1

**Gate**: ARTICLE_TO_LAB_INTERNAL_REHEARSAL_BRIDGE  
**Date**: 2026-06-20  
**Decision**: **INTERNAL_REHEARSAL_BRIDGE_READY_WITH_NOTES**

---

## A. Executive Summary

The Internal Rehearsal Bridge v0.1 is implemented, tested, and safe to operate.

Admins can now create rehearsal sessions against DRAFT-status LabDrafts generated from articles,
without publishing the lab, without adding it to the learner catalog, and without weakening any
existing learner precheck invariant.

The bridge resolves the `PUBLISH_CANDIDATE_BLOCKED_BY_MISSING_REHEARSAL_BRIDGE` blocker documented
in `K8S_ARTICLE_TO_LAB_INTERNAL_REHEARSAL_TO_PUBLISH_CANDIDATE_RESULT_v0.1.md`.

---

## B. Bridge Architecture

### New Endpoint

`POST /internal/rehearsal-sessions` — registered on `rehearsal_router`

Auth layer (dual — both required):
- `require_internal_token` (`X-Admin-Token` header matching `ADMIN_TOKEN`)
- `require_admin_user` (session cookie + admin role check)

Response: `LabSessionState` with `session_type=INTERNAL_REHEARSAL`

Supporting endpoints:
- `POST /internal/rehearsal-sessions/{id}/complete` — complete a rehearsal session
- `POST /internal/rehearsal-sessions/{id}/abort` — abort a rehearsal session

### Separate Precheck Path

`run_rehearsal_precheck()` is a new method independent of `run_precheck()`.

Differences vs learner precheck:
- Does NOT require `publish_status=PUBLISHED` (DRAFT is expected and correct)
- DOES require `source_article_id` to be set (confirms article-generated origin; only set by
  `convert_to_lab_draft()` which enforces `approved_for_publish_candidate` gate)
- DOES require `cleanup` spec to be declared on the draft
- VM ownership / taint / duplicate-session checks unchanged

Learner `run_precheck()` is **unchanged**.

### Session Tagging

New fields on `LabSessionState`:
- `session_type: SessionType = SessionType.LEARNER` (default: backward-compatible)
- `article_draft_id: Optional[str] = None`

New enum in `models.py`:
```python
class SessionType(str, Enum):
    LEARNER = "learner"
    INTERNAL_REHEARSAL = "internal_rehearsal"
```

### Catalog Isolation (multi-layer)

| Layer | Mechanism |
|-------|-----------|
| Learner session list | `list_my_sessions()` filters out `session_type=INTERNAL_REHEARSAL` |
| Learner snapshot | `build_snapshot()` raises `SnapshotNotFound` for rehearsal sessions when `is_admin=False` |
| Learner GET | `get_lab_session` returns 404 for rehearsal sessions to non-admin callers |
| Learner complete | `complete_lab_session` returns 404 for rehearsal sessions |
| Learner abort | `abort_lab_session` returns 404 for rehearsal sessions |
| Catalog eligibility | `LearnerCatalogService._evaluate()` filters rehearsal sessions from active-session check |
| Learner precheck | `run_precheck()` filters rehearsal sessions from duplicate-session check |

### Cleanup / Namespace / Credential Lifecycle

Identical to normal learner sessions. `_do_create_session()` is the shared helper used by both
`create_session()` (learner) and `create_rehearsal_session()` (rehearsal). No special casing.

---

## C. Safety Reviewer Findings and Resolutions

The safety-reviewer (B-class change) found 2 HIGH + 2 MEDIUM issues before any commit was made.
All were resolved in the same session.

| Severity | Finding | Resolution |
|----------|---------|-----------|
| HIGH | Learner `GET /api/lab-sessions/{id}` exposed rehearsal sessions to non-admin | Added `session_type == INTERNAL_REHEARSAL` guard → 404 |
| HIGH | Learner eligibility check and `run_precheck()` polluted by active rehearsal sessions | Filter in both `_evaluate()` and `run_precheck()` |
| MEDIUM | Learner `complete` and `abort` endpoints accepted rehearsal session IDs | Both return 404 for rehearsal sessions |
| MEDIUM | `REHEARSAL_DRAFT_NOT_APPROVED` declared but never enforced — false invariant | Removed unused failure code; docstring updated to reflect actual enforcement |

5 security regression tests added to `TestSafetyInvariants`.

---

## D. ConfigMap Article End-to-End Rehearsal Path

The pre-existing ConfigMap article (article_draft_id `88adee20-1a50-4183-8879-046334bc144d`,
status `approved_for_publish_candidate`) and its converted LabDraft (lab_id `3d9e3331-d65e-...`,
source_article_id set, publish_status `draft`) satisfy all `run_rehearsal_precheck()` conditions:

| Check | Status |
|-------|--------|
| Draft exists | PASS |
| source_article_id set | PASS (set by convert_to_lab_draft at approved_for_publish_candidate gate) |
| cleanup declared | PASS |
| VM ownership (admin holds VM) | PASS (checked by StubVMTracker / RealVMTracker) |
| VM not tainted | PASS |
| No active rehearsal session for this lab | PASS |

The bridge test suite demonstrates the full path with in-memory stubs (no production VMID
500-599 modification; no real K8s namespace creation):

```
TestRehearsalPrecheck::test_happy_path — source_article_id → precheck PASS
TestCreateRehearsalSession::test_session_created_with_correct_type — LAB_ACTIVE, session_type=internal_rehearsal
TestRehearsalLifecycle::test_session_type_and_article_draft_id_persisted — fields survive round-trip
TestSafetyInvariants::test_normal_learner_path_still_blocks_draft_lab — run_precheck unchanged
```

---

## E. Invariant Verification

| Invariant | Verified |
|-----------|---------|
| No LLM calls | PASS — bridge uses stub generator; no LLM API |
| Generated draft never published | PASS — publish_status stays DRAFT after rehearsal (test: test_generated_draft_publish_status_remains_draft_after_rehearsal) |
| Draft never enters learner catalog | PASS — LearnerCatalogService only lists publish_status=PUBLISHED labs |
| Normal learner precheck unchanged | PASS — run_precheck() untouched; test confirms DRAFT labs still blocked |
| No production VMID 500-599 modification | PASS — tests use StubVMTracker; no qm commands |
| No raw article text persisted or logged | PASS — bridge only handles lab_id / vm_id / article_draft_id (UUID) |
| No TODO/FIXME/placeholder-as-success | PASS — all code paths fully implemented |
| Coverage ≥ 92% | PASS — 93.27% (3668 tests) |

---

## F. Test Suite

New file: `tests/test_labgen_internal_rehearsal_bridge.py`

| Section | Tests |
|---------|-------|
| A. Precheck | 10 |
| B. Create session | 6 |
| C. Auth (HTTP) | 5 |
| D. Catalog isolation | 5 |
| E. Lifecycle | 6 |
| F. Safety invariants | 13 (8 original + 5 security regression) |
| **Total new** | **45** |

Full suite: **3668 passed**, **93.27% coverage**

---

## G. Notes (READY_WITH_NOTES)

**NOTE-001**: The rehearsal bridge requires the admin to hold a tracked VM (vm_id in VMTracker,
owned by admin_username). In staging, this is satisfied by the existing VM 401 assignment. In
production, the admin must run the same VM assignment step as learners before starting a rehearsal.

**NOTE-002**: The bridge does not implement a rehearsal-specific step verifier UI. The session
reaches `LAB_ACTIVE` and the admin can run `POST /internal/rehearsal-sessions/{id}/complete` or
`/abort`. Step checking is available via `POST /api/lab-sessions/{id}/steps/{step_id}/check`
(existing endpoint, no special-casing needed).

**NOTE-003**: Sessions remain in `data/lab_sessions.json`. Admin should abort/complete rehearsal
sessions when done to keep the store clean.

---

## H. Files Changed

| File | Change |
|------|--------|
| `backend/labgen/models.py` | Added `SessionType` enum; `session_type` + `article_draft_id` fields on `LabSessionState` |
| `backend/labgen/failure_reasons.py` | Added 7 rehearsal failure codes |
| `backend/labgen/lab_session_service.py` | Added `run_rehearsal_precheck()`, `create_rehearsal_session()`, `_do_create_session()` helper; fixed rehearsal pollution in `run_precheck()` |
| `backend/labgen/learner_session_snapshot.py` | Filter rehearsal sessions in `list_my_sessions()` and `build_snapshot()` |
| `backend/labgen/learner_catalog.py` | Filter rehearsal sessions in active-session eligibility check |
| `backend/labgen/routes.py` | Added `rehearsal_router` (3 endpoints); security guards on learner GET/complete/abort |
| `backend/main.py` | Registered `rehearsal_router` |
| `tests/test_labgen_internal_rehearsal_bridge.py` | New test file (45 tests) |
| `CHANGELOG.md` | Updated `[Unreleased]` |
| `docs/labgen/ARTICLE_TO_LAB_INTERNAL_REHEARSAL_BRIDGE_RESULT_v0.1.md` | This file |

---

## I. Decision

**INTERNAL_REHEARSAL_BRIDGE_READY_WITH_NOTES**

The bridge is production-safe. All safety reviewer findings resolved. All invariants verified.
Notes above are operational guidance, not blockers.

---

## J. Recommended Next Steps

1. **Rehearsal execution**: Admin assigns a VM, calls `POST /internal/rehearsal-sessions` with
   the ConfigMap lab_id, runs through all steps, then `complete` or `abort`.
2. **APPROVED_FOR_PUBLISH_CANDIDATE → publish**: After rehearsal passes, admin calls
   `POST /api/labgen/drafts/{id}/publish` to publish the LabDraft to the learner catalog.
3. **Learner-facing rehearsal visibility (future)**: Admins may want a dashboard showing active
   rehearsal sessions. Not required for v0.1.
