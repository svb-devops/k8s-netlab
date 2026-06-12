# LabGen MVP — Staging Infrastructure Checklist

> **Status**: BLANK TEMPLATE — fill in during provisioning  
> **Basis**: `docs/labgen/STAGING_ENVIRONMENT_PROVISIONING_v0.1.md`  
> **Purpose**: Track provisioning of each infrastructure component required for  
> Controlled Staging Trial v0.1 live execution  
> **No real secrets in this file** — use `<set-in-secret-manager>` or `<placeholder>` only  

---

## Instructions

1. Make a working copy of this file (e.g. `staging_infrastructure_checklist_YYYYMMDD.md`).
2. Fill in the **Owner** and **Status** columns as each item is provisioned.
3. Record the **Validation Result** — the actual output of the validation command.
4. Once all items are `[x]`, run the provisioning validator and trial dry run.
5. Keep the completed copy as evidence — do not discard after the trial.

---

## Phase 0 — Prerequisites

| # | Item | Owner | Required? | Config Key / Placeholder | Notes |
|---|------|-------|-----------|--------------------------|-------|
| 0-1 | Staging repo clone available and at commit `fd544e3` or later | Operator | YES | `git log --oneline -1` | |
| 0-2 | Python venv activated (`source venv/bin/activate`) | Operator | YES | — | |
| 0-3 | `.env.staging.example` template reviewed | Operator | YES | `deploy/labgen/.env.staging.example` | |
| 0-4 | Staging `.env` file created (gitignored) | Operator | YES | `.env.staging` (not committed) | Copy from example; fill placeholders |
| 0-5 | Secret manager accessible (Vault / Doppler / CI env) | Operator | YES | — | |
| 0-6 | Provisioning plan read (`STAGING_ENVIRONMENT_PROVISIONING_v0.1.md`) | Operator | YES | — | |

---

## Phase 1 — K3s Cluster

