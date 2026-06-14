# LabGen MVP — Home-Lab MVP Staging Profile v0.1

> **Status**: PROFILE DEFINITION — not a deployment record  
> **Date**: 2026-06-12  
> **Commit basis**: `44cce73` (Portable K3s Namespace Lifecycle Adapter v0.1)  
> **No real provisioning is performed in this document.**  
> **No real secrets appear in this document.**

---

## A. Scope

### What this profile IS

The `home_lab_mvp` profile defines how to run LabGen on a single Proxmox host (T430) for
small-cohort customer pilot testing.

- Deployment target: Dell T430 / Proxmox VE, single physical host.
- Use case: small-cohort customer testing (initial pilot, ≤ 10 concurrent students).
- Same physical host may serve both staging and production, with explicit isolation boundaries.
- Portability maintained: namespace lifecycle runs via Kubernetes API only, no Proxmox coupling.

### What this profile IS NOT

| Excluded | Reason |
|---------|--------|
| HA / multi-node Proxmox | Single server, single point of failure — accepted risk |
| Enterprise SLA | No uptime guarantee beyond best-effort |
| Large-scale rollout | CPU (1.8 GHz Xeon, 20 threads) bottlenecks at > 3 concurrent K3s VMs |
| Cloud production | This profile is for home-lab hardware only |
| Cloud-equivalent isolation | Same-host staging/prod has weaker isolation than cloud — explicitly accepted |
| Production-grade secret manager | Local `.env` injection acceptable at MVP scale |

### Accepted scope

- Same-physical-host staging is acceptable at MVP with explicit risk acknowledgement
  (see Section F).
- Small-cohort customer testing is acceptable on this profile.
- Future migration to AWS EKS / Alibaba ACK is supported by design (see Section E).
- `home_lab_mvp` and `cloud` use the same `K3sNamespaceLifecycleAdapter` implementation — no
  code changes required for cloud migration.

---

## B. Hardware Reality

| Property | Value | Impact |
|----------|-------|--------|
| CPU | Xeon E5-2630L v4, 20 threads, 1.8 GHz (low-voltage) | Primary concurrency bottleneck |
| RAM | 78 GB | Sufficient; not a bottleneck at MVP scale |
| Storage | root 94 GB / LVM-thin 1.7 TB | Sufficient |
| Network | Cloudflare Tunnel (ingress), home ISP | No exposed ports; ISP dependency accepted |
| Power | Home electricity | Single power source; outage accepted |
| Cooling | Home environment | No data-centre cooling; heat throttling possible |
| VM state | No running VMs currently (zero student load) | Clean baseline |

### Proxmox single-host reality

- One physical Proxmox node `pve`.
- Production pool: `k8s-netlab`, VMID range 500–599, template VM 101.
- Staging pool: must be created as `k8s-netlab-staging` with **non-overlapping** VMID range.
- Template VM 101 (`k8s-template`) is **production-only** — staging requires a separate template VM.
- Cloudflare Tunnel is the ingress layer — not part of runtime core.
- Registry mirror `registry:2` at `172.16.100.1:5000` is production-scoped —
  staging must use a separate registry or registry path prefix.

---

## C. Same-Proxmox Isolation Model

Using the same physical Proxmox host for both staging and production is acceptable at MVP with
the following isolation requirements. All isolation boundaries must be enforced before the first
staged customer interaction.

### Required isolation boundaries

