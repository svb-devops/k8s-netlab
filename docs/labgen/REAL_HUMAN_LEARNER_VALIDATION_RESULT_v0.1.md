# Real Human Learner Validation v0.1

**Validation date**: 2026-06-15  
**Decision**: REAL_HUMAN_LEARNER_BLOCKED  
**Blocker**: NO_REAL_HUMAN_LEARNER_RECRUITED  
**Operator**: Claude Code acting as senior dev + ops  
**Based on**: Small Cohort Feedback Triage & Product Decision v0.1 — SMALL_COHORT_TRIAGED_NEEDS_ITERATION (commit `b7840e4`)  
**No real secrets in this document.**

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Real learners recruited | 0 |
| Labs attempted | 0 |
| Runtime sessions started | 0 |
| Final decision | **REAL_HUMAN_LEARNER_BLOCKED** |
| Blocker | NO_REAL_HUMAN_LEARNER_RECRUITED |
| Feedback sufficient for product decision | NO — no real human feedback collected |
| LLM calls | 0 |
| Production VMID 500–599 touched | NO |
| API-only simulation used | NO |
| Operator executed steps for learner | NO |

**Why BLOCKED, not attempted**:  
The task requires real human learners who independently operate the learner frontend, with the operator failing closed if this cannot be confirmed. Claude Code is an AI assistant and cannot physically recruit human participants, cannot verify that a person has independently operated a browser, and cannot collect genuine learner self-reports. The task's own constraint applies: "若无法确认真实人类学员独立使用，必须 fail-closed."

No runtime sessions were started. No operator simulation of learner activity was performed.

---

## B. Authenticity Check

| Criterion | Status |
|-----------|--------|
| Learner is not Claude Code | N/A — no learner recruited |
| Operator did not execute steps for learner | PASS — no steps executed |
| API-only simulation not used | PASS — no API calls made on behalf of a learner |
| Learner operated frontend themselves | N/A — no learner |
| Operator observations separated from learner quotes | N/A |
| Feedback Sections 3–10 captured from learner | NOT COLLECTED |

**Authenticity conclusion**: The fail-closed rule was correctly applied. No operator simulation of real human activity was performed.

---

## C. Per-Learner Results

No learners recruited. This section is empty by design — creating placeholder data would violate the NO_PLACEHOLDER_AS_SUCCESS constraint.

---

## D. Product Learning Findings

No data. Cannot infer:

| Dimension | Status |
|-----------|--------|
| Step clarity | UNKNOWN — no human data |
| Concept clarity | UNKNOWN — no human data |
| Verifier feedback clarity | UNKNOWN — no human data |
| Frontend friction | UNKNOWN — no human data |
| Failure/retry comprehension | UNKNOWN — no human data |
| Completion clarity | UNKNOWN — no human data |
| Perceived learning value | UNKNOWN — no human data |
| Willingness to continue | UNKNOWN — no human data |

---

## E. Issue Triage

### BLOCKER

| ID | Dimension | Description | Status |
|----|-----------|-------------|--------|
| RECRUIT-001 | authenticity | No real human learner could be recruited by an AI operator | OPEN — blocks all further validation work |

### HIGH / MEDIUM / LOW / NOTE

None identified in this scope. Platform technical status is PASS (see Section F).

---

## F. Platform Technical Pre-Gate Results (Executed)

The pre-user gate technical checks were completed before applying the fail-closed rule.

| Check | Result |
|-------|--------|
| Backend health (`/api/health`) | PASS — `{"status":"healthy","proxmox":{"connected":true}}` |
| Published labs in data store | PASS — 4 labs confirmed |
| lab-* namespaces on K3s | PASS — 0 (no residuals) |
| RoleBindings in lab-* namespaces | PASS — 0 (no residuals) |
| Deployments in lab-* namespaces | PASS — 0 (no residuals) |
| K3s node ready | PASS — 1/1 |
| All sessions LAB_CLOSED | PASS — 26/26, all cleanup_verified=True |
| Tainted VMs | PASS — 0 |
| Verifier credentials | PASS — reclaimed (no residuals at /var/lib/labgen-staging/verifier-credentials/401/) |
| VM 401 status | PASS — running (labgen-home-k3s-staging-01) |
| /api/labs requires auth | PASS — not public |
| LLM disabled | PASS — no LLM calls in this session |
| Production VMID 500–599 | PASS — untouched |

**Published labs confirmed** (from data/lab_drafts.json):
1. Kubernetes Basics: Your Isolated Lab Environment
2. Kubernetes ConfigMap Basics: Store Your First Config
3. Kubernetes Secret Basics: Protect Your First Configuration
4. Kubernetes Deployment Basics: Run Your First Workload

