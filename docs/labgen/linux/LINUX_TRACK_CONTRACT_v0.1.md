# Linux Track Contract — v0.1

**Gate**: Linux Growth-First Track Foundation — Section 四 + 五
**Date**: 2026-07-20
**Executed by**: Claude Code
**Status of this document**: Contract for future Linux lab production. Where current reality
already satisfies a clause, it is marked ✅ compliant. Where it does not, the gap is named
explicitly rather than the clause being softened to fit — this contract states what must be
true, not what already is.

---

## A. Runtime

### A.1 Runtime Profile split (added 2026-07-20, Linux Golden Lab #1 brief)

This contract's original §A treated "the Linux sandbox" as a single runtime. A follow-up
CEO/CTO brief correctly required splitting this into two explicit profiles rather than
implicitly assuming the current sandbox is VM-equivalent:

| Profile | Scope | Status |
|---|---|---|
| **Linux Sandbox Profile** | File/directory/permission-only local risk experiments (Orders 1-3, 5-6 of the Series Plan) | Current implementation |
| **Linux VM Profile** | systemd/port/process/mount/df-du and other real-system experiments | **Not implemented; requires a future, separate infra decision** |

**Critical finding, not assumed — empirically verified this session**: the CEO/CTO brief's own
description of the Sandbox Profile states "无 root" (no root). **This is not what the current
implementation actually does.** The production service (`k8s-netlab.service`) runs
`uvicorn backend.main:app` with `User=root` (confirmed via `systemctl cat` and `ps -eo
pid,uid,user,cmd`), and `linux_command_executor.py`'s `subprocess.run()` call does not drop
privileges, set a different UID, or use any privilege-separation mechanism (`setuid`,
`seccomp`, a dedicated unprivileged worker, containers/cgroups/namespaces — none of these are
present, and the executor's own docstring already says so: "Process isolation (cgroups,
seccomp, namespaces) is NOT implemented"). Every learner command, including `cat`/`chmod`/
`stat`, runs as UID 0.

**Empirical reproduction (this session, in an isolated scratch directory, not the production
sandbox)**:
```
mode 600 (no execute bit) on a directory owned by root, containing report.txt (mode 644)
subprocess.run(['cat', 'vault/report.txt'], ...) as UID 0
→ returncode: 0, stdout: 'secret content\n' — NOT blocked.
```
This confirms the theoretical DAC_OVERRIDE behavior directly: **root bypasses directory
execute/traverse permission checks**, which is exactly the mechanism Golden Topic #1's fault
model depends on. See the Golden Lab #1 Feasibility Gate result
(`LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED_v0.1.md`) for the full gate outcome and required fix.