| Isolation Dimension | Staging Value | Production Value | Required? |
|--------------------|--------------|-----------------|-----------|
| Proxmox pool | `k8s-netlab-staging` | `k8s-netlab` | **YES** |
| VMID range | Must not overlap 500–599 | 500–599 | **YES** |
| VM template | Separate staging template (not VM 101) | VM 101 | **YES** |
| K8s namespace prefix | `lab-stg-` (or current `lab-` on isolated K3s) | `lab-` | **YES** — if same K3s |
| Verifier credential root | `/var/lib/labgen-staging/verifier-credentials` | `/var/lib/labgen/verifier-credentials` | **YES** |
| Audit storage path | `data-staging/` (separate directory) | `data/` | **YES** |
| Registry path prefix | `staging/` prefix or separate registry port | Production registry | **YES** |
| Env file / secret source | `.env.staging` (gitignored, separate from `.env`) | `.env` | **YES** |
| Admin token | Separate staging admin token | Production admin token | **YES** |
| Service port | 8001 (staging) or run as separate service unit | 8000 (production) | **YES** |
| Proxmox token | `labgen-staging@pve!labgen-staging-api` | `labgen@pve!labgen-api` | **YES** |

### K3s / namespace isolation options

**Option A: Same K3s cluster with staging namespace prefix**

- All staging lab namespaces use `lab-stg-<session-id>` prefix.
- `LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES=lab-stg-` for staging.
- `LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES=lab-` for production.
- Risk: shared K3s cluster; staging workloads visible in same cluster.
- Acceptable for MVP if student workloads are non-sensitive.

**Option B: Separate K3s node (recommended if spare VMs available)**

- Deploy a dedicated staging K3s VM (separate from production K3s VMs).
- Staging `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` points to staging K3s kubeconfig.
- Full namespace-level isolation.
- Preferred if a spare VMID in the staging range is available.

### ACCEPTED_MVP_RISK: network isolation

Current environment may not support a separate bridge / VLAN for staging VMs.
Using the same `vmbr1` bridge with production VMs is an **ACCEPTED_MVP_RISK**.
This must be documented explicitly and not misrepresented as full network isolation.

```
ACCEPTED_MVP_RISK: staging and production VMs may share vmbr1 bridge.
Network-layer isolation is weaker than a dedicated VLAN.
Acceptable for MVP pilot; must be remediated before enterprise rollout.
```

---

## D. Resource Limits

The following limits are **required** in the staging env file to prevent accidental VM sprawl
on the single-host T430. Staging limits must be stricter than production.

| Config Key | MVP Staging Default | Production Default | Rationale |
|-----------|--------------------|--------------------|-----------|
| `MAX_VMS_PER_USER` | `1` | `1` | One VM per student at any time |
| `MAX_TOTAL_VMS` | `3` | `12` | Hard cap: 3 concurrent staging VMs max |
| `LABGEN_LAB_SESSION_TTL_MINUTES` | `30` | `30` | 30-minute labs; adjust per curriculum |
| `VM_CORES` | `2` | `2` | 2 vCPUs per VM |
| `VM_MEMORY_MB` | `4096` | `4096` | 4 GB per VM |

### CPU concurrency constraint

With 20 threads at 1.8 GHz, the T430 can realistically support:
- **3 simultaneous K3s VMs** (each uses ~6–8 threads under load) without significant degradation.
- **5 VMs** at idle (low student activity).

Initial customer pilot: recommend `MAX_TOTAL_VMS=3` and `MAX_VMS_PER_USER=1`.

### Emergency kill switch

If CPU load exceeds threshold during a live session, the operator can:
```bash
# List running VMs in staging pool
pvesh get /pools/k8s-netlab-staging --output-format json | jq '.members'

# Hard-stop a specific VM (VMID must be from staging range)
qm stop <staging-vmid>

# Abort a lab session via admin API
curl -X POST http://localhost:8001/api/lab-sessions/<session-id>/abort \
  -H "X-Admin-Token: <staging-admin-token>"
```

When CPU reaches > 85% average over 5 minutes: manually abort the oldest session.
No automatic kill switch exists in v0.1 — this is an ACCEPTED_MVP_RISK.

---

## E. Portability Boundary

These rules are **non-negotiable** regardless of profile. Violating them creates lock-in
that will require a rewrite to migrate to cloud.

