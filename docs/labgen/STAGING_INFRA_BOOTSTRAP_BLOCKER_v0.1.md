# LabGen MVP — Staging Infra Bootstrap Blocker v0.1

> **Final Decision: STAGING_INFRA_BOOTSTRAP_BLOCKED**

---

## A. Final Decision

**STAGING_INFRA_BOOTSTRAP_BLOCKED**

Claude Code acting as dev+ops attempted to bootstrap the real staging infrastructure  
required to advance 6 ops tickets from BLOCKED_WITH_EVIDENCE to VERIFIED.  
The current execution environment does not possess the real infra access,  
secret manager access, or isolated staging resources required to proceed.  
No fake secrets were created. No production environment was used as staging.

---

## B. Operator

**Claude Code acting as dev+ops**  
Commit at time of attempt: `10e3ca7`  
Date / Time (UTC): `2026-06-12T07:50:56Z`

---

## C. Reason

The current execution environment (Proxmox host `pve`, project `/root/k8s-netlab`) is the  
**production** environment for k8s-netlab. There is no separate, isolated staging host,  
staging Proxmox pool, staging K3s cluster, staging registry, or secret manager available.

Using the production environment as staging would violate the contract constraint  
"不使用 production 环境作为 staging" and risks VMID conflicts (range 500-599 is already  
the live production range for k8s-netlab).

---

## D. Missing Required Access

| Access Item | Required For Ticket | Required Capability | Current Status | Blocking Effect | Minimum Unblock Action |
|-------------|--------------------|--------------------|---------------|----------------|----------------------|
| Staging host or cluster admin access | All 6 tickets | A separate host or cluster isolated from production pve | **NOT AVAILABLE** — current host IS production pve | Cannot create any staging resource without risking production contamination | Provision a dedicated staging host (VM, cloud instance, or separate Proxmox node) OR create an isolated staging Proxmox pool + VMID range that does not overlap production |
| K3s install / kubeconfig generation permission | OPS-K3S-001 | `kubectl` available, ability to install/access K3s cluster | **NOT AVAILABLE** — `kubectl` not installed; no `~/.kube/` directory; no K3s cluster exists | Cannot provision staging kubeconfig or SA for labgen verifier | Install K3s on staging host; generate scoped kubeconfig; write to absolute path; inject via secret manager |
| Proxmox staging pool admin or scoped token | OPS-PROXMOX-001, OPS-PROXMOX-002 | Staging-only Proxmox pool (`k8s-netlab-staging`); token scoped to staging pool | **NOT AVAILABLE** — existing pools are `k8s-netlab` (production), `containerlab`, `opsreplay`; VMID range 500-599 is production | Cannot create staging VMs without conflicting with production VMID range | Create `k8s-netlab-staging` Proxmox pool with non-overlapping VMID range; issue scoped token; set staging `PROXMOX_HOST` |
| Internal registry create/push/pull permission | OPS-REGISTRY-001 | Dedicated staging registry container, isolated from production `registry-mirror` (172.16.100.1:5000) | **NOT AVAILABLE** — existing registries are production (`registry-mirror`, `registry-custom`, `clab-registry`); reusing production registry is not staging-isolated | Cannot configure staging `VM_REGISTRY_MIRROR` without a staging-specific registry | Deploy a separate staging `registry:2` container on staging host at a staging-specific port; push required images; set `VM_REGISTRY_MIRROR=http://<staging-host>:<port>` |
| Secret manager write/read permission | OPS-AUTH-001, OPS-PROXMOX-002, OPS-VM-001 | A secret manager (Vault, Doppler, AWS Secrets Manager, etc.) or secure env injection mechanism | **NOT AVAILABLE** — no `vault`, `op`, `aws`, `doppler` CLIs found; no secret manager running | Cannot securely inject `ADMIN_TOKEN`, `PROXMOX_TOKEN_SECRET`, `VM_SSH_PASSWORD` without committing them | Set up a secret manager or provide a secure env injection script that reads from a secrets store outside the repo |
| Persistent storage mount permission | K3sNamespaceLifecycleAdapter (runtime) | `LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials` writable, chmod 700 | **NOT AVAILABLE** — directory does not exist; no staging-dedicated storage mount defined | Cannot store verifier credentials for staging lab sessions | Create `/var/lib/labgen-staging/verifier-credentials` on staging host with correct permissions; confirm storage isolation from production `/var/lib/labgen/` |
| DNS / TLS / staging base URL configuration | Intake gate (READY_TO_RERUN) | A staging-accessible base URL for `labgen_ops_staging_intake_verify.py --base-url` | **NOT AVAILABLE** — no staging base URL; production URL is `https://lab.cloudnetops.tech` | Intake gate `--base-url` check cannot run | Assign staging base URL (e.g., `http://<staging-host>:8000`); configure DNS or hosts entry; confirm staging service is reachable |
| Admin token issuance permission | OPS-AUTH-001 | Mechanism to generate a cryptographically random ≥32-char token without committing it | **NOT AVAILABLE** — no secret manager to receive the generated token | Cannot inject `ADMIN_TOKEN` into `.env.staging` without printing or committing it | Use secret manager to generate and store token; inject at runtime via environment |
| VM credential injection permission | OPS-VM-001 | Mechanism to set `VM_SSH_PASSWORD` on staging VM template and inject same value into `.env.staging` | **NOT AVAILABLE** — staging VM template does not exist; no secret manager for injection | Cannot configure staging VM SSH access | Provision staging VM template with SSH credential; inject matching `VM_SSH_PASSWORD` via secret manager |

