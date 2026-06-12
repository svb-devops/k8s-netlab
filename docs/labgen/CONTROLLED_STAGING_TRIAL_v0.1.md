# LabGen MVP — Controlled Staging Trial v0.1

> **Trial date**: TBD (requires provisioning checklist complete — see Section A)  
> **Operator**: —  
> **Basis**: Staging Deployment Dry Run v0.1 (`docs/labgen/STAGING_DEPLOYMENT_DRY_RUN_v0.1.md`)  
> **Provisioning plan**: `docs/labgen/STAGING_ENVIRONMENT_PROVISIONING_v0.1.md`  
> **Commit**: `fd544e3` or later  
> **RC verdict**: RC_READY_WITH_NOTES  

---

## A. Scope

### What this trial IS

- A **controlled validation** of LabGen MVP on an **isolated staging environment**.
- Verifies: production-like config, K3s namespace lifecycle, image registry readiness, verifier credential lifecycle, runtime precheck, LAB_TIMEOUT expiry, admin diagnostics, learner flow, audit, and safety behaviour under RC contract constraints.
- Uses real staging K3s cluster (not stub), real staging Proxmox (not production).
- Follows `docs/labgen/CONTROLLED_STAGING_TRIAL_v0.1.md` as the authoritative runbook.

### What this trial IS NOT

| Not in scope | Reason |
|--------------|--------|
| Production deployment | This is a staging trial only |
| Production traffic | Staging environment is isolated |
| Production secrets | All credentials are staging-only |
| Real LLM by default | `LABGEN_LLM_PROVIDER_MODE=fake_only` required |
| Production namespace | Staging namespaces prefixed `lab-staging-*` |
| Production-ready-live claim | Trial PASS ≠ production live |
| K3s E2E at production scale | Single controlled session per trial |

### Current Status

> **TOOLING_READY — Live Execution: BLOCKED (provisioning checklist not yet complete)**

All trial tooling is ready and tested:

| Artifact | Path | Status |
|----------|------|--------|
| **Provisioning plan** | **`docs/labgen/STAGING_ENVIRONMENT_PROVISIONING_v0.1.md`** | **Ready — complete this first** |
| **Infrastructure checklist** | **`deploy/labgen/staging_infrastructure_checklist.md`** | **Ready to fill** |
| **Provisioning validator** | **`scripts/labgen_staging_provisioning_validate.py`** | **Ready (82 tests pass)** |
| Runbook | `docs/labgen/CONTROLLED_STAGING_TRIAL_v0.1.md` | Ready |
| Trial checklist template | `deploy/labgen/staging_trial_checklist.md` | Ready |
| Trial helper script | `scripts/labgen_controlled_staging_trial.py` | Ready (61 tests pass) |
| Tests | `tests/test_labgen_controlled_staging_trial.py` | 61 passing |

Live execution requires provisioning checklist (Phase 7 gate) to be complete. Without it:
1. Mark trial **BLOCKED**.
2. Complete `deploy/labgen/staging_infrastructure_checklist.md` Phase 0–7 first.
3. Run provisioning validator: `python scripts/labgen_staging_provisioning_validate.py --env-file .env.staging`
4. Do not proceed with destructive/runtime trial phases.
5. Do not substitute production environment as fallback.

---

## B. Preconditions

All 13 items must be confirmed before proceeding to Section C. Record each in
`deploy/labgen/staging_trial_checklist.md` Phase 0.

| # | Precondition | Required value | Source |
|---|-------------|----------------|--------|
| B-1 | Staging K3s cluster endpoint reachable | Confirmed by `kubectl cluster-info --kubeconfig <path>` | Ops team |
| B-2 | Staging kubeconfig / SA injected | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` set to absolute path | Secret manager |
| B-3 | Namespace lifecycle permissions scoped | SA has `create/delete namespace`, `create/delete rolebinding` in staging only | Ops team |
| B-4 | Staging internal image registry reachable | `docker pull <staging-host>:5000/nginx:latest` succeeds | Ops team |
| B-5 | Image resolution config set | `config/image_whitelist.json` maps to staging registry | Config |
| B-6 | Verifier credential root is staging-only path | Absolute path, `chmod 700`, no overlap with production | Env file |
| B-7 | Runtime mode is `production` | `LABGEN_RUNTIME_MODE=production` | Env file |
| B-8 | Namespace adapter is `k8s` | `LABGEN_NAMESPACE_ADAPTER=k8s` | Env file |
| B-9 | LLM provider mode is `disabled` or `fake_only` | `LABGEN_LLM_PROVIDER_MODE=fake_only` | Env file |
| B-10 | Demo seed endpoint admin-only | Confirmed: no staging default auto-seed | App config |
| B-11 | Storage is staging-only | `data/` directory is staging-only mount, not shared with production | Ops team |
| B-12 | Frontend static serving points to staging backend | Confirmed by `curl http://<staging-host>:8000/` | Manual check |
| B-13 | Rollback config ready | Rollback steps reviewed (Section F) | Operator |