| Rule | Enforcement |
|------|-------------|
| Namespace lifecycle via Kubernetes API only | `K3sNamespaceLifecycleAdapter` has no Proxmox imports |
| VM provider (Proxmox) is isolated to VM creation path only | `backend/proxmox_api.py` — not called by namespace adapter |
| Image registry is config-driven (env var) | `VM_REGISTRY_MIRROR` — no hardcoded registry host in core |
| Cloudflare Tunnel is ingress-only | Not referenced in `backend/labgen/` or `backend/vm_manager.py` |
| Secrets injectable via any secret manager | `.env` file, Vault, Doppler, CI/CD env — all equivalent |
| No T430-specific paths in LabGen core | Verified by `test_namespace_lifecycle_portability.py` |
| `LABGEN_RUNTIME_MODE=home_lab_mvp` → same code as `cloud` | Only profile + config differ; adapter code is identical |
| `home_lab_mvp` must not be described as HA production | This document explicitly states non-HA |

### Migration path to cloud

When the exit criteria in Section G are met, migration requires:

1. Replace `LABGEN_RUNTIME_MODE=home_lab_mvp` with `LABGEN_RUNTIME_MODE=cloud`.
2. Set `LABGEN_K8S_IN_CLUSTER=true` OR `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<eks-kubeconfig>`.
3. Replace `PROXMOX_*` env vars with cloud VM provider config.
4. Replace `VM_REGISTRY_MIRROR` with ECR / ACR / GCR endpoint.
5. Replace local `.env` injection with cloud secret manager.
6. No changes to `backend/labgen/` namespace lifecycle or session state machine.

---

## F. Accepted MVP Risks

The following risks are **explicitly accepted** at the home_lab_mvp stage. They must NOT be
misrepresented as resolved or as cloud-equivalent.

| Risk ID | Risk | Mitigation | Accepted? |
|---------|------|-----------|-----------|
| RISK-01 | Single point of failure (T430 hardware) | Manual monitoring; no auto-recovery | **ACCEPTED** |
| RISK-02 | Home ISP uptime (~99% typical) | Session TTL-based cleanup on restart | **ACCEPTED** |
| RISK-03 | Power outage / electricity | No UPS; planned downtime acceptable | **ACCEPTED** |
| RISK-04 | CPU concurrency bottleneck | Hard VM cap (MAX_TOTAL_VMS=3) | **ACCEPTED** |
| RISK-05 | Same-host staging/prod isolation weaker than cloud | Separate pool/VMID/token/namespace/creds | **ACCEPTED** |
| RISK-06 | No HA — single Proxmox node | Non-HA is explicit non-goal | **ACCEPTED** |
| RISK-07 | Local `.env` file secrets (no HSM) | File permissions 600; not committed | **ACCEPTED** |
| RISK-08 | Network-layer isolation via same vmbr1 bridge | Accepted for pilot; VLAN preferred long-term | **ACCEPTED** |
| RISK-09 | Manual emergency kill switch only | Operator on-call during pilot sessions | **ACCEPTED** |
| RISK-10 | No automatic session expiry daemon | `POST /api/labgen/runtime/expire-sessions` must be run manually or via cron | **ACCEPTED** |

**Any risk above must be explicitly re-evaluated** if:
- Customer count grows past 10 concurrent users.
- Any customer data classified above "public demo material" is processed.
- SLA commitments are made to customers.

---

## G. Exit Criteria to Cloud Migration

The `home_lab_mvp` profile must be replaced with a `cloud` profile when ANY of the following
thresholds is reached:

| Trigger | Threshold |
|---------|----------|
| Active students | > 50 enrolled, or > 10 concurrent sessions during peak |
| Concurrent K3s sessions | > 5 during normal operation |
| SLA requirement | Any commitment to > 95% availability |
| Home network instability | > 3 unplanned outages per month affecting students |
| Enterprise customer onboarding | Any customer requiring SOC 2, ISO 27001, or equivalent |
| Data residency requirement | Any customer requiring data to stay in a specific geography |
| Multi-region requirement | Any requirement for geographical redundancy |
| Secret management requirement | Any requirement for HSM or audit-trail on secret access |
| Registry uptime requirement | Any requirement for registry HA (currently local `registry:2`) |

