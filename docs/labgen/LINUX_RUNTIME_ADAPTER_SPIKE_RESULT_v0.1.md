# Linux Runtime Adapter Spike Result v0.1

**Date**: 2026-06-22
**Operator**: Claude Code acting as senior dev + ops
**Status**: LINUX_RUNTIME_ADAPTER_SPIKE_READY_WITH_NOTES
**Design Gate Reference**: `LINUX_DOMAIN_PROOF_DESIGN_GATE_v0.1.md`
**Task**: Linux Domain Proof — Task 2 of 7 (Runtime Adapter Spike)
**No real secrets in this document.**

---

## A. Executive Summary

| Item | Value |
|------|-------|
| Final Decision | **LINUX_RUNTIME_ADAPTER_SPIKE_READY_WITH_NOTES** |
| Adapter pattern validated | YES — per-session workspace isolation, allowlist-gated execution, residual-scan cleanup, taint-on-failure |
| Learner-visible | **NO** — `enabled=False` by default; Linux publish still blocked by StaticValidator |
| K8s runtime changed | **NO** — zero regression |
| Tests added | 88 new tests (`tests/test_labgen_linux_runtime_adapter_spike.py`) |
| Full suite | 3885 passed, 93.38% coverage |
| Security issues at commit | MEDIUM × 1 (fixed), LOW × 3 (all fixed), NOTES × 3 (accepted) |
| Safety-reviewer result | All BLOCKER/HIGH/MEDIUM/LOW issues addressed before commit |

---

## B. North Star Alignment

| Principle | Status |
|-----------|--------|
| Article-to-Lab ("读了能练，练完即熟") | ALIGNED — spike proves adapter boundary needed for Linux labs, does not publish one |
| Platform-portable (not K8s-only) | ALIGNED — `NamespaceAdapterKind.LINUX` is a first-class enum value in selection service |
| No K8s hardcoding introduced | CONFIRMED — K8s selection path is unchanged `elif` branch |
| No learner exposure before publish gate | CONFIRMED — `LinuxRuntimeAdapter(enabled=False)` + StaticValidator publish block |
| Admin-curated pipeline respected | CONFIRMED — Linux labs cannot be published; `linux.publish_blocked_until_runtime` always fails |
| No premature expansion | CONFIRMED — no Linux catalog entry, no learner route, no LLM enabled |

---

## C. Architecture (What Was Built)

### Three-layer separation

```
LinuxRuntimeAdapter          ← session lifecycle + feature flag (enabled=False)
├── LinuxWorkspaceManager    ← filesystem isolation (per-session dir under /tmp/labgen-linux-sandboxes)
├── LinuxCommandExecutor     ← subprocess policy (allowlist, shell=False, metachar deny)
└── LinuxCleanupAdapter      ← shutil.rmtree + residual scan + taint-on-failure
```

### Separate from NamespaceLifecyclePort hierarchy

`LinuxContainerLifecycleAdapter` is a **skeleton** implementing `NamespaceLifecyclePort` to prove the interface works for `NamespaceAdapterKind.LINUX`. All 6 abstract methods raise `NotImplementedError`. The actual per-session Linux workspace management is handled by `LinuxRuntimeAdapter` which is **not** a `NamespaceLifecyclePort`.

This separation is intentional: Linux workspace lifecycle does not map 1:1 to K8s namespace lifecycle.

### Files created / modified

| File | Change |
|------|--------|
| `backend/labgen/linux_workspace.py` | NEW — `LinuxWorkspaceManager`, `WorkspaceSession`, path validation |
| `backend/labgen/linux_command_executor.py` | NEW — `LinuxCommandExecutor`, `ALLOWED_COMMANDS`, `DENIED_COMMANDS` |
| `backend/labgen/linux_cleanup.py` | NEW — `LinuxCleanupAdapter`, residual scan, cleanup validation |
| `backend/labgen/linux_runtime_adapter.py` | NEW — `LinuxRuntimeAdapter`, `LinuxSpikeSessionState`, feature flag |
| `backend/labgen/namespace_lifecycle.py` | MODIFIED — added `LinuxContainerLifecycleAdapter` skeleton |
| `backend/labgen/runtime_adapter_selection.py` | MODIFIED — `NamespaceAdapterKind.LINUX`, selection logic, `build_adapter()` guard |
| `backend/labgen/models.py` | MODIFIED — `@field_validator` enforcement on `LinuxSandboxPolicy.allow_root/allow_network` |
| `tests/test_labgen_linux_runtime_adapter_spike.py` | NEW — 88 tests |
| `tests/test_labgen_linux_domain_schema.py` | MODIFIED — 4 tests updated for model-layer enforcement |

---

## D. Spike Scenario Result

Scenario: create session → write files → execute allowed commands → cleanup → residual scan

