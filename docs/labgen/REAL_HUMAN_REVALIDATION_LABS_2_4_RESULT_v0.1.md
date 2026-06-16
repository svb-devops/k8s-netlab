# Real Human Re-validation for Labs 2–4 v0.1

**Validation date**: 2026-06-15
**Decision**: REAL_HUMAN_LABS_2_4_VALIDATED_WITH_NOTES
**Operator**: Claude Code acting as senior dev + ops
**Based on**: Real Human Learner Validation v0.1 — REAL_HUMAN_LEARNER_VALIDATED_WITH_NOTES (UX-H1: no kubectl terminal blocked Labs 2–4) → Terminal Post-Integration Runtime & Quality Hardening Gate v0.1 — TERMINAL_RUNTIME_HARDENED_WITH_NOTES
**Learner role**: User acting as learner-H1 (explicitly confirmed: operates frontend personally, no real secrets, no custom images, no replica scaling, no link sharing, understands MVP/no-SLA nature)
**No real secrets in this document.**

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Real learner | 1 (learner-H1, user acting as learner) |
| Labs attempted | 3 (Lab 2 ConfigMap Basics, Lab 3 Secret Basics, Lab 4 Deployment Basics) |
| Sessions | 3 (all LAB_CLOSED, cleanup_verified=True) |
| Final decision | **REAL_HUMAN_LABS_2_4_VALIDATED_WITH_NOTES** |
| Bugs found during validation | 4 (all fixed in-session, see Section E) |
| LLM calls | 0 |
| Production VMID 500–599 touched | NO |
| API-only simulation used | NO |
| Operator executed steps for learner | NO |

**What was confirmed by real human**:
Learner-H1 independently operated the kubectl web terminal across all three remaining published labs — typing real `kubectl create` / `get` / `describe` commands, reading the output, and clicking "Check Current Step" / "Complete Lab" without operator guidance. All three labs completed end-to-end (`LAB_CLOSED`, `cleanup_verified=True`, 0 residuals).