When any trigger fires:
1. Create new staging environment on EKS / ACK.
2. Switch `LABGEN_RUNTIME_MODE=cloud` and validate with same test suite.
3. Replace VM provider adapter (Proxmox → cloud provider).
4. Migrate secrets to cloud secret manager.
5. Run controlled staging trial on cloud profile.
6. Cut over; decommission T430 or reassign to dev-only.

---

## H. Config Keys Required for home_lab_mvp

All values below use placeholders. Inject real values via secret manager at runtime.

### Runtime and adapter

```bash
LABGEN_RUNTIME_MODE=home_lab_mvp          # Required — enables production-safe checks
LABGEN_NAMESPACE_ADAPTER=k8s              # Required — stub is forbidden in this mode
LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<abs-path-to-staging-kubeconfig>  # Required — from OPS-K3S-001
LABGEN_K8S_IN_CLUSTER=false               # Required — not running inside K8s
LABGEN_K8S_CONTEXT=                       # Optional — leave empty to use default context
LABGEN_K8S_API_TIMEOUT_SECONDS=10         # Optional — default 10s
LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES=lab-stg-   # Required — staging prefix; prevents lab- collision
LABGEN_K8S_VERIFIER_SA_NAME=labgen-verifier       # Optional — default
LABGEN_K8S_VERIFIER_SA_NAMESPACE=kube-system      # Optional — default
LABGEN_K8S_VERIFIER_ROLE_NAME=labgen-verifier-role  # Optional — default
LABGEN_K8S_VERIFIER_ROLEBINDING_NAME=labgen-verifier-binding  # Optional — default
```

### Proxmox / VM (staging-isolated values)

```bash
PROXMOX_HOST=<staging-proxmox-host>        # Use production host ONLY if staging pool is isolated
PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api
# PROXMOX_TOKEN_SECRET=<set-in-secret-manager>
# VM_SSH_PASSWORD=<set-in-secret-manager>
VM_TEMPLATE_ID=<staging-template-vmid>    # NOT 101; staging-specific template
VM_ID_MIN=<staging-vm-id-min>             # Must not overlap 500–599
VM_ID_MAX=<staging-vm-id-max>             # Must not overlap 500–599
PROXMOX_POOL=k8s-netlab-staging           # Dedicated staging pool
VM_REGISTRY_MIRROR=http://<staging-host>:<staging-registry-port>
VM_BRIDGE=vmbr1                           # Accepted if VLAN not available (RISK-08)
```

### Resource limits

```bash
MAX_VMS_PER_USER=1
MAX_TOTAL_VMS=3         # Hard cap for T430 CPU headroom
LABGEN_LAB_SESSION_TTL_MINUTES=30
VM_CORES=2
VM_MEMORY_MB=4096
```

### Auth and storage

```bash
# ADMIN_TOKEN=<set-in-secret-manager>     # Staging-specific token
LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials
SESSION_COOKIE_SECURE=false               # Acceptable if staging has no TLS
```

---

## I. Verification Commands (after secrets injected)

Run after all secrets are injected into `.env.staging`. No runtime start required for static checks.

```bash
# Static provisioning validation (no network calls)
python scripts/labgen_staging_provisioning_validate.py \
    --env-file deploy/labgen/.env.staging --json

# Profile guardrail validation (pure config, no network calls)
python scripts/labgen_production_preflight.py

# Adapter selection dry-run (pure config check)
python -c "
from backend.labgen.runtime_adapter_selection import RuntimeAdapterSelectionService
import os
os.environ['LABGEN_RUNTIME_MODE'] = 'home_lab_mvp'
os.environ['LABGEN_NAMESPACE_ADAPTER'] = 'k8s'
os.environ['LABGEN_K8S_PLATFORM_KUBECONFIG_PATH'] = '/path/to/kubeconfig'
r = RuntimeAdapterSelectionService.create_from_config()
print('production_safe:', r.production_safe)
print('issues:', r.issues)
"
```

