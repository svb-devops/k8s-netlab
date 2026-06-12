# LabGen MVP — Ops Provisioning Ticket Pack v0.1

> **Status**: SECRET_INJECTION_BLOCKED / LIVE_TRIAL_BLOCKED (2026-06-12)  
> **Updated**: 2026-06-12 — K3sNamespaceLifecycleAdapter fully implemented (commit `44cce73`); same-Proxmox acceptable  
> **Commit**: `d8f80d0` (ops ticket pack) / `44cce73` (K3s adapter)  
> **Purpose**: Actionable ops provisioning tickets for the 6 missing staging inputs.  
> Ops executes each ticket individually, verifies with the wrapper, then re-runs the injection verification and intake gate.  
> **This document does NOT perform real provisioning — no K3s/Proxmox/registry connections are made here.**

---

## A. Current Blocked State

### Summary

| Field | Value |
|-------|-------|
| Commit | `d8f80d0` |
| Secret injection decision | **SECRET_INJECTION_BLOCKED** |
| Live trial decision | **LIVE_TRIAL_BLOCKED** |
| Real staging `.env.staging` | **Not present** |
| Intake gate rerun | **NOT PERMITTED** |
| Runtime started | **NO** |
| K3s connected | **NO** |
| Proxmox connected | **NO** |
| Registry connected | **NO** |

### Why blocked

The Controlled Staging Trial Live Run (2026-06-12) executed correctly and **fail-closed** as designed.
All tooling ran without errors. The blocking outcome is expected — it means the staging environment
has not been provisioned. The tooling does not fake success.

**Secret injection verification result**: `docs/labgen/OPS_SECRET_INJECTION_VERIFICATION_RESULT_v0.1.md`
→ 6 of 7 required keys are PLACEHOLDER; 1 (PROXMOX_TOKEN_ID) is PRESENT_REDACTED.

### Blocked is fail-closed, not a bug

The staging tools exit non-zero when staging infrastructure is absent.
They do not connect to production, do not print secret values, and do not fake a READY decision.
`SECRET_INJECTION_BLOCKED` = expected outcome until ops injects all 6 secrets.

### Current 6 missing inputs

| # | Config Key | Category | Ticket |
|---|-----------|----------|--------|
| 1 | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | K3s / Kubernetes | OPS-K3S-001 |
| 2 | `ADMIN_TOKEN` | Auth / Admin | OPS-AUTH-001 |
| 3 | `PROXMOX_HOST` | Proxmox | OPS-PROXMOX-001 |
| 4 | `PROXMOX_TOKEN_SECRET` | Proxmox | OPS-PROXMOX-002 |
| 5 | `VM_SSH_PASSWORD` | VM Access | OPS-VM-001 |
| 6 | `VM_REGISTRY_MIRROR` | Image Registry | OPS-REGISTRY-001 |

---

## B. Ticket Overview

| Ticket ID | Title | Owner Role | Env Key(s) | Blocks | Validation Command | Status |
|-----------|-------|------------|-----------|--------|--------------------|--------|
| OPS-K3S-001 | Provision staging K3s kubeconfig / SA | Infra / K8s Ops | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Lab session start | `labgen_ops_ticket_verify.py --ticket OPS-K3S-001` | TODO |
| OPS-AUTH-001 | Inject staging ADMIN_TOKEN | Security / Ops | `ADMIN_TOKEN` | Admin diagnostics | `labgen_ops_ticket_verify.py --ticket OPS-AUTH-001` | TODO |
| OPS-PROXMOX-001 | Configure staging PROXMOX_HOST | Infra / Proxmox Ops | `PROXMOX_HOST` | Proxmox API calls | `labgen_ops_ticket_verify.py --ticket OPS-PROXMOX-001` | TODO |
| OPS-PROXMOX-002 | Inject staging PROXMOX_TOKEN_SECRET | Security / Proxmox Ops | `PROXMOX_TOKEN_SECRET` | Proxmox authentication | `labgen_ops_ticket_verify.py --ticket OPS-PROXMOX-002` | TODO |
| OPS-VM-001 | Inject staging VM SSH credential | Infra / VM Ops | `VM_SSH_PASSWORD` | K3s config via SSH | `labgen_ops_ticket_verify.py --ticket OPS-VM-001` | TODO |
| OPS-REGISTRY-001 | Configure staging VM_REGISTRY_MIRROR | Infra / Registry Ops | `VM_REGISTRY_MIRROR` | Image pull in lab sessions | `labgen_ops_ticket_verify.py --ticket OPS-REGISTRY-001` | TODO |

