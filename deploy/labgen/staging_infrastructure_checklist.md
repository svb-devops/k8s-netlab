# LabGen MVP — Staging Infrastructure Checklist

> **Status**: K8S_ARTICLE_TO_LAB_ADMIN_REHEARSAL_PASSED_WITH_NOTES (2026-06-17) — K3S_SMOKE_PASSED; RUNTIME_SESSION_SMOKE_PASSED_WITH_NOTES; First Pilot Lab RELEASED; First Pilot User ONBOARDED_WITH_NOTES; Pilot Feedback TRIAGED; Frontend Learner Smoke PASSED_WITH_NOTES; Second/Third/Fourth/Fifth/Sixth/Seventh/Eighth Pilot Users ONBOARDED; Deployment Lab READY; Small Cohort Gates COMPLETE; Real Human Learner REAL_HUMAN_LEARNER_VALIDATED_WITH_NOTES; Learner kubectl Terminal LEARNER_KUBECTL_TERMINAL_READY; Terminal Runtime Hardening TERMINAL_RUNTIME_HARDENED_WITH_NOTES; Real Human Labs 2-4 Re-validation REAL_HUMAN_LABS_2_4_VALIDATED_WITH_NOTES; Real Human Cohort Round 2 REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES; Small Customer Pilot Preparation Gate SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES; Small Customer Pilot Execution SMALL_CUSTOMER_PILOT_BLOCKED; Article-to-Lab Pipeline Design Gate ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES; Article-to-Lab Implementation Prerequisites ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES; Article-to-Lab MVP Contract Schema Gate ARTICLE_TO_LAB_SCHEMA_READY_WITH_NOTES; Article-to-Lab Draft Mode Implementation K8S_ARTICLE_TO_LAB_DRAFT_MODE_READY_WITH_NOTES; **Admin Review Rehearsal K8S_ARTICLE_TO_LAB_ADMIN_REHEARSAL_PASSED_WITH_NOTES**  
> **Updated**: 2026-06-17 — Admin Review Rehearsal COMPLETE: K8S_ARTICLE_TO_LAB_ADMIN_REHEARSAL_PASSED_WITH_NOTES — 4 samples verified; MEDIUM-001 fixed (PatchArticleDraftRequest + _ALLOWED_UPDATE_KEYS + PATCH extraction); 53 new rehearsal tests; 3623 total tests pass; 93.59% coverage; 0 LLM calls; recommended next step: K8s Article-to-Lab Internal Rehearsal to Publish Candidate; see `docs/labgen/K8S_ARTICLE_TO_LAB_ADMIN_REVIEW_REHEARSAL_RESULT_v0.1.md`  
> **Basis**: `docs/labgen/STAGING_ENVIRONMENT_PROVISIONING_v0.1.md`  
> **Purpose**: Track provisioning of each infrastructure component required for  
> Controlled Staging Trial v0.1 live execution  
> **Live run result**: `docs/labgen/CONTROLLED_STAGING_TRIAL_LIVE_RUN_RESULT_v0.1.md`  
> **Ops handoff**: `docs/labgen/STAGING_OPS_HANDOFF_v0.1.md`  
> **No real secrets in this file** — use `<set-in-secret-manager>` or `<placeholder>` only  

---

## Instructions

1. Make a working copy of this file (e.g. `staging_infrastructure_checklist_YYYYMMDD.md`).
2. Fill in the **Owner** and **Status** columns as each item is provisioned.
3. Record the **Validation Result** — the actual output of the validation command.
4. Once all items are `[x]`, run the provisioning validator and trial dry run.
5. Keep the completed copy as evidence — do not discard after the trial.

---

## Blocking Items from First Live Run (2026-06-12)

The first controlled staging live run was executed on 2026-06-12 and returned **LIVE\_TRIAL\_BLOCKED**.
The following items must be resolved before the trial can proceed. See
`docs/labgen/CONTROLLED_STAGING_TRIAL_LIVE_RUN_RESULT_v0.1.md` Section F for full detail.

