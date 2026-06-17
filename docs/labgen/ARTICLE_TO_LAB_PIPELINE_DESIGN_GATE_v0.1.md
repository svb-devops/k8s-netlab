# Article-to-Lab Pipeline Design Gate v0.1

**Date**: 2026-06-16
**Operator**: Claude Code acting as senior dev + ops
**Decision**: ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES
**No real secrets in this document.**

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Gate decision | **ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES** |
| Preceded by | Small Customer Pilot Execution — SMALL_CUSTOMER_PILOT_BLOCKED (NO_SUITABLE_SMALL_CUSTOMER) |
| Relationship to Pilot Blocked | Pilot blocked by absent customer, not by technical readiness; engineering mainline continues independently |
| Relationship to North Star | Direct forward step — this gate designs the platform's actual final product capability |
| LLM calls in this gate | 0 |
| Code changes in this gate | 0 |
| Production VMID 500-599 | Untouched |
| Fifth lab published | No |
| Concurrency increased | No |
| Live article ingestion enabled | No |
| LLM live generation enabled | No |

**Why now**: K8s domain proof is complete. Three rounds of real human validation across all 4 published labs, terminal integration, verifier closed loop, cleanup, credential reclaim — all working. Pilot execution is blocked by a non-technical constraint (no external customer). The engineering mainline can advance independently by formalizing the Article-to-Lab pipeline design. This gate answers the question: what does the platform need to become?

**Why WITH_NOTES**: The design is comprehensive and feasible. Existing infrastructure covers a substantial portion of the pipeline. However, LLM provider selection is an open decision, Linux domain runtime choice is unresolved, and source article storage/copyright policy is undecided. These open questions must be resolved before v0.1 implementation begins.

**What this gate does not do**:
- Does not enable live article ingestion
- Does not enable LLM live generation
- Does not publish a fifth lab
- Does not increase concurrency
- Does not start a customer pilot
- Does not declare arbitrary Article-to-Lab as implemented

---

## B. North Star Alignment

LabGen's mission is not to build a fixed K8s course platform. K8s is a domain proof.

The final product is: **"Let every reproducible technical article become a temporary, isolated, verifiable, recyclable live experiment."**

Product slogan: **读完即练，结果说话。**

| Alignment Check | Status |
|-----------------|--------|
| K8s as domain proof, not final product boundary | YES — 4 labs prove the platform, not add coursework |
| Article-to-Lab as the actual product direction | YES — this gate designs the pipeline |
| "读完即练，结果说话" preserved | YES — the pipeline starts from an article, ends with a reclaimed environment |
| Linux / multi-domain future migration preserved | YES — all adapter abstractions remain domain-swappable |
| Not declaring LLM live generation enabled | YES — gate is design only |
| Not declaring arbitrary article-to-lab complete | YES — design only, no live pipeline |
| K8s domain proof quality not degraded | YES — 0 code changes to existing runtime |

The K8s domain proof validated these platform capabilities (all domain-agnostic):
- Per-session namespace isolation
- Credential non-leakage across sessions
- RBAC minimal-privilege enforcement
- kubectl terminal sandbox (command allowlist, output limits)
- Verifier primitives (4 types, all namespace-scoped, safe_message-compliant)
- Cleanup + credential reclaim closed loop
- Tainted VM tracking and precheck blocking
- Admin draft → publish → catalog flow (StaticValidator, AdminReviewDiff, PublishService)

These are the substrate. The Article-to-Lab pipeline adds the input layer (article → draft) on top.

---

## C. Problem Statement

An engineer reads a well-written technical article about Kubernetes Secrets, Docker networking, or Linux permissions. They understand the concept. They want to verify it right now. But:

1. **Local environment cost**: Setting up a K8s cluster, configuring RBAC, or provisioning a database takes 30–120 minutes before the first experiment command runs.
2. **Retained material without retention**: Without execution, knowledge stays abstract. Reading without doing does not build skill.
3. **No temporary isolated context**: Running experiments on a local machine or shared server risks interference, credential leakage, and environment pollution.
4. **Article-to-practice gap**: The best technical articles describe exactly what to do, but the reader still must manually translate description into an executable environment.

LabGen closes this gap:
- The article is the input.
- The platform produces a temporary, isolated, verifiable experiment environment.
- The learner runs commands, checks results, and the environment is reclaimed when done.
- "读完即练" — from reading to practicing, with no local setup.
- "结果说话" — the verifier, not the learner's memory, says whether the step succeeded.

The platform must not fabricate experiments for articles that cannot support one. Not every article is operable. The first gate must decide.

---

## D. Feasibility Gate

The Feasibility Gate is the mandatory first step of the Article-to-Lab pipeline.

The system must not default to assuming every article can become an experiment. The gate classifies every input into exactly one of three tiers before any draft generation begins.

### D.1 Directly Lab-Ready

The article may proceed to Draft Lab Contract generation.

**All of the following must be true**:

| Criterion | Description |
|-----------|-------------|
| Clear technical objective | The article has a stated or clearly inferable goal (e.g., "configure a ConfigMap") |
| Executable operations | Steps exist that can be run as commands |
| Concrete artifacts | Commands, configuration, code, or deployment steps that become experiment actions |
| Provisionable environment | The required environment (K8s cluster, Linux VM, Docker host) can be provisioned temporarily |
| Observable result | The experiment produces an observable outcome (resource exists, service responds, file is created) |
| Automatically verifiable state | The result can be checked by a machine without reading sensitive data |
| Safely isolatable | The experiment can run inside a temporary isolated environment without host escape risk |
| Cleanable | All resources created by the experiment can be destroyed when the session ends |
| No real credentials required | Does not require real production accounts, API keys, tokens, or private keys |
| No inaccessible third-party | Does not depend on external services with no safe substitute |
| No long-lived environment | Does not require persistent state that survives the session |
| No high-risk operations | Does not involve destructive, illegal, or unsafe commands outside the sandbox |

### D.2 Partially Lab-Ready

The article has practice value but is missing key information. The system must not publish directly and must not fabricate missing content.

The system returns a structured list of **missing requirements / clarifications** to the user. The user may supply the missing information and resubmit.

**Trigger examples**:

| Category | Examples |
|----------|---------|
| Version missing | Target K8s version, distribution, or cloud provider not specified |
| Environment unspecified | "On your cluster" — which type? what size? any pre-reqs? |
| Commands incomplete | Conceptual description without actual commands |
| Input examples absent | "Create a ConfigMap with your app's settings" — what keys/values? |
| Verifiable outcome missing | "You should see the pod running" — but no state check defined |
| Expected output absent | No expected output specified; verifier cannot confirm correctness |
| External dependency with no safe substitute | Requires a live cloud provider API with no local simulation |
| Scope choice required | Article covers multiple deployment options; user must select scope |
| Only limited draft generatable | Feasible in principle but article text is insufficient for full steps |
| Verifier target ambiguous | Cannot determine what to check without additional specification |
| Cleanup scope ambiguous | Cannot determine what to clean up from the article alone |

The clarification response must:
- List exactly which elements are missing or ambiguous
- Not fabricate or infer missing content
- Suggest what additional information the user can provide to retry
- Not generate a partial lab draft that omits verified steps

### D.3 Not Lab-Ready / Reject

If the article has no operability, the system must explicitly refuse to generate an experiment, with a clear reason.

**Mandatory reject scenarios**:

| Category | Examples |
|----------|---------|
| Pure theory | Explanation of CAP theorem, description of eventual consistency |
| News / opinion / trend | "Why Kubernetes is winning" — no executable steps |
| No executable steps | Article describes a concept but has no commands or configuration |
| No verifiable outcome | No result that a machine can check |
| Missing environment with no inference | "On a production cluster" — cannot provision a safe substitute |
| Requires real production environment | Article only works with real cloud credentials, real database, real user data |
| Requires real secrets | Requires actual API key, token, certificate, or user private key |
| Requires inaccessible third-party | Service with no local substitute and no sandbox mode |
| Destructive / illegal / high-risk | Commands that could damage infrastructure outside the sandbox |
| Too expensive for temporary environment | Full machine learning training run, multi-datacenter setup |
| Cannot clean up | Resources that persist beyond the session and cannot be automatically removed |
| Cannot establish safety boundary | Article execution would require host escape or cross-user access |
| Cannot automatically verify | Outcome is subjective or requires human judgment |
| Would mislead learner | Generating a lab would make the learner believe they've mastered the content when the lab is too simplified to represent it |

**Reject response structure** (must include all fields):

```json
{
  "feasibility_tier": "not_lab_ready",
  "reasons": ["<specific reason from the article>", "..."],
  "missing_operable_elements": ["executable steps", "verifiable outcome", "..."],
  "supplementable": false,
  "supplement_hint": null,
  "content_alternative": "summary_or_study_notes_only",
  "content_alternative_reason": "This article can produce a concept summary, but not an executable lab."
}
```

**Constraints on reject handling**:
- Must not fabricate an experiment to appear "smart"
- Must not generate a fake experiment that cannot be verified
- Must not bypass safety / cleanup / verifier requirements to force a lab
- Must not allow the LLM to override the reject decision
- If content_alternative = "summary_or_study_notes_only", the system may optionally generate study notes, but must clearly label them as "not an executable lab"

---

## E. Pipeline Architecture

### E.1 Canonical Flow

```text
Technical Article / Document / README / Tutorial
        ↓
Article Ingestion
 Input: user-pasted text (or URL, file — future)
 Output: ArticleSubmission{text_hash, source_type, word_count, extracted_date}
 Responsibility: accept input, hash for dedup, record metadata
 Not allowed: store raw user text permanently without retention policy decision
        ↓
Operability / Feasibility Gate
 Input: ArticleSubmission + article text
 Output: FeasibilityResult{tier, reasons, missing_requirements, safety_flags}
 Responsibility: classify tier (directly_lab_ready / partially_lab_ready / not_lab_ready)
 Not allowed: default to lab-ready; fabricate missing info; allow LLM to override reject
        ↓
Experiment Planner (LLM — with stub mode)
 Input: article text + FeasibilityResult
 Output: ExperimentPlan{objective, domain, steps, artifacts, verifier_candidates, environment_reqs}
 Responsibility: extract practicable knowledge points, draft steps, map to verifier candidates
 Not allowed: generate verifiers directly; publish without review; invent steps not in the article
        ↓
Draft Lab Contract Generation
 Input: ExperimentPlan
 Output: LabDraftContract (see Section F)
 Responsibility: populate all schema fields, record source_grounding, flag unsupported_inferences
 Not allowed: set publish_status = published; omit source_grounding; omit safety_flags
        ↓
Human/Admin Review
 Input: LabDraftContract + source article + AdminReviewDiff history
 Output: admin_decision = approve | request_changes | reject
 Responsibility: admin reviews source grounding, inferred steps, safety flags, verifier candidates, cleanup plan
 Not allowed: LLM publish directly; lab enter catalog without approval; verifier without review
        ↓
StaticValidator
 Input: approved LabDraftContract
 Output: {publish_blocked: bool, check_results: []}
 Responsibility: 13 existing checks + new checks for source_grounding and admin_decision
 Not allowed: bypass; auto-approve; skip checks for LLM-generated content
        ↓
Internal Rehearsal (operator-run)
 Input: published draft in staging environment
 Output: rehearsal result (all steps completable, verifier correct, cleanup verified)
 Responsibility: operator walks through the lab before any learner sees it
 Not allowed: learner sees lab before internal rehearsal passes
        ↓
Publish Gate
 Input: StaticValidator PASS + internal rehearsal PASS + admin_decision = approve
 Output: publish_status = published
 Responsibility: lab enters catalog
 Not allowed: auto-publish; skip rehearsal; publish on validator failure
        ↓
Runtime Adapter Selection
 Input: target_domain from LabDraftContract
 Output: selected RuntimeAdapter (K8s | Linux | Docker | ...)
 Responsibility: route to correct domain provisioner
 Not allowed: use K8s adapter for non-K8s lab; use unknown adapter
        ↓
Environment Provisioning
 Input: RuntimeAdapter + environment_requirements
 Output: running isolated environment (namespace, VM, container)
 Responsibility: create per-session isolated context
 Not allowed: reuse another learner's environment; skip ownership assignment
        ↓
Learner Workspace + Terminal
 Input: provisioned environment + session credentials
 Output: browser-based terminal session (kubectl, bash, etc.)
 Responsibility: provide sandboxed interactive terminal; enforce command allowlist
 Not allowed: expose platform kubeconfig; expose verifier credentials; allow unsafe commands
        ↓
Step Verification
 Input: VerifyTemplate per step + learner's current environment state
 Output: VerifyResult{passed, error_code, safe_message}
 Responsibility: check environment state against expected outcome; return safe message
 Not allowed: read sensitive data (secret values, private keys); expose raw K8s objects
        ↓
Feedback / Reflection
 Input: session completion + step history
 Output: learner feedback (structured questions)
 Responsibility: capture learning outcome, friction, concept clarity
 Not allowed: retain PII beyond audit retention policy; require mandatory feedback to complete
        ↓
Cleanup / Credential Reclaim
 Input: session_id + provisioned resources
 Output: cleanup_verified=True; all resources destroyed; credentials reclaimed
 Responsibility: ensure "结果说话" — environment is completely reclaimed
 Not allowed: leave residuals; leave credentials; leave tainted state without marking
```

