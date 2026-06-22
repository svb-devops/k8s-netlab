# LabGen MVP — Staging Ops Ticket Status Tracker

> **Purpose**: Track completion status of each ops provisioning ticket.  
> **Updated**: 2026-06-22 — ALL 6 tickets VERIFIED; Runtime Session Smoke PASSED_WITH_NOTES; Pilot Gate READY_WITH_NOTES; First Pilot Lab RELEASED; First Pilot User ONBOARDED_WITH_NOTES; Pilot Feedback TRIAGED; Frontend Learner Smoke PASSED_WITH_NOTES; Second Pilot User ONBOARDED; Ops Runbook HARDENED; Third Pilot User ONBOARDED; Second Pilot Lab READY; Fourth Pilot User Second Lab ONBOARDED; Second Lab Feedback Triage TRIAGED_WITH_ITERATION; Fifth Pilot User Second Lab ONBOARDED; Third Pilot Lab READY; Sixth Pilot User Third Lab ONBOARDED; Deployment Lab READY; Seventh Pilot User Deployment Lab ONBOARDED; Deployment Feedback Triage TRIAGED_WITH_ITERATION; Eighth Pilot User Deployment Lab ONBOARDED; Small Cohort Readiness Gate SMALL_COHORT_READY_WITH_NOTES; Small Cohort Pilot SMALL_COHORT_PILOT_COMPLETED_WITH_NOTES; Small Cohort Triage SMALL_COHORT_TRIAGED_NEEDS_ITERATION; Real Human Learner Validation REAL_HUMAN_LEARNER_VALIDATED_WITH_NOTES; Learner kubectl Terminal Integration LEARNER_KUBECTL_TERMINAL_READY; Terminal Post-Integration Runtime Hardening TERMINAL_RUNTIME_HARDENED_WITH_NOTES; Real Human Re-validation for Labs 2-4 REAL_HUMAN_LABS_2_4_VALIDATED_WITH_NOTES; Real Human Cohort Round 2 REAL_HUMAN_COHORT_ROUND2_COMPLETED_WITH_NOTES; Small Customer Pilot Preparation Gate SMALL_CUSTOMER_PILOT_PREP_READY_WITH_NOTES; Small Customer Pilot Execution SMALL_CUSTOMER_PILOT_BLOCKED; Article-to-Lab Pipeline Design Gate ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES; Article-to-Lab Implementation Prerequisites ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES; Article-to-Lab MVP Contract Schema Gate ARTICLE_TO_LAB_SCHEMA_READY_WITH_NOTES; Article-to-Lab Draft Mode Implementation K8S_ARTICLE_TO_LAB_DRAFT_MODE_READY_WITH_NOTES; Admin Review Rehearsal K8S_ARTICLE_TO_LAB_ADMIN_REHEARSAL_PASSED_WITH_NOTES; North Star Re-Alignment NORTH_STAR_REALIGNED_WITH_NOTES; **Internal Rehearsal to Publish Candidate PUBLISH_CANDIDATE_BLOCKED_BY_MISSING_REHEARSAL_BRIDGE**; **Linux Runtime Adapter Spike LINUX_RUNTIME_ADAPTER_SPIKE_READY_WITH_NOTES** (G-37); **Linux Verifier Adapter Spike LINUX_VERIFIER_ADAPTER_SPIKE_READY_WITH_NOTES** (G-38); **Linux Verifier Adapter Hardening LINUX_VERIFIER_ADAPTER_HARDENED_WITH_NOTES** (G-39); **Linux Guided Practice Draft Template LINUX_GUIDED_PRACTICE_DRAFT_TEMPLATE_READY_WITH_NOTES** (G-40); **Linux Internal Rehearsal Bridge LINUX_INTERNAL_REHEARSAL_BRIDGE_READY_WITH_NOTES** (G-41)  
> **Current state**: ALL 6 ops tickets VERIFIED; SMALL_CUSTOMER_PILOT_BLOCKED (no suitable customer — technical system ready); Guided Practice Quality Iteration GUIDED_PRACTICE_QUALITY_READY_FOR_TRUSTED_READER (G-33); **K8s Trusted Reader Pilot PASSED** (G-34): session a301676a LAB_CLOSED cleanup_verified=True step_1+step_2 PASS observer-confirmed no hiccups; **Linux Domain Proof Design Gate LINUX_DOMAIN_PROOF_DESIGN_READY_WITH_NOTES** (G-35): 5 BLOCKER couplings enumerated; **Linux Domain Contract Schema Extension LINUX_DOMAIN_CONTRACT_SCHEMA_READY_WITH_NOTES** (G-36): 60 tests; publish blocked; K8s regression clean; **Linux Runtime Adapter Spike LINUX_RUNTIME_ADAPTER_SPIKE_READY_WITH_NOTES** (G-37): 88 tests; 3885 total; **Linux Verifier Adapter Spike LINUX_VERIFIER_ADAPTER_SPIKE_READY_WITH_NOTES** (G-38): 5 primitives; 48 tests; TOCTOU documented; **Linux Verifier Adapter Hardening LINUX_VERIFIER_ADAPTER_HARDENED_WITH_NOTES** (G-39): TOCTOU MEDIUM closed (lstat+recheck_containment+O_NOFOLLOW); safety-reviewer no BLOCKER; 61 hardening tests; list_files_recursive aligned; see `docs/labgen/LINUX_VERIFIER_ADAPTER_HARDENING_RESULT_v0.1.md`; **Linux Guided Practice Draft Template LINUX_GUIDED_PRACTICE_DRAFT_TEMPLATE_READY_WITH_NOTES** (G-40): LinuxFilesPermissionsTemplate (4 steps, all 5 primitives, no LLM, no placeholders); ai_tutor_context field added; generate_linux() in stub_generator; FeasibilityClassifier /etc MEDIUM fixed; StaticValidator linux.verifiers_present check added; publish blocked; 68 tests; 4065 total tests; 93.27% coverage; K8s regression CLEAN; **Linux Internal Rehearsal Bridge LINUX_INTERNAL_REHEARSAL_BRIDGE_READY_WITH_NOTES** (G-41): LinuxRehearsalService (9-point precheck, _safe_exec_command shell-redirect intercept, dual-auth routes, session_type + student_username guard); 70 new tests; 4136 total; 92.44% coverage; publish blocked; catalog zero; K8s CLEAN; LLM=0; VMID 500-599 untouched; next: Linux Trusted Reader Pilot (Task 7 of 7)  
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
| **K8s Article-to-Lab Draft Mode Implementation: READY_WITH_NOTES** | `[x]` **K8S_ARTICLE_TO_LAB_DRAFT_MODE_READY_WITH_NOTES** (2026-06-17) | `docs/labgen/K8S_ARTICLE_TO_LAB_DRAFT_MODE_IMPLEMENTATION_RESULT_v0.1.md` — admin-only stub-based Article-to-Lab draft pipeline implemented; new modules: stub_feasibility_classifier (deterministic, no LLM, fail-closed: sensitive-hard-reject / cloud-blocked / DIRECTLY_LAB_READY / PARTIALLY_LAB_READY / NOT_LAB_READY), article_draft_repository (flock JSON, raw text never stored), article_draft_service (full status machine DRAFT→APPROVED_FOR_STATIC_VALIDATION→APPROVED_FOR_INTERNAL_REHEARSAL→APPROVED_FOR_PUBLISH_CANDIDATE, ArticleDraftValidator integration, convert_to_lab_draft never auto-publishes), article_draft_routes (9 admin-only endpoints); 60 new tests; 3570 total tests pass; 93.03% coverage; 0 LLM calls; no learner catalog entry; runtime/verifier/terminal unchanged; production VMID 500-599 UNTOUCHED; next: Admin Review Rehearsal |
| **K8s Article-to-Lab Admin Review Rehearsal: PASSED_WITH_NOTES** | `[x]` **K8S_ARTICLE_TO_LAB_ADMIN_REHEARSAL_PASSED_WITH_NOTES** (2026-06-17) | `docs/labgen/K8S_ARTICLE_TO_LAB_ADMIN_REVIEW_REHEARSAL_RESULT_v0.1.md` — 4 K8s input samples verified (directly_lab_ready / partially_lab_ready / not_lab_ready / sensitive content); admin-only enforcement verified (all 9 endpoints); stub classifier confirmed (evaluated_by=stub for all); raw text non-persistence verified; sensitive content hard-rejection without persistence; confirmed_* gate enforcement verified; StaticValidator bridge (15 checks) verified; full happy path to APPROVED_FOR_PUBLISH_CANDIDATE and LabDraft conversion verified; catalog isolation verified; MEDIUM-001 fixed: PatchArticleDraftRequest now exposes source_grounding/required_runtime/verifier_candidates (missing fields blocked full pipeline); PATCH extraction changed to model_fields_set+getattr; _ALLOWED_UPDATE_KEYS adds source_grounding; LOW-001 documented (not_lab_ready approve from DRAFT succeeds, blocked at next gate); NOTE-001 documented (user_confirmed_* default False); 53 new rehearsal tests; 3623 total tests pass; 93.59% coverage; 0 LLM calls; no runtime/VM/namespace side effects; production VMID 500-599 UNTOUCHED; next: K8s Internal Rehearsal to Publish Candidate |
| **North Star Re-Alignment (post-Claude-reset): REALIGNED_WITH_NOTES** | `[x]` **NORTH_STAR_REALIGNED_WITH_NOTES** (2026-06-20) | `docs/labgen/PROJECT_NORTH_STAR_v0.1.md` — authoritative realignment after Claude Code reset; confirmed: LabGen is Article-to-Lab / Technical Content-to-Experiment Platform ("读了能做，做了就懂"), NOT a fixed K8s platform; K8s is domain proof only; current phase is Admin-curated Article-to-Lab (no public article submission); v0.1 is Guided Practice Lab (not Assessment Lab); lab background = article content brief; AI Tutor context preserved with explicit constraints; Feasibility Gate preserved; LLM only drafts, never publishes; Linux / multi-domain portability preserved; Article-to-Lab Follow-up Execution Checklist added (18 invariants); milestone table updated (Draft Mode + Admin Review Rehearsal marked COMPLETE, Internal Rehearsal marked NEXT); 0 code changes; 0 LLM calls; runtime/verifier/terminal unchanged; production VMID 500-599 UNTOUCHED |
| G-29 | **K8s Article-to-Lab Internal Rehearsal to Publish Candidate: BLOCKED** | `[x]` **PUBLISH_CANDIDATE_BLOCKED_BY_MISSING_REHEARSAL_BRIDGE** (2026-06-20) | `docs/labgen/K8S_ARTICLE_TO_LAB_INTERNAL_REHEARSAL_TO_PUBLISH_CANDIDATE_RESULT_v0.1.md` — full pipeline Article→Contract→AdminReview→Validator→LabDraft(DRAFT) passed; BLOCKER-001: `LabSessionService.run_precheck()` line 259 requires `publish_status=PUBLISHED`; converted LabDraft always DRAFT; publishing would add to learner catalog (forbidden); 0 LLM calls; primary slogan updated to "读了能练，练完即熟"; lab_id `3d9e3331-d65e-43d9-83bf-8247feaca462` isolated in /tmp; not in prod; 0 code changes; runtime/verifier/terminal unchanged; production VMID 500-599 UNTOUCHED; recommended next step: Internal Rehearsal Bridge Implementation |
| G-30 | **Article-to-Lab Internal Rehearsal Bridge: READY_WITH_NOTES** | `[x]` **INTERNAL_REHEARSAL_BRIDGE_READY_WITH_NOTES** (2026-06-20) | `docs/labgen/ARTICLE_TO_LAB_INTERNAL_REHEARSAL_BRIDGE_RESULT_v0.1.md` — `POST /internal/rehearsal-sessions` (X-Admin-Token + require_admin_user); session_type=INTERNAL_REHEARSAL; draft stays DRAFT; learner catalog isolated; safety-reviewer 2 HIGH + 2 MEDIUM all fixed; 45 new tests (incl. 5 security regression); 3668 total tests; 93.27% coverage; 0 LLM calls; production VMID 500-599 UNTOUCHED; next: admin executes rehearsal against ConfigMap lab, then publish |
| G-31 | **Admin-curated Article-linked Lab Publish Gate: READY** | `[x]` **PUBLISH_GATE_READY** (2026-06-21) | `docs/labgen/ADMIN_CURATED_ARTICLE_LINKED_LAB_PUBLISH_GATE_RESULT_v0.1.md` — complete article→rehearsal→publish pipeline in staging; article_draft aa7c4a99 → LabDraft cf019133 (rehearsal_required=True) → rehearsal session 0b0fb49b (step_1 configmap_exists PASS, step_2 namespace_exists PASS) → rehearsal_completed=True → published → 5 labs in catalog; `StepProgressionService` INTERNAL_REHEARSAL bypass for DRAFT labs; kubeconfig stale IP fixed; 30 tests; 3632 total tests; 93%+ coverage; 0 LLM calls; production VMID 500-599 UNTOUCHED |
| G-32 | **Reader-facing Article CTA Dry Run: READY_WITH_NOTES** | `[x]` **READER_FACING_ARTICLE_CTA_DRY_RUN_READY_WITH_NOTES** (2026-06-21) | `docs/labgen/READER_FACING_ARTICLE_CTA_DRY_RUN_RESULT_v0.1.md` — complete reader path verified: catalog visible (5 labs), draft isolation (404 for draft labs), learner session (k8s_test, VM 401) started on article-linked lab cf019133, step_1 configmap_exists FAIL→PASS after kubectl command, step_2 namespace_exists PASS, Complete LAB_CLOSED cleanup_verified=True, residual=0; kubeconfig drift check CLEAN; LabGen LLM calls=0; +3 tests; 3571 total tests; 93.26% coverage; UNTOUCHED production VMID 500-599; NOTES: stub content TODO placeholders (MEDIUM → CLOSED in G-33), VM ownership manual staging (NOTE), step_2 manual_review_required=true (LOW → FIXED in G-33) |
| G-33 | **Guided Practice Quality Iteration Lab 5: READY_FOR_TRUSTED_READER** | `[x]` **GUIDED_PRACTICE_QUALITY_READY_FOR_TRUSTED_READER** (2026-06-21) | `docs/labgen/GUIDED_PRACTICE_QUALITY_ITERATION_LAB5_RESULT_v0.1.md` — all [TODO] placeholders removed from Lab 5 (title/description/step_1+2 why/observe/explain/verify.notes); step_2 manual_review_required corrected to false; content.no_placeholders StaticValidator check added (publish_blocking); reader path re-validated (session 03e6a04b, step_1 FAIL→PASS, step_2 PASS, LAB_CLOSED cleanup_verified=True, residual=0); catalog count=5, no TODO visible; source_article_id not exposed; +27 tests (placeholder gate + admin PATCH + reader regression); 3728 total tests; 93.28% coverage; LabGen LLM calls=0; production VMID 500-599 UNTOUCHED; next: Article-linked Lab Pilot With Trusted Reader |
| G-34 | **K8s Article-linked Lab Trusted Reader Pilot: PASSED** | `[x]` **K8S_TRUSTED_READER_PILOT_PASSED** (2026-06-21) | session a301676a, VM 402, LAB_CLOSED, cleanup_verified=True, step_1+step_2 PASS, observer-confirmed no hiccups; trusted reader completed lab without guidance; no backend errors in journalctl; K8s domain proof milestone COMPLETE |
| G-35 | **Linux Domain Proof Design Gate: READY_WITH_NOTES** | `[x]` **LINUX_DOMAIN_PROOF_DESIGN_READY_WITH_NOTES** (2026-06-21) | `docs/labgen/LINUX_DOMAIN_PROOF_DESIGN_GATE_v0.1.md` — 5 BLOCKER couplings identified; recommended runtime: container sandbox; recommended first lab: Linux Files and Permissions Basics; 7-step implementation plan; 0 code changes; K8s regression CLEAN |
| G-36 | **Linux Domain Contract Schema Extension: READY_WITH_NOTES** | `[x]` **LINUX_DOMAIN_CONTRACT_SCHEMA_READY_WITH_NOTES** (2026-06-21) | `docs/labgen/LINUX_DOMAIN_CONTRACT_SCHEMA_EXTENSION_RESULT_v0.1.md` — LabDomainType/LinuxVerifyType/LinuxVerifyTemplate/LinuxSandboxPolicy/CleanupLinuxWorkspace added; StaticValidator Linux path; H-01+H-02 fixed; 60 tests; publish blocked until runtime; 3797 total tests; 93.40% coverage; K8s regression CLEAN |
| G-37 | **Linux Runtime Adapter Spike: READY_WITH_NOTES** | `[x]` **LINUX_RUNTIME_ADAPTER_SPIKE_READY_WITH_NOTES** (2026-06-22) | `docs/labgen/LINUX_RUNTIME_ADAPTER_SPIKE_RESULT_v0.1.md` — LinuxWorkspaceManager/LinuxCommandExecutor/LinuxCleanupAdapter/LinuxRuntimeAdapter; NamespaceAdapterKind.LINUX; LinuxContainerLifecycleAdapter skeleton; M-01(sibling prefix)+L-01(deep forbidden path)+L-02(production guard)+L-03(backstop test) all fixed; 88 new tests; 3885 total tests; 93.38% coverage; K8s zero regression; learner not exposed; publish still blocked; enabled=False default; next: Linux Verifier Adapter Spike (Task 3 of 7) |
| G-38 | **Linux Verifier Adapter Spike: READY_WITH_NOTES** | `[x]` **LINUX_VERIFIER_ADAPTER_SPIKE_READY_WITH_NOTES** (2026-06-22) | `docs/labgen/LINUX_VERIFIER_ADAPTER_SPIKE_RESULT_v0.1.md` — LinuxVerifyClientAdapter (5 primitives: file_exists/directory_exists/file_content_matches/file_mode_matches/no_residual_files); LinuxVerifierService (workspace-scoped, content mismatch redact); StepProgressionService Linux dispatch; 11 new FailureReason codes; 48 new tests; 3933 total tests; 93.38% coverage; K8s zero regression; TOCTOU LOW documented; publish still blocked |
| G-39 | **Linux Verifier Adapter Hardening: READY_WITH_NOTES** | `[x]` **LINUX_VERIFIER_ADAPTER_HARDENED_WITH_NOTES** (2026-06-22) | `docs/labgen/LINUX_VERIFIER_ADAPTER_HARDENING_RESULT_v0.1.md` — TOCTOU MEDIUM closed: lstat()+_recheck_containment()+O_NOFOLLOW; Codex P1: lstat on original path not realpath; list_files_recursive/no_residual_files symlink-to-dir alignment; dead code cleared; 64 new hardening tests; 3997 total tests; 93.23% coverage; TOCTOU residual downgraded to LOW (no concurrent learner processes); K8s zero regression; publish still blocked |
| G-40 | **Linux Guided Practice Draft Template: READY_WITH_NOTES** | `[x]` **LINUX_GUIDED_PRACTICE_DRAFT_TEMPLATE_READY_WITH_NOTES** (2026-06-22) | `docs/labgen/LINUX_GUIDED_PRACTICE_DRAFT_TEMPLATE_RESULT_v0.1.md` — LinuxFilesPermissionsTemplate (4 steps, all 5 verifier primitives, LinuxSandboxPolicy, CleanupLinuxWorkspace, ai_tutor_context); LabDraft.ai_tutor_context field added; generate_linux() in LabDraftGeneratorStub; FeasibilityClassifier MEDIUM fixed (cp/mv/tee/sed -i/truncate/install /etc write vectors); StaticValidator linux.verifiers_present check added; publish blocked by linux.publish_blocked_until_runtime; TOCTOU LOW inherited from G-39, attack surface unchanged; 68 new tests; 4065 total tests; 93.27% coverage; K8s zero regression; LLM=0; production VMID 500-599 untouched; next: Linux Internal Rehearsal Bridge (Task 6 of 7) |
| G-41 | **Linux Internal Rehearsal Bridge: READY_WITH_NOTES** | `[x]` **LINUX_INTERNAL_REHEARSAL_BRIDGE_READY_WITH_NOTES** (2026-06-22) | `docs/labgen/LINUX_INTERNAL_REHEARSAL_BRIDGE_RESULT_v0.1.md` — LinuxRehearsalService (9-point precheck, _safe_exec_command shell-redirect intercept, execute_linux_step, complete/abort); linux_rehearsal_router (5 endpoints, dual-auth X-Admin-Token + admin cookie, session_type + student_username ownership guard); 18 new FailureReason codes; workspace_manager property on LinuxRuntimeAdapter; safety-reviewer HIGH fixed (cross-admin session mutation); Codex P2 fixed (session_type guard); 70 new tests (A-F categories); 4136 total tests; 92.44% coverage; Linux publish still blocked; Linux catalog zero; K8s zero regression; LLM=0; VMID 500-599 untouched; next: Linux Trusted Reader Pilot (Task 7 of 7) |

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

This gate remains aligned with PROJECT_NORTH_STAR_v0.1: Article-to-Lab / Technical Content-to-Experiment Platform, "读了能练，练完即熟". K8s domain proof for the broader Article-to-Lab platform.

## North Star Alignment Check

| Check | Status |
|-------|--------|
| Still serving Article-to-Lab | YES |
| Still supports "读了能练，练完即熟" | YES |
| Avoids K8s-only hardcoding | YES — staging config is domain-specific by necessity (K3s kubeconfig, RBAC), but adapter boundaries (Runtime/Verifier/Terminal/Cleanup Adapter) remain swappable per PROJECT_NORTH_STAR_v0.1 §6 |
| Preserves Linux/domain portability | YES — no change to adapter contracts |
| No skipped human review | YES |
| No skipped StaticValidator | YES |
| No skipped cleanup | YES |
| No premature public launch expansion | YES |
| No home_lab_mvp → production promotion | YES |
