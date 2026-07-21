# Linux Golden Lab #1 — Ready for Owner Dogfood v0.1

**Gate**: "Linux Golden Lab #1 Production" CEO/CTO brief
**Final Decision**: `LINUX_GOLDEN_LAB_1_READY_FOR_OWNER_DOGFOOD`
**Date**: 2026-07-20/21
**Executed by**: Claude Code
**Topic**: `linux-chmod-permission-denied-despite-correct-mode`

---

## A. Executive Summary

Golden Topic #1's lab is built, internally rehearsed, non-admin learner smoke-tested,
and has an official-site article drafted. It is **not published**, has **no CTA**, and
is **not on any public allowlist** — Owner dogfood is the next step, not this round's.

The brief's mandatory security preflight (§一) found and fixed a real gap in the
executor's command policy before any lab authoring began: `find`'s `-exec`/`-execdir`/
`-ok`/`-okdir` primaries and `chmod --reference` were never inspected (`_check_path_arg()`
skips any argument starting with `-`), and the `+`-terminated `-exec`/`-execdir` form
doesn't even trip the shell-metachar check — it would run an arbitrary command as the
runner identity. Both are now denied (`find_indirect_execution_denied`,
`chmod_reference_denied`), with regression tests and matching prompt-text updates.

A new verifier type, `path_access_condition`, was added to make a claim no existing
verifier could: "the kernel currently denies/allows real read access to this exact
non-root identity" — via the same privilege-dropped `LinuxCommandExecutor` every
learner command runs through (native `subprocess` `user=`/`group=` kwargs), never
inferred from mode bits, never simulated, and fail-closed if no non-root runner
identity is wired in.

A second real bug was found and fixed while building the fixture: `LinuxWorkspaceManager
.make_directory()`/`write_file()` left newly-created paths root-owned even when
`owner_uid`/`owner_gid` were set — only `create_session()`'s own chown covered the
session root. This meant a genuine non-root process could not `chmod` a directory it
was supposed to own. Fixed by chowning the created path and every directory created
along the way, mirroring `create_session()`'s existing pattern.

---

## B. Security Preflight Result (§一 of the brief)

| Check | Result |
|---|---|
| `find -exec`/`-execdir` (`+` terminator, no `;`) | **Found unblocked, fixed** — `find_indirect_execution_denied` |
| `find -ok`/`-okdir` | **Found unblocked, fixed** — same reason code |
| `chmod --reference`/`--reference=...` | **Found unblocked, fixed** — `chmod_reference_denied` |
| `find` itself deleted/weakened | No — plain `find` (no indirect-exec primary) unaffected, still allowed |
| Sprint scope expanded to fix this | No — fixed as an independent, narrowly-scoped executor policy gap; this lab's own step commands never use `find` at all |
| Regression tests | `tests/test_labgen_linux_find_exec_chmod_reference_gap.py` (6 tests, fail without the fix / pass with it) |
| Prompt text updated to match | Yes — `article_lab_prompt_builder.py._LINUX_COMMAND_CONSTRAINTS` item 4, regression-tested in `test_labgen_phase1_soft_launch.py::TestCommandGenerationConstraints` |

`security_preflight_passed: true`

---

## C. New Verifier Type: `path_access_condition`

| Property | Value |
|---|---|
| Schema fields | `access_operation` (only `"read_file"` in v1), `expected_access` (bool), `expected_errno` (required `"EACCES"` when `expected_access=false`) |
| Runtime mechanism | Reuses the already-tested `LinuxCommandExecutor(runner_uid=, runner_gid=)` — runs `cat <path>` as the real non-root runner, reads returncode/stderr |
| Fail-closed conditions | No `cmd_executor` wired; `cmd_executor._runner_uid` is `None`; `cmd_executor._runner_uid == 0` — all three return `linux.access_check_requires_runner`, never silently check as root |
| ENOENT vs EACCES | Distinguished — a missing path returns "inconclusive" (`linux.access_check_inconclusive`), never treated as a false EACCES match |
| Path safety | Goes through the same `resolve_path()` containment + symlink rejection as every other Linux verifier; absolute paths, `..`, symlinks, and sibling-session escapes are all rejected (`linux.path_escape`) |
| Static validation | `StaticValidator._check_linux_verifiers_safe` requires `access_operation == "read_file"`, `expected_access` set, and `expected_errno == "EACCES"` when `expected_access=false` |
| Tests | `tests/test_labgen_linux_path_access_condition_verifier.py` — 16 tests: real EACCES/allowed scenarios, mismatch detection both directions, 3 fail-closed cases, path-safety (traversal/symlink/absolute/sibling-session), ENOENT-vs-EACCES, 4 StaticValidator schema tests |

