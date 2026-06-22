# Linux Domain Contract Schema Extension Result v0.1

**Date**: 2026-06-21  
**Operator**: Claude Code acting as senior dev + ops  
**Status**: LINUX_DOMAIN_CONTRACT_SCHEMA_READY_WITH_NOTES  
**Design Gate Reference**: `LINUX_DOMAIN_PROOF_DESIGN_GATE_v0.1.md`  
**No real secrets in this document.**

---

## A. Executive Summary

| Item | Value |
|------|-------|
| Final Decision | **LINUX_DOMAIN_CONTRACT_SCHEMA_READY_WITH_NOTES** |
| Schema added | LabDomainType enum, LinuxVerifyType enum, LinuxVerifyTemplate, LinuxSandboxPolicy, CleanupLinuxWorkspace |
| Validator support | StaticValidator Linux domain path (8 checks + publish gate) |
| H-01 fixed | `_pick_target_domain()` now returns `TargetDomain.LINUX` for Linux articles |
| H-02 fixed | `StubFeasibilityClassifier` detects chmod/chown/file permissions/filesystem signals |
| Linux runtime implemented | **No** — schema-only; publish always blocked |
| K8s path changed | **No** — K8s validation path is unchanged; all existing K8s tests pass |
| Tests added | 60 new tests (`tests/test_labgen_linux_domain_schema.py`) |
| Full suite | 3797 passed, 93.40% coverage |
| Security scans | bandit PASS (no new findings), pre-commit CLEAN |

---

## B. North Star Alignment

| Principle | Status |
|-----------|--------|
| 读了能练，练完即熟 | ✅ Linux schema enables future Linux labs on this pipeline |
| Linux proof supports multi-domain portability | ✅ General Experiment Core + Replaceable Domain Contract pattern realized |
| K8s remains validated domain proof | ✅ K8s path fully unchanged, all K8s tests pass |
| No public launch | ✅ Linux labs cannot be published (runtime blocked) |
| No live LLM | ✅ Zero LLM calls |
| No general reader article upload | ✅ Not opened |
| No production VMID 500-599 touched | ✅ Confirmed |

---

## C. Schema Changes

### C-1. `LabDomainType` enum (`backend/labgen/models.py`)

New enum for the published-lab layer. Separate from `TargetDomain` (article pipeline).

```python
class LabDomainType(str, Enum):
    K8S = "k8s"        # runtime implemented; labs publishable
    LINUX = "linux"    # schema-ready v0.1; runtime pending; publish blocked
    DOCKER = "docker"  # schema draft only
    NETWORKING = "networking"
    DATABASE = "database"
    CICD = "cicd"
    UNKNOWN = "unknown"
```

`LabDraft.target_domain` defaults to `LabDomainType.K8S` — all existing labs are backward compatible.

### C-2. `LinuxVerifyType` enum (`backend/labgen/models.py`)

Five workspace-scoped, filesystem-only verify primitives. No shell execution.

```python
class LinuxVerifyType(str, Enum):
    LINUX_FILE_EXISTS = "linux_file_exists"
    LINUX_DIRECTORY_EXISTS = "linux_directory_exists"
    LINUX_FILE_CONTENT_MATCHES = "linux_file_content_matches"
    LINUX_FILE_MODE_MATCHES = "linux_file_mode_matches"
    LINUX_NO_RESIDUAL_FILES = "linux_no_residual_files"
```

### C-3. `LinuxVerifyTemplate` model (`backend/labgen/models.py`)

Parallel to K8s `VerifyTemplate`, but Linux-specific:

- `target_path`: workspace-relative path (no absolute paths, no `..` traversal)
- `expected_content`: required for `linux_file_content_matches`
- `expected_mode`: required for `linux_file_mode_matches` (e.g. "644", "755")
- `workspace_relative_only`: model-level invariant — always True; `field_validator` enforces this
- Fields: `timeout_seconds`, `max_output_bytes`, `description`, `failure_hint`, `blocking_level_on_fail`

### C-4. `LinuxSandboxPolicy` model (`backend/labgen/models.py`)

Captures the runtime sandbox contract for Linux domain labs:

- `runtime_type`: `linux_container` | `linux_vm` | `sandboxed_shell` (default: `linux_container`)
- `base_image`: container base image (default: `ubuntu:22.04`)
- `shell`: `bash`
- `learner_user`: `learner`
- `workspace_root` / `working_directory`: default `/home/learner/workspace`
- `allow_network`: default **False** (enforced by StaticValidator)
- `allow_root`: default **False** (enforced by StaticValidator)
- `denied_commands`: default includes sudo/su/systemctl/service/apt/ssh/curl/wget
- `forbidden_paths`: default includes `/etc`, `/root`, `/var`, `/proc/sys`, `/sys`, `/dev`, `/boot`

