# Article-to-Lab Implementation Prerequisites v0.1

**Date**: 2026-06-16
**Operator**: Claude Code acting as senior dev + ops
**Decision**: ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES
**No real secrets in this document.**

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Gate decision | **ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES** |
| Preceded by | Article-to-Lab Pipeline Design Gate — ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES (commit 72f2674) |
| N-01 LLM Provider | **RESOLVED** — v0.1 uses stub mode; LLMProviderPort designed as swappable abstract interface |
| N-02 Article Storage | **RESOLVED** — ephemeral source text; persistent: hash + metadata + feasibility + snippets + contract |
| N-03 Copyright / Retention | **RESOLVED** — user consent required; no long-term raw text; retention defaults defined |
| Implementation may start? | **YES** — all three go/no-go blockers resolved; proceed to Article-to-Lab MVP Contract Schema Gate |
| LLM live enabled? | **NO** — stub mode only in v0.1 |
| LLM may publish? | **NO** — admin approval required at all times |
| Fifth lab published? | **NO** |
| Concurrency increased? | **NO** |
| Customer pilot started? | **NO** |
| Production VMID 500-599 | Untouched |
| LLM calls in this gate | 0 |
| Code changes in this gate | 0 |

**What this gate does**: Resolves the three prerequisite blockers (N-01, N-02, N-03) identified in the Article-to-Lab Pipeline Design Gate so that K8s Article-to-Lab Draft Mode Implementation may begin.

**What this gate does not do**:
- Does not start implementation
- Does not enable LLM live generation
- Does not enable live article ingestion
- Does not remove admin review requirement
- Does not remove StaticValidator requirement
- Does not remove internal rehearsal requirement
- Does not publish a fifth lab
- Does not allow LLM to publish directly
- Does not allow arbitrary article-to-lab to be called implemented

---

## B. North Star Alignment

| Alignment Check | Status |
|-----------------|--------|
| "读完即练，结果说话" preserved | YES — decisions only unlock the pipeline input layer; all quality gates remain |
| LLM draft only, human approval required | YES — stub mode and real LLM both go through Admin Review |
| Not declaring LLM live enabled | YES — stub mode is the v0.1 default |
| Not declaring arbitrary article-to-lab complete | YES — only K8s-operable articles in v0.1 |
| No production VMID touched | YES — 0 code changes |
| K8s domain proof quality not degraded | YES — 0 code changes to runtime |
| Future Linux / multi-domain portability preserved | YES — LLMProviderPort is domain-agnostic; storage policy is domain-agnostic |
| No raw article text permanently retained | YES — ephemeral processing policy |
| Sensitive content immediate discard | YES — feasibility gate rejects before any persistence |

---

## C. N-01 LLM Provider Decision

### C.1 Options Evaluated

| Option | Pros | Cons | v0.1 viable? |
|--------|------|------|-------------|
| OpenAI API / hosted commercial LLM | High quality; effective structured output; good at complex article understanding | External data transmission; user article privacy; provider availability dependency; cost | YES — as real provider when stub is replaced |
| Anthropic API (Claude) | Same as above; strong at following structured schemas | Same external data risks | YES — same |
| Local / self-hosted model (ollama, llama) | Data stays local; no external dependency | T430/home_lab_mvp cannot run a capable enough model (resource limitation is documented); output quality unstable for structured contract generation | NO for v0.1 on current hardware |
| Stub / mock / template-assisted | Fully deterministic; controllable; validates Contract schema and Admin Review flow without LLM | Cannot validate real article understanding; not a final product capability | **YES — v0.1 default** |

### C.2 v0.1 Decision

**v0.1 uses stub mode. No live LLM calls.**

Rationale:
- The goal of v0.1 is to validate the Contract schema, Admin Review flow, StaticValidator extensions, and Internal Rehearsal gate — not to demonstrate AI article comprehension.
- Stub mode produces a structurally correct Draft Lab Contract with clearly marked placeholder fields, which is sufficient to run through the complete pipeline.
- This is consistent with how all other LabGen components were built (stub-first, then real adapter): `StubVMTracker`, `StubNamespaceLifecycleAdapter`, `StubLLMProvider` follows the same pattern.
- The T430/home_lab_mvp cannot run a sufficiently capable local model, so self-hosted is not viable without additional hardware investment.
- When real LLM integration is needed (after v0.1 schema validation), the interface is ready to swap.

