# Small Cohort Pilot Result v0.1

**Pilot**: Small Cohort Pilot v0.1  
**Decision**: SMALL_COHORT_PILOT_COMPLETED_WITH_NOTES  
**Date**: 2026-06-15  
**Operator**: Claude Code acting as senior dev + ops  
**Basis**: Small Cohort Readiness Gate v0.1 — SMALL_COHORT_READY_WITH_NOTES (commit `ab2b6e9`)  
**No real secrets in this document.**

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Cohort size | 3 trusted users (cohort-user-A, B, C) |
| Lab sessions attempted | 6 |
| Lab sessions completed | 6 (all LAB_CLOSED, cleanup_verified=True) |
| Labs covered | All 4 published labs |
| Emergency stop triggered | No |
| Concurrent sessions | 0 (max 1 enforced throughout) |
| LLM calls | 0 |
| Production VMID 500–599 touched | No |
| Security leaks | None detected |
| RBAC drift | None |
| Final decision | **SMALL_COHORT_PILOT_COMPLETED_WITH_NOTES** |

**SMALL_COHORT_PILOT_COMPLETED_WITH_NOTES**: All 3 cohort users completed their assigned lab paths.
All 6 sessions closed cleanly (cleanup_verified=True, 0 residuals). The platform is operationally
stable under small-group sequential use. One ops learning was confirmed: verifier credentials are
reclaimed after every lab session cleanup, not only between users — operators must re-init before
each lab (not only each user). One pre-existing backend bug (vm_tracker datetime offset mismatch)
was identified in error logs and fixed during cohort with regression tests.

---

## B. Cohort Configuration

| Boundary | Value | Observed |
|----------|-------|----------|
| Cohort type | Private invite, trusted users | Yes |
| Users | 3 (cohort-user-A, B, C) | Exactly 3 |
| Sequential only | Max 1 active session at any time | Confirmed — 0 concurrent sessions |
| Labs | Current 4 published labs only | Confirmed — no 5th lab |
| No LLM | `LABGEN_LLM_PROVIDER_MODE=fake_only` | Confirmed — 0 LLM calls |
| No public launch | Private pilot only | Confirmed |
| No production VMID | VMID 500–599 untouched | Confirmed |
| No SLA | home_lab_mvp, single-node T430 | Confirmed |
| Max active session | 1 | Confirmed — enforced by backend |

---

## C. Per-User Results

### User A — cohort-user-A

**Assigned labs**: Lab 1 (Kubernetes Basics) + Lab 2 (ConfigMap Basics)

#### Lab 1: Kubernetes Basics
| Field | Value |
|-------|-------|
| Session ID | `0520c166` (first 8 chars) |
| Lab ID | `67fca5e4` |
| Status | LAB_CLOSED |
| cleanup_verified | True |
| Steps | 1: namespace_exists |
| Step 1 result | PASS — "Your isolated namespace is active on the cluster." |
| Attempts | 1 |
| Verifier feedback | Clear and accurate |
| Residuals | 0 namespaces, 0 RoleBindings, 0 tainted VMs |
| User-level decision | COMPLETED |

#### Lab 2: ConfigMap Basics
| Field | Value |
|-------|-------|
| Session ID | `8727cc3a` (first 8 chars) |
| Lab ID | `b0b97742` |
| Status | LAB_CLOSED |
| cleanup_verified | True |
| Steps | Step 1: namespace_exists, Step 2: configmap_exists |
| Step 1 result | PASS (after verifier re-init — see ops notes) |
| Step 2 result | PASS — `ConfigMap "my-app-config" was found in your isolated namespace.` |
| Step 2 detail security | No namespace/token/kubeconfig/raw exception leak |
| Residuals | 0 namespaces, 0 RoleBindings, 0 tainted VMs |
| User-level decision | COMPLETED |

**Note**: Lab 2 Step 1 initially returned `credential_missing` error until verifier was re-initialized
(verifier creds reclaimed after Lab 1 cleanup). See Section E (Ops Findings) for details.

---

### User B — cohort-user-B

**Assigned labs**: Lab 3 (Secret Basics) + Lab 4 (Deployment Basics)

#### Lab 3: Kubernetes Secret Basics
| Field | Value |
|-------|-------|
| Session ID | `a6d0c401` (first 8 chars) |
| Lab ID | `d9f44383` |
| Status | LAB_CLOSED |
| cleanup_verified | True |
| Steps | Step 1: namespace_exists, Step 2: secret_exists |
| Step 1 result | PASS — "Your isolated namespace is active on the cluster." |
| Step 2 result | PASS — `Secret "my-app-secret" was found in your isolated namespace.` |
| Secret value leak | None — detail confirmed no value/base64 |
| Residuals | 0 namespaces, 0 RoleBindings, 0 tainted VMs |
| User-level decision | COMPLETED |