---

## G. Decision

**REAL_HUMAN_LEARNER_BLOCKED**

Blocker: `NO_REAL_HUMAN_LEARNER_RECRUITED`

Reason: Claude Code (AI) cannot physically recruit human learners, cannot verify independent frontend operation, cannot collect authentic self-reported feedback. The task's own fail-closed rule was applied as designed.

---

## H. Recommendation

**Next step: User-initiated real learner recruitment**

The operator (human user) must recruit 1–2 actual human learners through direct personal contact. Claude Code cannot do this. Once a real learner is confirmed to be available:

1. Operator creates user account (POST /api/admin/users) for the learner
2. Learner independently opens `https://lab.cloudnetops.tech` in their browser
3. Learner logs in, browses catalog, selects lab
4. Learner follows lab instructions and runs `kubectl` commands independently
5. Operator observes without directing; records observations separately from learner comments
6. After each lab: learner fills feedback template Sections 3–10 verbatim
7. Operator performs per-session cleanup check and residual verify
8. After all labs: operator runs feedback triage → decision

**Preconditions (still met)**:
- Platform technical: ready (see Section F)
- 4 published labs: ready
- RBAC: stable
- Cleanup: 100% reliable
- All prior sessions: LAB_CLOSED

**What changes when a real learner is available**:
- No code changes needed
- No infrastructure changes needed
- Only action: run `initialize_verifier_for_vm_host_side(401, "/etc/labgen/home_lab_mvp.kubeconfig")` before each lab session
- Then follow Runbook Section J

**Path after real human validation**:
- If feedback sufficient and labs clear → Small Customer Pilot Preparation Gate
- If UX friction found → Human Learner UX/Content Iteration → re-validate
- If concept gaps found → Fifth Lab Design Gate (add scaffolding)
- If content quality is leading gap → LLM Live Gate Planning

---

## I. Technical Self-Check

| # | Check | Result |
|---|-------|--------|
| 1 | No TODO / FIXME | PASS |
| 2 | No placeholder-as-success | PASS — 0 learners = 0 learners, not simulated |
| 3 | No fabricated real learner feedback | PASS |
| 4 | No operator-executed steps labeled as learner-executed | PASS |
| 5 | No API-only simulation labeled as frontend usage | PASS |
| 6 | No hardcoded credential | PASS |
| 7 | No kubeconfig content logged | PASS |
| 8 | No token/password/cert/private key leaked | PASS |
| 9 | No verifier credential residual | PASS |
| 10 | No Secret value leaked | PASS |
| 11 | No raw Kubernetes exception body leaked | PASS |
| 12 | No raw Deployment/Pod object leaked | PASS |
| 13 | No admin/internal endpoint leaked | PASS |
| 14 | No unpublished lab leaked | PASS |
| 15 | No namespace residual | PASS |
| 16 | No RoleBinding residual | PASS |
| 17 | No Deployment residual | PASS |
| 18 | No tainted VM | PASS |
| 19 | No production VM / pool / registry modified | PASS |
| 20 | LLM call count = 0 | PASS |
| 21 | QEMU-agent verifier init path not used | PASS |
| 22 | No overbroad RBAC | PASS |
| 23 | No get verb regression | PASS |
| 24 | No stale namespaces/endpoints RBAC rules | PASS |
| 25 | No runbook drift | PASS |
| 26 | No real human validation before public launch | PASS — blocked, no launch |
| 27 | home_lab_mvp not treated as HA production | PASS |
| 28 | Customer pilot not started | PASS |
| 29 | No new untested code | PASS — no code changes |
| 30 | Cloud portability not broken | PASS |

---

## J. Modified / Created Files

| File | Change |
|------|--------|
| `docs/labgen/REAL_HUMAN_LEARNER_VALIDATION_RESULT_v0.1.md` | Created (this document) |
| `docs/labgen/SMALL_COHORT_FEEDBACK_TRIAGE_AND_PRODUCT_DECISION_v0.1.md` | Section update (N: Follow-up) |
| `deploy/labgen/staging_ops_ticket_status.md` | Status update |
| `deploy/labgen/staging_infrastructure_checklist.md` | Status update |
| `CHANGELOG.md` | [Unreleased] entry |

---

## K. Test Results

No code changes in this task. Test baseline unchanged.

| Metric | Value |
|--------|-------|
| Tests | 3216 passed (unchanged) |
| Coverage | 93.13% (unchanged) |
| Code changes | 0 |
| Runtime sessions | 0 |
| LLM calls | 0 |
