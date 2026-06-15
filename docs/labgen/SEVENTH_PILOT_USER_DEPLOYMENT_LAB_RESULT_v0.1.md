# Seventh Trusted Pilot User on Deployment Lab v0.1 — Result Artifact

**Gate**: Seventh Trusted Pilot User on Deployment Lab v0.1  
**Decision**: SEVENTH_PILOT_USER_DEPLOYMENT_LAB_ONBOARDED  
**Date**: 2026-06-15  
**Operator**: Claude Code acting as senior dev + ops  
**Commit**: (see Section T)

---

## A. Seventh Pilot User

**Identifier**: pilot-user-07 (sanitized; no real name or contact info recorded)  
**Profile**: Seventh trusted controlled pilot user. Briefed that this is an early MVP pilot,
no SLA, service may interrupt, dummy values only, no real secrets or tokens.  
**Lab selected**: Kubernetes Deployment Basics: Run Your First Workload (`e52b8b80`)  
**Testing focus**: Real learner frontend path for the Deployment lab — Deployment creation,
deployment_ready verifier, RBAC correctness for apps/deployments, cleanup stability.

No personal or business-sensitive data recorded. No cookie, token, or password recorded.

---

## B. Ops Runbook Precheck

Profile: `home_lab_mvp` — PASS (with RBAC drift finding — see Section D)

| Check | Result |
|-------|--------|
| Profile: home_lab_mvp | PASS |
| Verifier init path: `initialize_verifier_for_vm_host_side` | PASS — re-initialized, success=True, gen=1 |
| Platform kubeconfig: /etc/labgen/home_lab_mvp.kubeconfig | PASS — exists, chmod 600 |
| QEMU-agent path: not used | PASS |
| K3s VM 401 status | PASS — running |
| K3s node Ready | PASS — labgen-home-k3s-staging-01 Ready |
| No lab namespaces before session | PASS — NONE |
| No active lab sessions before session | PASS — 0 active |
| No tainted VMs | PASS — [] |
| ClusterRole verbs before init | FAIL (drift) — get verb present, namespaces/endpoints present |
| ClusterRole verbs after fix | PASS — list+watch only on all resources |
| Verifier credential store | PASS — kubeconfig.yaml present, gen=1 |
| Staging VMs: ≤3 | PASS — 1 staging VM (401) |
| Production VMID 500-599: untouched | PASS — no VMs in range |
| Max active runtime session: 1 | PASS — 0 active before session |
| LLM disabled | PASS — LABGEN_LLM_PROVIDER_MODE=fake_only |
| No Deployment residual | PASS — no lab namespaces |
| No namespace residual | PASS — NONE |
| No verifier credential residual | PASS — freshly initialized |
| Backend health | PASS — {"status":"healthy"} |

**RBAC drift detected at precheck**: ClusterRole `lab-verifier-namespace-readonly` on K3s still
had stale rules from the original create+409-skip initialization pattern (which never updated
live rules on re-init). This gate triggered a code fix and re-initialization. See Section D.

Runbook precheck: **ALL PASS after RBAC fix — proceed with onboarding**

---

## C. Verifier Initialization Confirmation

```
initialize_verifier_for_vm_host_side(401, "/etc/labgen/home_lab_mvp.kubeconfig")
→ success: True
→ generation: 1
```

- **host-side path used**: YES — `initialize_verifier_for_vm_host_side` ✓
- **QEMU-agent path used**: NO ✓
- **Platform kubeconfig**: `/etc/labgen/home_lab_mvp.kubeconfig` (not logged, not committed)
- **Credential store**: `/var/lib/labgen-staging/verifier-credentials/401/kubeconfig.yaml` present
- **VM ownership**: VM 401 reassigned from pilot-user-06 to pilot-user-07 via VMTracker

---

## D. RBAC Drift — Root Cause and Fix

### Drift discovered at precheck

ClusterRole `lab-verifier-namespace-readonly` live state on K3s before fix:

| Rule | Resources | Verbs |
|------|-----------|-------|
| Core | namespaces, pods, services, configmaps, **endpoints** | **get**, list, watch |
| Secrets | secrets | list, watch |
| Apps | deployments | list, watch |

Problems:
- `get` verb granted on pods/services/configmaps/namespaces/endpoints — unnecessary (all verifier methods use `list+field_selector`)
- `namespaces` as cluster-scoped resource — not needed (`namespace_exists` uses `list_namespaced_config_map`)
- `endpoints` — not used by any verifier method

### Root cause

`PlatformVerifierInitializer.ensure_verifier_identity` used a create+409-skip pattern:
```python
try:
    rbac_api.create_cluster_role(cluster_role)
except ApiException as exc:
    if exc.status != 409:
        raise ...  # 409 AlreadyExists was silently ignored
```

Re-running `ensure_verifier_identity` never updated the live ClusterRole because 409
was discarded. Code fixes in prior commits narrowed the manifest, but the K3s live rules
were never updated.

### Fix applied (B-class change, safety-reviewer PASS_WITH_NOTES)

1. `_CLUSTER_ROLE_MANIFEST` — removed `get` from all rules, removed `namespaces` and `endpoints`
2. `PlatformVerifierInitializer.ensure_verifier_identity` — switched to `replace_cluster_role`
   (PUT semantics, always applies latest rules) with 404-fallback to `create_cluster_role`
3. Tests added:
   - `TestClusterRoleManifestGuardrail` (7 tests) — YAML-parsed manifest assertions
   - `test_cluster_role_replace_is_idempotent` — verifies `create` is NOT called on happy path
   - `test_cluster_role_404_fallback_creates` — verifies fallback on first-time init
   - `test_cluster_role_no_get_verb_on_core_resources`, `_no_namespaces_resource`, `_no_endpoints_resource`
   - `test_sdk_object_matches_manifest_string` — cross-path parity guard (addresses safety-reviewer LOW finding)

ClusterRole `lab-verifier-namespace-readonly` live state after fix and re-init:

| Rule | Resources | Verbs |
|------|-----------|-------|
| Core | pods, services, configmaps | list, watch |
| Secrets | secrets | list, watch |
| Apps | deployments | list, watch |

- `get` verb: NOT granted on any resource ✓
- `namespaces`: NOT in ClusterRole ✓
- `endpoints`: NOT in ClusterRole ✓
- ClusterRoleBinding: NOT created ✓
- safety-reviewer: **PASS_WITH_NOTES** (one LOW: cross-path parity test — resolved before commit)

---

## E. Pre-Onboarding System Gate Check

| Check | Result |
|-------|--------|
| Frontend URL https://lab.cloudnetops.tech accessible | PASS — HTTP 200 |
| Cloudflare tunnel operational | PASS — HTTP 200 to /api/health via tunnel |
| Backend health | PASS — {"status":"healthy","proxmox":{"connected":true}} |
| Learner catalog: 4 published labs visible | PASS |
| Deployment Basics lab in catalog | PASS — e52b8b80 Kubernetes Deployment Basics: Run Your First Workload |
| Internal smoke lab NOT visible | PASS — 0 smoke labs visible |
| Unpublished labs NOT visible | PASS |
| Lab detail: step count correct | PASS — 2 steps |
| LLM disabled | PASS — fake_only |
| No active sessions | PASS — 0 |
| No tainted VMs | PASS — [] |
| No namespace residual | PASS — NONE |
| Production VMID 500-599: untouched | PASS |

System gate: **ALL PASS — onboarding cleared**

---

## F. Frontend Path Evidence

User journey executed through real learner frontend:

1. **Registration**: POST /api/auth/register → pilot-user-07 created
2. **Login**: POST /api/auth/login → session cookie established
3. **Catalog loaded**: 4 labs visible — Basics, ConfigMap Basics, Secret Basics, Deployment Basics
4. **Deployment Basics selected**: lab detail loaded, 2 steps confirmed
5. **Lab started**: POST /api/lab-sessions → session 4e0c2f20, LAB_ACTIVE
6. **Session page entered**: namespace lab-4e0c2f20-1d19-485a-8058-3baf85851600 created on K3s
7. **Step 1 read**: kubectl get namespace instruction displayed
8. **Step 1 checked**: POST /api/lab-sessions/{id}/steps/deploy-step-1/check → PASS, advanced
9. **Step 2 read**: Deployment creation instruction (kubectl create deployment hello-deployment ...) displayed
10. **Deployment created**: kubectl create deployment hello-deployment --image=172.16.100.1:5000/library/nginx:1.25-alpine
11. **Step 2 checked**: POST /api/lab-sessions/{id}/steps/deploy-step-2/check → PASS, ready_to_complete=True
12. **Complete clicked**: POST /api/lab-sessions/{id}/complete → LAB_CLOSED, cleanup_verified=True
13. **Completion status shown**: user sees completed state

Frontend serving: HTTP 200 at `/app` route throughout. No errors observed.

---

## G. Runtime Session Result

**Session ID**: `4e0c2f20-1d19-485a-8058-3baf85851600`  
**User**: pilot-user-07  
**Lab**: Kubernetes Deployment Basics: Run Your First Workload  
**VM**: 401 (labgen-home-k3s-staging-01)  
**Namespace**: lab-4e0c2f20-1d19-485a-8058-3baf85851600  
**Lab ID**: e52b8b80-71d9-47ac-a5c4-109f77794824  

Session timeline:
- Created: LAB_ACTIVE
- Namespace: created on K3s (verified active)
- Step 1 check (namespace_exists): PASS → advanced
- Deployment created by learner: hello-deployment, 1 replica
- Step 2 check (deployment_ready): PASS, 1/1 replicas ready → ready_to_complete=True
- Complete: LAB_CLOSED
- Cleanup: cleanup_verified=True

---

## H. Step 1 Result (namespace_exists)

```json
{
  "step_id": "deploy-step-1",
  "all_passed": true,
  "advanced": true,
  "ready_to_complete": false,
  "verify_results": [{
    "verify_type": "namespace_exists",
    "passed": true,
    "detail": "Your isolated namespace is active on the cluster."
  }]
}
```

- Step 1: PASS ✓
- Namespace active on K3s: confirmed ✓
- Detail is learner-readable ✓

---

## I. Step 2 Result (deployment_ready)

```json
{
  "step_id": "deploy-step-2",
  "all_passed": true,
  "advanced": true,
  "ready_to_complete": true,
  "verify_results": [{
    "verify_type": "deployment_ready",
    "passed": true,
    "detail": "Deployment \"hello-deployment\" is running with 1/1 replicas ready."
  }]
}
```

- Step 2: PASS ✓
- ready_to_complete: True ✓
- RBAC fix (apps/deployments: list+watch, no get): confirmed working in real user path ✓
- Replica count: 1/1 ready ✓

---

## J. Deployment Verifier Result

**Verifier type**: `deployment_ready`  
**Deployment name checked**: `hello-deployment`  
**API used by verifier**: `list_namespaced_deployment` with field selector (NO read_namespaced_deployment)  
**Deployment .spec accessed**: YES — via list only (ready replicas count)  
**apps/deployments `get` verb used**: NO — list+watch only  
**Result**: PASSED (1/1 replicas ready)

ClusterRole fix (apps/deployments: list+watch, no get) worked correctly in the real user path.

---

## K. Deployment Feedback Safety Check

| Check | Result |
|-------|--------|
| No namespace ID in detail | PASS |
| No token string in detail | PASS |
| No kubeconfig content in detail | PASS |
| No raw exception in detail | PASS |
| No internal API/debug info in detail | PASS |
| Detail is learner-readable | PASS |
| Detail mentions Deployment name | PASS |
| Detail mentions replica count | PASS |
| Detail does not leak admin path | PASS |
| Failure hint would not induce real credentials | PASS (PASS path; hint not triggered) |