**If any precondition is missing:** mark trial BLOCKED, do not proceed with Phase 3+.

---

## C. Trial Phases

### Phase 0 — Config and Preflight

```bash
# Run preflight (static config check, no network)
python scripts/labgen_production_preflight.py --env-file deploy/labgen/.env.staging.example

# Run dry run helper (preflight + safe GET probes)
python scripts/labgen_staging_dry_run.py \
    --env-file .env.staging \
    --base-url http://<staging-host>:8000

# Run controlled staging trial in diagnostics-only mode
python scripts/labgen_controlled_staging_trial.py \
    --env-file .env.staging \
    --base-url http://<staging-host>:8000 \
    --json
```

**Expected:** `"overall": "pass"` or `"overall": "warning"` (no blocking issues).  
**Blocking issues must be fixed before proceeding.**

---

### Phase 1 — Service Boot

```bash
source venv/bin/activate
LABGEN_RUNTIME_MODE=production \
LABGEN_NAMESPACE_ADAPTER=k8s \
LABGEN_LLM_PROVIDER_MODE=fake_only \
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Wait for startup, then check logs
journalctl -u k8s-netlab -p err --since "2 minutes ago" --no-pager
# Or for manual uvicorn: inspect stdout for ERROR lines
```

**Expected:** service starts without startup errors.  
**Fail condition:** crash, `RuntimeError` from config fail-closed, or unexpected 5xx at startup.

---

### Phase 2 — Admin Diagnostics

```bash
export ADMIN_TOKEN="<staging-only-admin-token>"

# Contract pack
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://<staging-host>:8000/api/labgen/contract-pack | python3 -m json.tool

# Runtime adapter status — must show namespace_adapter_kind=k8s, production_safe=true
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://<staging-host>:8000/api/labgen/runtime/adapter-status | python3 -m json.tool

# LLM provider status — must show live_enabled=false
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://<staging-host>:8000/api/labgen/llm-provider/status | python3 -m json.tool

# Expiry dry run (dry_run=true — no mutation)
curl -s -X POST \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"dry_run": true}' \
    http://<staging-host>:8000/api/labgen/runtime/expire-sessions | python3 -m json.tool
```

**Expected:** all 200, `live_enabled=false`, `namespace_adapter_kind=k8s`, `production_safe=true`.  
**Fail condition:** any response contains `sk-ant-`, `-----BEGIN`, `client-certificate-data:`, or `live_enabled=true`.

---

### Phase 3 — Image Readiness Publish Gate

```bash
# Create a test draft with READY images (all images resolve to staging registry)
# Create a test draft with BLOCKED images (one image blocked)

# Check publish decision for READY draft — should show ALLOWED
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://<staging-host>:8000/api/labgen/drafts/<ready-draft-id>/publish-decision

# Check publish decision for BLOCKED draft — should show BLOCKED
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://<staging-host>:8000/api/labgen/drafts/<blocked-draft-id>/publish-decision

# Attempt to publish BLOCKED draft — must return 409
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://<staging-host>:8000/api/labgen/drafts/<blocked-draft-id>/publish)
[ "$STATUS" = "409" ] && echo "PASS: blocked draft correctly rejected" || echo "FAIL: expected 409, got $STATUS"

# Publish READY draft — must return 200
curl -s -X POST \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://<staging-host>:8000/api/labgen/drafts/<ready-draft-id>/publish | python3 -m json.tool
```

---

### Phase 4 — Controlled Runtime Start

**Requires B-1 through B-8 confirmed. Set `STAGING_USER_SESSION` in environment.**

```bash
export STAGING_USER_SESSION="<session-cookie-from-logged-in-test-account>"

# Use trial helper with runtime start flag
python scripts/labgen_controlled_staging_trial.py \
    --env-file .env.staging \
    --base-url http://<staging-host>:8000 \
    --allow-runtime-start \
    --staging-lab-draft-id <published-lab-draft-id> \
    --json

# Verify session was created and namespace exists in K3s
kubectl --kubeconfig <staging-kubeconfig> get namespaces | grep "lab-"
```