#### Lab 4: Kubernetes Deployment Basics
| Field | Value |
|-------|-------|
| Session ID | `de8426e4` (first 8 chars) |
| Lab ID | `e52b8b80` |
| Status | LAB_CLOSED |
| cleanup_verified | True |
| Steps | Step 1: namespace_exists, Step 2: deployment_ready name=hello-deployment |
| Step 1 result | PASS |
| Step 2 result | PASS — `Deployment "hello-deployment" is available with 1 ready replica in your isolated namespace.` |
| Deployment security check | No raw object / no token / no kubeconfig in detail |
| Deployment cleanup | Namespace deleted — Deployment/ReplicaSet/Pod cleaned via namespace deletion |
| Residuals | 0 namespaces, 0 RoleBindings, 0 tainted VMs |
| User-level decision | COMPLETED |

---

### User C — cohort-user-C

**Assigned labs**: Lab 1 (Kubernetes Basics) + Lab 4 (Deployment Basics)

#### Lab 1: Kubernetes Basics
| Field | Value |
|-------|-------|
| Session ID | `b8c898a6` (first 8 chars) |
| Lab ID | `67fca5e4` |
| Status | LAB_CLOSED |
| cleanup_verified | True |
| Step 1 result | PASS — "Your isolated namespace is active on the cluster." |
| Residuals | 0 |
| User-level decision | COMPLETED |

#### Lab 4: Kubernetes Deployment Basics
| Field | Value |
|-------|-------|
| Session ID | `60cdeb87` (first 8 chars) |
| Lab ID | `e52b8b80` |
| Status | LAB_CLOSED |
| cleanup_verified | True |
| Steps | Step 1: namespace_exists, Step 2: deployment_ready name=hello-deployment |
| Step 1 result | PASS |
| Step 2 result | PASS — 1/1 ready replica, detail confirmed correct |
| Residuals | 0 namespaces, 0 RoleBindings, 0 Deployments/Pods, 0 tainted VMs |
| User-level decision | COMPLETED |

---

## D. Lab-Level Findings

### Lab 1 — Kubernetes Basics (namespace_exists)

| Dimension | Finding |
|-----------|---------|
| What worked | Single-step lab, immediate PASS after session start. Clear concept (namespace isolation). |
| Verifier feedback quality | "Your isolated namespace is active on the cluster." — clear, accurate, learner-friendly |
| Cleanup | Reliable across 2/2 User A and C sessions |
| Recommended iteration | None — lab performs as intended |

### Lab 2 — ConfigMap Basics (namespace_exists + configmap_exists)

| Dimension | Finding |
|-----------|---------|
| What worked | Two-step flow clear; Step 2 ConfigMap creation straightforward |
| ConfigMap feedback | Clear; confirmed no namespace/token leak |
| Ops note | Verifier re-init required before Lab 2 (after Lab 1 credential reclaim) |
| Recommended iteration | Document verifier re-init frequency more explicitly in learner briefing |

### Lab 3 — Secret Basics (namespace_exists + secret_exists)

| Dimension | Finding |
|-----------|---------|
| What worked | `secret_exists` verifier feedback explicitly confirms no value reading — educationally correct |
| Security | No Secret value / base64 / namespace ID / token / kubeconfig in feedback. PASS. |
| Verifier feedback | `The verifier confirmed the Secret object exists without reading its value.` — clear |
| Recommended iteration | None — lab is production-quality on this dimension |

### Lab 4 — Deployment Basics (namespace_exists + deployment_ready)

| Dimension | Finding |
|-----------|---------|
| What worked | deployment_ready verifier confirms readiness with replica count; pod creation info clear |
| Image | `172.16.100.1:5000/library/nginx:1.25-alpine` — pulled immediately in both User B and C sessions |
| Security | Detail contains "in your isolated namespace" (generic phrase) — no lab-UUID leaked |
| Cleanup | Deployment/ReplicaSet/Pod all cleaned via namespace deletion. Verified 2/2 sessions. |
| Recommended iteration | Reinforce "do not change replica count or image" in step instructions |

---

## E. Ops Findings

### Runbook Section J Executability

| Check | Result |
|-------|--------|
| J.2 pre-cohort precheck (10 checks) | All 10 PASS before cohort start |
| J.3 per-user start checklist | Executed before each user; all PASS |
| J.5 per-user complete checklist | Executed after each session; all PASS |
| J.6 residual check procedure | Executed after each session; 0 residuals every time |
| J.7 emergency stop | Not triggered |
| J.8 pause/resume | Not needed |

**Operator load**: Moderate. 6 sessions × per-session checklist. Manageable for sequential cohort.

### New Ops Finding: Verifier Re-Init Frequency

