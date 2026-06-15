# Deployment Feedback Triage & Iteration v0.1

**Date**: 2026-06-15  
**Decision**: DEPLOYMENT_FEEDBACK_TRIAGED_WITH_ITERATION  
**Operator**: Claude Code acting as senior dev + ops  
**Basis**: Seventh Trusted Pilot User on Deployment Lab v0.1 (commit `b48a9a2`)

---

## A. Summary

| Field | Value |
|-------|-------|
| Lab name | Kubernetes Deployment Basics: Run Your First Workload |
| Lab ID | e52b8b80-71d9-47ac-a5c4-109f77794824 |
| Pilot session | 4e0c2f20 (pilot-user-07, seventh gate) |
| Rehearsal session 1 | 18ad13a8 (pre-restart warm-up — old code, valid clean close) |
| Rehearsal session 2 | 4981c171 (post-restart — new code, feedback verified) |
| Final status | LAB_CLOSED (both rehearsals) |
| Cleanup result | cleanup_verified=True (both) |
| Residual result | 0 lab-* namespaces, 0 tainted VMs |
| Current gate state | DEPLOYMENT_FEEDBACK_TRIAGED_WITH_ITERATION |

---

## B. What Worked

| Area | Finding |
|------|---------|
| Learner catalog | 4 labs visible, correct titles, no smoke/internal leak |
| Lab detail load | e52b8b80 loads, 2 steps confirmed |
| Deployment start flow | POST /api/lab-sessions → LAB_ACTIVE, namespace created on K3s |
| namespace_exists (Step 1) | PASS on first attempt in all tested sessions |
| deployment_ready (Step 2) | PASS (1/1 replicas ready) in all tested sessions |
| Image readiness | `nginx:1.25-alpine` pulled from `172.16.100.1:5000/library/nginx:1.25-alpine` (local mirror, no internet) |
| Pod readiness | Pod ready within ~8s of Deployment creation |
| Ready replica feedback | **After iteration**: "available with 1 ready replica" — quantitative and educational |
| Complete flow | LAB_CLOSED after ready_to_complete=True confirmed |
| Cleanup | Namespace deletion cascades Deployment / ReplicaSet / Pod / RoleBinding — 0 residuals |
| Runbook compliance | host-side verifier init used; QEMU-agent path not used; VMID 400–499 only |
| RBAC (post-fix) | list+watch only on all resources; no `get`; no `namespaces`; no `endpoints` |

---

## C. Bugs Found and Fixed

### C.1 RBAC Drift (fixed in commit `b48a9a2`, prior gate)

**Symptom**: Operator discovered at Seventh Pilot User precheck that the live ClusterRole
`lab-verifier-namespace-readonly` on K3s contained stale rules: `get` verb on all core resources,
plus `namespaces` and `endpoints` resources. No runtime 403 occurred during actual user path
(K3s verifier used list+field_selector, not get) but the grant was overbroad.

**Root cause**: `PlatformVerifierInitializer.ensure_verifier_identity` used create+409-skip:
```python
try:
    rbac_api.create_cluster_role(cluster_role)
except ApiException as exc:
    if exc.status != 409:
        raise  # 409 silently discarded → live rules never updated
```
Code commits had narrowed the manifest, but K3s live rules were never re-applied.

**Fix**: Switch to `replace_cluster_role` (PUT semantics) + 404-fallback. Re-running
`ensure_verifier_identity` now ALWAYS applies the current manifest to the live ClusterRole.

**Stale rules removed**:
- `get` verb on all core resource rules
- `namespaces` resource (never used by any verifier method)
- `endpoints` resource (never used)
- `daemonsets`, `statefulsets`, `replicasets` (not used)

**Live ClusterRole after fix**:
| Rule | Resources | Verbs |
|------|-----------|-------|
| Core | pods, services, configmaps | list, watch |
| Secrets | secrets | list, watch |
| Apps | deployments | list, watch |

**Regression tests** (12 added in `b48a9a2`):
- `TestClusterRoleManifestGuardrail` (7 tests): YAML-parsed manifest assertions
- `test_cluster_role_replace_is_idempotent`, `test_cluster_role_404_fallback_creates`
- `test_cluster_role_no_get_verb_on_core_resources`, `_no_namespaces_resource`, `_no_endpoints_resource`
- `test_sdk_object_matches_manifest_string` (cross-path parity — safety-reviewer LOW finding)