### C-5. `CleanupLinuxWorkspace` model (`backend/labgen/models.py`)

Captures the cleanup contract for Linux domain labs:

- `workspace_root`: must not be empty or a forbidden path
- `cleanup_paths`: must all be within `workspace_root`
- `kill_session_processes`, `revoke_credentials`, `close_terminal`: default True
- `residual_checks`: must include all 4 required keys (workspace_removed_or_empty, no_session_owned_processes, credentials_revoked, terminal_closed)
- `taint_on_cleanup_failure`: model-level invariant — always True; `field_validator` enforces this
- `forbidden_cleanup_paths`: default includes `/`, `/home`, `/tmp`, `/etc`, `/var`, `/root`

### C-6. `LabDraft` new fields (`backend/labgen/models.py`)

```python
target_domain: LabDomainType = LabDomainType.K8S     # backward compat default
linux_sandbox_policy: Optional[LinuxSandboxPolicy] = None
linux_cleanup: Optional[CleanupLinuxWorkspace] = None
```

### C-7. `Step` new field (`backend/labgen/models.py`)

```python
linux_verify: list[LinuxVerifyTemplate] = Field(default_factory=list)
```

K8s steps continue to use `verify: list[VerifyTemplate]`. Linux steps use `linux_verify`. Both fields coexist; cross-domain mixing is rejected by StaticValidator.

---

## D. Validation Rules

### D-1. StaticValidator Linux path (`backend/labgen/static_validator.py`)

When `draft.target_domain == LabDomainType.LINUX`, `validate()` calls `_validate_linux()` instead of `_validate_k8s()`. This ensures K8s-specific checks (namespace hardcoding, K8s cleanup, helm, NodePort, CRD) do not run against Linux labs.

Linux validation checks:

| Check ID | What it validates | Blocking Level |
|----------|------------------|----------------|
| `content.no_placeholders` | No TODO/TBD/PLACEHOLDER in title/description/steps | PUBLISH_BLOCKING |
| `explain.verified_if_published` | published_to_student=True requires admin_verified=True | PUBLISH_BLOCKING |
| `linux.no_k8s_verifiers` | Linux labs must not contain K8s VerifyTemplate entries | PUBLISH_BLOCKING |
| `linux.sandbox_policy_required` | linux_sandbox_policy must be present | PUBLISH_BLOCKING |
| `linux.cleanup_required` | linux_cleanup must be present | PUBLISH_BLOCKING |
| `linux.verifiers_safe` | target_path: not empty, no `..`, no forbidden system path; expected_content/expected_mode present when required | PUBLISH_BLOCKING |
| `linux.sandbox_safe` | allow_root=False, allow_network=False, workspace_root not in forbidden paths | PUBLISH_BLOCKING |
| `linux.cleanup_safe` | workspace_root not forbidden, cleanup_paths within workspace_root, all 4 residual_checks present | PUBLISH_BLOCKING |
| `pollution.known` | NAMESPACE_ONLY if sandbox present; UNKNOWN otherwise | PUBLISH_BLOCKING |
| `linux.publish_blocked_until_runtime` | Always FAILS — Linux runtime not yet implemented | PUBLISH_BLOCKING |

K8s validation: All existing 14 checks run unchanged + new `k8s.no_linux_verifiers` check (K8s labs must not contain linux_verify entries).

### D-2. ArticleDraftValidator (`backend/labgen/static_validator.py`)

No changes. Linux domain is NOT blocked by `_check_cloud_domain_blocked_v1` (only CLOUD is blocked). Linux articles can proceed through the article draft pipeline — the publish block is at StaticValidator (LabDraft level), not at ArticleDraftValidator (ArticleDraftLabContract level).

### D-3. `_ALLOWED_DRAFT_DOMAINS_V1` (`backend/labgen/article_models.py`)

Updated from `{K8S}` to `{K8S, LINUX}` to accurately reflect that Linux is schema-ready.

### D-4. H-01 fix: `_pick_target_domain` (`backend/labgen/article_draft_service.py`)

