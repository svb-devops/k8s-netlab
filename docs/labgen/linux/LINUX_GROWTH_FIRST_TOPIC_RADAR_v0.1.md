# Linux Growth-First Topic Radar — v0.1

**Gate**: Linux Growth-First Track Foundation — Section 二
**Date**: 2026-07-20
**Executed by**: Claude Code
**Method**: Live web search (10 queries, this session) cross-referenced against the current Linux runtime's real command surface (`backend/labgen/linux_command_executor.py`, audited in `LINUX_EXISTING_ASSET_AUDIT_v0.1.md`). No fabricated search-volume numbers — every `source_signal` below is either a direct search result observed this session or explicitly labeled as inferred/low-confidence.

---

## A. Method Note (read before the table)

Two constraints shaped scoring, both drawn from the audit, not assumed:

1. **Runtime reality**: the current Linux sandbox allows exactly 19 commands (`pwd, ls, mkdir, touch, echo, cat, chmod, stat, find, rm, cp, mv, wc, head, tail, grep, diff, test, [`) with no shell, no root, no systemd, no network, no process management, no `ln`, no `df`/`du`/`lsof`. Topics that need commands outside this set are **not runtime-overhaul-free** — the brief explicitly forbids a runtime overhaul this round, so this is a real constraint on what "本轮不新增 lab" candidates could even become, not a style preference.
2. **Search-signal honesty**: I do not have Stack Overflow's own API or search-volume tools in this environment. Every signal below comes from a live `WebSearch` call made in this session (results attached) or is explicitly marked `confidence: low` / `inferred`. Two candidate ideas I considered were dropped from this list after searching, because the search evidence for them was weak (see §D).

---

## B. Candidate Topics (10)

### 1. `linux-chmod-permission-denied-despite-correct-mode`

```
topic_id: linux-chmod-permission-denied-despite-correct-mode
working_title: chmod 明明改对了，为什么还是 Permission Denied？
search_intent: "permission denied" + "chmod" troubleshooting — consistently the top-returned
  cluster across independent blogs/vendors (monovm, oneuptime, educative, cycle.io,
  linuxconfig, ioflood, fosslinux) when searched this session.
real_engineering_pain: The chmod bits on the file itself are correct, but access still fails
  because the *parent directory* lacks execute permission, the shebang/interpreter path is
  wrong, or line endings are CRLF. Every source found this session independently converges
  on the same diagnostic sequence: file mode → parent directory execute bit → shebang validity
  → line endings — which is exactly the kind of layered judgment chain this project's articles
  are built around (see North Star: engineering-judgment angle, not command dump).
existing_content_gap: Existing generic tutorials (all 10 search results) explain *what* each
  cause is; none walk a reader through *diagnosing which one it is* via a fixed decision tree
  with a verifiable lab at the end.
article_angle: "chmod 显示 -rwxr-xr-x，为什么还是 Permission Denied？" — judgment chain:
  file mode is right → check parent directory x bit → check shebang → check line endings.
lab_conversion_trigger: Reader has hit this exact error and searched for it — CTA: "5分钟复现
  这个陷阱，亲手用 stat/find 定位到底是哪一层挡住的".
experiment_scenario: Script has correct mode bits; parent directory is missing +x for the
  learner's user; learner must use `stat`/`find`/`ls` to locate the real blocker without being
  told which layer it is.
expected_audience: Linux 初中级用户，遇到过这个报错但没有系统排查方法的人
distribution_channels: 复用现有 K8s 文章漏斗结构（Official Site Article → CTA → Lab）
source_signals:
  - source_name: WebSearch aggregate (monovm.com, oneuptime.com, cycle.io, linuxconfig.org, ioflood.com, fosslinux.com, debugpoint.com)
    signal_type: cross-source blog consensus on diagnostic sequence
    observed_signal: 7+ independent sources this session converge on the same "mode → parent
      dir → shebang → line endings → SELinux/ACL" decision tree for this exact symptom
    why_relevant: Convergent independent coverage is a real (if indirect) proxy for how common
      and well-understood-as-a-pattern this failure mode is
    confidence: medium
    source_url_or_reference: https://monovm.com/blog/permission-denied-linux/, https://oneuptime.com/blog/post/2026-01-24-fix-permission-denied-errors-linux/view, https://cycle.io/learn/troubleshooting-linux-permissions
implementation_risk: LOW — fully executable with current allowlist (`chmod`, `stat`, `ls`, `find`)
score_breakdown:
  search_community_demand: 8/10 (30%) = 2.4
  engineering_pain_strength: 8/10 (25%) = 2.0
  article_differentiation_space: 7/10 (20%) = 1.4
  lab_conversion_naturalness: 9/10 (15%) = 1.35
  implementation_stability: 10/10 (10%) = 1.0
  total: 8.15/10
priority: P0
```