### C.3 Allowed / Disallowed LLM Usage

| Operation | Status |
|-----------|--------|
| Generate Draft Lab Contract via stub (structured template) | ALLOWED |
| Generate Draft Lab Contract via real LLM API | ALLOWED (after v0.1 schema validation, with explicit enablement) |
| Admin review of LLM-generated draft | REQUIRED (never bypassed) |
| LLM override Feasibility Gate reject | NEVER ALLOWED |
| LLM generate published lab directly | NEVER ALLOWED |
| LLM generate executable verifier code | NEVER ALLOWED |
| LLM process user article without user consent | NEVER ALLOWED |
| LLM call during feasibility classification | ALLOWED (future; v0.1 uses rule-based or hybrid stub) |
| LLM call to extract source grounding snippets | ALLOWED (future; v0.1 stub marks all as inferred) |

### C.4 Interface Design

The following interfaces must be designed before implementation begins (no code written in this gate):

```python
class LLMProviderPort(Protocol):
    """Abstract interface for LLM-backed article understanding."""
    async def analyze_article(self, text: str, domain_hint: str) -> ExperimentPlan: ...
    async def generate_draft_contract(self, plan: ExperimentPlan) -> DraftLabContractFields: ...
    async def extract_source_grounding(self, text: str, step: ExperimentStep) -> SourceGrounding: ...
    async def classify_feasibility(self, text: str) -> FeasibilityResult: ...

class StubLLMProvider:
    """v0.1 stub — returns structurally valid placeholder output."""
    async def analyze_article(self, text: str, domain_hint: str) -> ExperimentPlan:
        # Returns a minimal valid ExperimentPlan with all fields marked as inferred.
        ...

class ArticleUnderstandingService:
    """Orchestrates LLMProviderPort calls; enforces fail-closed rules."""
    def __init__(self, provider: LLMProviderPort): ...

class DraftContractGenerator:
    """Converts ExperimentPlan to DraftLabContract with source grounding."""
    ...

class FeasibilityClassifier:
    """Classifies article into directly_lab_ready / partially_lab_ready / not_lab_ready."""
    ...

class SourceGroundingExtractor:
    """Extracts verbatim article excerpts for each step; marks confidence."""
    ...
```

### C.5 Fail-Closed Rules

| Condition | Action |
|-----------|--------|
| LLM output missing source grounding for any step | Reject output; mark step as `unsupported_inference`; require admin resolution |
| LLM invents steps not traceable to source article | Flag all as `unsupported_inferences`; admin must resolve each |
| LLM proposes unsafe operation (shell injection, privilege escalation) | Reject; add to safety_flags; require admin explicit acknowledgement |
| LLM cannot determine verifier for a step | Mark step verifier_candidate as `not_verifiable`; require admin decision |
| LLM confidence low (stub: all fields) | Mark all as confidence=`inferred`; surface in admin review |
| LLM provider unavailable | No auto-generation; return provider_unavailable error; do not degrade to partial output |
| LLM returns structurally invalid output | Reject entirely; do not attempt to salvage partial fields |
| LLM returns empty output | Reject; do not create empty draft |

---

## D. N-02 Article Storage Strategy

### D.1 Storage Modes Evaluated

| Mode | Description | Privacy Risk | Admin Review Support | v0.1 viable? |
|------|-------------|-------------|---------------------|-------------|
| Full-text storage (long-term) | Store complete article text permanently | HIGHEST — reproduces third-party content indefinitely | Full support | NO |
| Ephemeral full-text + persistent hash/extracted structure | Process in-memory; persist only metadata, hash, extracted snippets, generated contract | LOW | Supported via source_grounding_snippets | **YES — v0.1 default** |
| No full-text storage (hash only) | Only store hash and metadata | LOWEST | Poor — admin cannot review source grounding | NO — insufficient for admin review |

### D.2 v0.1 Storage Policy

**Ephemeral source text. No long-term full-text storage.**

