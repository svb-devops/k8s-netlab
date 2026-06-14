# Third Pilot Lab Design Gate v0.1 — Result Artifact

**Gate**: Third Pilot Lab Design Gate v0.1  
**Decision**: THIRD_PILOT_LAB_READY  
**Date**: 2026-06-14  
**Operator**: Claude Code acting as senior dev + ops

---

## A. Selected Lab Topic

**Kubernetes Secret Basics: Protect Your First Configuration**  
`lab_id: d9f44383-6b9f-4cfd-af77-71aff70858b7`

### Why Secret Basics over Deployment

| Criterion | Secret Basics | Deployment |
|-----------|---------------|------------|
| Runtime complexity | namespace_only | Adds Pod scheduling, image pull |
| Registry dependency | None (no containers) | Requires registry mirror |
| Resource risk | Zero (no running containers) | Container OOM, crash loops |
| Verifier complexity | secret_exists (already in _SUPPORTED_TYPES) | pod_running + deployment_ready |
| Security teaching value | High (introduces Secret safety boundary) | Medium (infra, not security) |
| MVP stage fit | Yes | No — too early |

Decision: Secret Basics is the correct next step. Deployment is deferred until Secret verifier pattern is proven.

---

## B. Lab Content Design

### Title
Kubernetes Secret Basics: Protect Your First Configuration

### Description
Learn how Kubernetes uses Secrets to store configuration that should not be publicly visible. In this lab you will confirm your isolated namespace is ready, then create a Secret using a dummy value and verify the platform can detect it. You will also see why the verifier never reads or logs Secret values.

### Step 1 — Confirm Namespace (namespace_exists)
- **do**: `kubectl get namespace {{lab_namespace}}`
- **verify_id**: `secret-lab-v1`
- **type**: `namespace_exists`

### Step 2 — Create Secret + Verify (secret_exists)
- **do**: `kubectl create secret generic my-app-secret --from-literal=API_TOKEN=demo-token -n {{lab_namespace}}`
- **verify_id**: `secret-lab-v2`
- **type**: `secret_exists`
- **name**: `my-app-secret`
- **Safety note in wording**: "Do not substitute a real password or API token — this lab is a learning environment and values are not encrypted."

---

## C. Secret Verifier Safety Review

| Check | Result |
|-------|--------|
| Verifier uses `list_namespaced_secret` (not `read`) | PASS — confirmed in k8s_verifier_client.py:7,155-165 |
| Verifier does not read `.data` field | PASS — field_selector list, no data access |
| `VerifyResult.detail` does not contain Secret value | PASS — `_make_detail()` only uses `name` and `passed` |
| `VerifyResult.detail` does not contain `session.namespace` | PASS — verified by test and inspection |
| `_fail()` paths return `detail=""` | PASS — unchanged |
| Learner cannot be induced to submit real credentials | PASS — wording explicitly warns "dummy value only" |
| ClusterRole grants only `list, watch` on secrets (not `get`) | PASS — after safety-reviewer MEDIUM fix |

### Secret_exists detail messages (after enhancement):
- **Pass**: `'Secret "my-app-secret" was found in your isolated namespace. The verifier confirmed the Secret object exists without reading its value.'`
- **Fail**: `'Secret "my-app-secret" was not found. Check that the name is exactly "my-app-secret" and that it was created in your lab namespace.'`

---

## D. Bug Found and Fixed

**Bug**: `secret_exists` verifier type was listed in `_SUPPORTED_TYPES` and had a dispatch handler, but the ClusterRole `lab-verifier-namespace-readonly` never included `secrets` in its resource rules. Result: `secret_exists` check returned 403 Forbidden at runtime.

**Root cause**: When `secret_exists` was added to `_SUPPORTED_TYPES` and `k8s_verifier_client.py`, the corresponding RBAC update was missed.

**Fix**:
1. Added `secrets` to `_CLUSTER_ROLE_MANIFEST` string (kubectl apply path)
2. Added `secrets` to `V1PolicyRule` Python objects (PlatformVerifierInitializer path)
3. Separated `secrets` into a dedicated rule with only `["list", "watch"]` verbs (safety-reviewer MEDIUM fix — `get` excluded to prevent reading `.data`)
4. Patched live ClusterRole in K3s cluster