**All 6 tickets must reach VERIFIED before re-running the secret injection verification and intake gate.**

---

## C. Per-Ticket Details

---

### OPS-K3S-001 — Provision staging K3s kubeconfig / service account

#### Purpose

**[CODE BLOCKER RESOLVED]** `K3sNamespaceLifecycleAdapter` is fully implemented as of commit `44cce73`.
The adapter now has working implementations of all 7 `NamespaceLifecyclePort` methods — no more
`NotImplementedError` skeleton. The remaining blocker for this ticket is **kubeconfig injection only**.

Provision a staging K3s cluster (or use same-K3s-as-production with staging namespace prefix),
create a minimum-privilege service account, and inject the absolute path to the staging kubeconfig
into `.env.staging`. LabGen uses this kubeconfig to create and delete lab namespaces.
Without it, lab sessions cannot start.

**Same-K3s option**: If a dedicated staging K3s VM is not available, the same K3s cluster
used by production can be reused, provided:
- `LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES=lab-stg-` in staging env.
- `LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES=lab-` in production env.
- Staging service account is scoped to `lab-stg-*` namespaces only.

#### Required input

```
LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<absolute-path-to-staging-kubeconfig>
```

Example placeholder (replace before running):
```
LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-secret-manager>
```

#### Source of truth

- Staging K3s cluster provisioned by Ops.
- Kubeconfig generated from a dedicated service account (not admin kubeconfig).
- Stored in secret manager; path injected into `.env.staging`.

#### Injection mechanism

1. Provision staging K3s cluster (dedicated, not shared with production).
2. Create service account and ClusterRole with namespace create/delete + rolebinding permissions.
3. Generate kubeconfig for the service account.
4. Store kubeconfig file at a secure path (e.g. `/etc/labgen/staging/kubeconfig`). Permissions: `chmod 600`.
5. Inject the **absolute path** into secret manager.
6. Secret manager writes the path to `.env.staging`:
   ```
   LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<absolute-path>
   ```

#### Security requirements

- Kubeconfig content must **never** be committed to the repository.
- Kubeconfig content must **never** appear in logs or script output.
- Service account must be **minimum privilege** (only namespace lifecycle operations).
- Namespace prefix must restrict scope to staging (e.g. `lab-*` in staging cluster only).
- Kubeconfig must point to staging cluster — never production cluster.

#### Validation command

```bash
# Step 1: verify key is present and non-placeholder (offline)
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --ticket OPS-K3S-001 \
    --json
# Expected: "status": "VERIFIED"

# Step 2: verify kubeconfig path is accessible (if cluster is live)
kubectl version --kubeconfig <staging-kubeconfig-path>
# Expected: Client and Server version output
```

#### Expected pass result

- `labgen_ops_ticket_verify.py` reports `"status": "VERIFIED"` for OPS-K3S-001.
- `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` shows `PRESENT_REDACTED` in secret injection check.

#### Fail conditions

- Key is absent, empty, or contains `<...>` placeholder → BLOCKED.
- Kubeconfig path points to non-existent file at runtime.
- Service account lacks required RBAC permissions.
- Kubeconfig points to production cluster (abort criterion).

#### Rollback / revoke procedure

1. Delete the staging K3s service account: `kubectl delete sa <name> -n <ns>`.
2. Delete the ClusterRoleBinding: `kubectl delete clusterrolebinding <name>`.
3. Remove the kubeconfig file.
4. Remove `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` from secret manager and `.env.staging`.