| Data element | Storage | Retention | Access |
|-------------|---------|-----------|--------|
| Raw article text | In-memory only during processing session | Discarded after processing completes | Processing pipeline only (not logged, not stored) |
| content_hash (SHA-256 of normalized text) | Persistent | Indefinite (audit dedup) | Admin only |
| source_metadata (title, source_type, word_count, extracted_date, author) | Persistent with draft | Until draft is deleted | Draft owner + admin |
| feasibility_result (tier, reasons, missing_requirements, safety_flags) | Persistent with draft | Until draft is deleted | Draft owner + admin |
| source_grounding_snippets (verbatim excerpts, minimal necessary) | Persistent with draft | Until draft is deleted | Admin only (not exposed to learner) |
| unsupported_inferences (field, inferred_value, reason) | Persistent with draft | Until draft is deleted | Admin only |
| Generated Draft Lab Contract | Persistent | Until user/admin deletes | Draft owner + admin |
| admin_decision (approve / request_changes / reject + timestamp) | Persistent with draft | Until draft is deleted | Admin + audit |
| Published Lab (no raw article content) | Persistent | Indefinite (catalog) | Public (learners) |

### D.3 Raw Text Handling

- **Never stored to disk** in v0.1. Processing is ephemeral.
- **Never logged** — no log line may contain article text or excerpts beyond what is in source_grounding_snippets (which are stored, not logged).
- **Never transmitted to learners** — learners see only the published lab steps; source article is not visible.
- **Never auto-forwarded to third parties** — if a real LLM API is used in future, explicit user consent is required before text is transmitted.

### D.4 Sensitive Content Handling

If the article submission contains apparent secrets (token, password, private key, API key, connection string with credentials):

| Step | Action |
|------|--------|
| Detection | FeasibilityGate / FeasibilityClassifier scans for obvious credential patterns |
| Result | `feasibility_tier = not_lab_ready`, `safety_flags: ["sensitive_content_detected"]` |
| Persistence | Only rejection metadata (content_hash, timestamp, reason) — no content stored |
| User feedback | "Submission rejected: article appears to contain credentials or secrets. Please remove sensitive content before retrying." |
| Log | Only: `{"event": "submission_rejected", "reason": "sensitive_content_detected", "hash": "<hash>"}` |

The system must not:
- Store article content that triggered sensitive content detection
- Attempt to generate a lab from an article with credentials
- Log or persist the credential values or context

### D.5 Access Boundary

| Actor | Access |
|-------|--------|
| Article submitter (admin) | Own drafts: feasibility_result, source_metadata, generated contract, admin_decision history |
| Admin reviewer | source_grounding_snippets, unsupported_inferences, feasibility_result, full draft — not raw article text |
| Learner | Published lab steps only — no source article, no source grounding snippets |
| Logs | content_hash + decision + event type — never article text |
| Audit trail | content_hash + decision + timestamp — never article text |

---

## E. N-03 Copyright / Retention Policy

### E.1 User Consent Requirement

Before submitting article content, the user must confirm:

> "I confirm that I have the right to use this content to generate a personal or team experiment. I am not submitting content that is confidential to others, that contains secrets or credentials, or that I do not have permission to use for this purpose."

This consent must be:
- An explicit checkbox (not implied by submit action)
- Recorded in the submission audit log (content_hash + timestamp + consent=true)
- Not a blanket one-time consent — required per submission
- Not waivable by admin

### E.2 Copyright Risk Posture

| Risk scenario | v0.1 handling |
|---------------|---------------|
| User pastes third-party blog post | User confirms they have right to use; no full-text stored; only minimal snippets for internal review |
| User pastes employer-internal doc | Same — user consent; ephemeral; minimal snippets |
| User pastes public documentation (Apache, K8s docs) | Same — typically permissive license; user confirms |
| URL scraping | NOT ALLOWED in v0.1 — admin paste only |
| Public article fetching | NOT ALLOWED in v0.1 |
| Generated lab reproducing article text verbatim | NOT ALLOWED — generated lab contains only experiment steps, not article prose |

**v0.1 copyright posture**: Admin-only submission (not public-facing); ephemeral raw text; generated lab is transformative work (executable steps derived from, not reproducing, the article); minimal verbatim excerpts stored only for internal admin review. This is a low-risk posture appropriate for internal MVP validation.

Explicit statement: **v0.1 does not enable public article submission. All article submission is via admin paste.** This materially limits copyright exposure.

### E.3 Retention Defaults

