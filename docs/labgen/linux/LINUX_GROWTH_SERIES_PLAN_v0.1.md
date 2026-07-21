# Linux Growth Series Plan — v0.1

**Gate**: Linux Growth-First Track Foundation — Section 三
**Date**: 2026-07-20
**Executed by**: Claude Code
**Input**: `LINUX_GROWTH_FIRST_TOPIC_RADAR_v0.1.md` (10 scored candidates) + `LINUX_EXISTING_ASSET_AUDIT_v0.1.md` (existing lab classification)

---

## A. Series Composition Decision

The brief targets **6 高价值 Linux 主题**. This plan resolves the one open question the audit
deferred: where does the existing lab (`6c439064`, "Linux Files and Permissions Basics",
classified `upgrade_and_include`) sit relative to the 6 new topics?

**Decision: it is Series Order 0 — the series' proof-of-concept entry, upgraded, not one of the
6 new productions.** It already has validated runtime/verifier/cleanup infrastructure and one
independent external reader pass; the only work is writing the article it never had and wiring
a CTA. This is materially less work than any of the 6 new topics (which need lab content built
from zero) and should ship first precisely because it de-risks the funnel mechanics (article →
CTA → lab_start → LAB_ACTIVE → verifier PASS → cleanup) before the series commits real
production time to brand-new content.

This decision is a recommendation for Sprint sequencing, not an authorization to execute it —
per the brief's own prohibition, **no new lab dev and no new article happens in this round**.

---

## A.1 Correction (2026-07-20, Linux Golden Lab #1 brief)

A follow-up CEO/CTO brief narrowed this plan's scope and corrected its framing before any of
Orders 1-6 could start production. Both corrections below supersede §A/§B where they conflict.

**Existing lab role, corrected**: `6c439064` ("Linux Files and Permissions Basics") is
reclassified from "Series Order 0, series proof-of-concept" to **prerequisite / legacy
onboarding asset — explicitly NOT one of the 6 high-value growth topics, and not scheduled for
an article/CTA upgrade this round.** §A's framing of it as "de-risking the funnel mechanics
first" is withdrawn — that framing implied committing article-writing effort to it this round,
which this correction rules out. Its `upgrade_and_include` classification (Existing Asset
Audit) stands; only its *sequencing role* changes.

