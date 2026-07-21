# Linux Chmod Permission Denied — Lab Design Brief v0.1

Companion to `LINUX_CHMOD_PERMISSION_DENIED_TOPIC_BRIEF_v0.1.md`.

## Fixture

```
workspace/
└── case/
    ├── incident-note.txt
    └── vault/
        └── report.txt
```

Initial state (built by the platform, not the learner):

| Path | Owner/Group | Mode | Content |
|---|---|---|---|
| `case/` | runner (997/997) | 0755 | — |
| `case/incident-note.txt` | runner | 0644 | narrative text only — a hint, never verifier evidence |
| `case/vault/` | runner | **0600** (missing execute bit — the root cause) | — |
| `case/vault/report.txt` | runner | 0644 (already correct — never wrong) | fixed onboarding-report text |

Learner effective UID/GID: 997/997 (`labgen-linux-runner`) — real non-root identity,
same one every other Linux lab uses since Privilege Separation v0.1.

## Steps (5)

1. **Reproduce the surface symptom** — read `case/incident-note.txt`; attempt to read
   `case/vault/report.txt`; get a real `Permission denied`. Verifiers independently
   confirm (a) `report.txt` mode is 0644 and (b) the learner's real read access is
   currently denied — via `path_access_condition(expected_access=false, expected_errno=EACCES)`.
2. **Rule out the file's own mode** — learner runs `chmod 644 case/vault/report.txt`
   (a no-op, mode is already correct) and confirms the read *still* fails. Verifiers
   confirm mode is still 0644 and access is still denied — proving re-chmod'ing the
   file itself cannot be the fix.
3. **Trace the path** — learner runs `ls -ld case case/vault` / `stat` up the
   directory chain and identifies `case/vault` as missing the execute bit.
4. **Fix the actual root cause** — learner runs `chmod 700 case/vault` (never 777).
   Verifiers confirm `vault` mode is now 0700 and, critically, that read access is
   now genuinely restored — `path_access_condition(expected_access=true)`.
5. **Cleanup** — platform-driven, no learner commands; workspace removed, residual
   scan empty.

## Verifier plan

Reuses `linux_file_exists`, `linux_file_mode_matches` (existing types) plus the new
`path_access_condition` type (this Sprint) for the two claims neither existing type
can make: "the kernel currently denies real read access to this exact non-root
identity" and, later, "the kernel currently permits it" — both are live kernel
checks executed via the same privilege-dropped `LinuxCommandExecutor` every learner
command runs through (native `subprocess` `user=`/`group=` kwargs, not `preexec_fn`;
see Privilege Separation v0.1 for why that mattered here specifically), never
inferred from mode bits alone and never simulated.

Fail-closed contract (enforced in `linux_verifier_client.py`, not just documented):
`path_access_condition` refuses to run at all — returns
`linux.access_check_requires_runner` — if the wired `LinuxCommandExecutor` has no
runner identity or the identity is UID/GID 0. There is no path by which this
verifier can silently check access as root.

## Publish status

`publish_status: draft`. Not added to any public allowlist. No CTA. No Directus
article record. Existing Linux lab and K8s domain untouched.

## Estimated duration

8–12 minutes (per brief).