| # | Item | Owner | Required? | Config Key | Validation Command | Status | Validation Result | Notes |
|---|------|-------|-----------|------------|--------------------|--------|-------------------|-------|
| K-1 | Staging K3s cluster created (dedicated, staging-only) | Ops | **YES** | — | `kubectl version --kubeconfig <path>` | `[ ]` | | |
| K-2 | K3s cluster endpoint reachable from backend host | Ops | **YES** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | `kubectl cluster-info --kubeconfig <path>` | `[ ]` | | |
| K-3 | Service account created for LabGen namespace lifecycle | Ops | **YES** | — | `kubectl get sa -n kube-system` | `[ ]` | | |
| K-4 | ClusterRole / Role with namespace + rolebinding perms applied | Ops | **YES** | — | `kubectl get clusterrole labgen-ns-lifecycle` | `[ ]` | | |
| K-5 | SA can create namespaces | Ops | **YES** | — | `kubectl auth can-i create namespaces --as=system:serviceaccount:<ns>:<sa>` | `[ ]` | | |
| K-6 | SA can delete namespaces | Ops | **YES** | — | `kubectl auth can-i delete namespaces --as=system:serviceaccount:<ns>:<sa>` | `[ ]` | | |
| K-7 | SA can create/delete rolebindings in lab namespaces | Ops | **YES** | — | `kubectl auth can-i create rolebindings --as=...` | `[ ]` | | |
| K-8 | Kubeconfig generated and stored in secret manager | Ops | **YES** | — | Secret manager lookup | `[ ]` | | No kubeconfig committed to repo |
| K-9 | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` set to absolute path in `.env.staging` | Operator | **YES** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-secret-manager>` | `echo $LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | `[ ]` | | |
| K-10 | Kubeconfig file has restricted permissions (not world-readable) | Operator | **YES** | — | `stat <path>` → permissions 0600 or 0400 | `[ ]` | | |
| K-11 | Namespace cleanup works: `kubectl delete namespace test-ns` completes | Ops | YES | — | Manual test | `[ ]` | | |

---

## Phase 2 — Proxmox

| # | Item | Owner | Required? | Config Key | Validation Command | Status | Validation Result | Notes |
|---|------|-------|-----------|------------|--------------------|--------|-------------------|-------|
| P-1 | Staging Proxmox accessible | Ops | **YES** | `PROXMOX_HOST=<staging-proxmox-host>` | `curl -k https://<staging-proxmox>:8006/api2/json/version` | `[ ]` | | |
| P-2 | Staging Proxmox pool created (not production pool) | Ops | **YES** | `PROXMOX_POOL=<staging-pool-name>` | `pvesh get /pools` | `[ ]` | | e.g. `k8s-netlab-staging` |
| P-3 | Staging VMID range allocated (does not overlap 500–599) | Ops | **YES** | `VM_ID_MIN=<n>`, `VM_ID_MAX=<n>` | Config review + `qm list` | `[ ]` | | |
| P-4 | VM template cloned for staging (not VM 101) | Ops | **YES** | `VM_TEMPLATE_ID=<staging-template-id>` | `qm config <template-id>` | `[ ]` | | |
| P-5 | Template VM added to staging pool | Ops | **YES** | — | `pvesh get /pools/<staging-pool>` | `[ ]` | | Required for clone permissions |
| P-6 | Proxmox token created for staging (staging-specific, not production token) | Ops | **YES** | `PROXMOX_TOKEN_ID=<staging@pve!api>` | Proxmox GUI token list | `[ ]` | | |
| P-7 | `PROXMOX_TOKEN_SECRET` injected via secret manager | Ops | **YES** | `PROXMOX_TOKEN_SECRET=<set-in-secret-manager>` | Secret manager lookup | `[ ]` | | Never in plaintext file |
| P-8 | Token has `VM.Clone`, `VM.Allocate`, `VM.Config.*` on staging pool | Ops | **YES** | — | `pvesh get /access/acl` | `[ ]` | | |
| P-9 | `VM_SSH_PASSWORD` injected via secret manager | Ops | **YES** | `VM_SSH_PASSWORD=<set-in-secret-manager>` | Secret manager lookup | `[ ]` | | |
| P-10 | Staging network bridge available | Ops | YES | `VM_BRIDGE=<staging-bridge>` | `ip link show <bridge>` on Proxmox host | `[ ]` | | |

---

## Phase 3 — Image Registry

| # | Item | Owner | Required? | Config Key | Validation Command | Status | Validation Result | Notes |
|---|------|-------|-----------|------------|--------------------|--------|-------------------|-------|
| R-1 | Staging internal registry running | Ops | **YES** | `VM_REGISTRY_MIRROR=http://<staging-registry>:5000` | `curl http://<staging-registry>:5000/v2/` | `[ ]` | | |
| R-2 | Registry reachable from backend host | Ops | **YES** | — | `curl http://<staging-registry>:5000/v2/` from backend | `[ ]` | | |
| R-3 | `nginx:1.25-alpine` pushed to staging registry | Ops | **YES** | `config/image_whitelist.json` | `curl http://<staging-registry>:5000/v2/nginx/tags/list` | `[ ]` | | |
| R-4 | `busybox:1.36` pushed to staging registry | Ops | **YES** | `config/image_whitelist.json` | `curl http://<staging-registry>:5000/v2/busybox/tags/list` | `[ ]` | | |
| R-5 | `alpine:3.18` pushed to staging registry | Ops | **YES** | `config/image_whitelist.json` | `curl http://<staging-registry>:5000/v2/alpine/tags/list` | `[ ]` | | |
| R-6 | `curlimages/curl:8.5.0` pushed to staging registry | Ops | **YES** | `config/image_whitelist.json` | `curl http://<staging-registry>:5000/v2/curlimages/curl/tags/list` | `[ ]` | | |
| R-7 | `config/image_whitelist.json` updated to staging registry host | Operator | **YES** | `config/image_whitelist.json` | Review file content | `[ ]` | | Use staging-only values |
| R-8 | Registry auth configured (if required) | Ops | Conditional | Docker config / env | Registry login test | `[ ]` | | Leave empty if no auth |