| Blocker ID | Item | Config Key | Responsible | Secret injected? | Required before rerun? |
|------------|------|------------|-------------|------------------|------------------------|
| F-1 | K3s kubeconfig not injected | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Ops | `[x]` DONE | **RESOLVED** (2026-06-13) — `/etc/labgen/home_lab_mvp.kubeconfig`, chmod 600, K3S_SMOKE_PASSED. VM 401 (`labgen-home-k3s-staging-01`), K3s v1.34.4. |
| F-2 | Staging Proxmox pool not created | `PROXMOX_POOL=k8s-netlab-staging` | Ops | N/A | **RESOLVED** (2026-06-13) — pool `k8s-netlab-staging` created; VM 401 in pool. |
| F-3 | `ADMIN_TOKEN` not set | `ADMIN_TOKEN` | Ops | `[ ]` | **YES** |
| F-4 | `PROXMOX_TOKEN_SECRET` is placeholder | `PROXMOX_TOKEN_SECRET` | Ops | `[ ]` | **YES** |
| F-5 | `VM_SSH_PASSWORD` is placeholder | `VM_SSH_PASSWORD` | Ops | `[ ]` | **YES** |
| F-6 | Staging image registry not provisioned | `VM_REGISTRY_MIRROR` | Ops | N/A | **YES** |
| F-7 | Staging storage mount not confirmed | `data/` path, `LABGEN_VERIFIER_CREDENTIAL_ROOT` | Ops | N/A | **YES** |

**Quick check** (run after filling `.env.staging`):
```bash
python scripts/labgen_staging_missing_inputs.py --env-file <staging-env-file>
# Exit 0 = all blocking inputs are set
# Exit 1 = still missing inputs (shows grouped list)
```

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
| K-1 | Staging K3s cluster created (dedicated, staging-only) | Ops | **YES** | — | `kubectl version --kubeconfig <path>` | `[x]` | v1.34.4+k3s1, node Ready (2026-06-13) | VM 401 `labgen-home-k3s-staging-01` |
| K-2 | K3s cluster endpoint reachable from backend host | Ops | **YES** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | `kubectl cluster-info --kubeconfig <path>` | `[x]` | REACHABLE — Python K8s API verified (2026-06-13) | host→VM:6443, TLS OK |
| K-3 | Service account created for LabGen namespace lifecycle | Ops | **YES** | — | `kubectl get sa -n kube-system` | `[x]` | K3s admin credential used via kubeconfig | smoke verifier RoleBinding PASS |
| K-4 | ClusterRole / Role with namespace + rolebinding perms applied | Ops | **YES** | — | `kubectl get clusterrole labgen-ns-lifecycle` | `[x]` | namespace-scoped RoleBinding created/verified by smoke | K3S_SMOKE_PASSED |
| K-5 | SA can create namespaces | Ops | **YES** | — | `kubectl auth can-i create namespaces --as=...` | `[x]` | Namespace `lab-stg-smoke-*` created in smoke | phase3_namespace_create PASS |
| K-6 | SA can delete namespaces | Ops | **YES** | — | `kubectl auth can-i delete namespaces --as=...` | `[x]` | Namespace deleted in smoke | phase8_namespace_delete PASS |
| K-7 | SA can create/delete rolebindings in lab namespaces | Ops | **YES** | — | `kubectl auth can-i create rolebindings --as=...` | `[x]` | RoleBinding created/verified in smoke | phase5/6 PASS |
| K-8 | Kubeconfig generated and stored in secret manager | Ops | **YES** | — | Secret manager lookup | `[x]` | `/etc/labgen/home_lab_mvp.kubeconfig`, chmod 600 (not committed) | 2026-06-13 |
| K-9 | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` set to absolute path in `.env` | Operator | **YES** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/etc/labgen/home_lab_mvp.kubeconfig` | smoke precheck phase2 | `[x]` | phase2_precheck PASS | `/etc/labgen/home_lab_mvp.env` |
| K-10 | Kubeconfig file has restricted permissions (not world-readable) | Operator | **YES** | — | `stat <path>` → permissions 0600 or 0400 | `[x]` | 600 (verified) | 2026-06-13 |
| K-11 | Namespace cleanup works: smoke cleanup confirmed | Ops | YES | — | smoke cleanup | `[x]` | `cleanup_confirmed: true`, residue NONE | K3S_SMOKE_PASSED |

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

