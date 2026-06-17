# Small Customer Pilot Preparation Gate v0.1

**Date**: 2026-06-16
**Operator**: Claude Code acting as senior dev + ops
**Status**: SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES
**Based on**: Real Human Cohort Round 2 — REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES (2026-06-16)
**No real secrets in this document.**

This gate remains aligned with PROJECT_NORTH_STAR_v0.1: Article-to-Lab / Technical
Content-to-Experiment Platform, "读完即练，结果说话". K8s domain proof for the broader
Article-to-Lab platform.

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Gate decision | **SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES** |
| Ready to enter Small Customer Pilot Execution | YES — with conditions documented in §I |
| Round 1 evidence | REAL_HUMAN_LEARNER_VALIDATED_WITH_NOTES (1 learner, Lab 1 complete, Labs 2–4 blocked pre-terminal) |
| Re-validation evidence | REAL_HUMAN_LABS_2_4_VALIDATED_WITH_NOTES (1 learner, Labs 2–4 all complete, terminal validated) |
| Round 2 evidence | REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES (2 learners, 4/4 labs each, 8/8 LAB_CLOSED) |
| Remaining notes | Sections 3–10 learner self-report (qualitative) outstanding; VM assignment per-session documented in Runbook §K |
| LLM calls | 0 |
| Production VMID 500–599 | Untouched throughout all rounds |

---

## B. Pilot Scope

This is **not** a public launch. This is **not** a production deployment. This is **not** an HA
service. This is a **private small customer pilot** with strict operational boundaries.

| Dimension | Boundary |
|-----------|---------|
| Audience | 1 trusted customer or 1 trusted small team (≤ 3 real learners) |
| Concurrency | Max 1 active session (backend-enforced) |
| Scheduling | Sequential only — one learner at a time, operator approves each session |
| Supervision | Operator-supervised throughout |
| Labs available | Current 4 published K8s domain proof labs only |
| SLA | None — not promised |
| Availability | Not 24/7 — scheduled time slots only |
| Data persistence | Not promised — environment reclaimed after each session |
| No sharing | No public URLs, no link sharing, no broadcast invitations |
| No real secrets | Learner must not enter real secret/token/password/API key/private key |
| No custom images | registry.tar / custom Docker images not accepted |
| No registry credentials | Learner must not supply Docker Hub or other registry credentials |
| No production workloads | Platform is not connected to any production system |
| No fifth lab | Not during this pilot |
| No LLM | `LABGEN_LLM_PROVIDER_MODE=fake_only` enforced |
| No production VMID | 500–599 must not be touched |

---

## C. Customer Candidate Criteria

### Suitable

- Real person or small trusted team (≤ 3 learners)
- Can accept early-stage MVP with no SLA
- Willing to provide structured feedback
- Learners have basic command-line familiarity
- Can commit to a pre-scheduled sequential time slot
- Understands and accepts the conditions in §E onboarding notice

### Not suitable

- Requires production-grade reliability
- Requires concurrent multi-user access
- Requires public URL access
- Requires custom images or real registry credentials
- Requires enterprise-level SLA
- Requires persistent long-term environment
- Not willing to provide feedback
- Requires fully unattended operation

---

## D. Pre-Pilot Technical Gate

Run ALL of the following before the pilot session. All checks must pass.

### D.1 System health

| Check | Command | Expected |
|-------|---------|----------|
| Backend healthy | `curl -sf http://localhost:8000/api/health` | `{"status":"healthy"}` |
| Frontend reachable | `curl -sf https://lab.cloudnetops.tech/labgen-catalog.html -o /dev/null -w "%{http_code}"` | `200` |
| Cloudflare Tunnel healthy | `curl -sf https://lab.cloudnetops.tech/api/health` | `{"status":"healthy"}` |
| VM 401 running | `qm status 401` | `status: running` |
| K3s Ready | `kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get nodes --no-headers` | `Ready` |
| LLM disabled | `grep LABGEN_LLM_PROVIDER_MODE /etc/labgen/home_lab_mvp.env` | `fake_only` |

### D.2 Catalog and session state

| Check | Command | Expected |
|-------|---------|----------|
| 4 published labs visible | `curl -sf https://lab.cloudnetops.tech/api/labgen/drafts?status=published \| python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))"` | `4` |
| No unpublished labs visible in catalog | Manual review of catalog page | Only 4 published labs shown |
| No active sessions | Check `data/lab_sessions.json` | 0 active |
| No lab namespaces | `kubectl --kubeconfig ... get ns \| grep "^lab-"` | No output |
| No tainted VMs | `cat data/tainted_vms.json` | `{}` |
| No terminal credential residuals | `ls /var/lib/labgen-staging/learner-kubeconfigs/` | Empty or absent |