**Risk if unfixed**: Least-privilege violation. Any future RBAC audit would flag `get` on
core resources. Namespace-scoped `list_namespaced_*` pattern requires only `list`; `get` grants
direct read of individual objects by name, which is not needed and widens the attack surface
if the verifier SA token were compromised.

**Status**: RESOLVED — live ClusterRole confirmed correct after `replace_cluster_role` + re-init.

---

### C.2 safety-reviewer LOW Finding — cross-path parity (resolved before b48a9a2 commit)

**Symptom**: `_CLUSTER_ROLE_MANIFEST` YAML string and `V1ClusterRole` SDK object are two
parallel apply paths in `ensure_verifier_identity`. No test confirmed they encoded the same
apiGroups/resources/verbs.

**Fix**: Added `test_sdk_object_matches_manifest_string` — parses both paths into frozenset-of-tuples
canonical form and asserts equality. Future divergence between the two paths will fail this test.

**Status**: RESOLVED before commit `b48a9a2`.

---

## D. Deployment UX / Teaching Feedback

### D.1 Verifier feedback quality assessment (before iteration)

| Dimension | Before iteration | After iteration |
|-----------|-----------------|-----------------|
| PASS message | "is ready in your namespace." | "is available with 1 ready replica in your isolated namespace. Kubernetes has created a Pod for this workload." |
| FAIL message | "is not ready yet. Check with: kubectl get deployments" | "is not ready yet. Check that the Deployment is named '{name}', uses 1 replica, and uses the approved image. It may take a short time for the Pod to become ready." |
| Replica count visible | NO | YES — "1 ready replica" |
| Pod concept introduced | NO | YES — "Kubernetes has created a Pod" |
| Failure guidance | generic kubectl command only | actionable: name check + replica check + image check + timing |
| Image leak in fail message | N/A | NO — "approved image" (static text, no URL/tag) |

**Teaching value of new PASS message**: Learner sees "1 ready replica" which directly maps to
`kubectl get deployments` output `READY 1/1`. The phrase "Kubernetes has created a Pod" connects
the Deployment abstraction to the Pod they can observe with `kubectl get pods`. This is the highest
pedagogical signal of any lab's verifier feedback (ConfigMap/Secret only say "was found").

**Teaching value of new FAIL message**: Provides three concrete checks — name, replica count,
image — and sets correct timing expectations ("it may take a short time"). Prevents learners from
clicking Check repeatedly out of frustration without understanding what to verify.

### D.2 Lab instruction improvement

**Step 2 `do` field — before iteration**:
```
Create a Deployment named `hello-deployment` with 1 replica:

kubectl create deployment hello-deployment --image=nginx:1.25-alpine --replicas=1

Wait a few seconds for the Pod to start, then click Check Step.
```

**Step 2 `do` field — after iteration**:
```
Create a Deployment named `hello-deployment` with 1 replica:

kubectl create deployment hello-deployment --image=nginx:1.25-alpine --replicas=1

Do not change the replica count or image. The verifier checks for one ready replica.

Wait a few seconds for the Pod to start, then click Check Step. If the check fails on
the first attempt, wait briefly and try again while Kubernetes starts the Pod.
```

**Improvements**:
- Explicit constraint: "Do not change the replica count or image" — prevents off-spec experiments
- Explicit retry guidance: eliminates confusion on first-attempt timing failures (Pod scheduling latency)
- No new security surface: the `nginx:1.25-alpine` short form still resolves via K3s registry mirror

---

## E. Workload Risk Review

| Risk | Assessment |
|------|------------|
| Image pull reliability | LOW — `nginx:1.25-alpine` is pre-cached at `172.16.100.1:5000/library/nginx:1.25-alpine`. No internet pull. Pull is instant in practice (~0ms from local registry). |
| Registry / mirror dependency | MEDIUM — single local registry `172.16.100.1:5000`. If registry goes down, image pull fails. Acceptable for home_lab_mvp single-host setup (registry and K3s run on same host network). |
| Pod scheduling | LOW — K3s single-node; no scheduling spread. Pod always lands on the same node. No resource contention observed in 4 tested sessions. |
| Resource limits | NOTE — Deployment has no `resources.limits`. K3s default limits apply. For home_lab_mvp single session at a time, this is acceptable. |
| Cleanup of Deployment / ReplicaSet / Pod | PASS — Namespace deletion cascades all workload objects. Confirmed 0 residuals in 4 sessions (design rehearsal, sixth user internal, seventh user, triage rehearsal). |
| Effect on max active session = 1 | PASS — Backend enforces. Workload Deployment does not increase concurrent resource usage since only 1 session at a time. |
| Safe for small cohort | YES — All risk dimensions are LOW or ACCEPTABLE for 3–5 more users at home_lab_mvp scale. |

