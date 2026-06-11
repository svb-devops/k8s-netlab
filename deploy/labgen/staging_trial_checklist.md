# LabGen Controlled Staging Trial — Execution Checklist v0.1

> **Trial date**: ___________________  
> **Operator**: ___________________  
> **Staging host**: `<staging-host>` (fill in before trial)  
> **Commit**: ___________________  
> **Status**: ☐ READY TO START  ☐ IN PROGRESS  ☐ PASSED  ☐ FAILED  ☐ BLOCKED  

> **IMPORTANT**: This checklist must NOT contain real secrets, kubeconfigs, cluster tokens,
> or production credentials. Use `<staging-host>` for IPs/hostnames,
> `<placeholder>` or `<staging-only>` for credentials.

---

## Precondition Sign-Off (Phase 0)

| # | Precondition | Status | Evidence / Notes |
|---|-------------|--------|-----------------|
| B-1 | Staging K3s cluster endpoint reachable | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-2 | Staging kubeconfig / SA injected via secret manager | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-3 | Namespace lifecycle permissions scoped to staging | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-4 | Staging internal image registry reachable | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-5 | Image resolution config maps to staging registry | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-6 | Verifier credential root is staging-only absolute path | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-7 | `LABGEN_RUNTIME_MODE=production` confirmed | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-8 | `LABGEN_NAMESPACE_ADAPTER=k8s` confirmed | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-9 | `LABGEN_LLM_PROVIDER_MODE=fake_only` confirmed | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-10 | Demo seed endpoint admin-only, not auto-seeded | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-11 | Storage is staging-only (not shared with production) | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-12 | Frontend static serving points to staging backend | ☐ PASS ☐ FAIL ☐ SKIP | |
| B-13 | Rollback config and procedure reviewed | ☐ PASS ☐ FAIL ☐ SKIP | |

**Proceed to Phase 1 only if ALL preconditions are PASS.**

---

## Phase 0 — Config and Preflight

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P0-01 | `python scripts/labgen_production_preflight.py` | Overall: PASS (warnings OK) | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P0-02 | `python scripts/labgen_staging_dry_run.py --env-file .env.staging --base-url http://<staging-host>:8000` | Overall: PASS or WARN | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P0-03 | `python scripts/labgen_controlled_staging_trial.py --env-file .env.staging --base-url http://<staging-host>:8000 --json` | `"overall":"pass"` or `"warning"`, no `"blocking"` checks | | ☐ PASS ☐ FAIL ☐ SKIP | |

---

## Phase 1 — Service Boot

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P1-01 | `uvicorn backend.main:app --host 0.0.0.0 --port 8000` | Service starts, no startup errors | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P1-02 | `journalctl -u k8s-netlab -p err` (or stdout ERROR lines) | No ERROR lines at startup | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P1-03 | `GET http://<staging-host>:8000/api/health` | 200 or 500 (no Proxmox = acceptable) | | ☐ PASS ☐ WARN ☐ FAIL ☐ SKIP | Health may fail without Proxmox |

---

## Phase 2 — Admin Diagnostics

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P2-01 | `GET /api/labgen/contract-pack` (X-Admin-Token) | 200, `version=v0.1`, ≥10 endpoints, no sensitive patterns | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P2-02 | `GET /api/labgen/runtime/adapter-status` (X-Admin-Token) | `namespace_adapter_kind=k8s`, `production_safe=true` | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P2-03 | `GET /api/labgen/llm-provider/status` (X-Admin-Token) | `live_enabled=false` | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P2-04 | `POST /api/labgen/runtime/expire-sessions` `{"dry_run":true}` | 200, no mutations, no sensitive patterns | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P2-05 | Scan all Phase 2 responses for sensitive patterns | No `sk-ant-`, `-----BEGIN`, `client-certificate-data:` | | ☐ PASS ☐ FAIL ☐ SKIP | |

---

## Phase 3 — Image Readiness Publish Gate

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P3-01 | Create test draft with READY images | Draft created, ID recorded | | ☐ PASS ☐ FAIL ☐ SKIP | Draft ID: |
| CST-P3-02 | `GET /api/labgen/drafts/<ready-id>/publish-decision` | `status=ALLOWED` | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P3-03 | Create test draft with BLOCKED images | Draft created, ID recorded | | ☐ PASS ☐ FAIL ☐ SKIP | Draft ID: |
| CST-P3-04 | `GET /api/labgen/drafts/<blocked-id>/publish-decision` | `status=BLOCKED` | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P3-05 | `POST /api/labgen/drafts/<blocked-id>/publish` | HTTP 409, publish refused | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P3-06 | `POST /api/labgen/drafts/<ready-id>/publish` | HTTP 200, `publish_status=published` | | ☐ PASS ☐ FAIL ☐ SKIP | Published lab ID: |
| CST-P3-07 | Learner catalog: `GET /api/labs` | Contains published lab, not blocked draft | | ☐ PASS ☐ FAIL ☐ SKIP | |

