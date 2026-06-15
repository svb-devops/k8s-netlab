# Small Cohort Readiness Gate v0.1

**Gate**: Small Cohort Readiness Gate v0.1  
**Decision**: SMALL_COHORT_READY_WITH_NOTES  
**Date**: 2026-06-15  
**Operator**: Claude Code acting as senior dev + ops  
**Basis**: EIGHTH_PILOT_USER_DEPLOYMENT_LAB_ONBOARDED (commit `0e4b6ca`)  
**No real secrets in this document.**

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Current state | EIGHTH_PILOT_USER_DEPLOYMENT_LAB_ONBOARDED |
| Pilot history | 8 trusted users; 4 published labs; all sessions LAB_CLOSED |
| Open BLOCKER | NONE |
| Open HIGH | NONE |
| Open MEDIUM | NONE (all resolved) |
| Open NOTEs | 5 (all home_lab_mvp structural constraints; accepted) |
| Recommended cohort size | 3–5 trusted users |
| Recommended execution | Sequential; max 1 active session at a time |
| Key risks | T430 single-node; home ISP; no HA; no SLA |
| Final decision | **SMALL_COHORT_READY_WITH_NOTES** |
| Next step | Allow Small Cohort Pilot v0.1 with boundaries defined in Section G |

**SMALL_COHORT_READY_WITH_NOTES**: The LabGen `home_lab_mvp` platform is ready to begin a small cohort
pilot. All four published labs have been validated by real pilot users. RBAC is minimal and confirmed
stable across 8 sessions (list+watch only, no get). Cleanup is reliable across all 8 pilot sessions plus
multiple rehearsal sessions (cleanup_verified=True, 0 residuals each). No BLOCKER, HIGH, or MEDIUM issues
are open. Notes are structural `home_lab_mvp` constraints (single-node T430, home ISP, no HA, no SLA)
that must be disclosed to cohort users.

---

## B. Current Product Surface

| Lab | Lab ID | Verifiers | Real-user validation | Cleanup status | Known notes |
|-----|--------|-----------|---------------------|----------------|-------------|
| Kubernetes Basics: Your Isolated Lab Environment | 67fca5e4 | namespace_exists | pilot-user-01, 02, 03 (this lab); also used as step 1 in labs 2–4 | cleanup_verified=True all sessions | — |
| Kubernetes ConfigMap Basics: Store Your First Config | b0b97742 | namespace_exists + configmap_exists | pilot-user-04, 05 | cleanup_verified=True all sessions | NOTE: no progress indicator in UI (accepted) |
| Kubernetes Secret Basics: Protect Your First Configuration | d9f44383 | namespace_exists + secret_exists | pilot-user-06 | cleanup_verified=True | secret_exists: no value/base64 leak confirmed; RBAC fixed at design gate |
| Kubernetes Deployment Basics: Run Your First Workload | e52b8b80 | namespace_exists + deployment_ready | pilot-user-07, 08 | cleanup_verified=True all sessions | RBAC drift fix (b48a9a2) stable; PASS detail fix (0aa90e3) validated |

All 4 labs published, non-internal. Lab catalog shows 4 labs; no internal smoke labs visible.

**Verifier type coverage** (all validated end-to-end in real user sessions):

| Verifier type | API used | PASS detail confirmed | FAIL detail confirmed |
|--------------|----------|-----------------------|-----------------------|
| namespace_exists | list_namespaced_config_map (field selector) | Yes — "Your isolated namespace is active on the cluster." | Yes (Second Lab Triage) |
| configmap_exists | list_namespaced_config_map (field selector) | Yes — 'ConfigMap "my-app-config" was found in your isolated namespace.' | Yes |
| secret_exists | list_namespaced_secret (field selector, no data read) | Yes — 'Secret "my-app-secret" was found in your isolated namespace. The verifier confirmed the Secret object exists without reading its value.' | Yes |
| deployment_ready | list_namespaced_deployment (field selector + status check) | Yes — 'Deployment "hello-deployment" is available with 1 ready replica in your isolated namespace. Kubernetes has created a Pod for this workload.' | Yes |

---

## C. Runtime Readiness