| # | Item | Owner | Required? | Required before rerun? | Config Key | Validation Command | Secret injected? | Status | Validation Result | Notes |
|---|------|-------|-----------|------------------------|------------|--------------------|-----------------|--------|-------------------|-------|
| C-1 | `ADMIN_TOKEN` injected (≥ 32 chars) | Ops | **YES** | **YES — F-3 BLOCKER** | `ADMIN_TOKEN=<set-in-secret-manager>` | `echo ${#ADMIN_TOKEN}` → ≥ 32 | `[ ]` | `[ ]` | | Never in plaintext file |
| C-2 | `LABGEN_RUNTIME_MODE=production` in `.env.staging` | Operator | **YES** | YES | `LABGEN_RUNTIME_MODE=production` | `grep LABGEN_RUNTIME_MODE .env.staging` | N/A | `[ ]` | | |
| C-3 | `LABGEN_NAMESPACE_ADAPTER=k8s` in `.env.staging` | Operator | **YES** | YES | `LABGEN_NAMESPACE_ADAPTER=k8s` | `grep LABGEN_NAMESPACE_ADAPTER .env.staging` | N/A | `[ ]` | | |
| C-4 | `LABGEN_LLM_PROVIDER_MODE=fake_only` in `.env.staging` | Operator | **YES** | YES | `LABGEN_LLM_PROVIDER_MODE=fake_only` | `grep LABGEN_LLM_PROVIDER_MODE .env.staging` | N/A | `[ ]` | | Must NOT be `live_enabled` |
| C-5 | `LABGEN_LLM_OPENAI_API_KEY` is NOT set (or unset) | Operator | **YES** | YES | — | `echo ${LABGEN_LLM_OPENAI_API_KEY:-UNSET}` → UNSET | N/A | `[ ]` | | LLM disabled; no key needed |
| C-6 | `SESSION_COOKIE_SECURE` value appropriate for staging TLS setup | Operator | YES | NO | `SESSION_COOKIE_SECURE=false` (no TLS) or `true` (TLS) | Config review | N/A | `[ ]` | | |
| C-7 | `ALLOWED_ORIGINS` set to staging host only | Operator | YES | YES | `ALLOWED_ORIGINS=http://<staging-host>:8000` | Config review | N/A | `[ ]` | | |
| C-8 | `ADMIN_USERNAMES` set (non-empty) | Operator | YES | NO | `ADMIN_USERNAMES=admin` | Config review | N/A | `[ ]` | | |
| C-9 | No production credentials in `.env.staging` | Operator | **YES** | YES | — | Manual inspection + provisioning validator | N/A | `[ ]` | | |

---

## Phase 6 — Validation