```python
# Spike scenario (Section D, test_labgen_linux_runtime_adapter_spike.py)
policy = LinuxSandboxPolicy(allow_root=False, allow_network=False)
adapter = LinuxRuntimeAdapter(enabled=True, sandbox_root=sbox)

session = adapter.create_session("spike-01", policy)
assert session.status == LinuxSpikeStatus.ACTIVE

adapter.workspace.write_file(session.workspace_session, "hello.txt", "hello world\n")
result = adapter.execute_command("spike-01", ["cat", "hello.txt"])
assert result.returncode == 0
assert "hello world" in result.stdout

close_result = adapter.close_session("spike-01")
assert close_result.cleanup.cleanup_ok
assert not close_result.cleanup.residual.has_residual
assert close_result.state.status == LinuxSpikeStatus.CLOSED
assert close_result.state.cleanup_verified
```

**All 4 phases passed (session lifecycle, command execution, cleanup, residual scan).**

---

## E. Negative Tests (Security Boundary Coverage)

| Scenario | Expected | Result |
|----------|----------|--------|
| `allow_root=True` in policy | `ValidationError` at model construction | PASS |
| `allow_network=True` in policy | `ValidationError` at model construction | PASS |
| `LinuxRuntimeAdapter(enabled=False).create_session()` | `LinuxSpikeDisabledError` | PASS |
| Execute `sudo` | `policy_rejected=True`, reason `command_denied` | PASS |
| Execute `bash` | `policy_rejected=True`, reason `command_denied` | PASS |
| Execute `curl` | `policy_rejected=True`, reason `command_denied` | PASS |
| Execute `python3` | `policy_rejected=True`, reason `command_denied` | PASS |
| Argument with `;` metacharacter | `policy_rejected=True`, reason `shell_metachar_detected` | PASS |
| Argument with `\|` metacharacter | `policy_rejected=True`, reason `shell_metachar_detected` | PASS |
| Absolute path arg `/etc/passwd` | `policy_rejected=True`, reason `forbidden_path` | PASS |
| Absolute path arg `/tmp/other-session` | `policy_rejected=True`, reason `absolute_path_outside_workspace` | PASS |
| **Sibling session prefix** (`/sandbox/session-abc-evil` vs `/sandbox/session-abc`) | Rejected | PASS (MEDIUM fix) |
| `..` traversal in relative path | `WorkspacePathEscapeError` | PASS |
| `resolve_path()` with absolute input | `WorkspacePathEscapeError` | PASS |
| `sandbox_root=/home/user/custom` | `WorkspaceRootForbiddenError` at `__init__` | PASS (LOW fix) |
| `sandbox_root=/tmp` (bare) | `WorkspaceRootForbiddenError` | PASS |
| `cleanup()` with path outside sandbox | `ValueError` | PASS |
| `cleanup()` with forbidden root | `ValueError` | PASS |
| StaticValidator backstop via `model_construct()` bypass | Still raises `PUBLISH_BLOCKING` check | PASS (LOW fix) |
| `build_adapter(LINUX, production_mode)` | `RuntimeError` | PASS (LOW fix) |
| `NamespaceAdapterKind.LINUX` in production-like mode | Blocking issue emitted | PASS |
| Linux publish: `publish_blocked_until_runtime` | Publish blocked | PASS (K8s regression check) |

---

## F. Security Issues Raised and Resolved

### MEDIUM — Sibling session prefix confusion

**Finding**: `_check_path_arg()` used bare `startswith(workspace_root)`. Path `/sandbox/session-abc-evil` would pass the workspace check for `/sandbox/session-abc`.

**Fix**: `workspace_with_sep = workspace_root.rstrip(os.sep) + os.sep`; check `arg == workspace_root or arg.startswith(workspace_with_sep)`.

**Verified**: `test_command_sibling_session_prefix_rejected` passes.

---

### LOW-1 — Deep forbidden path in sandbox_root

**Finding**: `_validate_workspace_root()` only blocked exact forbidden roots. `sandbox_root=/home/user/custom-sandboxes` would bypass the check.

**Fix**: Validation moved to `LinuxWorkspaceManager.__init__`. Validates `sandbox_root` against all forbidden roots (using `startswith(forbidden + os.sep)`). Exception: `_ALLOWED_SANDBOX_ROOTS = frozenset({"/tmp/labgen-linux-sandboxes"})` is the sole explicitly carved-out path.

**Verified**: `test_workspace_root_deep_forbidden_path_rejected` passes.

---

### LOW-2 — LINUX adapter silently broken in production

**Finding**: `build_adapter()` for `NamespaceAdapterKind.LINUX` in production mode would return `LinuxContainerLifecycleAdapter()` whose every method raises `NotImplementedError`.

**Fix**: Hard guard in `build_adapter()` raises `RuntimeError` immediately when LINUX requested in `_PRODUCTION_LIKE_MODES`.

**Verified**: `test_build_adapter_linux_raises_in_production` passes.

---

### LOW-3 — StaticValidator backstop unreachable after model enforcement