| Check | Status | Detail |
|-------|--------|--------|
| home_lab_mvp profile | ✅ READY | Single-node T430 Proxmox VE, staging profile |
| T430 / Proxmox limits | ✅ ACCEPTED | Single physical host; power = T430 PSU; no HA |
| VM 401 (K3s control plane) | ✅ READY | labgen-home-k3s-staging-01, K3s v1.34.4, node Ready |
| Staging VMID 400–499 | ✅ ISOLATED | No overlap with production 500–599 |
| Production VMID 500–599 | ✅ UNTOUCHED | Not modified in any of the 8 pilot gates |
| Max active runtime session | ✅ ENFORCED | 1 (backend-enforced; `MAX_ACTIVE_SESSIONS` in config) |
| Max staging VMs | ✅ ENFORCED | 3 (`MAX_TOTAL_VMS=3` in env; current: 1 active VM) |
| Current active sessions | ✅ 0 | 20 total sessions; all LAB_CLOSED or LAB_ABORTED |
| Current lab namespaces | ✅ 0 | `kubectl get ns | grep '^lab-'` = no output |
| Tainted VMs | ✅ NONE | `data/tainted_vms.json` = `{}` |
| Cloudflare Tunnel | ✅ ACTIVE | cloudflared on 127.0.0.1:20241; public endpoint `https://lab.cloudnetops.tech` |
| Backend / frontend | ✅ HEALTHY | `{"status":"healthy","proxmox":{"connected":true}}` |
| Cleanup reliability | ✅ CONFIRMED | 8/8 pilot sessions + multiple rehearsal sessions: cleanup_verified=True, 0 residuals |

---

## D. Security / RBAC Readiness

| Check | Status | Detail |
|-------|--------|--------|
| Verifier init path | ✅ | `initialize_verifier_for_vm_host_side` — only accepted path for home_lab_mvp |
| Platform kubeconfig | ✅ | `/etc/labgen/home_lab_mvp.kubeconfig`, chmod 600, repo-external, not logged |
| QEMU-agent path | ✅ NOT USED | Explicitly forbidden for home_lab_mvp; creates unreachable kubeconfig (127.0.0.1:6443) |
| replace_cluster_role behavior | ✅ STABLE | 7th gate: fix applied; 8th gate: no regression; live ClusterRole always converges on re-init |
| No stale `get` verb | ✅ | `get` removed from all rules in `b48a9a2`; guardrail tests confirm |
| No stale `namespaces`/`endpoints` rules | ✅ | Removed in `b48a9a2`; 12 regression tests cover this |
| `deployments` list+watch | ✅ | PASS in 7th+8th pilot (`list_namespaced_deployment`) |
| `secrets` list+watch (no data read) | ✅ | PASS in 6th pilot (`list_namespaced_secret`, field selector) |
| `configmaps`/`pods`/`services` list+watch | ✅ | PASS in 1st–5th pilot |
| No ClusterRoleBinding | ✅ | Only namespace-scoped RoleBindings; deleted automatically on cleanup |
| No token / kubeconfig / credential leakage | ✅ | Not present in logs, responses, or any artifact |
| No Secret value / base64 leakage | ✅ | 6th pilot: 11/11 secret safety checks PASS |
| No raw workload object leakage | ✅ | `verifier.py` uses `_make_detail()` static text only |
| No raw Kubernetes exception body leakage | ✅ | Exception handler converts to sanitized VerifyResult |
| No namespace UUID leakage | ✅ | All detail messages use "your isolated namespace" |

---

## E. Teaching / UX Readiness

