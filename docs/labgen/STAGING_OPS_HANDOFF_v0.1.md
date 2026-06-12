# LabGen MVP — Staging Ops Handoff Package v0.1

> **Status**: HANDOFF PACKAGE — for ops team to provision staging environment  
> **Commit**: `96fdac9`  
> **Live trial decision**: LIVE_TRIAL_BLOCKED (first attempt 2026-06-12)  
> **Live run result**: `docs/labgen/CONTROLLED_STAGING_TRIAL_LIVE_RUN_RESULT_v0.1.md`  
> **This document is NOT a deployment record — no real provisioning is performed here**

---

## A. Current Status

### What happened

The first controlled staging live run was executed on 2026-06-12 at commit `96fdac9`.
All tooling ran correctly and **fail-closed** as designed — no fake success was produced.

**Final decision: LIVE\_TRIAL\_BLOCKED**

This is the **expected and correct outcome** when the staging environment has not been provisioned.
It is not a code failure. The tooling behaved exactly as specified:

> If the staging infrastructure is not available, the scripts exit non-zero and report
> blocking inputs. They do not fake success, do not connect to real infrastructure,
> and do not print secret values.

### What is currently blocking the live trial

| # | Blocking Input | Config Key | Responsible |
|---|---------------|------------|-------------|
| F-1 | Staging K3s cluster not provisioned | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Ops |
| F-2 | K3s kubeconfig not injected | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Ops |
| F-3 | Admin token not set | `ADMIN_TOKEN` | Ops |
| F-4 | Proxmox staging credentials not set | `PROXMOX_TOKEN_SECRET` | Ops |
| F-5 | VM SSH password not set | `VM_SSH_PASSWORD` | Ops |
| F-6 | Staging image registry not provisioned | `VM_REGISTRY_MIRROR` | Ops |
| F-7 | Staging storage mount not confirmed | `data/` writable, audit log path | Ops |