### E.2 Existing Infrastructure Reuse

| Component | Existing Implementation | Reuse Status |
|-----------|------------------------|--------------|
| Draft Lab Contract storage | `backend/labgen/repository.py` | ✅ Direct reuse — LabDraftRepository |
| Admin draft routes (PATCH, validate, publish) | `backend/labgen/routes.py` | ✅ Direct reuse — needs source_grounding fields added |
| Admin review diff | `backend/labgen/review_diff.py` | ✅ Direct reuse |
| StaticValidator (13 checks) | `backend/labgen/static_validator.py` | ✅ Direct reuse — add source_grounding + admin_decision checks |
| PublishService | `backend/labgen/publish_service.py` | ✅ Direct reuse |
| K8s namespace lifecycle | `backend/labgen/namespace_lifecycle.py` | ✅ Direct reuse — K3sNamespaceLifecycleAdapter |
| Verifier primitives (4 types) | `backend/labgen/verifier.py` | ✅ Direct reuse — namespace_exists, configmap_exists, secret_exists, deployment_ready |
| Verifier credential store | `backend/labgen/verifier_credentials.py` | ✅ Direct reuse |
| K8s verifier client | `backend/labgen/k8s_verifier_client.py` | ✅ Direct reuse |
| Lab session service | `backend/labgen/lab_session_service.py` | ✅ Direct reuse |
| kubectl web terminal | `backend/labgen/lab_kubectl_ws.py` + `kubectl_executor.py` + `learner_credentials.py` | ✅ Direct reuse for K8s domain |
| Tainted VM tracking | `backend/vm_tracker.py` | ✅ Direct reuse |
| Step progression | `backend/labgen/step_progression_service.py` | ✅ Direct reuse |
| LLM stub mode | `backend/labgen/stub_generator.py` | ✅ Direct reuse for testing |

### E.3 Gaps (Not Yet Implemented)

| Component | Gap | Priority |
|-----------|-----|---------|
| FeasibilityGate classifier | Not implemented — needs LLM or rule-based classifier | HIGH (MVP blocker) |
| ArticleAnalyzer (LLM) | Not implemented — extracts objective, domain, steps from article | HIGH (MVP blocker) |
| LabDraftGenerator (LLM) | Exists as stub — needs LLM integration for real content | HIGH (MVP blocker) |
| source_grounding fields in LabDraft | Not in current LabDraftState schema | HIGH (MVP blocker) |
| unsupported_inferences fields | Not in current LabDraftState schema | HIGH (MVP blocker) |
| Admin UI for article ingestion | Not built — admin must submit article text somewhere | HIGH (MVP blocker) |
| Linux domain adapter | Designed only — not implemented | LOW (not in v0.1) |
| Docker domain adapter | Designed only — not implemented | LOW (not in v0.1) |
| Networking domain adapter | Designed only — not implemented | LOW (not in v0.1) |
| Database domain adapter | Designed only — not implemented | LOW (not in v0.1) |
| LLM provider integration | LABGEN_LLM_PROVIDER_MODE=fake_only currently | HIGH (MVP blocker) |
| Article storage / retention policy | Undecided — see Open Questions | MEDIUM |
| Internal rehearsal gate | Operationally defined but not enforced by code | MEDIUM |

---

## F. Draft Lab Contract

Every article-to-lab pipeline output is a Draft Lab Contract before it is ever reviewed, validated, or published.

### F.1 Proposed Schema

The Draft Lab Contract extends the current `LabDraftState` with article-origin fields:

```python
@dataclass
class ArticleSourceMetadata:
    title: str                          # extracted or user-provided
    author: Optional[str]               # optional
    source_type: str                    # "blog_post" | "official_doc" | "readme" | "internal_doc" | "tutorial" | "other"
    text_hash: str                      # SHA-256 of normalized input text (dedup, audit)
    word_count: int
    extracted_date: str                 # ISO 8601

@dataclass
class FeasibilityResult:
    tier: str                           # "directly_lab_ready" | "partially_lab_ready" | "not_lab_ready"
    reasons: list[str]                  # why this tier
    missing_requirements: list[str]     # only for partially_lab_ready
    safety_flags: list[str]             # detected safety concerns

@dataclass
class VerifierCandidate:
    step_id: str
    description: str                    # what to verify
    candidate_state: str                # see Verifier Strategy (Section I)
    suggested_primitive: Optional[str]  # e.g., "namespace_exists", "configmap_exists"
    suggested_params: dict              # e.g., {"name": "my-config"}
    review_note: str                    # why this mapping was chosen

@dataclass
class SourceGrounding:
    step_id: str
    article_excerpt: str                # verbatim quote from article supporting this step
    confidence: str                     # "direct_quote" | "inferred" | "not_supported"

@dataclass
class UnsupportedInference:
    field: str                          # e.g., "learner_steps[2].commands[0]"
    inferred_value: str                 # what the LLM inferred
    reason: str                         # why it was inferred (not from article text)
    admin_must_verify: bool             # always True — requires explicit admin sign-off

@dataclass
class DraftLabContract:
    # --- Article origin ---
    source_metadata: ArticleSourceMetadata
    feasibility_result: FeasibilityResult

    # --- Lab definition (maps to existing LabDraftState fields) ---
    learning_objective: str
    target_domain: str                  # "k8s" | "linux" | "docker" | "networking" | "database" | "cicd" | "cloud" | "unknown"
    required_runtime: str               # "k3s" | "linux_vm" | "docker_host" | "unknown"
    environment_requirements: list[str] # e.g., ["K3s node Ready", "nginx:1.25-alpine in registry"]
    learner_steps: list[LabStep]        # existing LabStep schema
    expected_artifacts: list[str]       # e.g., ["ConfigMap my-app-config exists in namespace"]
    verifier_candidates: list[VerifierCandidate]
    cleanup_requirements: list[str]     # what must be destroyed on session end
    safety_constraints: list[str]       # domain-specific constraints
    credential_policy: str              # "no_real_credentials" | "sandbox_only"
    terminal_requirements: str          # "kubectl" | "bash" | "docker" | "psql" | "none"
    estimated_duration: str             # e.g., "15min"
    review_notes: str                   # planner-generated notes for admin

    # --- Transparency ---
    source_grounding: list[SourceGrounding]
    unsupported_inferences: list[UnsupportedInference]

    # --- Admin decision ---
    admin_decision: Optional[str]       # "approved" | "request_changes" | "rejected" | None
    admin_decision_notes: str
```