| Check | Status | Detail |
|-------|--------|--------|
| Learner catalog clarity | ✅ | 4 labs visible; correct titles; no internal smoke lab |
| Lab detail clarity | ✅ | Each lab shows title, description, step count |
| Step `do` guidance clarity | ✅ | Concrete `kubectl` commands in each step; replica/image constraints explicit |
| Check Step button clarity | ✅ | Button appears when step is current; result shown immediately |
| PASS feedback detail | ✅ | All 4 verifier types: learner-facing PASS detail messages visible in snapshot |
| FAIL feedback detail | ✅ | All 4 verifier types: actionable FAIL messages (iterated in Second Lab + Deployment Triage) |
| Complete flow | ✅ | Complete button appears only after `ready_to_complete=True`; guards against premature complete |
| Namespace concept | ✅ | Lab 1: "Your isolated namespace is active on the cluster." |
| ConfigMap concept | ✅ | Lab 2: 'ConfigMap "my-app-config" was found in your isolated namespace.' |
| Secret concept | ✅ | Lab 3: "without reading its value" — explicitly teaches no-read safety |
| Deployment concept | ✅ | Lab 4: "available with 1 ready replica … Kubernetes has created a Pod for this workload." |
| Ready replica concept | ✅ | "1 ready replica" maps directly to `kubectl get deployments` READY 1/1 column |
| Lab selection for cohort | ✅ | All 4 labs suitable; operator assigns per user interest and progression |

**Open NOTEs (not blocking)**:
- NOTE: UI progress indicator (step count display) is basic; no visual progress bar. Learner infers from step list. Accepted for cohort; post-cohort iteration candidate.
- NOTE: Lab `objectives` array is not rendered in current UI. Accepted.
- NOTE: Step retry hint ("it may take a short time") is present in step `do` text only; not in UI separately. Accepted.

---

## F. Ops Readiness

| Check | Status | Detail |
|-------|--------|--------|
| Operator pre-session checklist | ✅ | Runbook Section E.1 — 9-item checklist |
| Pre-cohort system precheck | ✅ | Same as Section E.1; confirmed clean as of this gate |
| Per-user start checklist | ✅ | Runbook Section E.1 |
| During-session monitoring | ✅ | Runbook Section E.2 — watch commands for sessions + namespaces + logs |
| Per-user complete checklist | ✅ | Runbook Section E.3 — 6-item post-session cleanup check |
| Residual check procedure | ✅ | Runbook Section E.3 + Section D.4 (tainted VM recovery) |
| Emergency stop | ✅ | Runbook Section F — F.1 stop new sessions → F.2 abort in-flight → F.3 stop staging VMs → F.4 cleanup namespaces → F.5 reclaim creds → F.6 preserve logs → F.7 record incident |
| Small Cohort Pilot Procedure | ✅ NEW | Runbook Section J (added this gate) |
| Feedback collection template | ✅ NEW | `docs/labgen/SMALL_COHORT_FEEDBACK_TEMPLATE_v0.1.md` (this gate) |
| Allowed user count | 3–5 trusted users | Sequential; operator approves each user after cleanup verified |
| Scheduling policy | One user at a time | Operator checks residuals between users |
| Max active sessions | 1 (backend-enforced) | Operator verifies 0 active before each user |
| Rollback policy | Run Section F (emergency stop) | Abort in-flight → clear residuals → root-cause → resume or pause |
| Communication template | See Section G | Included in cohort proposal |
| Audit preservation | ✅ | Runbook Section E.4 — snapshot copy + log preservation |

---

## G. Cohort Proposal

### Execution rules

| Rule | Value |
|------|-------|
| Cohort size | 3–5 trusted users (start with 3; extend to 5 based on feedback) |
| Concurrency | 1 active session only — backend enforced |
| Scheduling | One user at a time; operator approves each user before they start |
| User type | Trusted pilot users only — no public / anonymous access |
| Access | Private invite only — no public URL sharing |
| Labs | Current 4 published labs only |
| No fifth lab | Not during cohort |
| No public traffic | Not during cohort |
| No LLM | `LABGEN_LLM_PROVIDER_MODE=fake_only` throughout |
| No production VMID 500–599 | Not touched during cohort |
| No pool / registry changes | Production pool and registry remain unchanged |
| No SLA | Disclosed to users in advance |
| After each session | LAB_CLOSED + cleanup_verified=True + feedback collected → operator approves next user |

### Recommended lab paths

| User | Recommended path | Rationale |
|------|-----------------|-----------|
| User A | Kubernetes Basics + Deployment Basics | Full progression: namespace → workload |
| User B | ConfigMap Basics + Secret Basics | Data storage focus; both config and credentials |
| User C | Deployment Basics | Workload focus; Deployment + Pod concept in one lab |
| Optional User D | Secret Basics + Deployment Basics | Security + workload combination |
| Optional User E | TBD based on A–C feedback | Operator decides after first 3 complete |

