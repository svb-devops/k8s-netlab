# Deployment Lab Design Gate v0.1 — Result

**Date**: 2026-06-15  
**Decision**: DEPLOYMENT_LAB_READY  
**Session**: Internal rehearsal only — 0 production users, 0 production VMs touched  

---

## Summary

Fourth pilot lab "Kubernetes Deployment Basics: Run Your First Workload" has been designed,
validated, published, and successfully completed in one internal rehearsal session.
All cleanup residuals cleared. ClusterRole updated to least-privilege (list+watch only, no get).

---

## Feasibility Gate (pre-design checks)

| Check | Result |
|-------|--------|
| K3s VM health (VM 401) | PASS — K3s healthy, QEMU agent responsive |
| Registry reachable | PASS — `172.16.100.1:5000` responding |
| `nginx:1.25-alpine` in registry | PASS — OCI Accept header fix confirmed pull |
| `deployment_ready` verifier type | PASS — already implemented (list_namespaced_deployment) |
| Verifier RBAC on VM 401 | PASS — ClusterRole updated, gen=2 re-initialized |

---

## RBAC Changes (committed 80736b9)

**Before**: `apps/deployments,daemonsets,statefulsets,replicasets: get,list,watch`  
**After**: `apps/deployments: list,watch` (no get; no daemonsets/statefulsets/replicasets)

`deployment_ready()` uses `list_namespaced_deployment` with `field_selector=metadata.name={name}`,
matching the `secret_exists` pattern — no `get` RBAC required.

---

## Image Readiness (committed 1932c58)

- OCI Accept header added to `_default_http_get` — required for multi-arch OCI index images
- Whitelist paths corrected: `nginx` → `172.16.100.1:5000/library/nginx:1.25-alpine`
- Existence check: `existence_check_passed=True` manually set (admin-verified, image confirmed on VM)

---

## Lab Draft

**lab_id**: `e52b8b80-71d9-47ac-a5c4-109f77794824`  
**Title**: Kubernetes Deployment Basics: Run Your First Workload  
**Duration**: 20 minutes  
**Steps**: 2

| Step | verify_id | Type | Result |
|------|-----------|------|--------|
| 1 — Namespace active | depl-v1 | namespace_exists | PASS |
| 2 — Create Deployment | depl-v2 | deployment_ready | PASS |

**Publish gate**: 14/14 checks passed  
**Image readiness**: READY (`nginx:1.25-alpine` → `172.16.100.1:5000/library/nginx:1.25-alpine`)  
**Publish status**: published

---

## Internal Rehearsal

**User**: pilot-user-06 (existing staging user, VM 401)  
**Session**: `a77766a5-a381-4235-aa83-2db48b3d05ec`  
**Namespace**: `lab-a77766a5-a381-4235-aa83-2db48b3d05ec`

| Action | Result |
|--------|--------|
| Login + catalog (4 labs visible) | PASS |
| Session start (LAB_ACTIVE) | PASS |
| Step 1 check (namespace_exists) | PASS — detail: "Your isolated namespace is active on the cluster." |
| Create hello-deployment (kubectl via QEMU agent) | PASS — deployment.apps/hello-deployment created |
| Deployment ready (1/1 replicas) | PASS — confirmed via platform kubeconfig |
| Step 2 check (deployment_ready) | PASS — detail: "Deployment \"hello-deployment\" is ready in your namespace." |
| Session complete (ready_to_complete=True) | PASS |
| Final status | LAB_CLOSED |

---

## Cleanup Residuals (all PASS)

| Resource | Status |
|----------|--------|
| Namespace `lab-a77766a5-...` | DELETED |
| Deployment `hello-deployment` | DELETED (namespace deletion cascades) |
| ReplicaSet | DELETED (cascaded) |
| Pods | 0 remaining |
| Verifier credentials (VM 401) | RECLAIMED (cleanup_verified=True) |
| RoleBinding | DELETED (namespace-scoped, cascaded) |
| ClusterRoleBinding | NONE created (design constraint upheld) |

---

## Constraint Compliance

| Constraint | Status |
|------------|--------|
| No LLM calls | PASS — LABGEN_LLM_PROVIDER_MODE=fake_only |
| No production VMID 500-599 | PASS — used VM 401 (staging) |
| No ClusterRoleBinding created | PASS — namespace-scoped RoleBinding only |
| Max 1 active session | PASS — exactly 1 session created and completed |
| Verifier kubeconfig not in logs/return values | PASS |
| No raw K8s exception to learner | PASS |
| No unpublished lab exposed | PASS |

---

## Student Catalog After Gate

| Lab | Status |
|-----|--------|
| Kubernetes Basics: Your Isolated Lab Environment | published |
| Kubernetes ConfigMap Basics | published |
| Kubernetes Secret Basics | published |
| **Kubernetes Deployment Basics** | **published (new)** |

---

## Decision

**DEPLOYMENT_LAB_READY**

All gate criteria met. Lab is live in student catalog. No issues requiring notes.
