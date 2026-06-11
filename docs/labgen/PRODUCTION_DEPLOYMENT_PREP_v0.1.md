# LabGen MVP — Production Deployment Preparation v0.1

> **Prepared**: 2026-06-11  
> **Basis**: RC_READY_WITH_NOTES (commit `2c02478`), Contract MVP v0.1  
> **Status**: DEPLOYMENT PREPARATION — not a completed deployment  
> **Next step after this doc**: Staging Deployment Dry Run v0.1

---

## A. Deployment Scope

### This document is a preparation artifact, not a live deployment record.

| Assertion | Value |
|-----------|-------|
| RC decision | RC_READY_WITH_NOTES (see [PRODUCTION_READINESS_RC_v0.1.md](PRODUCTION_READINESS_RC_v0.1.md)) |
| Dependency commit | `2c02478` (Production Readiness RC Gate v0.1) or later |
| Real K3s E2E included | **No** — `K3sNamespaceLifecycleAdapter` is a skeleton (NotImplementedError); must be implemented before live student sessions |
| Live student traffic | **Not enabled** — production traffic is blocked until K3s adapter is implemented |
| Real LLM enabled by default | **No** — `LABGEN_LLM_PROVIDER_MODE=fake_only` is the default and must remain so at first deploy |

### What "production deployment" means here

"Production" in this document means deploying to a real server with real Proxmox/K3s infrastructure, behind HTTPS, with persistent storage and real credentials. It does **not** mean enabling live student sessions immediately — that requires `K3sNamespaceLifecycleAdapter` to be implemented (Gap 1 post-condition).

### What is NOT covered

- Executing the actual deployment
- Connecting to the real K3s cluster
- Running real E2E K3s tests
- Enabling live student traffic
- Enabling real LLM draft generation

---

## B. Required Services

All services listed below must be running and healthy before starting the LabGen backend.

| Service | Role | Production requirement |
|---------|------|----------------------|
| LabGen backend | FastAPI/uvicorn (`k8s-netlab.service`) | Required |
| Frontend static files | Served by the same uvicorn process | Required |
| Internal image registry | `registry:2` on `172.16.100.1:5000` (or configured equivalent) | Required — image readiness checks will fail without it |
| K8s/K3s cluster access | Platform kubeconfig at `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Required for `LABGEN_NAMESPACE_ADAPTER=k8s`; not required for initial stub deploy |
| Namespace lifecycle adapter | K3sNamespaceLifecycleAdapter (once implemented) | Required before live student sessions |
| Verifier credential root | Directory at `LABGEN_VERIFIER_CREDENTIAL_ROOT` with restricted permissions | Required — must be writable by the service user |
| VM tracker / runtime session persistence | `data/vm_tracker.json`, `data/sessions.json`, `data/tainted_vms.json` | Required — directory must be writable |
| Proxmox API | Token auth (`PROXMOX_TOKEN_ID` + `PROXMOX_TOKEN_SECRET`) | Required |
| OpenAI-compatible LLM provider | Optional — disabled by default | Disabled by default; enable explicitly |
| Audit storage | `data/lab_audit_events.json` | Required — directory must be writable |
| Persistent storage backend | JSON file store under `data/` | **Production risk**: single-process, no replication. Explicitly noted — see Section H. |

---

## C. Environment Configuration

All configuration is via environment variables. See [`deploy/labgen/.env.production.example`](../../deploy/labgen/.env.production.example) for the full template.

### Runtime and Namespace

| Variable | Required | Default | Production value |
|----------|----------|---------|-----------------|
| `LABGEN_RUNTIME_MODE` | Yes | `dev` | `production` |
| `LABGEN_NAMESPACE_ADAPTER` | Yes | `stub` | `k8s` (once K3s adapter implemented; `stub` is a blocking error in production mode) |
| `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Yes (if `k8s` adapter) | `` | Absolute path to platform kubeconfig |

### Verifier Credentials

| Variable | Required | Default | Production value |
|----------|----------|---------|-----------------|
| `LABGEN_VERIFIER_CREDENTIAL_ROOT` | Yes | `creds/vm_creds` | `/var/lib/labgen/verifier-credentials` (absolute path, outside app dir) |

**Warning**: The default `creds/vm_creds` is relative to CWD. In production, always set an absolute path. Credentials stored there grant K3s API access — the directory must have `chmod 700` and be owned by the service user.

### LLM Provider