**Finding**: After adding `@field_validator` on `allow_root`/`allow_network`, the StaticValidator `_check_linux_sandbox_safe()` backstop became unreachable via normal model construction. Defense-in-depth was untested.

**Fix**: Added tests using `LinuxSandboxPolicy.model_construct(allow_root=True)` (Pydantic bypass) to prove StaticValidator still catches the violation at publish time.

**Verified**: `test_static_validator_allow_root_backstop_via_model_construct` and `test_static_validator_allow_network_backstop_via_model_construct` pass.

---

### NOTES (accepted, not fixed)

| Note | Reason Accepted |
|------|----------------|
| OS-level process isolation not implemented | This is a spike proving adapter interfaces; cgroups/seccomp/namespaces are Task 4 scope |
| Network isolation not enforced at kernel level | Spike workspace runs as host process; full isolation is container/VM sandbox scope |
| `LinuxCommandExecutor` allowlist is restrictive but not complete | `test`, `[`, `find -exec` edge cases noted; production allowlist requires security review before any learner exposure |

---

## G. K8s Regression

| Check | Result |
|-------|--------|
| All K8s existing tests pass | YES — 3885 passed total |
| `build_adapter(K8S)` path unchanged | YES — K8S is a separate `if` branch; LINUX is `elif` |
| `StubNamespaceLifecycleAdapter` path unchanged | YES — falls through to `return StubNamespaceLifecycleAdapter()` |
| `LinuxContainerLifecycleAdapter` connected to K8s namespace ops | NO — all 6 methods raise `NotImplementedError` |
| Linux publish gate still blocks | YES — `StaticValidator.linux.publish_blocked_until_runtime` always fails |
| `NamespaceAdapterKind` enum parse unchanged for `stub`/`k8s` | YES — only `linux` added as new value |

---

## H. Tests and Scans

| Metric | Value |
|--------|-------|
| New tests (spike) | 88 (`tests/test_labgen_linux_runtime_adapter_spike.py`) |
| Tests updated (schema) | 4 (`tests/test_labgen_linux_domain_schema.py`) |
| Full suite result | 3885 passed, 0 failed |
| Coverage | 93.38% (above 90% gate) |
| `runtime_adapter_selection.py` coverage | 100% |
| `linux_workspace.py` coverage | measured in suite |
| `linux_command_executor.py` coverage | measured in suite |
| `linux_cleanup.py` coverage | measured in suite |
| `linux_runtime_adapter.py` coverage | measured in suite |
| bandit scan | PASS (no new findings in new files) |
| pre-commit hook | PASS |

---

## I. Issue Triage

| ID | Severity | Description | Resolution |
|----|----------|-------------|------------|
| M-01 | MEDIUM | Sibling session prefix confusion in `_check_path_arg()` | FIXED — trailing `os.sep` added |
| L-01 | LOW | Deep forbidden path in `sandbox_root` bypassed validation | FIXED — validation in `__init__`, `_ALLOWED_SANDBOX_ROOTS` exception |
| L-02 | LOW | LINUX adapter silently broken in production | FIXED — `RuntimeError` hard guard in `build_adapter()` |
| L-03 | LOW | StaticValidator backstop unreachable, untested | FIXED — `model_construct()` bypass tests added |
| N-01 | NOTE | OS-level process/network isolation absent | Accepted — out of scope for spike (adapter interface, not deployed sandbox) |
| N-02 | NOTE | `LinuxCommandExecutor` allowlist incomplete | Accepted — spike-level; any learner exposure requires dedicated security review |
| N-03 | NOTE | `find -exec` not covered | Accepted — `find` is allowlisted but `-exec` with shell commands is an edge case for future hardening |

---

## J. Final Decision

**LINUX_RUNTIME_ADAPTER_SPIKE_READY_WITH_NOTES**

The spike successfully proves the adapter boundary pattern:
- Per-session workspace isolation is implementable as a pure Python layer
- Allowlist-gated subprocess execution with `shell=False` is enforceable
- Residual-scan cleanup with taint-on-failure composes correctly with LabSession state machine
- `NamespaceAdapterKind.LINUX` integrates into the selection service without touching the K8s path
- All 4 security issues from safety-reviewer are resolved; 3 notes accepted as spike scope

**Not proved** (out of scope, future tasks):
- OS-level sandbox isolation (container/VM, cgroups, seccomp, namespaces)
- Linux VerifierClient (how to verify learner's file/permission work without shell injection)
- End-to-end publish gate for a real Linux lab
- Learner-visible Linux lab session

---

## K. Recommended Next Step

**Task 3 of 7: Linux Verifier Adapter Spike**

Define a `LinuxVerifyClientAdapter` that validates `LinuxVerifyTemplate` steps (file_exists, file_contains, permission_is, directory_exists, command_output_matches) against the learner's workspace without calling user-controlled shell. This is the analog to `K8sVerifierClientAdapter` for the Linux domain. The workspace isolation from this spike is a prerequisite.