**Expected:**
- Trial report shows runtime start phase PASS (201) or WARNING (422, K3s not yet fully configured).
- No sensitive patterns in any response.
- If 201: namespace `lab-<session-id>` created in staging K3s.

---

### Phase 5 — Step Check / Snapshot / Complete

```bash
# Get session snapshot
curl -s -b "session=$STAGING_USER_SESSION" \
    http://<staging-host>:8000/api/lab-sessions/<session-id>/snapshot | python3 -m json.tool

# Run a step check (will fail if K3s resources not deployed — expected)
curl -s -X POST \
    -b "session=$STAGING_USER_SESSION" \
    -H "Content-Type: application/json" \
    http://<staging-host>:8000/api/lab-sessions/<session-id>/steps/<step-id>/check \
    | python3 -m json.tool

# Use trial helper for cleanup
python scripts/labgen_controlled_staging_trial.py \
    --env-file .env.staging \
    --base-url http://<staging-host>:8000 \
    --allow-cleanup-check \
    --staging-session-id <session-id> \
    --json
```

---

### Phase 6 — Timeout / Cleanup / Reclaim Negative Test

```bash
# Expiry dry run
python scripts/labgen_controlled_staging_trial.py \
    --env-file .env.staging \
    --base-url http://<staging-host>:8000 \
    --allow-timeout-expiry \
    --json

# Abort session (if complete not available)
curl -s -X POST \
    -b "session=$STAGING_USER_SESSION" \
    http://<staging-host>:8000/api/lab-sessions/<session-id>/abort | python3 -m json.tool

# Verify namespace deleted
kubectl --kubeconfig <staging-kubeconfig> get namespace lab-<session-id> 2>&1

# Verify verifier credential reclaimed
ls <staging-verifier-credential-root>/<vm-id>_verifier.yaml 2>&1
```

**Expected:** namespace absent, credential file absent, no residuals.

---

### Phase 7 — Audit and Safety Review

```bash
# Query audit events for the session
curl -s -b "session=$STAGING_USER_SESSION" \
    http://<staging-host>:8000/api/lab-sessions/<session-id>/audit-events \
    | python3 -m json.tool

# Confirm no sensitive data in audit
# Check: no kubeconfig fields, no credential paths, no stack traces, no raw tokens
```

**Expected:** audit events present, no sensitive data patterns in any audit event field.

---

### Phase 8 — Rollback Rehearsal

Without making changes, rehearse the rollback steps mentally and confirm each is executable:

1. Stop new lab starts: `systemctl stop k8s-netlab` or disable service.
2. LLM already disabled: verify `live_enabled=false` (already confirmed Phase 2).
3. Demo seed disabled: no auto-seed in staging (already confirmed B-10).
4. Clean staging namespaces: `kubectl --kubeconfig <staging-kubeconfig> delete namespace lab-<id>`.
5. Reclaim verifier credentials: `rm -rf <staging-verifier-credential-root>/<vm-id>_verifier.yaml`.
6. Preserve audit logs: copy `data/lab_audit.json` to safe location before cleanup.
7. Revert config: restore `.env.staging` from backup, restart service.
8. Rollback code if needed: `git revert HEAD` (never `git reset --hard`).

---

## D. Pass / Fail Criteria

| Check | PASS condition | FAIL condition |
|-------|----------------|----------------|
| Stub adapter in production-like mode | Never allowed — blocked by Gap 1 guard | `namespace_adapter_kind=stub` with `LABGEN_RUNTIME_MODE=production` → FAIL |
| Namespace creation failure | Fails closed with safe error; no silent success | Namespace creation fails silently or leaks internal error → FAIL |
| Verifier credential not reclaimed | Not applicable until session completes | Credential file persists after session cleanup → FAIL |
| Image-BLOCKED lab published | 409 returned, publish blocked | BLOCKED lab publishes successfully (2xx) → FAIL |
| Learner sees unpublished lab | 404 returned | Learner receives unpublished draft content → FAIL |
| Raw secret in any response or log | Not present | Any `sk-ant-`, `sk-proj-`, `-----BEGIN`, `client-certificate-data:`, token value in any 2xx response or log line → FAIL |
| LAB_TIMEOUT expiry path | `dry_run=True` runs without mutation; live run changes state | Expiry endpoint ignores TTL or returns 500 → FAIL |
| Audit leaks credential/path/stack trace | Audit fields contain only safe metadata | Stack trace, kubeconfig, credential path, or token in audit event → FAIL |
| Controlled runtime start with safe cleanup | 201 + namespace created + cleanup verified | Runtime start unexpectedly silent-succeeds with stub adapter → FAIL |
| Runtime start fails closed (K3s not configured) | 422 with documented reason | Unexpected 5xx or response contains sensitive data → FAIL |

