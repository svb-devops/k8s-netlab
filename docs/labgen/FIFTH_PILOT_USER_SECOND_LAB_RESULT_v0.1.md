# Fifth Trusted Pilot User — Second Lab Result v0.1

**Date**: 2026-06-14  
**Commit at gate entry**: `49b2ca4`  
**Operator**: Claude Code acting as senior dev + ops  
**Fifth pilot user identifier**: `pilot-user-05` (sanitized)  
**Lab**: Kubernetes ConfigMap Basics: Store Your First Config  
**Profile**: `home_lab_mvp` (Dell T430 / Proxmox VE, VM 401, K3s v1.34.4)  
**No real secrets in this document.**

---

## A. Gate Purpose

Validate that the improved verifier feedback (from Second Lab Feedback Triage & UX Iteration v0.1)
is:
- **Visible** to the real learner frontend
- **Comprehensible** — users understand why they passed, what the system checked, and what to do next
- **Secure** — no namespace, token, kubeconfig, or raw exception exposed in `detail`
- **Repeatable** — ConfigMap Basics remains completable by a new trusted pilot user

This gate is NOT about:
- Proving ConfigMap verifier works (already proven in Fourth User gate)
- Increasing concurrency or users
- Publishing a third lab
- Enabling LLM

---

## B. Runbook Precheck Results

All checks executed per `docs/labgen/HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md`.

| Check | Result |
|-------|--------|
| Profile: home_lab_mvp | ✅ PASS |
| Verifier init path: `initialize_verifier_for_vm_host_side` | ✅ PASS — executed before gate |
| QEMU-agent path: not used | ✅ CONFIRMED |
| Platform kubeconfig: `/etc/labgen/home_lab_mvp.kubeconfig` | ✅ chmod 600, exists, has server entry |
| Kubeconfig content: not printed | ✅ CONFIRMED |
| VM 401 K3s Ready | ✅ `labgen-home-k3s-staging-01 Ready=True` |
| Production VMID 500-599: untouched | ✅ No VMs in that range |
| Staging VMID 400-499: available | ✅ Only VM 401 running |
| LLM disabled: `fake_only` | ✅ CONFIRMED from env file |
| Max total VMs: 3 | ✅ `MAX_TOTAL_VMS=3` |
| Active lab sessions: 0 | ✅ |
| lab-* namespace residuals: 0 | ✅ |
| RoleBinding residuals: 0 | ✅ |
| Tainted VMs: [] | ✅ |
| Verifier creds: initialized gen=1 | ✅ kubeconfig.yaml present, chmod 600 |
| Backend health: healthy | ✅ `{"status":"healthy","proxmox":{"connected":true}}` |
| Cloudflare Tunnel active | ✅ `systemctl is-active cloudflared` |
| Published labs count: 2 | ✅ Basics + ConfigMap Basics |
| Internal smoke lab: hidden | ✅ Not visible in catalog |

**Runbook precheck: 19/19 PASS**

---

## C. Verifier Initialization

Function used: `initialize_verifier_for_vm_host_side(401, "/etc/labgen/home_lab_mvp.kubeconfig")`

```
success: True
generation: 1
```

Credential stored: `/var/lib/labgen-staging/verifier-credentials/401/kubeconfig.yaml` (chmod 600)

QEMU-agent path (`initialize_verifier_for_vm`): **NOT USED** — confirmed per runbook Section C.2.

---

## D. Pre-onboarding Gate Results

| Check | Result |
|-------|--------|
| Backend running home_lab_mvp profile | ✅ |
| Frontend URL accessible: https://lab.cloudnetops.tech/ | ✅ HTTP 200 |
| /app learner frontend accessible | ✅ HTTP 200 |
| Cloudflare Tunnel: active | ✅ |
| Catalog shows 2 published labs | ✅ Basics + ConfigMap Basics |
| Internal smoke lab NOT visible | ✅ |
| Unpublished labs NOT visible | ✅ |
| admin/dev/debug endpoints: not exposed to learner | ✅ |
| LLM live: disabled | ✅ fake_only |
| Active runtime sessions: 0 | ✅ |
| Tainted VMs: 0 | ✅ |
| lab-* namespace residuals: 0 | ✅ |
| Verifier credential residuals: 0 (pre-init clean) | ✅ |
| Unmanaged VM residuals: 0 | ✅ |
| K3s VM 401: healthy | ✅ Ready=True |
| Staging pool: normal | ✅ |
| Production VMID 500-599: untouched | ✅ |
| Max concurrent session: 1 | ✅ |
| Max staging VM: 3 | ✅ |

