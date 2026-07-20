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

## B. Recommended Production Sequence

| Order | Topic | Priority | Runtime-ready | Why this position |
|---|---|---|---|---|
| 0 | Linux Files and Permissions Basics (existing, upgrade) | — | ✅ Yes (just needs article+CTA) | De-risks the funnel mechanics with the least new work; already has 1 external reader pass |
| 1 | chmod 明明改对了，为什么还是 Permission Denied | P0 | ✅ Yes | Highest score (8.15), zero platform work, and a natural sequel to #0 — same "permissions" judgment family, deepens rather than repeats |
| 2 | 团队共享目录里，新文件的属组总是不对 (setgid+sticky) | P0 | ✅ Yes | Second-highest score (7.9), zero platform work, extends the permissions family from single-user to multi-user/team scenarios |
| 3 | 用 find 做一次最小可行的权限安全审计 | P1 | ✅ Yes | Natural "graduation" topic — reader who did #0-2 now has enough judgment to run a real audit; introduces security framing without new runtime needs |
| 4 | 日志文件几个 G，怎么在不打开它的情况下找到最近的错误 | P1 | ⚠️ Needs 1 new verifier type | First topic with a genuinely different judgment skill (log triage, not permissions) — deliberately placed after the permissions arc to diversify, not homogenize, the series; requires `command_exit_code_equals` or `file_content_contains` to be built (verifier work, not runtime work — in scope for a future Sprint, not this planning round) |
| 5 | 明明是"文件不存在"，为什么报的是 Permission Denied（dangling symlink） | P2 | ⚠️ Needs `ln` (small executor addition) | Pairs with #6 as a "links" mini-arc; smallest platform gap among the P2s (one command addition, same sandboxing model, no architecture change) |
| 6 | 用硬链接备份之后，磁盘占用为什么"对不上" | P2 | ⚠️ Needs `ln` (shared gap with #5) | Closes the "links" arc; reuses the same `ln` addition as #5, so the two should be greenlit together if a future Sprint takes on this gap, not separately |

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
