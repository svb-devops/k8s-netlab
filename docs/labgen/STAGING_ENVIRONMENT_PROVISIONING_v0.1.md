# LabGen MVP — Staging Environment Provisioning Plan v0.1

> **Status**: PROVISIONING PLAN — no live provisioning performed  
> **Basis**: Controlled Staging Trial v0.1 (commit `fd544e3`), RC_READY_WITH_NOTES  
> **Purpose**: Enable team to prepare the real staging environment so that  
> Controlled Staging Trial v0.1 live execution can proceed  
> **Live execution**: BLOCKED until provisioning checklist is complete  

---

## A. Scope

### What this document IS

- A **provisioning plan** for the real staging environment required to execute Controlled Staging Trial v0.1.
- Defines what infrastructure, config, secrets, and network boundaries must exist before the trial can run.
- Provides a fillable checklist (`deploy/labgen/staging_infrastructure_checklist.md`) and a static validation helper (`scripts/labgen_staging_provisioning_validate.py`) to confirm readiness.

### What this document IS NOT

| Not in scope | Reason |
|--------------|--------|
| Live provisioning execution | This plan is read and executed by the ops team |
| Connecting to real K3s | No K3s calls performed by this document or its helper |
| Connecting to Proxmox | No Proxmox calls performed |
| Connecting to registry | No registry calls performed |
| Pushing to real images | Out of scope |
| Creating real secrets | Secrets are created by ops/secret manager, not this document |
| New backend APIs | No new endpoints added |
| New frontend pages | No new pages added |
| Modifying Contract v0.1 | Contract is frozen |
| New runtime states | No state machine changes |
| New audit event types | No audit schema changes |
| Enabling real LLM by default | `LABGEN_LLM_PROVIDER_MODE=fake_only` required |
| Production traffic | Staging environment is isolated |

### Current status of trial tooling

All trial tooling is ready (`TOOLING_READY`). Live execution is BLOCKED because the staging environment does not yet exist.

| Artifact | Path | Status |
|----------|------|--------|
| Provisioning plan | `docs/labgen/STAGING_ENVIRONMENT_PROVISIONING_v0.1.md` | **This document** |
| Infrastructure checklist | `deploy/labgen/staging_infrastructure_checklist.md` | Ready to fill |
| Provisioning validator | `scripts/labgen_staging_provisioning_validate.py` | Ready (82 tests pass) |
| Staging dry run runbook | `docs/labgen/STAGING_DEPLOYMENT_DRY_RUN_v0.1.md` | Complete |
| Controlled trial runbook | `docs/labgen/CONTROLLED_STAGING_TRIAL_v0.1.md` | Complete |
| Trial helper script | `scripts/labgen_controlled_staging_trial.py` | Ready |
| Trial checklist template | `deploy/labgen/staging_trial_checklist.md` | Ready to fill |

---

## B. Required Infrastructure

All components listed below must exist and be independently verified before the staging trial.

| Component | Purpose | Notes |
|-----------|---------|-------|
| Staging K3s cluster | Namespace lifecycle, verifier RBAC | Must be staging-only, not shared with production |
| Staging Proxmox | VM allocation, template, expiry | Dedicated VMID range, not production pool |
| Internal image registry | Image readiness checks for labs | Must serve the images in `config/image_whitelist.json` |
| Persistent storage (data/) | Session, draft, audit, tracker data | Staging-only path, not shared with production |
| Verifier credential root | Per-VM kubeconfig storage | Absolute path, `chmod 700`, staging-only |
| Audit log storage | Append-only `lab_audit_events.json` | Included in persistent storage |
| Frontend static hosting | Served by same uvicorn process | No separate host needed |
| Backend runtime service | FastAPI uvicorn port 8000 | Systemd unit or manual uvicorn |
| LLM provider | AI draft generation | **Disabled by default** (`fake_only`) |
| DNS/TLS/staging host | HTTPS termination (optional for staging) | HTTP acceptable if no staging TLS proxy |
| Secret manager | Inject secrets at runtime | Vault, Doppler, CI/CD secret injection, or `.env` file with strict permissions |

---

## C. K3s Requirements

### Cluster requirements

| Requirement | Value | Why |
|-------------|-------|-----|
| Environment isolation | **Staging-only cluster** | Must not share with production namespaces |
| Namespace adapter | `LABGEN_NAMESPACE_ADAPTER=k8s` | `stub` adapter is blocked in production mode |
| No stub adapter in production mode | Enforced by Gap 1 guard | `LABGEN_RUNTIME_MODE=production` + `stub` → every lab start fails with `STUB_ADAPTER_IN_PRODUCTION` |
| Kubeconfig delivery | Via secret manager → absolute path | No kubeconfig committed to repo |
| Kubeconfig scope | Platform-level (namespace lifecycle only) | No cluster-admin, no cross-namespace write |

