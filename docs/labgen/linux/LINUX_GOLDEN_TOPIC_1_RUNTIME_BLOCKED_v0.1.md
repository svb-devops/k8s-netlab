# Linux Golden Topic #1 — Runtime Blocked — v0.1

**Gate**: Linux Golden Lab #1 (chmod 正确位仍 Permission Denied) — Section 二 (硬性可行性 Gate)
**Final Decision**: `LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED`
**Date**: 2026-07-20
**⚠️ Status update (2026-07-21)**: The blocker recorded in this document is **RESOLVED**. See
`LINUX_SANDBOX_NONROOT_RUNTIME_ACCEPTANCE_v0.1.md` — a dedicated unprivileged system account
(`labgen-linux-runner`) now executes every Linux sandbox command, real EACCES is confirmed via
the production code path, and the existing lab was re-validated end-to-end under the new
runner. This document is kept as-is below for the historical failure evidence (not modified) —
the Golden Topic #1 feasibility gate itself may now be re-run and is expected to pass.
**Executed by**: Claude Code
**Lab created**: NO
**Verifier created**: NO
**Topic Brief created**: NO
**Lab Design Brief created**: NO
**Article Brief created**: NO
**Second reader test executed**: NO
**Production code modified**: NO
**Existing Linux lab upgraded**: NO
**K8s sub-series touched**: NO

---

## A. Executive Summary

The brief's own hard feasibility gate (§二) required verifying, with a real reproduction — not
an assumption — that the current Linux executor can produce a genuine kernel-level `EACCES`
when a directory's execute/traverse bit is removed, before any lab content is created. It does
not. **The Sprint is frozen per the brief's own explicit instruction for this outcome.**

| Question (brief §二, mandatory) | Answer |
|---|---|
| 当前 executor 是否以 root 身份运行？ | **YES** |
| 权限失败是否由 Linux 内核真实返回 EACCES？ | **NO — no failure occurs at all; root bypasses the check** |
| path validation 是否会在命令到达内核前改变权限语义？ | **NO** — `linux_command_executor.py`'s validation only enforces workspace-boundary containment (no `os.access`/`EACCES`/permission-bit logic anywhere in the file); it does not pre-empt or simulate kernel behavior |
| 修复单一父目录身份后是否真实访问成功？ | **N/A — access never failed to begin with, so there is nothing to "restore"** |

**Result: the fault model this lab depends on cannot be produced on the current production
runtime.** This is not a hypothetical concern flagged in advance (the Track Contract §A.1
already named the VM-isolation gap generally) — it is now a **directly reproduced, concrete
blocker** for this specific topic.

---

## B. Feasibility Investigation (real evidence, not simulated)

### B.1 Runtime identity

```
systemctl cat k8s-netlab.service:
  User=root
  ExecStart=/root/k8s-netlab/venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

ps -eo pid,uid,user,cmd (production process, port 8000):
  PID 1675, UID 0, USER root

id (equivalent shell context):
  uid=0(root) gid=0(root) groups=0(root)
```

`linux_command_executor.py`'s `subprocess.run(argv, shell=False, cwd=workspace_root, env=...)`
does not set `user=`, does not call `os.setuid`/`os.setgid`, and has no privilege-separation
mechanism of any kind — every learner command inherits the parent process's UID, which is 0.

### B.2 Real reproduction (isolated scratch directory — NOT the production sandbox, NOT any
real session workspace)

```
mkdir vault; echo "secret content" > vault/report.txt
chmod 644 vault/report.txt   # file itself: readable
chmod 600 vault              # directory: owner rwx removed the execute/traverse bit for
                              # everyone including owner (rw-------, no x)

stat -c '%a %U %G' vault vault/report.txt
  → 600 root root
  → 644 root root

subprocess.run(['cat', 'vault/report.txt'], cwd='.') as UID 0:
  → returncode: 0
  → stdout: 'secret content\n'
  → stderr: ''
```

**No error. No EACCES. The read succeeds despite the directory having zero execute bits.**
This is the textbook Linux `CAP_DAC_OVERRIDE` behavior: a process with root privileges bypasses
discretionary access control checks, including directory search/traverse permission, unless
that capability has been explicitly dropped. It was not dropped here — nothing in the current
codebase drops any capability.

This scratch reproduction was created and destroyed in `/tmp/claude-0/.../scratchpad/`, not in
`/tmp/labgen-linux-sandboxes/` — it did not touch any real session, workspace, or production
data path.