---

## Phase 4 — Storage and Credentials

| # | Item | Owner | Required? | Config Key | Validation Command | Status | Validation Result | Notes |
|---|------|-------|-----------|------------|--------------------|--------|-------------------|-------|
| S-1 | `data/` directory exists and is writable | Ops | **YES** | — | `touch data/test-write && rm data/test-write` | `[ ]` | | Staging-only path |
| S-2 | `data/` is on local filesystem (not NFS) | Ops | **YES** | — | `df -T data/` → not nfs | `[ ]` | | flock requires local FS |
| S-3 | Verifier credential root created | Ops | **YES** | `LABGEN_VERIFIER_CREDENTIAL_ROOT=<set-in-secret-manager>` | `stat <path>` | `[ ]` | | |
| S-4 | Verifier credential root has chmod 700 | Ops | **YES** | — | `stat <path>` → drwx------ | `[ ]` | | |
| S-5 | Verifier credential root is NOT under /tmp or /var/tmp | Ops | **YES** | — | Config review | `[ ]` | | |
| S-6 | Verifier credential root is staging-only (not shared with production) | Ops | **YES** | — | Path review | `[ ]` | | |
| S-7 | `data/` backup taken before trial start | Operator | YES | — | `cp -r data/ data_backup_<date>/` | `[ ]` | | |
| S-8 | Audit log storage path writable | Ops | **YES** | `data/lab_audit_events.json` | `touch data/lab_audit_events.json` | `[ ]` | | |

---

## Phase 5 — Secrets and Config

| # | Item | Owner | Required? | Config Key | Validation Command | Status | Validation Result | Notes |
|---|------|-------|-----------|------------|--------------------|--------|-------------------|-------|
| C-1 | `ADMIN_TOKEN` injected (≥ 32 chars) | Ops | **YES** | `ADMIN_TOKEN=<set-in-secret-manager>` | `echo ${#ADMIN_TOKEN}` → ≥ 32 | `[ ]` | | Never in plaintext file |
| C-2 | `LABGEN_RUNTIME_MODE=production` in `.env.staging` | Operator | **YES** | `LABGEN_RUNTIME_MODE=production` | `grep LABGEN_RUNTIME_MODE .env.staging` | `[ ]` | | |
| C-3 | `LABGEN_NAMESPACE_ADAPTER=k8s` in `.env.staging` | Operator | **YES** | `LABGEN_NAMESPACE_ADAPTER=k8s` | `grep LABGEN_NAMESPACE_ADAPTER .env.staging` | `[ ]` | | |
| C-4 | `LABGEN_LLM_PROVIDER_MODE=fake_only` in `.env.staging` | Operator | **YES** | `LABGEN_LLM_PROVIDER_MODE=fake_only` | `grep LABGEN_LLM_PROVIDER_MODE .env.staging` | `[ ]` | | Must NOT be `live_enabled` |
| C-5 | `LABGEN_LLM_OPENAI_API_KEY` is NOT set (or unset) | Operator | **YES** | — | `echo ${LABGEN_LLM_OPENAI_API_KEY:-UNSET}` → UNSET | `[ ]` | | LLM disabled; no key needed |
| C-6 | `SESSION_COOKIE_SECURE` value appropriate for staging TLS setup | Operator | YES | `SESSION_COOKIE_SECURE=false` (no TLS) or `true` (TLS) | Config review | `[ ]` | | |
| C-7 | `ALLOWED_ORIGINS` set to staging host only | Operator | YES | `ALLOWED_ORIGINS=http://<staging-host>:8000` | Config review | `[ ]` | | |
| C-8 | `ADMIN_USERNAMES` set (non-empty) | Operator | YES | `ADMIN_USERNAMES=admin` | Config review | `[ ]` | | |
| C-9 | No production credentials in `.env.staging` | Operator | **YES** | — | Manual inspection + provisioning validator | `[ ]` | | |

---

## Phase 6 — Validation

