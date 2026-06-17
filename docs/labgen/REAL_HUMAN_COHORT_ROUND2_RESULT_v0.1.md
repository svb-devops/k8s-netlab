# Real Human Small Cohort Pilot Round 2 — Result v0.1

**Date**: 2026-06-16
**Operator**: Claude Code acting as senior dev + ops
**Status**: System-evidence sections (A, B, C-system, D, E, G, H, I, J) complete. Section F and the learner self-report parts of C/Sections 3–10 are **PENDING_USER_INPUT** — they require the real human learners' (your) subjective feedback and have not been fabricated.
**No real secrets in this document.**

This gate remains aligned with PROJECT_NORTH_STAR_v0.1: Article-to-Lab / Technical Content-to-Experiment Platform, "读完即练，结果说话". K8s domain proof for the broader Article-to-Lab platform.

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Real human learners | 2 (`learner-r2-a`, `learner-r2-b`) |
| Labs attempted | 4 of 4 published labs, by both learners |
| Labs completed | 4 of 4, by both learners (8/8 sessions `LAB_CLOSED`) |
| All 4 labs covered | YES |
| Terminal issue (UX-H1) remains closed | YES — kubectl terminal used throughout, no recurrence reported |
| Final decision | **REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES** (see §I) |
| Feedback sufficient for Small Customer Pilot Preparation Gate | **NOT YET** — Sections 3–10 self-report not yet collected (see §F) |

---

## B. Authenticity Check

| Check | Result |
|-------|--------|
| Learners operated frontend themselves | YES — real human (you), via browser, screenshot evidence (422 error screen) |
| Learners used the page terminal themselves | YES — kubectl web terminal, per ops runbook flow |
| Operator did not execute commands for the learner | YES, with one disclosed exception below |
| API-only simulation not used | YES, with one disclosed exception below |
| Operator shell not used in place of learner terminal | YES |
| Learner feedback captured directly | PENDING — Sections 3–10 not yet collected |
| Operator observations separated from learner self-report | N/A until Sections 3–10 collected |

**Disclosed exception**: during root-cause verification of the `no_vm_assigned` 422 bug, the operator (Claude Code) issued one `curl` call as `learner-r2-a` to confirm the fix worked, creating session `918c5694-e3e0-43af-a631-3044e3018190`. This was caught immediately, the session was aborted and cleaned up (`LAB_CLOSED`, `cleanup_verified=True`, 0 residual), and it is **excluded** from the authentic learner results below. All other 8 sessions are genuine learner-initiated actions.

---

## C. Per-Learner Results

### learner-r2-a

| Field | Value |
|-------|-------|
| Sanitized learner ID | learner-r2-a |
| Prior Kubernetes familiarity | PENDING_USER_INPUT |
| Assigned/attempted labs | All 4 (Basics, ConfigMap, Secret, Deployment) |
| Session IDs | `03abae0c`, `a7a28f99`, `44adfb22`, `5dd63c3e` (excludes operator-verification session `918c5694`, see §B) |
| Terminal visible | YES (implied by step_check_passed events; no UX-H1 recurrence reported) |
| Namespace badge visible | PENDING_USER_INPUT |
| Command summary (sanitized) | Not captured by this artifact — no command-level audit log exists (see §K) |
| Step/check results | 100% pass, first attempt, every step, every lab |
| Hints needed | 0 (no `step_check_failed` events for this learner) |
| Completion status | 4/4 `LAB_CLOSED` via explicit Complete action |
| Cleanup status | `cleanup_verified=True` on all 4 sessions |
| Residual status | 0 (namespace/RoleBinding/workload — see §G) |
| Sections 3–10 summary | PENDING_USER_INPUT |

### learner-r2-b