The above static checks verify that:
- `home_lab_mvp` profile refuses stub adapter (blocking issue if stub set).
- Missing kubeconfig path is a blocking issue.
- `production_safe=True` only when all conditions are met.

---

## I-A. Ops Runbook

For operational procedures (verifier initialization, VM recovery, pilot session management,
emergency stop, cloud portability), see:

> **`docs/labgen/HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md`** (Ops Runbook Hardening v0.1, 2026-06-14)

Key ops constraint captured in runbook:
- For home_lab_mvp, verifier initialization MUST use `initialize_verifier_for_vm_host_side`.
- The QEMU-agent path (`initialize_verifier_for_vm`) creates kubeconfig with `127.0.0.1:6443`
  (VM-local, unreachable from Proxmox host) and is **forbidden** for this profile.

---

## J. Unblock Path (concrete next actions for ops)

Current state: LIVE_TRIAL_BLOCKED (no real `.env.staging`; no real staging secrets).
K3sNamespaceLifecycleAdapter is **fully implemented** (not a skeleton) as of commit `44cce73`.
K3s adapter smoke result (2026-06-12): **K3S_SMOKE_BLOCKED_BY_MISSING_KUBECONFIG** — all kubeconfig
locations searched on this host; none found; staging K3s VM (clone of VM 101) must be provisioned
before smoke can reach the write phase. See `docs/labgen/CONTROLLED_K3S_ADAPTER_SMOKE_RESULT_v0.1.md`.

The remaining blockers are all ops-side:

| # | Action | Ticket |
|---|--------|--------|
| 1 | Create `k8s-netlab-staging` pool in Proxmox (`pvesh create /pools --poolid k8s-netlab-staging`) | Pre-OPS |
| 2 | Allocate staging VMID range (e.g. 550–599; non-overlapping with 500–549 production range) | Pre-OPS |
| 3 | Clone staging VM template from VM 101 into staging pool | Pre-OPS |
| 4 | Provision staging K3s kubeconfig / SA | OPS-K3S-001 |
| 5 | Inject `ADMIN_TOKEN` | OPS-AUTH-001 |
| 6 | Confirm `PROXMOX_HOST` (may reuse production host if staging pool is isolated) | OPS-PROXMOX-001 |
| 7 | Inject `PROXMOX_TOKEN_SECRET` (staging-scoped token) | OPS-PROXMOX-002 |
| 8 | Inject `VM_SSH_PASSWORD` | OPS-VM-001 |
| 9 | Deploy staging registry (new port on same host, e.g. 5002) or confirm reuse path | OPS-REGISTRY-001 |
| 10 | Create real `.env.home_lab` or `.env.staging` — DO NOT copy `.env.staging.example`; use secret manager | Operator |
| 11 | Run K3s adapter smoke precheck: `python scripts/labgen_controlled_k3s_adapter_smoke.py --env-file .env.home_lab` | Operator |
| 12 | With operator authorization, run smoke write phase: `python scripts/labgen_controlled_k3s_adapter_smoke.py --env-file .env.home_lab --allow-k8s-write --json` | Operator |
| 13 | Confirm K3S_SMOKE_PASSED or K3S_SMOKE_PASSED_WITH_NOTES and cleanup_confirmed=true | Operator |
| 14 | Run `labgen_staging_missing_inputs.py` → exit 0 | Operator |
| 15 | Run `labgen_ops_staging_intake_verify.py` → `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL` | Operator |
| 16 | Rerun controlled staging trial | Operator |

**Steps 1–3 can be done by ops on the production Proxmox host without any production risk**,
since they only create new pools/VMs in the staging range.

---

*This document defines the home-lab MVP staging profile for LabGen.  
No real K3s, Proxmox, or registry connections are made by this document.  
No real secrets appear in this document.  
K3sNamespaceLifecycleAdapter is fully implemented as of commit `44cce73` — the adapter is ready.*
