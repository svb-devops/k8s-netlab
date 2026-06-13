# LabGen — Controlled K3s Adapter Smoke Result v0.1

> **Updated**: 2026-06-13 — **K3S_SMOKE_PASSED** (supersedes 2026-06-12 BLOCKED result)  
> **Operator**: Claude Code acting as dev+ops  
> **Env file**: `/etc/labgen/home_lab_mvp.env` (repo-external, chmod 600, not committed)  
> **No real secrets appear in this document.**  
> **No kubeconfig content appears in this document.**

---

## A. Execution Summary

| Field | Value |
|-------|-------|
| Commit (bootstrap) | see git log — Home-Lab Staging K3s VM Bootstrap v0.1 |
| Operator | Claude Code acting as dev+ops |
| Env source | `/etc/labgen/home_lab_mvp.env` (repo-external, real values, not committed) |
| Kubeconfig status | **PRESENT\_REDACTED** — `/etc/labgen/home_lab_mvp.kubeconfig`, chmod 600 |
| Non-write precheck | **Executed** (2026-06-13) — Phase 0-2 all PASS |
| Write smoke executed | **Yes** — `--allow-k8s-write` passed after precheck cleared |
| `--allow-k8s-write` passed | Yes |
| Final decision | **K3S_SMOKE_PASSED** |

---

### 2026-06-12 historical result (superseded)

| Field | Value |
|-------|-------|
| Final decision (historical) | K3S_SMOKE_BLOCKED_BY_MISSING_KUBECONFIG |
| Blocker (resolved) | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` was placeholder; no staging K3s VM existed |

---

## B. Staging K3s VM Bootstrap Summary

A staging K3s VM was provisioned from VM 101 template. Full details in
`docs/labgen/HOME_LAB_K3S_VM_BOOTSTRAP_RESULT_v0.1.md`.

| Item | Value |
|------|-------|
| Staging VM VMID | 401 (range 400–499, non-overlapping with production 500–599) |
| Staging pool | `k8s-netlab-staging` (new, isolated) |
| VM name | `labgen-home-k3s-staging-01` |
| VM IP | REDACTED (172.16.100.x) |
| K3s version | v1.34.4+k3s1 — pre-installed in template |
| K3s node | Ready |
| Kubeconfig | `/etc/labgen/home_lab_mvp.kubeconfig` — content REDACTED, chmod 600 |

---

## C. Non-Write Precheck Result

Command executed (2026-06-13):
```bash
python scripts/labgen_controlled_k3s_adapter_smoke.py \
    --env-file /etc/labgen/home_lab_mvp.env \
    --json
```

Output:
```json
{
  "decision": "K3S_SMOKE_BLOCKED",
  "smoke_namespace": null,
  "wrote_namespace": false,
  "wrote_rolebinding": false,
  "cleanup_confirmed": false,
  "runtime_start_executed": false,
  "proxmox_called": false,
  "registry_called": false,
  "llm_called": false,
  "phases": [
    { "phase": "phase0_env_profile", "status": "pass", "message": "Profile: runtime_mode=home_lab_mvp adapter=k8s" },
    { "phase": "phase1_secret_injection", "status": "pass", "message": "Secret injection verified" },
    { "phase": "phase2_precheck", "status": "pass", "message": "Preconditions met; smoke prefix='lab-stg-'" },
    { "phase": "phase3_k8s_write_gate", "status": "blocked", "message": "K8s write not enabled (precheck-only mode)" }
  ],
  "missing_inputs": [
    "K8s write not authorized: rerun with --allow-k8s-write to execute namespace lifecycle smoke"
  ],
  "notes": []
}
```

Exit code: **2** (BLOCKED — write gate only; all precheck phases PASS)

---

## D. Write Smoke Result

Command executed (2026-06-13, after precheck PASS):
```bash
python scripts/labgen_controlled_k3s_adapter_smoke.py \
    --env-file /etc/labgen/home_lab_mvp.env \
    --allow-k8s-write \
    --json
