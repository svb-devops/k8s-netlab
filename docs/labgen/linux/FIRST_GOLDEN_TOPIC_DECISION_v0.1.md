# First Golden Topic Decision — v0.1

**Gate**: Linux Growth-First Track Foundation — Section 六
**Date**: 2026-07-20
**Executed by**: Claude Code
**Status**: Decision document only. **No lab draft, no article body is created by this
document or this round.**

---

## A.0 Status Update (2026-07-20, Linux Golden Lab #1 brief)

This topic was bound as "Golden Topic #1" per a follow-up CEO/CTO brief and taken to
production planning. **The hard feasibility gate that brief required before any lab
creation FAILED**: the production executor runs as UID 0 (root), and root bypasses the
directory execute/traverse permission check this topic's fault model depends on — verified
empirically, not assumed (see Track Contract §A.1 and
`LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED_v0.1.md` for the full result). Per the brief's own
explicit instruction, this freezes the Sprint: no lab, no verifier, no article brief were
created. The topic selection and scoring below stand — the problem is a runtime identity gap,
not a flaw in the topic choice.

---

## A. Selected Topic

```
selected_topic: linux-chmod-permission-denied-despite-correct-mode
why_selected:
  - Highest score on the Topic Radar (8.15/10), driven by strong cross-source search
    convergence (7+ independent sources this session) and zero platform gap.
  - Fully executable with the current 19-command allowlist (chmod, stat, ls, find) —
    no verifier work, no executor change, no runtime investment needed. This is the
    only P0 candidate with a genuine 10/10 on implementation_stability.
  - Natural first production because it deepens (not repeats) the same "permissions"
    judgment family as the existing lab (Order 0, upgrade), giving the series a coherent
    on-ramp: Order 0 teaches basic file/permission concepts, Order 1 teaches the
    *diagnostic sequence* when the obvious fix (chmod) doesn't work.
  - systemd 服务启动失败 (Radar #9) scored close behind on raw demand (7.3) and was
    explicitly considered — see §D for why it was not selected despite the CEO/CTO
    brief naming it as an example.

search_intent: "permission denied" + "chmod" — readers who have already tried the
  obvious fix (chmod) and are still stuck, searching for why. This is a person already
  in a support/troubleshooting mindset, not passively browsing — high-intent traffic.

target_audience: Linux 初中级用户/运维新人，遇到过这个报错但没有系统排查方法的人；有过
  "我明明改了权限还是不行" 的挫败经历。

public_title_options:
  1. "chmod 明明改对了，为什么还是 Permission Denied？"
  2. "权限显示 -rwxr-xr-x，为什么还是打不开？"
  3. "Permission Denied 排查：不止是 chmod 的问题"

article_hook: 打开一个复现好的场景——文件权限看起来完全正确（-rwxr-xr-x），操作却依然被拒绝。
  读者的第一反应通常是"再 chmod 一次"，但这不是权限位的问题。

engineering_judgment_chain:
  文件本身权限位正确
  → （错误直觉：以为还是 chmod 位数不对，再试一次 chmod 777，依然失败）
  → 检查父目录是否有执行位（这是大多数人漏掉的第一层）
  → 若父目录正常，检查 shebang/解释器路径是否有效
  → 若脚本本身没问题，检查文件是否有 CRLF 行尾（Windows 编辑器常见坑）
  → 定位到具体是哪一层挡住后，针对性修复
  → 由 verifier 独立确认：目标操作真正成功，而不是学员自己说"应该好了"

lab_conversion_trigger: 文章结尾 CTA——"你的直觉可能会让你反复 chmod 却始终无效。5 分钟亲手
  复现这个陷阱，用 find/stat 定位到底是哪一层真正挡住了你。"

fault_scenario: 沙箱中预置一个脚本文件，文件本身的 mode 位是正确的（可执行），但其父目录缺少
  对应执行位，导致操作被拒绝。学员必须不被直接告知原因，自行用 stat/find/ls 定位到问题出在
  父目录而非文件本身。

learner_outcome: 学员建立起"权限报错不能只看文件本身，要按目录树逐层排查"的判断习惯，这个心智
  模型可以迁移到本系列后续所有权限类主题（Order 2-3）。

runtime_requirements: 现有 19 条命令白名单已完整覆盖（chmod, stat, ls, find），无需新增命令，
  无需新增 verifier 类型（file_mode_matches 已存在，足以验证最终状态）。

required_verifiers:
  - file_exists (已存在)
  - file_mode_matches (已存在) — 用于验证目标文件/父目录最终权限位是否被正确修复

missing_platform_assets: 无。这是本轮唯一一个"零缺口"的候选主题，这也是选它作为第一个黄金
  样板的直接原因——用一个不需要平台投入的主题验证"内容驱动增长漏斗"这个新模式本身能不能跑通，
  比一开始就压上一个需要新基础设施的主题（如 systemd）风险更低。

cleanup_strategy: 沙箱级别清理（删除 session workspace），与现有 LinuxCleanupAdapter 完全
  复用，无需新增清理逻辑。

risks:
  - 内容风险：判断链本身（mode → 父目录 → shebang → 行尾）需要写清楚"为什么先查这个再查那个"
    的工程判断，而不是罗列四个原因——这是本项目北极星强调的"工程判断优先于操作步骤堆砌"，落地
    时需要严格把关，避免写成普通教程。
  - 无平台/运行时风险——本主题不引入任何新的执行面。

explicitly_excluded_subtopics:
  - SELinux/AppArmor 上下文导致的权限拒绝（真实存在但需要真实策略引擎，当前沙箱环境不含
    SELinux/AppArmor，如果强行编造会违反"不得伪造"的红线，因此明确排除，不在本主题范围内）
  - ACL（setfacl/getfacl）导致的权限拒绝（同理，当前允许命令列表不含 setfacl/getfacl，且是
    独立的知识点，不应该塞进同一个 lab 造成主题不单一）

next_sprint_scope: 若本文档被采纳，下一 Sprint 的范围是：撰写 Lab Design Brief → Lab
  Contract → 构建 lab draft（4 步左右，参照现有 Order 0 lab 的步骤粒度）→ real rehearsal →
  non-admin smoke → Owner dogfood → 撰写 Official Site Article → Minimal Publish。
  **本轮（Foundation 任务）不执行其中任何一步。**
```

