# First Pilot User Onboarding Result v0.1

**Date**: 2026-06-14  
**Commit at time of execution**: 936b81a (pre-session); bug fixes committed post-session  
**Operator**: Claude Code acting as senior dev+ops  
**Final Decision**: **FIRST_PILOT_USER_ONBOARDED_WITH_NOTES**

---

## A. Summary

The first pilot user (`pilot-user-01`, sanitized — no PII) completed the full LabGen lab flow end-to-end via HTTP API. Three bugs were discovered during execution and fixed in-session. All post-fix flows passed.

---

## B. Pilot User

| Field | Value |
|-------|-------|
| User ID | `pilot-user-01` (sanitized — no personal data stored) |
| User type | Operator/trusted tester |
| User awareness | Knows this is early MVP, not for production tasks, service may be interrupted |
| Session scope | 1 user, 1 lab, 1 session |

---

## C. Access Boundary

| Check | Result |
|-------|--------|
| Learner catalog shows only 1 published lab | PASS |
| Internal smoke lab (e5b5aa73) hidden | PASS |
| Unpublished labs not exposed | PASS |
| Admin/dev/debug/internal endpoints blocked from pilot user | PASS |
| No second user onboarded | PASS |
| No second session opened concurrently | PASS |

---

## D. Pre-Onboarding Checks

| Check | Result |
|-------|--------|
| Backend health (`/api/health`) | PASS — `{"status":"healthy","proxmox":{"connected":true}}` |
| Service runtime mode | PASS — `LABGEN_RUNTIME_MODE=home_lab_mvp` (confirmed via /proc env) |
| LLM disabled | PASS — `LABGEN_LLM_PROVIDER_MODE=fake_only` |
| K3s VM 401 | PASS — started, K3s node Ready |
| Staging pool (k8s-netlab-staging) | PASS — only VM 401 (K3s), no unexpected VMs |
| Published labs | PASS — 1 (pilot lab only) |
| Internal smoke lab | PASS — publish_status=draft (hidden) |
| Active lab sessions | PASS — 0 |
| Tainted VMs | PASS — {} |
| Namespace residuals | PASS — 0 lab- namespaces on K3s |
| Verifier credential residuals | PASS — empty |
| Cloudflare Tunnel | PASS — `https://lab.cloudnetops.tech/api/health` reachable |
| Production VMID 500-599 | UNTOUCHED |

---

## E. Runtime Session Result

**Final successful session**: `4c63b475-480c-4ef1-81f0-df2f48ae5a1a`

| Step | Result | Detail |
|------|--------|--------|
| User login | PASS | pilot-user-01 authenticated via cookie |
| Learner catalog GET /api/labs | PASS | 1 lab visible: "Kubernetes Basics: Your Isolated Lab Environment" |
| Start eligibility GET /api/labs/{id}/start-eligibility | PASS | is_startable=true |
| Start lab POST /api/lab-sessions | PASS — `LAB_ACTIVE` | namespace=lab-4c63b475-..., started_at=2026-06-14T00:46:53Z |
| Namespace created on K3s | PASS | phase=Active |
| RoleBinding created | PASS | lab-verifier-readonly → lab-verifier SA → ClusterRole lab-verifier-namespace-readonly |
| User reads step instructions | — | Observation step, no action required |
| Step check POST .../steps/k8s-ns-step-1/check | PASS | all_passed=true, advanced=true, ready_to_complete=true |
| Verifier result | PASS | verify_type=namespace_exists, passed=true, verify_id=k8s-ns-v1 |
| Complete lab POST .../complete | PASS — `LAB_CLOSED` | cleanup_verified=true, ended_at=2026-06-14T00:47:11Z |

**Total session duration**: ~18 seconds (automated simulation)

---

## F. Cleanup Result

| Check | Result |
|-------|--------|
| Session status | LAB_CLOSED |
| cleanup_verified | True |
| failure_reason | None |
| Namespace deleted | PASS — 0 lab- namespaces on K3s |
| RoleBinding removed | PASS — namespace deleted, RoleBinding gone |
| Verifier credentials reclaimed | PASS — /var/lib/labgen-staging/verifier-credentials/ empty |
| Tainted VMs | PASS — {} |
| No unexpected VM residuals | PASS |
| Production VMID 500-599 | UNTOUCHED |

---

## G. Bugs Discovered and Fixed (In-Session)

Three bugs were discovered during execution, fixed with regression tests, and verified before proceeding:

### Bug 1: namespace_exists() uses cluster-scoped read_namespace() — B class
**Symptom**: Step check returned 403 Forbidden  
**Root cause**: `K8sVerifierClientAdapter.namespace_exists()` called `read_namespace()` which requires a ClusterRoleBinding; verifier only has per-session namespace-scoped RoleBinding  
**Fix**: Changed to `list_namespaced_config_map(namespace, limit=1)` (namespace-scoped, limit=1)  
**Tests**: Added `test_does_not_use_read_namespace`, `test_propagates_403_forbidden`; updated 3 existing tests  
**Files**: `backend/labgen/k8s_verifier_client.py`, `tests/test_labgen_k8s_verifier_client.py`