### F.2 Source Grounding Requirement

Every step must have a corresponding `SourceGrounding` entry. If the confidence is "inferred" or "not_supported", this is automatically added to `unsupported_inferences`. Admin must explicitly sign off on all unsupported inferences before approval.

This prevents the LLM from silently hallucinating steps that are not in the article.

### F.3 Unsupported Inferences

Every field value that the LLM inferred without direct article support must be flagged. The admin review UI must surface these explicitly. The admin must mark each one as "verified" or "rejected" before the admin_decision can be set to "approved".

This is the primary defense against LLM hallucination entering the learner experience.

### F.4 Admin Decision

The admin_decision field is required before PublishService will proceed. The StaticValidator must check:
- `admin_decision == "approved"`
- All unsupported_inferences have been reviewed (admin_must_verify items are resolved)
- source_grounding is non-empty
- No safety_flags remain unacknowledged

---

## G. Review / Validation / Publish Flow

### G.1 Admin Review

After draft generation, the admin reviews via the existing `/api/labgen/drafts/{id}` PATCH endpoint. The admin review UI (existing `labgen-admin.html`) must be extended to show:

| Field | Admin can see | Admin can edit | Required before approval |
|-------|--------------|----------------|--------------------------|
| source article text | YES | NO | — |
| feasibility_result | YES | NO | — |
| source_grounding (per step) | YES | NO | YES — review all |
| unsupported_inferences | YES | YES (mark resolved) | YES — resolve all |
| safety_flags | YES | YES (acknowledge) | YES — acknowledge all |
| learner_steps | YES | YES | YES — review |
| verifier_candidates | YES | YES (select/override) | YES — confirm each |
| cleanup_requirements | YES | YES | YES — review |
| admin_decision | YES | YES (set) | YES — must be set |
| admin_decision_notes | YES | YES (write) | Required if request_changes or rejected |

### G.2 Review Actions

- **approve**: draft is ready for StaticValidator + internal rehearsal
- **request_changes**: draft returned to planner with admin notes (may trigger LLM revision)
- **reject**: draft is archived, not published, not shown to learners

The LLM must not override an admin "reject" decision.

### G.3 StaticValidator Extension

The existing StaticValidator (13 checks) must be extended with:

| New Check | Description | Block condition |
|-----------|-------------|-----------------|
| `source_grounding_present` | source_grounding non-empty | blocks if empty |
| `no_unreviewed_inferences` | all unsupported_inferences marked resolved | blocks if any unresolved |
| `admin_decision_approved` | admin_decision == "approved" | blocks if not approved |
| `safety_flags_acknowledged` | all safety_flags acknowledged | blocks if any unacknowledged |
| `verifier_candidates_resolved` | all verifier_candidates have a confirmed state | blocks if any in "needs_review" |

All 13 existing checks still apply. The 5 new checks apply only to article-origin drafts (identified by presence of `source_metadata`).

### G.4 Internal Rehearsal

Before any learner can access a newly generated lab:

1. Operator loads the published draft in the staging environment
2. Operator walks through all steps manually
3. Operator runs verifier check for each step — all must pass
4. Cleanup must succeed (`cleanup_verified=True`)
5. Operator records rehearsal result

This gate applies to every article-to-lab generated lab. Manually designed labs (the current 4 K8s labs) are exempt because they already went through equivalent validation during lab design gates.

### G.5 Publish Gate Summary

| Gate | Required | Enforced by |
|------|---------|-------------|
| Feasibility Gate PASS | YES | FeasibilityGate (code) |
| Admin Review: approved | YES | StaticValidator new check |
| All unsupported_inferences resolved | YES | StaticValidator new check |
| All safety_flags acknowledged | YES | StaticValidator new check |
| StaticValidator all checks PASS | YES | PublishService (existing) |
| Internal rehearsal PASS | YES | Operator process (not yet code-enforced) |
| LLM did not auto-publish | YES | Architecture — LLM only generates draft |

---

## H. Domain Adapter Strategy

The K8s domain proof must be abstracted into a replaceable interface. No code must hardcode K8s as the only domain.

### H.1 Interface Definitions

Each domain requires four adapters:

```python
class RuntimeAdapter(Protocol):
    async def provision(self, session_id: str, reqs: EnvironmentRequirements) -> ProvisionedEnvironment: ...
    async def teardown(self, session_id: str, env: ProvisionedEnvironment) -> bool: ...

class TerminalAdapter(Protocol):
    async def open_session(self, session_id: str, env: ProvisionedEnvironment) -> TerminalSession: ...
    async def send_command(self, session: TerminalSession, command: str) -> CommandResult: ...
    async def close_session(self, session: TerminalSession) -> None: ...
    def get_allowed_commands(self) -> CommandAllowlist: ...

class VerifierAdapter(Protocol):
    async def verify_step(self, session_id: str, template: VerifyTemplate, env: ProvisionedEnvironment) -> VerifyResult: ...

class CleanupAdapter(Protocol):
    async def cleanup(self, session_id: str, env: ProvisionedEnvironment) -> CleanupResult: ...
    async def is_clean(self, session_id: str) -> bool: ...
```

### H.2 K8s Domain (Implemented)

| Component | Implementation | Notes |
|-----------|---------------|-------|
| RuntimeAdapter | `K3sNamespaceLifecycleAdapter` | namespace create/delete |
| TerminalAdapter | `KubectlExecutor` + `lab_kubectl_ws.py` | command allowlist, 64KB limit, 30s timeout |
| VerifierAdapter | `K8sVerifierClientAdapter` | 4 primitives: namespace_exists, configmap_exists, secret_exists, deployment_ready |
| CleanupAdapter | `LabSessionService._do_cleanup()` | namespace delete + credential reclaim |
| SafetyPolicy | ClusterRole `lab-verifier-namespace-readonly` | list+watch only, no get, namespace-scoped |

**Reuse**: Full — all existing infrastructure.

### H.3 Linux Domain (Designed — Not Implemented in v0.1)