---

## F. Issue Triage

| Severity | Category | Issue | Status |
|----------|----------|-------|--------|
| — | — | No BLOCKER found | — |
| — | — | No HIGH found | — |
| MEDIUM (resolved) | RBAC | ClusterRole live rules stale after create+409-skip pattern; `get` verb overbroad | RESOLVED — `b48a9a2` |
| LOW (resolved) | verifier correctness | DEPLOYMENT_READY PASS detail lacks replica count and Pod concept | RESOLVED — this iteration |
| LOW (resolved) | frontend UX | DEPLOYMENT_READY FAIL detail lacks actionable image/replica/timing guidance | RESOLVED — this iteration |
| LOW (resolved) | teaching clarity | Lab step 2 instructions lack retry hint and "do not change" constraint | RESOLVED — this iteration |
| LOW (resolved) | safety review | manifest/SDK cross-path parity not tested | RESOLVED — `b48a9a2` |
| NOTE | ops burden | Verifier re-init must be run before each gate (documented in runbook Section C) | ACCEPTED — runbook sufficient |
| NOTE | portability | home_lab_mvp uses local registry; cloud profile needs registry mirror reconfiguration | ACCEPTED — documented in runbook Section G |
| NOTE | ops burden | Runbook Section I now documents RBAC drift root cause + replace_cluster_role behavior | RESOLVED — this iteration |

---

## G. Recommendation

### Allow small cohort gate on Deployment Lab

All resolved issues are at LOW severity or below. No BLOCKER. No HIGH.

| Decision point | Finding |
|----------------|---------|
| Allow Deployment Lab small cohort? | **YES** — Lab has been validated in 2 real user sessions + 2 rehearsal sessions. All 4 produced LAB_CLOSED + cleanup_verified=True + 0 residuals. |
| Deployment UX/content iteration needed before cohort? | **NO** — Iteration complete in this triage. New feedback is confirmed in rehearsal (session 4981c171). |
| RBAC/runbook hardening needed before cohort? | **NO** — RBAC fix confirmed. Runbook updated with Section I (RBAC-DRIFT-001). |
| Start fifth lab design? | **DEFERRED** — User decision. Recommend either cohort expansion or fifth lab, not both in parallel. |
| Keep 1 concurrent session + LLM disabled? | **YES** — home_lab_mvp constraints must remain. No justification to raise limits. |

---

## H. Iteration Summary (this triage)

### Code changes

**`backend/labgen/verifier.py`** — `_make_detail()` DEPLOYMENT_READY branch:
```python
# Before
f'Deployment "{name}" is ready in your namespace.'
# ...
f'Deployment "{name}" is not ready yet. Check with: kubectl get deployments'

# After
f'Deployment "{name}" is available with 1 ready replica in your isolated namespace. '
"Kubernetes has created a Pod for this workload."
# ...
f'Deployment "{name}" is not ready yet. '
f'Check that the Deployment is named "{name}", uses 1 replica, and uses the approved image. '
"It may take a short time for the Pod to become ready."
```

**`tests/test_labgen_verifier.py`** — updated `test_deployment_ready_pass_detail` + added `test_deployment_ready_fail_detail`:
- Pass assertions: `"available" in detail`, `"replica" in detail`, `"Pod" in detail`
- Fail assertions: `"not ready" in detail`, `"approved image" in detail`, `"short time" in detail`

### Data changes

**`data/lab_drafts.json`** — Step 2 `do` field: added "Do not change the replica count or image" and retry hint.

### Doc changes

**`docs/labgen/HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md`** — Section I added:
- RBAC-DRIFT-001 root cause, fix, and operator behavior documentation
- Post-init verification command for operators

