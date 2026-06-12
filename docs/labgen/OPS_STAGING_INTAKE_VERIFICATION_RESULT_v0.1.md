# LabGen MVP — Ops Staging Intake Verification Gate Result v0.1

> **Final Decision: BLOCKED_MISSING_INPUTS**
> Intake verification gate was executed. 6 required staging inputs are missing or placeholder.
> Live Trial Rerun is NOT permitted. No runtime actions were executed.

---

## A. Run Metadata

| Field | Value |
|-------|-------|
| Commit | `c8e3c2a` |
| Date / Time (UTC) | 2026-06-12T04:56:27Z |
| Operator | k8s-netlab team |
| Tool | `scripts/labgen_ops_staging_intake_verify.py` |
| Env file | `deploy/labgen/.env.staging.example` (template with placeholders) |
| Real staging `.env.staging` | **Not present** — ops has not injected secrets |
| Base URL provided | **No** — staging backend not deployed |
| Runtime actions executed | **NO** — verification gate only, no runtime actions |

---

## B. Phase Results

### Phase 0 — Env File Readability

| Field | Value |
|-------|-------|
| Status | **PASS** |
| Summary | Env file readable: `deploy/labgen/.env.staging.example` |
| Blocking issues | None |
| Warnings | None |

---

### Phase 1 — Missing Inputs Check

| Field | Value |
|-------|-------|
| Status | **BLOCKING** |
| Summary | 6 required input(s) missing or placeholder |
| Missing count | 6 |

| # | Config Key | Category | Owner |
|---|-----------|----------|-------|
| 1 | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | K3s / Kubernetes | Ops |
| 2 | `ADMIN_TOKEN` | Auth / Admin | Ops |
| 3 | `PROXMOX_HOST` | Proxmox | Ops |
| 4 | `PROXMOX_TOKEN_SECRET` | Proxmox | Ops |
| 5 | `VM_SSH_PASSWORD` | VM Access | Ops |
| 6 | `VM_REGISTRY_MIRROR` | Image Registry | Ops |

---

### Phase 2 — Provisioning Validation

| Field | Value |
|-------|-------|
| Status | **WARNING** (not blocking) |
| Summary | Provisioning validate passed (1 warning) |
| Blocking issues | None |
| Warnings | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` is acknowledged as a commented placeholder. Inject the real kubeconfig path via secret manager before trial execution. |

---

### Phase 3 — Production Preflight

| Field | Value |
|-------|-------|
| Status | **BLOCKING** |
| Summary | Production preflight: 4 blocking issue(s) |

| Check | Status | Detail |
|-------|--------|--------|
| `runtime_mode_valid` | PASS | `LABGEN_RUNTIME_MODE=production` |
| `namespace_adapter_valid` | PASS | `LABGEN_NAMESPACE_ADAPTER=k8s` |
| `production_no_stub_adapter` | PASS | k8s adapter — production-safe |
| `k8s_kubeconfig_set` | **BLOCKING** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` is required when adapter=k8s |
| `credential_root_configured` | PASS | Absolute path set |
| `llm_provider_mode_valid` | PASS | `fake_only` |
| `llm_live_disabled` | PASS | Not live |
| `llm_api_key_not_exposed` | PASS | Not printed |
| `session_ttl_valid` | PASS | 30 minutes |
| `demo_seed_gated` | PASS | Admin-only |
| `admin_token_set` | **BLOCKING** | `ADMIN_TOKEN` not set — placeholder |
| `proxmox_auth` | **BLOCKING** | `PROXMOX_TOKEN_SECRET` is placeholder; authentication not configured |
| `vm_ssh_password_set` | **BLOCKING** | `VM_SSH_PASSWORD` is placeholder |
| `session_cookie_secure` | WARNING | `SESSION_COOKIE_SECURE=false` in staging example |

---

### Phase 4 — Staging Dry Run (Offline)

| Field | Value |
|-------|-------|
| Status | **BLOCKING** |
| Summary | Same 4 blocking issues as Phase 3 (preflight embedded in dry run) |
| Network probes | **NOT attempted** — preflight failed |

---

### Phase 5 — Safe Diagnostics (HTTP Probes)

| Field | Value |
|-------|-------|
| Status | **NOT EXECUTED** |
| Reason | No `--base-url` provided; staging backend not deployed. Phase 1 already blocking — gate terminated before HTTP probes. |

---

## C. Final Decision

> **BLOCKED_MISSING_INPUTS**

The intake gate determined that 6 required staging inputs are missing or placeholder. The staging environment has not been provisioned with real secrets. No HTTP probes were made. No runtime actions were executed.

**Live Trial Rerun: NOT PERMITTED.**