### User brief template (to send before session)

```
You are being invited to a private, early-stage pilot of a Kubernetes learning platform.
This is NOT a production service — it is a home-lab MVP on a single server with no SLA.
The session may be interrupted if the infrastructure has issues; we will reschedule if needed.

What to expect:
- A short Kubernetes lab (10–20 minutes)
- A browser-based interface with step-by-step instructions
- A "Check Step" button to validate your progress
- A "Complete Lab" button when you finish

Important constraints:
- Use only the kubectl commands shown in each step
- Do not enter any real passwords, tokens, API keys, or sensitive data
- Use only the dummy values shown in the instructions
- The lab environment is isolated — no external internet access from the K8s cluster

After the session, please share: what worked, what was confusing, what could be better.

Session link: https://lab.cloudnetops.tech
```

---

## H. Risk Register

| Risk | Severity | Mitigation | Stop condition |
|------|----------|------------|----------------|
| Home ISP outage (Cloudflare Tunnel interruption) | MEDIUM | Notify users in advance; reschedule if ISP down before session | ISP outage >15min during session → abort and reschedule |
| T430 hardware failure (power, disk) | MEDIUM | Single physical host; no HA; no redundancy | Hardware failure → emergency stop (Section F); no SLA for resumption timeline |
| K3s VM 401 failure / unresponsive | MEDIUM | Recovery: Runbook D.2/D.3/D.5; K3s restart or VM rebuild from template 101 | VM 401 unreachable → block next session until VM recovered and verifier re-inited |
| Image pull failure (local registry down) | LOW | `nginx:1.25-alpine` pre-cached at `172.16.100.1:5000`; registry on same host as K3s | Registry unreachable during session → image pull fails → abort session; recover registry |
| RBAC drift regression | LOW | `replace_cluster_role` (b48a9a2) always converges live ClusterRole on re-init; 12 regression tests | Unexpected 403 during verifier check → halt session; re-init verifier and recheck; investigate before next user |
| Namespace cleanup residual | LOW | Namespace deletion cascades all workload objects; confirmed 0 residuals in 8+ sessions | Namespace still present 90s after session close → ops escalation; block next session |
| User confusion (concept gap) | LOW | Learner-facing PASS/FAIL detail; actionable FAIL guidance; Complete only after ready | User cannot proceed after 3 attempts → operator assist; note for lab iteration |
| Feedback insufficiency | LOW | Structured template (`SMALL_COHORT_FEEDBACK_TEMPLATE_v0.1.md`); operator notes | Too little feedback per user → extend cohort by 1–2 users |
| Ops fatigue | NOTE | Sequential execution; rest between sessions; document everything | Operator overloaded → pause cohort; resume next session day |
| Cloud portability gap | NOTE | home_lab_mvp is Proxmox-specific at infra layer; K8s/session layer is portable | Not a cohort stop condition; tracked for post-cohort cloud migration planning |
| No HA / no SLA | NOTE | Disclosed to cohort users before session | N/A — users accept this constraint explicitly |

---

## I. Go / No-Go Checklist

### GO conditions (all must be true to allow cohort)

| Condition | Status |
|-----------|--------|
| ≥1 published lab with real-user validation | ✅ — 4 labs, all real-user validated |
| 0 active sessions | ✅ — 0 active |
| 0 residual lab namespaces | ✅ — 0 `lab-*` namespaces |
| 0 tainted VMs | ✅ — `{}` |
| No open BLOCKER | ✅ — NONE |
| No open HIGH | ✅ — NONE |
| No open MEDIUM | ✅ — NONE (all resolved in prior gates) |
| Runbook covers emergency stop | ✅ — Section F |
| Cleanup reliable across ≥5 sessions | ✅ — 8/8 pilot sessions + rehearsals |
| RBAC minimal and drift-protected | ✅ — list+watch only; replace_cluster_role; 12 regression tests |
| Backend healthy | ✅ — `{"status":"healthy"}` |
| VM 401 K3s Ready | ✅ — Running, K3s v1.34.4 |
| LLM disabled | ✅ — `LABGEN_LLM_PROVIDER_MODE=fake_only` |