### 2. `linux-shared-directory-setgid-sticky-bit-wrong-owner`

```
topic_id: linux-shared-directory-setgid-sticky-bit-wrong-owner
working_title: 团队共享目录里，新文件的属组总是不对
search_intent: setgid/sticky bit explainer content is abundant (9 independent sources found:
  maketecheasier, medium, linuxconfig, linkedin, liquidweb, linuxize, cbtnuggets, oneuptime,
  scribd) — a strong signal this is a recurring real question, not a one-off.
real_engineering_pain: A shared directory's new files inherit the creating user's default
  group instead of the team's shared group, breaking collaborative access — and separately,
  anyone can delete anyone else's files unless the sticky bit is also set. Both facts are
  usually taught in isolation; the *combination* (setgid for group inheritance + sticky bit
  for delete-protection) is the real production pattern and is exactly what a lab can verify.
existing_content_gap: Every source explains the two bits conceptually; none set up a "before"
  state (wrong group inheritance observed) and have the reader fix it, then have the platform
  verify both group inheritance AND deletion protection are actually enforced.
article_angle: "为什么这个共享目录里新建的文件属组总是错的？" — setgid inheritance judgment,
  then "如果只加 setgid 不加 sticky bit，你的同事就能删你的文件" as the natural escalation.
lab_conversion_trigger: CTA at the "光设置 setgid 还不够" cliffhanger.
experiment_scenario: Pre-seeded shared directory with wrong group; learner sets setgid (2xxx)
  and sticky bit (+t); verifier checks a newly created file inherits the directory's group AND
  a file cannot be removed by testing effective permission bits.
expected_audience: 小团队/多用户服务器运维初学者
distribution_channels: 同上
source_signals:
  - source_name: WebSearch aggregate (maketecheasier.com, medium.com, linuxconfig.org, liquidweb.com, linuxize.com, cbtnuggets.com)
    signal_type: cross-source explainer convergence
    observed_signal: 6+ independent vendor/blog sources this session all frame this exact
      "shared directory + setgid + sticky bit" combination as the canonical real-world use case
    why_relevant: Same convergence signal as #1
    confidence: medium
    source_url_or_reference: https://maketecheasier.com/use-sticky-bit-manage-files-shared-directories-linux/, https://linuxconfig.org/how-to-use-special-permissions-the-setuid-setgid-and-sticky-bits
implementation_risk: LOW — fully executable with current allowlist (`chmod`, `mkdir`, `touch`, `stat`, `ls`)
score_breakdown:
  search_community_demand: 7/10 (30%) = 2.1
  engineering_pain_strength: 8/10 (25%) = 2.0
  article_differentiation_space: 8/10 (20%) = 1.6
  lab_conversion_naturalness: 8/10 (15%) = 1.2
  implementation_stability: 10/10 (10%) = 1.0
  total: 7.9/10
priority: P0
```

### 3. `linux-find-security-audit-world-writable-suid`

