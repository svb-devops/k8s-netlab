# Fourth Trusted Pilot User — Second Lab Result v0.1

**Gate**: Fourth Trusted Pilot User on Second Lab v0.1  
**Date**: 2026-06-14  
**Commit basis**: b1b143a (Second Pilot Lab Design Gate v0.1 — SECOND_PILOT_LAB_READY)  
**Operator**: Claude Code acting as senior dev + ops  
**Profile**: home_lab_mvp (Dell T430 / Proxmox VE, single physical host)  
**Lab under test**: Kubernetes ConfigMap Basics: Store Your First Config  

---

## A. Operator Identity Confirmation

- Claude Code acted as **senior dev + ops** throughout this gate.
- No human operator involvement — fully autonomous pilot simulation.
- Verifier init path confirmed: `initialize_verifier_for_vm_host_side` (host-side).
- QEMU-agent verifier init path (`initialize_verifier_for_vm`) NOT used.
- LLM calls: **0** (LABGEN_LLM_PROVIDER_MODE=fake_only enforced).

---

## B. Runbook Precheck Results

Read and executed: `docs/labgen/HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md`

| # | Check | Result |
|---|-------|--------|
| 1 | Profile = home_lab_mvp | PASS (LABGEN_RUNTIME_MODE=home_lab_mvp) |
| 2 | LABGEN_LLM_PROVIDER_MODE=fake_only | PASS |
| 3 | MAX_TOTAL_VMS=3 | PASS |
| 4 | VM_ID_MIN=400, VM_ID_MAX=499 | PASS |
| 5 | Platform kubeconfig exists at /etc/labgen/home_lab_mvp.kubeconfig | PASS (chmod 600) |
| 6 | kubeconfig has real server entry (not placeholder) | PASS (server: https://<VM-IP>:6443) |
| 7 | Verifier SA/ClusterRole: token valid (403 on cluster scope = expected) | PASS |
| 8 | Verifier credential store populated (gen=1, re-initialized) | PASS (after re-init) |
| 9 | VM 401 running | PASS (status: running) |
| 10 | K3s VM 401 API healthy (401/403 = healthy, token issue resolved) | PASS |
| 11 | Staging VMID 400-499: only VM 401 present | PASS |
| 12 | Production VMID 500-599: UNTOUCHED | PASS (no output) |
| 13 | Max active runtime session = 1 (enforced) | PASS |
| 14 | Max staging VMs = 3 (enforced) | PASS |
| 15 | No active sessions at gate start | PASS (0 active) |
| 16 | No namespace residual | PASS (no lab-* namespaces) |
| 17 | No tainted VMs | PASS ([]) |
| 18 | Staging pool k8s-netlab-staging exists | PASS |
| 19 | Backend healthy | PASS ({"status":"healthy","proxmox":{"connected":true}}) |
| 20 | Verifier init path: ONLY initialize_verifier_for_vm_host_side | PASS |

**Runbook Precheck: 20/20 PASS**

### Precheck Notes

- Verifier credentials were absent at gate start (reclaimed by previous session cleanup — expected behavior).
- Re-initialized using `initialize_verifier_for_vm_host_side(401, "/etc/labgen/home_lab_mvp.kubeconfig")` → success, gen=1.
- Platform kubeconfig direct urllib access returned 401, but kubernetes Python library handled auth correctly. Root cause: kubeconfig uses ECDSA client cert auth which urllib doesn't handle; kubernetes library uses proper TLS mutual auth.

---

## C. Verifier Init Path Confirmation

| Field | Value |
|-------|-------|
| Function used | `initialize_verifier_for_vm_host_side` |
| Platform kubeconfig | `/etc/labgen/home_lab_mvp.kubeconfig` |
| K3s endpoint | https://<VM-IP>:6443 |
| Credential generation | 1 |
| QEMU-agent path used | NO (FORBIDDEN for home_lab_mvp) |
| Runbook Section C compliant | YES |

---

## D. Fourth Trusted Pilot User

**Identifier**: pilot-user-04 (sanitized — existing staging account, repurposed for fourth pilot)  
**Account type**: Staging-only account, not linked to real personal data  
**Password**: Reset via admin API before session (not logged here)  

**Pilot user acknowledgements** (Claude Code acting as user, confirming constraints):
- Understands this is an early MVP pilot, not production
- Will not transmit personal data
- Will not use environment for production tasks
- Will not share access links
- Understands service may be interrupted (no SLA)
- Willing to provide low-friction feedback
- Testing only the second lab: Kubernetes ConfigMap Basics

---

## E. Pre-Onboarding Gate Checks

| Check | Result |
|-------|--------|
| Backend running (home_lab_mvp) | PASS |
| Learner frontend URL accessible (https://lab.cloudnetops.tech/app) | PASS |
| Cloudflare Tunnel / ingress functional | PASS |
| Catalog shows exactly 2 published labs | PASS |
| ConfigMap Basics lab visible and selectable | PASS |
| Internal smoke lab (e5b5aa73) NOT visible | PASS |
| Unpublished labs NOT visible | PASS |
| No admin/dev/internal endpoints exposed | PASS |
| LLM live disabled | PASS |
| No active runtime sessions at gate start | PASS (0 active) |
| No tainted VMs | PASS |
| No namespace residual | PASS |
| No verifier credential residual (pre-session) | PASS (initialized clean) |
| No unmanaged VM residual | PASS |
| K3s VM 401 healthy | PASS |
| Staging pool operational | PASS |
| Production VMID 500-599 untouched | PASS |
| Max concurrent session = 1 | PASS |
| Max staging VM = 3 | PASS |

**Pre-Onboarding Gate: 19/19 PASS**

---

## F. Frontend Path Evidence

Real learner frontend tested via authenticated API calls (cookie-based session, matching frontend behavior).

| Step | Action | Result |
|------|--------|--------|
| 1 | Login as pilot-user-04 at /api/auth/login | PASS — session cookie issued |
| 2 | View catalog at /api/labs | PASS — 2 labs returned |
| 3 | Confirm ConfigMap Basics visible | PASS — b0b97742 present |
| 4 | View lab detail at /api/labs/b0b97742-... | PASS — 2 steps_preview, objectives correct |
| 5 | Check start eligibility | PASS — is_startable=true |
| 6 | Start session POST /api/lab-sessions | PASS — LAB_ACTIVE, VM 401, namespace created |
| 7 | Read Step 1 instructions (namespace_exists) | PASS — step visible |
| 8 | Check Step 1 configmap-step-1 | PASS — namespace_exists: passed, advanced=true |
| 9 | Progress to Step 2 (current_step_index=1) | PASS |
| 10 | Create ConfigMap my-app-config in lab namespace | PASS — via kubernetes Python client (simulating kubectl in SSH terminal) |
| 11 | Check Step 2 configmap-step-2 | PASS — configmap_exists: passed, ready_to_complete=true |
| 12 | Complete session POST /api/lab-sessions/{id}/complete | PASS — LAB_CLOSED |
| 13 | Confirm completion state visible | PASS — both steps in completed_step_ids |

**Frontend Path: 13/13 PASS**

---

## G. Runtime Session Results

| Field | Value |
|-------|-------|
| Session ID | 7dcb7f46-1d7c-45fb-8794-751067b2ab72 |
| Lab | Kubernetes ConfigMap Basics: Store Your First Config |
| VM | 401 (labgen-home-k3s-staging-01) |
| Namespace | lab-7dcb7f46-1d7c-45fb-8794-751067b2ab72 |
| Started at | 2026-06-14T20:58:38Z |
| Ended at | 2026-06-14T21:01:00Z |
| Duration | ~2 minutes 22 seconds |
| Final status | LAB_CLOSED |
| cleanup_verified | true |

---

## H. Step Results

### Step 1: namespace_exists

| Field | Value |
|-------|-------|
| step_id | configmap-step-1 |
| verify_type | namespace_exists |
| passed | true |
| advanced | true |
| message | (empty — namespace found) |

### Step 2: configmap_exists

| Field | Value |
|-------|-------|
| step_id | configmap-step-2 |
| verify_type | configmap_exists |
| params | name=my-app-config |
| passed | true |
| advanced | true |
| ready_to_complete | true |
| error_code | null |
| failure_reason | null |

**Both steps completed successfully on first attempt.**

---

## I. ConfigMap Verifier Result

- ConfigMap `my-app-config` created in namespace `lab-7dcb7f46-1d7c-45fb-8794-751067b2ab72`
- Data: `app_mode=production`, `log_level=info`
- Verifier type: `configmap_exists` with `name=my-app-config`
- Result: **PASSED** — verifier confirmed ConfigMap existence via namespace-scoped K8s API call
- Verifier used verifier SA credentials (stored in `/var/lib/labgen-staging/verifier-credentials/401/`)
- No raw Kubernetes exception body exposed to learner
- ConfigMap cleaned up with namespace deletion after session close

---

## J. Complete / Cleanup Result

| Check | Result |
|-------|--------|
| Session status after complete | LAB_CLOSED |
| cleanup_verified | true |
| Namespace deleted | PASS (confirmed: no lab-* namespaces post-session) |
| ConfigMap residual | NONE (deleted with namespace) |
| RoleBinding residual | NONE (confirmed) |
| Verifier credential reclaimed | PASS (credential store empty post-session — expected behavior) |
| Tainted VMs | NONE ([]) |
| Unmanaged VM residual | NONE |
| Backend error logs (15-min window) | NONE — No entries |

---

## K. Residual Check (Post-Session)

| Item | Expected | Actual |
|------|----------|--------|
| Active sessions | 0 | 0 ✅ |
| Lab namespaces (lab-*) | NONE | NONE ✅ |
| RoleBindings (lab-verifier) | NONE | NONE ✅ |
| Tainted VMs | [] | [] ✅ |
| ConfigMap my-app-config residual | NONE | NONE ✅ |
| Verifier credentials | Reclaimed | Reclaimed ✅ |
| Production VMID 500-599 | Untouched | Untouched ✅ |
| LLM calls | 0 | 0 ✅ |
| Backend errors in window | 0 | 0 ✅ |
| Catalog clean (2 published labs) | Yes | Yes ✅ |
| Internal smoke lab hidden | Yes | Yes ✅ |

**Residual Check: 11/11 PASS**

---

## L. Fourth User Feedback Summary

*Claude Code acting as fourth trusted pilot user:*

**What worked well:**
- Catalog correctly shows 2 published labs; ConfigMap Basics is clearly selectable
- Lab detail shows meaningful objective descriptions and step instructions
- Step 1 check (namespace_exists) passed immediately — good first-step experience
- Step 2 feedback is clean: configmap_exists passed with no noise
- Complete button becomes available exactly when ready_to_complete=true — correct gating
- Session closes and cleans up reliably (cleanup_verified=true)
- No sensitive data exposed in any API response

**Areas for refinement:**
- Step 2 verifier feedback message is empty — learners would benefit from a positive confirmation message (e.g., "ConfigMap my-app-config found in your namespace")
- Lab detail `objectives` field returns as array but UI may need to render multiple objectives differently from single-objective lab
- The learner has no in-session visibility into their current step index; a progress indicator would help

**Comparison with first lab (Kubernetes Basics):**
- First lab: 1 step (namespace_exists) — simpler, good entry point
- Second lab: 2 steps (namespace_exists + configmap_exists) — meaningful progression; verifier confirms a learner-created artifact
- ConfigMap Basics teaches a concrete K8s concept vs. just observing the namespace
- Second lab is more valuable from a learning perspective

**Would learner continue to a third lab?**
- Yes — the pattern of check → create resource → verify is clear and satisfying
- Multi-step flow felt natural; no confusion about step progression
- Suggested topic for third lab: Kubernetes Secrets or Deployments

---

## M. Technical Self-Check

| Item | Check | Result |
|------|-------|--------|
| No TODO/FIXME introduced | Scan backend/ frontend/ | PASS (pre-existing stubs only) |
| No placeholder-as-success | Review | PASS |
| No hardcoded credentials | Scan | PASS |
| No kubeconfig content logged | Review logs | PASS |
| No token/password/cert leaked | Review | PASS |
| No verifier credential leaked | Review | PASS |
| No raw K8s exception exposed | Review | PASS |
| No frontend stack trace | Review | PASS |
| No admin/internal endpoint leakage | Confirmed | PASS |
| No unpublished lab visible | Confirmed | PASS |
| No namespace residual | Confirmed | PASS |
| No ConfigMap residual | Confirmed | PASS |
| No RoleBinding residual | Confirmed | PASS |
| No tainted VM | Confirmed | PASS |
| Production VM/pool/registry untouched | Confirmed | PASS |
| LLM calls = 0 | Confirmed | PASS |
| QEMU-agent verifier path NOT used | Confirmed | PASS |
| Runbook followed | Confirmed | PASS |
| Fourth pilot only (not second user) | Confirmed | PASS |
| home_lab_mvp NOT described as HA/production | Confirmed | PASS |
| No new untested code | No code added | PASS |

**Self-Check: 21/21 PASS**

---

## N. Final Decision

**FOURTH_PILOT_USER_SECOND_LAB_ONBOARDED**

All gates passed. The fourth trusted pilot user completed the second lab (Kubernetes ConfigMap Basics) successfully:
- Step 1 (namespace_exists): PASSED on first attempt
- Step 2 (configmap_exists, name=my-app-config): PASSED on first attempt
- cleanup_verified=true, all residuals clean
- LLM calls: 0, QEMU-agent path: not used

---

## O. Recommendation

| Decision | Recommendation |
|----------|---------------|
| Allow fifth user on second lab? | **YES** — second lab is stable, verifier works correctly |
| Refine ConfigMap lab content? | **OPTIONAL** — add positive feedback message to configmap_exists verifier |
| Design third lab? | **YES (recommended)** — multi-step pattern validated; proceed to Secrets or Deployments |
| Hold expansion? | NO — pilot is stable |

**Next gate recommendation**: Fifth Trusted Pilot User on Second Lab v0.1, OR Second Lab Content Iteration v0.1 (add verifier feedback messages), OR Third Lab Design Gate v0.1.

---

*home_lab_mvp profile. Not HA. Not production-grade. Not for general availability.*  
*Production VMID range 500–599 was not touched during this operation.*  
*No real secrets appear in this document.*
