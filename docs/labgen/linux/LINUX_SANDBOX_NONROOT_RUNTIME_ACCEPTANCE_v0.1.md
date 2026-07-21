# Linux Sandbox Non-Root Runtime — Acceptance v0.1

**Gate**: Linux Sandbox Privilege Separation v0.1 — 只做 Runtime Blocker
**Final Decision**: `LINUX_SANDBOX_NONROOT_RUNTIME_READY`
**Date**: 2026-07-20/21
**Executed by**: Claude Code
**Golden Lab (chmod topic) built this round**: NO
**Official article written this round**: NO
**External Technical Article written this round**: NO
**Second real-external-reader test executed**: NO

---

## A. Executive Summary

The runtime blocker recorded in `LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED_v0.1.md` — the Linux
command executor running as root, letting root bypass the exact DAC directory-permission check
Golden Topic #1's fault model depends on — is resolved. Option A from that document's
recommendation set was implemented: a dedicated unprivileged system account
(`labgen-linux-runner`, UID/GID 997) that every learner and admin-rehearsal Linux command now
executes as, via native `subprocess.Popen` privilege-drop kwargs (not `preexec_fn` — see §D for
why that mattered here specifically).

**Original failure cause**: `k8s-netlab.service` runs `User=root`; `linux_command_executor.py`'s
`subprocess.run()` inherited that UID with no privilege-separation mechanism at all.

**Why Option A**: smallest change that fixes the actual gap (real DAC enforcement) without
requiring a VM or container investment (explicitly out of scope), and without weakening any
existing security semantics (no allowlist expansion, no relaxed path validation).

**Runner UID/GID**: 997 / 997 — real system account, no login shell, no password, no
supplementary groups, not in sudo/docker/libvirt.

**Real EACCES evidence**: confirmed via the production executor code path itself
(`tests/test_labgen_linux_sandbox_privilege_separation.py::TestRealEaccesReproduction`, plus an
independent manual `subprocess.run(user=..., group=...)` reproduction in an isolated scratch
directory — same result both ways: `cat` on a file inside a directory whose execute bit was
removed returns real `Permission denied`, and restoring the bit restores access).

**Existing Linux lab** (`6c439064`, "Linux Files and Permissions Basics"): re-validated under
the new runner — internal rehearsal 4/4, non-admin learner smoke 4/4, `LAB_CLOSED`,
`cleanup_verified=true`, no residual workspace. Public learner access restored
(`LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` back to its baseline value).

**A real bug found and fixed during this validation** (not present in the original brief, found
by actually running the lab end-to-end rather than trusting the design on paper): `>`
output-redirect files in `lab_kubectl_ws.py` were written by the root API process directly
(`out_path.write_text()`), never through the privilege-dropped executor — so a redirect-created
file stayed root-owned while everything else ran as the runner, and a later `chmod` on that same
file by the runner failed with "Operation not permitted." Fixed by chowning the file to the
runner identity immediately after the write, inside the same already-workspace-validated path.
Regression-tested (`tests/test_labgen_linux_terminal_ws.py::TestRunLinuxCmdWithRunnerIdentity`),
confirmed to fail without the fix and pass with it.

**Safety review** (mandatory A类 — security model change): 1 BLOCKER, 1 HIGH, both fixed before
this document was written:
- BLOCKER: CI (`test.yml`) never installed the runner account, so the new privilege-separation
  tests would crash pytest collection on the very next push. Fixed: added an install step before
  `pytest` runs.
- HIGH: `LinuxRehearsalService`'s default constructor path (`adapter=None`) silently built a
  root-running adapter if a future caller forgot to pass one — unreachable from current
  production code, but a real trap for any future caller. Fixed: the default path now requires
  `runner_uid=`/`runner_gid=` explicitly and raises `ValueError` otherwise; there is no way to
  construct a root-running `LinuxRehearsalService` by omission anymore.

---

## B. Runtime Profile Distinction (unchanged from the Track Contract correction)

Building this fixes the **Linux Sandbox Profile**'s privilege model (root → non-root, real DAC
enforcement). It does **not** build the **Linux VM Profile** (systemd/port/process/mount/df-du
real-system experiments) — that remains a separate, undecided infra investment, exactly as
`LINUX_TRACK_CONTRACT_v0.1.md` §A.1 already stated. Nothing in this round changes that
distinction.

---

## C. Hard Feasibility Gate — Re-Run Result