### NO-GO conditions (any one blocks cohort)

| Condition | Status |
|-----------|--------|
| Active session exists | ✅ CLEAR — 0 active |
| Residual lab namespace on K3s | ✅ CLEAR — 0 `lab-*` |
| Tainted VM | ✅ CLEAR — `{}` |
| Production VMID 500–599 touched | ✅ CLEAR — untouched |
| Open BLOCKER | ✅ CLEAR — none |
| Open HIGH | ✅ CLEAR — none |
| Open MEDIUM | ✅ CLEAR — none |
| LLM enabled | ✅ CLEAR — `fake_only` |

### HOLD conditions (pause until resolved)

| Condition | Current state |
|-----------|---------------|
| VM 401 not Ready | ✅ CLEAR — Ready |
| Cleanup failure in prior session | ✅ CLEAR — none |
| Backend unhealthy | ✅ CLEAR — healthy |
| Verifier creds missing or stale | ✅ CLEAR — present; re-init on next gate per Runbook C |

---

## J. Final Recommendation

**SMALL_COHORT_READY_WITH_NOTES**

All GO conditions satisfied. No NO-GO conditions triggered. All MEDIUM/HIGH/BLOCKER issues have been
resolved in prior gates. The five remaining NOTEs are structural `home_lab_mvp` constraints that do
not block the cohort but must be disclosed to participants.

**Notes disclosed to cohort users**:
1. `home_lab_mvp` is a single-node T430 Proxmox host; no HA; no power redundancy.
2. Home ISP dependency; Cloudflare Tunnel can handle brief outages; ISP failure stops the session.
3. K3s VM 401 is a single-node cluster; no control plane HA.
4. No SLA — sessions may be rescheduled if infrastructure fails.
5. Max 1 active session at a time; cohort is strictly sequential.

**Allow next step: Small Cohort Pilot v0.1**

Recommended start: 3 users minimum, up to 5. Operator must execute Section E.1 precheck before each
user, verify cleanup after each session (Section E.3), and approve next user only after cleanup_verified=True.

---

## K. Small Cohort Pilot v0.1 — Hard Boundaries

The following boundaries apply unconditionally to Small Cohort Pilot v0.1:

| Boundary | Value |
|----------|-------|
| Cohort size | 3–5 trusted users |
| Concurrency | 1 active session only |
| Scheduling | One user at a time |
| User type | Trusted pilot users only |
| Access | Private invite only |
| Labs | Current 4 published labs only |
| Fifth lab | NOT during cohort |
| Public traffic | NOT during cohort |
| LLM | NOT (fake_only enforced) |
| Production VMID 500–599 | NOT touched |
| Production pool / registry | NOT modified |
| SLA | NONE |
| Sensitive data | NOT entered (users briefed) |
| User-provided custom image | NOT allowed |
| Registry credential | NOT shared with users |
| After each session | LAB_CLOSED + cleanup_verified=True + feedback collected + operator approves next user |

---

## L. Runtime Rehearsal Decision

**No runtime rehearsal executed.**

This gate is documentation-only. No changes were made to:
- Frontend user-visible behavior
- Lab content (instructions, verifier templates, step text)
- Verifier behavior (`verifier.py`, `K8sVerifierClientAdapter`)
- RBAC behavior (ClusterRole, RoleBinding)
- Backend logic

The precheck confirms 0 active sessions, 0 residuals, 0 tainted VMs.
The 8 prior pilot sessions (all cleanup_verified=True) and multiple rehearsal sessions provide
sufficient evidence. Consuming VM 401 with a new runtime session would add no validation signal.

---

## M. No-Active-Session / No-Residual Precheck Result

| Check | Result |
|-------|--------|
| Active sessions | 0 (20 total; all LAB_CLOSED or LAB_ABORTED) |
| Lab namespaces on K3s | 0 (`kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get ns | grep "^lab-"` → no output) |
| Tainted VMs | `{}` (empty) |
| Backend health | `{"status":"healthy","proxmox":{"connected":true}}` |

Precheck: **ALL PASS**