### D.3 Security posture

| Check | Expected |
|-------|---------|
| Terminal visible in LAB_ACTIVE sessions | YES (auto-appears when session is active) |
| WebSocket auth/session owner check | Enabled (not modified) |
| Command sandbox (allowlist enforced) | Enabled — `kubectl` allowlist enforced |
| Audit/redaction enabled | Enabled |
| Max active session = 1 | Backend-enforced |
| RBAC minimality: list+watch only, no get | Confirmed via ClusterRole (no `get` verb) |
| No stale `get` verb in ClusterRole | Verified per RBAC-DRIFT-001 fix (commit `b48a9a2`) |
| No ClusterRoleBinding | Confirmed — namespace-scoped RoleBinding only |

### D.4 VM ownership / assignment

| Check | Required |
|-------|---------|
| VM 401 current owner identified | YES — run Runbook §K.2 check #1 |
| Pilot learner account created | YES — account must exist before assignment |
| VM ownership transferred to pilot learner | YES — run Runbook §K.3 |
| Assignment verified (§K.4 prints PASS) | YES — must pass before inviting learner |

### D.5 Verifier re-initialization

```bash
source /root/k8s-netlab/venv/bin/activate
python3 - <<'EOF'
from backend.vm_manager import initialize_verifier_for_vm_host_side
result = initialize_verifier_for_vm_host_side(401, "/etc/labgen/home_lab_mvp.kubeconfig")
print("success:", result["success"])
if not result["success"]:
    raise SystemExit(1)
EOF
# Expected: success: True
```

Must run before EACH lab session — not only between users.

### D.6 Approved image readiness (Deployment lab)

| Image | Registry check |
|-------|---------------|
| `nginx:1.25-alpine` | Must be present in internal registry (see `VM_REGISTRY_MIRROR` in env) |

```bash
# Replace <registry-host> with the value of VM_REGISTRY_MIRROR from /etc/labgen/home_lab_mvp.env
curl -sf http://<registry-host>/v2/nginx/tags/list
# Expected: {"name":"nginx","tags":["1.25-alpine",...]}
```

---

## E. Customer-Facing Onboarding Notice

Send to the customer/learner before their session. They must acknowledge before starting.

---

**LabGen Early Pilot — Participant Notice**

Thank you for participating in this early pilot. Please read the following before starting:

1. **This is an early-stage MVP.** It is not a production service. Bugs and rough edges exist.
2. **Do not enter real secrets.** Do not type your actual passwords, API keys, tokens, or private keys into the terminal. The lab environment uses only dummy example values.
3. **Do not upload real data.** Do not use this platform for data that belongs in a production environment.
4. **Do not use production environment information.** Use only the example commands provided in each lab step description.
5. **Do not supply custom images or registry credentials.**
6. **Each experiment environment is temporary.** When you complete or abort a lab, your namespace and all resources inside it are automatically reclaimed. You will not be able to retrieve them.
7. **Sessions are sequential.** Only one session is active at a time. Concurrent use is not supported.
8. **No SLA.** If the system encounters an error, the operator will assist. Please record what happened and report it.
9. **Your feedback is the most valuable part of this pilot.** After your session, please answer the feedback questions honestly. Your answers directly shape what gets improved.
10. **This pilot is private.** Please do not share the URL or invite others. Access is by invitation only.

If you encounter any issue, please stop and report it immediately — do not attempt workarounds.

---

## F. Feedback Collection

Collect ALL of the following after each pilot session. Do not leave fields blank — if the learner
did not have an opinion, record that explicitly.

| # | Dimension | Question |
|---|-----------|---------|
| 1 | User background | Prior command-line / Kubernetes experience? |
| 2 | Labs attempted | Which lab(s) did you attempt and complete? |
| 3 | Step clarity | Were the step instructions clear? Was there any step where you read the description but didn't know what command to run? |
| 4 | Concept clarity | After completing the lab, did you feel you understood the K8s concept being demonstrated? |
| 5 | Terminal clarity | Was the kubectl terminal panel obvious? Did you know what to type in it? |
| 6 | Command clarity | Were the example commands in the step description clear? Did you need to modify them? |
| 7 | Verifier feedback clarity | After clicking "Check Current Step," was the PASS/FAIL feedback clear and useful? |
| 8 | Failure / retry experience | Did any step fail? If so, did the failure message help you understand what went wrong? |
| 9 | Perceived speed | Did the environment feel fast enough? Were there noticeable delays? |
| 10 | Willingness to continue | Would you use this platform again? Would you recommend it? What is the one thing most worth improving? |
| 11 | Article-to-skill transfer | Did completing this lab help turn a technical concept you'd read about into a skill you practiced? |
| 12 | Pilot continuation | Do you want to continue participating in the pilot as more labs become available? |

