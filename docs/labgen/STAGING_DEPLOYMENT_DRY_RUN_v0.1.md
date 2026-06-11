# LabGen MVP — Staging Deployment Dry Run v0.1

> **Dry run date**: TBD  
> **Operator**: —  
> **Basis**: Production Deployment Preparation v0.1 (`docs/labgen/PRODUCTION_DEPLOYMENT_PREP_v0.1.md`)  
> **Commit**: `a5996e4` or later  
> **RC verdict**: RC_READY_WITH_NOTES  

---

## A. Scope

### What this IS

- A controlled staging deployment dry run validating that LabGen MVP can enter a staging environment-ready state.
- Verifies: preflight, startup configuration, admin diagnostics, contract pack, runtime fail-closed behaviour, LLM disabled-by-default, demo seed isolation, and safety response assertions.
- Based on commit `a5996e4` (Production Deployment Preparation v0.1) or later.

### What this IS NOT

| Not in scope | Reason |
|--------------|--------|
| Real production deployment | This is dry run only |
| Connecting to a real K3s cluster | K3sNamespaceLifecycleAdapter is NotImplementedError |
| Serving real production student traffic | No real users during dry run |
| Calling real LLM providers | `LABGEN_LLM_PROVIDER_MODE=fake_only` is required |
| Lab session creation succeeding | Expected to fail with NotImplementedError (by design) |
| Real secret injection | All secrets are placeholders or staging-only values |
| K3s E2E integration tests | Separate milestone, not part of this dry run |

### Expected behaviour in staging

The service starts, all admin diagnostics endpoints respond, and the contract pack is fetchable.  
Lab starts **fail intentionally** at `K3sNamespaceLifecycleAdapter` with `NotImplementedError` — this is the production safety guard (Gap 1) working correctly.  
This dry run validates the service is safe to operate in staging; it does **not** validate real lab workflows.

---

## B. Environment Assumptions

| Property | Required value | Notes |
|----------|----------------|-------|
| `LABGEN_RUNTIME_MODE` | `production` | Enforces stub-adapter guard |
| `LABGEN_NAMESPACE_ADAPTER` | `k8s` | Preflight PASSES; lab starts fail with NotImplementedError |
| `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Absolute path placeholder | File need not exist for dry run |
| `LABGEN_VERIFIER_CREDENTIAL_ROOT` | Absolute staging path | e.g. `/var/lib/labgen-staging/verifier-credentials` |
| `LABGEN_LLM_PROVIDER_MODE` | `fake_only` | **Must not be `live_enabled`** |
| `LABGEN_LAB_SESSION_TTL_MINUTES` | `30` | Positive integer |
| `ADMIN_TOKEN` | Set, ≥ 32 chars | Inject via secret manager |
| `PROXMOX_*` | Staging values or placeholders | Real Proxmox not required for diagnostics |
| `SESSION_COOKIE_SECURE` | `false` acceptable if no HTTPS | Causes preflight WARNING |
| Demo seed | Disabled by default | Admin-only, not auto-seeded |
| Runtime adapter | stub adapter = fail closed | production + stub → every lab start fails |

Template: `deploy/labgen/.env.staging.example`

---

## C. Dry Run Checklist

### Phase 1 — Env Setup

- [ ] Copy `deploy/labgen/.env.staging.example` to `.env` (gitignored)
- [ ] Fill in all required values (see template legend)
- [ ] Inject secrets via secret manager: `ADMIN_TOKEN`, `PROXMOX_TOKEN_SECRET`, `VM_SSH_PASSWORD`
- [ ] Verify `LABGEN_VERIFIER_CREDENTIAL_ROOT` is an absolute path with `chmod 700`
- [ ] Verify `LABGEN_LLM_PROVIDER_MODE=fake_only` (must not be `live_enabled`)

### Phase 2 — Preflight

```bash
# Load env and run offline preflight
python scripts/labgen_production_preflight.py

# Or use the dry run helper (also runs preflight)
python scripts/labgen_staging_dry_run.py --env-file .env

# JSON output for CI
python scripts/labgen_staging_dry_run.py --env-file .env --json
```

Expected: `Overall: PASS` (warnings about `SESSION_COOKIE_SECURE=false` are acceptable)  
**Blocking issues must be fixed before proceeding.**

### Phase 3 — Backend Start

```bash
source venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Expected: service starts without startup errors. Check `journalctl` or stdout for errors.