| Aspect | Design |
|--------|--------|
| Provisioning | Per-session VM or container (snapshot-based reset, or fresh clone from template) |
| Terminal | Bash shell via WebSocket (similar to kubectl terminal but executes bash commands) |
| Command sandbox | Allow-list of safe commands (ls, cat, mkdir, chmod, ps, systemctl status, etc.) — deny destructive commands outside sandbox |
| Verifier primitives needed | file_exists, process_running, service_active, user_exists, permission_matches, command_output_contains |
| Cleanup | VM reset to snapshot, or container removal |
| Safety | No host escape; no network egress by default; no sudo escalation outside sandbox; no package install of unsafe packages |
| Credential policy | No real user accounts; no SSH keys; sandbox user only |

**Status**: Interface boundary defined. Implementation deferred — not in v0.1.

### H.4 Docker Domain (Designed — Not Implemented in v0.1)

| Aspect | Design |
|--------|--------|
| Provisioning | Docker-in-Docker or isolated Docker socket per session |
| Terminal | Docker CLI via WebSocket; or compose commands |
| Verifier primitives needed | container_running, image_exists, network_connected, volume_mounted, compose_service_healthy |
| Cleanup | `docker rm -f`, `docker network rm`, `docker volume rm` — all scoped to session |
| Safety | No registry credential injection; no host volume mount; no `--privileged`; image whitelist enforced |

**Status**: Interface boundary defined. Implementation deferred — not in v0.1.

### H.5 Networking Domain (Designed — Not Implemented in v0.1)

| Aspect | Design |
|--------|--------|
| Provisioning | Isolated network namespace (Linux netns) or dedicated VM |
| Terminal | ip, iptables, curl, ping, netcat, dig — allow-listed only |
| Verifier primitives needed | route_exists, port_open, dns_resolves, iptables_rule_active, connectivity_check |
| Cleanup | netns deletion or VM reset |
| Safety | **Strictest**: no arbitrary egress; no ARP manipulation outside netns; no raw socket access by default |

**Status**: Interface boundary defined. Implementation deferred — not in v0.1.

### H.6 Database Domain (Designed — Not Implemented in v0.1)

| Aspect | Design |
|--------|--------|
| Provisioning | Temporary DB instance (SQLite in-process, or PostgreSQL in Docker) |
| Terminal | psql, mysql CLI — allow-listed queries |
| Verifier primitives needed | table_exists, row_count_matches, column_exists, query_returns_result |
| Cleanup | DROP DATABASE or container removal |
| Safety | No connection to real production DB; no user real credentials; instance-per-session |

**Status**: Interface boundary defined. Implementation deferred — not in v0.1.

### H.7 CI/CD Domain (Designed — Not Implemented in v0.1)

Requires pipeline execution environment (e.g., Gitea + runner). Complex provisioning. Deferred beyond v0.1.

### H.8 Cloud Domain (Explicitly Out of Scope)

Cloud experiments require real credentials, real billing, real production accounts. The platform's safety policy prohibits real credentials. Cloud simulation (LocalStack) is feasible for limited AWS services, but is complex and not in v0.1 scope. Design decision: no Cloud adapter in v0.1. Revisit when Linux + Docker domains are proven.

### H.9 Domain Priority for v0.1 and Beyond

| Domain | v0.1 | v0.2 | v0.3+ |
|--------|------|------|-------|
| K8s | ✅ Complete | — | — |
| Linux | Design only | Target | Stable |
| Docker | Design only | Target | Stable |
| Networking | Design only | — | Target |
| Database | Design only | — | Target |
| CI/CD | Design only | — | Evaluate |
| Cloud | Out of scope | Out of scope | Evaluate |

---

## I. Verifier Strategy

The LLM must not directly generate unreviewed verifier code. Verifiers handle real resource state and must be correct, safe, namespace-scoped, and testable.

### I.1 Strategy

1. **Prefer existing primitives**: map article expected result to an existing verifier primitive first.
2. **Parameterize existing primitives**: if an existing primitive needs a name/count/label param, use it with new params — no new code.
3. **Draft new primitive only if no existing primitive applies**: the draft requires admin review + tests before use.
4. **If not verifiable or unsafe, flag and reject**: do not fabricate a verifier.

### I.2 Existing Verifier Primitives (Reusable)

| Primitive | What it checks | Domain |
|-----------|---------------|--------|
| `namespace_exists` | namespace is active on the cluster | K8s |
| `configmap_exists` | ConfigMap with given name exists in learner namespace | K8s |
| `secret_exists` | Secret with given name exists (uses list, never reads .data) | K8s |
| `deployment_ready` | Deployment with given name has all replicas ready | K8s |

All existing primitives are:
- Namespace-scoped (no cluster-admin required)
- List-only (no read of sensitive data)
- safe_message-compliant (no raw K8s objects in output)
- Testable with mock K8s API client

### I.3 Verifier Candidate States

| State | Meaning | Action required |
|-------|---------|-----------------|
| `reusable_existing` | Exact match to existing primitive | No new code — use directly |
| `needs_parameterization` | Existing primitive with new name/value params | Parameter review by admin |
| `needs_new_primitive` | No existing primitive covers the check | Draft + admin review + test coverage required |
| `not_verifiable` | Cannot check automatically (e.g., "understand the concept") | Step must be marked as unverified / informational |
| `unsafe_to_verify` | Checking would require unsafe access (reading secret values, root access, egress check) | Must be redesigned to avoid unsafe check, or step dropped |

### I.4 New Primitive Requirements

Any new verifier primitive (state = `needs_new_primitive`) must satisfy:

| Requirement | Description |
|-------------|-------------|
| Namespace-scoped | Must operate within the learner's session namespace only |
| Read-only | Must not modify cluster state |
| No secret data access | Must use list/watch, not get for secrets and tokens |
| safe_message compliant | Output must not contain raw K8s objects, tokens, certificates, or credentials |
| Testable | Must have unit tests with mock K8s API client |
| Admin reviewed | Primitive code must pass admin review before being used in any published lab |
| No brittle text matching | Must check structured state (resource existence, count, label) not raw output substrings — unless no structured check exists |

### I.5 Verifier Safety Policy

- Verifier must never return secret values, base64 data, or tokens in `safe_message`
- Verifier must never access resources outside the learner's session namespace
- Verifier must never use `get` on Secrets (always `list` with field_selector for name)
- Verifier must never assume cluster-admin (ClusterRole is namespace-scoped list+watch only)
- Verifier failure message must be actionable but not leak internal cluster state

---

## J. Runtime / Terminal Strategy

### J.1 Workspace Model

Each lab session gets an isolated workspace:

| Domain | Workspace | Isolation |
|--------|-----------|----------|
| K8s | Kubernetes namespace `lab-{session_id}` | Namespace RBAC; no cross-namespace access |
| Linux | VM (snapshot reset) or Docker container | VM/container boundary |
| Docker | Docker-in-Docker or isolated socket | Container boundary |
| Networking | Linux netns | Network namespace |
| Database | Per-session DB instance | Process isolation |

The workspace is created at session start and destroyed at session end. No workspace survives across sessions. This is the "结果说话" contract.

### J.2 Terminal Model

The existing WebSocket-based kubectl terminal (`/ws/lab-kubectl/{session_id}`) serves as the reference implementation for the Terminal Adapter.

Key design constraints that apply to all domain terminals:

| Constraint | K8s (existing) | Linux (future) | Docker (future) |
|------------|----------------|----------------|-----------------|
| Auth | 5-layer: cookie → token → session → ownership → LAB_ACTIVE | Same auth chain | Same auth chain |
| Command allowlist | kubectl subcommands only | bash: safe commands only | docker subcommands only |
| Output limit | 64KB per response | 64KB per response | 64KB per response |
| Timeout | 30s per command | 30s per command | 30s per command |
| No shell=True | Yes | Yes | Yes |
| Credential isolation | learner kubeconfig (server-side only) | sandbox user only | no registry creds |

### J.3 Session Binding

The terminal session is bound to:
- `session_id` (owner check enforced)
- `lab_session_status = LAB_ACTIVE` (non-active sessions rejected)
- `namespace` (K8s) / `vm_id` or `container_id` (other domains)

The binding is non-transferable. A learner's terminal cannot access another learner's workspace.

### J.4 Domain Differences

| Aspect | K8s | Linux (planned) | Docker (planned) |
|--------|-----|-----------------|------------------|
| Primary command | kubectl | bash + system tools | docker / docker compose |
| Namespace badge | K8s namespace name | hostname or container name | compose project name |
| Command expansion | commands array per step + {{lab_namespace}} substitution | commands array + {{sandbox_user}} substitution | commands array |
| Cleanup signal | namespace deleted | VM reset or container removed | containers/volumes removed |

---

## K. Cleanup / Credential Strategy

"结果说话" requires that every session ends with complete reclamation. No residuals. No credentials lingering.

### K.1 Cleanup Requirements for All Labs

Every article-to-lab output must specify its `cleanup_requirements` in the Draft Lab Contract. The field is required — no lab may be published without it.

| Requirement | Description |
|-------------|-------------|
| Environment lifecycle | What must be destroyed when session ends |
| Credential lifecycle | What credentials exist during the session, and how they are reclaimed |
| Workspace lifecycle | What files/state are created, and where they live |
| Terminal process | WebSocket closed, subprocess terminated |
| Artifact lifecycle | All resources created during the lab are destroyed |
| Audit log retention | Logs are kept for audit; no PII in logs; no credentials in logs |

### K.2 Failure Cleanup

If cleanup fails:
- Session transitions to `LAB_CLEANUP_FAILED`
- VM is tainted (`tainted_vms.json`)
- Tainted VM blocks new sessions (existing `precheck.vm_tainted`)
- Operator must manually verify cleanup before untainting

This is the existing behavior — preserved for all domains.

### K.3 Credential Lifecycle

| Credential type | Created when | Where stored | Reclaimed when |
|-----------------|-------------|-------------|----------------|
| K8s learner SA token | Session starts | Server-side only (`/var/lib/labgen-staging/learner-kubeconfigs/`) | Session ends (cleanup) |
| K8s verifier kubeconfig | Per-session init | Server-side only (`creds/vm_creds/{vm_id}/`) | Session ends or VM exempt (staging) |
| Linux sandbox user key | Session starts | In-VM only | VM reset |
| Database session user | Session starts | DB instance | DB instance destroyed |

**Platform kubeconfig**: Never returned to learner. Never in logs. Never in API responses.
**Verifier credentials**: Never returned to learner. Never in logs. Operator-accessible only.
**Learner credentials**: Server-side only. Never sent in API response body. Mounted in terminal session only.

### K.4 User-Facing Cleanup Message

When a session ends (complete or abort), the learner sees:

> "Your isolated lab environment has been automatically reclaimed. All resources you created during this session have been removed."

This message is always shown. It is the user-facing guarantee of "结果说话".

### K.5 Tainted Resource Handling

If cleanup fails for any reason:
1. VM/container is marked tainted
2. Precheck blocks any new session on that resource
3. Operator resolves the tainted state manually
4. Operator removes the taint entry after verifying clean state
5. Only then can new sessions be provisioned on that resource

This policy applies to all domains, not only K8s.

---

## L. Safety Strategy

### L.1 Article Safety Flags

During Feasibility Gate evaluation, the following patterns in the article text must trigger safety flags:

| Pattern | Flag |
|---------|------|
| References to real production credentials | `real_credential_required` |
| References to real cloud accounts | `production_account_required` |
| References to private user data | `user_private_data_required` |
| Commands involving `rm -rf /` or equivalent | `destructive_host_command` |
| Commands involving `curl <url> \| bash` from untrusted sources | `unsafe_remote_execution` |
| References to crypto mining, botnet, or malware | `malware_or_abuse_pattern` |
| References to modifying firewall rules on real infrastructure | `production_network_modification` |
| High cost operations (GPU training, multi-region) | `cost_prohibitive` |
| References to regulatory or sensitive data | `regulatory_data_risk` |

Any unacknowledged safety flag blocks publication.

### L.2 Runtime Safety Policy

| Policy | Applies to all domains |
|--------|----------------------|
| No real secrets | Learner must not enter real credentials into the terminal |
| No production accounts | No real cloud/production account usage |
| No user private keys | No SSH private keys, TLS private keys |
| No registry credentials | No Docker Hub / registry login |
| No cross-namespace / cross-user access | Session is strictly isolated |
| No host filesystem escape | No bind mounts to host, no privileged containers |
| No cluster-admin | No ClusterRoleBinding; all access namespace-scoped |
| No unsafe network egress by default | Outbound network blocked unless explicitly required and safe-listed |
| No destructive command outside sandbox | rm -rf, dd, mkfs — blocked outside sandbox scope |
| No persistent malware | Any command or artifact that persists across sessions is detected and blocked |
| No sensitive output in feedback | Feedback messages must not contain credentials, tokens, raw K8s objects |
| No raw stack traces in API responses | Internal errors are logged, not exposed |
| No credential in logs | Platform logs must not contain kubeconfig content, tokens, passwords |

