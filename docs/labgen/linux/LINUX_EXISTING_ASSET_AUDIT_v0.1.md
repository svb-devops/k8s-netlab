# Linux Existing Asset Audit — v0.1

**Gate**: Linux Growth-First Track Foundation — Section 一 (现有 Linux 资产审计)
**Date**: 2026-07-20
**Executed by**: Claude Code
**Scope**: Audit only. No code changes, no new lab, no new article.

---

## A. Executive Summary

| Item | Value |
|------|-------|
| Existing lab | `6c439064-4cad-4229-addb-36927128d565` — "Linux Files and Permissions Basics" |
| publish_status | `published` |
| Public article | ❌ **Does not exist** — `art-linux-files-permissions-001` is a `source_article_id` string on the draft record, not a real Directus article; `GET /api/articles/art-linux-files-permissions-001` → 404 |
| Public CTA | ❌ None — no reader-facing entry point; access is a direct authenticated deep link only |
| Auto provisioning | ✅ Local workspace, created on session start (no VM wait — faster than K8s) |
| Verifier coverage | ⚠️ 2 of the Track Contract's 12 required types exist (`file_exists`, `file_mode_matches`) |
| Runtime command surface | ⚠️ 19-command allowlist, filesystem/permissions only — no systemd, process, mount, network, or port commands |
| sudo/root | ❌ Denied outright (`sudo`/`su`/`doas`/`chroot` on the deny list); learner never gets root |
| Isolation model | ⚠️ Local sandboxed directory per session (`/tmp/labgen-linux-sandboxes/{session_id}/`), **not a per-learner VM** |
| Cleanup | ✅ Verifiable, idempotent, fail-closed (taints on failure), forbidden-root guard |
| Trusted reader validation | ✅ 1 external reader passed (G-51), owner-attested "非常顺利" (G-54) |

**Classification: `upgrade_and_include`**

Rationale below (§F).

---

## B. Answers to Required Questions

### B.1 lab_id / title / publish_status / article status / CTA status

```
lab_id:           6c439064-4cad-4229-addb-36927128d565
title:            Linux Files and Permissions Basics
publish_status:   published
domain field:     None (lab record predates the domain field; identified by
                   LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS allowlist membership, not
                   a `domain` column value)
source_article_id: "art-linux-files-permissions-001" (string on the draft record)
article reality:   NOT a real Directus article — /api/articles/art-linux-files-permissions-001
                   returns 404. The 7 public articles (verified live) are all K8s:
                   welcome-to-k8s-netlab + 6 troubleshooting pieces. There is no
                   public Linux article.
cta_enabled:       True (flag on the lab record) — but with no article to host it,
                   this flag has never been exercised by a real reader-facing CTA.
```

**Finding**: the existing Linux lab has never been through the article → CTA → lab funnel that defines this project's growth model. Every session that has touched it (rehearsal, G-51 trusted reader) reached it via a direct authenticated URL, not organic traffic. This is a **pilot-grade technical proof**, not a **growth-funnel asset**.

### B.2 Auto-provisioning for new registered users

Yes, but by a different mechanism than K8s. K8s labs use `LABGEN_AUTO_VM_PROVISION_LAB_IDS` (VM clone + boot wait). Linux has no VM step at all — `get_linux_runtime_adapter()` (`backend/labgen/routes.py:282-291`) lazily creates a local sandbox workspace under `LABGEN_LINUX_SANDBOX_ROOT` (`/tmp/labgen-linux-sandboxes`) the first time any learner in `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` starts a session. There is no clone/boot latency — this is a genuine advantage over K8s for a growth funnel (near-zero time-to-first-command), worth stating explicitly as a `growth_value` point.

### B.3 Verifier: real state check or output pattern-matching?

**Real state check**, for the two types that exist. `LinuxVerifyClientAdapter.file_exists()` and `file_mode_matches()` (`backend/labgen/linux_verifier_client.py:150,238`) stat the real filesystem inside the sandbox — they do not parse command stdout, do not trust learner-created "done" files, and do not replay frontend command history. This matches the Track Contract's anti-pattern list (§C).

**Gap**: the Track Contract (per the CEO/CTO brief) names 12 verifier types as the baseline vocabulary:

| Verifier type | Status |
|---|---|
| `file_exists` | ✅ Exists, tested |
| `file_mode_matches` (≈ `file_mode_equals`) | ✅ Exists, tested |
| `systemd_unit_state_equals` | ❌ Does not exist |
| `command_exit_code_equals` | ❌ Does not exist |
| `file_content_contains` | ❌ Does not exist |
| `file_owner_equals` | ❌ Does not exist |
| `file_group_equals` | ❌ Does not exist |
| `port_listening` | ❌ Does not exist |
| `process_running` | ❌ Does not exist |
| `mount_exists` | ❌ Does not exist |
| `filesystem_usage_condition` | ❌ Does not exist |
| `path_accessible_as_user` | ❌ Does not exist |

10 of 12 types are missing. This is the single largest gap between "current asset" and "Track Contract compliant."

### B.4 Cleanup: verifiable? restores original state?

Yes on both counts. `LinuxCleanupAdapter` (`backend/labgen/linux_cleanup.py`):
- Validates `cleanup_path` is under `workspace_root` before any delete (path traversal guard)
- Refuses to touch a fixed list of forbidden roots (`/`, `/home`, `/tmp` top-level, `/etc`, `/var`, `/root`, `/proc`, `/sys`, `/dev`, `/boot`, `/usr`, `/bin`, `/sbin`)
- Runs a residual scan after delete to confirm the workspace is actually empty (not just "delete call returned success")
- Fails closed: a cleanup failure taints the session rather than silently reporting success
- Idempotent: a second cleanup call on an already-gone workspace is a no-op success, not an error

This is architecturally sound and matches the Track Contract's cleanup requirements (§D) as written. No gap here.

### B.5 Does the experiment use root/sudo? What is the privilege boundary?

**No root, no sudo, ever.** `linux_command_executor.py` denies `sudo`/`su`/`doas`/`chroot` outright (`DENIED_COMMANDS`), runs every command as `subprocess.run(argv, shell=False, cwd=workspace_root, env={"PATH": "/usr/bin:/bin", "HOME": workspace_root})` with no shell interpretation, and validates every path argument stays inside `workspace_root`. The allowlist (`ALLOWED_COMMANDS`) is 19 commands, and it is exhaustively **filesystem/permissions only**:

```
pwd, ls, mkdir, touch, echo, cat, chmod, stat, find, rm, cp, mv, wc, head, tail, grep, diff, test, [
```

Explicitly denied (not just "not on the allowlist" — actively blocked): `systemctl`, `service`, `mount`, `umount`, `ps`/`kill`/`killall`/`pkill`, `ip`/`iptables`, `curl`/`wget`/`ssh`, `docker`/`kubectl`, `awk`/`sed`, all shells, all interpreters, all package managers.

**Consequence for topic selection (see §F and the Golden Topic decision)**: any topic requiring systemd, process management, mounts, filesystems beyond the sandbox, network, or ports is **not executable today** without new runtime work. The CEO/CTO brief's own example topics (systemd failure, df/du mismatch, mount failure, port conflict) fall almost entirely outside the current command surface. This is flagged, not silently worked around — the brief explicitly forbids a runtime overhaul this round.

### B.6 Does it meet the current strictest publish gate?

Partially. It passed the gate that existed when it was published (static validation, real rehearsal, non-admin smoke, owner dogfood via G-51/G-54, `cleanup_verified=true`, no BLOCKER/HIGH). It does **not** meet the *new* gate implied by this brief's growth-funnel model, because that gate requires "article 与 lab 验证同步" (article and lab verified together) — and there is no article. Under the new Track Contract (§C.2) this lab cannot be called "gate compliant" for growth purposes until a real article exists and is verified alongside it.

### B.7 Does the source article have clear search intent and an engineering-judgment angle?

**N/A — no source article exists to evaluate.** The `source_article_id` field is a string with no backing content. This is not a content-quality gap; it is a missing-content gap.

### B.8 Is it worth folding into the new growth sub-track?

Yes, with upgrade — see classification below.

---

## C. Isolation Model Comparison (K8s vs. Linux)

