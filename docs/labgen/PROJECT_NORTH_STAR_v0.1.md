# LabGen Project North Star v0.1

**Date**: 2026-06-20 (re-aligned after Claude reset; original 2026-06-16)
**Operator**: Claude Code acting as senior dev + ops
**Status**: Authoritative — supersedes any prior document language that frames LabGen as a fixed K8s course platform
**No real secrets in this document.**

---

## 1. Project Mission

LabGen is **not** a fixed course platform.
LabGen is **not** a pure K8s learning platform.
LabGen is **not** just an LMS that displays courseware.

LabGen is a platform that turns reproducible technical content into runnable, on-demand experiments.

The user's core scenario: a technical practitioner reads a good, uniquely insightful article and wants to practice immediately — but has no local environment, and rebuilding one manually is too costly. They end up consuming the material passively. Knowledge is never converted to skill.

LabGen solves: **shrink the distance between "reading a technical article" and "running a live verification."**

## 2. Product Slogan

**读了能练，练完即熟。**
("Read it and practice it. Practice through it and you master it.")

Auxiliary expression: **读了能做，做了就懂。**
("Read it and be able to do it. Do it and you understand.")

Alt expression: **读完即练，结果说话。**
("Read it, then practice it immediately — the result speaks for itself.")

Interpretation:
- **读了能练**: Every article should become something you can practice right away, not just consume.
- **练完即熟**: Completing the hands-on steps in an isolated, verifiable environment converts reading into retained, executable skill — the way 熟能生巧 (practice makes perfect) always works.
- **读了能做**: The article gives you real operations to reproduce, not passive content to scroll through.
- **做了就懂**: Doing the steps in an isolated, verifiable environment converts reading into retained ability.
- **结果说话**: Every step can be Checked; the system confirms progress automatically.
- **结果说话**: When the experiment completes, the environment is reclaimed, credentials are revoked, resources are cleaned up — nothing lingers.

## 3. Current Phase Product Strategy

The current phase uses **Admin-curated Article-to-Lab**.

This means:

- Technical articles are provided by the admin / project team, **not** by general readers.
- The admin is responsible for article curation, rights confirmation, safety confirmation, and content quality.
- The system parses admin-provided articles into Guided Practice Labs.
- The admin reviews the Draft Lab Contract before any learner sees it.
- Project-team-authored articles are published to public channels (WeChat public accounts, Zhihu, CSDN, GitHub, blogs, etc.).
- Readers enter the corresponding lab from the article's CTA (call to action).
- Readers practice immediately in a browser terminal/workspace.
- The lab session ends with cleanup and credential reclaim.

**Not in scope for current phase:**

- General readers freely submitting arbitrary articles.
- Auto-generating and publishing labs from any article.
- URL scraping.
- Live LLM publishing.
- Auto-publishing generated drafts.
- Public launch.
- Production rollout.

**Future rollout path:**

1. Admin-curated articles (current).
2. Trusted contributor / trusted customer articles.
3. Eventually: general reader-submitted article input (with consent and review gates).

## 4. Content Form: Guided Practice Lab (not Assessment Lab)

v0.1 produces **Guided Practice Labs**, not Assessment Labs.

The goal is to help readers reproduce and understand the article's practical workflow — not to test whether they already know it.

### Lab UX Layout

**Left panel:**
- Experiment document
- Experiment background (article content brief — see below)
- Experiment objectives
- Guided steps
- Copyable commands
- Expected output
- Common issues / hint prompts
- Check button
- AI Tutor

**Right panel:**
- Browser terminal / workspace
- Current namespace / VM / sandbox status
- Command execution environment

### Design Principles

- **Give commands**: don't make users guess commands.
- **Give context**: don't leave users wondering why.
- **Give expected output**: don't make users guess if it worked.
- **Give hint prompts**: don't let users get stuck.
- **Check confirms progress**: not gatekeeping or assessing difficulty.
- If the article lacks sufficient operable information → mark as `partially_lab_ready` or reject; do not hardcode invented steps.
- Experiment background must be derived from the article content brief:
  - What this article covers.
  - Why it is worth practicing.
  - Which key points this experiment will reproduce.
- AI Tutor remains present (see Section 12 for constraints).

## 5. Canonical Flow