### Required RBAC permissions

The service account referenced by `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` must have:

```yaml
# Minimum permissions for K3sNamespaceLifecycleAdapter
rules:
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["create", "delete", "get", "list"]
  - apiGroups: ["rbac.authorization.k8s.io"]
    resources: ["rolebindings"]
    verbs: ["create", "delete", "get", "list"]
```

No `ClusterRoleBinding` creation is required — all RoleBindings are namespace-scoped.

### Allowed namespace prefix

Labs create namespaces with the prefix `lab-<session-uuid>`. The staging cluster must permit creation of namespaces matching this prefix by the service account.

### Namespace cleanup expectations

- `K3sNamespaceLifecycleAdapter.delete_namespace()` issues a `kubectl delete namespace lab-<id>`.
- A namespace in `Terminating` state longer than the expected grace period is treated as stuck.
- The `namespace_lifecycle_stuck_terminating` precheck prevents new sessions from being started on a VM that previously failed cleanup.

### RoleBinding creation expectations

- One RoleBinding per lab session, created in `lab-<session-id>` namespace.
- Bound to the verifier service account created by `VerifierIdentityManager`.
- The RoleBinding grants the verifier read access to namespace-scoped resources.
- Cleaned up when the session is aborted/completed (namespace deletion removes it implicitly).

### Kubeconfig injection

- Inject via secret manager.
- Set `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` to an absolute path (e.g. `/etc/labgen-staging/platform-kubeconfig`).
- The file must be readable by the service user (not world-readable).
- **Never commit the kubeconfig to the repository.**

---

## D. Proxmox Requirements

### Pool and VMID range

| Requirement | Value |
|-------------|-------|
| Pool name | Staging-specific pool (e.g. `k8s-netlab-staging`) |
| VMID range | Staging-only range — **must not overlap** with `500–599` (production range) |
| Template VM ID | Staging-specific clone template (not VM 101) |
| Pool membership | Template VM must be added to the staging pool before LabGen can clone from it |

### VM identity and tracker expectations

- Each lab session is associated with one VM (`vm_id`).
- The VM tracker (`data/vm_tracker.json`) records ownership and expiry.
- Staging tracker must be on staging-only storage — not shared with production tracker.

### VM expiry / LAB_TIMEOUT expectations

- Sessions expire after `LABGEN_LAB_SESSION_TTL_MINUTES` (default: 30).
- Expired sessions transition to `LAB_TIMEOUT`.
- `POST /api/labgen/runtime/expire-sessions` with `dry_run=true` previews candidates without mutation.
- Staging expiry can be tested with short TTL (e.g. `LABGEN_LAB_SESSION_TTL_MINUTES=5`).

### VM reclaim expectations

- After session completion or abort, namespace is deleted and verifier credentials are reclaimed.
- If cleanup fails, VM is marked tainted (`data/tainted_vms.json`).
- A tainted VM cannot be used for a new session until manually cleared.

### No production VM pool

- Staging provisioning must use a dedicated VMID range separate from the production `500–599` range.
- Refer to `~/.claude/rules/proxmox-infrastructure.md` for global pool rules.
- **Never use production VMID range for staging trial.**

### Failure / taint handling expectations

- `cleanup_verified=False` + `failure_reason=namespace_cleanup_failed` → VM tainted.
- Tainted VMs are visible in admin diagnostics.
- Staging: manually `DELETE /internal/vm-tracker/tainted/{vm_id}` (admin-only) to clear after investigation.

---

## E. Image Registry Requirements

### Staging internal registry endpoint

The staging registry must be reachable from the backend service. The registry address is configured in `config/image_whitelist.json` and through the `VM_REGISTRY_MIRROR` env var.

Example staging registry: `http://<staging-registry-host>:5000`

### Images required for template pack

The following images must be pushed to the staging registry to pass image readiness checks for the seeded demo labs:

| Image ref | Registry path | Used by demo scenario |
|-----------|---------------|----------------------|
| `nginx:1.25-alpine` | `<staging-registry>/nginx:1.25-alpine` | Network demos |
| `busybox:1.36` | `<staging-registry>/busybox:1.36` | Utility scenarios |
| `alpine:3.18` | `<staging-registry>/alpine:3.18` | Base container demos |
| `curlimages/curl:8.5.0` | `<staging-registry>/curlimages/curl:8.5.0` | HTTP test scenarios |

