# LabGen MVP — Ops Staging Intake Verification Gate v0.1

> **Purpose**: Determine whether the staging environment has advanced from  
> LIVE\_TRIAL\_BLOCKED to READY\_TO\_RERUN\_CONTROLLED\_STAGING\_TRIAL  
> **This is a verification gate — not a live trial and not a production cutover**  
> **Status**: TOOLING\_READY — awaiting ops provisioning  
> **Commit**: `e9e937a`

---

## A. Purpose

This gate answers a single yes/no question:

> **Has ops completed the staging provisioning checklist such that the  
> Controlled Staging Trial Live Run can be re-executed?**

It does this by calling all existing verification helpers in sequence and  
producing a single decision value. It does NOT execute any runtime action.

### What this gate does

- Reads the staging env file
- Checks for missing or placeholder required inputs
- Validates the static env file configuration (provisioning validate)
- Runs the production preflight against the env-loaded config
- Runs the staging dry run in offline mode (no HTTP probes)
- Optionally: runs safe GET diagnostics against a live staging service
- Produces a final decision and actionable next step

### What this gate does NOT do

- Does not execute runtime start
- Does not create namespaces
- Does not connect to K3s, Proxmox, or any real infrastructure
- Does not call LLM providers
- Does not call POST/PUT/PATCH endpoints
- Does not add new backend APIs
- Does not add new frontend pages
- Does not modify Contract v0.1
- Does not declare staging trial passed
- Does not declare production live
- Does not print secret values

---

## B. Required Inputs

All of the following must be set (not placeholder, not absent) in the staging  
env file or injected into the runtime environment before running this gate.

| Key | Category | Reason |
|-----|----------|--------|
| `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | K3s | Namespace lifecycle adapter |
| `ADMIN_TOKEN` | Auth | Admin diagnostic endpoints (Phase 5) |
| `PROXMOX_HOST` | Proxmox | VM creation and management |
| `PROXMOX_TOKEN_SECRET` | Proxmox | Proxmox API authentication |
| `VM_SSH_PASSWORD` | VM | K3s reset and verifier initialization |
| `VM_REGISTRY_MIRROR` | Registry | Image-gated lab sessions |
| `LABGEN_VERIFIER_CREDENTIAL_ROOT` | Storage | Verifier credential lifecycle |

Additionally, all keys required by `labgen_staging_provisioning_validate.py`  
must be present: `LABGEN_RUNTIME_MODE`, `LABGEN_NAMESPACE_ADAPTER`,  
`LABGEN_LLM_PROVIDER_MODE`, `LABGEN_LAB_SESSION_TTL_MINUTES`,  
`PROXMOX_TOKEN_ID`.

---

## C. Verification Phases

The gate runs 6 phases in sequence. All phases are always executed  
(except Phase 5, which is optional), so the full report is always available.

### Phase 0 — Env File Readability

Verifies the staging env file exists and is readable. If this fails, all  
subsequent phases are skipped and the decision is `BLOCKED_MISSING_INPUTS`.

### Phase 1 — Missing Inputs

Calls `scripts/labgen_staging_missing_inputs.py` logic.  
Identifies which required inputs are absent, empty, or set to placeholder  
values (`<set-in-secret-manager>`, `<placeholder>`, etc.).

A blocking result here means ops has not yet injected the required secrets.

### Phase 2 — Staging Provisioning Validate

Calls `scripts/labgen_staging_provisioning_validate.py` logic.  
Performs static analysis of the env file structure:
- Required key presence
- Namespace adapter safety
- LLM provider mode constraints
- Credential root path safety
- Secret value exposure detection (real credentials in file = BLOCKED)
- Placeholder pattern detection

### Phase 3 — Production Preflight

Calls `scripts/labgen_production_preflight.py` logic, with env vars  
temporarily applied from the staging env file.  
Checks the runtime configuration against production-readiness requirements.

### Phase 4 — Staging Dry Run Offline

Calls `scripts/labgen_staging_dry_run.py` in offline mode (no HTTP probes).  
Validates env loading + preflight in one comprehensive pass.

### Phase 5 — Safe Diagnostics (optional)

Only executed when `--base-url` is provided. Runs safe GET probes against  
the live staging service:

| Endpoint | Auth required | Expect JSON |
|----------|--------------|-------------|
| `GET /api/health` | No | Yes |
| `GET /openapi.json` | No | Yes |
| `GET /` | No | No |
| `GET /api/labgen/contract-pack` | X-Admin-Token | Yes |
| `GET /api/labgen/runtime/adapter-status` | X-Admin-Token | Yes |
| `GET /api/labgen/llm-provider/status` | X-Admin-Token | Yes |

Phase 5 fails closed:
- Network error or unreachable → `BLOCKED_DIAGNOSTICS_UNREACHABLE`
- Invalid JSON where JSON expected → `BLOCKED_DIAGNOSTICS_UNREACHABLE`
- Secret-looking value in any response body → `BLOCKED_SECRET_LEAK_RISK`

### Phase 6 — Readiness Decision

Evaluates all phase results and produces a final decision (Section D).

---

## D. Decision Values

| Decision | Condition | Priority |
|----------|-----------|----------|
| `BLOCKED_MISSING_INPUTS` | Phase 0 or 1 blocks | 1 (highest) |
| `BLOCKED_INVALID_CONFIG` | Phase 2, 3, or 4 blocks | 2 |
| `BLOCKED_SECRET_LEAK_RISK` | Phase 5: secret in response | 3 |
| `BLOCKED_DIAGNOSTICS_UNREACHABLE` | Phase 5: network/parse failure | 4 |
| `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL` | All phases pass | 5 (lowest) |

Priority is applied in descending order: if multiple phases block,  
the highest-priority decision is reported.

---

## E. Operator Commands

### Offline verification (minimum required)

```bash
python scripts/labgen_ops_staging_intake_verify.py \
    --env-file <staging-env-file> \
    --json