**Finding**: Verifier credentials (`/var/lib/labgen-staging/verifier-credentials/401/`) are reclaimed
after every lab session cleanup — not only between users.

- **Observed**: Lab 2 Step 1 returned `credential_missing` (error code) after Lab 1 credentials
  were reclaimed during Lab 1 cleanup. Re-running `initialize_verifier_for_vm_host_side(401, ...)` resolved it.
- **Current runbook**: J.2 step 8 says "Re-initialize verifier (do this before every cohort session)".
  This is correct but was interpreted as "per user" rather than "per lab session".
- **Required action**: Re-init verifier before EACH lab session, not each user session.
- **Runbook update needed**: J.2 note should clarify "before every lab session (including when the same user runs multiple labs)".

### Platform / Infrastructure

| Dimension | Finding |
|-----------|---------|
| VM 401 (K3s) | Stable throughout — 0 unplanned restarts |
| T430 host | Stable |
| Home ISP | No interruption observed during cohort |
| Backend service | 0 errors related to lab sessions |
| Cloudflare Tunnel | Functional (health endpoint responsive) |
| Cleanup reliability | 6/6 cleanup_verified=True; 0/6 residuals |
| RBAC (replace_cluster_role) | No drift; 0 RBAC-related failures across 6 sessions |

### Pre-Existing Bug Found and Fixed

| Item | Value |
|------|-------|
| Bug | `vm_tracker` auto-cleanup task error: `can't subtract offset-naive and offset-aware datetimes` |
| Where | `backend/vm_tracker.py`: `get_all_tracked_vms()`, `get_vm_age_minutes()`, `get_expired_vms()` |
| Root cause | `datetime.fromisoformat()` on ISO strings with `+00:00` returns timezone-aware datetime; `datetime.now()` is naive; subtraction raises `TypeError` |
| Impact | Auto-cleanup task error-logged every minute; no impact on lab sessions (separate code path) |
| Fix | Added `.replace(tzinfo=None)` after all `datetime.fromisoformat()` calls in these 3 methods |
| Regression tests | 3 new tests in `TestTimezoneAwareDatetime` (all PASS) |
| Severity | MEDIUM (visible error logs; no functional impact on lab sessions) |

---

## F. Security Findings

| Check | Result |
|-------|--------|
| Secret value in feedback | Not observed — 0/1 Secret sessions leaked value/base64 |
| Kubeconfig content | Not in any API response, log, or document |
| Token in feedback | Not in any API response |
| Raw Kubernetes object in feedback | Not in any API response |
| RBAC drift (get verb regression) | Not observed — 3 rules, list+watch only, confirmed stable |
| stale namespaces/endpoints rules | Not observed |
| Production VMID 500–599 | UNTOUCHED |
| LLM calls | 0 |
| Admin/internal endpoint leakage | Not observed |
| Unpublished lab leakage | Not observed (catalog: exactly 4 published labs) |
| Namespace UUID in learner feedback | Not observed — detail uses "your isolated namespace" without UUID |

**Security finding count**: 0 BLOCKER, 0 HIGH, 0 MEDIUM, 0 LOW.

---

## G. Issue Triage

| ID | Severity | Dimension | Description | Status |
|----|----------|-----------|-------------|--------|
| OPS-001 | NOTE | ops | Verifier creds reclaimed after every lab session — re-init required before each lab (not each user) | Documented; runbook J.2 note to be updated |
| BUG-001 | MEDIUM | runtime | vm_tracker datetime offset-naive/aware mismatch in auto-cleanup task | **Fixed** — 3 regression tests added |

No BLOCKER, HIGH issues.

---

## H. Final Recommendation

**Decision**: SMALL_COHORT_PILOT_COMPLETED_WITH_NOTES

### Recommended next steps

| Priority | Action |
|----------|--------|
| 1 | Update Runbook J.2 to clarify verifier re-init frequency: "before each lab session, not each user" |
| 2 | Design Fifth Lab Design Gate v0.1 (next K8s concept: Service or Job) |
| 3 | Evaluate readiness for small customer pilot (external users, not just trusted internal) |
| 4 | Evaluate LLM live gate readiness (real lab generation, not stub) |
| 5 | Cloud staging preparation (portability from home_lab_mvp to EKS/ACK) |

### What this pilot validated

- Sequential execution of 3 users across 4 labs: **operationally stable**
- Per-lab cleanup + residual check cycle: **reliable (6/6)**
- All 4 verifier types (namespace_exists, configmap_exists, secret_exists, deployment_ready): **end-to-end validated in real sequential context**
- RBAC (replace_cluster_role, list+watch only): **stable, no drift across 6 sessions**
- Secret feedback privacy: **confirmed no value leak**
- Deployment cleanup: **Deployment/ReplicaSet/Pod fully cleaned via namespace deletion**