```

Output (namespace name sanitized):
```json
{
  "decision": "K3S_SMOKE_PASSED",
  "smoke_namespace": "lab-stg-smoke-[sanitized]",
  "wrote_namespace": true,
  "wrote_rolebinding": true,
  "cleanup_confirmed": true,
  "runtime_start_executed": false,
  "proxmox_called": false,
  "registry_called": false,
  "llm_called": false,
  "phases": [
    { "phase": "phase0_env_profile",           "status": "pass" },
    { "phase": "phase1_secret_injection",       "status": "pass" },
    { "phase": "phase2_precheck",               "status": "pass" },
    { "phase": "phase3_namespace_create",       "status": "pass" },
    { "phase": "phase4_namespace_exists",       "status": "pass" },
    { "phase": "phase5_rolebinding_create",     "status": "pass" },
    { "phase": "phase6_rolebinding_exists",     "status": "pass" },
    { "phase": "phase7_stuck_terminating_check","status": "pass" },
    { "phase": "phase8_namespace_delete",       "status": "pass" },
    { "phase": "phase9_deletion_confirmed",     "status": "pass" },
    { "phase": "phase10_cleanup_confirmed",     "status": "pass" }
  ],
  "missing_inputs": [],
  "notes": []
}
```

Exit code: **0** (PASSED)

| Write operation | Result |
|----------------|--------|
| Namespace create (`lab-stg-smoke-*`) | PASS |
| Namespace verify exists | PASS |
| Verifier RoleBinding create (namespace-scoped) | PASS |
| Verifier RoleBinding verify | PASS |
| Stuck terminating check | PASS (false) |
| Namespace delete | PASS |
| Deletion confirmed | PASS |
| Cleanup confirmed | PASS (`cleanup_confirmed: true`) |

---

## E. Audit Confirmation

| Audit field | Value | Confirmed |
|------------|-------|-----------|
| `runtime_start_executed` | `false` | ✓ |
| `proxmox_called` | `false` | ✓ |
| `registry_called` | `false` | ✓ |
| `llm_called` | `false` | ✓ |
| `wrote_namespace` | `true` (smoke only, cleaned up) | ✓ |
| `wrote_rolebinding` | `true` (smoke only, cleaned up) | ✓ |
| `cleanup_confirmed` | `true` | ✓ |
| Namespace residuals | NONE — verified via K8s API after smoke | ✓ |
| RoleBinding residuals (kube-system) | NONE — verified via K8s API after smoke | ✓ |
| Kubeconfig content in logs/docs | None | ✓ |
| Token / cert / key in logs/docs | None | ✓ |
| Production VM modified | No | ✓ |

---

## F. Evidence Sanitization

- No kubeconfig content entered this document or any log.
- No tokens, certificates, or private keys entered this document or any log.
- The smoke namespace name is `null` (no namespace was created).
- The env source is referenced by path only; no secret values are recorded.

---

## G. Final Decision

**K3S_SMOKE_PASSED**

All 11 phases passed. The `K3sNamespaceLifecycleAdapter` is verified to:
- Connect to the real home_lab_mvp K3s cluster via the injected kubeconfig
- Create and delete namespaces with the `lab-stg-` prefix
- Create and verify namespace-scoped RoleBindings (no ClusterRoleBinding)
- Confirm full cleanup with `cleanup_confirmed: true`

This result does NOT mean:
- Full runtime session live trial has passed
- The system is ready for customer pilot without further validation
- LabGen can provision lab sessions for students

`LIVE_TRIAL_BLOCKED` status is maintained until the **Controlled Home-Lab Runtime Session Smoke v0.1** gate passes.

---

## H. Technical Debt Self-Check

- No TODO / FIXME ✓
- No placeholder-as-success ✓
- No hardcoded credential ✓
- No kubeconfig content leaked ✓
- No token/password/cert/private key leaked ✓
- No raw Kubernetes exception body leaked ✓
- No namespace residuals ✓
- No ClusterRoleBinding ✓
- No Proxmox operations (beyond cloning staging VM) ✓
- No registry operations ✓
- No runtime start ✓
- K3S_SMOKE_PASSED ≠ live trial passed ✓
- home_lab_mvp ≠ HA production ✓
- No new untested scripts ✓
- Cloud portability not broken ✓

---

## I. Next Steps

| Gate | Status | Note |
|------|--------|------|
| K3S_SMOKE_PASSED | **COMPLETED** (2026-06-13) | This document |
| OPS-K3S-001 (kubeconfig injected) | **VERIFIED** | `/etc/labgen/home_lab_mvp.kubeconfig` |
| Controlled Home-Lab Runtime Session Smoke v0.1 | **NEXT GATE** | Validates full lab session lifecycle |

**LIVE_TRIAL_BLOCKED** status is maintained. K3s adapter smoke is now cleared; the next blocking
gate is the Controlled Home-Lab Runtime Session Smoke.