| Field | Value |
|-------|-------|
| Sanitized learner ID | learner-r2-b |
| Prior Kubernetes familiarity | PENDING_USER_INPUT |
| Assigned/attempted labs | All 4 (Basics, ConfigMap, Secret, Deployment) |
| Session IDs | `7502839d`, `14417898`, `5afa703b`, `cf79e0c7` |
| Terminal visible | YES |
| Namespace badge visible | PENDING_USER_INPUT |
| Command summary (sanitized) | Not captured by this artifact — no command-level audit log exists (see §K) |
| Step/check results | 100% pass, first attempt, every step, every lab |
| Hints needed | 0 (no `step_check_failed` events for this learner) |
| Completion status | 4/4 `LAB_CLOSED` via explicit Complete action |
| Cleanup status | `cleanup_verified=True` on all 4 sessions |
| Residual status | 0 |
| Sections 3–10 summary | PENDING_USER_INPUT |

---

## D. Lab-Level Findings

| Lab | Attempts | Completion | Terminal UX | Command clarity | Concept clarity | Verifier feedback clarity | Failure/retry notes | Cleanup result | Recommended iteration |
|-----|----------|------------|--------------|------------------|------------------|---------------------------|----------------------|-----------------|------------------------|
| Kubernetes Basics | 2 (a, b) | 2/2 | PENDING_USER_INPUT | PENDING_USER_INPUT | PENDING_USER_INPUT | PENDING_USER_INPUT | None (0 failed checks) | cleanup_verified=True ×2 | PENDING_USER_INPUT |
| ConfigMap Basics | 2 (a, b) | 2/2 | PENDING_USER_INPUT | PENDING_USER_INPUT | PENDING_USER_INPUT | PENDING_USER_INPUT | None (0 failed checks) | cleanup_verified=True ×2 | PENDING_USER_INPUT |
| Secret Basics | 2 (a, b) | 2/2 | PENDING_USER_INPUT | PENDING_USER_INPUT | PENDING_USER_INPUT | PENDING_USER_INPUT | None (0 failed checks) | cleanup_verified=True ×2 | PENDING_USER_INPUT |
| Deployment Basics | 2 (a, b) | 2/2 | PENDING_USER_INPUT | PENDING_USER_INPUT | PENDING_USER_INPUT | PENDING_USER_INPUT | None (0 failed checks) | cleanup_verified=True ×2 | PENDING_USER_INPUT |

---

## E. Terminal Findings

| Item | Result |
|------|--------|
| Terminal discoverability | PENDING_USER_INPUT |
| Terminal command usability | PENDING_USER_INPUT |
| Terminal output clarity | PENDING_USER_INPUT |
| Namespace badge clarity | PENDING_USER_INPUT |
| Forbidden behavior observed | None reported; no `step_check_failed` or error-level log entries during cohort window |
| Socket/credential cleanup | Verified system-side: `creds/vm_creds/401` is the persistent shared-VM verifier identity (expected baseline, not a per-session residual); 0 lab-* namespaces, 0 RoleBindings, 0 workloads after both learners finished |
| kubectl NOTE recurrence status | PENDING_USER_INPUT — known NOTE (`kubectl create deployment` missing `--image` produces a confusing plugin-resolution error) was not confirmed reproduced or absent this round; ask the learners directly |

---

## F. Product Learning Findings

**PENDING_USER_INPUT — not fabricated.**

This section requires direct learner self-report (step clarity, concept clarity, frontend friction, perceived speed, willingness to continue, readiness for small customer pilot prep) and cannot be filled from system logs alone. Per task rules, leaving it blank rather than inferring or guessing.

---

## G. Security Findings

| Check | Result |
|-------|--------|
| No kubeconfig leak | PASS — no `client-certificate-data`/`client-key-data`/kubeconfig content in any logged verify detail |
| No token leak | PASS |
| No verifier credential leak | PASS — verifier kubeconfig stays server-side in `creds/vm_creds/401`, never returned in API responses |
| No learner credential leak | PASS |
| No Secret value/base64 leak | PASS — scanned all `last_verify_results[].detail` for learner-r2-a/b sessions, 0 matches for `base64`, `-----BEGIN`, `token`, `kubeconfig` |
| No raw workload object leak | PASS (no raw K8s object echoed in any session detail field) |
| No cross-namespace access | PASS — each session scoped to its own `lab-{session_id}` namespace; RBAC unchanged (list+watch only, no get; no ClusterRoleBinding) |
| Terminal disabled/closed after LAB_CLOSED | Consistent with existing terminal ownership/session-active checks (unchanged this round) |
| No production touch | PASS — no `qm` command executed against VMID 500–599 this round; only VM 401 (staging range 400–499) was used |
| No LLM call | PASS — `LABGEN_LLM_PROVIDER_MODE=fake_only` |