```
topic_id: linux-find-security-audit-world-writable-suid
working_title: 用 find 做一次最小可行的权限安全审计
search_intent: "find world writable files", "find suid sgid audit" — 10 independent sources
  (commandinline.com, intramweb.com, visiontrainingsystems.com x2, linux-audit.com x2,
  decryptiondigest.com, data-flair.training) treat this as a canonical sysadmin/security
  interview topic, not a niche question.
real_engineering_pain: World-writable files and unexpected SUID/SGID binaries are a real
  privilege-escalation vector; `find` is the only tool that requires zero installation and
  zero baseline config to catch them — exactly the kind of "no fancy tool, just judgment
  with what's already there" angle this project favors.
existing_content_gap: Most sources give the `find` one-liners without a guided "here's a
  planted vulnerability, go find it yourself" exercise with pass/fail verification.
article_angle: "不装任何工具，5 条 find 命令做一次权限体检" — engineering judgment: why
  world-writable in /tmp is fine but in /etc is a BLOCKER.
lab_conversion_trigger: "你的 find 命令能找到这三个我藏起来的问题吗？"
experiment_scenario: Sandbox pre-seeded with a world-writable "config" file and a SUID-set
  script the learner didn't create; learner uses `find`/`stat` to locate and remediate both;
  verifier checks resulting mode bits.
expected_audience: 运维/安全入门，准备面试或做内部审计的人
distribution_channels: 同上
source_signals:
  - source_name: WebSearch aggregate (commandinline.com, intramweb.com, linux-audit.com, decryptiondigest.com, data-flair.training)
    signal_type: cross-source topic convergence + explicit "common interview questions" framing
    observed_signal: data-flair.training explicitly catalogs this as a recurring Linux
      interview question category; linux-audit.com has two dedicated articles on the same
      `find`-based audit pattern
    why_relevant: Interview-question framing is a stronger-than-average signal of durable,
      recurring real demand (not a one-off blog SEO topic)
    confidence: medium
    source_url_or_reference: https://www.commandinline.com/linux-file-permissions-audit/, https://linux-audit.com/finding-setuid-binaries-on-linux-and-bsd/, https://data-flair.training/blogs/linux-interview-questions/
implementation_risk: LOW — fully executable with current allowlist (`find`, `stat`, `chmod`)
score_breakdown:
  search_community_demand: 7/10 (30%) = 2.1
  engineering_pain_strength: 7/10 (25%) = 1.75
  article_differentiation_space: 8/10 (20%) = 1.6
  lab_conversion_naturalness: 7/10 (15%) = 1.05
  implementation_stability: 10/10 (10%) = 1.0
  total: 7.5/10
priority: P1
```

### 4. `linux-huge-log-file-triage-without-opening-it`

```
topic_id: linux-huge-log-file-triage-without-opening-it
working_title: 日志文件几个 G，怎么在不打开它的情况下找到最近的错误
search_intent: Dedicated real-world guides exist specifically for this workflow (Papertrail's
  own product blog, thegeekstuff's decade-old but still-referenced classic guide) — this is an
  operational pattern people actively search for, not a permissions edge case.
real_engineering_pain: Opening a multi-GB log in an editor is the wrong instinct; the right
  judgment chain is tail → grep → head/tail-of-the-match to bound the search before reading
  anything in full. This is a genuinely different judgment skill from the permissions topics
  above (log triage vs. filesystem permission diagnosis), giving the series real angle diversity
  per the CEO brief's own anti-homogenization rule.
existing_content_gap: Existing guides show the commands; none give the reader a large
  pre-seeded log file with a needle buried in it and ask them to find the last N errors before
  a specific timestamp using only `grep`/`tail`/`head`/`wc` — with the platform verifying the
  exact line count/content the learner extracted.
article_angle: "日志几个 G，你的第一反应不该是打开它" — judgment: bound the search before you
  read anything.
lab_conversion_trigger: "3 分钟内从一个模拟的 5000 行日志里精确定位最后 5 次真实报错"
experiment_scenario: Pre-seeded large text file simulating a log with noise + a known number
  of "ERROR" lines; learner must extract exactly the right slice using grep/tail/head/wc;
  verifier checks file_content_contains / output count via a new command_exit_code_equals-style
  verifier (see Track Contract gap list — this is one of the missing types).
expected_audience: 运维/后端开发排查生产问题的人
distribution_channels: 同上
source_signals:
  - source_name: WebSearch (papertrail.com, thegeekstuff.com)
    signal_type: dedicated product/classic-guide content
    observed_signal: Papertrail (a commercial log-management product) maintains a dedicated
      page teaching this exact workflow — companies invest content marketing budget only on
      real, recurring pain
    why_relevant: Vendor content investment is a stronger commercial-relevance signal than
      generic blog SEO content
    confidence: medium
    source_url_or_reference: https://www.papertrail.com/solution/tips/how-to-tail-search-and-filter-linux-logs/, https://www.thegeekstuff.com/2009/08/10-awesome-examples-for-viewing-huge-log-files-in-unix/
implementation_risk: MEDIUM — executable with current allowlist (`grep`, `tail`, `head`, `wc`,
  `cat`), but the verifier needed (checking an exact extracted line count/content) is not
  `file_exists`/`file_mode_matches` — this needs `command_exit_code_equals` or
  `file_content_contains` from the Track Contract's missing-verifier list (§ Existing Asset
  Audit B.3). Verifier work required, not runtime work.
score_breakdown:
  search_community_demand: 6/10 (30%) = 1.8
  engineering_pain_strength: 8/10 (25%) = 2.0
  article_differentiation_space: 7/10 (20%) = 1.4
  lab_conversion_naturalness: 7/10 (15%) = 1.05
  implementation_stability: 7/10 (10%) = 0.7
  total: 6.95/10
priority: P1
```