| # | Item | Owner | Required? | Config Key | Validation Command | Status | Validation Result | Notes |
|---|------|-------|-----------|------------|--------------------|--------|-------------------|-------|
| V-1 | Provisioning validator passes (exit code 0) | Operator | **YES** | — | `python scripts/labgen_staging_provisioning_validate.py --env-file .env.staging` | `[ ]` | | No blocking issues |
| V-2 | Preflight passes (exit code 0 or warnings only) | Operator | **YES** | — | `python scripts/labgen_production_preflight.py` | `[ ]` | | Warnings acceptable |
| V-3 | Staging dry run passes | Operator | **YES** | — | `python scripts/labgen_staging_dry_run.py --env-file .env.staging --base-url http://<staging-host>:8000 --json` | `[ ]` | | `"overall": "pass"` or `"warning"` |
| V-4 | Backend starts without errors | Operator | **YES** | — | Check stdout / journalctl for ERROR lines | `[ ]` | | |
| V-5 | `GET /api/labgen/runtime/adapter-status` → `production_safe=true` | Operator | **YES** | — | `curl -H "X-Admin-Token: $ADMIN_TOKEN" http://<staging-host>:8000/api/labgen/runtime/adapter-status` | `[ ]` | | |
| V-6 | `GET /api/labgen/llm-provider/status` → `live_enabled=false` | Operator | **YES** | — | `curl -H "X-Admin-Token: $ADMIN_TOKEN" http://<staging-host>:8000/api/labgen/llm-provider/status` | `[ ]` | | |
| V-7 | No sensitive patterns in any diagnostic response | Operator | **YES** | — | Visual inspection of all diagnostic responses | `[ ]` | | `sk-ant-`, `-----BEGIN`, `client-certificate-data:` must be absent |

---

## Phase 7 — Trial Readiness Gate

All of the following must be `[x]` before proceeding to Controlled Staging Trial v0.1 Phase 3+.

| # | Gate | Satisfied? |
|---|------|------------|
| G-1 | All Phase 1–6 items are `[x]` | `[ ]` |
| G-2 | Provisioning validator: exit code 0 (no blocking issues) | `[ ]` |
| G-3 | Staging dry run: `"overall": "pass"` or `"warning"` | `[ ]` |
| G-4 | Runtime adapter status: `production_safe=true`, `namespace_adapter_kind=k8s` | `[ ]` |
| G-5 | LLM provider status: `live_enabled=false` | `[ ]` |
| G-6 | Rollback plan reviewed (Section F of `CONTROLLED_STAGING_TRIAL_v0.1.md`) | `[ ]` |
| G-7 | STAGING_USER_SESSION available (for Phase 4 runtime start) | `[ ]` |
| G-8 | Published staging lab draft available in lab catalog | `[ ]` |

**If any gate is `[ ]`: trial is BLOCKED. Do not proceed with Phase 3+ of the trial runbook.**

---

## Maps to env template

This checklist maps to `deploy/labgen/.env.staging.example`.
Fill in real values in a gitignored `.env.staging` file; never commit real values.

Config keys marked `<set-in-secret-manager>` in the template must be injected  
via your secret manager before validation. The provisioning validator  
(`scripts/labgen_staging_provisioning_validate.py`) will catch active (uncommented)  
secret values that look like real credentials.

## Maps to dry run / trial helpers

| Helper | When to run | What it checks |
|--------|-------------|----------------|
| `scripts/labgen_staging_provisioning_validate.py` | Phase 6, V-1 | Static env file safety (offline) |
| `scripts/labgen_production_preflight.py` | Phase 6, V-2 | Runtime config against current env (offline) |
| `scripts/labgen_staging_dry_run.py` | Phase 6, V-3 | Live service diagnostics (online, safe GETs only) |
| `scripts/labgen_controlled_staging_trial.py` | Trial Phase 0 | Full trial execution (with explicit allow flags) |

---

*This checklist contains no real secrets. All placeholders use `<angle-bracket>` format.*  
*Keep a completed copy as provisioning evidence for the trial record.*