#### Evidence to attach

- Cluster endpoint (no credentials).
- Service account name.
- ClusterRole name.
- Result of `labgen_ops_ticket_verify.py --ticket OPS-K3S-001 --json`.

#### Notes

- Do **not** use the admin kubeconfig — use a dedicated SA kubeconfig.
- Namespace prefix should be `lab-<uuid>` (LabGen generates the UUID internally).
- This ticket is a prerequisite for K3sNamespaceLifecycleAdapter integration tests.

---

### OPS-AUTH-001 — Inject staging ADMIN_TOKEN

#### Purpose

Generate a staging-only admin token and inject it into `.env.staging`.
The token is used for admin-only API endpoints (diagnostics, dry run, adapter status).
Without it, the intake gate cannot verify admin endpoint accessibility.

#### Required input

```
ADMIN_TOKEN=<set-in-secret-manager>
```

Requirement: value must be **>= 32 characters** of random entropy.

#### Source of truth

- Generated by Ops from a secure random source.
- Stored in secret manager.
- **Never** the production admin token.

#### Injection mechanism

1. Generate a >= 32-character random string:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Store in secret manager.
3. Secret manager writes to `.env.staging`:
   ```
   ADMIN_TOKEN=<set-in-secret-manager>
   ```

#### Security requirements

- Token must **never** appear in logs, script output, or committed files.
- Token must be staging-specific — **never** reuse the production admin token.
- Length check: value must be >= 32 characters (format check in injection verify).
- Only admin-level operators may access admin diagnostics endpoints using this token.

#### Validation command

```bash
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --ticket OPS-AUTH-001 \
    --json
# Expected: "status": "VERIFIED"
```

#### Expected pass result

- `labgen_ops_ticket_verify.py` reports `"status": "VERIFIED"` for OPS-AUTH-001.
- `ADMIN_TOKEN` shows `PRESENT_REDACTED` and passes length >= 32 check.

#### Fail conditions

- Key is absent, empty, placeholder, or < 32 characters → BLOCKED.
- Production token accidentally reused → abort and rotate.

#### Rollback / revoke procedure

1. Remove `ADMIN_TOKEN` from secret manager.
2. Remove from `.env.staging`.
3. Rotate if accidentally exposed in logs.

#### Evidence to attach

- Confirmation that token was generated (no value, just length confirmation).
- Result of `labgen_ops_ticket_verify.py --ticket OPS-AUTH-001 --json`.

#### Notes

- `echo ${#ADMIN_TOKEN}` → must print >= 32.
- Intake gate uses this token to probe admin-only HTTP endpoints.

---

### OPS-PROXMOX-001 — Configure staging PROXMOX_HOST

#### Purpose

Set the staging Proxmox API hostname in `.env.staging`.
LabGen uses this to construct API URLs for VM clone/create/delete operations.
Without a real non-placeholder value, all Proxmox API calls fail.

#### Required input

```
PROXMOX_HOST=<staging-host>
```

Replace `<staging-host>` with the real staging Proxmox hostname or IP (staging-only, not production).

#### Source of truth

- Staging Proxmox host provisioned by Ops.
- Hostname or IP recorded in secret manager / infrastructure registry.

#### Injection mechanism

1. Identify the staging Proxmox host address.
2. Record in secret manager or infrastructure configuration.
3. Set in `.env.staging`:
   ```
   PROXMOX_HOST=<staging-proxmox-host>
   ```

#### Security requirements

- Must be the **staging** Proxmox host — **never** the production host.
- Hostname/IP must not appear in committed files (set only in `.env.staging`, which is gitignored).
- Host value must not contain `<...>` placeholder tokens.

#### Validation command

```bash
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --ticket OPS-PROXMOX-001 \
    --json
# Expected: "status": "VERIFIED"
```

#### Expected pass result

- `labgen_ops_ticket_verify.py` reports `"status": "VERIFIED"` for OPS-PROXMOX-001.
- `PROXMOX_HOST` shows `PRESENT_REDACTED` in secret injection check.

