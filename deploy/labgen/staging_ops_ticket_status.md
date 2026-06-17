# LabGen MVP — Staging Ops Ticket Status Tracker

> **Purpose**: Track completion status of each ops provisioning ticket.  
> **Updated**: 2026-06-17 — ALL 6 tickets VERIFIED; Runtime Session Smoke PASSED_WITH_NOTES; Pilot Gate READY_WITH_NOTES; First Pilot Lab RELEASED; First Pilot User ONBOARDED_WITH_NOTES; Pilot Feedback TRIAGED; Frontend Learner Smoke PASSED_WITH_NOTES; Second Pilot User ONBOARDED; Ops Runbook HARDENED; Third Pilot User ONBOARDED; Second Pilot Lab READY; Fourth Pilot User Second Lab ONBOARDED; Second Lab Feedback Triage TRIAGED_WITH_ITERATION; Fifth Pilot User Second Lab ONBOARDED; Third Pilot Lab READY; Sixth Pilot User Third Lab ONBOARDED; Deployment Lab READY; Seventh Pilot User Deployment Lab ONBOARDED; Deployment Feedback Triage TRIAGED_WITH_ITERATION; Eighth Pilot User Deployment Lab ONBOARDED; Small Cohort Readiness Gate SMALL_COHORT_READY_WITH_NOTES; Small Cohort Pilot SMALL_COHORT_PILOT_COMPLETED_WITH_NOTES; Small Cohort Triage SMALL_COHORT_TRIAGED_NEEDS_ITERATION; Real Human Learner Validation REAL_HUMAN_LEARNER_VALIDATED_WITH_NOTES; Learner kubectl Terminal Integration LEARNER_KUBECTL_TERMINAL_READY; Terminal Post-Integration Runtime Hardening TERMINAL_RUNTIME_HARDENED_WITH_NOTES; Real Human Re-validation for Labs 2-4 REAL_HUMAN_LABS_2_4_VALIDATED_WITH_NOTES; Real Human Cohort Round 2 REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES; Small Customer Pilot Preparation Gate SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES; Small Customer Pilot Execution SMALL_CUSTOMER_PILOT_BLOCKED; Article-to-Lab Pipeline Design Gate ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES; Article-to-Lab Implementation Prerequisites ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES; Article-to-Lab MVP Contract Schema Gate ARTICLE_TO_LAB_SCHEMA_READY_WITH_NOTES; **Article-to-Lab Draft Mode Implementation K8S_ARTICLE_TO_LAB_DRAFT_MODE_READY_WITH_NOTES**  
> **Current state**: ALL 6 ops tickets VERIFIED; SMALL_CUSTOMER_PILOT_BLOCKED (no suitable customer — technical system ready); **Article-to-Lab Draft Mode Implementation COMPLETE — K8S_ARTICLE_TO_LAB_DRAFT_MODE_READY_WITH_NOTES**: admin-only stub pipeline implemented (ArticleDraftRepository + StubFeasibilityClassifier + ArticleDraftService + article_draft_routes), 9 endpoints, 60 new tests, 3570 total tests pass, 93.03% coverage; raw text never persisted; sensitive content hard-rejected; generated drafts always DRAFT status; 0 LLM calls; recommended next step: K8s Article-to-Lab Admin Review Rehearsal; see `docs/labgen/K8S_ARTICLE_TO_LAB_DRAFT_MODE_IMPLEMENTATION_RESULT_v0.1.md`  
> **Code blocker resolved**: `K3sNamespaceLifecycleAdapter` is fully implemented (commit `44cce73`). Remaining blockers are ops-side only.  
> **Ticket pack**: `docs/labgen/OPS_PROVISIONING_TICKET_PACK_v0.1.md`  
> **Execution result**: `docs/labgen/STAGING_OPS_TICKET_EXECUTION_RESULT_v0.1.md`  
> **No real secrets in this file** — use `<set-in-secret-manager>` or `<placeholder>` only.