```

### Full verification (with live staging service)

```bash
python scripts/labgen_ops_staging_intake_verify.py \
    --env-file <staging-env-file> \
    --base-url <staging-host> \
    --json
```

### Individual phase commands (if gate blocks, run these for detail)

```bash
# Phase 1: missing inputs
python scripts/labgen_staging_missing_inputs.py \
    --env-file <staging-env-file> --json

# Phase 2: provisioning validate
python scripts/labgen_staging_provisioning_validate.py \
    --env-file <staging-env-file> --json

# Phase 3: production preflight
python scripts/labgen_production_preflight.py \
    --env-file <staging-env-file> --json

# Phase 4: dry run offline
python scripts/labgen_staging_dry_run.py \
    --env-file <staging-env-file> --json

# Phase 5: optional safe diagnostics
python scripts/labgen_staging_dry_run.py \
    --env-file <staging-env-file> \
    --base-url <staging-host> --json
```

---

## F. What Passing Means

When the gate outputs `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL`:

- All required inputs appear configured (not placeholder, not absent)
- Static env file configuration passes provisioning validate
- Runtime config passes production preflight
- Offline dry run produces no blocking issues
- (If `--base-url` provided) safe diagnostic endpoints are reachable and contain no secret-looking content

The operator **may** re-execute Controlled Staging Trial Live Run with explicit approval:

```bash
python scripts/labgen_controlled_staging_trial.py \
    --env-file <staging-env-file> \
    --base-url <staging-host> \
    [--allow-runtime-start ...]
```

---

## G. What Passing Does NOT Mean

| Claim | Status |
|-------|--------|
| Staging environment is production-ready | **NOT declared** |
| Controlled staging trial has passed | **NOT declared** |
| K3s namespace E2E has completed | **NOT declared** |
| LLM live generation is approved | **NOT declared** |
| Production cutover is approved | **NOT declared** |
| K3sNamespaceLifecycleAdapter is implemented | **NOT declared** |

This gate is strictly a pre-flight check for the right to re-execute the  
Controlled Staging Trial Live Run. It is not a substitute for the trial itself.

---

## H. Security Requirements

The gate script (`scripts/labgen_ops_staging_intake_verify.py`) enforces:

- Secret values are never printed (only key names and presence)
- Placeholder values are treated as missing (not as configured)
- No HTTP call is made in offline mode (zero network calls when `--base-url` absent)
- Phase 5 calls only safe GET endpoints (list in Section C)
- Forbidden paths are never called: `/seed/demo`, `/publish`, `/start`, `/complete`, `/abort`, `/expire-sessions`
- Invalid JSON or unreachable endpoints → fail closed (`BLOCKED_DIAGNOSTICS_UNREACHABLE`)
- Secret-looking patterns in response body → fail closed (`BLOCKED_SECRET_LEAK_RISK`)
- HTTP client is injectable for testing (no real network calls in test suite)

All example values in documentation use:
- `<staging-env-file>` — path placeholder
- `<staging-host>` — URL placeholder
- `<set-in-secret-manager>` — secret placeholder
- `<placeholder>` — generic placeholder
- `<redacted>` — redacted value indicator

---

## I. Integration with Existing Docs

| Document | Relationship |
|----------|-------------|
| `docs/labgen/STAGING_OPS_HANDOFF_v0.1.md` | Intake gate added as pre-step to Section E |
| `docs/labgen/CONTROLLED_STAGING_TRIAL_LIVE_RUN_RESULT_v0.1.md` | Gate referenced in Section F unblock checklist |
| `docs/labgen/CONTROLLED_STAGING_TRIAL_v0.1.md` | Gate referenced as prerequisite to Phase 3+ |
| `docs/labgen/STAGING_ENVIRONMENT_PROVISIONING_v0.1.md` | Gate referenced in Phase 7 validation sequence |
| `deploy/labgen/staging_infrastructure_checklist.md` | Gate added as Phase 6 validation item V-0a |

---

*This gate produces only a readiness signal. The actual live trial re-execution  
requires explicit operator approval and remains governed by  
`docs/labgen/CONTROLLED_STAGING_TRIAL_v0.1.md`.*