---

## B. Why Not systemd (the brief's own suggested example)

The CEO/CTO brief's suggested diagnostic chain for systemd was:

```
服务状态 → systemd 失败原因 → 顺序错误 → journal 第一条有效错误 → 配置/权限/运行环境
→ 修复 → 独立验证服务恢复
```

This is a sound judgment chain and systemd scored the 3rd-highest raw demand signal on the
radar (9/10 on search/community demand alone, the highest of any candidate). It was not
selected as the *first* golden topic because:

1. It requires `systemctl`/`journalctl` (both on the current deny list, not just absent) and a
   real systemd-capable init system — systemd is PID 1 and cannot run inside a sandboxed
   directory the way the current Linux runtime works.
2. Building it means the same class of infrastructure investment as the K8s domain already
   has (a real per-learner VM) — which this round's brief explicitly prohibits ("不做 Linux
   runtime 大改造").
3. Picking a runtime-blocked topic as the *first* proof point of a brand-new growth-funnel
   model would conflate two separate risks (does the funnel model work? does the new
   infrastructure work?) into one bet. De-risking them separately — prove the funnel with a
   zero-platform-gap topic first — is the more conservative sequencing, consistent with this
   project's own incremental-over-revolutionary practice on the K8s side (each K8s lab added
   exactly one new verifier/judgment branch, never several at once).

This is a sequencing decision, not a rejection of systemd's value — see Series Plan §C for the
explicit recommendation that systemd become the strongest candidate for a *future* infra
Sprint once the funnel model is proven.

---

## C. Score Comparison (from the Radar, for traceability)

| Candidate | Score | Platform gap | Selected? |
|---|---|---|---|
| linux-chmod-permission-denied-despite-correct-mode | 8.15 | None | **✅ Selected** |
| linux-shared-directory-setgid-sticky-bit-wrong-owner | 7.9 | None | Order 2 (next) |
| linux-systemd-service-failed-to-start | 7.3 | VM+systemd (large) | Deferred |
| linux-find-security-audit-world-writable-suid | 7.5 | None | Order 3 |

---

## D. Anti-Fabrication Self-Check

| Check | Result |
|---|---|
| Selection traces directly to Radar scoring, not a fresh preference | ✅ §A, §C |
| systemd's exclusion reasoned explicitly, not silently dropped despite being the brief's own example | ✅ §B |
| No lab draft, article body, or code created by this document | ✅ |
| `missing_platform_assets` honestly states "none" only where independently verified true (chmod/stat/ls/find all confirmed present in the allowlist during the audit) | ✅ |
| Explicitly excluded subtopics (SELinux/ACL) named with reason, not silently merged into the main topic | ✅ |
