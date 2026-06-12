# LabGen MVP — Controlled Staging Trial Live Run Result v0.1

> **Final Decision: LIVE_TRIAL_BLOCKED**
> Live runtime phases were NOT executed. Static validation passed with warnings;
> all runtime-facing preflight checks are BLOCKING due to missing staging secrets.

---

## A. Run Metadata

| Field | Value |
|-------|-------|
| Commit | `4717e98` |
| Date / Time (UTC) | 2026-06-12T02:01–02:03Z |
| Operator | k8s-netlab team |
| Staging environment ID | none — staging infra not provisioned |
| Tools used | `scripts/labgen_staging_provisioning_validate.py`, `scripts/labgen_production_preflight.py`, `scripts/labgen_staging_dry_run.py`, `scripts/labgen_controlled_staging_trial.py` |
| Live runtime actions executed | **NO** — static validation / offline checks only |
| Env file used | `deploy/labgen/.env.staging.example` (template with placeholders) |
| Real staging `.env.staging` | **Not present** — secrets not yet injected |

---

## B. Preconditions Result

| # | Precondition | Status | Detail |
|---|-------------|--------|--------|
| B-1 | Staging K3s cluster endpoint reachable | **BLOCKED** | No staging K3s cluster provisioned |
| B-2 | Staging kubeconfig / SA injected | **BLOCKED** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` is a commented placeholder in `.env.staging.example` |
| B-3 | Namespace lifecycle permissions scoped | **BLOCKED** | Depends on B-1 |
| B-4 | Staging internal image registry reachable | **BLOCKED** | No staging registry provisioned; `VM_REGISTRY_MIRROR=http://<staging-host>:5000` is placeholder |
| B-5 | Image resolution config set | WARNING | `config/image_whitelist.json` exists; registry URL depends on B-4 |
| B-6 | Verifier credential root is staging-only absolute path | PASS | `LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials` (staging example) |
| B-7 | Runtime mode is `production` | PASS | `LABGEN_RUNTIME_MODE=production` in staging example |
| B-8 | Namespace adapter is `k8s` | PASS | `LABGEN_NAMESPACE_ADAPTER=k8s` in staging example |
| B-9 | LLM provider mode is `fake_only` | PASS | `LABGEN_LLM_PROVIDER_MODE=fake_only` in staging example |
| B-10 | Demo seed endpoint admin-only | PASS | `ADMIN_USERNAMES` set in staging example |
| B-11 | Storage is staging-only | **BLOCKED** | No staging storage mount confirmed |
| B-12 | Frontend static serving points to staging backend | **BLOCKED** | No staging backend URL reachable |
| B-13 | Rollback config ready | PASS | Rollback procedure documented in runbook Section F |

**B-1, B-2, B-3, B-4, B-11, B-12 are BLOCKING. Trial cannot proceed to Phase 3+.**

> Proceed to runtime phase? **NO**

---

## C. Phase Results

### Phase 0 — Provisioning Validation

**Tool**: `scripts/labgen_staging_provisioning_validate.py`  
**Env file**: `deploy/labgen/.env.staging.example`  
**Result**: **WARNING (not blocking)**

```
Env file : deploy/labgen/.env.staging.example
Active keys: 35

WARNINGS (1):
  ⚠ [k8s_kubeconfig_present] LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is acknowledged as
    a commented placeholder. Inject the real kubeconfig path via secret manager
    before trial execution.

Overall: WARNING ⚠
```

Exit code: 0. The static structure of the staging example file is valid. The kubeconfig path is acknowledged as a placeholder — not a blocker at the provisioning validation layer, but a hard requirement for the runtime preflight.

---

### Phase 1 — Production Preflight

**Tool**: `scripts/labgen_production_preflight.py`  
**Env file**: `deploy/labgen/.env.staging.example`  
**Result**: **BLOCKING (4 blocking issues)**