See [Section D](#d-required-secrets-inventory) for full secrets inventory.

### Reference documents

| Document | Path |
|----------|------|
| Live run result (LIVE_TRIAL_BLOCKED) | `docs/labgen/CONTROLLED_STAGING_TRIAL_LIVE_RUN_RESULT_v0.1.md` |
| Staging environment provisioning plan | `docs/labgen/STAGING_ENVIRONMENT_PROVISIONING_v0.1.md` |
| Infrastructure checklist (fillable) | `deploy/labgen/staging_infrastructure_checklist.md` |
| **Ops provisioning ticket pack** | **`docs/labgen/OPS_PROVISIONING_TICKET_PACK_v0.1.md`** |
| Ticket status tracker | `deploy/labgen/staging_ops_ticket_status.md` |
| Missing inputs helper (quick check) | `scripts/labgen_staging_missing_inputs.py` |
| Staging env template | `deploy/labgen/.env.staging.example` |
| Controlled staging trial runbook | `docs/labgen/CONTROLLED_STAGING_TRIAL_v0.1.md` |

---

## B. What Dev Has Delivered

All tooling is complete, tested, and ready. No further dev work is required before ops provisions
the staging environment.

### Scripts (all fail-closed, no network calls unless noted)

| Script | Purpose | Tests |
|--------|---------|-------|
| `scripts/labgen_ops_staging_intake_verify.py` | **Unified intake gate** — calls all helpers in sequence, produces single READY/BLOCKED decision. No network calls in offline mode. | 34 tests pass |
| `scripts/labgen_ops_secret_injection_verify.py` | **Per-key secret injection verifier** — classifies each of 7 required keys (PRESENT_REDACTED/MISSING/PLACEHOLDER/EMPTY/INVALID_FORMAT). Offline. | 52 tests pass |
| `scripts/labgen_ops_ticket_verify.py` | **Ops ticket verification wrapper** — per-ticket VERIFIED/BLOCKED status for each of 6 provisioning tickets. Offline. | 66 tests pass |
| `scripts/labgen_staging_provisioning_validate.py` | Static env file validator — checks safety of `.env.staging` before any runtime action. No network calls. | 82 tests pass |
| `scripts/labgen_production_preflight.py` | Runtime config preflight — checks all required secrets are set. No network calls in offline mode. | 48 tests pass |
| `scripts/labgen_staging_dry_run.py` | Live service diagnostics — safe GET probes only, no destructive calls. Requires running backend. | 51 tests pass |
| `scripts/labgen_controlled_staging_trial.py` | Full trial orchestrator — phases gated behind explicit allow flags. Runtime phases require preflight PASS. | 61 tests pass |
| `scripts/labgen_staging_missing_inputs.py` | Ops-facing missing inputs helper — reports which keys are missing or placeholder, grouped by category. No network calls. | 65 tests pass |

### Artifacts

| Artifact | Description |
|----------|-------------|
| `docs/labgen/STAGING_ENVIRONMENT_PROVISIONING_v0.1.md` | Full provisioning plan — what infrastructure, config, and secrets must exist |
| `deploy/labgen/staging_infrastructure_checklist.md` | Fillable checklist — Phase 0–7, 44 items, with validation commands |
| `deploy/labgen/.env.staging.example` | Staging env template — all values are placeholders or staging-safe defaults |
| `docs/labgen/CONTROLLED_STAGING_TRIAL_LIVE_RUN_RESULT_v0.1.md` | First live run result artifact — LIVE_TRIAL_BLOCKED, unblock checklist in Section F |

### Fail-closed guarantees (all scripts)

- No fake success: if a blocking check fails, the script exits with code 1.
- No secret values printed: scripts report key names and presence/absence only.
- No network calls during static checks: provisioning validator, preflight, and missing inputs helper never connect to K3s, Proxmox, or registry.
- No production interference: scripts do not touch production config, production K3s, or production secrets.

---

## C. What Ops Must Provide

The following items must be provisioned and injected before the live trial can proceed.
None of these are created by dev tooling — they must be provided by the ops team via
secret manager or direct infra provisioning.

### Infrastructure

| Item | Notes |
|------|-------|
| Staging K3s cluster | Dedicated staging-only cluster, not shared with production |
| K3s RBAC: service account + ClusterRole | Namespace create/delete + rolebinding create/delete permissions |
| Staging Proxmox pool and VM template | Not production pool; VMID range must not overlap 500–599 |
| Staging Proxmox API token | Staging-specific token with `VM.Clone`, `VM.Allocate`, `VM.Config.*` on staging pool |
| Internal image registry | Registry at `<staging-registry-host>:5000`; required images pushed |
| Persistent storage mount | `data/` directory writable by service user; local filesystem (flock requires local FS) |
| Verifier credential root | Directory with `chmod 700`; staging-only; not under `/tmp` |
| Audit log storage | `data/lab_audit_events.json` path writable |
| Staging base URL, TLS (optional), DNS | Required for dry run and trial HTTP probes |
| Rollback access | Ability to delete staging namespaces, VMs, and credentials after trial |

### Required images (push to staging registry)

| Image | Source |
|-------|--------|
| `nginx:1.25-alpine` | Docker Hub |
| `busybox:1.36` | Docker Hub |
| `alpine:3.18` | Docker Hub |
| `curlimages/curl:8.5.0` | Docker Hub |

### Secrets (all via secret manager — never in plaintext files)

See [Section D](#d-required-secrets-inventory) for full inventory with injection mechanism and validation commands.

---

## D. Required Secrets Inventory

All secrets must be injected via secret manager into the `.env.staging` file (gitignored).
**No secret value must ever appear in logs, output, or committed files.**
All examples below use `<placeholder>` format.

| Secret Name | Env/Config Key | Required for Phase | Owner | Source of Truth | Injection Mechanism | Validation Command | Must Not Appear in Logs | Status |
|-------------|---------------|-------------------|-------|----------------|---------------------|--------------------|------------------------|--------|
| K3s platform kubeconfig | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Phase 1 (K3s) + all lab sessions | Ops | Staging K3s cluster | Secret manager → absolute file path | `kubectl cluster-info --kubeconfig <path>` | YES — kubeconfig content must never be printed | MISSING |
| Admin token | `ADMIN_TOKEN` | Phase 6 validation + admin endpoints | Ops | Secret manager | Inject as env var | `echo ${#ADMIN_TOKEN}` → ≥ 32 | YES | MISSING |
| Proxmox token secret | `PROXMOX_TOKEN_SECRET` | Phase 4 (Proxmox) + VM creation | Ops | Proxmox GUI or secret manager | Secret manager | Proxmox API connection test | YES | MISSING |
| VM SSH password | `VM_SSH_PASSWORD` | Phase 4 (VM SSH) + K3s reset | Ops | Secret manager | Inject as env var | SSH connectivity test | YES | MISSING |
| Registry credential | (if auth required) | Phase 3 (registry) | Ops | Registry config | Docker config or env | `curl http://<staging-registry>:5000/v2/` | YES (if used) | Conditional |
| Session signing secret | `SECRET_KEY` (if set) | Auth cookies | Ops | Secret manager | Inject as env var | Service startup | YES | Optional |
| LLM API key | `LABGEN_LLM_OPENAI_API_KEY` | NOT required for this trial | — | — | Leave unset | `echo ${LABGEN_LLM_OPENAI_API_KEY:-UNSET}` → UNSET | YES (disabled by default) | **Disabled — do not set** |

### Verification: no secrets in output

Run after injecting secrets to confirm no values are leaked:

```bash
python scripts/labgen_staging_missing_inputs.py --env-file <staging-env-file> --json \
  | grep -E '"key"|"reason"|"status"|"overall"'
# Expected: only key names, no values
```

---

## E. Minimal Provisioning Sequence

Complete these phases in order. Each phase has a validation gate — do not skip ahead.

### Phase 0 — Secret Manager Setup

- Create all entries in secret manager (see Section D inventory).
- Placeholders: `<set-in-secret-manager>` in `.env.staging.example` are the keys to populate.
- **Do not commit real secrets to git.**

### Phase 1 — K3s Staging Cluster

- Provision a dedicated staging K3s cluster (not shared with production).
- Obtain the kubeconfig for the service account.
- Store the kubeconfig file at the path you will set in `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH`.
- Permissions: `chmod 600` on kubeconfig file.

Validation:
```bash
kubectl cluster-info --kubeconfig <staging-kubeconfig-path>
```

### Phase 2 — K3s RBAC

- Create a service account for LabGen namespace lifecycle.
- Create a `ClusterRole` with permissions: create/delete namespaces, create/delete rolebindings.
- Create a `ClusterRoleBinding` binding the SA to the ClusterRole.
- Generate a kubeconfig for this SA.

Validation:
```bash
kubectl auth can-i create namespaces --as=system:serviceaccount:<ns>:<sa> --kubeconfig <path>
kubectl auth can-i delete namespaces --as=system:serviceaccount:<ns>:<sa> --kubeconfig <path>
kubectl auth can-i create rolebindings --as=system:serviceaccount:<ns>:<sa> -n test-ns --kubeconfig <path>
```

### Phase 3 — Internal Image Registry

- Start a container registry at `<staging-registry-host>:5000`.
- Push all required images (see Section C).
- Verify each image is reachable from the backend host.

Validation:
```bash
curl http://<staging-registry-host>:5000/v2/nginx/tags/list
curl http://<staging-registry-host>:5000/v2/busybox/tags/list
curl http://<staging-registry-host>:5000/v2/alpine/tags/list
curl http://<staging-registry-host>:5000/v2/curlimages/curl/tags/list
```

### Phase 4 — Proxmox Staging VM Pool

- Create a staging Proxmox pool (e.g. `k8s-netlab-staging`).
- Allocate a VMID range that does not overlap production range (500–599).
- Clone or create a staging VM template. Add it to the staging pool.
- Create a Proxmox API token for the staging pool. Inject `PROXMOX_TOKEN_SECRET` via secret manager.
- Set `VM_SSH_PASSWORD` via secret manager.

Validation:
```bash
curl -k -H "Authorization: PVEAPIToken=<staging-token-id>=<staging-token-secret>" \
  https://<staging-proxmox-host>:8006/api2/json/version
```

### Phase 5 — Storage Mounts

- Ensure `data/` directory exists and is writable by the service user.
- Ensure `data/` is on a local filesystem (not NFS — `flock` requires local FS).
- Create the verifier credential root directory at the path set in `LABGEN_VERIFIER_CREDENTIAL_ROOT`.
- Set permissions: `chmod 700 <credential-root>`.
- Take a backup: `cp -r data/ data_backup_$(date +%Y%m%d)/`

Validation:
```bash
touch data/test-write && rm data/test-write
df -T data/   # must not show nfs
stat <credential-root>   # must show drwx------
```

### Phase 6 — Backend Env Injection

- Copy `deploy/labgen/.env.staging.example` to `.env.staging` (gitignored).
- Fill in all `<set-in-staging-secret-manager>` values from secret manager.
- Replace all placeholder hosts (`<staging-host>`) with real staging hostnames/IPs.
- **Review**: no production credentials must appear in `.env.staging`.

Run the missing inputs helper:
```bash
python scripts/labgen_staging_missing_inputs.py --env-file <staging-env-file>
# Must exit 0 (no missing inputs)
```

### Phase 7 — Intake Verification Gate + Preflight and Dry Run

**Run the unified intake gate first (combines all checks in one command):**

```bash
python scripts/labgen_ops_staging_intake_verify.py \
  --env-file <staging-env-file> \
  --base-url <staging-base-url> \
  --json
# Decision must be: READY_TO_RERUN_CONTROLLED_STAGING_TRIAL
# If any BLOCKED_* — resolve blocking_issues before proceeding
```

See `docs/labgen/OPS_STAGING_INTAKE_VERIFICATION_v0.1.md` for full gate documentation.

If the gate blocks, run individual commands for detail:

```bash
# Phase 1: check which inputs are missing
python scripts/labgen_staging_missing_inputs.py --env-file <staging-env-file>

# Phase 2: static validation (offline — no backend required)
python scripts/labgen_staging_provisioning_validate.py --env-file <staging-env-file>
# Must exit 0 (no blocking issues)

# Phase 3: runtime preflight
python scripts/labgen_production_preflight.py --env-file <staging-env-file>
# Must exit 0 (no blocking issues)

# Phase 4: staging dry run (requires running backend)
python scripts/labgen_staging_dry_run.py \
  --env-file <staging-env-file> \
  --base-url <staging-base-url> \
  --json
# Must return "overall": "pass" or "overall": "warning"

# Adapter and LLM status verification
curl -H "X-Admin-Token: <admin-token-from-secret-manager>" \
  <staging-base-url>/api/labgen/runtime/adapter-status
# Must return: "production_safe": true, "namespace_adapter_kind": "k8s"

curl -H "X-Admin-Token: <admin-token-from-secret-manager>" \
  <staging-base-url>/api/labgen/llm-provider/status
# Must return: "live_enabled": false
```

### Phase 8 — Controlled Live Trial Rerun

**Intake gate (Phase 7) must output `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL` before running this.**
All Phase 0–7 gates must be satisfied before proceeding.

```bash
python scripts/labgen_controlled_staging_trial.py \
  --env-file <staging-env-file> \
  --base-url <staging-base-url> \
  --staging-lab-draft-id <published-staging-draft-id> \
  --staging-user-session <STAGING_USER_SESSION_COOKIE> \
  --allow-runtime-start \
  --allow-timeout-expiry \
  --allow-cleanup-check \
  --json
```

Expected result when all inputs are provided: **LIVE\_TRIAL\_PASSED** or **LIVE\_TRIAL\_PASSED\_WITH\_NOTES**.

---

## F. Validation Commands Reference

All commands use placeholders — replace before running.

### Unified intake gate (run first — combines all phases)

```bash
# 0. Unified intake verification gate (offline + optional live diagnostics)
python scripts/labgen_ops_staging_intake_verify.py \
  --env-file <staging-env-file> \
  --base-url <staging-base-url> \
  --json
# Decision: READY_TO_RERUN_CONTROLLED_STAGING_TRIAL or BLOCKED_*
```

### Static checks (no backend required, no network calls)

```bash
# 1. Check which inputs are missing or placeholder
python scripts/labgen_staging_missing_inputs.py \
  --env-file <staging-env-file> \
  --json

# 2. Full static env file validation
python scripts/labgen_staging_provisioning_validate.py \
  --env-file <staging-env-file>

# 3. Runtime config preflight
python scripts/labgen_production_preflight.py \
  --env-file <staging-env-file>
```

### Live checks (require running backend at `<staging-base-url>`)

```bash
# 4. Staging dry run (safe GET probes only)
python scripts/labgen_staging_dry_run.py \
  --env-file <staging-env-file> \
  --base-url <staging-base-url> \
  --json

# 5. Safe diagnostics phase only (no runtime start)
python scripts/labgen_controlled_staging_trial.py \
  --env-file <staging-env-file> \
  --base-url <staging-base-url> \
  --json

# 6. Full controlled trial (all phases — only after all preconditions pass)
python scripts/labgen_controlled_staging_trial.py \
  --env-file <staging-env-file> \
  --base-url <staging-base-url> \
  --staging-lab-draft-id <published-staging-draft-id> \
  --staging-user-session <STAGING_USER_SESSION_COOKIE> \
  --allow-runtime-start \
  --allow-timeout-expiry \
  --allow-cleanup-check \
  --json
```

---

## G. Expected Pass Criteria

The controlled staging trial passes when ALL of the following are true:

| Criterion | How to verify |
|-----------|--------------|
| Provisioning validator exits 0 | `python scripts/labgen_staging_provisioning_validate.py --env-file <staging-env-file>` → exit 0 |
| Preflight exits 0 | `python scripts/labgen_production_preflight.py --env-file <staging-env-file>` → exit 0 |
| Dry run exits 0 or warning | `python scripts/labgen_staging_dry_run.py ... --json` → `"overall": "pass"` or `"warning"` |
| Runtime adapter is production-safe | `GET /api/labgen/runtime/adapter-status` → `"production_safe": true`, `"namespace_adapter_kind": "k8s"` |
| LLM live is disabled | `GET /api/labgen/llm-provider/status` → `"live_enabled": false` |
| Demo seed not exposed to non-admins | Learner cannot access `/api/labgen/demo/seed` (expect 403) |
| Image readiness responds correctly | Images in whitelist return `READY`, unknown images return `BLOCKED` / `UNRESOLVED` / `NOT_FOUND` |
| One controlled runtime session can start, check, complete, cleanup | Controlled trial Phase 5–7 pass |
| Verifier credential is reclaimed after session close | No credential files remain after cleanup |
| No sensitive values in any response or log | Visual inspection + `--json` output review |

---

## H. Abort Criteria

Abort the trial immediately if any of the following occur:

| Condition | Action |
|-----------|--------|
| Any secret value printed in script output or backend log | Abort, rotate all staging secrets, investigate source |
| Production config mistakenly used in staging | Abort, isolate staging environment, review `.env.staging` |
| Stub adapter active in `production` runtime mode | Abort — check `LABGEN_NAMESPACE_ADAPTER` and `LABGEN_RUNTIME_MODE` |
| LLM unexpectedly enabled (`live_enabled: true`) | Abort — `LABGEN_LLM_PROVIDER_MODE` must be `fake_only` |
| Credential root has unsafe permissions or path | Abort — check `LABGEN_VERIFIER_CREDENTIAL_ROOT` |
| Cleanup fails without `VM_TAINTED` / `CLEANUP_FAILED` observability | Abort — investigate cleanup pipeline |
| Learner can see unpublished draft | Abort — check draft status and access control |
| Image-BLOCKED lab draft can be published | Abort — check `PublishService` and `ImageResolver` |

---

## I. Handoff Checklist

Use this checklist to track ops provisioning progress before requesting a live trial rerun.

| # | Item | Owner | Due | Evidence Path | Validation Command | Status | Notes |
|---|------|-------|-----|---------------|--------------------|--------|-------|
| I-1 | Secret manager entries created for all secrets in Section D | Ops | — | Secret manager console screenshot | Secret manager lookup | `[ ]` | Never commit values to git |
| I-2 | Staging K3s cluster provisioned | Ops | — | Cluster endpoint URL | `kubectl cluster-info --kubeconfig <path>` | `[ ]` | Staging-only, not production |
| I-3 | K3s RBAC (SA + ClusterRole + kubeconfig) | Ops | — | SA and role names | `kubectl auth can-i create namespaces --as=...` | `[ ]` | See Phase 2 |
| I-4 | Kubeconfig injected at `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Ops | — | Path confirmed | `kubectl version --kubeconfig <path>` | `[ ]` | File permissions: chmod 600 |
| I-5 | `ADMIN_TOKEN` injected (>= 32 chars) | Ops | — | Length check only | `echo ${#ADMIN_TOKEN}` → ≥ 32 | `[ ]` | Never in plaintext file |
| I-6 | Staging Proxmox pool and template created | Ops | — | Pool name, template VMID | `pvesh get /pools/<staging-pool>` | `[ ]` | VMID range must not overlap 500–599 |
| I-7 | Proxmox staging API token created | Ops | — | Token ID (not secret) | Proxmox GUI token list | `[ ]` | Staging-specific, not production token |
| I-8 | `PROXMOX_TOKEN_SECRET` injected | Ops | — | — | Proxmox API version call | `[ ]` | Never in plaintext file |
| I-9 | `VM_SSH_PASSWORD` injected | Ops | — | — | SSH connectivity test | `[ ]` | Never in plaintext file |
| I-10 | Staging image registry running | Ops | — | Registry URL (host only) | `curl http://<staging-registry>:5000/v2/` | `[ ]` | |
| I-11 | Required images pushed to staging registry | Ops | — | Tag list output | `curl .../v2/nginx/tags/list` | `[ ]` | nginx/busybox/alpine/curl |
| I-12 | `VM_REGISTRY_MIRROR` set to real staging registry URL | Operator | — | `.env.staging` diff | `grep VM_REGISTRY_MIRROR .env.staging` | `[ ]` | No `<placeholder>` tokens |
| I-13 | `data/` directory writable on staging host | Ops | — | — | `touch data/test-write && rm data/test-write` | `[ ]` | Local FS only |
| I-14 | Verifier credential root created, chmod 700 | Ops | — | `stat` output | `stat <path>` → drwx------ | `[ ]` | Not /tmp |
| I-15 | `.env.staging` file created from template, all placeholders filled | Operator | — | File diff (no values) | `grep '<' .env.staging` → no output | `[ ]` | Gitignored |
| I-16 | Missing inputs helper exits 0 | Operator | — | Script output | `python scripts/labgen_staging_missing_inputs.py --env-file <staging-env-file>` | `[ ]` | Exit code 0 = all inputs set |
| **I-16a** | **Secret injection verify: decision = SECRET\_INJECTION\_READY** | Operator | — | JSON output → `docs/labgen/OPS_SECRET_INJECTION_VERIFICATION_RESULT_v0.1.md` | `python scripts/labgen_ops_secret_injection_verify.py --env-file <staging-env-file> --json` | `[ ]` | **Run before I-19a** — all 7 keys must be PRESENT\_REDACTED |
| **I-16b** | **Ticket pack: all 6 tickets VERIFIED** | Operator | — | JSON output → `deploy/labgen/staging_ops_ticket_status.md` | `python scripts/labgen_ops_ticket_verify.py --env-file <staging-env-file> --all --json` | `[ ]` | **Run after I-16a** — all tickets must show VERIFIED; see `docs/labgen/OPS_PROVISIONING_TICKET_PACK_v0.1.md` |
| I-17 | Provisioning validator exits 0 | Operator | — | Script output | `python scripts/labgen_staging_provisioning_validate.py --env-file <staging-env-file>` | `[ ]` | No blocking issues |
| I-18 | Preflight exits 0 | Operator | — | Script output | `python scripts/labgen_production_preflight.py --env-file <staging-env-file>` | `[ ]` | No blocking issues |
| I-19 | Staging dry run exits 0 or warning | Operator | — | JSON output | `python scripts/labgen_staging_dry_run.py --env-file <staging-env-file> --base-url <staging-base-url> --json` | `[ ]` | `"overall": "pass"` or `"warning"` |
| **I-19a** | **Intake verification gate: decision = READY\_TO\_RERUN\_CONTROLLED\_STAGING\_TRIAL** | Operator | — | JSON output saved to file | `python scripts/labgen_ops_staging_intake_verify.py --env-file <staging-env-file> --base-url <staging-base-url> --json` | `[ ]` | **Must pass before I-20** — see `docs/labgen/OPS_STAGING_INTAKE_VERIFICATION_RESULT_v0.1.md` |
| I-20 | Controlled trial rerun executed | Operator | — | Live run result artifact v0.2 | Full trial script with allow flags | `[ ]` | Requires I-16a = READY + I-19a = READY — replaces this blocked run |

**Gate**: All items must be `[x]` before proceeding to controlled live trial rerun.  
**Critical**: I-16a (secret injection) must output `SECRET_INJECTION_READY` and I-19a (intake gate) must output `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL` before I-20 may be executed.

---

## Notes

- This handoff package is updated as of commit `d8f80d0`. No further dev work is required to unblock the staging trial.
- Secret injection verification tool added: `scripts/labgen_ops_secret_injection_verify.py` (step I-16a).
  Current result: `SECRET_INJECTION_BLOCKED` — see `docs/labgen/OPS_SECRET_INJECTION_VERIFICATION_RESULT_v0.1.md`.
- Ops provisioning ticket pack added: `docs/labgen/OPS_PROVISIONING_TICKET_PACK_v0.1.md` (step I-16b).
  Ticket verification wrapper: `scripts/labgen_ops_ticket_verify.py`.
  Status tracker: `deploy/labgen/staging_ops_ticket_status.md`.
- The live trial can proceed as soon as ops provisions the staging environment and all checklist items are satisfied.
- Only after a successful live trial (`LIVE_TRIAL_PASSED` or `LIVE_TRIAL_PASSED_WITH_NOTES`) is it permitted to proceed to `Production Cutover Plan v0.1`.
- **Do not declare staging live-passed until the trial script itself reports LIVE\_TRIAL\_PASSED.**

---

*No real secrets, real K3s connections, real Proxmox connections, or real registry connections  
were created in producing this document. All command examples use placeholder values.*