| Variable | Required | Default | Production value |
|----------|----------|---------|-----------------|
| `LABGEN_LLM_PROVIDER_MODE` | Yes | `fake_only` | `fake_only` (must remain disabled at initial deploy) |
| `LABGEN_LLM_PROVIDER_NAME` | No | `fake` | `fake` |
| `LABGEN_LLM_TIMEOUT_MS` | No | `30000` | `30000` (max 60000) |
| `LABGEN_LLM_MAX_OUTPUT_TOKENS` | No | `4096` | `4096` (max 8192) |
| `LABGEN_LLM_OPENAI_BASE_URL` | No (live only) | `` | Set in secret manager when live enabled |
| `LABGEN_LLM_OPENAI_MODEL` | No (live only) | `` | Set in secret manager when live enabled |
| `LABGEN_LLM_OPENAI_API_KEY` | No (live only) | `` | **Set in secret manager only** — never in .env file |

**`LABGEN_LLM_OPENAI_API_KEY` must never appear in any file tracked by git or in plaintext on disk.** Inject via secret manager at runtime.

### Session / Expiry

| Variable | Required | Default | Production value |
|----------|----------|---------|-----------------|
| `LABGEN_LAB_SESSION_TTL_MINUTES` | No | `30` | `30` (adjust per curriculum; must be ≥ 1) |

### Proxmox / VM

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `PROXMOX_HOST` | Yes | — | Proxmox API host |
| `PROXMOX_TOKEN_ID` | Yes | — | Token auth (preferred) |
| `PROXMOX_TOKEN_SECRET` | Yes | — | **Secret manager only** |
| `VM_SSH_PASSWORD` | Yes | — | **Secret manager only** |
| `VM_TEMPLATE_ID` | No | `9000` | Set to `101` in production |
| `VM_ID_MIN` / `VM_ID_MAX` | No | `500`/`599` | k8s-netlab VMID range |
| `VM_REGISTRY_MIRROR` | Recommended | `` | Registry pull-through cache URL |

### Auth / Admin

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `ADMIN_TOKEN` | Yes | `` | ≥ 32 chars; **secret manager only** |
| `ADMIN_USERNAMES` | No | `` | Comma-separated admin usernames |
| `SESSION_COOKIE_SECURE` | No | `true` | Must be `true` behind HTTPS |

### CORS / Frontend

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `ALLOWED_ORIGINS` | Recommended | `` | Set to production domain; empty = block all cross-origin |

### Demo Seed

The demo seed router (`POST /api/labgen/seed/demo`) is always registered and is admin-gated (requires `ADMIN_USERNAMES` membership). There is no `LABGEN_DEMO_SEED_ENABLED` env var — access control is purely through admin auth.

**Production recommendation**: ensure `ADMIN_USERNAMES` is set to a small, known list. The demo seed endpoint creates predictable lab IDs and sessions — do not expose to student-role users.

### Storage

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `DATA_DIR` | No (implicit) | `data/` | JSON files stored here; must be on a persistent volume |

---

## D. Fail-Closed Guarantees

All of the following are currently enforced in code and verified by test.