---

## Instructions

1. Ops team updates this file as each ticket is completed.
2. Change `BLOCKED_WITH_EVIDENCE` → `IN_PROGRESS` when work starts.
3. Change `IN_PROGRESS` → `READY_FOR_VERIFY` when injection is complete.
4. Run the verification wrapper and record the result.
5. Change `READY_FOR_VERIFY` → `VERIFIED` when `labgen_ops_ticket_verify.py` reports `"status": "VERIFIED"`.
6. Once all 6 tickets are VERIFIED, run the full secret injection verification and intake gate.
7. Keep this file as provisioning evidence.

---

## Ticket Status Table

| Ticket ID | Title | Owner | Status | Env Key | Evidence Path | Last Verification Command | Last Decision | Notes |
|-----------|-------|-------|--------|---------|---------------|--------------------------|---------------|-------|
| OPS-K3S-001 | Provision staging K3s kubeconfig / SA | Infra / K8s Ops | **VERIFIED** | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | `docs/labgen/CONTROLLED_K3S_ADAPTER_SMOKE_RESULT_v0.1.md` | smoke: `python scripts/labgen_controlled_k3s_adapter_smoke.py --env-file /etc/labgen/home_lab_mvp.env --allow-k8s-write --json` | **K3S_SMOKE_PASSED** (2026-06-13) | VM 401 (`labgen-home-k3s-staging-01`) provisioned; kubeconfig at `/etc/labgen/home_lab_mvp.kubeconfig` (chmod 600, not committed). K3s v1.34.4, node Ready. |
| OPS-AUTH-001 | Inject staging ADMIN_TOKEN | Security / Ops | **VERIFIED** | `ADMIN_TOKEN` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-AUTH-001 --json` | **VERIFIED** (2026-06-13) | Staging-specific ADMIN_TOKEN (64 hex chars) injected; ACCEPTED_MVP_RISK: stored in chmod 600 repo-external file (no external secret manager) |
| OPS-PROXMOX-001 | Configure staging PROXMOX_HOST | Infra / Proxmox Ops | **VERIFIED** | `PROXMOX_HOST` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-PROXMOX-001 --json` | **VERIFIED** (2026-06-13) | Same-Proxmox host (127.0.0.1); ACCEPTED_MVP_RISK (documented); Pool.Allocate ACL granted on k8s-netlab-staging |
| OPS-PROXMOX-002 | Inject staging PROXMOX_TOKEN_SECRET | Security / Proxmox Ops | **VERIFIED** | `PROXMOX_TOKEN_SECRET` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-PROXMOX-002 --json` | **VERIFIED** (2026-06-13) | Same token as production; ACCEPTED_MVP_RISK; scoped to staging pool k8s-netlab-staging |
| OPS-VM-001 | Inject staging VM SSH credential | Infra / VM Ops | **VERIFIED** | `VM_SSH_PASSWORD` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-VM-001 --json` | **VERIFIED** (2026-06-13) | Same VM_SSH_PASSWORD as production; ACCEPTED_MVP_RISK (same Proxmox) |
| OPS-REGISTRY-001 | Configure staging VM_REGISTRY_MIRROR | Infra / Registry Ops | **VERIFIED** | `VM_REGISTRY_MIRROR` | `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external) | `python scripts/labgen_ops_ticket_verify.py --env-file /etc/labgen/home_lab_mvp.env --ticket OPS-REGISTRY-001 --json` | **VERIFIED** (2026-06-13) | Local registry mirror (production marker; ACCEPTED_MVP_RISK for staging — same-Proxmox host) |

**Status legend**: `TODO` → `IN_PROGRESS` → `READY_FOR_VERIFY` → `VERIFIED` | `BLOCKED_WITH_EVIDENCE`

---

## Verification Commands

Replace `<staging-env-file>` with the path to your `.env.staging` file.

```bash
# Verify a single ticket
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --ticket OPS-K3S-001 \
    --json