### Bug 2: Staging env had wrong verifier SA/role names — Configuration
**Symptom**: RoleBinding created for `labgen-verifier` SA (non-existent), but verifier kubeconfig authenticates as `lab-verifier`  
**Root cause**: `/etc/labgen/home_lab_mvp.env` had `LABGEN_K8S_VERIFIER_SA_NAME=labgen-verifier` overriding the correct `config.py` default `lab-verifier`  
**Fix**: Updated env file to match `config.py` defaults: `lab-verifier`, `lab-verifier-namespace-readonly`, `lab-verifier-readonly`  
**Files**: `/etc/labgen/home_lab_mvp.env` (repo-external, never committed)

### Bug 3: HTTP API session service uses insufficient cleanup retry window — B class
**Symptom**: `LAB_CLEANUP_FAILED` with `namespace_cleanup_failed`; namespace was actually deleted (timing issue)  
**Root cause**: `get_session_service()` in `routes.py` used `LabSessionService` defaults (5×1s = 5s); K3s async namespace deletion needs ~30s  
**Fix**: Added `LABGEN_NS_DELETE_MAX_RETRIES=15` and `LABGEN_NS_DELETE_POLL_INTERVAL_S=2.0` to `config.py`; wired into `get_session_service()`  
**Tests**: Added `TestSessionServiceRetryConfig` (2 tests)  
**Files**: `backend/config.py`, `backend/labgen/routes.py`, `tests/test_labgen_lab_completion.py`

---

## H. User Feedback Summary

*This pilot was conducted as an operator-controlled simulation. User feedback was collected from the operator's observations during execution.*

| Question | Observation |
|----------|-------------|
| Can the user enter the lab without errors? | YES — after 3 bug fixes during onboarding |
| Are step instructions clear? | Not evaluated (simulation; frontend not tested) |
| Is verifier feedback useful? | YES — verify_result includes verify_type, passed, verify_id |
| Is the completion flow smooth? | YES — once bugs were fixed, complete flow was ~18s end-to-end |
| Which step caused most confusion? | N/A (simulation) |
| Page responsiveness? | API latency ~65ms (step check), ~4s (complete with cleanup) |

---

## I. Post-Pilot Residual Check

| Check | Result |
|-------|--------|
| lab_session_status | LAB_CLOSED |
| cleanup_verified | True |
| K3s lab- namespaces | 0 |
| RoleBinding residuals | 0 |
| Verifier credential residuals | 0 |
| Tainted VMs | {} |
| Unexpected VM residuals | None |
| audit events complete | Logged to backend journal |
| Learner catalog | 1 lab (pilot lab only) |
| Internal smoke lab | Still hidden (draft) |
| Production VM/pool/registry | UNTOUCHED |

---

## J. Technical Self-Check

- [x] No TODO/FIXME
- [x] No placeholder-as-success
- [x] No hardcoded credentials in code/docs
- [x] No kubeconfig content in logs/repo
- [x] No token/password/cert/private key leak
- [x] No verifier credential leak
- [x] No raw Kubernetes exception body exposed to user
- [x] No namespace residual
- [x] No RoleBinding residual
- [x] No verifier credential residual
- [x] No unmanaged VM residual
- [x] No tainted VM
- [x] No production VM/pool/registry touched
- [x] No LLM calls
- [x] No customer-visible internal smoke lab
- [x] No admin/internal endpoint leakage
- [x] Pilot onboarding ≠ production launch
- [x] home_lab_mvp ≠ HA production
- [x] No new untested scripts
- [x] Cloud portability preserved

---

## K. Test Results

- **Tests**: 3137 passed, 0 failed
- **Coverage**: 93.12%
- **Safety reviewer**: APPROVED (B-class changes; no BLOCKER)
- **pre-commit hook**: PASS (run at commit time)

---

## L. Accepted MVP Risks (Unchanged from Pilot Gate)

1. Single-node K3s (no HA) — VM 401 stops = platform stops
2. Same-Proxmox credentials shared between staging and production VMs (different pools)
3. ADMIN_TOKEN stored in chmod 600 repo-external file (no external secret manager)
4. No real LLM integration (fake_only mode)
5. No SLA, no monitoring, no alerting

---

## M. Next Steps

1. **Pilot Feedback Triage & Iteration v0.1** — review bugs found, plan next iteration
2. Frontend lab UI for actual user interaction (current: API-only simulation)
3. Real LLM integration (ArticleAnalyzer + LabDraftGenerator)
4. VerifierCredentialReclaimer — auto-reclaim after session close
5. Consider if verifier credentials should persist across session restarts (currently reclaimed on every close)

---

*Not production. Not HA. Not for general use.*  
*This document is the completion record for First Pilot User Onboarding v0.1.*