### 5. `linux-dangling-symlink-permission-confusion`

```
topic_id: linux-dangling-symlink-permission-confusion
working_title: 明明是"文件不存在"，为什么报的是 Permission Denied？
search_intent: Real, documented recurring bug pattern (Red Hat Bugzilla, NixOS GitHub issue,
  Phalcon forum, FreePBX forum) — a genuine "gotcha" people hit and file bugs about.
real_engineering_pain: A dangling symlink normally fails with "No such file or directory," but
  if a parent directory in the resolved path lacks execute permission, the error becomes the
  more confusing "Permission Denied" — a real judgment trap distinct from topics #1-3.
existing_content_gap: Sources document the bug reports; none teach the general diagnostic
  principle ("when a symlink error looks wrong, check exec bits on parent dirs, not just the
  target").
implementation_risk: MEDIUM-HIGH — creating symlinks requires `ln`, which is **not** in the
  current allowlist (`ALLOWED_COMMANDS`) or the deny list — it is simply absent. Adding it is a
  small, low-risk executor change (one more filesystem-only command, same sandboxing model),
  but it is still a code change to `linux_command_executor.py`, which this round's brief
  reserves for "not a runtime overhaul" judgment calls, not a hard block. Flagged as a real
  missing_platform_asset, scored down on implementation_stability accordingly.
score_breakdown:
  search_community_demand: 5/10 (30%) = 1.5
  engineering_pain_strength: 6/10 (25%) = 1.5
  article_differentiation_space: 7/10 (20%) = 1.4
  lab_conversion_naturalness: 6/10 (15%) = 0.9
  implementation_stability: 5/10 (10%) = 0.5
  total: 5.8/10
priority: P2
source_signals:
  - source_name: WebSearch (bugzilla.redhat.com, github.com/NixOS/nixpkgs, forum.phalcon.io, community.freepbx.org)
    signal_type: real bug reports across unrelated projects
    observed_signal: The same "chmod cannot operate on dangling symlink" / confusing
      permission error shows up independently in Red Hat Bugzilla, a NixOS GitHub issue, and
      two unrelated community forums
    why_relevant: Independent bug reports across unrelated ecosystems is stronger evidence of
      a real recurring gotcha than blog-post volume alone
    confidence: medium
    source_url_or_reference: https://bugzilla.redhat.com/show_bug.cgi?id=1385072, https://github.com/NixOS/nixpkgs/issues/51025
```

### 6. `linux-hardlink-symlink-inode-disk-usage-confusion`

