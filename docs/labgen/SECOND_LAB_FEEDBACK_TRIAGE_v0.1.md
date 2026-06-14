# Second Lab Feedback Triage v0.1

**Gate**: Second Lab Feedback Triage & UX Iteration v0.1  
**Date**: 2026-06-14  
**Operator**: Claude Code acting as senior dev + ops  
**Profile**: home_lab_mvp (Dell T430 / Proxmox VE, single physical host)  
**Lab under review**: Kubernetes ConfigMap Basics: Store Your First Config  
**Basis**: Fourth Trusted Pilot User on Second Lab v0.1 — FOURTH_PILOT_USER_SECOND_LAB_ONBOARDED (commit 212a515)

---

## A. Summary

| Field | Value |
|-------|-------|
| Lab name | Kubernetes ConfigMap Basics: Store Your First Config |
| Lab ID | b0b97742-80e4-4715-9a66-1fdd3009cfea |
| Session ID | 7dcb7f46-... (sanitized) |
| User | pilot-user-04 (staging account) |
| Final status | LAB_CLOSED |
| Duration | ~2 minutes 22 seconds |
| Cleanup result | cleanup_verified=True |
| Residual result | 11/11 PASS — zero residuals |
| Current gate state | All runbook, pre-onboarding, frontend, and self-checks PASS |
| LLM calls | 0 |
| Production VMID 500-599 | Untouched |

---

## B. What Worked

| Area | Finding |
|------|---------|
| Catalog visibility | 2 published labs displayed correctly; ConfigMap Basics selectable |
| Internal smoke lab hidden | e5b5aa73 NOT visible in catalog — correct |
| Lab detail | Title, description, objectives, steps_preview all present |
| Multi-step flow | Step 1 → Step 2 progression worked correctly; current_step_index advanced on pass |
| Step 1 — namespace_exists | Passed on first attempt; namespace confirmed active |
| Step 2 — configmap_exists | Passed on first attempt after kubectl create configmap |
| ready_to_complete gating | Became true only after both steps passed; Complete button correctly gated |
| Complete | POST /api/lab-sessions/{id}/complete → LAB_CLOSED |
| Cleanup | namespace deleted, RoleBindings removed, verifier creds reclaimed — all confirmed |
| Runbook compliance | initialize_verifier_for_vm_host_side used; QEMU-agent path not used; 20/20 PASS |
| Security | 0 secrets leaked in any API response; 0 raw K8s exceptions exposed |

---

## C. What Needs Improvement

### C.1 configmap_exists — empty success detail (MEDIUM)

**Observed**: When Step 2 passes, `VerifyResult.detail = ""`. The API response contains only `passed: true` with no human-readable message.

**Impact**: Learner sees a pass state but receives no explanation of WHY — no confirmation that their `kubectl create configmap` actually worked. This is a missed teaching moment for a lab specifically designed to teach ConfigMap creation.

**Expected**: A message such as:
> "ConfigMap 'my-app-config' was found in your isolated namespace. Your Kubernetes resource was created successfully."

**Root cause**: `VerifierService.check()` constructs `VerifyResult(passed=passed)` with `detail` defaulting to `""` for the dispatch path. Only `_fail()` paths populate `error_code`.

### C.2 namespace_exists — empty success detail (LOW)

**Observed**: Step 1 also returns `detail=""` on success.

**Impact**: Learner sees pass but has no confirmation message. Less critical than C.1 because Step 1 is a warm-up check with lower conceptual content.

**Expected**: "Your isolated namespace is active on the cluster."

### C.3 configmap_exists — no troubleshooting hint on failure (LOW)

**Observed**: If configmap_exists fails (e.g., wrong name), `VerifyResult.detail = ""`. Error code alone ("verifier_check_failed") does not help the learner diagnose the problem.

**Expected on failure**:
> "ConfigMap 'my-app-config' was not found. Check that the name is exactly 'my-app-config' and that it was created in your lab namespace."

### C.4 No in-session step progress indicator (NOTE)

**Observed**: The learner has no visual indicator of "Step X of Y complete". The API provides `current_step_index` and `completed_step_ids`, but the frontend does not render a progress bar.

**Impact**: Low for a 2-step lab, but will become more noticeable as labs gain more steps.

**Recommendation**: Track as a UX backlog item. Not blocking for current pilot scale.

### C.5 objectives rendered as array (NOTE)

**Observed**: `lab_detail.objectives` is an array. Frontend may need to handle multi-objective labs differently from single-objective display.

**Impact**: None observed for current labs (both use simple single-line objectives).

**Recommendation**: Track as frontend tech debt. Not blocking.

---

## D. User Feedback

**Source**: Claude Code acting as fourth trusted pilot user (no real user feedback collected for this pilot session).

**Status**: `FEEDBACK_INSUFFICIENT_FOR_CONTENT_QUALITY`

No human learner provided free-text feedback. The session was a controlled pilot simulation. The issues identified in Section C are derived from first-principles analysis of the UX, verifier API responses, and learner journey, not from user-reported problems.

**Questions to ask in future real-user sessions**:
1. "After clicking Check Step for Step 2, did you understand that your ConfigMap was successfully created?"
2. "Would a confirmation message (e.g., 'ConfigMap found — great job!') have helped?"
3. "Did the step instructions clearly explain the exact name required ('my-app-config')?"
4. "Was the Complete button clearly labeled once both steps were done?"
5. "Did you have any confusion about what a ConfigMap is or why you were creating one?"

---

## E. Issue Triage