### B.3 Why this specific topic is affected (and others may not be)

The two *existing* verifier types (`file_exists`, `file_mode_matches`) never depended on this —
they inspect file metadata (`os.stat()` mode bits) directly in Python, which works identically
regardless of the executor's own privilege level, because metadata inspection is not the same
operation as a privileged access attempt. **The gap only bites when a lab's fault model
requires the executor to actually be *denied* access** — which is exactly Golden Topic #1's
premise (and would equally affect the still-provisional Order 2 topic, "setgid 归属" — see
Series Plan correction — for the same underlying reason, though that was not the subject of
this gate).

---

## C. Why the Sprint Freezes Here (per the brief's own instruction)

The brief's §二 states explicitly: if the executor runs as root and cannot stably produce real
`EACCES`, then: freeze the Sprint, do not fabricate Permission Denied, do not create any
experiment, output `LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED`, and give a minimal isolation-identity
fix recommendation while waiting for Owner's decision. All of this is followed exactly:

- **No lab, verifier, Topic Brief, or Lab Design Brief were created** — Sections 三 through 六
  of the brief are gated behind this feasibility check and were never started.
- **No fabrication**: at no point was a fake "Permission Denied" state simulated, hardcoded, or
  worked around to make the topic appear buildable. The honest result is that the fault does
  not reproduce.
- **No second-reader test, no article, no Directus record** — none of these were ever reached;
  they were downstream of a gate that did not pass.

---

## D. Minimal Isolation-Identity Fix Recommendation (for Owner decision — not executed)

This section names options; it does not choose one, and none of these are implemented by this
document.

| Option | What it does | Cost/risk |
|---|---|---|
| **A. Dedicated unprivileged system user for the executor subprocess** (e.g. `labgen-linux-runner`, no login shell, no sudo group) — `subprocess.run(..., user='labgen-linux-runner')` (Python 3.9+ supports the `user=` kwarg directly, or `preexec_fn` with `os.setuid`) | Real, kernel-enforced DAC checks apply to that user; root-owned files/dirs correctly deny it | Requires the sandbox workspace directories to be owned by (or made accessible to) that user instead of root, which touches `linux_workspace.py`'s directory-creation logic; moderate, contained change |
| **B. Run the entire Linux runtime (not just command execution) as a separate non-root system service**, distinct from the root-owned main API process | Same effect as A but architecturally cleaner — no per-subprocess UID juggling inside a root parent | Larger change: a second systemd unit, an internal API/IPC boundary between the root API process and this new unprivileged worker |
| **C. User namespaces / `unshare --user` per session** | Strongest isolation, closest to a "real VM" experience without an actual VM | Highest implementation complexity of the three; the executor docstring already flags namespaces as "NOT implemented" — this is the largest lift |
| **D. Do not fix this — restrict all future Linux sandbox topics to fault models that don't depend on privileged-access denial** (e.g. content/structural topics: log triage, `find`-based audit, symlink semantics — none of which require the executor to be denied anything) | Zero engineering cost | Golden Topic #1 (and the provisional Order 2, setgid) would need to be dropped or fundamentally redesigned; permanently caps what "Linux Sandbox Profile" topics can ever teach |

**No recommendation is made among these** — this is exactly the kind of infra/product tradeoff
the brief reserves for Owner decision, not for this document to pre-empt. Option A is the
smallest, most contained change if the Owner wants to keep Golden Topic #1's current design;
Option D is the fastest way to keep production moving on a different topic without touching
runtime security architecture at all.

---

## E. Final Handoff