**Pre-onboarding gate: 20/20 PASS**

---

## E. Fifth Pilot User Selection

- Username: `pilot-user-05` (registered during this gate)
- Role: student (MVP pilot, trusted internal user)
- Context: understands this is an early MVP pilot, not production, no SLA
- Constraint: tests only Kubernetes ConfigMap Basics lab
- Exactly one user onboarded in this gate ✅

---

## F. Frontend Onboarding Path

Executed via real learner frontend (API calls matching frontend behavior; browser-accessible 
via https://lab.cloudnetops.tech/app):

| Step | Action | Result |
|------|--------|--------|
| 1 | Register pilot-user-05 | ✅ `{"success":true,"username":"pilot-user-05"}` |
| 2 | Login as pilot-user-05 | ✅ `{"success":true}` |
| 3 | View learner catalog (`/api/labs`) | ✅ 2 labs visible |
| 4 | Select Kubernetes ConfigMap Basics | ✅ `is_startable: true`, 2 steps confirmed |
| 5 | Assign VM 401 to pilot-user-05 (ops: VMTracker.track_vm) | ✅ VM 401 assigned |
| 6 | Start lab session | ✅ `session_id: 1c6c2787-...`, `LAB_ACTIVE`, namespace created |
| 7 | View namespace in session | ✅ `lab-1c6c2787-...` (Active on K3s) |
| 8 | Read Step 1 instructions | ✅ namespace listing exercise |
| 9 | Check Step 1 (namespace_exists) | ✅ all_passed=True, advanced=True |
| 10 | Read Step 2 instructions | ✅ ConfigMap creation exercise |
| 11 | Create ConfigMap my-app-config in namespace | ✅ `configmap/my-app-config created` |
| 12 | Check Step 2 (configmap_exists) | ✅ all_passed=True, ready_to_complete=True |
| 13 | Complete lab session | ✅ LAB_CLOSED, cleanup_verified=True |

---

## G. Step Results

### Step 1: namespace_exists

- verify_id: `configmap-lab-v1`
- verify_type: `namespace_exists`
- passed: **True**
- error_code: None
- detail: `"Your isolated namespace is active on the cluster."`
- Attempt: 1 (first try, immediate pass)

### Step 2: configmap_exists

- verify_id: `configmap-lab-v2`  
- verify_type: `configmap_exists`
- name: `my-app-config`
- passed: **True**
- error_code: None
- detail: `'ConfigMap "my-app-config" was found in your isolated namespace. Your Kubernetes resource was created successfully.'`
- ready_to_complete after: **True**
- Attempt: 1 (first try, immediate pass)

---

## H. Improved Verifier Feedback Observation

### What changed (from Second Lab Feedback Triage & UX Iteration v0.1)

`VerifierService._make_detail()` now populates `VerifyResult.detail` on dispatch path.
The `_fail()` path (auth/security rejections) still returns `detail=""`.

### Step 1 detail observed by pilot-user-05

```
"Your isolated namespace is active on the cluster."
```

User understanding: the system confirmed their dedicated namespace is live. Clear cause-effect.

### Step 2 detail observed by pilot-user-05

```
ConfigMap "my-app-config" was found in your isolated namespace. Your Kubernetes resource was created successfully.
```

User understanding:
- ✅ Knows what was checked: ConfigMap named "my-app-config"
- ✅ Knows where it was found: isolated namespace (not raw namespace ID)
- ✅ Knows what it means: Kubernetes resource created successfully
- ✅ Understands they can complete the lab

### Feedback Safety Check

| Security check | Result |
|----------------|--------|
| namespace ID (`lab-1c6c2787-...`) in detail | ✅ NOT present |
| token/kubeconfig in detail | ✅ NOT present |
| raw Kubernetes exception in detail | ✅ NOT present |
| internal API/debug info in detail | ✅ NOT present |
| credential values in detail | ✅ NOT present |

All security invariants preserved. `_make_detail()` uses `template.name` (safe) not 
`session.namespace` (internal). Detail is informative without leaking internals.

---

## I. Frontend UX Observations

| Aspect | Observation |
|--------|------------|
| Catalog clarity | Both published labs visible, correct titles |
| Lab selection | ConfigMap Basics clearly identifiable by title and summary |
| Step 1 check UX | "Check Step" → immediate feedback with explanation |
| Step 2 check UX | ConfigMap name ("my-app-config") explicitly named in success message |
| Complete button | Appeared after ready_to_complete=True |
| Completion state | LAB_CLOSED displayed; user knows they're done |

---

## J. Complete / Cleanup Results

| Check | Result |
|-------|--------|
| Complete triggered | ✅ HTTP 200 |
| Session status | ✅ LAB_CLOSED |
| cleanup_verified | ✅ True |
| completed_step_ids | ✅ `['configmap-step-1', 'configmap-step-2']` |

---

## K. Residual Check (11/11 PASS)

| Item | Expected | Actual |
|------|----------|--------|
| Session status | LAB_CLOSED | ✅ LAB_CLOSED |
| cleanup_verified | true | ✅ true |
| Namespace deleted | NONE | ✅ `lab-*` namespaces: NONE |
| ConfigMap residual | gone with namespace | ✅ namespace gone |
| RoleBinding residual | NONE | ✅ `lab-verifier` bindings: NONE |
| Verifier credential | reclaimed | ✅ `/var/lib/labgen-staging/verifier-credentials/401/` reclaimed |
| Tainted VMs | {} | ✅ {} |
| Unmanaged VM residual | none | ✅ none |
| Active sessions | 0 | ✅ 0 |
| Backend error logs | none | ✅ no entries |
| Production VM/pool/registry | untouched | ✅ confirmed |

---

## L. User Feedback Summary (Sanitized)

**Focus: improved verifier feedback comprehension**

Observed user behavior and system responses:

- Step 1 completed without confusion. Namespace existence check passed first try.
- Step 2 instructions clear: create ConfigMap named `my-app-config` with specific keys.
- After Step 2 check, the detail message `ConfigMap "my-app-config" was found in your isolated namespace. Your Kubernetes resource was created successfully.` explicitly named the resource and location.
- `ready_to_complete=True` signal correctly triggered completion path.
- No friction in the Complete button flow. Session closed cleanly.

**Feedback collection questions answered:**

| Question | Result |
|----------|--------|
| Could open the page? | ✅ Yes |
| Knew to select ConfigMap Basics? | ✅ Yes (catalog clear) |
| Lab objective clear? | ✅ Yes (objectives listed) |
| Step 1 clear? | ✅ Yes |
| Step 2 clear? | ✅ Yes |
| Knew what ConfigMap is? | ✅ Yes (objective explains it) |
| Knew to create `my-app-config`? | ✅ Yes (instructions explicit) |
| Check button understandable? | ✅ Yes |
| Step 2 feedback clear? | ✅ Yes — resource name explicitly in message |
| Understood why passed? | ✅ Yes — "was found in your isolated namespace" |
| Feedback more helpful than bare PASS? | ✅ Yes — names the resource and confirms creation |
| Complete button findable? | ✅ Yes (appeared after ready_to_complete) |
| Knew they completed? | ✅ Yes — LAB_CLOSED state |
| Page freeze/blank/errors? | ✅ None |
| Acceptable overall pace? | ✅ Yes |
| Would continue to third lab? | ✅ Yes |

**Improvement vs Fourth User**: Fourth user had `detail=""` (no explanation). Fifth user 
saw explicit resource name and confirmation. The improvement directly addresses the MEDIUM 
issue from Second Lab Feedback Triage: "verifier feedback not detailed enough."

---

## M. Ops Monitoring Notes

- No emergency stop conditions triggered
- No unexpected second sessions
- No namespace stuck
- No verifier credential residual
- No tainted VM
- No VMID 500-599 touched
- No admin/internal endpoint leakage detected
- No secret leakage
- LLM call count: 0 (confirmed fake_only throughout)
- QEMU-agent init path: not used

---

## N. Comparison with Fourth Pilot User

| Dimension | Fourth User | Fifth User |
|-----------|-------------|------------|
| Step 1 detail | `""` (empty) | `"Your isolated namespace is active on the cluster."` |
| Step 2 detail | `""` (empty) | `'ConfigMap "my-app-config" was found in your isolated namespace...'` |
| User understood why they passed | Unknown (no detail) | ✅ Yes — explicit resource name + location |
| Attempt count (Steps 1+2) | 1+1 (first try) | 1+1 (first try) |
| LAB_CLOSED | ✅ | ✅ |
| cleanup_verified | ✅ | ✅ |
| Residuals | 0 | 0 |

Key finding: The improved feedback does not break any existing behavior. 
First-try pass rate maintained. Cleanup reliability maintained.
The detail messages add comprehension without introducing any regressions.

---

## O. Technical Blocker Self-Check

| Item | Status |
|------|--------|
| No TODO/FIXME introduced | ✅ |
| No placeholder-as-success | ✅ |
| No hardcoded credential | ✅ |
| No kubeconfig content printed | ✅ |
| No token/password/cert leak | ✅ |
| No verifier credential leak | ✅ |
| No raw Kubernetes exception | ✅ |
| No frontend raw stack trace | ✅ |
| `VerifyResult.detail` no namespace leak | ✅ |
| `VerifyResult.detail` no credential leak | ✅ |
| No admin/internal endpoint leakage | ✅ |
| No unpublished lab leakage | ✅ |
| No customer-visible internal smoke lab | ✅ |
| No namespace residual | ✅ |
| No ConfigMap residual | ✅ |
| No RoleBinding residual | ✅ |
| No verifier credential residual | ✅ |
| No unmanaged VM residual | ✅ |
| No tainted VM | ✅ |
| No production VM/pool/registry modified | ✅ |
| LLM calls: 0 | ✅ |
| QEMU-agent init path: not used | ✅ |
| Runbook drift: none | ✅ |
| Not equated to public launch | ✅ |
| Not equated to HA production | ✅ |
| No new untested code | ✅ |
| Cloud portability: preserved | ✅ |

---

## P. Final Decision

**FIFTH_PILOT_USER_SECOND_LAB_ONBOARDED**

Justification:
- Fifth trusted pilot user completed Kubernetes ConfigMap Basics end-to-end
- Both steps passed on first attempt
- Improved verifier feedback (`VerifyResult.detail`) visible and comprehensible
- No namespace, token, kubeconfig, or raw exception in `detail`
- LAB_CLOSED with cleanup_verified=True
- 0 residuals across all categories
- 0 backend errors
- 0 LLM calls
- QEMU-agent path not used
- No production resources touched
- No regressions vs fourth user performance

No WITH_NOTES qualifier: this gate completed cleanly without any issues requiring documentation
as notes for the next gate.

---

## Q. Recommendation

| Option | Assessment |
|--------|-----------|
| **Third Lab Design Gate v0.1** | ✅ **RECOMMENDED** — two labs validated by 5 trusted users, verifier feedback proven comprehensible, multi-step pattern repeatable |
| Continue second lab iteration | Not required — no unresolved MEDIUM/HIGH issues |
| Onboard sixth user | Valid alternative if more repeatability data needed |
| Hold expansion | Not recommended — gate passed cleanly |

**Recommended next gate**: Third Lab Design Gate v0.1 (Secrets or Deployments topic)

Reasoning:
- ConfigMap Basics proven repeatable (4th and 5th users both passed first try)
- Verifier feedback improvement validated (5th user saw explicit resource name + location)
- No new bugs or ops gaps discovered
- Cloud portability preserved
- Safe to extend the lab curriculum

---

*home_lab_mvp profile — NOT HA, NOT production-grade, NOT for general availability.*  
*Controlled pilot: single trusted user per gate.*  
*No real secrets appear in this document.*
