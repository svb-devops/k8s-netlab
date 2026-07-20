# Linux Growth-First Track Foundation — Result v0.1

**Gate**: Linux Growth-First Track Foundation (full task)
**Final Decision**: `LINUX_GROWTH_FIRST_TRACK_FOUNDATION_READY`
**Date**: 2026-07-20
**Executed by**: Claude Code
**New lab created**: NO
**New article created**: NO
**Second reader test executed**: NO (gate removed, not executed — see Track Contract §E.1)
**Second reader account created**: NO
**Production code modified**: NO
**Public allowlist modified**: NO
**Growth analytics platform built**: NO
**Multiple topics merged into one**: NO

---

## A. What This Round Produced

| Document | Purpose |
|---|---|
| `docs/labgen/linux/LINUX_EXISTING_ASSET_AUDIT_v0.1.md` | Ground-truth audit of the existing Linux lab against 8 required questions; classification `upgrade_and_include` |
| `docs/labgen/linux/LINUX_GROWTH_FIRST_TOPIC_RADAR_v0.1.md` | 10 scored candidate topics, live-WebSearch-backed source signals, 2 candidates dropped for weak evidence rather than padded in |
| `docs/labgen/linux/LINUX_GROWTH_SERIES_PLAN_v0.1.md` | 7-entry production sequence (Order 0 upgrade + Orders 1-6 new); 4 topics explicitly deferred with named platform gaps |
| `docs/labgen/linux/LINUX_TRACK_CONTRACT_v0.1.md` | Runtime / fault-injection / verifier / cleanup / publish-order / funnel-instrumentation contract, checked clause-by-clause against real source code |
| `docs/labgen/linux/FIRST_GOLDEN_TOPIC_DECISION_v0.1.md` | Selected `linux-chmod-permission-denied-despite-correct-mode`; systemd explicitly considered and deferred with reasoning |
| `docs/labgen/PROJECT_NORTH_STAR_v0.1.md` (updated §16) | K8s Phase 1 marked `COMPLETE/FROZEN_MAINTENANCE`; Linux track marked `FOUNDATION_READY`; second-reader gate marked `REMOVED_AS_BLOCKING_GATE` |
| `CHANGELOG.md` (updated `[Unreleased]`) | Summary entry for this round |

---

## B. Key Findings (the parts a CEO/CTO reading only this section needs)

1. **The existing Linux lab has never touched the growth funnel.** It is technically sound
   (validated cleanup, 2 real verifier types, 1 passed external reader) but has zero public
   article, zero CTA, zero funnel instrumentation. It is not a "growth asset" today — it is a
   proven technical pilot that needs an article before it counts as one.

2. **The current Linux runtime is a 19-command, filesystem-only sandbox — no root, no
   systemd, no network, no process management, no VM.** This is a real, structural
   constraint, not a maturity gap that closes by itself. It rules out several of the CEO/CTO
   brief's own suggested example topics (systemd, df/du, port conflict) as buildable *this
   round* — they require real infrastructure investment (VM + systemd/network stack, or a
   persistent-process execution model), which the brief itself prohibits building this round.

3. **10 of 12 Track Contract verifier types don't exist yet.** Only 2 topics in the
   recommended 6-topic series (Order 2 and Order 4) need new verifier types before they can be
   built; the rest (Orders 1, 3, 5-6) work with what exists today or a small allowlist
   addition (`ln`).

4. **The First Golden Topic (`linux-chmod-permission-denied-despite-correct-mode`) needs zero
   platform investment** — it was selected specifically because it lets the *funnel model*
   (article → CTA → lab → verifier → cleanup) be proven independently of any runtime risk,
   before committing to topics (like systemd) that would conflate "does the funnel work" with
   "does new infrastructure work."

5. **No growth funnel instrumentation exists at all** beyond a `lab_start_success/failed`
   audit event. Building it is out of scope this round by explicit instruction, but the gap
   (9 funnel stages, 1 partially instrumented) is now named precisely rather than left vague.

---

## C. Final Handoff