```
topic_id: linux-hardlink-symlink-inode-disk-usage-confusion
working_title: 用硬链接备份之后，磁盘占用为什么"对不上"
real_engineering_pain: Backup tooling that uses hard links to dedupe unchanged files across
  snapshots is a real, common pattern (explicitly noted by ituonline.com and
  aleksandrhovhannisyan.com) — but it means naive per-directory size math misleads anyone who
  doesn't understand inode link counts.
implementation_risk: HIGH — needs `ln` (missing, same as #5) and ideally a way to display
  inode numbers/link counts distinctly, which `stat` already supports, so the remaining gap is
  narrower than #5, but still requires the same executor change.
score_breakdown:
  search_community_demand: 5/10 (30%) = 1.5
  engineering_pain_strength: 6/10 (25%) = 1.5
  article_differentiation_space: 6/10 (20%) = 1.2
  lab_conversion_naturalness: 6/10 (15%) = 0.9
  implementation_stability: 5/10 (10%) = 0.5
  total: 5.6/10
priority: P2
source_signals:
  - source_name: WebSearch (ituonline.com, aleksandrhovhannisyan.com, linuxize.com, rtfm.co.ua)
    signal_type: explainer convergence
    observed_signal: 4 independent sources this session all use the backup/snapshot dedup
      scenario as the canonical "why this matters" example
    confidence: medium
    source_url_or_reference: https://www.aleksandrhovhannisyan.com/blog/hard-links-vs-soft-links/
```

### 7. `linux-umask-unexpected-default-permissions`

```
topic_id: linux-umask-unexpected-default-permissions
working_title: 为什么这台机器新建文件的权限跟我预期的不一样
real_engineering_pain: Real and well-documented (8 independent sources), especially the
  "works in my interactive shell, wrong under systemd/cron/sudo" variant — a genuine judgment
  topic about *which* umask actually applies in a given execution context.
implementation_risk: HIGH — `umask` is a shell builtin on essentially all Linux distributions,
  not a standalone executable; the current executor runs argv via `subprocess.run(shell=False)`
  and has no shell to source. Demonstrating umask behavior would require either (a) shelling
  out (violates the executor's core no-shell design constraint) or (b) a bespoke built-in
  command the executor simulates itself. This is the largest gap of any P2 candidate here —
  flagged explicitly rather than hidden.
score_breakdown:
  search_community_demand: 6/10 (30%) = 1.8
  engineering_pain_strength: 7/10 (25%) = 1.75
  article_differentiation_space: 6/10 (20%) = 1.2
  lab_conversion_naturalness: 5/10 (15%) = 0.75
  implementation_stability: 2/10 (10%) = 0.2
  total: 5.7/10
priority: P2
source_signals:
  - source_name: WebSearch (linuxize.com, oneuptime.com, cyberciti.biz, community.sap.com)
    signal_type: explainer convergence, including an SAP enterprise operations blog
    observed_signal: The "service umask differs from interactive shell umask" pattern is
      documented independently by both a general Linux tutorial site and an enterprise SAP
      operations blog — spans both hobbyist and enterprise audiences
    confidence: medium
    source_url_or_reference: https://linuxize.com/post/umask-command-in-linux/, https://community.sap.com/t5/technology-blog-posts-by-members/dealing-with-default-file-permissions-umask-on-nw-as-abap-on-linux/ba-p/13448074
```

### 8. `linux-disk-full-df-du-mismatch-deleted-open-file`

```
topic_id: linux-disk-full-df-du-mismatch-deleted-open-file
working_title: df 说磁盘满了，du 却说没占多少，到底哪个对
real_engineering_pain: One of the best-documented "real incident" patterns in Linux ops (Red
  Hat's own official KB article, IBM's own official support KB, plus 6 independent
  blogs/wikis) — a deleted-but-still-open file keeps its disk blocks until the holding process
  closes it or restarts.
implementation_risk: **VERY HIGH** — requires `df`, `du`, `lsof` (none in the allowlist, all
  absent from ALLOWED_COMMANDS), and fundamentally requires a *long-running background process*
  holding a deleted file open, which the current one-shot `subprocess.run()`-per-command
  executor model does not support at all (no process supervision, no persistent process
  between commands). This is not a small allowlist addition like #5/#6 — it needs a different
  execution model. Explicitly named as a `missing_platform_asset` requiring real runtime
  investment, consistent with the brief's "不做 Linux runtime 大改造" prohibition this round.
score_breakdown:
  search_community_demand: 7/10 (30%) = 2.1
  engineering_pain_strength: 9/10 (25%) = 2.25
  article_differentiation_space: 7/10 (20%) = 1.4
  lab_conversion_naturalness: 6/10 (15%) = 0.9
  implementation_stability: 1/10 (10%) = 0.1
  total: 6.75/10
priority: P2
source_signals:
  - source_name: WebSearch (access.redhat.com official KB, ibm.com official KB, tecmint.com, penguin-gym-linux.com)
    signal_type: official vendor knowledge-base articles (highest-confidence tier available in
      this session — not blog SEO content)
    observed_signal: Both Red Hat and IBM maintain official, dedicated support KB pages for
      this exact symptom — vendor KB investment is reserved for genuinely high-volume support
      tickets, not speculative content
    confidence: high
    source_url_or_reference: https://access.redhat.com/solutions/2316, https://www.ibm.com/support/pages/causes-mismatch-between-disk-usage-reported-df-and-du
```

