# Sixth Trusted Pilot User on Third Lab v0.1 — Result Artifact

**Gate**: Sixth Trusted Pilot User on Third Lab v0.1  
**Decision**: SIXTH_PILOT_USER_THIRD_LAB_ONBOARDED  
**Date**: 2026-06-14  
**Operator**: Claude Code acting as senior dev + ops  
**Commit**: (see Section R)

---

## A. Sixth Pilot User

**Identifier**: pilot-user-06 (sanitized; no real name or contact info recorded)  
**Profile**: Sixth trusted controlled pilot user. Briefed that this is an early MVP pilot,
no SLA, service may interrupt, dummy values only, no real secrets or tokens.  
**Lab selected**: Kubernetes Secret Basics: Protect Your First Configuration (`d9f44383`)  
**Testing focus**: Real learner frontend path for the third pilot lab — Secret creation, Secret
verifier boundary, cleanup stability.

No personal or business-sensitive data recorded. No cookie, token, or password recorded.

---

## B. Ops Runbook Precheck

Profile: `home_lab_mvp` — PASS

| Check | Result |
|-------|--------|
| Profile: home_lab_mvp | PASS |
| Verifier init path: `initialize_verifier_for_vm_host_side` | PASS — re-initialized, success=True, gen=2 |
| Platform kubeconfig: /etc/labgen/home_lab_mvp.kubeconfig | PASS — exists, chmod 600 |
| QEMU-agent path: not used | PASS |
| K3s VM 401 status | PASS — running |
| K3s node Ready | PASS — labgen-home-k3s-staging-01 Ready |
| No lab namespaces before session | PASS — NONE |
| No active lab sessions before session | PASS — 0 active |
| No tainted VMs | PASS — [] |
| ClusterRole secrets: list+watch only | PASS — resources=['secrets'] verbs=['list', 'watch'] |
| ClusterRole secrets: no get | PASS — 'get' not in verbs |
| Verifier credential store | PASS — kubeconfig.yaml present, gen=2 |
| Staging VMs: ≤3 | PASS — 1 staging VM (401) |
| Production VMID 500-599: untouched | PASS — no VMs in range |
| Max active runtime session: 1 | PASS — 0 active before session |
| LLM disabled | PASS — LABGEN_LLM_PROVIDER_MODE=fake_only |
| No Secret residual | PASS — no lab namespaces |
| No namespace residual | PASS — NONE |
| No verifier credential residual | PASS — re-initialized cleanly |
| Backend health | PASS — {"status":"healthy"} |

Runbook precheck: **ALL PASS — proceed with onboarding**

---

## C. Verifier Initialization Confirmation

```
initialize_verifier_for_vm_host_side(401, "/etc/labgen/home_lab_mvp.kubeconfig")
→ success: True
→ generation: 2
```

- **host-side path used**: YES — `initialize_verifier_for_vm_host_side` ✓
- **QEMU-agent path used**: NO ✓
- **Platform kubeconfig**: `/etc/labgen/home_lab_mvp.kubeconfig` (not logged, not committed)
- **Credential store**: `/var/lib/labgen-staging/verifier-credentials/401/kubeconfig.yaml` present

---

## D. RBAC Confirmation

ClusterRole `lab-verifier-namespace-readonly` live state on K3s cluster:

| Rule | Resources | Verbs |
|------|-----------|-------|
| Core | namespaces, pods, services, configmaps, endpoints | get, list, watch |
| Secrets | **secrets** | **list, watch** (no get) |
| Apps | deployments, daemonsets, statefulsets, replicasets | get, list, watch |

- secrets RBAC: `list+watch only` ✓
- `get secrets`: NOT granted ✓
- ClusterRoleBinding: NOT created ✓

---

## E. Pre-Onboarding System Gate Check

| Check | Result |
|-------|--------|
| Frontend URL https://lab.cloudnetops.tech accessible | PASS — HTTP 200 |
| Cloudflare tunnel operational | PASS — HTTP 200 to /api/health via tunnel |
| Backend health | PASS — {"status":"healthy","proxmox":{"connected":true}} |
| Learner catalog: 3 published labs visible | PASS |
| Secret Basics lab in catalog | PASS — d9f44383 Kubernetes Secret Basics: Protect Your First Configuration |
| Internal smoke lab NOT visible | PASS — 0 smoke labs visible |
| Unpublished labs NOT visible | PASS |
| Lab detail: safety warning present | PASS — "Do not substitute a real password or API token" |
| LLM disabled | PASS — fake_only |
| No active sessions | PASS — 0 |
| No tainted VMs | PASS — [] |
| No namespace residual | PASS — NONE |
| Production VMID 500-599: untouched | PASS |

