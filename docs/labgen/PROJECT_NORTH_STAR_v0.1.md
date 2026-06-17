# LabGen Project North Star v0.1

**Date**: 2026-06-16
**Operator**: Claude Code acting as senior dev + ops
**Status**: Authoritative — supersedes any prior document language that frames LabGen as a fixed K8s course platform
**No real secrets in this document.**

---

## 1. Project Mission

LabGen is **not** a fixed course platform.
LabGen is **not** a pure K8s learning platform.
LabGen is **not** just an LMS that displays courseware.

LabGen is a platform that turns reproducible technical content into runnable, on-demand experiments.

The user's core scenario: a technical practitioner reads a good article and wants to verify it immediately — without manually building a local environment.

The project's goal is to turn **"consuming material" into "practiced ability."**

> **Mission statement**: "Let every reproducible technical article become a temporary, isolated, verifiable, recyclable live experiment."

## 2. Product Slogan

**读完即练，结果说话。**
("Read it, then practice it immediately — the result speaks for itself.")

Interpretation:
- **读完即练**: An article is not consumed by passive reading alone — it gets parsed into practicable steps.
- **马上**: The system prepares the environment; the user doesn't build it themselves.
- **结果**: Isolated environment, least-privilege access, credential non-leakage.
- **说话**: Every step can be Checked; the system gives feedback.
- **结果说话**: When the experiment completes, the environment is reclaimed, credentials are revoked, resources are cleaned up.

## 3. Canonical Flow

```text
Technical Article / Document / README
        ↓
Experiment Planner
        ↓
Draft Lab Contract
        ↓
Human/Admin Review
        ↓
Static Validation
        ↓
Runtime Provisioning
        ↓
Learner Workspace + Terminal
        ↓
Step Verification
        ↓
Feedback / Reflection
        ↓
Cleanup / Credential Reclaim
```

## 4. Article Operability / Lab Feasibility Gate

LabGen is **not** a system that forcibly turns "any article" into an experiment. The first step of Article-to-Lab must be a judgment of whether the input content is operable and verifiable — **before** a Draft Lab Contract is ever generated.

When a user submits a technical article, README, tutorial, or internal tech doc, the system **must** first run the **Lab Feasibility Gate** to decide whether to generate a Draft Lab Contract.

The Feasibility Gate classifies input into exactly one of three tiers:

### 4.1 Directly Lab-Ready

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

### 4.2 Partially Lab-Ready

The article has practice value but is missing key experiment information. The system must **not** publish directly, and must **not** fabricate missing content.

This case must return **clarification / missing requirements**, for example:
- missing target system/version
- missing runtime environment
- missing command or configuration
- missing input examples
- missing verifiable outcome
- depends on an external service with no safe substitute
- requires the user to choose an experiment scope
- content is experimentable in principle, but only a **limited draft** can be generated

### 4.3 Not Lab-Ready / Reject

If the article has no operability, the system must explicitly refuse to generate an experiment, with a clear reason.

Non-exhaustive reject scenarios:
- pure theory article
- news, opinion, trend analysis
- no executable steps
- no verifiable outcome
- missing necessary environment with no reasonable inference possible
- requires a real production environment
- requires real keys / tokens / accounts / user private or sensitive data
- requires an inaccessible third-party service
- involves destructive, illegal, or high-risk unsafe operations
- experiment cost too high, not suited to a temporary environment
- cannot be cleaned up
- cannot establish a safety boundary
- cannot be automatically verified
- generating an experiment would mislead the user into thinking they've mastered the article's core content

When rejecting, the system must:
- clearly state why a lab cannot be generated
- list which operable elements are missing
- where possible, suggest what information the user could add to retry
- if the article is only a concept summary, explicitly state it can only produce summary / study notes, not an executable lab
- never harden an experiment just to appear "smart"
- never generate a fake experiment that cannot be verified
- never bypass safety / cleanup / verifier requirements