```yaml
linux_golden_lab_1_handoff:
  overall_status: LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED

  planning_corrections:
    existing_lab_role: prerequisite_legacy_onboarding_asset_not_in_6_topic_series
    six_topic_series_count: 6 (1 bound - Golden Topic #1 - + 5 provisional, pending this gate's resolution and future runtime decisions)
    remaining_topics_provisional: true
    sandbox_profile: "file/dir/permission-only local risk experiments; CURRENT IMPLEMENTATION RUNS AS ROOT (contradicts the brief's own 'no root' Sandbox Profile description — corrected in Track Contract SS A.1)"
    vm_profile_deferred: true

  feasibility:
    runtime_uid: 0
    runtime_gid: 0
    is_root: true
    learner_identity: "same as the API process (root) - no privilege separation exists"
    kernel_eacces_confirmed: false
    file_chmod_did_not_fix: not_applicable (access never failed)
    parent_execute_fix_succeeded: not_applicable (nothing to fix - access was never denied)
    path_validation_preserved_semantics: true (workspace-boundary containment only, no permission-bit logic, confirmed by reading linux_command_executor.py source)

  topic:
    topic_id: linux-chmod-permission-denied-despite-correct-mode
    primary_root_cause: parent_directory_missing_execute_traverse_bit
    excluded_subtopics: [selinux, apparmor, acl, shebang, crlf, readonly_mount, user_group_ownership]

  lab:
    lab_id: null
    title: null
    publish_status: not_created
    steps: not_created
    verifier_types: not_created

  verifier:
    new_type: not_created (path_accessible_as_user was designed in the brief but never implemented - gated behind this feasibility check)
    independent_state_check: not_applicable
    learner_identity_enforced: not_applicable
    fail_closed: not_applicable
    cross_session_isolation: not_applicable

  rehearsal:
    status: not_started
    steps_passed: 0
    access_denied_confirmed: false
    access_restored_confirmed: not_applicable
    cleanup_verified: not_applicable

  smoke:
    username: not_created
    non_admin: not_applicable
    steps_passed: 0
    cleanup_verified: not_applicable
    session_status: not_applicable

  article_brief:
    path: null
    article_body_created: false
    directus_record_created: false

  growth_measurement:
    existing_events: [lab_start_success, lab_start_failed]
    missing_events: [article_page_view, cta_click, LAB_ACTIVE_event, first_verifier_pass, lab_completion_event, cleanup_success_event, next_article_click]
    publish_sprint_requirement: not_applicable_this_round

  regression:
    k8s_unchanged: true
    existing_linux_lab_unchanged: true
    public_exposure_unchanged: true
    health: healthy (proxmox connected, labgen ok; sessions.status=degraded is the pre-existing, unrelated zombie-draft-count warning noted in the Foundation round, not caused by this task)
    active_sessions: 0
    residual_workspaces: 0 (scratch reproduction was created/destroyed outside /tmp/labgen-linux-sandboxes/, confirmed removed)

  tests:
    targeted: not_run (no code was changed - nothing new to target-test; existing suite unaffected)
    full_suite: not_run_this_task (last confirmed green at commit 497f276, prior task in this session)
    mypy: not_run (no code changed)

  issues:
    blocker:
      - "Golden Topic #1's fault model (directory execute-bit denial) cannot be reproduced because the Linux executor runs as root (UID 0), which bypasses DAC directory-traverse checks. Confirmed via live reproduction, not assumed. Requires an Owner decision among the options in SS D before any lab work on this topic can resume."
    high: []
    medium: []
    low:
      - "Track Contract's Sandbox Profile description previously implied (by omission) that the current runtime satisfies 'no root' - corrected in this round; the gap was real and is now named, not newly introduced."
  commits: "pending - see repo HEAD after this task's commit"
  pushed_to_github: "pending - standard commit+push workflow, docs-only change"
  git_status: "clean prior to this task's own doc additions; scratch reproduction directory created and fully removed outside the repo and outside any production data path"
  recommended_next_step: "Owner reviews SS D (four isolation-identity options) and either (a) selects one to unblock Golden Topic #1, or (b) redirects Golden Lab production to a topic whose fault model does not require privileged-access denial (see Series Plan Order 3, 'find security audit', or Order 4, 'log triage', both of which do not depend on this gap). No further Linux Golden Lab production should proceed until this decision is made."
```

---

## F. Anti-Fabrication Self-Check

| Check | Result |
|---|---|
| Root/UID claim verified via `systemctl cat` + `ps` + `id`, not assumed from memory | ✅ |
| EACCES-does-not-occur claim verified via a real `subprocess.run()` reproduction, not reasoned about only in the abstract | ✅ |
| Reproduction ran outside any production data path (`/tmp/labgen-linux-sandboxes/` untouched) | ✅ |
| No lab, verifier, or article created despite the gate failing | ✅ |
| No fake Permission Denied fabricated to make the topic look buildable | ✅ |
| Isolation-fix options presented without a forced recommendation, per "wait for Owner decision" | ✅ |
| Existing Linux lab, K8s series, public exposure confirmed unchanged | ✅ |
| Health checked live, not assumed from the prior round's snapshot | ✅ |