**Series binding, corrected**: only **Order 1 (`linux-chmod-permission-denied-despite-correct-mode`,
now "Golden Topic #1") is formally bound.** Orders 2-6 (originally: shared-directory
setgid/sticky bit, find security audit, log triage, dangling symlink, hardlink/inode) are
marked **provisional** — real rehearsal data from Golden Topic #1, plus a future runtime
investment decision (see Track Contract §A.1's new Runtime Profile split), may reorder or
replace them. **This document does not claim a fully bound 6-topic roadmap.** That claim was
implicit in §B's table before this correction and is retracted here.

---

## B. Recommended Production Sequence (Order 1 bound; Orders 2-6 provisional per §A.1)

| Order | Topic | Priority | Runtime-ready | Binding status | Why this position |
|---|---|---|---|---|---|
| — | Linux Files and Permissions Basics (existing) | — | — | **Prerequisite/legacy asset — not in the 6-topic series** (§A.1) | Reusable infra proof point; article/CTA upgrade explicitly deferred, not scheduled |
| 1 | chmod 明明改对了，为什么还是 Permission Denied ("Golden Topic #1") | P0 | ⚠️ **See feasibility gate — see `LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED` result** | **Bound** | Highest score (8.15) — bound as the series' first production, pending the hard feasibility gate outcome |
| 2 | 团队共享目录里，新文件的属组总是不对 (setgid+sticky) | P0 | ✅ Yes | Provisional (§A.1) | Second-highest score (7.9); resequencing depends on Golden Topic #1's real rehearsal data |
| 3 | 用 find 做一次最小可行的权限安全审计 | P1 | ✅ Yes | Provisional (§A.1) | Natural "graduation" topic if the permissions arc proceeds |
| 4 | 日志文件几个 G，怎么在不打开它的情况下找到最近的错误 | P1 | ⚠️ Needs 1 new verifier type | Provisional (§A.1) | Different judgment skill; needs verifier work regardless of Order 1's outcome |
| 5 | 明明是"文件不存在"，为什么报的是 Permission Denied（dangling symlink） | P2 | ⚠️ Needs `ln` (small executor addition) | Provisional (§A.1) | Pairs with #6 as a "links" mini-arc |
| 6 | 用硬链接备份之后，磁盘占用为什么"对不上" | P2 | ⚠️ Needs `ln` (shared gap with #5) | Provisional (§A.1) | Closes the "links" arc |

**This is 7 entries (0-6) covering the "6 高价值主题" target** — Order 0 is the upgrade of what
already exists, Orders 1-6 are the six new productions the brief asks for.

---

## C. Explicitly Deferred (not part of this series, and why)

| Topic | Radar score | Why deferred |
|---|---|---|
| systemd 服务启动失败排查 | 7.3 (3rd highest) | Requires a real systemd-capable VM — the same class of infrastructure as the K8s domain, explicitly out of scope for "不做 Linux runtime 大改造" this round. This is the CEO/CTO brief's own suggested example topic; deferring it is not a disagreement with its value (it scores well on demand), it is a statement that shipping it requires a runtime-investment decision this document is not authorized to make. |
| df 与 du 对不上（deleted-but-open file） | 6.75 | Requires a persistent background process the current one-shot executor model cannot run, plus `df`/`du`/`lsof`. Same class of gap as systemd — process model change, not allowlist tweak. |
| Address already in use（端口冲突） | 5.75 | Requires a real network stack + VM. Same class of gap. |
| umask 默认权限不符合预期 | 5.7 | `umask` is a shell builtin with no standalone binary; the executor's no-shell design (a deliberate security boundary, not an oversight) has no clean path to demonstrate it without either shelling out or hand-simulating a builtin. |

**Pattern**: all four deferred topics need infrastructure investment beyond an allowlist
addition — either a VM+systemd/network stack, or a persistent-process execution model, or a
shell escape hatch. None of these are "quick fixes"; each is a real architecture decision that
belongs in a future Track Contract revision or a dedicated infra Sprint, explicitly not this
planning round.

**Recommendation for a future Sprint (not decided here)**: if the 6-topic series (Order 0-6)
proves the funnel model works (real CTA clicks, real completions, real second-topic
return-clicks — see Growth Funnel section of the Track Contract), the systemd topic is the
strongest candidate to justify a VM-based Linux runtime investment, given it scored highest on
raw demand (9/10) of anything on the radar. That is a build-vs-defer call for whoever owns the
next infra Sprint, not a decision this planning document makes.

---

## D. Series-Level Coherence Check

- **No two topics share the same root cause path**: #0-2 are permissions (file mode / parent-dir
  exec / group inheritance / delete-protection — each a distinct sub-mechanism), #3 is a
  synthesis/audit topic building on #0-2, #4 is a distinct judgment skill (log triage), #5-6 are
  a distinct judgment skill (linking/inode semantics). No homogenization.
- **Learning curve is intentionally graduated**: single-user file mode (#1) → multi-user
  directory semantics (#2) → security-audit synthesis of both (#3) → new skill domain (#4) →
  new skill domain (#5-6). This mirrors the K8s series' own stated design principle (see
  `PHASE1_SERIES_ALIGNMENT_v0.1.md`: each new lab shares a "diagnostic mental model" with
  its predecessor while introducing exactly one new judgment branch).
- **P0 count constraint honored**: exactly 2 P0s in the whole radar, both in Orders 1-2, matches
  the Topic Radar's own rule (§Radar C).

---

## E. Anti-Fabrication Self-Check

| Check | Result |
|---|---|
| Series composition traces to Radar scores, not preference | ✅ Table B directly cites Radar totals |
| Existing-asset placement decision made here (audit deferred it), not silently assumed | ✅ §A |
| Deferred topics named with concrete reasons, not silently dropped | ✅ §C |
| No claim that any of Orders 1-6 have been built or started | ✅ — this is a plan document only |
| No runtime overhaul recommended for this round | ✅ — deferred topics explicitly flagged as future-Sprint decisions |