This gate is the formal entry gate of the Article-to-Lab pipeline. At the current stage it is recorded in the North Star document for subsequent design; full automated decision-making is **not** required to be implemented now.

## 5. Current Domain Proof

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

All of the above are domain-agnostic platform capabilities being proven through one concrete domain (K8s). The proof is the point, not the domain.

## 6. Future Domains

The architecture must remain able to support, without rewrite:
- Linux learning platform
- shell / filesystem / process / permission labs
- networking labs
- Docker / container labs
- database labs
- CI/CD labs
- cloud service labs
- security sandbox labs
- Python / backend engineering labs

## 7. Architecture Principle

**General Experiment Core + Replaceable Domain Contract**

Do not let the system harden into K8s-only. The following must remain swappable abstractions:
- Lab Contract
- Domain Contract
- Runtime Adapter
- Environment Provisioner
- Verifier Adapter
- Terminal Adapter
- Cleanup Adapter
- Safety Policy
- Feedback Template
- Admin Review / Publish Gate

## 8. What We Must Not Become

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

## 9. LLM Positioning

The LLM's correct position is **not** to publish experiments directly. It is to:
- extract practicable knowledge points from an article
- generate a Draft Lab Contract
- generate draft steps
- generate a verifier draft
- generate an environment-requirement draft
- generate a learning-feedback draft
- help admins correct content

But it must always go through:
- Human/Admin Review
- StaticValidator
- Publish Gate
- Internal Rehearsal
- Real Learner Validation

## 10. Product Stage Definition

The project is currently in the **real-human product validation phase**.

It is **not**:
- public launch
- production ready
- cloud production
- LLM live generation phase
- fixed course expansion phase

Current focus is only:
- validating whether real learners can independently complete experiments
- validating the terminal + verifier + cleanup closed loop
- validating real feedback from a small cohort
- validating whether the project is ready to enter the Small Customer Pilot Preparation Gate

## 11. Decision Rule

Every subsequent task must ask:

- Does this step shrink the distance between "read an article" and "run a live verification"?
- Does this step strengthen Article-to-Lab capability?
- Does this step preserve future Linux / multi-domain migration capability?
- Does this step still support "读完即练，结果说话"?
- Does this step merely pile on more fixed K8s coursework?
- Does this step introduce K8s-only hardcoding that cannot migrate?
- Does this step weaken cleanup / credential / safety / verifier boundaries?

If the answer reveals drift, the task must be paused and realigned.

## 12. Article-to-Lab Pipeline Design Progress

| Gate | Status | Evidence |
|------|--------|----------|
| K8s Domain Proof (4 labs, 3 rounds real human validation) | ✅ COMPLETE | `REAL_HUMAN_COHORT_ROUND2_RESULT_v0.1.md` |
| Small Customer Pilot Preparation Gate | ✅ COMPLETE | `SMALL_CUSTOMER_PILOT_PREPARATION_GATE_v0.1.md` — PREP_READY_WITH_NOTES |
| Small Customer Pilot Execution | 🔴 BLOCKED | `SMALL_CUSTOMER_PILOT_RESULT_v0.1.md` — NO_SUITABLE_SMALL_CUSTOMER (not a technical blocker) |
| **Article-to-Lab Pipeline Design Gate** | ✅ COMPLETE | `ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` — **ARTICLE_TO_LAB_PIPELINE_DESIGN_READY_WITH_NOTES** |
| K8s Article-to-Lab Draft Mode Implementation | ⬜ PENDING | Requires LLM provider + storage/copyright policy decisions (Open Questions N-01, N-02, N-03) |
| Linux Domain Proof | ⬜ PENDING | After K8s Article-to-Lab Draft Mode validated |
| Docker Domain Proof | ⬜ PENDING | After Linux domain |

The pipeline design (Section E of `ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md`) is the canonical reference for the Article-to-Lab platform architecture. All subsequent implementation must follow that design and must not harden into K8s-only.

---

*This document is the authoritative reference for LabGen's structural goal. Any future document that describes the project as a pure K8s learning platform must be corrected to reference this document.*