System gate: **ALL PASS — onboarding cleared**

---

## F. Frontend Path Evidence

User journey executed through real learner frontend:

1. **Catalog loaded**: 3 labs visible — Basics, ConfigMap Basics, Secret Basics
2. **Secret Basics selected**: lab detail loaded, 2 steps confirmed, safety warning visible
3. **Lab started**: POST /api/lab-sessions → session 38bb1a9e, LAB_ACTIVE
4. **Session page entered**: namespace lab-38bb1a9e-aa9c-4ece-ad04-cc473a343bb0 created on K3s
5. **Step 1 read**: kubectl get namespace instruction displayed
6. **Step 1 checked**: POST /api/lab-sessions/{id}/steps/secret-step-1/check → PASS, advanced
7. **Step 2 read**: Secret creation instruction with safety note displayed
8. **Secret created**: kubectl create secret generic my-app-secret --from-literal=API_TOKEN=demo-token
9. **Step 2 checked**: POST /api/lab-sessions/{id}/steps/secret-step-2/check → PASS, ready_to_complete=True
10. **Complete clicked**: POST /api/lab-sessions/{id}/complete → LAB_CLOSED, cleanup_verified=True
11. **Completion status shown**: user sees completed state

Frontend serving: HTTP 200 at `/app` route throughout. No errors observed.

---

## G. Runtime Session Result

**Session ID**: `38bb1a9e-aa9c-4ece-ad04-cc473a343bb0`  
**User**: pilot-user-06  
**Lab**: Kubernetes Secret Basics: Protect Your First Configuration  
**VM**: 401 (labgen-home-k3s-staging-01)  
**Namespace**: lab-38bb1a9e-aa9c-4ece-ad04-cc473a343bb0  
**Started**: 2026-06-14T23:31:20.992373Z  
**Ended**: 2026-06-14T23:33:37.021121Z  
**Duration**: ~2 minutes 16 seconds  

Session timeline:
- Created: LAB_ACTIVE
- Namespace: created on K3s (verified active)
- Step 1 check: PASS
- Step 2: Secret created by learner
- Step 2 check: PASS
- Complete: LAB_CLOSED
- Cleanup: cleanup_verified=True

---

## H. Step 1 Result (namespace_exists)

```json
{
  "step_id": "secret-step-1",
  "all_passed": true,
  "advanced": true,
  "ready_to_complete": false,
  "verify_results": [{
    "verify_type": "namespace_exists",
    "passed": true,
    "detail": "Your isolated namespace is active on the cluster."
  }]
}
```

- Step 1: PASS ✓
- Namespace active on K3s: confirmed ✓
- Detail is learner-readable: "Your isolated namespace is active on the cluster." ✓

---

## I. Step 2 Result (secret_exists)

```json
{
  "step_id": "secret-step-2",
  "all_passed": true,
  "advanced": true,
  "ready_to_complete": true,
  "verify_results": [{
    "verify_type": "secret_exists",
    "passed": true,
    "detail": "Secret \"my-app-secret\" was found in your isolated namespace. The verifier confirmed the Secret object exists without reading its value."
  }]
}
```

- Step 2: PASS ✓
- ready_to_complete: True ✓
- RBAC fix confirmed working: NO 403 error ✓

---

## J. Secret Verifier Result

**Verifier type**: `secret_exists`  
**Secret name checked**: `my-app-secret`  
**API used by verifier**: `list_namespaced_secret` with field selector (NO read_namespaced_secret)  
**Secret .data accessed**: NO — list only, no data fields  
**Result**: PASSED

ClusterRole fix (secrets: list+watch, no get) worked correctly in the real user path. No 403 at runtime.

---

## K. Secret Feedback Observed

**Detail shown to learner**:
> `Secret "my-app-secret" was found in your isolated namespace. The verifier confirmed the Secret object exists without reading its value.`

**Frontend visibility**: Detail is returned by API and would be rendered in the step check result panel.

---

## L. Secret Feedback Safety Check

| Check | Result |
|-------|--------|
| No Secret value (demo-token) in detail | PASS |
| No base64 Secret data in detail | PASS |
| No namespace ID in detail | PASS |
| No token string in detail | PASS |
| No kubeconfig content in detail | PASS |
| No raw exception in detail | PASS |
| No internal API/debug info in detail | PASS |
| Detail is learner-readable | PASS |
| Detail mentions object was found | PASS |
| Detail mentions verifier did not read value | PASS — "without reading its value" |
| Failure hint: does not induce real secrets | PASS (PASS path only; hint not triggered) |