```python
# Before
if TargetDomain.K8S in candidates:
    return TargetDomain.K8S
if candidates:
    return candidates[0]  # Linux falls to UNKNOWN via this path

# After
if TargetDomain.K8S in candidates:
    return TargetDomain.K8S
if TargetDomain.LINUX in candidates:
    return TargetDomain.LINUX  # Linux now correctly returned
if candidates:
    return candidates[0]
```

### D-5. H-02 fix: Linux signal detection (`backend/labgen/stub_feasibility_classifier.py`)

Added `_LINUX_SIGNALS` (7 patterns) to detect Linux articles:

```python
_LINUX_SIGNALS: list[re.Pattern] = [
    re.compile(r"(?i)\b(chmod|chown|chgrp)\b"),
    re.compile(r"(?i)\b(file\s+permissions?|directory\s+permissions?|linux\s+permissions?)\b"),
    re.compile(r"(?i)\b(inodes?|symbolic\s+links?|hard\s+links?|file\s+ownership)\b"),
    re.compile(r"(?i)\b(bash\s+script|shell\s+script|/etc/passwd|/etc/shadow|/proc/)\b"),
    re.compile(r"(?i)\b(linux\s+file|linux\s+directory|linux\s+process|linux\s+user)\b"),
    re.compile(r"(?i)\b(ext4|ext3|xfs|btrfs|filesystem|file\s+system)\b"),
    re.compile(r"(?i)(ls\s+-l|stat\s+\S|touch\s+\S|mkdir\s+\S|rm\s+\S|find\s+\.)"),
]
```

Safety invariant: Linux signals only added if K8s hits = 0 (prevents K8s articles from being re-classified as Linux, since K8s terms overlap with Linux, e.g. "namespace").

Linux domain feasibility result:
- If operable signals present → `DIRECTLY_LAB_READY`
- Otherwise → `PARTIALLY_LAB_READY`
- Always includes `missing_requirements=["linux runtime adapter", "linux verifier execution"]`
- Always `verifier_feasibility=NEEDS_NEW_PRIMITIVE`

---

## E. Minimal Linux Contract Example (Linux Files and Permissions Basics)

This is a schema-valid example only — not published, not in catalog.

```python
steps = [
    Step(
        step_id="step_1",
        # Create workspace file
        commands=["mkdir -p workspace", "echo 'hello world' > workspace/hello.txt"],
        linux_verify=[
            LinuxVerifyTemplate(
                verify_id="step1_v1",
                type=LinuxVerifyType.LINUX_FILE_EXISTS,
                target_path="workspace/hello.txt",
            ),
            LinuxVerifyTemplate(
                verify_id="step1_v2",
                type=LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES,
                target_path="workspace/hello.txt",
                expected_content="hello world",
            ),
        ],
        ...
    ),
    Step(
        step_id="step_2",
        # Set file permissions
        commands=["chmod 644 workspace/hello.txt"],
        linux_verify=[
            LinuxVerifyTemplate(
                verify_id="step2_v1",
                type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                target_path="workspace/hello.txt",
                expected_mode="644",
            ),
        ],
        ...
    ),
]

draft = LabDraft(
    target_domain=LabDomainType.LINUX,
    linux_sandbox_policy=LinuxSandboxPolicy(
        workspace_root="/home/learner/workspace",
    ),
    linux_cleanup=CleanupLinuxWorkspace(
        workspace_root="/home/learner/workspace",
        cleanup_paths=["/home/learner/workspace"],
    ),
    steps=steps,
    ...
)
```

StaticValidator result: 1 failure (`linux.publish_blocked_until_runtime`), all other checks PASS. Schema is valid and expressible.

---

## F. K8s Regression

| Assertion | Result |
|-----------|--------|
| K8s lab `target_domain` defaults to K8S | ✅ LabDomainType.K8S (backward compat) |
| K8s `validate()` runs all 14 existing checks + new `k8s.no_linux_verifiers` | ✅ Confirmed |
| Clean K8s lab passes `k8s.no_linux_verifiers` | ✅ Confirmed |
| K8s lab not blocked by `linux.publish_blocked_until_runtime` | ✅ Confirmed |
| K8s lab with missing cleanup fails `cleanup.declared` | ✅ Confirmed |
| Lab 5 (catalog) publish behavior unchanged | ✅ Confirmed — 5 K8s labs, no Linux labs |
| 3737 pre-existing tests all pass | ✅ 3797 total (3737 pre-existing + 60 new) |

---

## G. Limitations