Push procedure:
```bash
docker pull <image>
docker tag <image> <staging-registry-host>:5000/<image>
docker push <staging-registry-host>:5000/<image>
```

### Image resolution config

`config/image_whitelist.json` maps external image refs to the internal registry. For staging, update the whitelist to point to `<staging-registry-host>:5000`. **Do not commit staging-specific host values** — use a placeholder and override via env var or deployment config.

### Image readiness check behaviour

- `ImageResolver` performs an HTTP HEAD check against the registry.
- If the registry is unreachable → `not_found` (image readiness check will block publish).
- If the image exists → `ready`.
- If the image is in the blocked list → `blocked` (publish gate enforced regardless of registry state).

### Blocked / unresolved / not_found test images

For negative testing during the trial, the demo seed includes a lab draft with a blocked image. The trial helper verifies that:
- Labs with `BLOCKED` images cannot be published (409 returned).
- Labs with `not_found` images cannot be published if `LABGEN_RUNTIME_MODE=production`.

### Registry credential handling

- If the staging registry requires authentication, credentials must be set via env var or Docker config.
- Registry credentials must **not** appear in any API response.
- The `ImageResolver` never returns registry authentication headers in its output.

---

## F. Storage Requirements

### Persistent repository / storage backend

LabGen uses a JSON file store under `data/`. In staging:

| File | Purpose | Retention |
|------|---------|-----------|
| `data/sessions.json` | User auth sessions | Clear between trial runs if needed |
| `data/lab_sessions.json` | Lab session state | Preserve for audit; clear between trial sets |
| `data/lab_drafts.json` | Draft repository | Preserve through trial |
| `data/vm_tracker.json` | VM ownership + expiry | Critical — preserve; clear only after full cleanup |
| `data/tainted_vms.json` | Tainted VM list | Preserve; investigate before clearing |
| `data/lab_audit_events.json` | Append-only audit log | Never clear during trial |
| `data/lab_review_diffs.json` | Admin review diffs | Preserve |

### Session persistence

`data/sessions.json` uses flock-based atomic writes. The staging `data/` directory must be on a local filesystem (not NFS) to ensure flock works correctly.

### VM tracker persistence

`data/vm_tracker.json` is the authoritative source for VM ownership and expiry. Loss of this file means loss of VM tracking — VMs become orphaned. Back up before each trial run.

### Runtime audit JSON append-only storage

`data/lab_audit_events.json` is append-only. Never truncate or replace this file during a trial. After the trial, copy to a safe location before any cleanup.

### Verifier credential root path

The `LABGEN_VERIFIER_CREDENTIAL_ROOT` directory stores per-VM kubeconfig files. Requirements:
- Must be an absolute path.
- Must not be `/tmp`, `/var/tmp`, `/`, `/root`.
- Must be staging-only (not shared with production).
- Must have `chmod 700` (owner-only access).
- Must be writable by the service user.
- Recommended staging path: `/var/lib/labgen-staging/verifier-credentials`

### Backup / restore expectations

Before each trial run:
```bash
cp data/vm_tracker.json data/vm_tracker.json.bak
cp data/lab_audit_events.json data/lab_audit_events.json.bak
```

After the trial, preserve all audit evidence. Do not delete `data/` contents until investigation is complete.

### Cleanup and retention expectations

- After a successful lab session: namespace deleted, credential reclaimed, tracker updated.
- After a failed cleanup (tainted VM): preserve all data for investigation.
- Staging `data/` directory should be cleared completely only after a full debrief and before a new trial baseline.

---

## G. Secrets and Config

All secrets below use placeholders. Real values are injected by the ops team via secret manager at runtime. **No real values must appear in this document, the checklist, the helper script, or tests.**

| Secret / Config | Env var | Required for trial? | Default / Notes |
|-----------------|---------|---------------------|-----------------|
| K3s platform kubeconfig path | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | **YES** | Absolute path; inject via secret manager |
| Registry credentials (if auth required) | Docker config / env var | Conditional | Only if staging registry requires auth |
| LLM API key | `LABGEN_LLM_OPENAI_API_KEY` | **DISABLED** | Must remain unset; `fake_only` mode |
| Admin token | `ADMIN_TOKEN` | **YES** | ≥ 32 chars; inject via secret manager |
| Session signing secret | `SECRET_KEY` (if used) | YES | Inject via secret manager if applicable |
| Proxmox token ID | `PROXMOX_TOKEN_ID` | **YES** | Staging-specific token |
| Proxmox token secret | `PROXMOX_TOKEN_SECRET` | **YES** | Inject via secret manager |
| VM SSH password | `VM_SSH_PASSWORD` | **YES** | Inject via secret manager |
| Storage credentials | N/A (local file store) | N/A | No storage credentials for JSON file store |
| DeepSeek API key | `DEEPSEEK_API_KEY` | **DISABLED** | Leave unset |