File feedback as `docs/labgen/SMALL_CUSTOMER_PILOT_FEEDBACK_<learner-id>_<YYYYMMDD>.md` before
the next session.

---

## G. Emergency Stop Conditions

Stop the pilot immediately if ANY of the following occurs:

| Condition | Action |
|-----------|--------|
| Active sessions > 1 | Stop accepting new sessions; abort in-flight; investigate |
| `cleanup_verified=False` | Block next session; run residual check; taint VM if needed |
| Residual not zero (namespace/RoleBinding/workload) | Block next session; manually clean; investigate |
| VM assignment failure (`no_vm_assigned`) recurring | Stop pilot; fix runbook gap; re-run full precheck |
| Tainted VM not cleared before next session | Block until taint is cleared per Runbook §D.4 |
| Verifier credential residual detected | Block; run credential audit; re-init verifier |
| Learner terminal credential residual detected | Block; manually reclaim; investigate |
| Any kubeconfig / token / cert / private key leak in logs or API responses | STOP IMMEDIATELY; audit all sessions; preserve all logs |
| Any Secret value or base64-encoded data returned in API response | STOP IMMEDIATELY |
| Raw K8s workload object returned in API response | Stop; audit; patch |
| Cross-namespace access detected | STOP IMMEDIATELY |
| Admin/internal endpoint (`/internal/`) accessible to learner | STOP IMMEDIATELY |
| Backend or frontend crashes or becomes unreachable | Stop admitting users; investigate before resuming |
| Cloudflare Tunnel becomes unreachable | Stop; restore tunnel first |
| K3s VM 401 becomes unhealthy | Stop; run Runbook §D.2 recovery |
| Production VMID 500–599 touched | STOP IMMEDIATELY — audit all `qm` commands |
| Operator cannot safely supervise | Pause pilot; resume only when supervision is restored |

After any emergency stop: do NOT resume until root cause is identified, fixed, and full J.2
pre-cohort precheck is re-run and passes.

---

## H. North Star Alignment

| Check | Status |
|-------|--------|
| This pilot is aligned with PROJECT_NORTH_STAR_v0.1 | YES |
| K8s is a domain proof for Article-to-Lab, not the final product boundary | YES |
| The goal is still "读完即练，结果说话" | YES |
| This pilot validates whether real learners can turn technical content into hands-on skill through temporary labs | YES |
| This pilot does not mean LabGen has completed arbitrary article-to-lab generation | YES — LLM pipeline not yet live |
| LLM/article ingestion remains future-stage and must pass Lab Feasibility Gate before deployment | YES |
| Future Linux / multi-domain migration capability preserved | YES — adapter boundaries unchanged |

---

## I. Final Decision

**SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES**

### Rationale

**Evidence base** (why READY):
- Three rounds of real human validation prove the 4-lab K8s domain proof learning path is
  viable end-to-end: namespace isolation, terminal, verifier, cleanup closed loop — all work.
- Round 2 (2026-06-16): 2 learners × 4 labs = 8 sessions, 100% LAB_CLOSED,
  100% step-check first-pass, 0 residuals, all security checks PASS.
- Every round exposed and fixed real bugs — the platform is hardened against real learner usage.
- Security posture: no kubeconfig/token/credential leak in any session across all rounds.

**WITH_NOTES** (why not unqualified READY):
1. Sections 3–10 qualitative learner self-report from Round 2 are PENDING_USER_INPUT.
   This is the subjective UX layer — it does not block the technical prep, but it must
   be collected before drawing product conclusions from the pilot.
2. VM ownership assignment is now documented in Runbook §K — the ops gap exposed by
   Round 2 is closed, but each new pilot session requires following §K protocol. This is
   not a code gap; it is an ops discipline requirement.

**NOT BLOCKED** because:
- All technical/security gates are clear.
- The one ops gap (VM assignment) has been addressed in the Runbook.
- The qualitative feedback layer is outstanding but not a technical preparation blocker.

### Conditions for entering Small Customer Pilot Execution