---

## Phase 4 — Controlled Runtime Start

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P4-01 | Run trial helper with `--allow-runtime-start --staging-lab-draft-id <id>` | Trial report phase=runtime shows PASS (201) or WARN (422, K3s not configured) | | ☐ PASS ☐ WARN ☐ FAIL ☐ SKIP | Session ID (if created): |
| CST-P4-02 | `kubectl get namespace lab-<session-id>` (if session created) | Namespace exists | | ☐ PASS ☐ FAIL ☐ SKIP ☐ N/A | |
| CST-P4-03 | Response contains no sensitive patterns | `sk-ant-`, `-----BEGIN`, token values absent | | ☐ PASS ☐ FAIL ☐ SKIP | |

---

## Phase 5 — Step Check / Snapshot / Complete

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P5-01 | `GET /api/lab-sessions/<id>/snapshot` | `status=LAB_ACTIVE` (if session exists), no sensitive fields | | ☐ PASS ☐ FAIL ☐ SKIP ☐ N/A | |
| CST-P5-02 | `POST /api/lab-sessions/<id>/steps/<step-id>/check` | Structured response, no sensitive patterns | | ☐ PASS ☐ WARN ☐ FAIL ☐ SKIP ☐ N/A | Step check may fail (K3s resources not deployed) |
| CST-P5-03 | Run trial helper with `--allow-cleanup-check --staging-session-id <id>` | Cleanup phase: PASS (200) or WARN (409) | | ☐ PASS ☐ WARN ☐ FAIL ☐ SKIP ☐ N/A | |

---

## Phase 6 — Timeout / Cleanup / Reclaim Negative Test

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P6-01 | Run trial helper with `--allow-timeout-expiry` | Expiry dry run: PASS (200, dry_run=true, no mutations) | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P6-02 | `POST /api/lab-sessions/<id>/abort` (if session exists) | 200, `status=LAB_ABORTED` or `LAB_CLOSED` | | ☐ PASS ☐ FAIL ☐ SKIP ☐ N/A | |
| CST-P6-03 | `kubectl get namespace lab-<id>` after cleanup | NotFound (namespace deleted) | | ☐ PASS ☐ FAIL ☐ SKIP ☐ N/A | |
| CST-P6-04 | `ls <staging-cred-root>/<vm-id>_verifier.yaml` after cleanup | File not found (credential reclaimed) | | ☐ PASS ☐ FAIL ☐ SKIP ☐ N/A | |

---

## Phase 7 — Audit and Safety Review

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P7-01 | `GET /api/lab-sessions/<id>/audit-events` | Events present, structured fields only | | ☐ PASS ☐ FAIL ☐ SKIP ☐ N/A | |
| CST-P7-02 | Scan audit events for sensitive patterns | No kubeconfig, credential path, stack trace, or token values | | ☐ PASS ☐ FAIL ☐ SKIP | |
| CST-P7-03 | Check logs for leaked secrets | No sensitive patterns in service logs | | ☐ PASS ☐ FAIL ☐ SKIP | |

---

## Phase 8 — Rollback Rehearsal

| Check ID | Command / Endpoint | Expected Result | Actual Result | Status | Evidence / Notes |
|----------|-------------------|-----------------|---------------|--------|-----------------|
| CST-P8-01 | Confirm stop command is ready: `systemctl stop k8s-netlab` | Command documented | | ☐ CONFIRMED ☐ SKIP | |
| CST-P8-02 | Confirm LLM is disabled: `live_enabled=false` (from Phase 2) | Confirmed | | ☐ CONFIRMED ☐ SKIP | |
| CST-P8-03 | Confirm namespace cleanup command ready | `kubectl delete namespace lab-<id>` | | ☐ CONFIRMED ☐ SKIP | |
| CST-P8-04 | Confirm credential reclaim command ready | `rm -f <cred-root>/<vm-id>_verifier.yaml` | | ☐ CONFIRMED ☐ SKIP | |
| CST-P8-05 | Confirm audit log backup command ready | `cp data/lab_audit.json /tmp/...` | | ☐ CONFIRMED ☐ SKIP | |

---

## Trial Result Summary

| Item | Value |
|------|-------|
| Trial date | |
| Operator | |
| Commit | |
| Phases completed | |
| Total checks run | |
| PASS | |
| WARN | |
| FAIL | |
| SKIP / N/A | |
| Overall verdict | ☐ PASSED  ☐ PASSED_WITH_WARNINGS  ☐ FAILED  ☐ BLOCKED |
| Blocking issues | |
| Next step | |

---

*Do NOT record real secrets, kubeconfigs, cluster tokens, or production credentials in this document.
Use `<staging-only>` or `<redacted>` for any credential references.*