**Contract correction**: the Sandbox Profile's "无 root" clause is downgraded from ✅-compliant
(as this document previously implied by omission) to an **explicit, named gap**. Any future
Linux lab whose fault model depends on real DAC permission enforcement (not just the existing
`file_exists`/`file_mode_matches` checks, which only inspect metadata and never depend on the
executor's own access rights) requires this gap to be closed first — either a dedicated
unprivileged worker/service account for the executor subprocess, or a per-session
setuid/user-namespace mechanism. This is a real infra decision, not a code nitpick — it changes
the security model of the entire Linux runtime, not just one lab.

| Clause | Current reality | Compliance |
|---|---|---|
| 每个 learner 使用隔离 VM | ❌ Uses a local sandboxed directory on the API host (`/tmp/labgen-linux-sandboxes/{session_id}/`), not a VM | ⚠️ **NON-COMPLIANT for VM isolation, compliant for the practical effect** — isolation is enforced by application-level path validation + command allowlist, not OS-level VM boundary. This is a real architectural difference from K8s, named honestly in the Existing Asset Audit §C. This contract does not mandate migrating to VMs — that is out of scope for this round — but it records the gap so future readers of this contract don't assume VM-equivalent isolation exists. |
| 不允许实验修改宿主机 | ✅ Enforced — `linux_command_executor.py` validates every path argument stays under `workspace_root`; forbidden roots list (`/`, `/home`, `/tmp` top-level, `/etc`, `/var`, `/root`, `/proc`, `/sys`, `/dev`, `/boot`, `/usr`, `/bin`, `/sbin`) is checked before any delete | ✅ Compliant |
| 不依赖公网软件仓库或外部服务 | ✅ Compliant — the command allowlist contains zero network tools (`curl`/`wget`/`ssh`/`scp` all explicitly denied) | ✅ Compliant |
| 明确本地镜像、软件包预置依赖策略 | N/A — no packages are installed or required by any command in the current allowlist | ✅ Compliant (trivially, by having no dependency) |
| systemd 实验必须在真实支持 systemd 的 VM 中运行 | ❌ No systemd experiments exist or are runnable today (`systemctl` is on the deny list, no VM) | **Forward-looking clause** — this is a requirement for *if/when* a systemd topic is built (see Series Plan §C: `linux-systemd-service-failed-to-start` is deferred pending exactly this VM investment). It is not violated today because no systemd lab exists to violate it. |
| 不允许 learner 获得无限制 root shell | ✅ Compliant — `sudo`/`su`/`doas`/`chroot` explicitly denied; no shell is ever invoked (`shell=False`) | ✅ Compliant |
| sudo 必须使用命令 allowlist 或封装脚本 | N/A given the clause above — sudo is not offered at all, which satisfies the intent (no unrestricted privilege) more strictly than an allowlisted sudo would | ✅ Compliant (by prohibition, not by allowlisted grant) |
| 高风险实验使用 loopback 文件或专用测试盘 | N/A — no filesystem/mount-level experiments exist yet (`mount`/`umount`/`mkfs`/`fdisk` all denied); this clause activates only if such a topic is ever built | Not yet applicable |
| 禁止直接修改系统根文件系统或真实可达生产网络 | ✅ Compliant — path validation + no network commands | ✅ Compliant |
| 明确 session TTL、VM 回收和配置策略 | ⚠️ Session TTL exists at the platform level (`LABGEN_LAB_SESSION_TTL_MINUTES`, shared with K8s), but there is no "VM 回收" for Linux since there is no VM — the equivalent is workspace directory cleanup, which is covered under §D (Cleanup) | ⚠️ Terminology gap only — the *intent* (bounded lifetime + guaranteed reclamation) is met by workspace cleanup; "VM 回收" literally does not apply |

---

## B. Fault Injection

| Clause | Requirement | How future Linux labs must satisfy it |
|---|---|---|
| 故障必须可复现 | Every fault must be deterministically seeded at session start, not randomly generated | Lab authors must seed fixture state (files, permissions, directory trees) via a fixed setup step, never via `random`/timestamp-dependent state |
| 故障必须局限于实验资产 | The fault must live entirely inside `workspace_root` | Already structurally enforced by the executor's path validation — a lab cannot inject a fault outside the sandbox even if it tried |
| 每个 lab 只注入一个主要根因 | One root cause per lab | Matches the Topic Radar's own single-root-cause rule (Radar §A anti-example list) — this is the same discipline applied consistently from topic selection through to fault design |
| 不依赖随机资源竞争 | No race-condition-dependent faults | Consistent with "故障必须可复现" — race conditions are the opposite of reproducible |
| 不允许以破坏系统关键服务作为教学捷径 | N/A today — no system services are reachable at all from the sandbox | Compliant by architecture; stays true as long as §A's isolation model holds |
| 故障注入和修复都必须可由 verifier 独立确认 | Verifier must check real filesystem/process state, never learner-reported state | Directly enforced by §C below |

---

## C. Verifier

### C.1 Anti-pattern list (binding, not aspirational)

A verifier MUST NOT treat any of the following as sufficient for PASS:
- learner 命令顺序历史 (command history replay)
- 前端命令回放 (frontend-side command echo)
- learner 自己输出的字符串 (learner-printed strings, unless independently re-checked against real state)
- learner 创建的"完成标记"文件 (a learner-created "done" marker file)

**Current compliance**: ✅ both existing verifier types (`file_exists`, `file_mode_matches`)
stat the real filesystem inside the sandbox directly — confirmed by reading
`linux_verifier_client.py` in the Existing Asset Audit (§B.3). No violation exists today.

### C.2 Required verifier vocabulary and current gap

| Verifier type | Status | Needed by (from Series Plan) |
|---|---|---|
| `file_exists` | ✅ Exists, tested | Orders 0-3, 5-6 |
| `file_mode_equals` (implemented as `file_mode_matches`) | ✅ Exists, tested | Orders 0-2 |
| `file_content_contains` | ❌ Missing | Order 4 (log triage) |
| `command_exit_code_equals` | ❌ Missing | Order 4 (log triage), potentially Order 3 (audit) |
| `file_owner_equals` | ❌ Missing | Order 2 (setgid — verifying group inheritance needs this or an equivalent) |
| `file_group_equals` | ❌ Missing | Order 2 (setgid — same need) |
| `systemd_unit_state_equals` | ❌ Missing | Deferred systemd topic only — not needed by Orders 0-6 |
| `port_listening` | ❌ Missing | Deferred port-conflict topic only |
| `process_running` | ❌ Missing | Deferred df/du topic only |
| `mount_exists` | ❌ Missing | Not needed by any current-round topic |
| `filesystem_usage_condition` | ❌ Missing | Deferred df/du topic only |
| `path_accessible_as_user` | ❌ Missing | Not strictly required by Orders 0-6 as scoped, but useful generally for permission labs |

**Compliance summary**: of the 12 baseline types, 2 exist. Of the 6 series topics (Orders 1-6),
**Order 2 needs `file_owner_equals`/`file_group_equals` and Order 4 needs
`file_content_contains`/`command_exit_code_equals` before they can be built** — this is real,
scoped verifier backlog, not a hypothetical future need. This contract does not authorize
building them now (out of scope this round); it records precisely which topics are blocked on
which verifier and why, so a future Sprint's scope is unambiguous.

---

## D. Cleanup

| Clause | Current reality | Compliance |
|---|---|---|
| cleanup 必须恢复实验前状态 | ✅ `LinuxCleanupAdapter` deletes the entire session workspace | ✅ Compliant |
| cleanup_verified 必须由平台验证 | ✅ Residual scan after delete confirms the workspace is actually empty, not just that the delete call returned success | ✅ Compliant |
| systemd unit/文件/用户/进程/端口/mount/loop device 等要有对应回收策略 | N/A for files/directories (covered); N/A for the others because none of Orders 0-6 use systemd units, dedicated users, background processes, ports, mounts, or loop devices | ✅ Compliant by scope — this clause becomes binding again only if a future topic (e.g. the deferred systemd/df-du/port topics) is built |
| cleanup 必须幂等 | ✅ Explicitly designed for it — a second cleanup call on an already-gone workspace is a no-op success (audited directly in source) | ✅ Compliant |
| cleanup 失败不得伪装成功 | ✅ Fail-closed — cleanup failure taints the session rather than reporting success | ✅ Compliant |
| VM 最终删除可作为最后隔离层，但不能替代 lab 内 cleanup 验证 | N/A — no VM exists in the Linux model; the equivalent backstop is the forbidden-root guard in `linux_command_executor.py`/`linux_cleanup.py`, which is enforced on every delete, not just as a "final" backstop | ⚠️ Intent satisfied via a different mechanism (defense embedded in every operation, not a single final layer) — noted rather than silently equated |

**Summary**: Cleanup is the one contract section where current reality is fully compliant with
the letter of the brief, not just its intent. No gap to close here for Orders 0-6.

---

## E. Content & Publish Order

Fixed sequence (binding for all future Linux lab production):

```
需求信号
→ Topic Brief
→ Lab Design Brief
→ Lab Contract
→ verifier/runtime
→ real rehearsal
→ non-admin learner smoke
→ Owner dogfood
→ Official Site Article
→ Minimal Publish
→ External Technical Article
→ 平台侧埋点上线
```

### E.1 Second-reader gate: REMOVED

Per this brief's explicit CEO/CTO decision, **"必须两位真实读者独立完成才能继续产能发布" is no
longer a publish blocker.** This supersedes the second-reader planning process described in
`SECOND_LINUX_TRUSTED_READER_PILOT_PLANNING_REVIEW_RESULT_v0.1.md` (2026-06-24) — that plan is
not cancelled as a *good idea* (a second independent reader still produces real signal), but it
is no longer a **gate**. A future Sprint may still choose to run it opportunistically for
qualitative signal; it must not block any publish decision.

### E.2 New default publish gate (replaces the second-reader requirement)

| Gate | Requirement |
|---|---|
| static validation | PASS |
| 真实 VM/sandbox rehearsal | PASS (VM for K8s domain, sandbox rehearsal for Linux domain — same rigor, different execution substrate per §A) |
| 普通非 admin smoke | PASS |
| Owner dogfood | PASS |
| cleanup_verified | `true` |
| BLOCKER/HIGH count | 0 |
| article 与 lab 验证同步 | Article must exist and be verified alongside the lab — **this replaces "two readers" as the actual quality backstop.** An article with a real CTA, checked against the lab's actual steps, catches "does the funnel work" issues that a second reader was being used as a proxy for. |

This gate applies to Order 0 (upgrade) and Orders 1-6 (new) alike once each reaches production
in a future Sprint. This document does not execute any of them — see §Completion Check.

---

## F. Growth Funnel Instrumentation Standard

Fixed funnel (binding vocabulary for all future analytics work, K8s and Linux alike):

```
External Technical Article
→ Official Site Article
→ CTA click
→ Lab Start
→ LAB_ACTIVE
→ Core Verifier PASS
→ Lab Complete
→ Next Article Click
```

### F.1 Stage-1 events to record (minimum vocabulary, not an implementation)

```
article_page_view
CTA click
lab_start
provisioning_success
LAB_ACTIVE
first_verifier_pass
lab_completion
cleanup_success
next_article_click
```

### F.2 Current capability vs. this standard

| Check | Status |
|---|---|
| `lab_start_success` / `lab_start_failed` audit events | ✅ Exist today (`backend/labgen/models.py:583-584`, `backend/labgen/api_contract.py:734`) — the only funnel stage with any existing instrumentation |
| `article_page_view` | ❌ Missing — no page-view tracking exists anywhere in the codebase |
| CTA click | ❌ Missing |
| `provisioning_success` (Linux) | ❌ Missing — Linux has no equivalent of K8s's VM-provisioning success event since there's no VM step |
| `LAB_ACTIVE` transition | ⚠️ Session state model already has this as a state (`session_state` field), but it is not emitted as a discrete analytics *event* — it is a database field read on demand, not a stream |
| `first_verifier_pass` | ❌ Missing as a distinct event (step-check results exist per-request but are not aggregated into a funnel metric) |
| `lab_completion` | ⚠️ Same as `LAB_ACTIVE` — exists as a state, not an event |
| `cleanup_success` | ⚠️ Same — `cleanup_verified` is a stored boolean, not an emitted event |
| `next_article_click` | ❌ Missing |

**This round explicitly does not build any of this** (per the brief: "本轮只定义指标和现有能力
缺口，不开发新的 analytics 平台"). The table above is the scope of that future work, stated
precisely so it isn't re-discovered from scratch later.

---

## G. Anti-Fabrication Self-Check

| Check | Result |
|---|---|
| Every "✅ Compliant" claim backed by source code read in the Existing Asset Audit | ✅ |
| Every "❌ Non-compliant" / gap claim named with the specific missing capability | ✅ |
| No clause silently reworded to claim compliance it doesn't have | ✅ — VM isolation gap stated plainly in §A, not glossed as "isolation exists" |
| Second-reader gate removal stated as this brief's explicit instruction, not this document's own opinion | ✅ §E.1 |
| No analytics platform built or committed to in this round | ✅ §F.2 explicit |
| No runtime overhaul executed or silently started | ✅ — every gap in §A/§C is recorded, none is closed by this document |