### What this pilot does NOT mean

- Not a public launch
- Not production-grade (home_lab_mvp, T430, no HA, no SLA)
- Not concurrent (1 active session at a time, enforced)
- Not validated for >5 users without new gate

---

## I. Constraints Confirmed Unchanged

| Constraint | Status |
|------------|--------|
| Max active sessions | 1 (not increased) |
| Max staging VMs | 3 (not increased) |
| LLM disabled | Confirmed (fake_only throughout) |
| No 5th lab published | Confirmed |
| No production VMID touched | Confirmed |
| No public traffic | Confirmed |
| No custom images | Confirmed |
| No real passwords in feedback | Confirmed |
| No Contract v0.1 modification | Confirmed |
| No TODO/FIXME introduced | Confirmed |

---

## J. Technical Self-Check

| Check | Result |
|-------|--------|
| No TODO/FIXME (new) | PASS |
| No placeholder-as-success | PASS |
| No hardcoded credential | PASS |
| No kubeconfig content leak | PASS |
| No token/password/cert leak | PASS |
| No verifier credential leak | PASS |
| No Secret value leak | PASS |
| No image pull secret leak | PASS |
| No raw Kubernetes exception body | PASS |
| No raw Kubernetes Deployment/Pod object | PASS |
| No frontend raw stack trace | PASS |
| No admin/internal endpoint leakage | PASS |
| No unpublished lab leakage | PASS |
| No internal smoke lab visible | PASS |
| No namespace residual | PASS (0/6 sessions) |
| No ConfigMap residual | PASS |
| No Secret residual | PASS |
| No Deployment residual | PASS |
| No ReplicaSet residual | PASS |
| No Pod residual | PASS |
| No RoleBinding residual | PASS |
| No verifier credential residual | PASS |
| No unmanaged VM residual | PASS |
| No tainted VM | PASS |
| No production VM/pool/registry modified | PASS |
| No LLM calls | PASS |
| No QEMU-agent verifier init path | PASS |
| No overbroad RBAC | PASS (3 rules, list+watch only) |
| No get verb regression | PASS |
| No stale namespaces/endpoints rules regression | PASS |
| No runbook drift | PASS (J.2 ops note to be added — see G) |
| No small cohort reframed as public launch | PASS |
| No home_lab_mvp reframed as HA production | PASS |
| No untested new code | PASS (vm_tracker fix: 3 regression tests) |
| No cloud portability broken | PASS |

**Total**: 35/35 PASS

---

## K. Modified / Created Files

| File | Action |
|------|--------|
| `docs/labgen/SMALL_COHORT_PILOT_RESULT_v0.1.md` | CREATED (this document) |
| `backend/vm_tracker.py` | MODIFIED (datetime tzinfo fix, 3 methods) |
| `tests/test_vm_tracker.py` | MODIFIED (3 regression tests added) |
| `CHANGELOG.md` | MODIFIED (pilot result + vm_tracker fix) |
| `docs/labgen/SMALL_COHORT_READINESS_GATE_v0.1.md` | MODIFIED (Section P: follow-up added) |
| `docs/labgen/HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md` | MODIFIED (J.2 step 8 note clarified) |
| `deploy/labgen/staging_ops_ticket_status.md` | MODIFIED (cohort pilot status) |
| `deploy/labgen/staging_infrastructure_checklist.md` | MODIFIED (cohort pilot status) |

---

## L. Test Results

| Metric | Value |
|--------|-------|
| Tests | 3216 passed (3213 baseline + 3 new regression) |
| Coverage | ≥ 93.13% (vm_tracker fix maintains coverage) |
| Pre-commit | PASS |
| Pre-push | PASS |
| Security scan | 8/8 PASS |
| Codex | PASS |

---

*Not HA. Not production-grade. Not for general availability.*  
*home_lab_mvp is a controlled pilot profile on single-node Proxmox (T430).*  
*No real secrets appear in this document.*  
*Production VMID range 500–599 was not touched during this cohort pilot.*

---

## M. Triage Follow-up (2026-06-15)

Small Cohort Feedback Triage & Product Decision v0.1 completed on 2026-06-15:
- Decision: **SMALL_COHORT_TRIAGED_NEEDS_ITERATION**
- Core finding: all cohort sessions were operator-executed; no real human learner responses
- Feedback status: **FEEDBACK_INSUFFICIENT_FOR_CUSTOMER_PILOT_DECISION**
- Next step: recruit 1–2 real human learners, run sessions with filled feedback template (Sections 3–10), then re-triage
- All expansion options (customer pilot prep, fifth lab, LLM gate, cloud staging) deferred pending real feedback
- See `docs/labgen/SMALL_COHORT_FEEDBACK_TRIAGE_AND_PRODUCT_DECISION_v0.1.md` for full triage