| # | Item | Owner | Required? | Validation Command | Validated by script? | Status | Validation Result | Notes |
|---|------|-------|-----------|--------------------|--------------------|--------|-------------------|-------|
| V-0b | **Secret injection verify exits 0** (per-key status check — run before V-0a) | Operator | **YES** | `python scripts/labgen_ops_secret_injection_verify.py --env-file .env.staging --json` | `labgen_ops_secret_injection_verify.py` | `[ ]` | | Decision must be `SECRET_INJECTION_READY` |
| V-0c | **Ticket pack all VERIFIED** (per-ticket wrapper — run after V-0b) | Operator | **YES** | `python scripts/labgen_ops_ticket_verify.py --env-file .env.staging --all --json` | `labgen_ops_ticket_verify.py` | `[ ]` | | All 6 tickets must show `"status": "VERIFIED"`; see `deploy/labgen/staging_ops_ticket_status.md` |
| V-0a | **Intake verification gate exits 0** (unified gate: all phases in one command) | Operator | **YES** | `python scripts/labgen_ops_staging_intake_verify.py --env-file .env.staging --json` | `labgen_ops_staging_intake_verify.py` | `[ ]` | | Decision must be `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL` |
| V-0 | Missing inputs helper exits 0 | Operator | **YES** | `python scripts/labgen_staging_missing_inputs.py --env-file .env.staging` | `labgen_staging_missing_inputs.py` | `[ ]` | | Exit 0 = all blocking inputs set |
| V-1 | Provisioning validator passes (exit code 0) | Operator | **YES** | `python scripts/labgen_staging_provisioning_validate.py --env-file .env.staging` | `labgen_staging_provisioning_validate.py` | `[ ]` | | No blocking issues |
| V-2 | Preflight passes (exit code 0 or warnings only) | Operator | **YES** | `python scripts/labgen_production_preflight.py --env-file .env.staging` | `labgen_production_preflight.py` | `[ ]` | | Warnings acceptable |
| V-3 | Staging dry run passes | Operator | **YES** | `python scripts/labgen_staging_dry_run.py --env-file .env.staging --base-url http://<staging-host>:8000 --json` | `labgen_staging_dry_run.py` | `[ ]` | | `"overall": "pass"` or `"warning"` |
| V-4 | Backend starts without errors | Operator | **YES** | Check stdout / journalctl for ERROR lines | Manual | `[ ]` | | |
| V-5 | `GET /api/labgen/runtime/adapter-status` → `production_safe=true` | Operator | **YES** | `curl -H "X-Admin-Token: $ADMIN_TOKEN" http://<staging-host>:8000/api/labgen/runtime/adapter-status` | Manual | `[ ]` | | |
| V-6 | `GET /api/labgen/llm-provider/status` → `live_enabled=false` | Operator | **YES** | `curl -H "X-Admin-Token: $ADMIN_TOKEN" http://<staging-host>:8000/api/labgen/llm-provider/status` | Manual | `[ ]` | | |
| V-7 | No sensitive patterns in any diagnostic response | Operator | **YES** | Visual inspection of all diagnostic responses | Manual | `[ ]` | | `sk-ant-`, `-----BEGIN`, `client-certificate-data:` must be absent |

---

## Phase 7 — Trial Readiness Gate

All of the following must be `[x]` before proceeding to Controlled Staging Trial v0.1 Phase 3+.

### Intake Verification Gate (run first — unified pre-check)

| # | Gate | Verified by | Evidence Path | Intake Decision | Intake Verified? | Ready for live rerun? |
|---|------|-------------|---------------|----------------|-----------------|----------------------|
| G-0b | **Secret Injection Verification exits 0** | `labgen_ops_secret_injection_verify.py` | `docs/labgen/OPS_SECRET_INJECTION_VERIFICATION_RESULT_v0.1.md` | `SECRET_INJECTION_BLOCKED` (2026-06-12) | `[ ]` | `[ ]` |
| G-0c | **Ticket Pack all VERIFIED** | `labgen_ops_ticket_verify.py` | `deploy/labgen/staging_ops_ticket_status.md` | All TODO (2026-06-12) | `[ ]` | `[ ]` |
| G-0a | **Ops Staging Intake Verification Gate exits 0** | `labgen_ops_staging_intake_verify.py` | `docs/labgen/OPS_STAGING_INTAKE_VERIFICATION_RESULT_v0.1.md` | `BLOCKED_MISSING_INPUTS` (2026-06-12) | `[ ]` | `[ ]` |

Run command:
```bash
python scripts/labgen_ops_staging_intake_verify.py \
    --env-file <staging-env-file> \
    --base-url <staging-host> \
    --json > intake_verify_result_$(date +%Y%m%d).json
```

**Intake decision must be `READY_TO_RERUN_CONTROLLED_STAGING_TRIAL` before proceeding.**

### Individual Gate Items