### Keys that must be disabled by default

| Key | Required value | Consequence of enabling |
|-----|---------------|------------------------|
| `LABGEN_LLM_PROVIDER_MODE` | `fake_only` | `live_enabled` → real LLM API calls, unexpected costs |
| `LABGEN_NAMESPACE_ADAPTER` | `k8s` | `stub` → every lab start fails (Gap 1 guard) |
| `LABGEN_RUNTIME_MODE` | `production` | `demo` → demo seed behaviours inappropriate for trial |
| `DEEPSEEK_API_KEY` | unset | Set → unexpected AI tutor calls |

### Placeholder format convention

All placeholder values in example files use `<angle-bracket-description>`:

```
<staging-host>                  — staging hostname or IP
<staging-namespace>             — staging K8s namespace prefix
<staging-registry>              — staging internal registry host
<set-in-secret-manager>         — inject via Vault/Doppler/CI secret
<placeholder>                   — generic placeholder
<redacted>                      — value intentionally hidden in logs/docs
```

---

## H. Network and Security Boundaries

### Connectivity requirements

| Connection | Direction | Protocol | Notes |
|------------|-----------|----------|-------|
| Backend → K3s API | Outbound from backend | HTTPS (6443) | Via `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` kubeconfig |
| Backend → Image registry | Outbound from backend | HTTP or HTTPS | HEAD requests only (image readiness check) |
| Backend → Proxmox API | Outbound from backend | HTTPS (8006) | Token auth only |
| Frontend → Backend | Inbound to backend | HTTP (8000) | CORS restricted to `ALLOWED_ORIGINS` |
| Student browser → Backend | Inbound to backend | HTTP/WS (8000) | WebSocket for SSH terminal |
| Admin browser → Backend | Inbound to backend | HTTP (8000) | `X-Admin-Token` header required |

### Admin diagnostics — no public access

- All `/api/labgen/*` admin endpoints require `X-Admin-Token` header.
- All `/internal/*` endpoints require `X-Admin-Token` header.
- No admin endpoint must be reachable without authentication.
- Staging firewall / network policy must block public access to port 8000 admin paths.

### Learner access restrictions

- Learners cannot access draft content (only published labs visible via `/api/lab-catalog`).
- Learners cannot access admin diagnostics or `/internal/*` endpoints.
- Session isolation: each learner session is confined to their own namespace (`lab-<session-id>`).

### Egress restrictions for LLM disabled mode

When `LABGEN_LLM_PROVIDER_MODE=fake_only`:
- No outbound connection to LLM provider APIs is attempted.
- Staging network policy should block egress to `api.anthropic.com`, `api.openai.com`, external AI APIs.
- This prevents accidental enablement of live LLM from causing unexpected external connections.

### Allowed staging hostnames

```
<staging-host>:8000       — backend service
<staging-host>:5000       — internal image registry (if on same host)
<staging-k3s-host>:6443   — K3s API server
<staging-proxmox-host>:8006  — Proxmox API
```

No production hostnames, IPs, or namespaces must appear in staging configuration.

---

## I. Provisioning Checklist

Full fillable checklist: `deploy/labgen/staging_infrastructure_checklist.md`

Summary table (use the full checklist for execution):