- **Linux runtime not implemented**: No container or VM provisioning for Linux labs.
- **Linux verifier execution not implemented**: LinuxVerifyTemplate is schema-only; no runtime check execution.
- **Linux lab publish not enabled**: `linux.publish_blocked_until_runtime` always fails. No Linux lab can enter the learner catalog.
- **Linux trusted reader pilot not started**: No learner has run a Linux lab (runtime not ready).
- **LLM still disabled**: `LABGEN_LLM_PROVIDER_MODE=fake_only`. No live LLM calls.
- **`linux_command_output_contains`** not added: The design gate flagged this as restricted/future (requires shell execution, not filesystem read). Not included in v0.1.
- **K3s-to-General-Core refactor not done**: `NamespaceLifecyclePort`, `K8sVerifierClientPort`, `NamespaceAdapterKind` remain K8s-specific (BLOCKERs B-03/B-04/B-05 from design gate). These are addressed in Task 2 (Runtime Adapter Spike).

---

## H. Tests

| Category | Tests Added |
|----------|-------------|
| A. LinuxVerifyType | 9 (all 5 primitives, invariant enforcement, domain cross-rejection) |
| B. LinuxSandboxPolicy | 10 (defaults, safe workspace, 6 unsafe scenario rejections, base_image) |
| C. CleanupLinuxWorkspace | 8 (valid cleanup, forbidden roots, residual checks, invariants) |
| D. StaticValidator Linux | 15 (minimal contract, missing policy, unsafe paths, publish gate, full example) |
| E. Article pipeline Linux | 6 (H-01, H-02, ArticleDraftValidator not blocking Linux) |
| F. K8s regression | 12 (domain default, all K8s checks present, no cross-contamination) |
| **Total new** | **60** |
| Full suite | 3797 passed |
| Coverage | 93.40% (≥ 92% requirement met) |
| bandit | PASS (no new findings; pre-existing image_resolver.py verify=False documented) |
| pre-commit | PASS |
| pre-push | Will run at push (3797 tests + 8-item security scan) |

---

## I. Issue Triage

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| B-01 | ~~BLOCKER~~ | `VerifyType` enum K8s-only | ✅ RESOLVED — `LinuxVerifyType` added |
| B-02 | ~~BLOCKER~~ | `CleanupNamespace` K8s-only | ✅ RESOLVED — `CleanupLinuxWorkspace` added |
| B-03 | HIGH | `NamespaceLifecyclePort` K8s-only interface | OPEN — Task 2 |
| B-04 | HIGH | `K8sVerifierClientPort` K8s-only | OPEN — Task 2 |
| B-05 | HIGH | `NamespaceAdapterKind` only STUB/K8S | OPEN — Task 2 |
| H-01 | ~~HIGH~~ | `_pick_target_domain()` ignores LINUX | ✅ RESOLVED |
| H-02 | ~~HIGH~~ | `StubFeasibilityClassifier` no Linux detection | ✅ RESOLVED |
| M-01 | MEDIUM | `LabSessionState.namespace` K8s-semantic name | OPEN — cosmetic; address in Task 3+ |
| M-02 | MEDIUM | `LabSessionStatus` names include NAMESPACE_* | OPEN — cosmetic; no behavior impact |
| NOTE-01 | NOTE | Docker daemon availability on Proxmox host not confirmed | OPEN — ops ticket OPS-LINUX-001 |

---

## J. Final Decision

**LINUX_DOMAIN_CONTRACT_SCHEMA_READY_WITH_NOTES**

The schema layer is complete. Linux domain labs can be expressed, authored, and validated at the schema level. The two remaining NOTES are:

1. Linux runtime (BLOCKERs B-03/B-04/B-05) — deliberately deferred to Task 2 (Runtime Adapter Spike); publish gate enforces this.
2. Docker daemon ops ticket (NOTE-01) — must be resolved before Task 5 (Container Sandbox Provisioning).

---

## K. Recommended Next Step

**Linux Runtime Adapter Spike (Task 2 of 7)**

Add `LINUX` to `NamespaceAdapterKind`, create `LinuxContainerLifecycleAdapter` (skeleton, `NotImplementedError`), add `linux` to `RuntimeMode` selection logic, and add `LinuxVerifierClientPort` interface (skeleton). No actual container execution — this is the adapter interface layer that unblocks Task 3-7.

Exit criteria for Task 2:
- `NamespaceAdapterKind.LINUX` exists
- `select_adapter(LINUX)` returns `LinuxContainerLifecycleAdapter`
- K8s adapter selection unchanged
- 0 new production runtime paths activated
- Tests confirm stub/k8s still selected correctly

---

*This document is the authoritative result record for Linux Domain Contract Schema Extension v0.1.*