#### Fail conditions

- Key absent, empty, or still `<staging-host>` placeholder → BLOCKED.
- Production Proxmox host accidentally set → abort criterion.

#### Rollback / revoke procedure

1. Remove `PROXMOX_HOST` from `.env.staging`.
2. Staging Proxmox access is controlled by Proxmox API token (OPS-PROXMOX-002), not this key.

#### Evidence to attach

- Confirmation that host is staging-only (no real hostname in this document).
- Result of `labgen_ops_ticket_verify.py --ticket OPS-PROXMOX-001 --json`.

#### Notes

- PROXMOX_TOKEN_ID is already PRESENT_REDACTED in the current env example.
- PROXMOX_HOST is the hostname only — no port, no protocol prefix.

---

### OPS-PROXMOX-002 — Inject staging PROXMOX_TOKEN_SECRET

#### Purpose

Create a staging-only Proxmox API token and inject the UUID secret into `.env.staging`.
The token authenticates all Proxmox API calls (VM clone, status, delete).
Without it, VM provisioning is blocked even if PROXMOX_HOST is set.

#### Required input

```
PROXMOX_TOKEN_SECRET=<set-in-secret-manager>
```

Value is a UUID-format string issued by Proxmox when the API token is created.

#### Source of truth

- Generated via Proxmox GUI or API when creating a staging API token.
- Stored in secret manager.
- **Never** the production Proxmox token secret.

#### Injection mechanism

1. In Proxmox GUI: Datacenter → Permissions → API Tokens → Add.
   - User: staging service account.
   - Token name: `labgen-staging` (or similar).
   - Disable expiry for trial period (or set appropriate TTL).
2. Copy the generated UUID-format secret.
3. Store in secret manager immediately (Proxmox shows the secret only once).
4. Secret manager writes to `.env.staging`:
   ```
   PROXMOX_TOKEN_SECRET=<set-in-secret-manager>
   ```

#### Security requirements

- Token secret must **never** appear in logs, output, or committed files.
- Token must be staging-specific — never reuse production token secret.
- Token must have minimum privileges: `VM.Clone`, `VM.Allocate`, `VM.Config.*` on staging pool only.
- Secret verification output shows only `PRESENT_REDACTED` — never the value.

#### Validation command

```bash
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --ticket OPS-PROXMOX-002 \
    --json
# Expected: "status": "VERIFIED"
```

#### Expected pass result

- `labgen_ops_ticket_verify.py` reports `"status": "VERIFIED"` for OPS-PROXMOX-002.
- `PROXMOX_TOKEN_SECRET` shows `PRESENT_REDACTED` in secret injection check.

#### Fail conditions

- Key absent, empty, or placeholder → BLOCKED.
- Token permissions insufficient at runtime.
- Production token accidentally used → abort and rotate.

#### Rollback / revoke procedure

1. Delete the staging API token in Proxmox GUI.
2. Remove `PROXMOX_TOKEN_SECRET` from secret manager and `.env.staging`.
3. If accidentally exposed: revoke token immediately, generate new one.

#### Evidence to attach

- Proxmox token ID (not the secret): e.g. `staging-user@pve!labgen-staging`.
- Proxmox permission grant confirmation.
- Result of `labgen_ops_ticket_verify.py --ticket OPS-PROXMOX-002 --json`.

#### Notes

- PROXMOX_TOKEN_ID is already set (`PRESENT_REDACTED`). This ticket covers only the secret.
- Proxmox token format: `<tokenid>=<uuid>` in the `Authorization` header — LabGen handles assembly.

---

### OPS-VM-001 — Inject staging VM SSH credential

#### Purpose

Inject the staging VM SSH credential into `.env.staging`.
LabGen uses this to connect to newly cloned VMs via SSH to configure K3s
(hostname, registry mirror, etcd cleanup). Without it, K3s configuration fails
after VM clone.

#### Required input

```
VM_SSH_PASSWORD=<set-in-secret-manager>
```