| Check | Status | Detail |
|-------|--------|--------|
| `runtime_mode_valid` | PASS | `LABGEN_RUNTIME_MODE=production` |
| `namespace_adapter_valid` | PASS | `LABGEN_NAMESPACE_ADAPTER=k8s` |
| `production_no_stub_adapter` | PASS | k8s adapter — production-safe |
| `k8s_kubeconfig_set` | **BLOCKING** | Required when adapter=k8s; path is placeholder |
| `credential_root_configured` | PASS | Absolute path set |
| `llm_provider_mode_valid` | PASS | `fake_only` |
| `llm_live_disabled` | PASS | Not live |
| `llm_api_key_not_exposed` | PASS | Not printed |
| `session_ttl_valid` | PASS | 30 minutes |
| `demo_seed_gated` | PASS | Admin-only |
| `admin_token_set` | **BLOCKING** | `ADMIN_TOKEN` not set — placeholder in staging example |
| `proxmox_auth` | **BLOCKING** | `PROXMOX_TOKEN_SECRET` is placeholder; authentication not configured |
| `vm_ssh_password_set` | **BLOCKING** | `VM_SSH_PASSWORD` is placeholder |
| `session_cookie_secure` | WARNING | `SESSION_COOKIE_SECURE=false` in staging example |

Exit code: 1. **4 blocking issues.**

---

### Phase 2 — Staging Deployment Dry Run

**Tool**: `scripts/labgen_staging_dry_run.py`  
**Env file**: `deploy/labgen/.env.staging.example`  
**Result**: **BLOCKING (4 blocking issues — same as Phase 1)**

Same blocking issues as Phase 1 (preflight embedded in dry run). No network probe attempted because preflight failed.

Exit code: 1.

---

### Phase 3 — Safe Diagnostics (Controlled Staging Trial, diagnostics-only mode)

**Tool**: `scripts/labgen_controlled_staging_trial.py`  
**Env file**: `deploy/labgen/.env.staging.example`  
**Result**: **BLOCKING (4 blocking issues — same as Phase 1)**

Same blocking issues. No HTTP probes attempted.

Exit code: 1.

---

### Phase 4 — Image Readiness Gate

**Status**: **NOT EXECUTED**  
Blocked by Phase 1–3. No staging backend URL reachable.

---

### Phase 5 — Controlled Runtime Start

**Status**: **NOT EXECUTED**  
Blocked by Phase 1–3. No real K3s, no namespace created, no VM created, no verifier credential created.

---

### Phase 6 — Step Check / Snapshot / Complete

**Status**: **NOT EXECUTED**

---

### Phase 7 — Cleanup / Verifier Credential Reclaim

**Status**: **NOT EXECUTED**

---

### Phase 8 — LAB\_TIMEOUT / Expiry Dry-Run

**Status**: **NOT EXECUTED**

---

### Phase 9 — Audit Review

**Status**: **NOT EXECUTED**

---

### Phase 10 — Rollback / Cleanup Verification

**Status**: **NOT EXECUTED** (no runtime actions were taken; no cleanup required)

---

## D. Final Decision

> **LIVE\_TRIAL\_BLOCKED**

All tooling is ready and static validation passes with warnings only. However, 4 blocking issues prevent any runtime phase from executing. The staging environment has not been provisioned with real secrets.

---

## E. Evidence

### E-1. Sanitized Script Outputs

All outputs captured above in Section C. No secret values were printed by any script. All scripts comply with the no-secret-printing guarantee.

### E-2. Secret Leakage Assertion

| Check | Result |
|-------|--------|
| No kubeconfig content in output | PASS — scripts never print kubeconfig content |
| No token in output | PASS — scripts report key names only, never values |
| No password in output | PASS — `ADMIN_TOKEN`, `PROXMOX_TOKEN_SECRET`, `VM_SSH_PASSWORD` never printed |
| No credential path leak | PASS — credential root path reported as configured/not-set only |
| No raw provider response | PASS — no HTTP calls made |
| No hidden prompt | PASS — no LLM calls made |
| No stack trace with sensitive info | PASS — no exceptions raised |
| No namespace mismatch detail | PASS — no runtime session created |

### E-3. Namespace Lifecycle Summary

No namespaces were created. No K3s API calls were made.

### E-4. Credential Reclaim Summary

No verifier credentials were created. Credential root was not accessed.

### E-5. Registry Readiness Summary

Registry reachability not tested — no staging registry URL available.

### E-6. Audit Event IDs