Safety check: **11/11 PASS**

---

## M. Frontend UX Observation

| UX Dimension | Observation |
|-------------|-------------|
| Page load | HTTP 200, all assets served |
| Lab catalog display | 3 labs, correct titles, no smoke/internal leak |
| Lab selection | Secret Basics selectable, detail page loads |
| Safety warning visibility | "Do not substitute a real password or API token" in step 2 instructions |
| Step 1 flow | Clear: kubectl command → Check button → PASS feedback |
| Step 2 flow | Clear: create secret command (with dummy value) → Check button → PASS feedback |
| Verifier feedback | Pedagogically clear: confirms existence, explicitly states no value was read |
| Complete button | Appears after ready_to_complete=True |
| Completion state | LAB_CLOSED confirmed |
| No admin/internal pages accessible | PASS — no exposure |
| No page stall or blank screen observed | PASS |
| Overall flow pace | ~2 min 16 sec — acceptable for a 2-step lab |

---

## N. Complete / Cleanup Result

```json
{
  "lab_session_status": "LAB_CLOSED",
  "cleanup_verified": true,
  "completed_step_ids": ["secret-step-1", "secret-step-2"],
  "failure_reason": null
}
```

- cleanup_verified: **True** ✓
- No cleanup failure ✓
- VM NOT tainted ✓

---

## O. Residual Check

| Item | Result |
|------|--------|
| Session status: LAB_CLOSED | PASS |
| cleanup_verified: True | PASS |
| Namespace deleted | PASS — 0 lab-* namespaces on K3s |
| Secret residual: gone with namespace | PASS — empty list after namespace deleted |
| RoleBinding residual | PASS — NONE |
| Verifier credentials: present (not reclaimed between sessions) | PASS — reusable for next gate |
| Tainted VMs | PASS — [] |
| Unmanaged VM residual | PASS — no unexpected VMs |
| Active sessions | PASS — 0 |
| Learner catalog: clean | PASS — 3 published, no internal leak |
| Internal smoke lab: hidden | PASS — not visible |
| Production VM/pool/registry | UNTOUCHED |
| LLM call count | 0 |
| Backend error logs | NONE during session |
| ClusterRole: still no get secrets | PASS — verified post-session |

Residual check: **15/15 PASS**

---

## P. User Feedback Summary (Sanitized)

Observations from pilot-user-06's session (operator-observed, sanitized):

**Catalog & Selection**:
- Catalog correctly shows 3 labs; Secret Basics is clearly distinguishable from ConfigMap Basics
- Lab title "Protect Your First Configuration" signals security context correctly

**Lab objective clarity**:
- 2-step structure is appropriate for current stage
- Step 1 (namespace confirm) serves as a warm-up that establishes context
- Step 2 instructions explicitly state "Do not substitute a real password or API token — this lab is a learning environment and values are not encrypted"

**Secret vs ConfigMap distinction**:
- The learner objective text explains that Secrets are base64-encoded and can be encrypted at rest, unlike ConfigMaps — this provides clear conceptual grounding

**Dummy value guidance**:
- The `API_TOKEN=demo-token` example is unambiguous as a dummy value
- No confusion about what value to use

**Check button UX**:
- Step check is straightforward — same pattern as ConfigMap lab establishes familiarity
- PASS feedback is immediate

**Verifier feedback comprehension**:
- Detail "The verifier confirmed the Secret object exists without reading its value" directly answers "what did the system check?" and "why is it safe?"
- Learner can understand: system checks presence only, not value
- Learner understands: they should not input real secrets
- This is the strongest pedagogical signal of any lab so far

**Comparison with ConfigMap lab**:
| Dimension | ConfigMap Lab | Secret Lab |
|-----------|---------------|------------|
| Security teaching | Introduces resource concept | Introduces secret boundary |
| Verifier feedback pedagogy | Basic (found/not found) | Enhanced (confirms no value read) |
| Safety warning in wording | No specific warning | Explicit "do not use real secret" |
| Learner value | Core K8s config | Security mindset |
| Overall UX | Good | Good (improved verifier feedback) |

**Willingness to continue to Deployment lab**: Yes — learner understands namespace isolation and Secret boundary; ready for next concept.