| Dimension | K8s domain | Linux domain (current) |
|---|---|---|
| Isolation unit | Dedicated Proxmox VM (linked clone, VMID 500-599) | Local filesystem directory under `/tmp/labgen-linux-sandboxes/{session_id}/` on the same host as the API process |
| Root/sudo | Full root inside the VM (VM is disposable) | Denied entirely |
| systemd availability | Yes (K3s runs as systemd units inside the VM) | No — no VM, no init system, no service manager |
| Blast radius of a bug in the sandbox | Contained to one disposable VM | Contained to one host directory, enforced by path-traversal checks in application code, not OS-level isolation (no cgroups/seccomp/namespaces — explicitly noted as a spike limitation in `linux_command_executor.py`'s own docstring) |
| Provisioning latency | ~1-5 min (clone + boot + K3s ready) | Near-zero (mkdir) |

**This is a real architectural difference, not a maturity gap that will close by itself.** The Linux runtime's isolation depends entirely on the command allowlist + path validation in `linux_command_executor.py` holding up; there is no VM-level backstop the way K8s has one. This matters directly for Track Contract §A (Runtime) and is called out there rather than glossed over.

---

## D. Prior Test / Rehearsal / Pilot Evidence

| Evidence | Source | Result |
|---|---|---|
| Internal rehearsal | `LINUX_INTERNAL_REHEARSAL_BRIDGE_RESULT_v0.1.md`, `LINUX_E2E_INTERNAL_REHEARSAL_ACCEPTANCE_RESULT_v0.1.md` | PASS |
| Non-admin learner smoke | `LINUX_LEARNER_RUNTIME_E2E_SMOKE_ACCEPTANCE_RESULT_v0.1.md` | PASS |
| First trusted external reader (G-51) | `LINUX_TRUSTED_READER_PILOT_RESULT_v0.1.md`, `LINUX_TRUSTED_READER_PILOT_EXIT_REVIEW_RESULT_v0.1.md` | PASS — 4/4 steps, session closed, cleanup verified |
| Owner onsite attestation (G-54) | `LINUX_PILOT_FEEDBACK_ATTESTATION_v0.1.md` | "测试非常顺利" (USER_ONSITE_ATTESTATION, not a 10-Q form) |
| Independence instrumentation | — | Not fully instrumented — no step-level timestamps; classified `USER_OBSERVED_SMOOTH_COMPLETION`, tracked as LOW-004 (open) |
| Test suite | `tests/test_labgen_linux_*.py` (11 files) | All passing as of this audit (confirmed via full suite run 2026-07-20, part of the K8s nav work earlier this session) |

No fabricated claims are made about qualitative feedback beyond what these documents already recorded — this audit does not restate the second-reader gate (removed by this brief, §Track Contract E) and does not claim it was ever run.

---

## E. Growth-Value Assessment (not just technical soundness)

| Factor | Assessment |
|---|---|
| Content-market fit signal | None yet — no article means no real-world search/CTA data exists for this topic |
| Funnel readiness | 0% — none of the funnel stages (article_page_view → CTA click → lab_start → …) exist for this asset |
| Reusable technical asset value | High — cleanup model, sandbox isolation, and the 2 existing verifier types are solid, reusable primitives for *any* filesystem/permissions-themed Linux lab, not just this one |
| Reusable verifier gap | 10 of 12 contract verifier types absent — a real, non-trivial backlog for any future Linux lab beyond filesystem basics |
| Topic durability | "Files and Permissions Basics" is evergreen, high-frequency beginner pain — a defensible P1/P2 candidate in its own right once wrapped with a real article (see Topic Radar, `chmod-777-still-permission-denied` overlaps conceptually) |

---

## F. Classification Decision

**`upgrade_and_include`**

Not `include_as_is`, because: no public article, no CTA path, no funnel instrumentation, and only 2 of 12 contract-level verifier types exist. Calling it "as-is ready" would misrepresent a technically-sound pilot as a growth asset it has never been.

Not `legacy_outside_new_series`, because: the underlying runtime, cleanup, and verifier primitives are real, reusable, and already proven with one independent external reader — discarding it would waste validated infrastructure and the one genuine pilot data point this track has.

**Upgrade path** (tracked as backlog, not committed to a Sprint by this document): write a real public article for the existing content, wire a CTA, and decide whether this becomes the Golden Topic itself or ships alongside it as the "already-proven" second entry once the funnel exists. This decision is deferred to the Golden Topic document (§六) and the Series Plan (§三) — this audit does not pre-select it.

---

## G. Anti-Fabrication Self-Check

| Check | Result |
|---|---|
| Public article existence claim verified live (curl, not assumption) | ✅ 404 confirmed |
| Verifier type inventory read from source, not recalled from memory | ✅ `linux_verifier_client.py` read directly |
| Command allowlist/denylist read from source | ✅ `linux_command_executor.py` read directly |
| No claim of "second reader passed" (that pilot was never run) | ✅ Not claimed |
| No qualitative feedback fabricated beyond recorded attestation | ✅ |
| No production code modified in this audit | ✅ |
| No new lab, article, or account created | ✅ |