No audit events were generated. No runtime session was started.

---

## F. Follow-up Items

### Blockers (must resolve before next trial)

| # | Blocker | Responsible | Config Key / Action |
|---|---------|-------------|---------------------|
| F-1 | Staging K3s cluster not provisioned | Ops team | Provision cluster, obtain kubeconfig |
| F-2 | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` not injected | Ops team | Set absolute kubeconfig path via secret manager |
| F-3 | `ADMIN_TOKEN` not set | Ops team | Generate 32+ char random string, inject via secret manager |
| F-4 | Proxmox credentials not set (`PROXMOX_TOKEN_SECRET`) | Ops team | Create staging Proxmox API token, inject via secret manager |
| F-5 | `VM_SSH_PASSWORD` not set | Ops team | Set staging VM SSH password, inject via secret manager |
| F-6 | Staging internal image registry not provisioned | Ops team | Deploy registry at `<staging-host>:5000`, push nginx/busybox/alpine/curl |
| F-7 | Staging storage mount not available | Ops team | Mount staging data directory at staging host |

### Non-Blocking Notes

| # | Note |
|---|------|
| N-1 | `SESSION_COOKIE_SECURE=false` in staging example — set to `true` if staging uses HTTPS |
| N-2 | Gap 5 (CLEANUP_VERIFICATION_RUNNING intermediate state) and Gap 7 (real K8s integration tests) remain out of scope for this trial |
| N-3 | LLM remains disabled (`fake_only`) — no action required |

### Unblock Checklist

Complete these items in order before re-running the trial:

- [ ] F-1: Provision staging K3s cluster
- [ ] F-2: Inject `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` via secret manager → `.env.staging`
- [ ] F-3: Inject `ADMIN_TOKEN` (32+ chars) via secret manager → `.env.staging`
- [ ] F-4: Create staging Proxmox API token, inject `PROXMOX_TOKEN_ID` + `PROXMOX_TOKEN_SECRET` → `.env.staging`
- [ ] F-5: Set `VM_SSH_PASSWORD` via secret manager → `.env.staging`
- [ ] F-6: Deploy staging internal image registry, push required images
- [ ] F-7: Mount staging data directory, confirm writable
- [ ] Run `python scripts/labgen_staging_provisioning_validate.py --env-file .env.staging` → must be PASS (not WARNING)
- [ ] Run `python scripts/labgen_production_preflight.py --env-file .env.staging` → must be PASS
- [ ] Run `python scripts/labgen_staging_dry_run.py --env-file .env.staging --base-url http://<staging-host>:8000` → must be PASS
- [ ] Re-run this trial with `--env-file .env.staging --base-url http://<staging-host>:8000`

### Recommended Next Step

1. Ops team reads `docs/labgen/STAGING_OPS_HANDOFF_v0.1.md` (actionable handoff package — Section I checklist).
2. Fills in `deploy/labgen/staging_infrastructure_checklist.md` Phase 0–7.
3. Provides real staging secrets. Runs `scripts/labgen_staging_missing_inputs.py` to confirm all blocking inputs are set.
4. Re-executes this trial with a real `.env.staging` pointing at a live staging cluster.

No code changes are required — all tooling is ready (2693 tests, 94.08% coverage).

---

## G. Quality Gate Results

| Gate | Result |
|------|--------|
| Backend pytest (2628 tests) | PASS — 94.08% coverage |
| Coverage ≥ 92% | PASS |
| safety-reviewer | PASS (docs-only change, C-class) |
| Codex review | PASS (docs-only change) |
| pre-commit | PASS |
| pre-push | PASS |

*No code was modified in this run. Only this result artifact and doc updates were added.*

---

*This document records the first execution attempt of LabGen MVP Controlled Staging Trial v0.1.  
The trial is BLOCKED pending real staging infrastructure. This is the expected and correct outcome  
when staging infra is not yet provisioned. It is NOT a failure of the tooling — all scripts  
behaved correctly (fail-closed, no fake success).  
Next step: ops provides real staging environment → re-execute trial → LIVE\_TRIAL\_PASSED or LIVE\_TRIAL\_PASSED\_WITH\_NOTES.*