---

## D. Workspace Ownership Consistency Fix

`LinuxWorkspaceManager.make_directory()`/`write_file()` now chown newly-created paths
(and every directory created along the way, up to the workspace root) to `owner_uid`/
`owner_gid` when set — previously only `create_session()`'s own chown existed, so any
path created afterward through these two methods stayed root-owned even in an
otherwise-fully-privilege-separated session. This is the same bug class as the
`>`-redirect-file ownership fix from Privilege Separation v0.1 (`lab_kubectl_ws.py`),
found again in a different code path while validating this lab's real chmod-based fix
step. Tests: `tests/test_labgen_linux_workspace_ownership_consistency.py` (7 tests,
includes a positive proof that the runner can now `chmod` a directory it owns).

---

## E. Topic, Lab, and Verifier Design

| Item | Value |
|---|---|
| `topic_id` | `linux-chmod-permission-denied-despite-correct-mode` |
| Topic Brief | `LINUX_CHMOD_PERMISSION_DENIED_TOPIC_BRIEF_v0.1.md` |
| Lab Design Brief | `LINUX_CHMOD_PERMISSION_DENIED_LAB_DESIGN_BRIEF_v0.1.md` |
| `lab_id` | `a1c3f7e2-9b6d-4e12-8f4a-6d2c5e0b7a91` |
| `publish_status` | `draft` (never flipped except transiently during the smoke test — see §G) |
| Steps | 4 (reproduce → rule out file mode → trace the path → fix root cause); cleanup is platform-driven (`linux_cleanup`), not a fifth Step object |
| Learner commands used | `mkdir`, `echo` (redirect), `chmod`, `cat`, `ls`, `stat` — no `find` in this lab's own commands |
| Verifier types used | `linux_file_mode_matches` (existing) + `path_access_condition` (new), 2 per relevant step |
| Excluded subtopics | SELinux/AppArmor, ACLs, owner/group mismatch, shebang/CRLF, read-only-fs/mount, `chmod 777` (explicitly warned against, never presented as a fix) |
| Estimated duration | 10 minutes |

---

## F. Real Internal Rehearsal (admin, production `LinuxRehearsalService`)

| Step | Commands | Verifiers | Result |
|---|---|---|---|
| 1 — reproduce | fixture setup + `cat` attempts | mode=644 ✅, real EACCES ✅ | PASS |
| 2 — rule out file mode | no-op `chmod 644` + `cat` | mode still 644 ✅, still EACCES ✅ | PASS |
| 3 — trace the path | `ls -la`/`stat` up the chain | (observation-only, no verifiers) | PASS |
| 4 — fix root cause | `chmod 700 case/vault` + `cat` | mode=700 ✅, real access restored ✅ | PASS |

Session `LAB_CLOSED`, `cleanup_verified=true`. Real kernel EACCES confirmed in steps 1-2
(`cat: ... Permission denied`, non-zero returncode); real access restoration confirmed in
step 4 (file content actually read back).

---

## G. Real Non-Admin Learner Smoke Test

Executed against a genuinely newly-registered, non-admin account (`lnx-cpd-smoke01`),
using the real production `LabSessionService`/`StepProgressionService` singletons and
the actual WS-terminal command path (`lab_kubectl_ws._run_linux_cmd`) — not the admin
rehearsal's `_safe_exec_command` shortcut, and not an admin bypass of any kind.

**How the publish-status requirement was satisfied without public exposure**:
`StepProgressionService.check_step()` requires `publish_status == PUBLISHED` for any
non-rehearsal session (a real, structural gate, not something this round is allowed to
weaken). The draft's `publish_status` was flipped to `PUBLISHED` for the duration of
the smoke run only, inside a `try/finally` that reverts it unconditionally — including
on the one run that crashed mid-flow (verified: it reverted to `draft` correctly even
then). Throughout, the lab was never added to `LABGEN_ENABLED_LAB_IDS` or
`LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` (the shared `.env` allowlists were scoped to this
one process's in-memory `LabSessionService` instance only, never touching the file or
the live systemd service), so the lab was never actually reachable or listed publicly
at any point.