| ID | Severity | Dimension | Issue |
|----|----------|-----------|-------|
| ISS-01 | MEDIUM | verifier feedback | `configmap_exists` success returns empty `detail`; no learner-facing confirmation message |
| ISS-02 | LOW | verifier feedback | `namespace_exists` success returns empty `detail` |
| ISS-03 | LOW | verifier feedback | `configmap_exists` failure returns empty `detail`; no troubleshooting hint |
| ISS-04 | LOW | verifier feedback | All other supported verify types (pod_running, deployment_ready, service_exists, secret_exists) return empty `detail` on both pass and fail |
| ISS-05 | NOTE | frontend UX | No in-session step progress indicator (current_step_index not rendered visually) |
| ISS-06 | NOTE | frontend UX | objectives field as array may need different rendering for multi-objective labs |
| ISS-07 | NOTE | ops burden | Verifier credentials must be re-initialized before each gate (expected, documented in runbook) |
| ISS-08 | NOTE | ops burden | kubernetes Python library required for platform kubeconfig (urllib fails with ECDSA cert auth) |

**BLOCKER count**: 0  
**HIGH count**: 0  
**MEDIUM count**: 1 (ISS-01)  
**LOW count**: 3 (ISS-02, ISS-03, ISS-04)  
**NOTE count**: 4 (ISS-05 through ISS-08)

---

## F. Recommendation

| Question | Answer |
|----------|--------|
| Allow fifth user on second lab? | **YES** — lab is functionally stable; iteration is additive, not blocking |
| Need UX/content iteration before fifth user? | **NO** — but iteration should be done concurrently (detail messages are additive) |
| Ready to design third lab? | **YES (after iteration)** — multi-step pattern validated; verifier feedback iteration is small |
| Hold expansion? | NO |
| Keep concurrency at 1 active session? | YES — max_active_runtime_sessions=1 stays; home_lab_mvp capacity unchanged |
| Keep LLM disabled? | YES — LABGEN_LLM_PROVIDER_MODE=fake_only unchanged |

**Decided action**: Implement minimal verifier feedback iteration (ISS-01 through ISS-04) — populate `VerifyResult.detail` with learner-facing messages for all dispatch-path results. This is a pure additive change to the verifier service with no architectural impact. Followed by one internal rehearsal with the real learner frontend.

---

## G. Iteration Scope

**Minimal change**: Add `_make_detail(vtype, name, passed) -> str` to `VerifierService` in `backend/labgen/verifier.py`. Populate `detail` in the `VerifyResult` returned on the dispatch path (not on `_fail()` security paths).

**Security constraint**: `detail` must NEVER contain `session.namespace` or any credential value. The existing regression test `TestVerifierDetailSafetyRC` enforces this.

**Messages per verify type**:

| Type | Pass | Fail |
|------|------|------|
| namespace_exists | "Your isolated namespace is active on the cluster." | "Your namespace was not found. Try clicking Check Step again in a moment." |
| configmap_exists | "ConfigMap '{name}' was found in your isolated namespace. Your Kubernetes resource was created successfully." | "ConfigMap '{name}' was not found. Check that the name is exactly '{name}' and that it was created in your lab namespace." |
| secret_exists | "Secret '{name}' was found in your namespace." | "Secret '{name}' was not found. Check the name and namespace." |
| pod_running | "Pod '{name}' is running in your namespace." | "Pod '{name}' is not running yet. Check the pod status with: kubectl get pods" |
| deployment_ready | "Deployment '{name}' is ready in your namespace." | "Deployment '{name}' is not ready yet. Check with: kubectl get deployments" |
| service_exists | "Service '{name}' exists in your namespace." | "Service '{name}' was not found. Check the service name and namespace." |

**Tests added**:
- `test_success_configmap_exists_detail_message` — dispatch pass, configmap_exists, detail non-empty
- `test_success_namespace_exists_detail_message` — dispatch pass, namespace_exists, detail non-empty
- `test_dispatch_failure_configmap_hint` — dispatch fail (FakeK8sVerifierClient(default=False)), detail contains hint
- `test_dispatch_failure_namespace_hint` — dispatch fail, namespace_exists, detail contains hint
- `test_security_fail_paths_no_detail` — all `_fail()` paths still return `detail=""`

**Not changed**:
- `_fail()` paths — remain `detail=""`
- `VerifyResult` model — `detail: str = ""` default unchanged
- StaticValidator, routes, publish logic, session lifecycle — untouched
- Frontend rendering — `detail` field already present in API response; frontend already receives it

---

## H. Runtime Risk Assessment

| Risk | Mitigation |
|------|------------|
| Namespace value leaked in detail message | Messages use `template.name` (resource name, safe to expose) not `resolved_ns` |
| Security test regression | `TestVerifierDetailSafetyRC` tests remain — must pass after change |
| Existing test breakage | One assertion (`test_success_has_no_error_code`) needs update: `detail == ""` → non-empty |
| Internal rehearsal required | Yes — user-visible behavior changes; one internal rehearsal will be run |

---

## I. Final Decision

**SECOND_LAB_FEEDBACK_TRIAGED_WITH_ITERATION**

- 0 BLOCKER, 0 HIGH, 1 MEDIUM, 3 LOW, 4 NOTE
- Minimum iteration: verifier `detail` messages (ISS-01 through ISS-04)
- Internal rehearsal required after iteration
- Fifth user allowed after iteration completes
- Third lab design allowed after iteration completes

---

*home_lab_mvp profile. Not HA. Not production-grade. Not for general availability.*  
*No real secrets appear in this document.*
