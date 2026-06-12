# LabGen — Controlled K3s Adapter Smoke Result v0.1

> **Generated**: 2026-06-12  
> **Operator**: Claude Code acting as dev+ops  
> **Commit basis**: `87e0297` (Controlled K3s Adapter Smoke v0.1)  
> **No real secrets appear in this document.**  
> **No kubeconfig content appears in this document.**

---

## A. Execution Summary

| Field | Value |
|-------|-------|
| Commit | `87e0297` |
| Operator | Claude Code acting as dev+ops |
| Env source | `deploy/labgen/.env.staging.example` (path reference only; no secrets) |
| Kubeconfig status | **MISSING** — `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` not set (commented out in example file) |
| Non-write precheck | **Executed** (2026-06-12) |
| Write smoke executed | **No** — blocked before write gate |
| `--allow-k8s-write` passed | No |
| Final decision | **K3S_SMOKE_BLOCKED_BY_MISSING_KUBECONFIG** |

---

## B. Kubeconfig Search Result (ops-side investigation)

Claude Code checked all standard locations on this Proxmox host for a real K3s kubeconfig:

| Location checked | Result |
|-----------------|--------|
| `/root/.kube/` | Not found (directory does not exist) |
| `/etc/kubernetes/` | Not found |
| `/etc/rancher/` | Not found |
| `/etc/k3s/` | Not found |
| `/etc/labgen/` | Not found |
| `find /root /home -name kubeconfig -o -name "*.kubeconfig" -o -name "k3s.yaml"` | No results |
| K3s binary (`which k3s`) | Not found |
| Running K3s systemd service | None found |
| Running K3s VMs (VMID 500-599) | None running |
| VM 101 (`k8s-template`) | **Proxmox template** (`template: 1`) — cannot be started directly |

**Conclusion**: No real K3s kubeconfig is accessible on this host. VM 101 is the production K3s
template; it is a Proxmox template (cannot be started) and is explicitly marked production-only
in `HOME_LAB_MVP_STAGING_PROFILE_v0.1.md`. Using its kubeconfig as a home_lab_mvp staging
kubeconfig would violate isolation requirements.

---

## C. Non-Write Precheck Result

Command executed:
```bash
python scripts/labgen_controlled_k3s_adapter_smoke.py \
    --env-file deploy/labgen/.env.staging.example \
    --json
```

Output (2026-06-12):
```json
{
  "decision": "K3S_SMOKE_BLOCKED_BY_MISSING_KUBECONFIG",
  "smoke_namespace": null,
  "wrote_namespace": false,
  "wrote_rolebinding": false,
  "cleanup_confirmed": false,
  "runtime_start_executed": false,
  "proxmox_called": false,
  "registry_called": false,
  "llm_called": false,
  "phases": [
    { "phase": "phase0_env_profile", "status": "blocked", "message": "Profile validation failed" },
    { "phase": "phase1_secret_injection", "status": "pass", "message": "Secret injection verified" },
    { "phase": "phase2_precheck", "status": "blocked", "message": "Blocked: 1 precondition(s) not met" }
  ],
  "missing_inputs": [
    "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is not set or is a placeholder — inject the real kubeconfig path"
  ],
  "notes": []
}
```

Exit code: **2** (BLOCKED)

---

## D. Write Smoke Result

**Not executed.** The write smoke (`--allow-k8s-write`) was not run because precheck returned
`K3S_SMOKE_BLOCKED_BY_MISSING_KUBECONFIG`. Write gate requires all precheck conditions to pass.

| Write operation | Result |
|----------------|--------|
| Namespace create | Not executed |
| Namespace verify exists | Not executed |
| Verifier RoleBinding create | Not executed |
| Verifier RoleBinding verify | Not executed |
| Namespace delete (cleanup) | Not executed |
| Cleanup confirmed | N/A |

---

## E. Audit Confirmation

All of the following are confirmed false (no operations performed):

| Audit field | Value | Confirmed |
|------------|-------|-----------|
| `runtime_start_executed` | `false` | ✓ |
| `proxmox_called` | `false` | ✓ |
| `registry_called` | `false` | ✓ |
| `llm_called` | `false` | ✓ |
| `wrote_namespace` | `false` | ✓ |
| `wrote_rolebinding` | `false` | ✓ |
| `cleanup_confirmed` | `false` (N/A — nothing to clean) | ✓ |
| Namespace residuals | None (no writes performed) | ✓ |
| Kubeconfig content in logs/docs | None | ✓ |
| Token / cert / key in logs/docs | None | ✓ |

---