---

## N. Technical Blocker Self-Check

| Check | Result |
|-------|--------|
| No TODO / FIXME (new, introduced by this gate) | PASS — no code changes |
| No placeholder-as-success | PASS |
| No hardcoded credential | PASS |
| No kubeconfig content leaked | PASS |
| No token / password / cert / private key leaked | PASS |
| No verifier credential leaked | PASS |
| No Secret value / base64 leaked | PASS |
| No image pull secret leaked | PASS |
| No raw Kubernetes exception body leaked | PASS |
| No raw Kubernetes Deployment / Pod object leaked | PASS |
| No frontend raw stack trace / sensitive raw JSON | PASS |
| No admin / internal endpoint leakage | PASS |
| No unpublished lab leakage | PASS |
| No customer-visible internal smoke lab | PASS |
| No namespace residual | PASS — 0 |
| No Deployment residual | PASS — 0 |
| No ReplicaSet residual | PASS — 0 |
| No Pod residual | PASS — 0 |
| No RoleBinding residual | PASS — 0 |
| No verifier credential residual | PASS — credentials present (per-VM persistent; correct behavior) |
| No unmanaged VM residual | PASS |
| No tainted VM | PASS — `{}` |
| No production VM / pool / registry modified | PASS |
| No LLM call | PASS — 0 |
| No QEMU-agent verifier init path | PASS |
| No overbroad RBAC | PASS |
| No `get` verb regression | PASS |
| No stale `namespaces` / `endpoints` rules regression | PASS |
| No runbook drift | PASS — Section J added this gate |
| No small cohort = public launch | PASS |
| No home_lab_mvp = HA production | PASS |
| No new untested code | PASS — no code changes |
| No cloud portability broken | PASS |
| Tests: 3213 passed | PASS |
| Coverage: 93.13% | PASS |

Self-check: **34/34 PASS**

---

## O. Evidence References

| Document | Role in evidence |
|----------|-----------------|
| `docs/labgen/EIGHTH_PILOT_USER_DEPLOYMENT_LAB_RESULT_v0.1.md` | 8th pilot: PASS detail fix end-to-end; RBAC stable; cleanup_verified=True |
| `docs/labgen/DEPLOYMENT_FEEDBACK_TRIAGE_v0.1.md` | Deployment lab: 0 BLOCKER/HIGH; RBAC drift root cause + fix; UX iteration |
| `docs/labgen/SEVENTH_PILOT_USER_DEPLOYMENT_LAB_RESULT_v0.1.md` | 7th pilot: RBAC drift discovery + fix; deployment_ready first real-user validation |
| `docs/labgen/SIXTH_PILOT_USER_THIRD_LAB_RESULT_v0.1.md` | 6th pilot: secret_exists PASS; Secret safety 11/11; secrets RBAC validated |
| `docs/labgen/THIRD_PILOT_LAB_DESIGN_RESULT_v0.1.md` | Secret lab design; secret_exists RBAC fix; safety-reviewer MEDIUM fixed |
| `docs/labgen/FIFTH_PILOT_USER_SECOND_LAB_RESULT_v0.1.md` | 5th pilot: configmap_exists PASS detail visible; clean cleanup |
| `docs/labgen/SECOND_LAB_FEEDBACK_TRIAGE_v0.1.md` | ConfigMap lab: 0 BLOCKER/HIGH; verifier detail messages for all 6 types |
| `docs/labgen/HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md` | Operational procedures; Section J (Small Cohort; added this gate) |
| `docs/labgen/HOME_LAB_MVP_PILOT_GATE_RESULT_v0.1.md` | PILOT_GATE_READY_WITH_NOTES baseline |
| `deploy/labgen/staging_ops_ticket_status.md` | All 6 tickets VERIFIED; full gate history |
| `deploy/labgen/staging_infrastructure_checklist.md` | Infrastructure status |
| `CHANGELOG.md` | Full commit history |

---

*Not HA. Not production-grade. Not for general availability.*  
*home_lab_mvp is a controlled pilot profile on single-node Proxmox (T430).*  
*No real secrets appear in this document.*  
*Production VMID range 500–599 was not touched during this gate.*