```text
Admin-curated Technical Article / Document / README
        ↓
Article Operability / Lab Feasibility Gate
        ↓
Experiment Planner
        ↓
Draft Lab Contract
        ↓
Human / Admin Review
        ↓
StaticValidator
        ↓
Internal Rehearsal
        ↓
Publish article-linked lab
        ↓
Reader enters from article CTA
        ↓
Learner Workspace + Terminal + AI Tutor
        ↓
Guided Step Verification
        ↓
Feedback / Reflection
        ↓
Cleanup / Credential Reclaim
```

## 6. Article Operability / Lab Feasibility Gate

LabGen is **not** a system that forcibly turns "any article" into an experiment. The first step of Article-to-Lab must be a judgment of whether the input content is operable and verifiable — **before** a Draft Lab Contract is ever generated.

When an admin submits a technical article, README, tutorial, or internal tech doc, the system **must** first run the **Lab Feasibility Gate** to decide whether to generate a Draft Lab Contract.

The Feasibility Gate classifies input into exactly one of three tiers:

### 6.1 Directly Lab-Ready

The article has clear, sufficient experiment conditions and may proceed to a Draft Lab Contract.

Judgment criteria (must have all of):
- a clear technical objective
- executable operations
- commands, configuration, code, or deployment steps that can become experiment actions
- an environment that can be provisioned for it
- observable results
- an automatically verifiable state
- can run safely inside a temporary isolated environment
- can be cleaned up when the experiment ends
- does not require real production accounts, real keys, or inaccessible third-party resources
- does not involve destructive, illegal, or high-risk unsafe operations

### 6.2 Partially Lab-Ready

The article has practice value but is missing key experiment information. The system must **not** publish directly, and must **not** fabricate missing content.

This case must return **clarification / missing requirements**, for example:
- missing target system/version
- missing runtime environment
- missing command or configuration
- missing input examples
- missing verifiable outcome
- depends on an external service with no safe substitute
- cleanup path unclear
- verifier path unclear
- content is experimentable in principle, but only a **limited draft** can be generated

### 6.3 Not Lab-Ready / Reject

If the article has no operability, the system must explicitly refuse to generate an experiment, with a clear reason.

Non-exhaustive reject scenarios:
- pure theory article
- news, opinion, trend analysis
- no executable steps
- no verifiable outcome
- requires a real production environment
- requires real keys / tokens / accounts / user private or sensitive data
- requires an inaccessible third-party service
- involves destructive, illegal, or high-risk unsafe operations
- experiment cost too high, not suited to a temporary environment
- cannot be cleaned up
- cannot establish a safety boundary
- cannot be automatically verified
- generating an experiment would mislead the user into thinking they have mastered the article's core content

When rejecting, the system must:
- clearly state why a lab cannot be generated
- list which operable elements are missing
- where possible, suggest what information the admin could add to retry
- if the article is only a concept summary, explicitly state it can only produce summary / study notes, not an executable lab
- never harden an experiment just to appear "smart"
- never generate a fake experiment that cannot be verified
- never let LLM output override a Feasibility Gate rejection

## 7. Current Domain Proof

The current K8s learning platform is the **first validation scenario** — it is not the permanent product boundary.

The K8s domain is currently used to validate:
- namespace isolation
- ConfigMap / Secret / Deployment resource experiments
- kubectl terminal
- verifier
- RBAC safety
- cleanup
- real human learner validation
- small cohort validation
- ops runbook
- home_lab_mvp runtime
- Article-to-Lab stub pipeline (admin-curated, stub classifier)
- Admin Review Rehearsal (4 input samples verified)

All of the above are domain-agnostic platform capabilities being proven through one concrete domain (K8s). The proof is the point, not the domain.

## 8. Future Domains

The architecture must remain able to support, without rewrite:
- Linux learning platform
- shell / filesystem / process / permission labs
- networking labs
- Docker / container labs
- database labs
- CI/CD labs
- cloud service labs (currently blocked by safety policy)
- security sandbox labs
- Python / backend engineering labs

## 9. Architecture Principle

**General Experiment Core + Replaceable Domain Contract**

Do not let the system harden into K8s-only. The following must remain swappable abstractions:
- Lab Contract
- Article Draft Contract
- Domain Contract
- Runtime Adapter
- Environment Provisioner
- Verifier Adapter
- Terminal Adapter
- Cleanup Adapter
- Safety Policy
- Feedback Template
- Admin Review / Publish Gate
- AI Tutor Context

## 10. What We Must Not Become