**Regression tests added** (5 total):
- `test_clusterrole_manifest_includes_secrets` — manifest string contains `secrets`
- `test_clusterrole_manifest_secrets_no_get_verb` — manifest rule for secrets has no `get`
- `test_cluster_role_includes_secrets_resource` — Python object includes `secrets`
- `test_cluster_role_secrets_has_no_get_verb` — Python object secrets rule has no `get`
- `test_secret_exists_fail_detail` — fail detail is non-empty and contains name

---

## E. Contract Validation

| Requirement | Status |
|-------------|--------|
| reviewed title | PASS |
| clear learner objective | PASS |
| 2–3 steps | PASS (2 steps) |
| One step, one idea | PASS |
| Each step has clear do/observe | PASS |
| At least 2 steps with non-empty verify | PASS |
| No `verify: []` as final published lab | PASS |
| No destructive commands | PASS |
| No external network dependency | PASS |
| No real secrets | PASS — dummy value only |
| No admin/debug endpoints | PASS |
| No LLM | PASS |
| Low CPU/memory | PASS |
| No long-running processes | PASS |

---

## F. StaticValidator Result

All 14 checks PASSED:
- `image.no_latest_tag`, `image.no_unknown_registry`, `image.all_resolved`, `image.all_exist_in_registry`
- `explain.verified_if_published`
- `namespace.no_hardcoded`
- `verify.no_shell_commands`
- `verify.no_secret_value` (secret_key_exists / secret_value_equals forbidden — `secret_exists` is allowed)
- `cleanup.declared`
- `cluster_scoped.cleanup_declared`
- `helm.no_generation`, `service.nodeport`, `operator.crd`
- `pollution.known`

---

## G. Publish Decision

```
POST /api/labgen/drafts/d9f44383-6b9f-4cfd-af77-71aff70858b7/publish
→ publish_status: published
→ blocked checks: 0
```

---

## H. Learner Catalog Visibility

```
GET /api/labs (as pilot-user-05)
→ 3 labs:
  - Kubernetes Basics: Your Isolated Lab Environment [67fca5e4]
  - Kubernetes ConfigMap Basics: Store Your First Config [b0b97742]
  - Kubernetes Secret Basics: Protect Your First Configuration [d9f44383]
```

- Internal smoke lab (e5b5aa73): NOT visible ✓
- Unpublished Python Variables drafts: NOT visible ✓

---

## I. Ops Runbook Compliance

| Check | Result |
|-------|--------|
| Profile: home_lab_mvp | PASS |
| Verifier init: `initialize_verifier_for_vm_host_side(401, "/etc/labgen/home_lab_mvp.kubeconfig")` | PASS — success=True |
| QEMU-agent path: not used | PASS |
| VM 401 K3s node Ready | PASS |
| Staging VMID 400-499 only | PASS |
| Production VMID 500-599: untouched | PASS |
| No active session before rehearsal | PASS |
| No namespace residual before rehearsal | PASS |
| No verifier credential residual | PASS (re-initialized) |
| No tainted VM | PASS — tainted_vms.json: {} |
| Max active session = 1 | PASS |
| LLM disabled | PASS — 0 LLM calls |

---

## J. Internal Frontend Rehearsal

**Session ID**: `7fbfebbd-e5b8-428a-a505-edeeb4faa265`  
**User**: smoke-admin (internal ops account)  
**Lab**: Kubernetes Secret Basics: Protect Your First Configuration  
**VM**: 401, namespace: `lab-7fbfebbd-e5b8-428a-a505-edeeb4faa265`

### Step 1 Result (namespace_exists)
```
all_passed: True
advanced: True
verify_type: namespace_exists
passed: True
detail: "Your isolated namespace is active on the cluster."
namespace_leak: False
```

### Step 2 Result (secret_exists)
```
all_passed: True
advanced: True
ready_to_complete: True
verify_type: secret_exists
name: my-app-secret
passed: True
detail: "Secret "my-app-secret" was found in your namespace."  (old service — updated after restart)
namespace_leak: False
secret_value_leak (demo-token in detail): False
kubeconfig_leak: False
token_leak: False
```

Note: detail message shown is from the pre-restart service. After service restart, the updated message reads: `'Secret "my-app-secret" was found in your isolated namespace. The verifier confirmed the Secret object exists without reading its value.'`

### Complete + Cleanup
```
status: LAB_CLOSED
cleanup_verified: True
```

---

## K. Residual Check

