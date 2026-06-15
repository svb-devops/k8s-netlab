# Small Cohort Pilot v0.1 — Feedback Template

**Template version**: v0.1  
**Date created**: 2026-06-15  
**Basis**: Small Cohort Readiness Gate v0.1 — SMALL_COHORT_READY_WITH_NOTES  
**No real secrets in this document.**

---

## Usage Notes for Operator

- Fill one copy of this template per user per session.
- Sanitize: do not record real names, real email addresses, cookies, tokens, passwords, API keys, or any credential.
- Use sanitized identifiers (e.g., `cohort-user-01`) consistently across this session's artifacts.
- The "User self-report" sections below should be filled based on user feedback (verbal, written, or observed behavior). Do not infer what the user thinks — record what they actually said or did.
- Preserve the completed template in `docs/labgen/` as `SMALL_COHORT_FEEDBACK_cohort-user-NN_YYYYMMDD.md`.
- Do not record: real name (unless user consents and it's necessary), browser fingerprints, IP addresses, raw request/response bodies, raw kubeconfig content, raw exception traces.

---

## Section 1: Session Identity

| Field | Value |
|-------|-------|
| Template version | v0.1 |
| User identifier | `cohort-user-XX` (sanitized) |
| Date | YYYY-MM-DD |
| Operator | Claude Code / human ops |
| Session ID (first 8 chars only) | `XXXXXXXX` |
| Lab(s) attempted | |
| Lab ID(s) | |
| VM ID | 401 |
| Session start status | LAB_ACTIVE / error |
| Session end status | LAB_CLOSED / LAB_ABORTED / LAB_CLEANUP_FAILED / other |
| cleanup_verified | True / False |
| Total session duration (minutes) | |

---

## Section 2: Step-by-Step Results

Fill one row per step attempted.

| Step ID | Step title (short) | Attempts | Final result | Time to pass (approx) | Notes |
|---------|-------------------|----------|--------------|----------------------|-------|
| | | | PASS / FAIL / SKIPPED | | |
| | | | PASS / FAIL / SKIPPED | | |

---

## Section 3: Learner-Reported Step Clarity

Scale: 1 = very confusing, 5 = very clear. Leave blank if not reported.

| Dimension | Score (1–5) | User comment (verbatim or paraphrase) |
|-----------|-------------|---------------------------------------|
| Lab start — did the user understand how to begin? | | |
| Step 1 instructions — clear enough to follow? | | |
| Step 2 instructions — clear enough to follow? | | |
| "Check Step" button — did the user understand when to click it? | | |
| PASS feedback text — did it teach something about K8s? | | |
| FAIL feedback text — did it give actionable guidance? | | |
| "Complete Lab" button — did the user understand when it appears? | | |
| Overall lab difficulty | | |

---

## Section 4: Concept Clarity (K8s Concepts)

Did the learner demonstrate understanding of the following after completing the lab?
Mark: Yes / Partial / No / N/A (lab didn't cover this concept)

| Concept | Evidence of understanding | Mark |
|---------|--------------------------|------|
| Kubernetes namespace — what it is and why it's isolated | | |
| ConfigMap — what it stores and how to create it | | |
| Secret — what it stores and why the value is not shown | | |
| Deployment — what it does and how it creates a Pod | | |
| Ready replica — what 1/1 means in `kubectl get deployments` | | |
| Why `kubectl get namespace` shows their lab namespace | | |

---

## Section 5: Verifier Feedback Quality

| Dimension | User reaction | Mark (Good / Confusing / Misleading) |
|-----------|--------------|--------------------------------------|
| PASS message (e.g., "Your isolated namespace is active on the cluster.") | | |
| PASS message (e.g., "ConfigMap was found in your isolated namespace.") | | |
| PASS message (e.g., "Secret exists without reading its value.") | | |
| PASS message (e.g., "Deployment available with 1 ready replica. Kubernetes has created a Pod.") | | |
| FAIL message (if user triggered one) | | |

---

## Section 6: Technical / Frontend Experience

| Check | Observed result | Notes |
|-------|----------------|-------|
| Page load speed (subjective) | Fast / Acceptable / Slow | |
| Any page blank / white screen | Yes / No | |
| Any frontend error in console | Yes / No (do not record raw error if sensitive) | |
| Check Step button responsiveness | Immediate / Delayed / No response | |
| Snapshot update after Check Step | Instant / Delayed | |
| Complete Lab button appeared at right time | Yes / No | |
| Post-complete screen clear | Yes / No | |
| Any unexpected UI behavior | | |

---

## Section 7: Failure / Retry Experience

Fill only if the user triggered a FAIL on any step.

| Step | Failure reason shown to user | User action | Resolution |
|------|------------------------------|-------------|------------|
| | | | |

---

## Section 8: User Experience Summary

Fill based on post-session conversation or written feedback.

| Question | User response (sanitized) |
|----------|--------------------------|
| Most confusing step or concept | |
| Most valuable step or concept | |
| What they would change about the lab | |
| Would they continue with another lab? (Yes / No / Maybe) | |
| Any feature they expected but didn't find | |
| Any concern about data privacy or security? (Note: do NOT record sensitive data here) | |
| Other comments | |

---

## Section 9: Perceived Speed / Resource Usage

| Dimension | User report | Operator observation |
|-----------|-------------|---------------------|
| Deployment Pod ready (approx time) | | |
| Any noticeable lag in step check | | |
| Page navigation speed | | |

---

## Section 10: Operator Notes

| Item | Notes |
|------|-------|
| Any ops issues during session (backend errors, K3s lag, etc.) | |
| Backend error log entries (if any, sanitized) | |
| Namespace created: confirm active during session | |
| Namespace deleted: confirm after LAB_CLOSED | |
| RoleBinding residual check | |
| Tainted VM check (post-session) | |
| LLM call count | 0 (must be 0) |
| Production VMID 500–599 touched | No (must be No) |
| Next user pre-approved | Yes / No / Pending |

---

## Section 11: Cleanup Result

| Check | Result |
|-------|--------|
| Session end status | LAB_CLOSED / LAB_ABORTED / LAB_CLEANUP_FAILED |
| cleanup_verified | True / False |
| Lab namespace deleted | Yes / No |
| Tainted VM | Yes (HOLD — do not proceed) / No |
| Active sessions remaining | 0 (required) |
| Operator approval for next user | APPROVED / HOLD — resolve cleanup first |

---

## Section 12: Not Recorded (Sanitization Checklist)

Confirm the following are NOT in this document:

| Item | Confirm absent |
|------|---------------|
| Real name or email address (unless necessary and consented) | ✅ |
| Browser fingerprint or raw IP address | ✅ |
| Session cookie or auth token | ✅ |
| kubeconfig content | ✅ |
| Secret `.data` value (base64 or raw) | ✅ |
| Registry credential | ✅ |
| Raw Kubernetes exception body | ✅ |
| Raw kubectl YAML output | ✅ |
| ADMIN_TOKEN or any server-side credential | ✅ |

---

## Section 13: Final Session Status

| Field | Value |
|-------|-------|
| Session result | COMPLETED / ABORTED / FAILED / INCOMPLETE |
| LAB_CLOSED + cleanup_verified=True | Yes / No |
| Issues to carry forward | |
| Recommendation for next user | Proceed / Hold — resolve [issue] first |

---

*This template records operator-observed and user-reported feedback only.*  
*No real credentials, kubeconfig content, or secret values should appear here.*  
*home_lab_mvp is a controlled pilot; not production; no SLA.*