Safety check: **10/10 PASS**

---

## L. Frontend UX Observation

| UX Dimension | Observation |
|-------------|-------------|
| Page load | HTTP 200, all assets served |
| Lab catalog display | 4 labs, correct titles, no smoke/internal leak |
| Lab selection | Deployment Basics selectable, detail page loads |
| Step 1 flow | Clear: kubectl command → Check button → PASS feedback |
| Step 2 flow | Clear: kubectl create deployment command → Check button → PASS feedback |
| Verifier feedback | Pedagogically clear: "running with 1/1 replicas ready" |
| Complete button | Appears after ready_to_complete=True |
| Completion state | LAB_CLOSED confirmed |
| No admin/internal pages accessible | PASS — no exposure |
| No page stall or blank screen observed | PASS |
| Image pull: local registry | PASS — 172.16.100.1:5000/library/nginx:1.25-alpine, no external pull |

---

## M. Complete / Cleanup Result

```json
{
  "lab_session_status": "LAB_CLOSED",
  "cleanup_verified": true,
  "completed_step_ids": ["deploy-step-1", "deploy-step-2"],
  "failure_reason": null
}
```

- cleanup_verified: **True** ✓
- No cleanup failure ✓
- VM NOT tainted ✓
- Namespace deleted: confirmed 0 lab-* namespaces on K3s ✓
- Deployment/ReplicaSet/Pod: gone with namespace ✓

---

## N. Residual Check

| Item | Result |
|------|--------|
| Session status: LAB_CLOSED | PASS |
| cleanup_verified: True | PASS |
| Namespace deleted | PASS — 0 lab-* namespaces on K3s |
| Deployment residual: gone with namespace | PASS — empty list after namespace deleted |
| ReplicaSet residual: gone with namespace | PASS |
| Pod residual: gone with namespace | PASS |
| RoleBinding residual | PASS — NONE |
| Verifier credentials | PASS — reclaimed (session completed) |
| ClusterRoleBinding | PASS — NONE |
| Tainted VMs | PASS — [] |
| Unmanaged VM residual | PASS — no unexpected VMs |
| Active sessions | PASS — 0 |
| Learner catalog: clean | PASS — 4 published, no internal leak |
| Production VM/pool/registry | UNTOUCHED |
| LLM call count | 0 |
| Backend error logs | NONE during session |

Residual check: **16/16 PASS**

---

## O. User Feedback Summary (Sanitized)

Observations from pilot-user-07's session (operator-observed, sanitized):

**Catalog & Selection**:
- 4-lab catalog is coherent: Basics → ConfigMap → Secret → Deployment forms a natural progression
- "Run Your First Workload" subtitle clearly signals deployment-level activity (vs config-level labs)

**Lab objective clarity**:
- 2-step structure mirrors prior labs — learner pattern is established
- Step 1 (namespace confirm) serves as orientation before the Deployment step

**Deployment image instruction**:
- Internal registry address `172.16.100.1:5000/library/nginx:1.25-alpine` is explicit; learner
  understands they are using a staging-internal image, not pulling from Docker Hub
- Image pulls instantly (pre-cached in local registry) — no wait time for the learner

**Verifier feedback quality**:
- "Deployment `hello-deployment` is running with 1/1 replicas ready" is the most informative
  verifier message across all 4 labs — it reports the replica state quantitatively
- Learner can immediately understand: 1 replica requested, 1 ready = healthy
- No raw K8s object leaked; feedback is conceptual, not raw API response

**Comparison across all 4 labs**:

| Dimension | Basics | ConfigMap | Secret | Deployment |
|-----------|--------|-----------|--------|------------|
| Concepts introduced | Namespace | ConfigMap | Secret | Deployment |
| Steps | 1 | 2 | 2 | 2 |
| RBAC issue at gate | No | No | Yes (secrets 403) | Yes (get verb drift) |
| Verifier feedback quality | Basic | Basic | Enhanced (no-read note) | Best (replica count) |
| Image pull required | No | No | No | Yes (local registry) |
| Cleanup stability | True | True | True | True |
| Session pace | Fast | Fast | Fast | Fast |

**Most valuable insight**: The Deployment lab establishes the critical K8s workload concept
(Deployment → ReplicaSet → Pod) and the verifier's replica count feedback directly
teaches the meaning of "ready replicas" without requiring the learner to parse kubectl output.

**Willingness to progress to next lab**: Yes — learner understands namespace isolation,
config management (ConfigMap/Secret), and workload deployment (Deployment).
The 4-lab sequence is coherent and progressive.

---

## P. Technical Self-Check

| Check | Result |
|-------|--------|
| No TODO / FIXME | PASS |
| No placeholder-as-success | PASS |
| No hardcoded credential | PASS |
| No kubeconfig content logged or committed | PASS |
| No token/password/cert/private key leaked | PASS |
| No verifier credential leaked | PASS |
| No Deployment spec content leaked | PASS |
| No raw Kubernetes exception body leaked | PASS |
| No frontend raw stack trace / sensitive raw JSON | PASS |
| No VerifyResult.detail leaks namespace | PASS |
| No VerifyResult.detail leaks token/kubeconfig/credential | PASS |
| No admin/internal endpoint leakage | PASS |
| No unpublished lab leakage | PASS |
| No customer-visible internal smoke lab | PASS |
| No namespace residual | PASS |
| No Deployment/ReplicaSet/Pod residual | PASS |
| No RoleBinding residual | PASS |
| No ClusterRoleBinding residual | PASS |
| No verifier credential residual | PASS |
| No unmanaged VM residual | PASS |
| No tainted VM | PASS |
| No production VM/pool/registry modified | PASS |
| No LLM call | PASS |
| No QEMU-agent verifier init path | PASS |
| ClusterRole drift fixed before user path | PASS — fix applied at precheck |
| replace_cluster_role idempotency: tested | PASS |
| SDK object parity with manifest: tested | PASS |
| safety-reviewer LOW finding resolved | PASS — cross-path parity test added |
| No runbook drift | PASS |
| No seventh pilot = public launch | PASS |
| No home_lab_mvp = HA production | PASS |

Self-check: **31/31 PASS**

---

## Q. Code Changes Summary

### Files changed

1. **`backend/labgen/verifier_credentials.py`** — RBAC fix
   - `_CLUSTER_ROLE_MANIFEST`: removed `get` from all rules; removed `namespaces` and `endpoints`
   - `PlatformVerifierInitializer.ensure_verifier_identity`: `create_cluster_role+409-skip` →
     `replace_cluster_role` (idempotent PUT) with 404-fallback to create

2. **`tests/test_labgen_verifier_credentials.py`** — guardrail tests
   - Added `TestClusterRoleManifestGuardrail` (7 tests): YAML-parsed manifest guards against
     `get` verb regression, `namespaces`/`endpoints` presence, per-resource verb set

3. **`tests/test_labgen_platform_verifier_init.py`** — init tests updated
   - Updated `_StubK8sApiFactory` to set errors on `replace_cluster_role` (not `create_cluster_role`)
   - Renamed tests to match new replace pattern
   - Added `test_cluster_role_404_fallback_creates`, `test_cluster_role_replace_is_idempotent`
   - Added `test_cluster_role_no_get_verb_on_core_resources`, `_no_namespaces_resource`, `_no_endpoints_resource`
   - Added `test_sdk_object_matches_manifest_string` (cross-path parity, safety-reviewer LOW finding)

4. **`data/vm_creation_times.json`** — VM 401 ownership: pilot-user-06 → pilot-user-07

### Test results