# Verify all tickets at once
python scripts/labgen_ops_ticket_verify.py \
    --env-file <staging-env-file> \
    --all \
    --json

# Full secret injection verification (after all tickets VERIFIED)
python scripts/labgen_ops_secret_injection_verify.py \
    --env-file <staging-env-file> \
    --json
# Expected: "decision": "SECRET_INJECTION_READY"

# Intake gate (after SECRET_INJECTION_READY)
python scripts/labgen_ops_staging_intake_verify.py \
    --env-file <staging-env-file> \
    --base-url http://<staging-host>:8000 \
    --json
# Expected: "decision": "READY_TO_RERUN_CONTROLLED_STAGING_TRIAL"
```

---

## Current Gate State

| Gate | Status | Evidence |
|------|--------|----------|
| Staging infra bootstrap | `[x]` VERIFIED — home_lab_mvp profile | `docs/labgen/STAGING_INFRA_BOOTSTRAP_EXECUTION_RESULT_v0.1.md` |
| All 6 tickets VERIFIED | `[x]` **VERIFIED** (2026-06-13) | `docs/labgen/STAGING_OPS_TICKET_EXECUTION_RESULT_v0.1.md` |
| Secret injection: SECRET_INJECTION_READY | `[x]` **SECRET_INJECTION_READY** (2026-06-13) | `docs/labgen/OPS_SECRET_INJECTION_VERIFICATION_RESULT_v0.1.md` |
| Intake gate: READY_TO_RERUN | `[x]` **READY** (2026-06-13) | `docs/labgen/OPS_STAGING_INTAKE_VERIFICATION_RESULT_v0.1.md` |
| **K3S Adapter Smoke: K3S_SMOKE_PASSED** | `[x]` **K3S_SMOKE_PASSED** (2026-06-13) | `docs/labgen/CONTROLLED_K3S_ADAPTER_SMOKE_RESULT_v0.1.md` — VM 401 provisioned, all 11 phases PASS, cleanup_confirmed=true |
| **Runtime Session Smoke: PASSED_WITH_NOTES** | `[x]` **RUNTIME_SESSION_SMOKE_PASSED_WITH_NOTES** (2026-06-13) | `docs/labgen/CONTROLLED_HOME_LAB_RUNTIME_SESSION_SMOKE_RESULT_v0.1.md` |
| **Pilot Gate: READY_WITH_NOTES** | `[x]` **PILOT_GATE_READY_WITH_NOTES** (2026-06-13) | `docs/labgen/HOME_LAB_MVP_PILOT_GATE_RESULT_v0.1.md` — VM 400 cleaned; all residuals clear; pre-pilot actions required |
| **First Pilot User Onboarding: ONBOARDED_WITH_NOTES** | `[x]` **FIRST_PILOT_USER_ONBOARDED_WITH_NOTES** (2026-06-14) | `docs/labgen/FIRST_PILOT_USER_ONBOARDING_RESULT_v0.1.md` — pilot-user-01 completed; LAB_CLOSED; cleanup_verified=True; 3 bugs fixed in-session; 3137 tests pass, 93.12% coverage |
| **Pilot Feedback Triage: PILOT_FEEDBACK_TRIAGED** | `[x]` **PILOT_FEEDBACK_TRIAGED** (2026-06-14) | `docs/labgen/PILOT_FEEDBACK_TRIAGE_v0.1.md` — 0 BLOCKER/HIGH; 3 MEDIUM fixed; 2 LOW open; 5 NOTE open; second pilot user allowed after frontend smoke test |
| **Frontend Learner Pilot Smoke: PASSED_WITH_NOTES** | `[x]` **FRONTEND_LEARNER_SMOKE_PASSED_WITH_NOTES** (2026-06-14) | `docs/labgen/FRONTEND_LEARNER_PILOT_SMOKE_RESULT_v0.1.md` — 16 PASS 0 FAIL; 12 bugs fixed (CSP + 11 field mismatches); vm_id auto-discovery; cleanup_verified=True; 3139 tests; 93.13% |
| **Second Trusted Pilot User: ONBOARDED** | `[x]` **SECOND_PILOT_USER_ONBOARDED** (2026-06-14) | `docs/labgen/SECOND_PILOT_USER_ONBOARDING_RESULT_v0.1.md` — 23 PASS 0 FAIL 0 NOTE; pilot-user-02 via real frontend; cleanup_verified=True; ops gap documented (host-side verifier init); third user allowed; 3139 tests; 93.13% |
| **Ops Runbook Hardening: HARDENED** | `[x]` **OPS_RUNBOOK_HARDENED** (2026-06-14) | `docs/labgen/HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md` — OPS-INIT-001 documented; host-side verifier init path specified; QEMU-agent path forbidden for home_lab_mvp; 31 guardrail tests; VM recovery + emergency stop + cloud portability covered |
| **Third Trusted Pilot User Gate: ONBOARDED** | `[x]` **THIRD_PILOT_USER_ONBOARDED** (2026-06-14) | `docs/labgen/THIRD_PILOT_USER_ONBOARDING_RESULT_v0.1.md` — pilot-user-03; 19/19 Playwright PASS; first complete path (step PASS→Complete→LAB_CLOSED); VM 401 rebuilt per Runbook D.5; cleanup_verified=True; all residuals clean |
| **Fourth Trusted Pilot User — Second Lab: ONBOARDED** | `[x]` **FOURTH_PILOT_USER_SECOND_LAB_ONBOARDED** (2026-06-14) | `docs/labgen/FOURTH_PILOT_USER_SECOND_LAB_RESULT_v0.1.md` — pilot-user-04; Runbook precheck 20/20 PASS; pre-onboarding gate 19/19 PASS; frontend path 13/13 PASS; Step 1 (namespace_exists) + Step 2 (configmap_exists name=my-app-config) both PASS on first attempt; LAB_CLOSED; cleanup_verified=True; residual check 11/11 PASS; 0 LLM calls; QEMU-agent path not used; recommendation: allow 5th user OR iterate ConfigMap lab content |
| **Second Lab Feedback Triage: TRIAGED_WITH_ITERATION** | `[x]` **SECOND_LAB_FEEDBACK_TRIAGED_WITH_ITERATION** (2026-06-14) | `docs/labgen/SECOND_LAB_FEEDBACK_TRIAGE_v0.1.md` — 0 BLOCKER/HIGH; 1 MEDIUM fixed (configmap_exists empty detail); 3 LOW fixed (all 6 verify types now return learner-facing detail messages); 4 NOTE open (progress indicator, objectives array, ops burden); 11 new tests; internal rehearsal PASS (detail='ConfigMap "my-app-config" was found…'); cleanup_verified=True; 3181 tests; 93.13%; 5th user + 3rd lab design unlocked |
| **Fifth Trusted Pilot User — Second Lab: ONBOARDED** | `[x]` **FIFTH_PILOT_USER_SECOND_LAB_ONBOARDED** (2026-06-14) | `docs/labgen/FIFTH_PILOT_USER_SECOND_LAB_RESULT_v0.1.md` — pilot-user-05; Runbook precheck 19/19 PASS; pre-onboarding gate 20/20 PASS; Step 1 (namespace_exists detail visible) + Step 2 (configmap_exists detail: 'ConfigMap "my-app-config" was found in your isolated namespace…') both PASS on first attempt; no namespace/token/kubeconfig leak in detail; LAB_CLOSED; cleanup_verified=True; residual check 11/11 PASS; 0 LLM calls; QEMU-agent path not used; improved feedback validated by real user; Third Lab Design Gate unlocked |
| **Third Pilot Lab Design Gate: READY** | `[x]` **THIRD_PILOT_LAB_READY** (2026-06-14) | `docs/labgen/THIRD_PILOT_LAB_DESIGN_RESULT_v0.1.md` — Kubernetes Secret Basics published (lab_id=d9f44383); secret_exists RBAC bug found+fixed (ClusterRole missing secrets, caused 403); safety-reviewer MEDIUM fixed (secrets list+watch only, no get); 5 regression tests; StaticValidator 14/14 PASS; internal rehearsal LAB_CLOSED cleanup_verified=True; residual 11/11 PASS; 3186 tests 93.13%; 0 LLM; production VMID 500-599 UNTOUCHED; Sixth Trusted Pilot User on Third Lab Gate unlocked |
| **Sixth Trusted Pilot User — Third Lab: ONBOARDED** | `[x]` **SIXTH_PILOT_USER_THIRD_LAB_ONBOARDED** (2026-06-14) | `docs/labgen/SIXTH_PILOT_USER_THIRD_LAB_RESULT_v0.1.md` — pilot-user-06; Runbook precheck 20/20 PASS; verifier re-init gen=2 (host-side, QEMU-agent not used); RBAC confirmed (secrets list+watch only, no get); pre-onboarding gate 13/13 PASS; Secret Basics lab selected; session 38bb1a9e; Step 1 (namespace_exists PASS) + Step 2 (secret_exists my-app-secret PASS); Secret feedback safety 11/11 PASS (no value/base64/namespace/token/kubeconfig/raw-exception leak); LAB_CLOSED; cleanup_verified=True; residual 15/15 PASS; 0 LLM calls; production VMID 500-599 UNTOUCHED; 3186 tests 93.13% (no code changes); Seventh User OR Deployment Lab Design Gate unlocked |
| **Real Human Re-validation for Labs 2-4: VALIDATED_WITH_NOTES** | `[x]` **REAL_HUMAN_LABS_2_4_VALIDATED_WITH_NOTES** (2026-06-15) | `docs/labgen/REAL_HUMAN_REVALIDATION_LABS_2_4_RESULT_v0.1.md` — real learner (learner-H1) completed Lab 2 (ConfigMap), Lab 3 (Secret), Lab 4 (Deployment) end-to-end via kubectl web terminal; all 3 sessions LAB_CLOSED, cleanup_verified=True, 0 residuals; 4 bugs found+fixed live (Cloudflare CDN cache E-1, credential path mismatch E-2, wrong verifier provisioning function E-3, shared-VM credential reclaim wiping next session's creds E-4 — new `VM_CLEANUP_EXEMPT_IDS` reuse, safety-reviewer no BLOCKER); 1 NOTE open (confusing kubectl plugin-resolution error, unreproduced); 3394 tests 93.22%; 0 LLM calls; production VMID 500-599 UNTOUCHED; closes prior UX-H1 finding; Small Cohort Pilot round 2 recommended next |
| **Real Human Cohort Round 2: COMPLETED_WITH_NOTES** | `[x]` **REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES** (2026-06-16) | `docs/labgen/REAL_HUMAN_COHORT_ROUND2_RESULT_v0.1.md` — 2 real learners (learner-r2-a, learner-r2-b), 4 labs each, 8/8 sessions LAB_CLOSED, 100% step-check first-pass, 0 step failures, 0 residuals; all security checks PASS (no kubeconfig/token/credential leak); 1 MEDIUM resolved live (422 no_vm_assigned — VM ownership not transferred, ops-only fix); Sections 3–10 learner self-report PENDING_USER_INPUT (qualitative, non-blocking); 0 LLM calls; production VMID 500-599 UNTOUCHED; strongest technical result to date |
| **Small Customer Pilot Preparation Gate: READY_WITH_NOTES** | `[x]` **SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES** (2026-06-16) | `docs/labgen/SMALL_CUSTOMER_PILOT_PREPARATION_GATE_v0.1.md` — VM ownership/assignment runbook gap fixed (§K added to Runbook); pilot scope, customer criteria, pre-pilot technical gate, onboarding notice, feedback template (12 questions), emergency stop conditions, and North Star alignment all defined; decision: READY_WITH_NOTES (Sections 3–10 qualitative feedback outstanding, per-session §K protocol required); 0 code changes; 0 LLM calls; production VMID 500-599 UNTOUCHED |
| **Small Customer Pilot Execution: BLOCKED** | `[x]` **SMALL_CUSTOMER_PILOT_BLOCKED** (2026-06-16) | `docs/labgen/SMALL_CUSTOMER_PILOT_RESULT_v0.1.md` — Pre-Pilot Gate system checks all PASS (backend/VM 401/K3s healthy, 4 published labs, 0 residuals, 0 tainted VMs, 0 active sessions); blocker: NO_SUITABLE_SMALL_CUSTOMER — 28 registered users all test/dev accounts, no external customer meeting Section 四 criteria identified; NOTE: 356 Python draft labs found (stub-generated, all draft, not customer-visible); NOTE: LAB_START_FAILED stale session (k8s_test, no K3s residual); 0 LLM calls; production VMID 500-599 UNTOUCHED; system technically ready, awaiting customer identification |
| **Article-to-Lab Pipeline Design Gate: READY_WITH_NOTES** | `[x]` **ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES** (2026-06-16) | `docs/labgen/ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` — full pipeline designed: Feasibility Gate (3 tiers: Directly/Partially/Not Lab-Ready) + Draft Lab Contract schema (source_grounding, unsupported_inferences, admin_decision) + Admin Review flow + StaticValidator extensions (5 new checks) + Internal Rehearsal gate + Domain Adapter interfaces (K8s complete; Linux/Docker/Networking/Database designed) + Verifier Strategy (5 candidate states; no LLM direct publish) + Cleanup / Credential lifecycle + Safety Policy (article flags + runtime + output safety); existing K8s infrastructure reuse fully mapped; 3 go/no-go blockers identified (N-01: LLM provider, N-02/N-03: article storage/copyright policy); N-01/N-02/N-03 resolved in Prerequisites gate (2026-06-16); 0 LLM calls; 0 code changes; production VMID 500-599 UNTOUCHED |
| **Article-to-Lab Implementation Prerequisites: READY_WITH_NOTES** | `[x]` **ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES** (2026-06-16) | `docs/labgen/ARTICLE_TO_LAB_IMPLEMENTATION_PREREQUISITES_v0.1.md` — N-01 RESOLVED: v0.1 stub mode (no live LLM), `LLMProviderPort` abstract interface, fail-closed rules for all LLM failure modes, self-hosted ruled out on T430, commercial API deferred to post-stub-validation; N-02 RESOLVED: ephemeral source text (discarded after processing), persistent fields: content_hash + source_metadata + feasibility_result + source_grounding_snippets + draft contract, sensitive content immediate discard, access boundary defined; N-03 RESOLVED: user consent required per submission (explicit checkbox), no long-term raw text, 30-day rejection metadata retention, audit indefinite (hash+decision only), admin-only v0.1 = low copyright exposure; all 3 blockers resolved; recommended next step resolved in G-25; 0 LLM calls; 0 code changes; production VMID 500-599 UNTOUCHED |
| **Article-to-Lab MVP Contract Schema Gate: READY_WITH_NOTES** | `[x]` **ARTICLE_TO_LAB_SCHEMA_READY_WITH_NOTES** (2026-06-16) | `docs/labgen/ARTICLE_TO_LAB_MVP_CONTRACT_SCHEMA_GATE_v0.1.md` — 11 Pydantic models: ArticleSourceMetadata/FeasibilityResult/SafetyFlag(13 values)/SourceGroundingSnippet/UnsupportedInference/TargetDomain(8 values including cloud blocked by default)/ArticleLabRuntimeRequirement/VerifierCandidate/ArticleDraftLabContract/AdminDecision/ArticleStoragePolicy; ArticleDraftValidator with 15 guardrail checks (rejected feasibility / partial feasibility / directly-ready-requires-admin / missing grounding / high-blocker inference / no raw text / no sensitive grounding / admin-approve-requires-confirmations / unknown domain / unsafe verifier / cleanup required / LLM bypass prevention / cloud domain blocked / source_url no scraping / user confirmations); 116 tests pass, 0 LLM calls; runtime/verifier/terminal unchanged; production VMID 500-599 UNTOUCHED; implementation may start: K8s Article-to-Lab Draft Mode Implementation |

**None of the above may be declared passed until the corresponding verification script outputs the READY/PASSED decision.**

---

## Unblock Path (concrete next actions for ops)

1. **Create real `.env.staging`** — do NOT copy from `.env.staging.example`. Use secret manager to inject real values.
2. For each ticket below, perform the infra action and inject the real value:

| Ticket | Required Action |
|--------|----------------|
| OPS-K3S-001 | Provision staging K3s cluster; write kubeconfig to absolute path; set `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<abs-path>` |
| OPS-AUTH-001 | Generate ≥32-char random token; set `ADMIN_TOKEN=<token>` |
| OPS-PROXMOX-001 | Set `PROXMOX_HOST=<real-staging-proxmox-hostname-or-IP>` |
| OPS-PROXMOX-002 | Create staging Proxmox API token; set `PROXMOX_TOKEN_SECRET=<uuid>` |
| OPS-VM-001 | Set `VM_SSH_PASSWORD=<real-credential>` |
| OPS-REGISTRY-001 | Deploy staging registry; push required images; set `VM_REGISTRY_MIRROR=http://<host>:<port>` |

