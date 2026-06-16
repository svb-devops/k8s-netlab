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

## 4. Current Domain Proof

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

## 5. Future Domains

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

## 6. Architecture Principle

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

## 7. What We Must Not Become

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

## 8. LLM Positioning

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

## 9. Product Stage Definition

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

## 10. Decision Rule

Every subsequent task must ask:

- Does this step shrink the distance between "read an article" and "run a live verification"?
- Does this step strengthen Article-to-Lab capability?
- Does this step preserve future Linux / multi-domain migration capability?
- Does this step still support "读完即练，结果说话"?
- Does this step merely pile on more fixed K8s coursework?
- Does this step introduce K8s-only hardcoding that cannot migrate?
- Does this step weaken cleanup / credential / safety / verifier boundaries?

If the answer reveals drift, the task must be paused and realigned.

---

*This document is the authoritative reference for LabGen's structural goal. Any future document that describes the project as a pure K8s learning platform must be corrected to reference this document.*