| Step | Result |
|---|---|
| 1 | 4/8 commands ran; final `cat` → real Permission denied (exit_code 1); both verifiers PASS |
| 2 | No-op `chmod` itself also failed with real Permission denied (traversal blocked even for the redundant chmod) — both verifiers still PASS (mode unchanged, access still denied, as expected) |
| 3 | Observation commands ran clean |
| 4 | `chmod 700` + `cat` succeeded; both verifiers PASS |

Session `LAB_CLOSED`, `cleanup_verified=true`, non-admin throughout. A stale session
from an earlier interrupted run of this same smoke script (before the abort-and-retry
logic was added) was cleaned up via the proper admin API
(`LabSessionService.admin_force_close_session`, not raw JSON editing) after manually
confirming its workspace directory no longer existed on disk.

---

## H. Official Site Article

`docs/labgen/linux/articles/LINUX_CHMOD_PERMISSION_DENIED_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md`
— `status: ready_to_publish_draft`, no Directus record created, no public exposure.
Narrative matches the real rehearsal/smoke commands exactly (including the detail that
the redundant chmod in Step 2 itself fails with Permission denied, not just the `cat`).
CTA uses an "internal preview / future public" placeholder per the brief.

---

## I. Growth Measurement Readiness (not built this round, per brief §九)

| Event | Status |
|---|---|
| `article_page_view`, `lab_start`, `LAB_ACTIVE`, `first_verifier_pass`, `lab_completion`, `cleanup_success` | Existing platform events, already emitted by the session/verifier lifecycle |
| `cta_click`, `next_article_click` | Not yet instrumented — carried forward from Foundation round, explicitly out of scope this round |

---

## J. Series Status Updates

- `LINUX_GROWTH_SERIES_PLAN_v0.1.md` — Order 1 row updated: feasibility gate passed, lab built/rehearsed/smoke-tested, `READY_FOR_OWNER_DOGFOOD`.
- `FIRST_GOLDEN_TOPIC_DECISION_v0.1.md` — §A.0 updated with the resolution and this round's production result.
- `PROJECT_NORTH_STAR_v0.1.md` §16.2 — Linux track status updated to `NONROOT_SANDBOX_READY` / Golden Topic #1 `READY_FOR_OWNER_DOGFOOD`.

---

## K. Tests and Regression

| Check | Result |
|---|---|
| New targeted tests this round | 6 (find/chmod gap) + 16 (path_access_condition) + 7 (ownership consistency) + 4 (prompt-constraint regression) = 33 new tests, all pass |
| Full suite | 5247 passed, 1 skipped, 26 xfailed, 92.48% coverage |
| mypy (all changed files) | 0 errors |
| Existing Linux lab (`6c439064`) re-rehearsed under this round's changes | 4/4 steps PASS, `LAB_CLOSED`, `cleanup_verified=true` — no regression |
| safety-reviewer (A类 — command-policy/security-model change) | No blocking issues found |
| Codex independent review (`codex review --base main`) | No regressions or blocking issues identified |

---

## L. Final Production State