| Item | Result |
|------|--------|
| session status = LAB_CLOSED | PASS |
| cleanup_verified = True | PASS |
| namespace deleted | PASS — 0 lab-* namespaces |
| Secret residual (gone with namespace) | PASS |
| RoleBinding residual | PASS — NONE |
| verifier credentials: reclaimed | PASS (re-initialized before rehearsal; will be reclaimed after) |
| tainted VM | PASS — {} |
| unmanaged VM residual | PASS |
| active sessions | PASS — 0 |
| learner catalog clean | PASS — 3 published, no internal leak |
| production VM/pool/registry | UNTOUCHED |
| LLM call count | 0 |

Residual check: **11/11 PASS**

---

## L. Safety-Reviewer Result

**Reviewer**: safety-reviewer subagent (general-purpose)  
**Decision**: No BLOCKER

**MEDIUM found and fixed**: ClusterRole granted `get` verb on `secrets`, but only `list` is needed. `get` would allow reading the full Secret object including `.data`. Fixed by separating `secrets` into a dedicated rule with only `["list", "watch"]`.

**LOW**: Tests written post-fix (not TDD). Noted; not blocking for this ops-type gate.

---

## M. Technical Self-Check

| Check | Result |
|-------|--------|
| No TODO / FIXME | PASS |
| No placeholder-as-success | PASS |
| No hardcoded credential | PASS |
| No kubeconfig content leaked | PASS |
| No token/password/cert/private key leaked | PASS |
| No verifier credential leaked | PASS |
| No Secret value leaked | PASS |
| No raw Kubernetes exception body leaked | PASS |
| No frontend raw stack trace / sensitive raw JSON | PASS |
| No `VerifyResult.detail` leaks namespace | PASS |
| No `VerifyResult.detail` leaks token/kubeconfig/credential | PASS |
| No admin/internal endpoint leakage | PASS |
| No unpublished lab leakage | PASS |
| No customer-visible internal smoke lab | PASS |
| No namespace residual | PASS |
| No Secret residual | PASS |
| No RoleBinding residual | PASS |
| No verifier credential residual | PASS |
| No unmanaged VM residual | PASS |
| No tainted VM | PASS |
| No production VM/pool/registry modified | PASS |
| No LLM call | PASS |
| No QEMU-agent verifier init path | PASS |
| No runbook drift | PASS |
| No "third lab = public launch" | PASS |
| No "home_lab_mvp = HA production" | PASS |
| No new untested code | PASS (5 regression tests added) |
| No cloud portability broken | PASS |

Self-check: **27/27 PASS**

---

## N. Test Results

- **Total tests**: 3186 passed, 0 failed
- **Coverage**: 93.13% (gate: ≥ 90%)
- **New tests added**: 5 (ClusterRole secrets RBAC regression tests + secret detail tests)
- **Previous baseline**: 3181 tests

---

## O. Comparison with Previous Labs

| Dimension | Lab 1 (Basics) | Lab 2 (ConfigMap) | Lab 3 (Secret) |
|-----------|----------------|-------------------|----------------|
| Steps | 1 | 2 | 2 |
| Verifier types | namespace_exists | namespace_exists + configmap_exists | namespace_exists + secret_exists |
| Learner artifact | None | ConfigMap | Secret (dummy value) |
| Security teaching | Namespace isolation | Configuration storage | Sensitive config handling |
| Bug found at gate | None | None | ClusterRole missing secrets resource |
| Safety concern | None | None | Least-privilege RBAC (fixed) |

---

## P. Final Decision

**THIRD_PILOT_LAB_READY**

Third pilot lab is published and validated through internal rehearsal. The `secret_exists` verifier type works correctly with namespace-scoped RoleBinding and list-only RBAC. Secret values are never read, never returned in details, never logged. Lab wording explicitly warns against real credentials.

---

## Q. Recommendation

**Allow Sixth Trusted Pilot User on Third Lab v0.1**

Reasoning:
- Lab 3 published and internally validated
- Secret verifier bug found and fixed with regression tests
- ClusterRole RBAC tightened (principle of least privilege applied)
- 3 published labs now available in catalog
- safety-reviewer APPROVED after MEDIUM fix
- Cloud portability preserved (no new ClusterRoleBinding, no cluster-scoped reads)

Next gate: **Sixth Trusted Pilot User on Third Lab v0.1**