```yaml
linux_growth_first_foundation_handoff:
  overall_status: LINUX_GROWTH_FIRST_TRACK_FOUNDATION_READY

  existing_asset:
    lab_id: 6c439064-4cad-4229-addb-36927128d565
    title: Linux Files and Permissions Basics
    current_status: published
    article_status: NO_PUBLIC_ARTICLE_EXISTS (source_article_id is a string with no backing content; /api/articles/art-linux-files-permissions-001 returns 404)
    auto_provisioning: LOCAL_WORKSPACE_ON_SESSION_START (no VM step, near-zero latency vs K8s)
    verifier_quality: REAL_STATE_CHECK (file_exists, file_mode_matches both stat the real sandbox filesystem, not command output)
    cleanup_quality: VERIFIED_IDEMPOTENT_FAIL_CLOSED
    growth_value: HIGH_REUSABLE_INFRA_ZERO_FUNNEL_DATA
    classification: upgrade_and_include
    classification_reason: sound reusable runtime/verifier/cleanup primitives + 1 real external reader pass, but zero article/CTA/funnel presence — not include_as_is, not legacy

  topic_radar:
    candidates_count: 10
    shortlisted_topics:
      - linux-chmod-permission-denied-despite-correct-mode
      - linux-shared-directory-setgid-sticky-bit-wrong-owner
      - linux-find-security-audit-world-writable-suid
      - linux-huge-log-file-triage-without-opening-it
      - linux-dangling-symlink-permission-confusion
      - linux-hardlink-symlink-inode-disk-usage-confusion
      - linux-umask-unexpected-default-permissions
      - linux-disk-full-df-du-mismatch-deleted-open-file
      - linux-systemd-service-failed-to-start
      - linux-address-already-in-use-port-conflict
    p0_count: 2
    p1_count: 2
    p2_count: 6
    evidence_source_types: [live_websearch_this_session, official_vendor_kb, cross_source_blog_convergence, real_bug_reports_across_unrelated_projects]
    unsupported_claims_found: 0

  selected_series:
    - order: 0
      topic: "Linux Files and Permissions Basics (existing, upgrade with article+CTA)"
      priority: series_proof_of_concept
      article_angle: N/A (existing lab content, only article+CTA are new work)
      lab_conversion_trigger: N/A (upgrade only)
    - order: 1
      topic: linux-chmod-permission-denied-despite-correct-mode
      priority: P0
      article_angle: "chmod 显示正确权限，为什么还是 Permission Denied — 按目录树逐层排查"
      lab_conversion_trigger: "5分钟复现这个陷阱，用 stat/find 定位真正的阻断层"
    - order: 2
      topic: linux-shared-directory-setgid-sticky-bit-wrong-owner
      priority: P0
      article_angle: "共享目录新文件属组总是不对 — setgid + sticky bit 的组合判断"
      lab_conversion_trigger: "光设置 setgid 还不够——你的同事就能删你的文件"
    - order: 3
      topic: linux-find-security-audit-world-writable-suid
      priority: P1
      article_angle: "不装任何工具，用 find 做一次最小可行的权限体检"
      lab_conversion_trigger: "你的 find 命令能找到我藏起来的三个问题吗？"
    - order: 4
      topic: linux-huge-log-file-triage-without-opening-it
      priority: P1
      article_angle: "日志几个 G，你的第一反应不该是打开它"
      lab_conversion_trigger: "3分钟内从模拟日志里精确定位最后5次真实报错"
    - order: 5
      topic: linux-dangling-symlink-permission-confusion
      priority: P2
      article_angle: "明明是文件不存在，为什么报的是 Permission Denied"
      lab_conversion_trigger: deferred pending `ln` allowlist addition
    - order: 6
      topic: linux-hardlink-symlink-inode-disk-usage-confusion
      priority: P2
      article_angle: "用硬链接备份之后，磁盘占用为什么对不上"
      lab_conversion_trigger: deferred pending `ln` allowlist addition (shared gap with order 5)

  track_contract:
    runtime_frozen: "local sandboxed directory, no VM, no root, no systemd, no network — 19-command filesystem/permissions-only allowlist; NOT changed this round"
    sudo_boundary: "sudo/su/doas/chroot explicitly denied; no unrestricted root ever granted"
    verifier_model: "real filesystem state checks only (file_exists, file_mode_matches exist); 10 of 12 contract-baseline types are missing and named per-topic in the Track Contract"
    cleanup_model: "path-validated, residual-scanned, idempotent, fail-closed; fully compliant with the contract as written"
    publish_gate: "static validation + real rehearsal + non-admin smoke + owner dogfood + cleanup_verified + zero BLOCKER/HIGH + article-lab verified together"
    second_reader_gate_removed: true

  first_golden_topic:
    selected: linux-chmod-permission-denied-despite-correct-mode
    score: 8.15/10
    title_direction: "chmod 明明改对了，为什么还是 Permission Denied？"
    lab_scenario: "seeded script with correct file mode but a parent directory missing execute permission; learner must diagnose via stat/find/ls without being told which layer blocks it"
    required_verifiers: [file_exists, file_mode_matches]
    missing_assets: none
    next_sprint_scope: "Lab Design Brief -> Lab Contract -> build lab draft -> real rehearsal -> non-admin smoke -> owner dogfood -> Official Site Article -> Minimal Publish. No other Series Plan order starts until this ships."

  growth_funnel:
    metrics_defined: [article_page_view, cta_click, lab_start, provisioning_success, LAB_ACTIVE, first_verifier_pass, lab_completion, cleanup_success, next_article_click]
    existing_tracking: "lab_start_success / lab_start_failed audit events only"
    missing_tracking: "8 of 9 funnel stages have zero instrumentation; LAB_ACTIVE and lab_completion exist as session-state fields but are not emitted as discrete analytics events"

  production:
    k8s_unchanged: true
    linux_existing_lab_unchanged: true
    public_exposure_unchanged: true
    health: "healthy (proxmox connected, labgen ok); sessions.status=degraded is a pre-existing, unrelated zombie-draft-count warning, not caused by this task and not remediated by this task per explicit instruction not to fix incidental issues"

  issues:
    blocker: []
    high: []
    medium: []
    low:
      - "10 of 12 Track Contract verifier types do not exist yet; 2 of the 6 series topics (Order 2, Order 4) are blocked on new verifier work before they can be built (tracked, not built this round)"
      - "ln is absent from the command allowlist (not denied, just missing); Orders 5-6 need this small addition before they can be built"
      - "Growth funnel has 8 of 9 stages uninstrumented; tracked in Track Contract §F, no code written this round"
      - "Zombie draft count in health check (10, pre-existing, unrelated to this task, not remediated per explicit instruction)"

  docs:
    - docs/labgen/linux/LINUX_EXISTING_ASSET_AUDIT_v0.1.md
    - docs/labgen/linux/LINUX_GROWTH_FIRST_TOPIC_RADAR_v0.1.md
    - docs/labgen/linux/LINUX_GROWTH_SERIES_PLAN_v0.1.md
    - docs/labgen/linux/LINUX_TRACK_CONTRACT_v0.1.md
    - docs/labgen/linux/FIRST_GOLDEN_TOPIC_DECISION_v0.1.md
    - docs/labgen/linux/LINUX_GROWTH_FIRST_TRACK_FOUNDATION_RESULT_v0.1.md (this document)
    - docs/labgen/PROJECT_NORTH_STAR_v0.1.md (updated section 16)
    - CHANGELOG.md (updated [Unreleased])
  commits: "pending — this document is written before the commit that includes it; see repo HEAD after this task's commit for the exact hash"
  pushed_to_github: "pending — will follow this project's standard commit+push workflow (docs-only change, still runs through pre-commit/pre-push hooks)"
  git_status: "clean prior to this task's own doc additions; no unrelated uncommitted changes were present or introduced"
  recommended_next_step: "User/CEO reviews the 5 planning documents in docs/labgen/linux/ and either (a) approves Sprint scope = First Golden Topic production only, or (b) redirects topic/sequencing choices before that Sprint starts. No further Linux track action should be taken by Claude Code until this review happens."
```