| Guarantee | Mechanism | Enforcement location | Evidence tests |
|-----------|-----------|---------------------|---------------|
| Production mode with stub namespace adapter → lab start fails | `RuntimeAdapterSelectionService.select()` → `STUB_ADAPTER_IN_PRODUCTION` blocking issue; `create_session()` pre-check rejects with `precheck.unsafe_runtime_adapter` | `runtime_adapter_selection.py`, `lab_session_service.py` | `test_labgen_runtime_adapter_selection.py`, `test_labgen_runtime_start_precheck.py` |
| Invalid `LABGEN_RUNTIME_MODE` or `LABGEN_NAMESPACE_ADAPTER` value → blocking issue | `RuntimeMode(raw)` / `NamespaceAdapterKind(raw)` raises `ValueError`, captured as `INVALID_RUNTIME_MODE` / `INVALID_ADAPTER_KIND` blocking issue | `runtime_adapter_selection.py` | `test_labgen_runtime_adapter_selection.py` |
| Image readiness check must pass before publish | `PublishService._run_image_readiness_check()` → 409 if any image unresolved or registry unreachable | `publish_service.py`, `image_readiness.py` | `test_labgen_image_readiness_publish_gate.py` |
| Runtime precheck condition 4 (stuck Terminating namespace) → lab start fails | `RuntimePrecheckService.check()` condition 4 | `runtime_precheck.py` | `test_labgen_runtime_precheck.py` |
| Runtime precheck condition 6 (prior cleanup unverified) → lab start fails | `RuntimePrecheckService.check()` condition 6 | `runtime_precheck.py` | `test_labgen_runtime_precheck.py` |
| LAB_TIMEOUT sessions trigger cleanup and credential reclaim | `VMExpiryService.expire_sessions()` → `LabSessionService.timeout_session()` → `_do_cleanup()` → `VerifierCredentialReclaimer.reclaim()` | `vm_expiry.py`, `lab_session_service.py` | `test_labgen_vm_expiry.py`, `test_labgen_lab_timeout_integration.py` |
| Verifier credential reclaim on VM reclaim / cleanup failure | `VerifierCredentialReclaimer.reclaim()` in `_do_cleanup()` Phase 2; failure → `LAB_CLEANUP_FAILED` + `mark_vm_tainted` | `lab_session_service.py`, `verifier_credentials.py` | `test_labgen_verifier_credential_reclaim.py` |
| Real LLM provider disabled by default | `LABGEN_LLM_PROVIDER_MODE=fake_only` default; `live_disabled` guard in `LLMProviderBoundaryService.call()` | `llm_provider_boundary.py`, `config.py` | `test_labgen_llm_provider_boundary.py` |
| LLM provider output cannot bypass Pydantic + StaticValidator | `LabDraftGenerationService._validate_candidate()` → `LabDraft(**candidate)` + `StaticValidator.validate()` | `llm_generation.py` | `test_labgen_llm_generation.py` |
| Learner cannot access unpublished drafts | `learner_catalog.py` filters `publish_status == "published"` | `learner_catalog.py`, `routes.py` | `test_labgen_learner_catalog.py` |
| `LABGEN_LAB_SESSION_TTL_MINUTES < 1` → startup fails | `config.py` raises `RuntimeError` at import | `config.py` | `test_labgen_production_preflight.py` |

---

## E. Deployment Checklist

### Phase 0 — Pre-deploy config review

- [ ] Run `python scripts/labgen_production_preflight.py` — exit code must be 0
- [ ] Verify `LABGEN_RUNTIME_MODE=production` (or target value)
- [ ] Verify `LABGEN_NAMESPACE_ADAPTER=k8s` (or confirm stub is intentional with documented exception)
- [ ] Verify `LABGEN_LLM_PROVIDER_MODE=fake_only` (or `disabled`)
- [ ] Verify `LABGEN_VERIFIER_CREDENTIAL_ROOT` is an absolute path outside the app directory
- [ ] Verify `LABGEN_LAB_SESSION_TTL_MINUTES` is set to the intended value (≥ 1)

### Phase 1 — Secrets provisioning

- [ ] `PROXMOX_TOKEN_SECRET` injected via secret manager
- [ ] `VM_SSH_PASSWORD` injected via secret manager
- [ ] `ADMIN_TOKEN` (≥ 32 chars) injected via secret manager
- [ ] `LABGEN_LLM_OPENAI_API_KEY` **not** set (LLM is disabled; if set, verify `LABGEN_LLM_PROVIDER_MODE != live_enabled`)
- [ ] No secrets committed to git

### Phase 2 — Storage setup

- [ ] `data/` directory exists and is writable by the service user
- [ ] `data/users.json`, `data/sessions.json` present (or will be created on first write)
- [ ] `LABGEN_VERIFIER_CREDENTIAL_ROOT` directory created with `chmod 700`, owned by service user
- [ ] Backup script (`scripts/backup-data.sh`) scheduled (daily 03:00 cron)

### Phase 3 — Image registry readiness

- [ ] Internal registry (`172.16.100.1:5000` or configured mirror) is reachable from the LabGen host
- [ ] Required images present in registry: `nginx`, `busybox`, `alpine`, `curlimages/curl`
- [ ] `GET /api/labgen/drafts/{id}/validate` returns no `IMAGE_NOT_IN_REGISTRY` failures for published drafts
- [ ] `POST /api/images/resolve` returns resolved (non-unresolvable) results for whitelist images

### Phase 4 — K8s namespace lifecycle validation

- [ ] Confirm `LABGEN_NAMESPACE_ADAPTER` value
  - If `stub`: document the intentional exception; note that `LABGEN_RUNTIME_MODE=production` + `stub` will block all lab starts
  - If `k8s`: verify `K3sNamespaceLifecycleAdapter` is implemented (currently NotImplementedError skeleton)
- [ ] Platform kubeconfig is at `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` with restricted permissions
- [ ] `GET /api/labgen/runtime/adapter-status` returns `production_safe: true`