1. Operator follows Runbook §K (VM ownership / learner assignment) for every session.
2. Runbook §J.2 pre-cohort precheck (all 10 checks) passes before every session.
3. Verifier is re-initialized (§J.2 check #8) before every lab session.
4. Learner acknowledges §E onboarding notice before starting.
5. Operator supervises the session (monitoring per §J.4).
6. Post-session cleanup and residual check (§J.5–J.6) passes before the next session.
7. Sections 3–10 feedback (§F) captured after each session.
8. Emergency stop (§G) triggers are understood and actioned immediately.

### What this gate does NOT authorize

- Not authorized to raise max concurrent sessions beyond 1.
- Not authorized to increase cohort beyond 3 real learners without a new gate.
- Not authorized to publish a fifth lab.
- Not authorized to enable LLM.
- Not authorized to touch production VMID 500–599.
- Not authorized to announce public access.
- Not authorized to remove operator supervision.
- Not authorized to skip VM ownership assignment precheck.

---

## J. Deliverables Produced by This Gate

| Deliverable | Status |
|-------------|--------|
| `HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md` §K — VM Ownership / Learner Assignment Precheck | ✅ Added |
| `SMALL_CUSTOMER_PILOT_PREPARATION_GATE_v0.1.md` (this document) | ✅ Created |
| `deploy/labgen/staging_ops_ticket_status.md` — updated with Round 2 + Prep Gate result | ✅ Updated |
| `deploy/labgen/staging_infrastructure_checklist.md` — updated with Prep Gate gate entry | ✅ Updated |
| `CHANGELOG.md` [Unreleased] entry | ✅ Updated |
| `docs/labgen/REAL_HUMAN_COHORT_ROUND2_RESULT_v0.1.md` — committed (was untracked) | ✅ Committed |

---

## K. Technical Self-Check

| Check | Status |
|-------|--------|
| No TODO/FIXME in deliverables | PASS |
| No placeholder-as-success in deliverables | PASS |
| No K8s framed as permanent product boundary | PASS |
| No home_lab_mvp promoted to production | PASS |
| No small customer pilot declared as public launch | PASS |
| No SLA declared | PASS |
| No HA declared | PASS |
| No VM ownership assignment skipped | PASS — §K.6 requires it unconditionally |
| No `no_vm_assigned` runbook gap remaining | PASS — §K.5 protocol defined |
| No cleanup/residual checks skipped | PASS — §J.5–J.6 required after each session |
| No credential checks skipped | PASS — §K.2 and §D.3 cover all credential types |
| No terminal socket/process cleanup skipped | PASS — covered by §J.5 and §G |
| No platform kubeconfig leak | PASS — stored at `/etc/labgen/home_lab_mvp.kubeconfig`, never in logs or responses |
| No verifier credential leak | PASS — verifier kubeconfig stays in `creds/vm_creds/`, never returned to learner |
| No learner credential leak | PASS — per-session kubeconfig in `/var/lib/labgen-staging/learner-kubeconfigs/`, reclaimed on session close |
| No token/password/cert/private key leak | PASS — confirmed in all Round 2 sessions |
| No Secret value/base64 leak | PASS — confirmed in all Round 2 sessions |
| No raw workload object leak | PASS |
| No admin/internal endpoint leakage | PASS — `/internal/` endpoints protected by `X-Admin-Token` |
| No production VM/pool/registry modified | PASS |
| No LLM calls | PASS — `LABGEN_LLM_PROVIDER_MODE=fake_only` |
| No customer pilot started by this gate | PASS — preparation only |
| No second lab published | PASS (4 labs, no fifth) |
| No concurrency increase | PASS — max 1 session unchanged |
| No Linux/multi-domain portability broken | PASS |
| Still aligned with "读完即练，结果说话" | PASS |

---

## L. Next Step

**→ Small Customer Pilot Execution**

1. Identify pilot customer / learner(s) (≤ 3 real learners total).
2. Create learner account(s).
3. Follow Runbook §K (VM ownership assignment) for each learner.
4. Run Runbook §J.2 full pre-cohort precheck.
5. Send §E onboarding notice; collect acknowledgement.
6. Supervise session per §J.4.
7. Collect §F feedback after each session.
8. File result artifact `docs/labgen/SMALL_CUSTOMER_PILOT_EXECUTION_v0.1.md` after pilot completes.

---

*Not HA. Not production-grade. Not for general availability.*
*home_lab_mvp is a controlled pilot profile on single-node Proxmox (T430).*
*No real secrets appear in this document.*
*Production VMID range 500–599 was not touched during this gate.*
*0 LLM calls. 0 customer pilot started. 0 second lab published. No concurrency increase.*