---

## D. Blocking Issues (Unique, Deduplicated)

| # | Input / Check | Root Cause |
|---|--------------|-----------|
| D-1 | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Placeholder — staging K3s cluster not provisioned / kubeconfig not injected |
| D-2 | `ADMIN_TOKEN` | Placeholder — not injected via secret manager |
| D-3 | `PROXMOX_HOST` | Placeholder — staging Proxmox hostname not configured |
| D-4 | `PROXMOX_TOKEN_SECRET` | Placeholder — staging Proxmox API token not created |
| D-5 | `VM_SSH_PASSWORD` | Placeholder — VM SSH password not injected |
| D-6 | `VM_REGISTRY_MIRROR` | Placeholder — staging internal image registry not deployed |

---

## E. Warnings

| # | Warning |
|---|---------|
| W-1 | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` is a commented placeholder — inject before trial execution |
| W-2 | `SESSION_COOKIE_SECURE=false` in staging example — set to `true` if staging uses HTTPS |

---

## F. Security Assertions

| Check | Result |
|-------|--------|
| No secret values in gate output | PASS — gate reports key names only, never values |
| No kubeconfig content in output | PASS — no kubeconfig was loaded or printed |
| No token in output | PASS — `ADMIN_TOKEN`, `PROXMOX_TOKEN_SECRET` never printed |
| No password in output | PASS — `VM_SSH_PASSWORD` never printed |
| No raw env values in output | PASS — only key names and presence reported |
| No HTTP calls made | PASS — no `--base-url` provided; Phase 5 not reached |
| No runtime actions executed | PASS — gate is read-only |
| No namespace created | PASS |
| No verifier credential created | PASS |
| No Proxmox API call made | PASS |
| No K3s API call made | PASS |
| No registry call made | PASS |

---

## G. Unblock Checklist

Complete all items below, then re-run the intake gate:

- [ ] **G-1**: Provision staging K3s cluster
- [ ] **G-2**: Inject `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` (absolute path to real kubeconfig) via secret manager → `.env.staging`
- [ ] **G-3**: Inject `ADMIN_TOKEN` (≥ 32 random chars) via secret manager → `.env.staging`
- [ ] **G-4**: Create staging Proxmox API token; inject `PROXMOX_HOST`, `PROXMOX_TOKEN_ID`, `PROXMOX_TOKEN_SECRET` → `.env.staging`
- [ ] **G-5**: Inject `VM_SSH_PASSWORD` via secret manager → `.env.staging`
- [ ] **G-6**: Deploy staging internal image registry at `<staging-host>:5000`; push `nginx`, `busybox`, `alpine`, `curl`; inject real URL as `VM_REGISTRY_MIRROR` → `.env.staging`
- [ ] **G-7**: Mount staging data directory, confirm writable at `LABGEN_DATA_DIR` path
- [ ] **G-8**: Deploy staging backend; confirm `http://<staging-host>:8000/api/health` returns `{"status":"healthy"}`
- [ ] **G-9**: Re-run missing inputs check → exit 0:
  ```bash
  python scripts/labgen_staging_missing_inputs.py --env-file .env.staging
  ```
- [ ] **G-10**: Re-run intake verification gate → decision must be `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL`:
  ```bash
  python scripts/labgen_ops_staging_intake_verify.py \
      --env-file .env.staging \
      --base-url http://<staging-host>:8000 \
      --json
  ```

See `docs/labgen/STAGING_OPS_HANDOFF_v0.1.md` (Section I checklist) for the full actionable handoff.

---

## H. Next Steps

1. Ops team reads `docs/labgen/STAGING_OPS_HANDOFF_v0.1.md` (actionable handoff — Section I).
2. Fills in `deploy/labgen/staging_infrastructure_checklist.md` Phase 0–7.
3. Injects all 6 missing secrets. Re-runs `scripts/labgen_ops_secret_injection_verify.py --env-file .env.staging --json` → decision must be `SECRET_INJECTION_READY`.
   See `docs/labgen/OPS_SECRET_INJECTION_VERIFICATION_RESULT_v0.1.md` for per-key status detail.
4. Re-runs intake verification gate with real env file and staging base URL.
5. Re-executes Controlled Staging Trial **only after** intake gate outputs `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL`.

No code changes are required — all tooling is ready (2727 tests, 94.08% coverage).

---

*This document records the first execution of the Ops Staging Intake Verification Gate v0.1 against the staging example env file.
The gate correctly identified 6 missing inputs and blocked live trial rerun.
This is the expected and correct outcome when staging secrets have not been provisioned.
It is NOT a tooling failure — the gate behaved correctly (fail-closed, no fake READY).*