### Phase 5 — LLM provider disabled validation

- [ ] `GET /api/labgen/llm-provider/status` returns `mode: fake_only` (or `disabled`)
- [ ] `live_enabled: false` in the status response
- [ ] No `LABGEN_LLM_OPENAI_API_KEY` in environment

### Phase 6 — Contract pack validation

- [ ] `GET /api/labgen/contract-pack` returns `schema_version: "1.0"` and expected endpoint list
- [ ] All endpoints present in the OpenAPI spec (`/openapi.json`)
- [ ] Admin endpoints require `X-Admin-Token` header (verify with a request missing the token → 401/403)

### Phase 7 — Admin diagnostics validation

- [ ] `GET /api/labgen/runtime/adapter-status` → 200 (admin token required)
- [ ] `GET /api/labgen/llm-provider/status` → 200 (admin token required)
- [ ] `GET /api/labgen/contract-pack` → 200 (admin token required)
- [ ] `POST /api/labgen/runtime/expire-sessions` with `{"dry_run": true}` → 200 (admin token required)
- [ ] None of the above responses contain API keys, kubeconfig content, or raw secrets

### Phase 8 — Demo seed disabled or isolated validation

- [ ] Confirm `ADMIN_USERNAMES` is set to a small known list
- [ ] `POST /api/labgen/seed/demo` with a non-admin session cookie → 403
- [ ] Demo seed is not triggered automatically on startup

### Phase 9 — Smoke test procedure

Run the smoke test script after service restart:

```bash
# 1. Health check
curl -sf https://lab.cloudnetops.tech/api/health | python3 -m json.tool

# 2. LabGen contract pack (admin token required)
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" \
     https://lab.cloudnetops.tech/api/labgen/contract-pack | python3 -m json.tool

# 3. Runtime adapter status
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" \
     https://lab.cloudnetops.tech/api/labgen/runtime/adapter-status | python3 -m json.tool

# 4. LLM provider status (must show fake_only or disabled)
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" \
     https://lab.cloudnetops.tech/api/labgen/llm-provider/status | python3 -m json.tool

# 5. Expiry dry-run (must return 200, no mutations)
curl -sf -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"dry_run": true}' \
     https://lab.cloudnetops.tech/api/labgen/runtime/expire-sessions | python3 -m json.tool

# 6. Verify errors log — no new exceptions
journalctl -u k8s-netlab -p err --since "3 minutes ago" --no-pager
```

All six steps must pass without error output.

### Phase 10 — Rollback readiness

- [ ] Previous deployed commit is known and documented
- [ ] Rollback procedure tested in staging (see Section G)
- [ ] `data/` backup from Phase 2 is current

---

## F. Operational Runbook

### How to check runtime adapter status

```bash
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" \
     https://lab.cloudnetops.tech/api/labgen/runtime/adapter-status
```

Response fields:
- `production_safe: true` — production mode + k8s adapter + kubeconfig set + no blocking issues
- `issues[]` — list of `{code, severity, message}` items; severity `"blocking"` requires immediate action

### How to check LLM provider status

```bash
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" \
     https://lab.cloudnetops.tech/api/labgen/llm-provider/status
```

Response:
- `mode` must be `fake_only` or `disabled` unless live generation is explicitly approved
- `live_enabled: false` is the required state at initial production deployment

### How to check image readiness

```bash
# Validate a specific published draft
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" \
     -X POST https://lab.cloudnetops.tech/api/labgen/drafts/{lab_id}/validate

# Batch-resolve image intents
curl -sf -X POST -H "Content-Type: application/json" \
     -d '{"images": [{"requested_image": "nginx:latest"}]}' \
     https://lab.cloudnetops.tech/api/images/resolve
```

An `IMAGE_NOT_IN_REGISTRY` result means the image is absent from the internal registry — add it before publishing the draft.

### How to run expiry dry-run / maintenance

```bash
# Dry-run: inspect without mutating
curl -sf -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"dry_run": true}' \
     https://lab.cloudnetops.tech/api/labgen/runtime/expire-sessions

# Live expiry (mutates state — use when sessions are genuinely timed out)
curl -sf -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"dry_run": false}' \
     https://lab.cloudnetops.tech/api/labgen/runtime/expire-sessions
```

**Note**: Expiry is admin-triggered. Automated cron trigger for expiry is a post-RC enhancement (not yet implemented).

### How to inspect audit events