**Key finding**:
The terminal integration validated in the prior gate works for real usage, but the validation surfaced 4 real bugs that no prior operator-executed rehearsal had caught — 3 infrastructure/ops bugs (CDN caching, credential path, wrong provisioning function) and 1 platform logic bug (shared-VM credential reclaim wiping the next session's credentials). This is exactly the value real human validation is supposed to provide over operator-executed smoke tests.

---

## B. Authenticity Check

| Criterion | Status |
|-----------|--------|
| Learner is not Claude Code | PASS — real human (user, acting as learner-H1) |
| Operator did not execute steps for learner | PASS — learner typed all terminal commands and clicked all buttons |
| API-only simulation not used | PASS — real browser, real frontend, real kubectl web terminal |
| Learner operated frontend themselves | PASS — navigated session page, typed kubectl commands, clicked Check/Complete |
| Operator observations separated from learner quotes | PASS — see Section D |
| Feedback captured directly from learner | PASS — 6 questions answered directly by learner (Section D) |

---

## C. Per-Lab Results

### Lab 2 — ConfigMap Basics

| Field | Value |
|-------|-------|
| Session ID | `774ae02f-e7d3-4fde-af26-b7e6ec82dc76` |
| Step 1 (namespace_exists) | PASS |
| Step 2 (configmap_exists) | PASS |
| Terminal commands run | `kubectl create configmap`, `kubectl get configmap`, `kubectl describe configmap` |
| Cleanup | LAB_CLOSED, cleanup_verified=True |
| Residuals | 0 namespace, 0 tainted VM |
| Bugs encountered | Terminal panel did not initially appear (Cloudflare CDN cache, see E-1) |

### Lab 3 — Secret Basics

| Field | Value |
|-------|-------|
| Session ID | `955dfe1f-3f9d-41dc-b742-c77f77d80d77` |
| Step 1 (namespace_exists) | PASS (after credential fix, see E-2/E-3/E-4) |
| Step 2 (secret_exists `my-app-secret`) | PASS |
| Terminal commands run | `kubectl create secret generic app-secret ...` (wrong name, learner self-corrected), `kubectl get secrets`, `kubectl describe secret`, `kubectl get secret -o yaml` (blocked, see Section F), `kubectl create secret generic my-app-secret ...` |
| Cleanup | LAB_CLOSED, cleanup_verified=True |
| Residuals | 0 namespace, 0 tainted VM |
| Bugs encountered | Step 1 failed with `credential_missing` (see E-2/E-3/E-4); learner's first secret name was a learner error (`app-secret` instead of `my-app-secret`), not a platform bug |

### Lab 4 — Deployment Basics

| Field | Value |
|-------|-------|
| Session ID | `bbb866ad-53c3-4390-b6c3-964155555e4c` |
| Step 1 (namespace_exists) | PASS |
| Step 2 (deployment_ready `hello-deployment`) | PASS |
| Terminal commands run | `kubectl create deployment nginx-deployment` (missing `--image`, errored), `kubectl create deployment hello-deployment --image=nginx:1.25-alpine --replicas=1`, `kubectl get deployments`, `kubectl get pods` |
| Cleanup | LAB_CLOSED, cleanup_verified=True |
| Residuals | 0 namespace, 0 Deployment/Pod, 0 tainted VM |
| Bugs encountered | First `create deployment` attempt (missing `--image`) returned a confusing kubectl error (`flags cannot be placed before plugin name: --kubeconfig`) instead of the expected `required flag(s) "image" not set` — see F-1 (NOTE, not reproduced independently) |

---

## D. Learner Feedback (verbatim, self-reported)

| # | Question | Learner Response |
|---|----------|-------------------|
| 1 | Were the step instructions for Labs 2/3/4 clear? Any step where you read the description but didn't know what command to run? | 没有 (No — all clear) |
| 2 | When you hit `credential_missing`, did you think it was your own mistake or a system issue? | 系统问题 (System issue) |
| 3 | Was the `flags cannot be placed before plugin name` error from Lab 4 friendly/clear to a learner? | 不太友好 (Not very friendly) |
| 4 | Overall terminal experience across the 3 labs vs. Lab 1 (no terminal)? | 感觉非常棒 (Feels great) |
| 5 | Was the block message for `kubectl get secret -o yaml` clear? Did it confuse you? | 不会 (No confusion) |
| 6 | Would you continue using this platform / recommend it? Anything missing? | 会 (Yes, would continue) |

### Aggregate findings

| Dimension | Assessment | Evidence |
|-----------|-----------|----------|
| Step clarity (Labs 2–4) | CLEAR | Learner reported no step where instructions were unclear |
| Credential-error comprehension | CLEAR | Learner correctly identified `credential_missing` as a system issue, not user error |
| kubectl error message quality | MIXED | Real kubectl errors (image required) are acceptable; the plugin-resolution error is confusing (F-1) |
| Terminal experience | STRONG POSITIVE | "感觉非常棒" — terminal integration directly resolved the prior gate's HIGH finding (UX-H1) |
| Security block message clarity (`-o yaml`) | CLEAR | No confusion reported |
| Willingness to continue | POSITIVE | Learner would continue using the platform |

---

## E. Bugs Found and Fixed During Validation

All bugs below were discovered live during this validation session and fixed using the project's standard root-cause-first, test-first bug-fix workflow (regression test → fix → CHANGELOG → safety-reviewer for B-class → commit → push with full pytest + 8 security scans).

### E-1. Cloudflare edge-caching hid a deployed JS fix (Infra)

- **Symptom**: kubectl terminal panel did not appear for the real learner even though the underlying fix (commit `a924a4c`) was already deployed to disk.
- **Root cause**: Cloudflare's edge cached `/js/*` for its default TTL (~4h, `cache-control: max-age=14400`) and ignored/overrode the origin's explicit no-cache header.
- **Fix**: `NoCacheStaticFiles` (forces `Cache-Control: no-cache, must-revalidate` on every static response) + cache-busting `?v=2` query param on the affected script tag, as an interim workaround until Cloudflare dashboard/API access is available for a permanent cache-rule fix.
- **Regression test**: `tests/test_static_no_cache_headers.py`.
- **Commit**: `647418f`.

### E-2. Verifier credential store path mismatch (Ops, one-time)

- **Symptom**: `VerifierCredentialStore.exists('401')` returned False in production.
- **Root cause**: an earlier ad-hoc VM-401 rebuild ran without sourcing `/etc/labgen/home_lab_mvp.env`, so `LABGEN_VERIFIER_CREDENTIAL_ROOT` fell back to the relative default and wrote credentials to the wrong path.
- **Fix**: re-ran provisioning with the correct environment sourced. One-time ops fix, no code change.

### E-3. Wrong verifier provisioning function used (Ops, one-time)

- **Symptom**: even after fixing E-2, the generated kubeconfig pointed at `https://127.0.0.1:6443` (unreachable from the FastAPI host), causing a connection-refused 500.
- **Root cause**: `initialize_verifier_for_vm()` runs `kubectl config view` *inside* the VM via QEMU agent, which always reports the VM's own loopback view of K3s. The project's own ops runbook explicitly documents this and requires `initialize_verifier_for_vm_host_side()` for the home_lab_mvp shared-cluster profile.
- **Fix**: re-ran provisioning with `initialize_verifier_for_vm_host_side(401, '/etc/labgen/home_lab_mvp.kubeconfig')`. One-time ops fix, no code change.

### E-4. Shared-VM verifier credential reclaim on every session cleanup (Platform logic bug)

- **Symptom**: Lab 3 Step 1 failed with `credential_missing` immediately after Lab 2's session closed cleanly, on the same shared staging VM (401).
- **Root cause**: `LabSessionService._do_cleanup()` Phase 2 unconditionally calls `credential_reclaimer.reclaim_for_vm(vm_id)` on every session close. This is correct for a true per-student ephemeral-VM model, but home_lab_mvp's VM 401 is a single shared/persistent VM reused across many sequential students — every session's cleanup destroyed the credentials the *next* session on the same VM needed.
- **Fix**: extended the existing `VM_CLEANUP_EXEMPT_IDS` exemption pattern (previously used only to protect shared VMs from auto-delete) to also exempt credential reclaim. `LabSessionService` gained a `credential_reclaim_exempt_vm_ids` constructor parameter; `routes.py::get_session_service()` wires it from `config.VM_CLEANUP_EXEMPT_IDS`; `/etc/labgen/home_lab_mvp.env` now sets `VM_CLEANUP_EXEMPT_IDS=401`.
- **Regression test**: `tests/test_labgen_verifier_credential_reclaim.py::TestSharedVMCredentialReclaimExemption` (3 tests: exempt VM survives complete, exempt VM survives abort, non-exempt VM still reclaimed).
- **Safety review**: reviewed by safety-reviewer — no BLOCKER. One MEDIUM note accepted (the shared `VM_CLEANUP_EXEMPT_IDS` variable now controls two semantically different behaviors — VM-delete exemption and credential-reclaim exemption — with no independent toggle or audit log; acceptable tradeoff for the current single-shared-VM MVP scope).
- **Verified live**: after the fix, Lab 3's cleanup and Lab 4's cleanup both left VM 401's credential files untouched (confirmed via unchanged file mtime), and Lab 4 ran successfully against the same credentials Lab 3 used.
- **Commit**: `7219b34`.

---

## F. Notes (non-blocking)

### F-1. Confusing kubectl error for missing required flag (NOTE, unreproduced)

- **Symptom**: the learner's first `kubectl create deployment nginx-deployment` (without `--image`) returned `Error: flags cannot be placed before plugin name: --kubeconfig` instead of the expected `error: required flag(s) "image" not set`.
- **Investigation**: manually reproducing `kubectl --kubeconfig <path> --namespace <ns> create deployment <name>` (without `--image`) against the platform kubeconfig returned the expected, clear error — not the plugin-resolution error seen by the learner. Root cause not confirmed; suspected interaction between the per-session learner kubeconfig/restricted SA and kubectl's plugin-fallback path, or a transient artifact of the custom xterm.js local line-editing implementation. Not blocking — the learner immediately corrected by adding `--image` and the lab passed.
- **Learner feedback**: confirmed this message was "不太友好" (not very friendly) — worth improving if reproduced, but not actionable without a reliable repro.
- **Disposition**: documented as a NOTE for future investigation; no code change made.

---

## G. Platform Technical Gate Results

Post-session residual checks (run after all 3 labs closed):

| Check | Result |
|-------|--------|
| `lab-*` namespaces | 0 — PASS |
| Tainted VMs | 0 — PASS |
| VM 401 verifier credentials | present, correct path, correct server address — PASS |
| Production VMID 500–599 | untouched — PASS |
| Lab 2 session | LAB_CLOSED, cleanup_verified=True |
| Lab 3 session | LAB_CLOSED, cleanup_verified=True |
| Lab 4 session | LAB_CLOSED, cleanup_verified=True |
| Backend error log (post-fix) | clean — PASS |
| Secret value leak via `-o yaml`/`-o json` | blocked — PASS |

---

## H. Decision

**REAL_HUMAN_LABS_2_4_VALIDATED_WITH_NOTES**

A real human learner independently operated the kubectl web terminal and completed Labs 2, 3, and 4 end-to-end. The terminal integration from the prior gate is confirmed working under real usage. Four real bugs were found and fixed live during validation — three ops/infrastructure issues (CDN caching, credential path, wrong provisioning function) and one platform logic bug (shared-VM credential reclaim) that no operator-executed rehearsal had previously caught. One NOTE (confusing kubectl error message) remains open, unreproduced, non-blocking.

This closes the HIGH finding (UX-H1: no kubectl terminal) raised by the original Real Human Learner Validation v0.1 gate.

---

## I. Recommendation

**Next step options** (ranked):

1. **Small Cohort Pilot, round 2** — re-run the 3–5 trusted user small cohort pilot, now with real (non-operator) learners using the terminal across all 4 labs, to gather broader UX signal before any customer-facing decision.
2. **Cloudflare cache-rule permanent fix** — the `?v=` query-string workaround (E-1) is functional but requires manual version bumping on every JS change; get Cloudflare dashboard/API access to set a permanent cache-bypass rule for `/js/*` and `/css/*`.
3. **Investigate F-1** — if the confusing kubectl plugin-resolution error recurs, capture the raw bytes sent by the frontend terminal (not just the rendered echo) to rule out a local-line-editing bug in `labgen-kubectl-terminal.js`.

**Recommended path**: Option 1 (Small Cohort Pilot round 2), since the terminal-blocking issue is now resolved and the platform has 4 working labs with verified end-to-end terminal flows.

---

## J. Technical Self-Check

| # | Check | Result |
|---|-------|--------|
| 1 | No TODO / FIXME | PASS |
| 2 | No placeholder-as-success | PASS |
| 3 | No fabricated learner feedback | PASS — all responses verbatim from real learner |
| 4 | Learner self-report separated from operator observation | PASS — Section D vs Section C/E |
| 5 | No operator steps labeled as learner steps | PASS |
| 6 | No API-only simulation | PASS |
| 7 | No hardcoded credential | PASS |
| 8 | No kubeconfig content logged | PASS |
| 9 | No token/password/cert leaked | PASS |
| 10 | No verifier credential residual | PASS |
| 11 | No Secret value leaked | PASS |
| 12 | No namespace residual | PASS |
| 13 | No RoleBinding residual | PASS |
| 14 | No tainted VM | PASS |
| 15 | No production VM / pool / registry modified | PASS |
| 16 | LLM call count = 0 | PASS |
| 17 | No QEMU-agent verifier init path used in this validation | PASS |
| 18 | No overbroad RBAC introduced | PASS |
| 19 | No get verb regression | PASS |
| 20 | No customer pilot started | PASS |
| 21 | home_lab_mvp not treated as HA production | PASS |
| 22 | No public launch declared | PASS |
| 23 | All code changes have regression tests | PASS — E-4 fix covered by 3 new tests; full bug-fix workflow followed |
| 24 | Cloud portability not broken | PASS — exemption sourced from existing config mechanism, no hardcoded VM ID in code |

---

## K. Modified / Created Files

| File | Change |
|------|--------|
| `backend/main.py` | `NoCacheStaticFiles` (E-1) |
| `frontend/labgen-session.html` | cache-busting `?v=2` (E-1) |
| `tests/test_static_no_cache_headers.py` | new (E-1 regression) |
| `backend/labgen/lab_session_service.py` | `credential_reclaim_exempt_vm_ids` param + Phase 2 skip logic (E-4) |
| `backend/labgen/routes.py` | wire `config.VM_CLEANUP_EXEMPT_IDS` into session service (E-4) |
| `tests/test_labgen_verifier_credential_reclaim.py` | `TestSharedVMCredentialReclaimExemption` (E-4 regression) |
| `/etc/labgen/home_lab_mvp.env` (repo-external) | `VM_CLEANUP_EXEMPT_IDS=401` (E-4) |
| `CHANGELOG.md` | 2 `[Unreleased]` entries (E-1, E-4) |
| `docs/labgen/REAL_HUMAN_REVALIDATION_LABS_2_4_RESULT_v0.1.md` | this file |
| `deploy/labgen/staging_ops_ticket_status.md` | status banner update |

---

## L. Test Results

| Metric | Value |
|--------|-------|
| Tests | 3394 passed |
| Coverage | 93.22% |
| Code changes | 2 commits (`647418f`, `7219b34`) |
| Runtime sessions | 3 (Lab 2, Lab 3, Lab 4 — all LAB_CLOSED, cleanup_verified=True) |
| LLM calls | 0 |
| Real human learner | 1 (learner-H1, user acting as learner) |
| Bugs found and fixed | 4 |

---

This gate remains aligned with PROJECT_NORTH_STAR_v0.1: Article-to-Lab / Technical Content-to-Experiment Platform, "读完即练，结果说话". K8s domain proof for the broader Article-to-Lab platform.
