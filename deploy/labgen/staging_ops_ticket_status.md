# LabGen MVP — Staging Ops Ticket Status Tracker

> **Purpose**: Track completion status of each ops provisioning ticket.  
> **Updated**: 2026-06-13 — ALL 6 tickets VERIFIED; Controlled Home-Lab Runtime Session Smoke PASSED_WITH_NOTES  
> **Current state**: ALL 6 ops tickets VERIFIED; Controlled Runtime Session Smoke PASSED_WITH_NOTES (see `docs/labgen/CONTROLLED_HOME_LAB_RUNTIME_SESSION_SMOKE_RESULT_v0.1.md`)  
> **Code blocker resolved**: `K3sNamespaceLifecycleAdapter` is fully implemented (commit `44cce73`). Remaining blockers are ops-side only.  
> **Ticket pack**: `docs/labgen/OPS_PROVISIONING_TICKET_PACK_v0.1.md`  
> **Execution result**: `docs/labgen/STAGING_OPS_TICKET_EXECUTION_RESULT_v0.1.md`  
> **No real secrets in this file** — use `<set-in-secret-manager>` or `<placeholder>` only.

---

## Instructions

1. Ops team updates this file as each ticket is completed.
2. Change `BLOCKED_WITH_EVIDENCE` → `IN_PROGRESS` when work starts.
3. Change `IN_PROGRESS` → `READY_FOR_VERIFY` when injection is complete.
4. Run the verification wrapper and record the result.
5. Change `READY_FOR_VERIFY` → `VERIFIED` when `labgen_ops_ticket_verify.py` reports `"status": "VERIFIED"`.
6. Once all 6 tickets are VERIFIED, run the full secret injection verification and intake gate.
7. Keep this file as provisioning evidence.

---

## Ticket Status Table

| Ticket ID | Title | Owner | Status | Env Key | Evidence Path | Last Verification Command | Last Decision | Notes |
|-----------|-------|-------|--------|---------|---------------|--------------------------|---------------|-------|
| OPS-K3S-001 | Provision staging K3s kubeconfig / SA | Infra / K8s Ops | **VERIFIED** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | `docs/labgen/CONTROLLED_K3S_ADAPTER_SMOKE_RESULT_v0.1.md` | smoke: `python scripts/labgen_controlled_k3s_adapter_smoke.py --env-file /etc/labgen/home_lab_mvp.env --allow-k8s-write --json` | **K3S_SMOKE_PASSED** (2026-06-13) | VM 401 (`labgen-home-k3s-staging-01`) provisioned; kubeconfig at `/etc/labgen/home_lab_mvp.kubeconfig` (chmod 600, not committed). K3s v1.34.4, node Ready. |
| OPS-AUTH-001 | Inject staging ADMIN_TOKEN | Security / Ops | **VERIFIED** | `ADMIN_TOKEN` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-AUTH-001 --json` | **VERIFIED** (2026-06-13) | Staging-specific ADMIN_TOKEN (64 hex chars) injected; ACCEPTED_MVP_RISK: stored in chmod 600 repo-external file (no external secret manager) |
| OPS-PROXMOX-001 | Configure staging PROXMOX_HOST | Infra / Proxmox Ops | **VERIFIED** | `PROXMOX_HOST` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-PROXMOX-001 --json` | **VERIFIED** (2026-06-13) | Same-Proxmox host (127.0.0.1); ACCEPTED_MVP_RISK (documented); Pool.Allocate ACL granted on k8s-netlab-staging |
| OPS-PROXMOX-002 | Inject staging PROXMOX_TOKEN_SECRET | Security / Proxmox Ops | **VERIFIED** | `PROXMOX_TOKEN_SECRET` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-PROXMOX-002 --json` | **VERIFIED** (2026-06-13) | Same token as production; ACCEPTED_MVP_RISK; scoped to staging pool k8s-netlab-staging |
| OPS-VM-001 | Inject staging VM SSH credential | Infra / VM Ops | **VERIFIED** | `VM_SSH_PASSWORD` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-VM-001 --json` | **VERIFIED** (2026-06-13) | Same VM_SSH_PASSWORD as production; ACCEPTED_MVP_RISK (same Proxmox) |
| OPS-REGISTRY-001 | Configure staging VM_REGISTRY_MIRROR | Infra / Registry Ops | **VERIFIED** | `VM_REGISTRY_MIRROR` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-REGISTRY-001 --json` | **VERIFIED** (2026-06-13) | Local registry mirror (production marker; ACCEPTED_MVP_RISK for staging — same-Proxmox host) |

**Status legend**: `TODO` → `IN_PROGRESS` → `READY_FOR_VERIFY` → `VERIFIED` | `BLOCKED_WITH_EVIDENCE`

---

## Verification Commands

Replace `<staging-env-file>` with the path to your `.env.staging` file.

```bash
# Verify a single ticket
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --ticket OPS-K3S-001 \
    --json