Or, if SSH key authentication is used instead, add a note — but `VM_SSH_PASSWORD` must still
contain a non-placeholder value that LabGen can pass to the SSH client.

#### Source of truth

- Set when the staging VM template is configured.
- Stored in secret manager.
- **Never** the production VM SSH credential.

#### Injection mechanism

1. Configure the staging VM template with a staging-specific SSH credential.
2. Store the credential in secret manager.
3. Secret manager writes to `.env.staging`:
   ```
   VM_SSH_PASSWORD=<set-in-secret-manager>
   ```

#### Security requirements

- Credential must **never** appear in logs, output, or committed files.
- Credential must be staging-specific — never reuse production VM credential.
- If SSH key is used: inject key path, not private key content. Never commit private key.
- Must support VM reclaim and timeout cleanup trial (VM SSH access required for cleanup).

#### Validation command

```bash
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --ticket OPS-VM-001 \
    --json
# Expected: "status": "VERIFIED"
```

#### Expected pass result

- `labgen_ops_ticket_verify.py` reports `"status": "VERIFIED"` for OPS-VM-001.
- `VM_SSH_PASSWORD` shows `PRESENT_REDACTED` in secret injection check.

#### Fail conditions

- Key absent, empty, or placeholder → BLOCKED.
- SSH credential incorrect at runtime → K3s configuration fails.
- Production credential accidentally used → abort and rotate.

#### Rollback / revoke procedure

1. Change the staging VM template SSH credential.
2. Remove `VM_SSH_PASSWORD` from secret manager and `.env.staging`.
3. Revoke old credential at template level.

#### Evidence to attach

- Confirmation that credential is staging-specific (no value in this document).
- Result of `labgen_ops_ticket_verify.py --ticket OPS-VM-001 --json`.

#### Notes

- `VM_SSH_PASSWORD` is used by `reset_k3s_via_agent` after VM clone.
- For fresh VMs (age < 5 min), SSH is used to reset hostname and configure registry mirror.
- VM timeout / reclaim also requires SSH access — credential must be stable for trial duration.

---

### OPS-REGISTRY-001 — Configure staging VM_REGISTRY_MIRROR

#### Purpose

Deploy a staging internal image registry and inject its URL into `.env.staging`.
LabGen configures cloned VMs to pull images from this registry mirror.
Without it, image pull fails in lab namespace initialization.

#### Required input

```
VM_REGISTRY_MIRROR=http://<staging-host>:5000
```

Replace `<staging-host>:5000` with the real staging registry address.
Value must start with `http://` or `https://`.

#### Source of truth

- Staging registry deployed by Ops.
- Registry URL recorded in secret manager / infrastructure registry.

#### Injection mechanism

1. Deploy a container registry at a staging-only host and port (e.g. `docker.io/library/registry:2`).
2. Push all required images:
   - `nginx:1.25-alpine`
   - `busybox:1.36`
   - `alpine:3.18`
   - `curlimages/curl:8.5.0`
3. Verify reachability from backend host: `curl http://<staging-host>:5000/v2/`.
4. Set in `.env.staging`:
   ```
   VM_REGISTRY_MIRROR=http://<staging-host>:5000
   ```

#### Security requirements

- Registry must be **staging-isolated** — not shared with production.
- Registry credentials (if auth enabled) must not appear in committed files.
- The `BLOCKED`, `UNRESOLVED`, and `NOT_FOUND` test scenarios must be expressible
  (registry returns 404 for unknown images → `NOT_FOUND`).
- Value must not contain `<...>` placeholder tokens.

#### Validation command

```bash
# Step 1: static key check (offline)
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --ticket OPS-REGISTRY-001 \
    --json
# Expected: "status": "VERIFIED"

# Step 2: registry connectivity check (if registry is live)
curl http://<staging-host>:5000/v2/
# Expected: {} or 200 OK

# Step 3: verify required images are present
curl http://<staging-host>:5000/v2/nginx/tags/list
curl http://<staging-host>:5000/v2/busybox/tags/list
curl http://<staging-host>:5000/v2/alpine/tags/list
curl http://<staging-host>:5000/v2/curlimages/curl/tags/list
```