---

## I. Internal Rehearsal Result

| Dimension | Session 1 (18ad13a8, old code) | Session 2 (4981c171, new code) |
|-----------|-------------------------------|-------------------------------|
| Purpose | Clean close before service restart | Verify new feedback messages |
| Step 1 (namespace_exists) | PASS | PASS |
| Step 2 (deployment_ready) | PASS — old detail confirmed | PASS — **new detail confirmed** |
| detail (PASS) | "is ready in your namespace." | **"is available with 1 ready replica in your isolated namespace. Kubernetes has created a Pod for this workload."** |
| ready_to_complete | True | True |
| Complete | LAB_CLOSED | LAB_CLOSED |
| cleanup_verified | True | True |
| Lab namespaces residual | 0 | 0 |
| Tainted VMs | 0 | 0 |
| Backend errors | 0 | 0 |

Rehearsal result: **new detail message confirmed working in live service path.**

---

## J. Safety / Constraint Self-Check

| Check | Result |
|-------|--------|
| No TODO / FIXME | PASS |
| No placeholder-as-success | PASS |
| No hardcoded credential | PASS |
| No kubeconfig content logged or committed | PASS |
| No token/password/cert/private key leaked | PASS |
| No verifier credential leaked | PASS |
| No Deployment spec content leaked (detail is static text) | PASS |
| No raw Kubernetes exception body leaked | PASS |
| No VerifyResult.detail leaks namespace | PASS |
| No VerifyResult.detail leaks token/kubeconfig/credential | PASS |
| No admin/internal endpoint leakage | PASS |
| No unpublished lab leakage | PASS |
| No "approved image" hint reveals registry URL or credential | PASS — "approved image" is static text |
| No namespace residual | PASS — 0 lab-* namespaces |
| No Deployment/ReplicaSet/Pod residual | PASS — cascaded with namespace deletion |
| No RoleBinding residual | PASS |
| No verifier credential residual | PASS — reclaimed on session close |
| No tainted VM | PASS — {} |
| No production VM/pool/registry modified | PASS |
| No LLM call | PASS |
| No QEMU-agent verifier init path | PASS |
| No overbroad RBAC (get verb) | PASS — confirmed after re-init |
| No runbook drift | PASS — Section I added |
| No Deployment pilot → public launch | PASS |
| No home_lab_mvp → HA production | PASS |
| No new untested code | PASS — 1 new test added (test_deployment_ready_fail_detail) |
| safety-reviewer: PASS_WITH_NOTES (LOW resolved) | PASS |
| Codex review | via pre-push hook |
| No cloud portability broken | PASS |

---

## K. Test Results

| Metric | Before triage | After triage |
|--------|--------------|--------------|
| Tests passed | 3210 | 3211 (+1) |
| Coverage | 93.11% | 93.12% |
| Status | PASS | PASS |

New test: `test_deployment_ready_fail_detail` (tests failure message content)

---

## L. Final Decision

**DEPLOYMENT_FEEDBACK_TRIAGED_WITH_ITERATION**

The Deployment workload lab has been triaged and iterated. The RBAC drift (create+409-skip) was
the only MEDIUM issue — already resolved in `b48a9a2`. Verifier feedback quality and lab
instruction gaps were LOW — iterated and confirmed working in internal rehearsal.

The 4-lab sequence (Basics → ConfigMap → Secret → Deployment) is now coherent, progressive,
and has validated RBAC for each resource type:
- namespace_exists: list configmaps by field selector
- configmap_exists: list configmaps by field selector
- secret_exists: list secrets by field selector (no value read)
- deployment_ready: list deployments by field selector (replica count from status)

All verifier types use `list+field_selector` — no `get` required on any resource.

---

## M. Recommendation

**Allow Eighth Trusted Pilot User on Deployment Lab v0.1** OR **Fifth Pilot Lab Design Gate v0.1**

The small cohort can begin on the Deployment lab. The content is correct, the RBAC is minimal,
the feedback is pedagogically sound, and cleanup is reliable across all tested sessions.

home_lab_mvp constraints remain: no HA, no SLA, no LLM, single VM 401, max 1 active session.

*Not HA. Not production-grade. Not for general availability.*  
*Production VMID range 500–599 was not touched during this triage.*  
*No real secrets appear in this document.*