---

## E. Evidence Collection

Fill in during or immediately after trial execution. Keep a copy as evidence.

| Evidence item | Phase | Command / location | Collected | Notes |
|---------------|-------|--------------------|-----------|-------|
| Preflight output | Phase 0 | `python scripts/labgen_production_preflight.py` | — | — |
| Dry run output | Phase 0 | `scripts/labgen_staging_dry_run.py --json` | — | — |
| Trial diagnostics output | Phase 0 | `scripts/labgen_controlled_staging_trial.py --json` | — | — |
| Service startup logs | Phase 1 | `journalctl` or stdout | — | — |
| Contract pack response | Phase 2 | `GET /api/labgen/contract-pack` (sanitized) | — | — |
| Adapter status response | Phase 2 | `GET /api/labgen/runtime/adapter-status` | — | — |
| LLM provider status response | Phase 2 | `GET /api/labgen/llm-provider/status` | — | — |
| Expiry dry run response | Phase 2 | `POST /api/labgen/runtime/expire-sessions` `{"dry_run":true}` | — | — |
| Publish gate blocked response | Phase 3 | `POST /api/labgen/drafts/{id}/publish` → 409 | — | — |
| Runtime start result | Phase 4 | Trial helper JSON output | — | — |
| Namespace lifecycle evidence | Phase 4 | `kubectl get namespace lab-<id>` | — | — |
| Step check result | Phase 5 | `POST /api/lab-sessions/{id}/steps/{sid}/check` (sanitized) | — | — |
| Session snapshot | Phase 5 | `GET /api/lab-sessions/{id}/snapshot` (sanitized) | — | — |
| Cleanup result | Phase 6 | Trial helper `--allow-cleanup-check` output | — | — |
| Verifier credential reclaim evidence | Phase 6 | `ls <cred-root>/<vm-id>_verifier.yaml` | — | — |
| Namespace deletion evidence | Phase 6 | `kubectl get namespace lab-<id>` → NotFound | — | — |
| Audit events | Phase 7 | `GET /api/lab-sessions/{id}/audit-events` (sanitized) | — | — |
| Full pytest output | Quality gate | `pytest tests/ -q` | — | — |

---

## F. Abort / Rollback Plan

### Abort conditions (stop trial immediately)

| Condition | Action |
|-----------|--------|
| Any HTTP response contains `sk-ant-`, `-----BEGIN`, `client-certificate-data:`, or credential token | Stop, rotate the exposed credential, audit which endpoint returned it, do NOT continue |
| `live_enabled=true` detected in diagnostics | Stop service, verify env, rotate API key if loaded, do NOT proceed |
| Stub adapter in production mode passes session creation | Stop, investigate why Gap 1 guard did not trigger, file bug, do NOT continue |
| Namespace cleanup fails and credential not reclaimed | Stop, manually delete namespace and credential file, mark VM tainted |
| Unhandled 5xx that leaks internal stack trace to response | Stop, patch sanitizer, restart trial from Phase 0 |

### Rollback procedure

1. **Stop new starts**: `systemctl stop k8s-netlab` (or SIGTERM the uvicorn process).
2. **Disable live LLM**: already disabled by default; verify `LABGEN_LLM_PROVIDER_MODE` is not `live_enabled`.
3. **Disable demo seed**: already admin-only; no automatic rollback needed.
4. **Clean staging namespaces**: `kubectl --kubeconfig <staging-kubeconfig> delete namespace lab-<id> --grace-period=0`.
5. **Reclaim verifier credentials**: `rm -f <staging-verifier-credential-root>/<vm-id>_verifier.yaml`.
6. **Preserve audit logs**: `cp data/lab_audit.json /tmp/staging-trial-audit-$(date +%s).json`.
7. **Revert config**: restore `.env.staging` from backup, do NOT `git reset --hard` — use `git revert`.
8. **Rollback code**: `git revert HEAD` if a code regression caused the abort.

### After rollback

- Do NOT mark trial as complete.
- Document what failed and in which phase.
- Fix root cause before re-running trial from Phase 0.
- Update `deploy/labgen/staging_trial_checklist.md` with evidence.

---

*This document is the authoritative runbook for LabGen MVP Controlled Staging Trial v0.1.  
It does not represent a completed production deployment, production traffic cutover,  
or a "production live" declaration. See `PRODUCTION_DEPLOYMENT_PREP_v0.1.md` for the full  
production deployment plan.*