```bash
# Get all audit events for a session
curl -sf -H "Cookie: session=<token>" \
     https://lab.cloudnetops.tech/api/lab-sessions/{session_id}/audit-events
```

Events contain `event_type`, `timestamp`, `vm_id`, and `metadata` (never contains secrets or kubeconfig).

### How to respond to VM_TAINTED

A VM is tainted when cleanup fails and the namespace may be in an unknown state. Tainted VMs are blocked from new lab sessions by precheck condition 6.

1. Check which VM is tainted:
   ```bash
   cat data/tainted_vms.json
   ```
2. Manually verify the VM's K3s state:
   ```bash
   kubectl --kubeconfig=$LABGEN_K8S_PLATFORM_KUBECONFIG_PATH get namespaces | grep lab-
   ```
3. Once the namespace is confirmed deleted, clear the taint:
   ```bash
   # Edit data/tainted_vms.json — remove the VM ID from the list
   # Then restart the service to reload state
   systemctl restart k8s-netlab
   ```
4. Audit event `precheck.vm_tainted` will record all block events for this VM.

### How to respond to CLEANUP_FAILED

Session status `LAB_CLEANUP_FAILED` means the namespace deletion or credential reclaim failed.

1. Check session state:
   ```bash
   curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" \
        https://lab.cloudnetops.tech/api/lab-sessions/{session_id}
   ```
2. Check `failure_reason` field — typically `namespace_cleanup_failed` or `credential_reclaim_failed`.
3. Manually clean up the namespace:
   ```bash
   kubectl --kubeconfig=$LABGEN_K8S_PLATFORM_KUBECONFIG_PATH delete namespace lab-{session_id}
   ```
4. Manually clean up verifier credentials:
   ```bash
   rm -rf $LABGEN_VERIFIER_CREDENTIAL_ROOT/vm_creds/{vm_id}/
   ```
5. Manually remove the taint from `data/tainted_vms.json` once cleanup is confirmed.

### How to handle LAB_TIMEOUT

Sessions in `LAB_TIMEOUT` state are awaiting expiry processing.

1. Run the expiry endpoint (dry-run first):
   ```bash
   curl -sf -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"dry_run": true}' \
        https://lab.cloudnetops.tech/api/labgen/runtime/expire-sessions
   ```
2. If the dry-run output looks correct, run live:
   ```bash
   curl -sf -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"dry_run": false}' \
        https://lab.cloudnetops.tech/api/labgen/runtime/expire-sessions
   ```
3. Sessions will transition `LAB_TIMEOUT → LAB_CLOSED` (or `LAB_CLEANUP_FAILED` if cleanup fails — see above).

### How to disable live LLM immediately

Set `LABGEN_LLM_PROVIDER_MODE=disabled` (or `fake_only`) and restart:
```bash
# In your .env or secret manager, update the variable, then:
systemctl restart k8s-netlab
# Verify:
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" \
     https://lab.cloudnetops.tech/api/labgen/llm-provider/status | grep '"mode"'
# Must return: "mode": "disabled"  or  "mode": "fake_only"
```

No data migration needed — the fake path takes over immediately.

### How to handle demo seed endpoint in production

The demo seed endpoint (`POST /api/labgen/seed/demo`) is admin-gated. If you need to disable it entirely, remove the relevant username from `ADMIN_USERNAMES` and restart. There is no separate flag — access control is the only gate.

---

## G. Rollback Plan

### Code rollback

```bash
# 1. Identify the previous good commit
git log --oneline -10

# 2. Create a revert commit (never git reset --hard)
git revert <bad-commit-hash> --no-edit

# 3. Push and restart
git push
systemctl restart k8s-netlab

# 4. Verify health
sleep 3
curl -sf https://lab.cloudnetops.tech/api/health
journalctl -u k8s-netlab -p err --since "2 minutes ago" --no-pager
```

### Config rollback

1. Update the environment variable(s) in your secret manager / `.env` file to the previous values.
2. Restart the service: `systemctl restart k8s-netlab`
3. Verify `GET /api/labgen/runtime/adapter-status` returns the expected config.

### LLM provider disable switch

Set `LABGEN_LLM_PROVIDER_MODE=disabled` and restart. Effective immediately — no data migration required.

### Runtime disable / maintenance mode strategy

There is no built-in maintenance mode flag in v0.1. To prevent new lab sessions during maintenance:

1. Option A — restrict admin access: temporarily set `ADMIN_USERNAMES` to an empty string (disables admin APIs and lab session creation for non-admin users, depending on auth flow).
2. Option B — stop the service: `systemctl stop k8s-netlab` — in-flight sessions will be left in their current state; on restart, the expiry service will clean up timed-out ones.

In-flight sessions during a code rollback:
- Sessions in terminal states (`LAB_CLOSED`, `LAB_COMPLETED`, `LAB_ABORTED`, `LAB_CLEANUP_FAILED`) are unaffected.
- Sessions in active states (`LAB_ACTIVE`, `LAB_TIMEOUT`) will be picked up by the expiry service on next trigger after restart.
- Namespaces created before rollback are not automatically deleted by a code rollback — manual cleanup may be required if the code change affected namespace naming.

### Session cleanup considerations

- Sessions with `LAB_ACTIVE` status will remain active in `data/sessions.json` across a restart.
- On restart, the expiry service resumes scanning from the current session list.
- Tainted VMs (`data/tainted_vms.json`) are preserved across restarts.

### Credential cleanup considerations

- Verifier credentials at `LABGEN_VERIFIER_CREDENTIAL_ROOT` are not automatically cleaned up by a code rollback.
- After a rollback, run a dry-run expiry to identify any orphaned sessions: `POST /api/labgen/runtime/expire-sessions` with `{"dry_run": true}`.
- For credentials associated with `LAB_CLEANUP_FAILED` sessions, follow the manual cleanup procedure in Section F.

### Audit preservation

- Audit events are stored in `data/lab_audit_events.json`.
- This file is NOT cleared by a rollback.
- Back up `data/` before any rollback: `bash scripts/backup-data.sh`.

---

## H. Known Non-Blocking Notes

### Gap 5 — Cleanup state sequence skips CLEANUP_VERIFICATION_RUNNING

**What it is**: `_do_cleanup()` transitions directly to `LAB_CLOSED` without passing through the `CLEANUP_VERIFICATION_RUNNING` intermediate state specified in Contract §11.

**Why not blocking RC**: The observable outcome is correct (`cleanup_verified=True/False`, final state `LAB_CLOSED`/`LAB_CLEANUP_FAILED`). The `cleanup_verified` field is set accurately. This is a state-sequence fidelity issue, not a safety or data-loss issue.

**Impact on production**: None — students see correct final states. Operations tooling only needs to distinguish `LAB_CLOSED` vs `LAB_CLEANUP_FAILED`.

**What to monitor**: If you build a frontend progress indicator for cleanup, note that the `CLEANUP_VERIFICATION_RUNNING` state will not appear. Design the indicator to tolerate direct transitions.

**When to address**: When a frontend cleanup progress bar is built, or as part of a post-RC state machine hardening task.

---

### Gap 7 — verifier_credentials.py real K8s paths at 63% coverage

**What it is**: Lines 309–414 of `verifier_credentials.py` implement `VerifierIdentityManager.ensure()` and `export()` which make real subprocess calls (`kubectl apply`, `kubectl create token`). These paths require a live K8s cluster and cannot be tested in the static suite.

**Why not blocking RC**: The logic is structurally correct and reviewed. The untested surface is bounded and well-understood — it only executes when `K3sNamespaceLifecycleAdapter` is active (i.e., after Gap 1 post-condition is met). At that point, integration tests marked `pytest.mark.vm` can cover these paths against a real cluster.

**What to monitor**: Any subprocess failures from `kubectl apply` or `kubectl create token` will surface in the audit log as `VerifierCredentialError` events. Watch the error log on first deployment against a real K3s cluster.

**When to address**: Add `pytest.mark.vm` integration tests when the staging K3s cluster is available.

---

### Persistent storage is JSON file-based (not a database)

**What it is**: All runtime state (`data/*.json`) uses flock-based atomic JSON. There is no replication, no WAL, and no concurrent multi-process access.

**Why acceptable for current scale**: Single-process FastAPI with student capacity of ~12 VMs. The flock pattern provides write safety within one process.

**Production risk**: If the service crashes mid-write, flock will release on process exit and the next write will succeed. However, a corrupted partial write (hardware failure, OOM kill during write) could corrupt a JSON file. The backup script (`scripts/backup-data.sh`) mitigates this.

**What to monitor**: Watch for JSON decode errors in the error log (`journalctl -u k8s-netlab -p err`). Each data file has one entry in the audit log at startup (`data_file_loaded`).

**When to address**: Migrate to SQLite or PostgreSQL when student capacity exceeds ~50 concurrent sessions.