## F. Evidence Sanitization

- No kubeconfig content entered this document or any log.
- No tokens, certificates, or private keys entered this document or any log.
- The smoke namespace name is `null` (no namespace was created).
- The env source is referenced by path only; no secret values are recorded.

---

## G. Final Decision

**K3S_SMOKE_BLOCKED_BY_MISSING_KUBECONFIG**

The sole blocker is the missing platform kubeconfig:
- `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` is not set (commented out in `.env.staging.example`)
- No real K3s kubeconfig is available on this host (all locations searched — none found)
- VM 101 (`k8s-template`) is a Proxmox template; it cannot be started and is production-only
- Creating a staging K3s VM requires ops-side infrastructure provisioning (out of scope for this task)

This result does NOT mean:
- K3S_SMOKE_FAILED (the adapter is not broken — it was not called)
- live trial has failed (LIVE_TRIAL_BLOCKED remains for unrelated reasons)
- production is not ready

---

## H. Unblock Path

To unblock and reach `K3S_SMOKE_PASSED`:

1. **Provision a staging K3s node** (ops-side):
   - Clone VM 101 to a staging VMID (e.g., outside 500–599 range)
   - Assign clone to `k8s-netlab-staging` pool
   - Start the clone VM
   - Wait for K3s to be ready (`kubectl get nodes`)

2. **Export kubeconfig from the staging K3s VM** (ops-side):
   - SSH into the staging VM
   - Copy `/etc/rancher/k3s/k3s.yaml` to an external path, e.g. `/etc/labgen/home_lab_mvp.kubeconfig`
   - Update server URL if needed (replace `127.0.0.1` with VM IP)
   - Set permissions: `chmod 600 /etc/labgen/home_lab_mvp.kubeconfig`
   - Do NOT commit the kubeconfig to git

3. **Create repo-external env file**:
   - Copy `deploy/labgen/.env.staging.example` to `/etc/labgen/home_lab_mvp.env` (outside repo)
   - Set `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/etc/labgen/home_lab_mvp.kubeconfig`
   - Set all other required values (ADMIN_TOKEN, PROXMOX_*, VM_SSH_PASSWORD, etc.)
   - Set permissions: `chmod 600 /etc/labgen/home_lab_mvp.env`

4. **Re-run non-write precheck**:
   ```bash
   python scripts/labgen_controlled_k3s_adapter_smoke.py \
       --env-file /etc/labgen/home_lab_mvp.env \
       --json
   ```
   Expected: all phases `pass`, decision changes from `BLOCKED` to `BLOCKED` (write gate)

5. **With explicit operator authorization, run write smoke**:
   ```bash
   python scripts/labgen_controlled_k3s_adapter_smoke.py \
       --env-file /etc/labgen/home_lab_mvp.env \
       --allow-k8s-write \
       --json
   ```
   Expected decision: `K3S_SMOKE_PASSED` or `K3S_SMOKE_PASSED_WITH_NOTES`
   Expected: `cleanup_confirmed: true`, exit code 0

6. **Record the result** in this document (replace Section C, D, E with actual output).

---

## I. Technical Debt Self-Check

- No TODO / FIXME ✓
- No placeholder-as-success ✓
- No hardcoded credential ✓
- No kubeconfig content leaked ✓
- No token/password/cert/private key leaked ✓
- No raw Kubernetes exception body leaked ✓
- No namespace residuals ✓
- No ClusterRoleBinding ✓
- No Proxmox operations ✓
- No registry operations ✓
- No runtime start ✓
- K3S_SMOKE_BLOCKED_BY_MISSING_KUBECONFIG ≠ K3S_SMOKE_FAILED ✓
- K3S_SMOKE_BLOCKED_BY_MISSING_KUBECONFIG ≠ live trial passed ✓
- home_lab_mvp ≠ HA production ✓
- No new untested scripts ✓
- No new low-value helpers ✓
- Cloud portability not broken ✓

---

## J. Next Steps

| Gate | Condition | Owner |
|------|-----------|-------|
| K3S_SMOKE_PASSED | Staging K3s VM provisioned + kubeconfig injected + write smoke executed | Ops |
| OPS-K3S-001 VERIFIED | After K3S_SMOKE_PASSED | Ops |
| Controlled Home-Lab Runtime Session Smoke | After K3S_SMOKE_PASSED | Dev (after ops unblocks) |

**LIVE_TRIAL_BLOCKED** status is unchanged. K3s adapter smoke is a prerequisite gate for
the controlled staging trial rerun, but not the only gate (see `staging_ops_ticket_status.md`).