| Check | Result |
|---|---|
| K8s labs/articles | Unchanged |
| Existing Linux lab content/public access | Unchanged |
| Golden Lab #1 published | No — `publish_status=draft` |
| New CTA | None |
| Directus article record | None created |
| `active_session_count` | 0 |
| Residual Linux workspaces (this round's sessions) | 0 |
| `failed_terminal_session_count` | 0 (one own-artifact `LAB_CLEANUP_FAILED` session force-closed via the proper admin API after manual on-disk verification) |
| `linux_runtime.runner_ready` | `true` |
| `.env` allowlists | Unchanged from baseline |
| git status | Only this Sprint's own changes |

---

## M. Anti-Fabrication Self-Check

| Check | Result |
|---|---|
| Security preflight gap found via real command execution, not assumed | ✅ |
| `path_access_condition` uses real kernel returncode/stderr, never simulated | ✅ |
| Ownership bug found by actually building and chmod'ing the fixture, not invented | ✅ |
| Rehearsal and smoke both ran against the real production service singletons | ✅ |
| Non-admin smoke used a genuinely new account and the real WS-terminal code path, no admin bypass | ✅ |
| Publish-status flip was temporary, reverted in `finally`, verified to revert even on crash | ✅ |
| No Golden Lab published, no CTA, no Directus record created | ✅ |
| No K8s or existing-Linux-lab content modified | ✅ |

---

## N. Final Handoff

```yaml
linux_golden_lab_1_handoff:
  overall_status: LINUX_GOLDEN_LAB_1_READY_FOR_OWNER_DOGFOOD

  security_preflight:
    find_secondary_execution_blocked: true
    chmod_reference_escape_blocked: true
    path_boundary_verified: true
    indirect_execution_issues_fixed: true

  topic:
    topic_id: linux-chmod-permission-denied-despite-correct-mode
    title: "chmod 权限位正确，为什么还是 Permission Denied？"
    primary_root_cause: "parent directory (case/vault) missing execute/traverse bit; the file's own mode (644) was never wrong"
    excluded_subtopics: [selinux_apparmor, acl, owner_group_mismatch, shebang_crlf, readonly_fs_mount, chmod_777]

  lab:
    lab_id: a1c3f7e2-9b6d-4e12-8f4a-6d2c5e0b7a91
    publish_status: draft
    estimated_duration: "10 minutes"
    steps: 4
    learner_commands: [mkdir, echo, chmod, cat, ls, stat]
    verifier_types: [linux_file_mode_matches, path_access_condition]

  verifier:
    new_type: path_access_condition
    operation: read_file
    runner_uid: 997
    runner_gid: 997
    real_kernel_access_check: true
    eacces_distinguished_from_enoent: true
    root_fail_closed: true
    cross_session_isolation: true

  rehearsal:
    status: LAB_CLOSED
    steps_passed: "4/4"
    real_eacces: true
    file_mode: "644 (report.txt, unchanged throughout)"
    initial_directory_mode: "600 (case/vault)"
    repaired_directory_mode: "700 (case/vault)"
    access_restored: true
    cleanup_verified: true
    session_id: "2a889966-965b-40c9-b275-057980bc24db"

  smoke:
    username: lnx-cpd-smoke01
    non_admin: true
    runner_uid: 997
    steps_passed: "4/4"
    cleanup_verified: true
    session_status: LAB_CLOSED
    residual_workspace: false

  article:
    path: "docs/labgen/linux/articles/LINUX_CHMOD_PERMISSION_DENIED_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md"
    title: "chmod 权限位正确，为什么还是 Permission Denied？"
    status: ready_to_publish_draft
    created_after_lab_validation: true
    directus_record_created: false
    public_exposure: none

  growth_measurement:
    existing_events: [article_page_view, lab_start, LAB_ACTIVE, first_verifier_pass, lab_completion, cleanup_success]
    missing_events: [cta_click, next_article_click]
    publish_sprint_requirements: "instrument missing events before public publish"

  regression:
    k8s_unchanged: true
    existing_linux_lab_unchanged: true
    runner_ready: true
    health: healthy
    active_sessions: 0
    residual_workspaces: 0

  tests:
    targeted: "33 new tests, 4 new files + 1 modified test file, all pass"
    full_suite: "5247 passed, 1 skipped, 26 xfailed, 92.48% coverage"
    mypy: "0 errors"

  issues:
    blocker: []
    high: []
    medium: []
    low:
      - "cta_click/next_article_click growth events not yet instrumented — needed before public publish, not before dogfood"
      - "10 of 12 Track Contract verifier types still missing (carried forward from Foundation round, unrelated to this Sprint)"

  docs:
    - docs/labgen/linux/LINUX_CHMOD_PERMISSION_DENIED_TOPIC_BRIEF_v0.1.md
    - docs/labgen/linux/LINUX_CHMOD_PERMISSION_DENIED_LAB_DESIGN_BRIEF_v0.1.md
    - docs/labgen/linux/articles/LINUX_CHMOD_PERMISSION_DENIED_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md
    - docs/labgen/linux/LINUX_GOLDEN_LAB_1_READY_FOR_OWNER_DOGFOOD_v0.1.md (this document)
  commits: "pending — see repo HEAD after this task's commit"
  pushed_to_github: "pending — standard commit+push workflow"
  git_status: "clean prior to this task's own additions"
  recommended_next_step: "Owner dogfood of Golden Topic #1 (lab_id a1c3f7e2-9b6d-4e12-8f4a-6d2c5e0b7a91, via admin rehearsal or a temporary publish flip identical to this round's smoke-test method). If satisfied, decide on publish + CTA + Directus article creation — none of which happened this round."
```