# Verify all tickets at once
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --all \
    --json

# Full secret injection verification (after all tickets VERIFIED)
python scripts/labgen_ops_secret_injection_verify.py \
    --env-file <staging-env-file> \
    --json
# Expected: "decision": "SECRET_INJECTION_READY"

# Intake gate (after SECRET_INJECTION_READY)
python scripts/labgen_ops_staging_intake_verify.py \
    --env-file <staging-env-file> \
    --base-url http://<staging-host>:8000 \
    --json
# Expected: "decision": "READY_TO_RERUN_CONTROLLED_STAGING_TRIAL"
```

---

## Current Gate State

| Gate | Status | Evidence |
|------|--------|----------|
| Staging infra bootstrap | `[ ]` NOT READY — STAGING_INFRA_BOOTSTRAP_BLOCKED | `docs/labgen/STAGING_INFRA_BOOTSTRAP_EXECUTION_RESULT_v0.1.md` |
| All 6 tickets VERIFIED | `[ ]` NOT READY — 6/6 BLOCKED_WITH_EVIDENCE | `docs/labgen/STAGING_OPS_TICKET_EXECUTION_RESULT_v0.1.md` |
| Secret injection: SECRET_INJECTION_READY | `[ ]` NOT READY | `docs/labgen/OPS_SECRET_INJECTION_VERIFICATION_RESULT_v0.1.md` — currently BLOCKED |
| Intake gate: READY_TO_RERUN | `[ ]` NOT READY | `docs/labgen/OPS_STAGING_INTAKE_VERIFICATION_RESULT_v0.1.md` — currently BLOCKED |
| **K3S Adapter Smoke: K3S_SMOKE_PASSED** | `[x]` **READY — K3S_SMOKE_PASSED** (2026-06-13) | `docs/labgen/CONTROLLED_K3S_ADAPTER_SMOKE_RESULT_v0.1.md` — VM 401 provisioned, all 11 phases PASS, cleanup_confirmed=true |
| Controlled Trial rerun: LIVE_TRIAL_PASSED | `[ ]` NOT READY | To be recorded after rerun |

**None of the above may be declared passed until the corresponding verification script outputs the READY/PASSED decision.**

---

## Unblock Path (concrete next actions for ops)

1. **Create real `.env.staging`** — do NOT copy from `.env.staging.example`. Use secret manager to inject real values.
2. For each ticket below, perform the infra action and inject the real value:

| Ticket | Required Action |
|--------|----------------|
| OPS-K3S-001 | Provision staging K3s cluster; write kubeconfig to absolute path; set `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<abs-path>` |
| OPS-AUTH-001 | Generate ≥32-char random token; set `ADMIN_TOKEN=<token>` |
| OPS-PROXMOX-001 | Set `PROXMOX_HOST=<real-staging-proxmox-hostname-or-IP>` |
| OPS-PROXMOX-002 | Create staging Proxmox API token; set `PROXMOX_TOKEN_SECRET=<uuid>` |
| OPS-VM-001 | Set `VM_SSH_PASSWORD=<real-credential>` |
| OPS-REGISTRY-001 | Deploy staging registry; push required images; set `VM_REGISTRY_MIRROR=http://<host>:<port>` |

3. Run per-ticket verification: `python scripts/labgen_ops_ticket_verify.py --env-file .env.staging --ticket <ID> --json`
4. When all 6 show `"status": "VERIFIED"`, run: `python scripts/labgen_ops_ticket_verify.py --env-file .env.staging --all --json`
5. Then proceed to secret injection verify → intake gate → controlled trial rerun.

---

## Dependency Graph

```
OPS-K3S-001 ─────────────────────────────────────────────┐
OPS-AUTH-001 ────────────────────────────────────────────┤
OPS-PROXMOX-001 ─────────────────────────────────────────┤
OPS-PROXMOX-002 ─────────────────────────────────────────┤──▶ All VERIFIED
OPS-VM-001 ──────────────────────────────────────────────┤        │
OPS-REGISTRY-001 ────────────────────────────────────────┘        │
                                                                   ▼
                                              SECRET_INJECTION_READY
                                                                   │
                                                                   ▼
                                       READY_TO_RERUN_CONTROLLED_STAGING_TRIAL
                                                                   │
                                                                   ▼
                                               Controlled Staging Trial Live Run
```

---

*No real secrets appear in this file.  
All example values use `<placeholder>` or `<set-in-secret-manager>` format.  
Ops updates this file in-place as each ticket progresses.*