| Question | Before (blocked) | After (this round) |
|---|---|---|
| 当前 executor 是否以 root 身份运行？ | YES | **NO — UID 997, GID 997** |
| 权限失败是否由内核真实返回 EACCES？ | NO (root bypassed it) | **YES — confirmed twice, independently** |
| path validation 是否会改变权限语义？ | NO (unaffected either way) | NO — unchanged, still pure containment logic |
| 修复单一父目录身份后是否真实访问成功？ | N/A (never failed) | **YES — confirmed** |

`kernel_eacces_confirmed=true`, `file_chmod_did_not_fix=true` (chmod on the file itself does not
restore access — the parent directory's execute bit is the actual root cause),
`parent_execute_fix_succeeded=true`.

---

## D. Why `preexec_fn` Was Deliberately Not Used

`linux_command_executor.py`'s `execute()` is called via `run_in_executor` from
`lab_kubectl_ws.py`'s WebSocket handler — i.e. inside a thread-pool worker thread, not the main
event-loop thread. Python's own `subprocess` documentation warns that `preexec_fn` is unsafe in
multi-threaded programs (fork() only carries over the calling thread; a lock held by another
thread at fork time can deadlock the child before it execs). This was a real, specific risk in
this codebase's actual call site, not a generic caution copied from documentation — verified by
reading `lab_kubectl_ws.py`'s own docstring ("Runs synchronously (called via `run_in_executor`)")
before deciding. Python 3.9+'s native `subprocess.Popen(user=, group=, extra_groups=, umask=)`
kwargs avoid this entirely (implemented without a Python-level fork-time callback) and were used
instead.

---

## E. Existing Linux Lab Regression

| Check | Result |
|---|---|
| Internal rehearsal (admin-only, `/internal/linux-rehearsal-sessions`) | ✅ 4/4 steps, `all_verifiers_passed=True` every step, session `LAB_CLOSED`, `cleanup_verified=True` |
| Non-admin learner smoke | ✅ Genuine newly-registered, non-admin account (`lnx-mig-smoke01`); workspace auto-created; 4/4 steps (including the `chmod` step that exposed and confirmed the redirect-ownership bug fix); `LAB_CLOSED`, `cleanup_verified=True` |
| Fixture ownership issue | ✅ Found (redirect-created files), fixed via targeted chown at the point of creation — not a blanket `chmod 777`, not an allowlist expansion, not a root fallback |
| Public access restored | ✅ `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` back to baseline (`6c439064-...`), service restarted, health confirms `linux_runtime.enabled=true, runner_ready=true` |

---

## F. Security Regression (full results in `tests/test_labgen_linux_runner_security_regression.py`, 16/16 pass)

| Check | Result |
|---|---|
| `../` path traversal | ✅ Still blocked (policy layer, unaffected by privilege separation) |
| Absolute path escape | ✅ Still blocked |
| symlink escape outside workspace | ✅ Blocked by `LinuxWorkspaceManager.resolve_path()`'s realpath containment |
| Sibling/cross-session workspace access | ✅ Blocked — proven under the actual shared runner UID (all sessions use the SAME UID 997; isolation comes entirely from path validation, not OS user separation — stated explicitly, not glossed over) |
| `/etc/shadow` read | ✅ Blocked by app policy AND real OS permissions (0640 root:shadow, runner not in shadow group) |
| `/root` / source tree write | ✅ Blocked by real OS permissions (0755 root:root, no world-write bit) |
| sudo/su/shell/interpreter/network commands | ✅ Still rejected at the policy layer with a runner identity wired in |
| Runner supplementary groups | ✅ Empty — confirmed via `os.getgrouplist`, not just at install time |

---

## G. Production Recovery Confirmation

| Check | Result |
|---|---|
| K8s labs | ✅ Unchanged (6 published, unaffected) |
| K8s articles | ✅ Unchanged (7 public, unaffected) |
| K8s provisioning | ✅ Untouched — no code in the K8s VM path was modified |
| Existing Linux lab content | ✅ Unchanged (`6c439064`, same 4 steps, same verifiers) |
| No new article/CTA created | ✅ |
| `active_session_count` | ✅ 0 |
| Residual Linux workspaces | ✅ 0 (real production sandbox root scanned; only pytest-artifact-named dirs remain, pre-existing and unrelated) |
| `runner_ready` | ✅ `true` (health, live) |
| git status | ✅ Only this Sprint's own changes; no unrelated uncommitted state |

---

## H. Tests and Regression

| Check | Result |
|---|---|
| Targeted Linux privilege-separation/security tests | 33 new tests across 6 new files, all pass |
| Full suite | 5214 passed, 1 skipped, 26 xfailed, 92.52% coverage |
| mypy (all changed files) | 0 errors |
| Production health check | `healthy`, `linux_runtime.runner_ready=true` |

---

## I. Anti-Fabrication Self-Check

| Check | Result |
|---|---|
| EACCES reproduction run against the real production code path, not simulated | ✅ |
| Redirect-ownership bug found by actually running the lab, not invented for drama | ✅ — confirmed to fail without the fix, pass with it |
| Safety-reviewer findings (1 BLOCKER, 1 HIGH) fixed, not argued away | ✅ |
| No Golden Lab, article, or Directus record created this round | ✅ |
| No K8s or existing-Linux-content modification | ✅ |
| Public access restoration gated on rehearsal + smoke + security regression all passing first | ✅ |

---

## J. Final Handoff

```yaml
linux_sandbox_nonroot_runtime_handoff:
  overall_status: LINUX_SANDBOX_NONROOT_RUNTIME_READY

  containment:
    linux_public_access_disabled_during_migration: true
    k8s_unchanged: true
    baseline_recorded: "6c439064-4cad-4229-addb-36927128d565 (restored to this value in .env after validation)"

  runner:
    user: labgen-linux-runner
    group: labgen-linux-runner
    uid: 997
    gid: 997
    is_root: false
    login_disabled: true
    supplementary_groups: []
    installation_idempotent: true
    missing_config_fail_closed: true
    root_config_fail_closed: true

  executor:
    subprocess_user_enforced: true
    subprocess_group_enforced: true
    extra_groups_cleared: true
    shell: false
    cwd: session_workspace
    home: session_workspace
    tmpdir: not_separately_set (HOME=workspace_root already scopes writes; no lab uses TMPDIR)
    umask: "0o077 (native subprocess kwarg, not preexec_fn)"
    process_group_cleanup: "not explicitly set (start_new_session not passed) — timeout handling unchanged from pre-existing subprocess.run(timeout=) behavior, out of this round's scope"

  workspace:
    root_owner: root (sandbox_root itself, unchanged)
    session_owner: labgen-linux-runner (chowned after creation)
    session_mode: "0700"
    path_boundary: enforced (realpath containment, unchanged)
    symlink_escape_blocked: true
    cross_session_access_blocked: true
    cleanup_idempotent: true

  feasibility_recheck:
    learner_effective_uid: 997
    learner_effective_gid: 997
    kernel_eacces_confirmed: true
    file_mode_correct: true
    file_chmod_did_not_fix: true
    parent_execute_fix_succeeded: true
    error_simulated: false

  existing_linux_lab:
    lab_id: 6c439064-4cad-4229-addb-36927128d565
    rehearsal_steps: "4/4 PASS"
    smoke_username: lnx-mig-smoke01
    non_admin: true
    smoke_steps: "4/4 PASS"
    cleanup_verified: true
    public_access_restored: true

  security:
    etc_shadow_denied: true
    etc_write_denied: true
    root_write_denied: true
    source_tree_write_denied: true
    denied_commands_unchanged: true
    path_traversal_denied: true
    sibling_workspace_denied: true

  production:
    health: healthy
    linux_runner_ready: true
    active_sessions: 0
    residual_workspaces: 0
    public_exposure: "existing Linux lab restored to baseline allowlist; no new exposure"

  regression:
    k8s_labs: unchanged
    k8s_articles: unchanged
    k8s_provisioning: unchanged
    existing_linux_content_unchanged: true

  tests:
    targeted: "33 new tests, 6 new files, all pass"
    full_suite: "5214 passed, 1 skipped, 26 xfailed, 92.52% coverage"
    mypy: "0 errors"

  issues:
    blocker: []
    high: []
    medium: []
    low:
      - "process_group_cleanup (start_new_session) not added this round — command timeout behavior unchanged from pre-existing subprocess.run(timeout=) semantics; not a new gap introduced by privilege separation, out of this round's scope"
      - "10 of 12 Track Contract verifier types still missing (carried forward from Foundation round, unrelated to this Sprint)"

  docs:
    - docs/labgen/linux/LINUX_SANDBOX_NONROOT_RUNTIME_ACCEPTANCE_v0.1.md (this document)
    - docs/labgen/linux/LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED_v0.1.md (updated with resolution pointer)
    - scripts/install-labgen-linux-runner.sh (new)
    - deploy/systemd/labgen-linux-runner.sysusers.conf (new)
  commits: "pending — see repo HEAD after this task's commit"
  pushed_to_github: "pending — standard commit+push workflow"
  git_status: "clean prior to this task's own additions"
  recommended_next_step: "Owner/CEO reviews this acceptance. If satisfied, re-run the Golden Topic #1 (chmod despite correct mode) production pipeline from Topic Brief onward — the feasibility gate that previously blocked it now passes. No Golden Lab content was built this round; that is the next Sprint's scope, not this one's."
```