3. Run per-ticket verification: `python scripts/labgen_ops_ticket_verify.py --env-file .env.staging --ticket <ID> --json`
4. When all 6 show `"status": "VERIFIED"`, run: `python scripts/labgen_ops_ticket_verify.py --env-file .env.staging --all --json`
5. Then proceed to secret injection verify → intake gate → controlled trial rerun.

---

## Dependency Graph

```
OPS-K3S-001 ─────────────────────────────────────────────┐
OPS-AUTH-001 ────────────────────────────────────────────┤
OPS-PROXMOX-001 ─────────────────────────────────────────┤
OPS-PROXMOX-002 ─────────────────────────────────────────┤──▶ All VERIFIED
OPS-VM-001 ──────────────────────────────────────────────┤        │
OPS-REGISTRY-001 ────────────────────────────────────────┘        │
                                                                   ▼
                                              SECRET_INJECTION_READY
                                                                   │
                                                                   ▼
                                       READY_TO_RERUN_CONTROLLED_STAGING_TRIAL
                                                                   │
                                                                   ▼
                                               Controlled Staging Trial Live Run
```

---

*No real secrets appear in this file.  
All example values use `<placeholder>` or `<set-in-secret-manager>` format.  
Ops updates this file in-place as each ticket progresses.*

---

This gate remains aligned with PROJECT_NORTH_STAR_v0.1: Article-to-Lab / Technical Content-to-Experiment Platform, "读完即练，结果说话". K8s domain proof for the broader Article-to-Lab platform.

## North Star Alignment Check

| Check | Status |
|-------|--------|
| Still serving Article-to-Lab | YES |
| Still supports "读完即练，结果说话" | YES |
| Avoids K8s-only hardcoding | YES — staging config is domain-specific by necessity (K3s kubeconfig, RBAC), but adapter boundaries (Runtime/Verifier/Terminal/Cleanup Adapter) remain swappable per PROJECT_NORTH_STAR_v0.1 §6 |
| Preserves Linux/domain portability | YES — no change to adapter contracts |
| No skipped human review | YES |
| No skipped StaticValidator | YES |
| No skipped cleanup | YES |
| No premature public launch expansion | YES |
| No home_lab_mvp → production promotion | YES |