- Must not harden into a fixed K8s course platform.
- Must not just keep adding more K8s labs for their own sake.
- Must not promote home_lab_mvp to production status.
- Must not skip cleanup for the sake of a demo.
- Must not skip human review for the sake of speed.
- Must not let an LLM publish directly.
- Must not let AI silently generate unreviewable experiments.
- Must not trade safety boundaries for user-scale growth.
- Must not let technical articles remain stuck at the "skim/consume" level.
- Must not let experiment environments accumulate long-term residue.
- Must not pollute the user's local machine.
- Must not break future Linux / multi-domain migration capability.
- Must not allow inoperable articles to be hardcoded into experiments.
- Must not generate experiments that cannot be automatically verified.
- Must not mislead learners into thinking they have mastered article content via fake experiments.
- Must not allow reader-submitted articles until the admin-curated gate is validated.
- Must not allow URL scraping.
- Must not let any generated draft enter the learner catalog without a complete publish gate.

## 11. LLM Positioning

The LLM's correct position is **not** to publish experiments directly. It is to:
- extract practicable knowledge points from an article
- generate a Draft Lab Contract
- generate draft steps
- generate a verifier draft
- generate an environment-requirement draft
- generate a learning-feedback draft
- generate an AI Tutor hint draft
- help admins correct content

But it must always go through:
- Human / Admin Review
- StaticValidator
- Publish Gate
- Internal Rehearsal
- Real Learner Validation

v0.1 uses stub mode only (no live LLM calls). `LLMProviderPort` is the swappable interface. Live LLM is deferred until stub flow is validated.

## 12. AI Tutor Context

AI Tutor is part of the Guided Practice Lab and must remain present. Its role and constraints:

**AI Tutor may:**
- Explain what a command does.
- Explain an error message.
- Guide the learner within safety boundaries.
- Help the learner understand the current step.
- Hint at what to look for next.