---

## H. Issue Triage

| # | Severity | Dimension | Finding |
|---|----------|-----------|---------|
| 1 | **MEDIUM (resolved during this round)** | ops | `POST /api/lab-sessions` returned `422 no_vm_assigned` for `learner-r2-a` on first Start Lab attempt. Root cause: home_lab_mvp's shared-VM model relies on `VMTracker`'s single-owner-per-VM field; VM 401 was still owned by the previous round's test account (`k8s_test05`) and was never reassigned to the newly created `learner-r2-a` account. Fixed live via `VMTracker().track_vm(401, owner=...)`; not a code defect (existing `no_vm_assigned` precheck behavior is already covered by `tests/test_labgen_lab_session.py`) — it is an undocumented manual ops step. **Action taken**: runbook gap identified; recommend adding an explicit "assign/reassign VM 401 ownership before each new learner" step to the Per-Learner Start Checklist (not yet written into the runbook as of this artifact). |
| 2 | NOTE | authenticity | Operator (Claude Code) created and immediately aborted one verification session as `learner-r2-a` while diagnosing finding #1. Disclosed in §B; excluded from authentic results; 0 residual after abort. |
| 3 | NOTE | runtime | The previously known kubectl `create deployment` missing `--image` NOTE was not specifically tested or ruled out this round (no command-level audit exists to confirm). Status unchanged from prior gate. |

0 BLOCKER. 0 HIGH. 1 MEDIUM (resolved live, ops-only fix, no code change). 2 NOTE.

---

## I. Decision

**REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES**

Rationale:
- All 4 published labs were covered by both real learners, end-to-end, with zero step failures and zero residuals — this is the strongest technical result of any cohort round to date.
- One real ops bug was found and fixed live (VM ownership reassignment gap), consistent with the project's "real bugs get found and fixed during real human testing" track record.
- "WITH_NOTES" rather than unqualified COMPLETED because: (1) Sections 3–10 learner self-report feedback has not yet been collected, and (2) the kubectl `--image` NOTE status was not actively re-checked this round.

It is **not** BLOCKED or FEEDBACK_INSUFFICIENT because the technical/system-evidence bar (§B, §C system fields, §D session-level data, §G security) is fully satisfied — only the qualitative learner-feedback layer is outstanding.

---

## J. Recommendation

**Recruit More Human Learners is not required.** Recommended next step:

→ **Collect Sections 3–10 from both learners (Terminal UX/Content Iteration data-gathering)**, then re-evaluate against the Small Customer Pilot Preparation Gate.

Do **not** advance to Small Customer Pilot Preparation Gate until Sections 3–10 are captured — per task rules, incomplete Sections 3–10 means "not allowed to enter Small Customer Pilot Preparation."

---

## K. Known Limitations of This Artifact

- No command-level kubectl audit log exists in the current system (`lab_runtime_audit.json` records `lab_start_success` / `step_check_passed` / `step_check_failed` / `lab_complete` / `cleanup_success` event types, not raw terminal input). Sanitized command summaries in §C could not be reconstructed from system evidence; only verbal/written learner recall could fill that field.
- "Prior Kubernetes familiarity" and all subjective UX/clarity fields are intentionally left `PENDING_USER_INPUT` rather than inferred from pass/fail timing, per the rule against fabricating learner feedback.

---

*Not HA. Not production-grade. Not for general availability.*
*home_lab_mvp is a controlled pilot profile on single-node Proxmox (T430).*
*No real secrets appear in this document.*
*Production VMID range 500–599 was not touched during this round.*
*0 LLM calls. 0 customer pilot started. 0 second lab published. No concurrency increase.*