| # | Gate | Satisfied? |
|---|------|------------|
| G-0 | Missing inputs helper: exit code 0 (all blocking inputs set) | `[ ]` |
| G-1 | All Phase 1–6 items are `[x]` | `[ ]` |
| G-2 | Provisioning validator: exit code 0 (no blocking issues) | `[ ]` |
| G-3 | Staging dry run: `"overall": "pass"` or `"warning"` | `[ ]` |
| G-4 | Runtime adapter status: `production_safe=true`, `namespace_adapter_kind=k8s` | `[ ]` |
| G-5 | LLM provider status: `live_enabled=false` | `[ ]` |
| G-6 | Rollback plan reviewed (Section F of `CONTROLLED_STAGING_TRIAL_v0.1.md`) | `[ ]` |
| G-7 | STAGING_USER_SESSION available (for Phase 4 runtime start) | `[ ]` |
| G-8 | Published staging lab draft available in lab catalog | `[ ]` |
| G-9 | **K3s Adapter Smoke: K3S_SMOKE_PASSED or K3S_SMOKE_PASSED_WITH_NOTES** | `[x]` — **K3S_SMOKE_PASSED** (2026-06-13); VM 401 K3s v1.34.4; see `docs/labgen/CONTROLLED_K3S_ADAPTER_SMOKE_RESULT_v0.1.md` |
| G-10 | **Runtime Session Smoke: RUNTIME_SESSION_SMOKE_PASSED or PASSED_WITH_NOTES** | `[x]` — **RUNTIME_SESSION_SMOKE_PASSED_WITH_NOTES** (2026-06-13); full create→step-check→complete→cleanup cycle; LAB_CLOSED+cleanup_verified=true; see `docs/labgen/CONTROLLED_HOME_LAB_RUNTIME_SESSION_SMOKE_RESULT_v0.1.md` |
| G-11 | **Pilot Gate: PILOT_GATE_READY or PILOT_GATE_READY_WITH_NOTES** | `[x]` — **PILOT_GATE_READY_WITH_NOTES** (2026-06-13); VM 400 cleaned; all residuals clear; verifier client not exercised (note); 0 published labs (pre-pilot action required); see `docs/labgen/HOME_LAB_MVP_PILOT_GATE_RESULT_v0.1.md` |
| G-12 | **First Pilot User Onboarding: FIRST_PILOT_USER_ONBOARDED or FIRST_PILOT_USER_ONBOARDED_WITH_NOTES** | `[x]` — **FIRST_PILOT_USER_ONBOARDED_WITH_NOTES** (2026-06-14); pilot-user-01 completed full lab flow; LAB_CLOSED; cleanup_verified=True; 3 bugs discovered and fixed; 3137 tests pass, 93.12% coverage; see `docs/labgen/FIRST_PILOT_USER_ONBOARDING_RESULT_v0.1.md` |
| G-13 | **Pilot Feedback Triage: PILOT_FEEDBACK_TRIAGED or PILOT_FEEDBACK_TRIAGED_WITH_BLOCKERS** | `[x]` — **PILOT_FEEDBACK_TRIAGED** (2026-06-14); 0 BLOCKER, 0 HIGH; 3 MEDIUM bugs resolved with regression tests; 2 LOW (sync cleanup latency, orphan tracker entry); 5 NOTE (frontend untested, feedback insufficient, single verifier type, env drift risk, portability); second pilot user allowed (precondition: frontend smoke test); see `docs/labgen/PILOT_FEEDBACK_TRIAGE_v0.1.md` |
| G-14 | **Frontend Learner Pilot Smoke: FRONTEND_LEARNER_SMOKE_PASSED or FRONTEND_LEARNER_SMOKE_PASSED_WITH_NOTES** | `[x]` — **FRONTEND_LEARNER_SMOKE_PASSED_WITH_NOTES** (2026-06-14); 16 PASS 0 FAIL; 12 bugs fixed; vm_id auto-discovery; cleanup_verified=True; 3139 tests, 93.13%; second pilot user unblocked; see `docs/labgen/FRONTEND_LEARNER_PILOT_SMOKE_RESULT_v0.1.md` |
| G-15 | **Second Trusted Pilot User Gate: SECOND_PILOT_USER_ONBOARDED** | `[x]` — **SECOND_PILOT_USER_ONBOARDED** (2026-06-14); 23 PASS 0 FAIL 0 NOTE; pilot-user-02 real frontend; cleanup_verified=True; ops gap documented (host-side verifier init); third user allowed; see `docs/labgen/SECOND_PILOT_USER_ONBOARDING_RESULT_v0.1.md` |
| G-16 | **Ops Runbook Hardening: OPS_RUNBOOK_HARDENED** | `[x]` — **OPS_RUNBOOK_HARDENED** (2026-06-14); `HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md` created; OPS-INIT-001 documented; initialize_verifier_for_vm_host_side specified; QEMU-agent path explicitly forbidden for home_lab_mvp; 31 guardrail tests; VM recovery + emergency stop + cloud portability covered; third pilot user onboarding now unblocked |
| G-17 | **Third Trusted Pilot User Gate: THIRD_PILOT_USER_ONBOARDED** | `[x]` — **THIRD_PILOT_USER_ONBOARDED** (2026-06-14); pilot-user-03; real frontend; Step 1 (namespace_exists) PASS; Complete→LAB_CLOSED; cleanup_verified=True; VM 401 rebuilt per Runbook D.5; all residuals clean; second lab rehearsal PASS; see `docs/labgen/THIRD_PILOT_USER_ONBOARDING_RESULT_v0.1.md` |
| G-18 | **Fourth Trusted Pilot User — Second Lab: FOURTH_PILOT_USER_SECOND_LAB_ONBOARDED** | `[x]` — **FOURTH_PILOT_USER_SECOND_LAB_ONBOARDED** (2026-06-14); pilot-user-04; real frontend; Step 1 (namespace_exists) PASS + Step 2 (configmap_exists name=my-app-config) PASS; both first attempt; LAB_CLOSED; cleanup_verified=True; residual check 11/11 PASS; 0 LLM calls; configmap_exists verifier real-user validated; see `docs/labgen/FOURTH_PILOT_USER_SECOND_LAB_RESULT_v0.1.md` |
| G-19 | **Second Lab Feedback Triage: SECOND_LAB_FEEDBACK_TRIAGED_WITH_ITERATION** | `[x]` — **SECOND_LAB_FEEDBACK_TRIAGED_WITH_ITERATION** (2026-06-14); 0 BLOCKER/HIGH; 1 MEDIUM + 3 LOW fixed (verifier detail messages for all 6 types); VerifierService._make_detail() added; 11 new tests; internal rehearsal PASS (detail='ConfigMap "my-app-config" was found…'; LAB_CLOSED; cleanup_verified=True); 4 NOTE open (progress indicator, objectives, ops burden); 3181 tests; 93.13%; 5th user + 3rd lab unlocked; see `docs/labgen/SECOND_LAB_FEEDBACK_TRIAGE_v0.1.md` |
| G-20 | **Real Human Cohort Round 2: REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES** | `[x]` — **REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES** (2026-06-16); 2 real learners × 4 labs = 8 sessions; 8/8 LAB_CLOSED; 100% step-check first-pass; 0 step failures; 0 residuals; all security checks PASS; 1 MEDIUM resolved live (422 no_vm_assigned — VM ownership gap); Sections 3–10 PENDING; 0 LLM calls; production VMID 500-599 UNTOUCHED; see `docs/labgen/REAL_HUMAN_COHORT_ROUND2_RESULT_v0.1.md` |
| G-21 | **Small Customer Pilot Preparation Gate: SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES** | `[x]` — **SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES** (2026-06-16); VM ownership/assignment runbook gap fixed (Runbook §K); pilot scope + customer criteria + pre-pilot technical gate + onboarding notice + feedback template (12Q) + emergency stop conditions + North Star alignment all defined; Sections 3–10 qualitative feedback still PENDING (non-blocking for technical prep); 0 code changes; ready to enter Small Customer Pilot Execution; see `docs/labgen/SMALL_CUSTOMER_PILOT_PREPARATION_GATE_v0.1.md` |
| G-22 | **Small Customer Pilot Execution: SMALL_CUSTOMER_PILOT_BLOCKED** | `[x]` — **SMALL_CUSTOMER_PILOT_BLOCKED** (2026-06-16); Pre-Pilot Gate all PASS; blocker: NO_SUITABLE_SMALL_CUSTOMER (28 users all test/dev accounts); system technically ready; awaiting customer identification; see `docs/labgen/SMALL_CUSTOMER_PILOT_RESULT_v0.1.md` |
| G-23 | **Article-to-Lab Pipeline Design Gate: ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES** | `[x]` — **ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES** (2026-06-16); full pipeline designed — Feasibility Gate (3 tiers) + Draft Lab Contract schema (source_grounding, unsupported_inferences, admin_decision) + Admin Review + StaticValidator 5 new checks + Domain Adapter interfaces (K8s complete; Linux/Docker/Networking/Database designed) + Verifier Strategy (5 candidate states) + Cleanup/Credential lifecycle + Safety Policy; existing K8s reuse fully mapped; 3 go/no-go blockers identified (N-01/N-02/N-03) — resolved in G-24; 0 LLM calls; 0 code changes; production VMID 500-599 UNTOUCHED; see `docs/labgen/ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` |
| G-24 | **Article-to-Lab Implementation Prerequisites: ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES** | `[x]` — **ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES** (2026-06-16); N-01 RESOLVED: v0.1 stub mode (no live LLM), `LLMProviderPort` abstract interface, fail-closed rules, self-hosted ruled out on T430; N-02 RESOLVED: ephemeral source text, persistent: content_hash+source_metadata+feasibility_result+source_grounding_snippets+contract, sensitive content immediate discard; N-03 RESOLVED: user consent required per submission, ephemeral raw text, 30-day rejection metadata, audit indefinite (hash+decision); all 3 blockers resolved; implementation may start; next gate: Article-to-Lab MVP Contract Schema Gate; 0 LLM calls; 0 code changes; production VMID 500-599 UNTOUCHED; see `docs/labgen/ARTICLE_TO_LAB_IMPLEMENTATION_PREREQUISITES_v0.1.md` |