---

## E. Why No Further Dev Work Should Proceed

- **Existing code and tooling are ready**: 2835 tests pass, 94.08% coverage, all gates implemented.
- **Current blocker is external infra access**: The code is complete. The block is environment and credentials, not engineering.
- **Adding more helpers or docs would be low-value process debt**: Every additional helper script that cannot run against real staging is a maintenance burden with zero near-term utility.
- **The next real unblock is granting infra access**: Only a human operator with access to staging infrastructure can move this forward.

**The correct action is to escalate to a platform manager or infra team, not to produce more tooling.**

---

## F. Exact Unblock Request

The following items must be provided by a human operator with access to real infrastructure.  
**No production secrets may be used. All values must be staging-specific.**

```
Required from platform manager / infra team:

1. PROVIDE staging host or K3s cluster
   → Either a dedicated staging VM, cloud instance, or separate Proxmox node.
   → OR an isolated Proxmox pool (k8s-netlab-staging) with non-overlapping VMID range.

2. PROVIDE scoped staging kubeconfig path via secret manager
   → K3s cluster with namespace-scoped service account for labgen.
   → Kubeconfig written to absolute path on staging host.
   → Path injected as LABGEN_K8S_PLATFORM_KUBECONFIG_PATH via secret manager.

3. PROVIDE staging Proxmox host and scoped token
   → PROXMOX_HOST = staging Proxmox hostname or IP (NOT pve / production).
   → PROXMOX_TOKEN_SECRET = staging-scoped API token UUID (NOT production token).
   → Both injected via secret manager.

4. PROVIDE staging registry mirror endpoint
   → Deploy registry:2 container at a staging-specific host:port.
   → Push required images: nginx, busybox, alpine, curl.
   → Set VM_REGISTRY_MIRROR=http://<staging-host>:<port> (NOT 172.16.100.1:5000).

5. PROVIDE VM SSH credential mechanism
   → Set staging VM template SSH password.
   → Inject matching credential as VM_SSH_PASSWORD via secret manager.

6. PROVIDE ADMIN_TOKEN
   → Generate cryptographically random string (≥ 32 characters).
   → Store in secret manager.
   → Inject as ADMIN_TOKEN at staging service startup (NOT written to repo).

7. PROVIDE persistent storage mount on staging host
   → /var/lib/labgen-staging/verifier-credentials (chmod 700, owned by service user).
   → Isolated from production /var/lib/labgen/.

8. PROVIDE staging base URL
   → hostname or IP where staging k8s-netlab service will be accessible.
   → Used for intake gate: --base-url http://<staging-host>:8000.

9. CONFIRM no production secrets are used
   → All values above must be staging-specific, not copied from .env or production config.
```

---

## G. Commands to Rerun After Unblock

Once all access items in section F are provided, ops must run in this order:

```bash
# 1. Verify all 6 tickets (requires real .env.staging)
python scripts/labgen_ops_ticket_verify.py \
    --env-file .env.staging \
    --all --json
# Expected: "all_verified": true

# 2. Secret injection verify
python scripts/labgen_ops_secret_injection_verify.py \
    --env-file .env.staging \
    --json
# Expected: "decision": "SECRET_INJECTION_READY"

# 3. Intake gate (offline)
python scripts/labgen_ops_staging_intake_verify.py \
    --env-file .env.staging \
    --json

# 4. Intake gate (with staging base-url, after staging service is running)
python scripts/labgen_ops_staging_intake_verify.py \
    --env-file .env.staging \
    --base-url http://<staging-host>:8000 \
    --admin-token <from-secret-manager> \
    --json
# Expected: "decision": "READY_TO_RERUN_CONTROLLED_STAGING_TRIAL"
```

Track progress: `deploy/labgen/staging_ops_ticket_status.md`

---

*No real secrets were printed or committed in the production of this document.  
All access item descriptions reference key names only, not values.  
This is the correct and expected outcome when real staging infra has not been provisioned.*