**AI Tutor must not:**
- Bypass the experiment (skip steps / shortcut the lab).
- Leak platform information (kubeconfig paths, admin credentials, other users' data).
- Suggest dangerous or irreversible operations.
- Complete the lab for the user.
- Answer questions outside the current lab's domain.
- Reveal that a step's verifier logic can be fooled.

## 13. Product Stage Definition

The project has completed **real-human product validation** (3 rounds, 4 labs, multiple learners).

It is currently in the **Article-to-Lab pipeline build phase**.

It is **not**:
- public launch
- production ready
- cloud production
- LLM live generation phase
- fixed course expansion phase
- customer pilot (blocked — no suitable external customer identified)

Current focus:
- Building and validating the Article-to-Lab pipeline (admin-curated, stub classifier)
- Admin Review Rehearsal: complete (4 K8s samples verified)
- Next: K8s Article-to-Lab Internal Rehearsal to Publish Candidate
- Eventually: Linux domain proof, Docker domain proof

## 14. Decision Rule

Every subsequent task must ask:

- Does this step shrink the distance between "read an article" and "run a live verification"?
- Does this step strengthen Article-to-Lab capability?
- Does this step preserve future Linux / multi-domain migration capability?
- Does this step still support "读了能练，练完即熟"?
- Does this step produce a Guided Practice Lab, not an Assessment Lab?
- Does this step merely pile on more fixed K8s coursework?
- Does this step introduce K8s-only hardcoding that cannot migrate?
- Does this step weaken cleanup / credential / safety / verifier boundaries?
- Does this step bypass Admin Review or Feasibility Gate?

If the answer reveals drift, the task must be paused and realigned.

## 15. Article-to-Lab Follow-up Execution Checklist

Every subsequent Article-to-Lab task must verify:

**Product alignment:**
- [ ] Serves "读了能练，练完即熟"
- [ ] Input is Admin-curated (not reader-submitted)
- [ ] Output is Guided Practice Lab (not Assessment Lab)
- [ ] Experiment background is derived from article content brief
- [ ] AI Tutor context is included
- [ ] Steps include: copyable commands / expected output / hint prompts
- [ ] Check is used for progress confirmation (not difficulty gatekeeping)

**Gate preservation:**
- [ ] Feasibility Gate is preserved
- [ ] Inoperable articles → reject (no hardcoding)
- [ ] Admin Review is preserved
- [ ] StaticValidator is preserved
- [ ] Internal Rehearsal is preserved

**Boundary preservation:**
- [ ] No direct publish of generated lab
- [ ] No generated draft in learner catalog without complete publish gate
- [ ] No live LLM calls
- [ ] No break of Linux / multi-domain portability
- [ ] No modification of runtime / verifier / terminal (unless explicit gate)
- [ ] No modification of production VMID 500-599
- [ ] No modification of production pool / registry
- [ ] No customer pilot launch
- [ ] No fifth lab published
- [ ] No concurrency increase

## 16. Article-to-Lab Pipeline Progress

| Gate | Status | Evidence |
|------|--------|----------|
| K8s Domain Proof (4 labs, 3 rounds real human validation) | ✅ COMPLETE | `REAL_HUMAN_COHORT_ROUND2_RESULT_v0.1.md` |
| Small Customer Pilot Preparation Gate | ✅ COMPLETE | `SMALL_CUSTOMER_PILOT_PREPARATION_GATE_v0.1.md` |
| Small Customer Pilot Execution | 🔴 BLOCKED | `SMALL_CUSTOMER_PILOT_RESULT_v0.1.md` — NO_SUITABLE_SMALL_CUSTOMER |
| Article-to-Lab Pipeline Design Gate | ✅ COMPLETE | `ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` |
| Article-to-Lab Implementation Prerequisites | ✅ COMPLETE | `ARTICLE_TO_LAB_IMPLEMENTATION_PREREQUISITES_v0.1.md` — N-01/N-02/N-03 resolved |
| Article-to-Lab MVP Contract Schema Gate | ✅ COMPLETE | `ARTICLE_TO_LAB_MVP_CONTRACT_SCHEMA_GATE_v0.1.md` — 11 models, 15 guardrails, 116 tests |
| **K8s Article-to-Lab Draft Mode Implementation** | ✅ **COMPLETE** | `K8S_ARTICLE_TO_LAB_DRAFT_MODE_IMPLEMENTATION_RESULT_v0.1.md` — 9 endpoints, 60 tests, stub classifier |
| **K8s Article-to-Lab Admin Review Rehearsal** | ✅ **COMPLETE** | `K8S_ARTICLE_TO_LAB_ADMIN_REVIEW_REHEARSAL_RESULT_v0.1.md` — 4 samples, MEDIUM-001 fixed, 53 tests |
| K8s Article-linked Lab Reader-facing CTA Dry Run | ✅ COMPLETE | `READER_FACING_ARTICLE_CTA_DRY_RUN_RESULT_v0.1.md` — reader path end-to-end validated |
| K8s Guided Practice Quality Iteration Lab 5 | ✅ COMPLETE | `GUIDED_PRACTICE_QUALITY_ITERATION_LAB5_RESULT_v0.1.md` — all TODO placeholders cleared, placeholder gate added |
| **K8s Article-linked Lab Trusted Reader Pilot** | ✅ **COMPLETE** | session a301676a, LAB_CLOSED, cleanup_verified=True, step_1+step_2 PASS, observer-confirmed no hiccups |
| **Linux Domain Proof Design Gate** | ✅ **COMPLETE** | `LINUX_DOMAIN_PROOF_DESIGN_GATE_v0.1.md` — LINUX_DOMAIN_PROOF_DESIGN_READY_WITH_NOTES; 5 BLOCKER couplings identified and enumerated; recommended runtime: container sandbox; recommended first lab: Linux Files and Permissions Basics |
| **Linux Domain Contract Schema Extension** | ✅ **COMPLETE** | `LINUX_DOMAIN_CONTRACT_SCHEMA_EXTENSION_RESULT_v0.1.md` — LINUX_DOMAIN_CONTRACT_SCHEMA_READY_WITH_NOTES；LabDomainType / LinuxVerifyType / LinuxVerifyTemplate / LinuxSandboxPolicy / CleanupLinuxWorkspace；StaticValidator Linux 路径；H-01+H-02 修复；60 tests；publish 仍 blocked（runtime pending） |
| Linux Domain Proof (full, through Trusted Reader) | ⬜ NEXT | Task 2: Runtime Adapter Spike |
| Docker Domain Proof | ⬜ PENDING | After Linux domain proof |

The pipeline design (`ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md`) is the canonical reference for the Article-to-Lab platform architecture. All subsequent implementation must follow that design and must not harden into K8s-only.

---

*This document is the authoritative reference for LabGen's structural goal. Any future document that describes the project as a pure K8s learning platform, or that omits the Admin-curated / Guided Practice Lab / Article Operability Gate constraints, must be corrected to reference this document.*