| Data element | Default retention | Admin override |
|-------------|-----------------|----------------|
| Raw article text | Ephemeral (session-scoped; discarded after processing) | Not applicable — no long-term storage path |
| Draft Lab Contract | Until user/admin deletes | Admin purge available |
| source_grounding_snippets | Stored with draft; deleted when draft is deleted | Admin purge |
| Rejected submission (sensitive content) | Only metadata (hash, timestamp, reason) — 30 days, then purged | Admin may purge immediately |
| Rejected submission (not_lab_ready) | Only metadata (hash, timestamp, feasibility_result) — 30 days, then purged | Admin may purge immediately |
| Published Lab | Indefinite (catalog) — contains no raw article content | Admin unpublish |
| Audit records (hash + decision + timestamp) | Indefinite | Not purgeable (security audit) |
| Admin consent records | Indefinite | Not purgeable (audit) |

### E.4 Deletion / Purge

| Operation | Who can trigger | Effect |
|-----------|----------------|--------|
| Delete own draft | Draft owner (admin who submitted) | Removes: draft contract, source_metadata, feasibility_result, source_grounding_snippets, unsupported_inferences. Retains: content_hash + deletion event in audit log |
| Admin purge draft | Any admin | Same as above |
| Admin purge rejected submission metadata | Admin | Removes rejection metadata (not present in audit hash) |
| Admin unpublish lab | Admin | Removes from catalog; lab data retained in admin view |
| User-initiated data deletion request | Admin executes | All drafts deleted + audit note added |

v0.1 does not implement automated expiry enforcement — retention policy is manual. Automated expiry is a v0.2 feature.

### E.5 UI / Docs Notice Draft

For future article submission UI (admin panel):

---

**使用说明（Article-to-Lab 功能）**

请仅提交您有权使用的技术内容。

- 请勿提交密钥、token、密码、私钥或生产数据
- 请勿提交包含他人机密信息的内容
- 系统会判断内容是否适合生成实验；不适合的内容会被拒绝并说明原因
- 生成结果为草稿，须经管理员审核，不会直接发布
- 原始文章内容不会被长期保存；审核完成后仅保留最小必要摘录
- 实验环境完成后会被自动回收

[☐] 我确认我有权使用上述内容生成实验草稿，且内容不包含凭证或他人机密信息。

---

---

## F. Implementation Preconditions

All of the following must be true before K8s Article-to-Lab Draft Mode Implementation begins:

| Precondition | Status |
|-------------|--------|
| Feasibility Gate defined (3 tiers, reject response structure) | READY — `ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` Section D |
| Draft Lab Contract schema extension designed | READY — `ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` Section F |
| LLMProviderPort interface design accepted | READY — this document Section C.4 |
| v0.1 stub mode accepted (no live LLM) | READY — this document Section C.2 |
| Article storage policy accepted | READY — this document Section D |
| Copyright / retention policy accepted | READY — this document Section E |
| Admin Review flow defined | READY — `ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` Section G |
| StaticValidator extension plan (5 new checks) defined | READY — `ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` Section G.3 |
| No direct LLM publish | ENFORCED — Admin Review required at all design layers |
| No full-text long-term storage | ENFORCED — ephemeral source text policy |
| No raw secret retention | ENFORCED — sensitive content immediate discard |
| No arbitrary article-to-lab claimed | ENFORCED — stub mode; K8s only; admin-only input |
| tests / scans planned | YES — all new modules require unit tests; coverage ≥ 92% |

---

## G. Decision

**ARTICLE_TO_LAB_PREREQS_READY_WITH_NOTES**

### Rationale

**READY** because:
- All three go/no-go blockers (N-01, N-02, N-03) are definitively resolved by this gate.
- N-01: v0.1 stub mode unblocks implementation without requiring a live LLM decision. `LLMProviderPort` is designed as a swappable interface — the real provider can be integrated after schema validation without architectural changes.
- N-02: Ephemeral source text policy eliminates the main storage risk. The set of persistable fields is precisely enumerated. No ambiguity remains about what is stored and where.
- N-03: User consent + no-long-term-raw-text policy establishes a defensible low-risk copyright posture appropriate for admin-only internal MVP validation.
- All decisions are internally consistent with the pipeline architecture (Section E of Design Gate), with each other, and with the "不允许" list from the task.
- Fail-closed rules (Section C.5) are complete — every failure mode has a defined action.