#### Expected pass result

- `labgen_ops_ticket_verify.py` reports `"status": "VERIFIED"` for OPS-REGISTRY-001.
- `VM_REGISTRY_MIRROR` shows `PRESENT_REDACTED` in secret injection check.
- Registry responds with tag lists for all 4 required images.

#### Fail conditions

- Key absent, empty, placeholder, or missing `http://`/`https://` prefix → BLOCKED.
- Registry unreachable from backend host at runtime.
- Required images not pushed to registry.
- Registry auth not configured when backend expects auth.

#### Rollback / revoke procedure

1. Stop the staging registry container.
2. Remove `VM_REGISTRY_MIRROR` from `.env.staging`.
3. Registry data can be discarded after the trial.

#### Evidence to attach

- Registry host (no credentials): e.g. `staging.registry.example:5000`.
- Tag list responses for all 4 required images.
- Result of `labgen_ops_ticket_verify.py --ticket OPS-REGISTRY-001 --json`.

#### Notes

- Registry must run `docker.io/library/registry:2` or equivalent.
- `config/image_whitelist.json` maps canonical image refs to the internal registry — update if host changes.
- `VM_REGISTRY_MIRROR` must be reachable from **inside the staging VMs**, not just from the backend host.

---

## D. Ticket Execution Sequence

Complete tickets in any order, but verify each one before proceeding to the full gate.

```
[OPS-K3S-001]     Provision K3s kubeconfig → inject path
[OPS-AUTH-001]    Generate and inject ADMIN_TOKEN
[OPS-PROXMOX-001] Set PROXMOX_HOST (staging-only)
[OPS-PROXMOX-002] Create and inject PROXMOX_TOKEN_SECRET
[OPS-VM-001]      Inject VM SSH credential
[OPS-REGISTRY-001] Deploy registry and inject VM_REGISTRY_MIRROR
         ↓
  Run ticket pack verification wrapper (all tickets)
         ↓
  Re-run secret injection verification → SECRET_INJECTION_READY
         ↓
  Re-run Ops Staging Intake Gate → READY_TO_RERUN_CONTROLLED_STAGING_TRIAL
         ↓
  Re-run Controlled Staging Trial Live Run
```

---

## E. Ticket Pack Verification

After completing all tickets, run the verification wrapper to confirm all are VERIFIED:

```bash
# 1. Verify all 6 tickets at once (offline, no network)
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --all \
    --json
# All tickets must show "status": "VERIFIED"
# "summary.all_verified": true

# 2. Re-run full secret injection verification
python scripts/labgen_ops_secret_injection_verify.py \
    --env-file <staging-env-file> \
    --json
# Must show "decision": "SECRET_INJECTION_READY"

# 3. Re-run intake verification gate (with real staging base URL)
python scripts/labgen_ops_staging_intake_verify.py \
    --env-file <staging-env-file> \
    --base-url http://<staging-host>:8000 \
    --json
# Must show "decision": "READY_TO_RERUN_CONTROLLED_STAGING_TRIAL"
```

Only when step 3 outputs `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL` may the
Controlled Staging Trial Live Run be re-executed.

---

## F. Security Assertions

All examples in this document use `<placeholder>` format.
No real API keys, tokens, kubeconfig content, credentials, or production IPs
appear anywhere in this document.

| Assertion | Status |
|-----------|--------|
| No real API key in this document | PASS |
| No real token value in this document | PASS |
| No kubeconfig content in this document | PASS |
| No real private key in this document | PASS |
| No real registry credential in this document | PASS |
| No real Proxmox credential in this document | PASS |
| No production internal IP in this document | PASS |
| No production namespace in this document | PASS |
| Ticket status declared TODO (not VERIFIED) | PASS |
| No live trial declared as passed | PASS |

---

*Ticket execution and verification are performed by ops. Dev tooling is complete.  
No code changes are required — all verification scripts are ready.*