---

## D. Completion Check

| Check | Result |
|---|---|
| K8s labs unchanged | ✅ (verified via live API + local data file) |
| K8s articles unchanged | ✅ 7 public articles, count unchanged |
| Existing Linux published lab unchanged | ✅ `publish_status=published`, no field modified |
| Public exposure unchanged | ✅ No allowlist, no route, no CTA flag touched |
| Health healthy | ✅ `{"status":"healthy",...}` — pre-existing zombie-draft warning noted, not touched |
| Git clean (aside from this task's own doc additions) | ✅ Only `docs/labgen/linux/` (new), `docs/labgen/PROJECT_NORTH_STAR_v0.1.md` (updated), `CHANGELOG.md` (updated), plus harness-managed `.claude/settings.json` permission entries from tool approvals this session |
| No new tests added to chase a coverage number | ✅ None added — this is a docs-only round |
| No proactive code fix for discovered issues | ✅ Zombie-draft-count warning and the `ln`/verifier-type gaps are recorded as backlog (§Issues), not fixed |

---

## E. Anti-Bullshit Self-Audit

| Check | Result |
|---|---|
| No TODO/FIXME in any produced document | ✅ |
| No placeholder-as-success | ✅ |
| Second reader test NOT run | ✅ |
| Second reader account NOT created | ✅ |
| No new lab created | ✅ |
| No new article created or published | ✅ |
| No public allowlist modified | ✅ |
| No production code modified | ✅ |
| No analytics platform built | ✅ |
| No runtime overhaul executed | ✅ |
| Multiple topics NOT merged into one | ✅ — every candidate on the Radar is single-root-cause |
| Weak-evidence candidates dropped, not padded in to hit a count | ✅ (§Radar D) |
| systemd (brief's own suggested example) explicitly evaluated and reasoned about, not silently ignored or silently rubber-stamped | ✅ (`FIRST_GOLDEN_TOPIC_DECISION_v0.1.md` §B) |
| All "✅ Compliant" Track Contract claims traced to source code read during the audit | ✅ |
| K8s Phase 1 status accurately reflects existing closure docs (not re-declared complete without checking) | ✅ verified against `PHASE1_KUBERNETES_SERIES_CLOSURE_v1.0.md` |