**Note on health endpoint**: `GET /api/health` connects to Proxmox. In staging without a Proxmox instance, it will return `{"status": "unhealthy"}` or 500. This is expected and does **not** block the dry run — all other endpoints remain operational.

### Phase 4 — Admin Diagnostics

```bash
export ADMIN_TOKEN="<your-staging-admin-token>"

# Contract pack
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/api/labgen/contract-pack | python3 -m json.tool

# Runtime adapter status
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/api/labgen/runtime/adapter-status | python3 -m json.tool

# LLM provider status
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/api/labgen/llm-provider/status | python3 -m json.tool

# Expiry diagnostics (dry_run=true — no mutations)
curl -s -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}' \
  http://localhost:8000/api/labgen/runtime/expire-sessions | python3 -m json.tool
```

### Phase 5 — Contract Pack Validation

```bash
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/labgen/contract-pack | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body.get('version') == 'v0.1', f'version mismatch: {body.get(\"version\")}'
endpoints = body.get('endpoints', [])
assert len(endpoints) > 10, f'Too few endpoints: {len(endpoints)}'
print(f'Contract pack OK: version={body[\"version\"]}, endpoints={len(endpoints)}')
"
```

### Phase 6 — Runtime Adapter and LLM Status

```bash
# Adapter: must be k8s (not stub) and runtime_mode=production
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/labgen/runtime/adapter-status | python3 -c "
import json, sys
body = json.load(sys.stdin)
print('adapter:', body.get('adapter_kind'))
print('runtime_mode:', body.get('runtime_mode'))
print('lab_creation_blocked:', body.get('lab_creation_blocked'))
"

# LLM: must be live_enabled=false
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/labgen/llm-provider/status | python3 -c "
import json, sys
body = json.load(sys.stdin)
assert body.get('live_enabled') == False, 'FAIL: LLM live mode is unexpectedly enabled'
print('LLM live_enabled:', body.get('live_enabled'), '— OK')
"
```

### Phase 7 — Demo Seed Isolation Check

```bash
# Without admin token: must return 401/403/503 (not 200)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8000/api/labgen/seed/demo)
echo "Demo seed without auth: $STATUS"
[ "$STATUS" = "401" ] || [ "$STATUS" = "403" ] || [ "$STATUS" = "503" ] \
  && echo "PASS: gate active" || echo "FAIL: endpoint returned $STATUS"
```

### Phase 8 — Learner API Safety

```bash
# Unauthenticated: published labs visible, unpublished not
curl -s http://localhost:8000/api/lab-catalog | python3 -m json.tool

# Attempt to access non-existent draft as learner — must 404, not 500
curl -s -o /dev/null -w "%{http_code}" \
  http://localhost:8000/api/labgen/drafts/00000000-0000-0000-0000-000000000000
```

### Phase 9 — Dry Run Helper (all-in-one with live probes)

```bash
# Runs preflight + all safe endpoint probes
python scripts/labgen_staging_dry_run.py \
  --env-file .env \
  --base-url http://localhost:8000 \
  --allow-demo-seed-check

# JSON output for CI
python scripts/labgen_staging_dry_run.py \
  --env-file .env \
  --base-url http://localhost:8000 \
  --json
```

### Phase 10 — Rollback Review

- [ ] Confirm rollback plan has been read (Section F of this document)
- [ ] Confirm no real secrets were written to disk or logs
- [ ] Confirm no real Proxmox VMs were created

---

## D. Pass / Fail Criteria

| Check | Expected | Fail Condition |
|-------|----------|----------------|
| Preflight blocking issues | Zero | Any blocking issue → FAIL |
| Service starts | No startup errors | Startup crash → FAIL |
| `production` + `stub` adapter silently allowed | Never — lab starts fail with STUB_ADAPTER_IN_PRODUCTION | 2xx on lab start with stub → FAIL |
| Live LLM enabled | `live_enabled: false` | `live_enabled: true` in status → FAIL |
| API key or secret in diagnostics response | Not present | Any `sk-ant-`, `sk-proj-`, `-----BEGIN`, `client-certificate-data:` in 2xx response → FAIL |
| Contract pack missing | ≥ 10 endpoints, `version: v0.1` | Missing version or < 10 endpoints → FAIL |
| Learner can see unpublished draft | No — 404 | 200 with draft content → FAIL |
| Demo seed accessible to non-admin | No — 401/403/503 | 200 without auth → FAIL |
| Backend fails to start due to expected fail-closed config (e.g. stub+production) | PASS only if documented | Undocumented startup crash → FAIL |
| Lab start fails with NotImplementedError | PASS — expected behaviour | Lab start succeeds unexpectedly (implies stub adapter) → WARN |
| Health endpoint fails without Proxmox | WARNING — acceptable | Do not treat as FAIL |
| Preflight warnings only (no blockers) | PASS with warnings | Blockers → FAIL |