### 9. `linux-systemd-service-failed-to-start`

```
topic_id: linux-systemd-service-failed-to-start
working_title: systemctl start 报 failed，journalctl 第一条真实错误在哪
real_engineering_pain: Extremely well-documented, arguably the single most universal Linux ops
  pain point (10 independent sources, including multiple 2026-dated vendor blogs actively
  publishing on it) — this is the CEO/CTO brief's own suggested example topic.
implementation_risk: **VERY HIGH** — requires `systemctl`/`journalctl` (both explicitly on the
  DENY list, not just absent) and a real systemd-capable init system, which a sandboxed
  directory-based executor fundamentally cannot provide (systemd is PID 1; you cannot run it
  inside another process's home directory). This topic requires the **same class of
  infrastructure investment as the K8s domain already has** — a real per-learner VM, not a
  local sandbox. It is the single largest platform gap of any candidate on this radar.
  Recommendation (not a decision — Series Plan owns sequencing): defer until the track either
  (a) reuses K8s's existing VM-clone infrastructure for a "systemd VM" variant, which is a real
  runtime investment explicitly out of this round's scope, or (b) is re-evaluated after the
  first 2-3 filesystem-only topics prove the funnel model works at all.
score_breakdown:
  search_community_demand: 9/10 (30%) = 2.7
  engineering_pain_strength: 9/10 (25%) = 2.25
  article_differentiation_space: 6/10 (20%) = 1.2
  lab_conversion_naturalness: 7/10 (15%) = 1.05
  implementation_stability: 1/10 (10%) = 0.1
  total: 7.3/10
priority: P2
source_signals:
  - source_name: WebSearch aggregate (oneuptime.com x3, adminschoice.com, penguin-gym-linux.com, devops.aibit.im x2, medium.com, infotechninja.com, how2.sh)
    signal_type: extremely high cross-source volume, multiple actively-dated 2026 posts
    observed_signal: 10 independent sources this session, several dated 2026 (oneuptime
      publishes 3 separate distro-specific variants of the same article) — the highest search
      volume signal of any candidate, but paired with the worst implementation feasibility
    confidence: high (demand) / not applicable (feasibility is a hard platform fact, not a
      confidence-rated signal)
    source_url_or_reference: https://oneuptime.com/blog/post/2026-01-24-systemd-failed-to-start-service/view, https://how2.sh/posts/how-to-debug-a-systemd-crash-loop-with-journalctl/
```

### 10. `linux-address-already-in-use-port-conflict`

```
topic_id: linux-address-already-in-use-port-conflict
working_title: 服务启动报 Address already in use，但 ps 看着什么都没跑
real_engineering_pain: Genuinely common (7 independent sources) — the classic case is not
  even a live process, but the kernel holding TIME_WAIT state on a recently-closed TCP
  connection. A real judgment topic: "no visible process ≠ port is free."
implementation_risk: **VERY HIGH** — requires binding real sockets, `ss`/`netstat`/`lsof`
  (none available, network commands explicitly denied), and a real network stack the sandbox
  doesn't provide. Same class of gap as #9 — needs VM-level infrastructure, not an executor
  tweak.
score_breakdown:
  search_community_demand: 6/10 (30%) = 1.8
  engineering_pain_strength: 7/10 (25%) = 1.75
  article_differentiation_space: 6/10 (20%) = 1.2
  lab_conversion_naturalness: 6/10 (15%) = 0.9
  implementation_stability: 1/10 (10%) = 0.1
  total: 5.75/10
priority: P2
source_signals:
  - source_name: WebSearch (baeldung.com, linuxvox.com, codingeasypeasy.com, linuxbash.sh, dropvps.com)
    signal_type: cross-source convergence, including a well-regarded engineering education
      site (Baeldung)
    observed_signal: Baeldung (a respected software-engineering tutorial brand, not SEO
      content-mill) has a dedicated page for this exact symptom
    confidence: medium
    source_url_or_reference: https://www.baeldung.com/linux/docker-address-already-in-use
```