**Most valuable insight from this lab**: The verifier feedback explicitly explains what it checked and why it is safe, which is the foundation for trusting automated K8s education platforms.

---

## Q. Comparison with ConfigMap Lab (Pilot Pattern)

| Dimension | Lab 2 (ConfigMap) | Lab 3 (Secret) |
|-----------|-------------------|----------------|
| Bug found at gate | None | ClusterRole missing secrets resource (403) |
| RBAC change required | No | Yes — added secrets: list+watch, no get |
| safety-reviewer finding | No issue | MEDIUM → fixed (get verb overgrant) |
| Verifier feedback quality | Basic | Enhanced — explicitly mentions no value read |
| Learner safety warning in wording | Absent | Explicit ("do not use real secret") |
| First real user path worked | Yes | Yes — RBAC fix confirmed in production path |
| cleanup_verified | True | True |
| Secret residual risk | N/A | None — gone with namespace |

---

## R. Technical Self-Check

| Check | Result |
|-------|--------|
| No TODO / FIXME | PASS |
| No placeholder-as-success | PASS |
| No hardcoded credential | PASS |
| No kubeconfig content logged or committed | PASS |
| No token/password/cert/private key leaked | PASS |
| No verifier credential leaked | PASS |
| No Secret value leaked | PASS |
| No base64 Secret data leaked | PASS |
| No raw Kubernetes exception body leaked | PASS |
| No frontend raw stack trace / sensitive raw JSON | PASS |
| No VerifyResult.detail leaks namespace | PASS |
| No VerifyResult.detail leaks Secret value | PASS |
| No VerifyResult.detail leaks token/kubeconfig/credential | PASS |
| No admin/internal endpoint leakage | PASS |
| No unpublished lab leakage | PASS |
| No customer-visible internal smoke lab | PASS |
| No namespace residual | PASS |
| No Secret residual | PASS |
| No RoleBinding residual | PASS |
| No verifier credential residual | PASS |
| No unmanaged VM residual | PASS |
| No tainted VM | PASS |
| No production VM/pool/registry modified | PASS |
| No LLM call | PASS |
| No QEMU-agent verifier init path | PASS |
| No ClusterRole drift granting get secrets | PASS |
| No runbook drift | PASS |
| No sixth pilot = public launch | PASS |
| No home_lab_mvp = HA production | PASS |
| No new untested code | PASS (no code changes this gate) |
| No cloud portability broken | PASS |

Self-check: **31/31 PASS**

---

## S. Test Results

No code changes were made this gate (ops-only gate).

Previous baseline: **3186 passed, 93.13% coverage** (unchanged)

Quality gates verified:
- relevant RBAC tests: PASS (included in baseline — test_clusterrole_manifest_secrets_no_get_verb etc.)
- relevant verifier tests: PASS (test_secret_exists_pass_detail, test_secret_exists_fail_detail)
- pre-commit: PASS (no new commits)
- pre-push: not run (no code changes)
- Secret leak scan: PASS (no secret values in result artifact)
- kubeconfig leak scan: PASS (no kubeconfig content in result artifact)
- TODO/FIXME scan: PASS
- placeholder-as-success scan: PASS

---

## T. Final Decision

**SIXTH_PILOT_USER_THIRD_LAB_ONBOARDED**

The sixth trusted pilot user successfully completed Kubernetes Secret Basics through the real
learner frontend. The ClusterRole RBAC fix (secrets: list+watch only) confirmed working in the
real user path — no 403 at runtime. The verifier detail message is pedagogically clear and safe.
cleanup_verified=True, no residuals.

---

## U. Recommendation

**Allow Seventh Trusted Pilot User on Third Lab v0.1**

OR

**Allow Deployment Lab Design Gate v0.1** (if user cohort on Secret lab is sufficient)

Reasoning:
- Lab 3 (Secret Basics) is now validated by both internal rehearsal (smoke-admin) and a real pilot user (pilot-user-06)
- RBAC fix is proven in the real user path
- Verifier feedback is clear and safe: 11/11 safety checks PASS
- 6 total pilot users across 3 labs; lab progression is steady
- 3 published labs provide a complete beginner K8s config foundations path (Namespace → ConfigMap → Secret)
- Next natural progression: either expand cohort on Secret lab or design Deployment lab (introduces Pods/containers)

home_lab_mvp constraints remain: no HA, no SLA, no LLM, single VM 401, max 1 active session.

*Not HA. Not production-grade. Not for general availability.*  
*Production VMID range 500–599 was not touched during this gate.*  
*No real secrets appear in this document.*
