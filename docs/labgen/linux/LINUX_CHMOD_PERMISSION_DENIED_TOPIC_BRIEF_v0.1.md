# Linux Chmod Permission Denied — Topic Brief v0.1

**Golden Topic #1**, per `LINUX_SANDBOX_NONROOT_RUNTIME_ACCEPTANCE_v0.1.md` (runtime blocker
resolved) and the CEO/CTO "Linux Golden Lab #1 Production" brief.

```yaml
topic_id: linux-chmod-permission-denied-despite-correct-mode
search_intent: >
  "chmod 644 but still permission denied", "chmod correct but can't read file linux",
  "file permissions correct but access denied" — engineers who have already checked
  and fixed the target file's own mode bits and are stuck because the real cause is
  one level up the path, not on the file itself.
target_audience: >
  Junior-to-mid engineers and sysadmins debugging a real permission error for the
  first time without a senior nearby; anyone whose mental model of "chmod" stops at
  "the file's own bits" and has never had to reason about directory execute/traverse
  permission as a *distinct* dimension from file read/write permission.
real_engineering_pain: >
  This is one of the most common "the fix looks right, the bug is still there" traps
  in Linux permission debugging: `ls -l file` shows perfectly reasonable bits (0644),
  yet `cat file` fails with Permission denied. Nothing about the file itself is wrong.
  The missing piece — that traversing into a directory requires its own execute bit,
  independent of the file's own permissions — is one of the least intuitive parts of
  the Unix permission model and is under-covered relative to how often it bites people.
existing_content_gap: >
  Confirmed via LINUX_EXISTING_ASSET_AUDIT_v0.1.md: no public article on this domain
  exists at /api/articles/art-linux-files-permissions-001 (404, verified live). The
  existing "Linux Files and Permissions Basics" lab teaches file-level chmod only —
  it never touches directory execute bits or the "correct file mode, still denied"
  trap. This topic fills that gap rather than duplicating existing content.
article_angle: >
  Walk through a real incident narrative (see lab_conversion_trigger below) from the
  learner's naive first assumption ("the mode must still be wrong, let me chmod it
  again") through the actual diagnostic path (ls -ld up the directory chain) to the
  real fix (restore the parent directory's execute bit — never chmod 777, never
  touch the file's own already-correct mode).
lab_conversion_trigger: >
  "In a live Linux environment: file permissions are already correct, but the parent
  directory still won't let you access it." — reproduce this hands-on rather than
  just reading about it, using the platform's real non-root sandbox runner (UID/GID
  997) so the Permission denied the learner sees is a genuine kernel EACCES, not a
  scripted message.
primary_root_cause: >
  Parent directory (`case/vault/`) is missing the execute (traverse) bit for the
  runner identity — mode 0600 instead of 0700+. The file itself (`report.txt`,
  mode 0644) has never been wrong.
engineering_judgment_chain: |
  target file's mode is already correct (0644)
  → real read still fails with Permission denied
  → re-chmod'ing the file itself cannot solve this (nothing wrong with it)
  → Linux path access requires traverse/execute permission on every directory
    component along the path, independent of the target's own permissions
  → check the immediate parent directory's permissions
  → find the directory missing the execute bit
  → fix only that root cause (restore execute, e.g. mode 0700)
  → re-verify read access under the same non-root identity that failed before
source_signals: >
  Scored 8.15/10 in LINUX_GROWTH_FIRST_TOPIC_RADAR_v0.1.md (highest of 10 candidates
  evaluated via 10 real WebSearch calls) — high recurring search volume for "chmod
  correct but permission denied" variants, low existing content saturation, and a
  root cause that is genuinely non-obvious to the target audience (unlike e.g. an
  ownership mismatch, which is comparatively well-covered elsewhere).
excluded_subtopics:
  - SELinux / AppArmor (MAC systems) — different enforcement layer entirely, would
    dilute the DAC-specific lesson this topic teaches.
  - ACLs (getfacl/setfacl) — a real but separate permission dimension; conflating
    it with directory execute bits would confuse the core lesson.
  - File owner/group mismatch — a different, already well-covered failure mode;
    this topic assumes ownership is already correct and isolates the traverse-bit
    lesson specifically.
  - shebang / line-ending (CRLF) script-execution errors — unrelated failure class
    (exec format, not DAC permission).
  - Read-only filesystem / mount option causes — different root cause, would blur
    the single lesson this lab teaches.
  - chmod 777 as a "fix" — explicitly excluded as an anti-pattern the article and
    lab both actively warn against, never presented as a valid resolution path.
```

## Security preflight (completed before any lab authoring — see §一 of the CEO brief)

Ran against the real production `LinuxCommandExecutor` policy layer before designing
the lab, per the brief's mandatory security preflight:

- **Found a real gap**: `find`'s `-exec`/`-execdir`/`-ok`/`-okdir` primaries and
  `chmod --reference` were not blocked — `_check_path_arg()` skips any argument
  starting with `-`, so these were never inspected. The `+`-terminated form of
  `-exec`/`-execdir` doesn't even require a `;` argument, so it doesn't trip the
  shell-metachar check either. Confirmed via a live repro: `find . -exec echo PWNED +`
  executed successfully (not policy-rejected) before the fix.
- **Fixed**: `linux_command_executor.py` now rejects `find` argv containing a bare
  `-exec`/`-execdir`/`-ok`/`-okdir` token (`find_indirect_execution_denied`), and
  `chmod` argv containing `--reference`/`--reference=...` (`chmod_reference_denied`).
  Regression tests: `tests/test_labgen_linux_find_exec_chmod_reference_gap.py`
  (fails without the fix, passes with it). Prompt text
  (`article_lab_prompt_builder.py._LINUX_COMMAND_CONSTRAINTS`) updated to match,
  with a matching regression test in `test_labgen_phase1_soft_launch.py`.
- This lab's learner-visible commands only use `cat`, `ls`, `stat`, `chmod`, `pwd`
  (per the brief's §一 requirement) — `find` is not used in the lab steps at all,
  so the gap above, while real and fixed, was not itself reachable by this specific
  lab's step commands. It was fixed anyway because it is a real sandbox-escape-class
  gap independent of this lab.

Security preflight: **PASSED** (gap found, fixed, regression-tested — not glossed over).