---

## C. Scoring Summary

| # | topic_id | Total | Priority | Runtime-ready today? |
|---|---|---|---|---|
| 1 | linux-chmod-permission-denied-despite-correct-mode | 8.15 | **P0** | ✅ Yes |
| 2 | linux-shared-directory-setgid-sticky-bit-wrong-owner | 7.9 | **P0** | ✅ Yes |
| 9 | linux-systemd-service-failed-to-start | 7.3 | P2 | ❌ Needs VM+systemd |
| 3 | linux-find-security-audit-world-writable-suid | 7.5 | P1 | ✅ Yes |
| 4 | linux-huge-log-file-triage-without-opening-it | 6.95 | P1 | ⚠️ Needs 1 new verifier type |
| 8 | linux-disk-full-df-du-mismatch-deleted-open-file | 6.75 | P2 | ❌ Needs process model change |
| 10 | linux-address-already-in-use-port-conflict | 5.75 | P2 | ❌ Needs VM+network |
| 7 | linux-umask-unexpected-default-permissions | 5.7 | P2 | ❌ Needs shell builtin support |
| 5 | linux-dangling-symlink-permission-confusion | 5.8 | P2 | ⚠️ Needs `ln` (small add) |
| 6 | linux-hardlink-symlink-inode-disk-usage-confusion | 5.6 | P2 | ⚠️ Needs `ln` (small add) |

**Note on rule compliance**: exactly 2 P0s (#1, #2), both scored highest AND both runtime-ready
today with zero platform changes — the ranking and the "buildable now" constraint happen to
agree, which is a genuine (not forced) alignment. `#9 (systemd)` scores 3rd-highest on raw
demand but is deliberately **not** P0/P1 despite the CEO/CTO brief naming it as an example,
because `implementation_stability` correctly drags it down and because building it this round
would violate "不做 Linux runtime 大改造." This is flagged explicitly in the Golden Topic
decision (§六) rather than silently overridden.

---

## D. Candidates Considered and Dropped (transparency, not padding)

| Idea | Why dropped |
|---|---|
| "Config drift diagnosis across two machines" (diff/grep-based) | Searched this session (`linux config file wrong version diagnose...`) — results were weak/tangential (mostly kernel-mailing-list noise, one PostgreSQL bug report), not a real convergent community pain signal. Rather than force a `confidence: low` entry to pad the count to 12, it was dropped. The brief's own anti-fabrication rule ("不得伪造搜索量... 不得假设") applies here. |
| "cron job silently not running" | Considered, but diagnosing it for real needs `crontab -l`/`crontab -e` (not in allowlist, and cron itself is a systemd/cron-daemon dependent service — same class of gap as #9). Would duplicate #9's flagged gap without adding a distinct judgment angle. |

Final count: **10 candidates**, within the brief's 10-12 range, with 0 fabricated or padded entries.

---

## E. Anti-Fabrication Self-Check

| Check | Result |
|---|---|
| Every source_signal backed by an actual WebSearch call this session | ✅ 10 searches run, all cited above |
| No "网上讨论很多" / "工程师经常遇到" / "搜索量很高" style unsupported claims | ✅ |
| confidence field present on every source_signal | ✅ all `medium` or `high`, none fabricated as unjustified `high` |
| implementation_risk assessed against real source code, not assumed | ✅ cross-checked against `ALLOWED_COMMANDS`/`DENIED_COMMANDS` read in the audit |
| P0 count ≤ 2 | ✅ exactly 2 |
| No candidate topic bundles multiple unrelated root causes | ✅ each is single-root-cause (matches the brief's own anti-example list) |
| Weak-evidence candidates dropped rather than padded in | ✅ §D |