**If G-0a is `[ ]` (intake gate not READY): trial is BLOCKED. Do not run Phase 3+.**  
**If any other gate is `[ ]`: trial is BLOCKED. Do not proceed with Phase 3+ of the trial runbook.**

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
| `scripts/labgen_ops_secret_injection_verify.py` | **Phase 6, V-0b (run first — per-key secret status)** | Per-key injection status for 7 required secrets (offline, no network) |
| `scripts/labgen_ops_ticket_verify.py` | **Phase 6, V-0c (run after V-0b — per-ticket status)** | Per-ticket VERIFIED/BLOCKED status for 6 ops provisioning tickets (offline, no network) |
| `scripts/labgen_ops_staging_intake_verify.py` | **Phase 6, V-0a (run after V-0b/V-0c — unified gate)** | All phases in sequence: missing inputs + provisioning + preflight + dry run + optional diagnostics |
| `scripts/labgen_staging_missing_inputs.py` | Phase 6, V-0 (detail check) | Which blocking inputs are missing or placeholder (offline) |
| `scripts/labgen_staging_provisioning_validate.py` | Phase 6, V-1 | Static env file safety (offline) |
| `scripts/labgen_production_preflight.py` | Phase 6, V-2 | Runtime config against current env (offline) |
| `scripts/labgen_staging_dry_run.py` | Phase 6, V-3 | Live service diagnostics (online, safe GETs only) |
| `scripts/labgen_controlled_k3s_adapter_smoke.py` | **Before trial — K3S smoke gate** | Namespace lifecycle smoke: create/verify/rolebinding/delete (precheck-only by default; `--allow-k8s-write` to execute) |
| `scripts/labgen_controlled_staging_trial.py` | Trial Phase 0 | Full trial execution (with explicit allow flags) |

---

*This checklist contains no real secrets. All placeholders use `<angle-bracket>` format.*  
*Keep a completed copy as provisioning evidence for the trial record.*

---

This gate remains aligned with PROJECT_NORTH_STAR_v0.1: Article-to-Lab / Technical Content-to-Experiment Platform, "读完即练，结果说话". K8s domain proof for the broader Article-to-Lab platform.

## North Star Alignment Check

| Check | Status |
|-------|--------|
| Still serving Article-to-Lab | YES |
| Still supports "读完即练，结果说话" | YES |
| Avoids K8s-only hardcoding | YES — adapter boundaries unchanged |
| Preserves Linux/domain portability | YES |
| No skipped human review | YES |
| No skipped StaticValidator | YES |
| No skipped cleanup | YES |
| No premature public launch expansion | YES |
| No home_lab_mvp → production promotion | YES |