---

## E. Dry Run Result Template

Fill in this table after executing the checklist. Keep a copy as evidence.

| Check | Command / Endpoint | Expected | Actual | Status | Notes |
|-------|--------------------|----------|--------|--------|-------|
| Preflight | `python scripts/labgen_production_preflight.py` | PASS (warnings OK) | — | — | — |
| Backend starts | `uvicorn backend.main:app` | No startup errors | — | — | — |
| Health endpoint | `GET /api/health` | 200 or 500 (no Proxmox) | — | — | — |
| Contract pack | `GET /api/labgen/contract-pack` (admin) | `{"version":"v0.1", ...}` | — | — | — |
| Contract pack version | Check `version == "v0.1"` | Pass | — | — | — |
| Contract pack endpoint count | Check `len(endpoints) > 10` | Pass | — | — | — |
| Runtime adapter | `GET /api/labgen/runtime/adapter-status` | `adapter_kind=k8s` | — | — | — |
| Lab creation blocked | `lab_creation_blocked=true` | True (K3s not implemented) | — | — | — |
| LLM live_enabled | `GET /api/labgen/llm-provider/status` | `live_enabled=false` | — | — | — |
| Demo seed gate | `POST /api/labgen/seed/demo` without auth | 401/403/503 | — | — | — |
| Learner catalog | `GET /api/lab-catalog` | 200, no admin data | — | — | — |
| Unpublished draft 404 | `GET /api/labgen/drafts/{unknown-id}` | 404 | — | — | — |
| Expiry dry run | `POST /api/labgen/runtime/expire-sessions` `{"dry_run":true}` | 200, no mutations | — | — | — |
| Dry run helper | `python scripts/labgen_staging_dry_run.py --env-file .env --base-url ...` | Overall: PASS/WARN | — | — | — |
| Secret leak scan | All 2xx responses | No sensitive patterns | — | — | — |
| Pre-commit hook | `git commit` | PASS | — | — | — |
| Pre-push hook | `git push` | PASS | — | — | — |

---

## F. Rollback / Abort Criteria

### If preflight fails with blocking issues

1. Stop: do not start the service.
2. Fix the blocking issue(s) — see `PRODUCTION_DEPLOYMENT_PREP_v0.1.md` Section D for per-issue remediation.
3. Re-run preflight until no blocking issues.

### If diagnostics endpoint leaks a secret

1. Stop immediately.
2. Rotate the leaked credential (even if staging-only).
3. Identify which endpoint returned the sensitive pattern.
4. Audit the response model for that endpoint — ensure sensitive fields are not included.
5. Do NOT proceed until the leak is fixed and confirmed absent.

### If runtime adapter status shows stub in production mode

1. Verify `LABGEN_NAMESPACE_ADAPTER=k8s` is set in the environment.
2. If set and still shows stub: check application startup logs for config loading errors.
3. Do NOT attempt to bypass — production + stub means no lab sessions will start, by design.

### If LLM provider is unexpectedly live_enabled

1. Stop the service immediately.
2. Verify `LABGEN_LLM_PROVIDER_MODE=fake_only` in the loaded env.
3. Check for env var override from a parent process or CI environment.
4. Rotate any API key that may have been loaded.
5. Do NOT proceed until confirmed `live_enabled=false`.

### If the service crashes on startup

1. Check logs for the specific error.
2. If error is `RuntimeError: LABGEN_LAB_SESSION_TTL_MINUTES must be ≥ 1` → fix the TTL value (fail-closed behaviour is working correctly).
3. If error is due to `LABGEN_RUNTIME_MODE=production` + `LABGEN_NAMESPACE_ADAPTER=stub` being rejected by a hypothetical future hard-fail at startup → expected.
4. Other crashes: investigate, fix, re-run preflight before retrying.

---

*This document records the staging dry run process for LabGen MVP v0.1.  
It does not represent a completed production deployment, a real K3s E2E validation,  
or a live-traffic cutover. See `PRODUCTION_DEPLOYMENT_PREP_v0.1.md` for the full deployment plan.*