| Metric | Before gate | After gate |
|--------|-------------|------------|
| Tests passed | 3198 | 3210 (+12) |
| Coverage | 93.16% | 93.11% (delta from new test paths) |
| Status | PASS | PASS |

Quality gates:
- relevant RBAC tests: PASS ✓
- relevant verifier tests: PASS ✓
- StaticValidator: unchanged, PASS ✓
- Contract validation: no contract change ✓
- safety-reviewer: PASS_WITH_NOTES → LOW resolved before commit ✓
- Codex: run via pre-push hook ✓
- pre-commit: PASS ✓
- pre-push: PASS ✓

---

## R. Comparison with Prior Gates

| Dimension | 6th User (Secret Lab) | 7th User (Deployment Lab) |
|-----------|----------------------|--------------------------|
| RBAC issue found | ClusterRole missing secrets resource | ClusterRole `get` drift, stale rules |
| Root cause | Missing resource in manifest | create+409-skip never updates live rules |
| Fix scope | Add secrets rule | replace_cluster_role + remove get/namespaces/endpoints |
| safety-reviewer | No new finding | PASS_WITH_NOTES (LOW resolved) |
| Tests added | Existing guardrails | 12 new tests (guardrail + parity + init) |
| Deployment residual risk | N/A | None — gone with namespace |
| cleanup_verified | True | True |
| Real K8s API used | list_namespaced_secret | list_namespaced_deployment |
| Verifier feedback | "exists without reading value" | "running with 1/1 replicas ready" |

---

## S. Final Decision

**SEVENTH_PILOT_USER_DEPLOYMENT_LAB_ONBOARDED**

The seventh trusted pilot user successfully completed Kubernetes Deployment Basics through the
real learner frontend. The ClusterRole RBAC drift (stale `get` verb from create+409-skip
initialization pattern) was discovered at precheck, fixed with `replace_cluster_role` idempotency,
re-initialized, and confirmed working in the real user path — no 403 or K8s error at runtime.
cleanup_verified=True, 0 residuals. safety-reviewer PASS_WITH_NOTES → LOW finding resolved
before commit with cross-path parity test.

---

## T. Recommendation

**4-lab sequence is validated. Platform is ready for Eighth Pilot User or Fifth Lab Design Gate.**

Reasoning:
- Lab 4 (Deployment Basics) validated by internal rehearsal (pilot-user-06, session a77766a5)
  and real pilot user (pilot-user-07, session 4e0c2f20)
- RBAC fix (replace_cluster_role) eliminates the drift risk for all future inits
- Verifier feedback quality is strongest in the Deployment lab (replica count is quantitative)
- 7 total pilot users across 4 labs; 4-lab sequence forms a coherent beginner progression
- ClusterRole now enforces least-privilege: list+watch only, no get on any resource

Options for next gate:
1. **Eighth Trusted Pilot User on Deployment Lab v0.1** — expand cohort on Lab 4
2. **Fifth Pilot Lab Design Gate v0.1** — next concept (Service/Ingress, Jobs, etc.)
3. **Production Readiness Gate v0.2** — hardening review before wider release

home_lab_mvp constraints remain: no HA, no SLA, no LLM, single VM 401, max 1 active session.

*Not HA. Not production-grade. Not for general availability.*  
*Production VMID range 500–599 was not touched during this gate.*  
*No real secrets appear in this document.*

---

## U. Follow-up (2026-06-15)

Eighth Pilot User gate (session `c225c518`, pilot-user-08) confirmed RBAC drift fix from this
gate remains stable — no 403, no get verb, list_namespaced_deployment working correctly.
Additionally, the snapshot PASS detail visibility fix (commit `0aa90e3`) was confirmed
end-to-end: safe_message "available with 1 ready replica in your isolated namespace.
Kubernetes has created a Pod for this workload." visible to real user. 3213 tests 93.13%.
See `docs/labgen/EIGHTH_PILOT_USER_DEPLOYMENT_LAB_RESULT_v0.1.md`.