**WITH_NOTES** because:
- Stub mode means real LLM article understanding is not validated in v0.1. The first real article ingestion (after stub validation) will be a separate validation milestone.
- Copyright policy relies on good-faith user submission — no automated verification of the user's right to submit content is implemented in v0.1.
- N-04 through N-09 remain open but none block v0.1 start.
  - N-04 (user-provided secret in article): handled by sensitive content detection in feasibility gate; edge cases may surface during testing.
  - N-09 (feasibility gate automation level): v0.1 uses rule-based classification; LLM-assisted feasibility is deferred.
- Retention expiry is manual in v0.1 — no automated 30-day purge enforcement; operator must execute manually.
- LLM provider for real integration (after v0.1) remains undecided between OpenAI and Anthropic APIs.

**NOT BLOCKED** because:
- The three go/no-go blockers are now resolved with clear, actionable decisions.
- No open question in N-04 through N-09 blocks v0.1 implementation start.
- No constraint in the task "不允许" list is violated by any decision in this gate.
- The platform substrate (K8s domain proof, Admin Review, StaticValidator, PublishService) is proven and ready.

---

## H. Recommended Next Step

**Article-to-Lab MVP Contract Schema Gate** — gate: `ARTICLE_TO_LAB_CONTRACT_SCHEMA_GATE_v0.1`

**Why this step before implementation**: The Draft Lab Contract schema extensions (`source_metadata`, `feasibility_result`, `source_grounding`, `unsupported_inferences`, `admin_decision`) need to be precisely specified and locked before any implementation begins. Writing code against an unfinished schema creates rework. The schema gate produces the single-source-of-truth Pydantic model definitions that all pipeline components depend on.

**Scope of next gate**:
1. Finalize `ArticleSourceMetadata` Pydantic model (all fields, all validators)
2. Finalize `FeasibilityResult` Pydantic model (including safety_flags enum)
3. Finalize `SourceGrounding` Pydantic model (step_id, article_excerpt, confidence enum, verbatim constraint)
4. Finalize `UnsupportedInference` Pydantic model (field, inferred_value, reason, admin_resolved)
5. Extend `LabDraftState` to include all new fields
6. Extend `StaticValidator` check list with 5 new check IDs (schema-level, no logic yet)
7. Extend admin API response schema to surface source_grounding and unsupported_inferences
8. Write schema-level unit tests (valid/invalid cases, boundary conditions)
9. Gate decision: SCHEMA_LOCKED or SCHEMA_NEEDS_REVISION

**Not next**:
- K8s Article-to-Lab Draft Mode full implementation (wait for schema gate)
- LLM provider spike (not needed until stub validation is complete)
- Linux domain adapter (not needed until K8s Article-to-Lab is validated)
- Customer pilot retry (parallel, does not block engineering)

---

## Technical Self-Check

| Check | Result |
|-------|--------|
| No TODO/FIXME in this document | PASS |
| No placeholder-as-success | PASS |
| N-01 resolved without opening implementation | PASS — decisions only, 0 code |
| N-02 resolved without full-text storage commitment | PASS — ephemeral policy |
| N-03 resolved without copyright risk | PASS — admin-only, ephemeral, consent |
| No LLM direct publish | PASS — explicitly prohibited |
| No LLM override of reject decision | PASS — explicitly prohibited in fail-closed rules |
| No user article long-term raw storage | PASS — ephemeral processing |
| No copyrighted full text stored | PASS — only minimal snippets for admin review |
| No content publicly transmitted without consent | PASS — admin-only; user consent required |
| No URL scraping | PASS — explicitly not allowed |
| No sensitive content retained | PASS — immediate discard policy |
| No arbitrary article-to-lab claimed | PASS |
| No LLM live generation claimed | PASS — stub mode |
| No production ready claim | PASS |
| No public launch claim | PASS |
| K8s domain proof not degraded | PASS — 0 code changes |
| "读完即练，结果说话" preserved | PASS |
| Future Linux / multi-domain portability preserved | PASS — LLMProviderPort and storage policy are domain-agnostic |
| No fifth lab published | PASS |
| No concurrency increase | PASS |
| No customer pilot started | PASS |
| No runtime / verifier / terminal modification | PASS |
| No production VMID 500-599 touched | PASS |
| No production pool / registry modified | PASS |
| Fail-closed rules complete for all LLM failure modes | PASS |
| All preconditions enumerable and verifiable | PASS — Section F |
| Decision rationale grounded in evidence | PASS — references Design Gate sections |