| # | Item | Owner | Required? | Config Key / Placeholder | Validation | Status |
|---|------|-------|-----------|--------------------------|------------|--------|
| 1 | Staging K3s cluster endpoint reachable | Ops | **YES** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | `kubectl cluster-info --kubeconfig <path>` | `[ ]` |
| 2 | K3s RBAC: SA with namespace create/delete + rolebinding create/delete | Ops | **YES** | K8s manifest | `kubectl auth can-i create namespaces --as=<sa>` | `[ ]` |
| 3 | Staging Proxmox accessible | Ops | **YES** | `PROXMOX_HOST`, `PROXMOX_TOKEN_ID`, `PROXMOX_TOKEN_SECRET` | `curl -k https://<staging-proxmox>:8006/api2/json/version` | `[ ]` |
| 4 | Staging VMID range allocated (not overlapping production 500–599) | Ops | **YES** | `VM_ID_MIN`, `VM_ID_MAX` | Config review | `[ ]` |
| 5 | Staging VM template cloned and in pool | Ops | **YES** | `VM_TEMPLATE_ID` | `qm config <template-id>` | `[ ]` |
| 6 | Internal image registry reachable | Ops | **YES** | `VM_REGISTRY_MIRROR` | `curl http://<staging-registry>:5000/v2/` | `[ ]` |
| 7 | Required images pushed to staging registry | Ops | **YES** | `config/image_whitelist.json` | `curl http://<staging-registry>:5000/v2/<image>/tags/list` | `[ ]` |
| 8 | Persistent storage directory writable | Ops | **YES** | `data/` path | `touch data/test-write && rm data/test-write` | `[ ]` |
| 9 | Verifier credential root created with chmod 700 | Ops | **YES** | `LABGEN_VERIFIER_CREDENTIAL_ROOT` | `stat <path>` | `[ ]` |
| 10 | All secrets injected via secret manager | Ops | **YES** | Multiple (see Section G) | `python scripts/labgen_staging_provisioning_validate.py` | `[ ]` |
| 11 | LLM provider disabled | Ops | **YES** | `LABGEN_LLM_PROVIDER_MODE=fake_only` | Provisioning validator + adapter status endpoint | `[ ]` |
| 12 | Provisioning validator passes (no blocking issues) | Operator | **YES** | `scripts/labgen_staging_provisioning_validate.py` | `python scripts/labgen_staging_provisioning_validate.py --env-file .env.staging` | `[ ]` |
| 13 | Staging dry run passes | Operator | **YES** | `scripts/labgen_staging_dry_run.py` | `python scripts/labgen_staging_dry_run.py --env-file .env.staging --base-url http://<staging-host>:8000` | `[ ]` |
| 14 | Rollback plan reviewed | Operator | **YES** | `CONTROLLED_STAGING_TRIAL_v0.1.md` Section F | Manual review | `[ ]` |

---

## J. Trial Unblock Criteria

All of the following must be satisfied before Controlled Staging Trial v0.1 live execution can proceed.

| # | Criterion | How to verify |
|---|-----------|---------------|
| J-1 | Preflight PASS (no blocking issues) | `python scripts/labgen_production_preflight.py` → `Overall: PASS` or `WARN` |
| J-2 | Staging dry run PASS | `python scripts/labgen_staging_dry_run.py --env-file .env.staging --json` → `"overall": "pass"` or `"warning"` |
| J-3 | Runtime adapter `production_safe=true` | `GET /api/labgen/runtime/adapter-status` → `namespace_adapter_kind=k8s`, `production_safe=true` |
| J-4 | LLM live disabled | `GET /api/labgen/llm-provider/status` → `live_enabled=false` |
| J-5 | Registry image readiness check reachable | `POST /api/labgen/drafts/{id}/validate` with known-image draft → `image_check_status` not `registry_unreachable` |
| J-6 | Verifier credential root writable and deletable | `stat <LABGEN_VERIFIER_CREDENTIAL_ROOT>` + write/delete test |
| J-7 | Storage persistent across service restart | Write test data → restart service → verify data present |
| J-8 | Staging test lab (published draft) available | `GET /api/lab-catalog` → at least one published lab |
| J-9 | Rollback path defined and reviewed | Section F of `CONTROLLED_STAGING_TRIAL_v0.1.md` read by operator |
| J-10 | Provisioning validator passes (no blocking issues) | `python scripts/labgen_staging_provisioning_validate.py --env-file .env.staging` → exit code 0 |

**If any criterion is unmet:** mark trial BLOCKED, do not proceed with Phase 3+ of the trial runbook.

---

## Validation Helper Quick Reference

```bash
# Validate the example template (no live connections)
python scripts/labgen_staging_provisioning_validate.py

# Validate a real staging env file
python scripts/labgen_staging_provisioning_validate.py \
    --env-file .env.staging

# JSON output for CI
python scripts/labgen_staging_provisioning_validate.py \
    --env-file .env.staging \
    --json

# Quiet (exit code only — 0=pass, 1=blocking, 2=file-not-found)
python scripts/labgen_staging_provisioning_validate.py \
    --env-file .env.staging \
    --quiet
```

The validator performs **static checks only** — no K3s, Proxmox, or registry connections.

---

*This document is the authoritative provisioning plan for LabGen MVP Controlled Staging Trial v0.1.*  
*No live provisioning has been performed. No real secrets are present in this document.*  
*See `CONTROLLED_STAGING_TRIAL_v0.1.md` for the trial runbook to execute once provisioning is complete.*