### L.3 Domain-Specific Safety Extensions

| Domain | Additional Safety |
|--------|-----------------|
| K8s | ClusterRole list+watch only; no get on Secrets; no ClusterRoleBinding; no privileged Pods |
| Linux | No privilege escalation; no kernel module; no raw socket; sandboxed user only |
| Docker | No `--privileged`; no host volume; no arbitrary image (whitelist only); no network = host |
| Networking | No traffic to production networks; netns isolated; no ARP manipulation outside scope |
| Database | No connection to real DB; no user credentials; instance-per-session |

### L.4 Output Safety

| Output source | Safety constraint |
|---------------|-----------------|
| Verifier safe_message | No raw K8s objects; no credential data; no base64; no namespace/token leakage |
| API responses | No kubeconfig; no verifier credential; no private key; no secret value |
| Terminal output | 64KB limit; no automatic credential echoing; command output only |
| Feedback responses | No session-internal data; no learner namespace; no sensitive paths |
| Logs | No credential values; no kubeconfig content; no token strings; structured JSON only |

---

## M. MVP Scope

### M.1 Recommended v0.1 Implementation

**K8s Article-to-Lab Draft Mode** — not live publish, not live learner access to generated labs

| Scope Item | In v0.1 | Notes |
|------------|---------|-------|
| Article ingestion via admin paste | YES | Admin pastes article text into admin UI |
| Feasibility Gate (K8s-aware) | YES | Classifier for K8s operability |
| ArticleAnalyzer LLM component | YES (with stub mode) | Extracts objective, domain, steps from article |
| LabDraftGenerator with source grounding | YES (with stub mode) | Generates Draft Lab Contract with source grounding |
| Draft Lab Contract schema extensions | YES | Add source_metadata, feasibility_result, source_grounding, unsupported_inferences, admin_decision |
| Admin review UI extensions | YES | Show source grounding, unsupported inferences, safety flags |
| StaticValidator extensions (5 new checks) | YES | source_grounding_present, no_unreviewed_inferences, admin_decision_approved, safety_flags_acknowledged, verifier_candidates_resolved |
| Internal rehearsal gate (operational) | YES | Operator process, not yet code-enforced |
| Only target_domain = k8s | YES | Only K8s articles in v0.1 |
| Only existing verifier primitives | YES | namespace_exists, configmap_exists, secret_exists, deployment_ready |
| No auto-publish | YES (enforced) | LLM cannot publish; admin approval required |
| No user-direct access to generated labs | YES (enforced) | Must pass internal rehearsal before catalog |

### M.2 Out of Scope for v0.1

| Item | Why out of scope |
|------|-----------------|
| Linux domain adapter | Too many unknowns (runtime choice, command sandbox design) |
| Docker domain adapter | Depends on Linux runtime design decisions |
| Networking / Database adapters | Even further behind |
| Live user-facing article ingestion | Admin-only in v0.1; no public "paste article" feature |
| LLM auto-approve / auto-publish | Explicitly prohibited by architecture |
| Fifth K8s lab (hand-designed) | Not needed for pipeline validation |
| New verifier primitives from LLM | Review + test requirement — deferred |
| Customer pilot with generated labs | After internal rehearsal; after small customer pilot unblocking |

### M.3 Go / No-Go Requirements for v0.1 Start

| Requirement | Status |
|-------------|--------|
| LLM provider selected and accessible | ✅ RESOLVED (2026-06-16) — v0.1 stub mode; `LLMProviderPort` interface designed; see `ARTICLE_TO_LAB_IMPLEMENTATION_PREREQUISITES_v0.1.md` |
| Source article storage / retention policy decided | ✅ RESOLVED (2026-06-16) — ephemeral source text; persistent fields enumerated; see Prerequisites doc Section D+E |
| StaticValidator extension design approved | READY — this document |
| Draft Lab Contract schema extension designed | READY — this document |
| Admin review UI extension scope defined | READY — this document |
| K8s domain proof validated | COMPLETE — 4 published labs, 3 rounds real human validation |

---

## N. Open Questions

| ID | Question | Impact | Decision needed by |
|----|---------|--------|-------------------|
| N-01 | **LLM provider choice**: commercial API (OpenAI, Anthropic) or self-hosted (ollama, local model)? | HIGH — blocks implementation start | ✅ **RESOLVED (2026-06-16)** — v0.1 uses stub mode; `LLMProviderPort` abstract interface designed; self-hosted ruled out on T430; commercial API deferred to after stub validation. See `ARTICLE_TO_LAB_IMPLEMENTATION_PREREQUISITES_v0.1.md` Section C. |
| N-02 | **Source article storage**: store full text? Hash only? Duration? Who can access? | HIGH — affects privacy, copyright, storage | ✅ **RESOLVED (2026-06-16)** — ephemeral source text; persistent: content_hash + source_metadata + feasibility_result + source_grounding_snippets + draft contract; no long-term raw text; user/admin deletable. See Section D. |
| N-03 | **Copyright / retention policy**: attribution required? Fair use for education? Deletion on user request? | HIGH — legal risk | ✅ **RESOLVED (2026-06-16)** — user consent required per submission; no long-term raw text; 30-day rejection metadata retention; audit indefinite (hash+decision only); admin-only v0.1 = low copyright exposure. See Section E. |
| N-04 | **User-provided secret handling**: what if an article requires accessing a live service (e.g., "curl api.example.com/your-token")? Reject? Sandbox substitute? | MEDIUM — affects feasibility gate logic | Before v0.1 implementation |
| N-05 | **Linux runtime choice**: VM-based (snapshot reset) or container-based (Docker-in-Docker)? | MEDIUM — affects Linux domain adapter design | Before Linux domain work begins |
| N-06 | **Domain prioritization**: K8s → Linux → Docker → or different order? | MEDIUM — sequencing only | Before v0.2 planning |
| N-07 | **Customer article collection**: how to source technical articles for testing the pipeline? Public blogs? Internal docs? User-provided only? | MEDIUM — affects testing strategy | Before first real article ingestion |
| N-08 | **Internal rehearsal enforcement**: should the "internal rehearsal passed" state be code-enforced (blocking publish until rehearsal logged), or remain an operational process? | LOW — implementation detail | Before Publish Gate code design |
| N-09 | **Feasibility Gate automation level**: fully automated (LLM classifier), rule-based, or hybrid? | MEDIUM — affects gate reliability | Before FeasibilityGate implementation |

---

## O. Final Decision

**ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES**

### Rationale

**READY** because:
- K8s domain proof is complete. The platform's core substrate — namespace isolation, verifier closed loop, kubectl terminal, credential non-leakage, cleanup, admin review, StaticValidator, PublishService — is proven end-to-end through three rounds of real human validation.
- The existing architecture already exhibits the correct domain-agnostic abstractions: `NamespaceLifecyclePort`, `VMTrackerPort`, `VerifierCredentialStore` are swappable. No K8s-only hardcoding blocks the design.
- The pipeline architecture is fully specified (Section E). Responsibilities are unambiguous. Reuse is clearly mapped. Gaps are precisely identified.
- The Feasibility Gate is defined with three tiers, reject response structure, and explicit "must not" list (Section D). No ambiguity about what the gate must do.
- The Draft Lab Contract schema is designed with source grounding and unsupported inference tracking — the primary defenses against LLM hallucination (Section F).
- The Admin Review + StaticValidator + Internal Rehearsal + Publish Gate flow is designed (Section G). The human check is not optional.
- Verifier strategy prevents LLM from generating unsafe verifiers (Section I).
- Cleanup / credential strategy is explicitly required for every lab (Section K).
- Safety strategy covers article-level flags, runtime policy, output safety, and domain-specific rules (Section L).
- MVP scope is realistic and grounded in existing infrastructure (Section M).

**WITH_NOTES** because:
- N-01 (LLM provider choice) and N-02/N-03 (source article storage/copyright) are unresolved and block v0.1 implementation start.
- Linux/Docker/Networking domain adapters are designed but not implemented — the platform cannot yet accept non-K8s articles.
- Internal rehearsal is defined operationally but not code-enforced — this is an accepted MVP risk (mitigated by operator discipline).
- FeasibilityGate automation level (N-09) affects reliability — rule-based is safer, LLM-based is more capable; choice is open.

**NOT BLOCKED** because:
- All open questions are scoped to implementation decisions, not fundamental design flaws.
- The platform substrate is proven and ready.
- The design is internally consistent and does not contain architectural contradictions.
- Nothing in this design requires violating any constraint (no LLM live publish, no real secrets, no production VMID, no 5th lab, no concurrency increase).

---

## P. Recommended Next Step

**K8s Article-to-Lab Draft Mode Implementation** — gate: `ARTICLE_TO_LAB_DRAFT_MODE_GATE_v0.1`

Scope:
1. Resolve N-01 (LLM provider) and N-02/N-03 (article storage/copyright) — prerequisites
2. Implement `FeasibilityGate` (K8s-aware classifier) with stub mode
3. Implement `ArticleAnalyzer` (LLM, with stub mode) — K8s article → ExperimentPlan
4. Implement `LabDraftGenerator` with source grounding (LLM, with stub mode) — real content mode
5. Extend `LabDraftState` schema with `source_metadata`, `feasibility_result`, `source_grounding`, `unsupported_inferences`, `admin_decision`
6. Extend admin UI for article ingestion + feasibility result display + source grounding review
7. Extend `StaticValidator` with 5 new checks (Section G.3)
8. Implement internal rehearsal logging (optional code enforcement)
9. Test end-to-end with one real K8s-operable article in staging
10. Admin reviews and approves the generated draft
11. Internal rehearsal passes in staging (VM 401, K3s)
12. Lab published to catalog

**Not next**:
- Linux Domain Proof Planning (lower priority than first real article-to-lab flow)
- Small Customer Recruitment Retry (can proceed in parallel, does not block engineering)
- Hold Expansion (not warranted — design is ready)

---

## Technical Self-Check

| Check | Status |
|-------|--------|
| No TODO/FIXME | PASS |
| No placeholder-as-success | PASS |
| No claim that arbitrary Article-to-Lab is implemented | PASS — design only |
| No claim that LLM live generation is enabled | PASS — explicitly excluded |
| No claim that production is ready | PASS |
| No claim that public launch is ready | PASS |
| No K8s hardcoded as permanent product boundary | PASS — domain adapters designed for all domains |
| No Linux / multi-domain portability broken | PASS — adapter interfaces designed |
| No Feasibility Gate bypassed | PASS — gate is mandatory first step |
| No default "all articles can become labs" assumption | PASS — reject tier is explicit |
| No non-operable article allowed to generate lab | PASS — reject tier covers all cases |
| No LLM allowed to publish directly | PASS — admin approval + StaticValidator + rehearsal required |
| No LLM allowed to override admin reject decision | PASS — admin_decision is authoritative |
| No lab without source grounding | PASS — StaticValidator check |
| No unreviewed unsupported inference | PASS — StaticValidator check |
| No lab without cleanup requirements | PASS — required field in schema |
| No lab without verifier candidates resolved | PASS — StaticValidator check |
| No lab without admin approval | PASS — StaticValidator check |
| No lab without internal rehearsal (by policy) | PASS — operational gate |
| No StaticValidator bypassed | PASS — PublishService re-runs it |
| No Admin Review bypassed | PASS — admin_decision check |
| No cleanup omitted | PASS — cleanup_requirements required field |
| No credential reclaim omitted | PASS — credential lifecycle defined |
| No platform kubeconfig leaked | PASS — architecture prohibits it |
| No verifier credential leaked | PASS — architecture prohibits it |
| No learner credential leaked | PASS — architecture prohibits it |
| No token/password/key in this document | PASS |
| No Secret value in this document | PASS |
| No customer data in this document | PASS |
| No production VM / pool / registry modified | PASS — 0 code changes |
| No LLM calls in this gate | PASS |
| No 5th lab published | PASS |
| No concurrency increased | PASS |
| "读完即练，结果说话" preserved | PASS — pipeline starts from article, ends with reclaimed environment |

---

## Modified Files

| File | Operation |
|------|-----------|
| `docs/labgen/ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` | Created (this file) |
| `docs/labgen/PROJECT_NORTH_STAR_v0.1.md` | Updated — added Section 12 (Design Gate reference) |
| `deploy/labgen/staging_ops_ticket_status.md` | Updated — added Article-to-Lab Pipeline Design Gate entry |
| `deploy/labgen/staging_infrastructure_checklist.md` | Updated — added Article-to-Lab Pipeline Design Gate entry |
| `CHANGELOG.md` | Updated |

---

*Executed by Claude Code (senior dev + ops) — 2026-06-16*
*Role: design gate, docs-only execution*
*0 LLM calls. 0 code changes. 0 lab published. 0 concurrency increase. Production VMID 500-599 untouched.*
