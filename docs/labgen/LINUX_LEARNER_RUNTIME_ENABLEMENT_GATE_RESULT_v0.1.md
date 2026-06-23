# Linux Learner Runtime Enablement Gate — Result v0.1

**Gate ID**: G-45  
**Status**: LINUX_LEARNER_RUNTIME_ENABLEMENT_GATE_PASSED  
**Date**: 2026-06-23  
**Branch**: main  

---

## 1. Gate Objective

Enable the already-published Linux lab (`6c439064-4cad-4229-addb-36927128d565`) for learner
sessions under **controlled conditions only**.

Controlled means:
- Feature flag `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` explicitly lists the lab UUID.
- Only that lab. No second Linux lab, no public launch, no Trusted Reader Pilot.
- No live LLM calls during the learner smoke flow.
- K8s Lab 5 path must remain zero-regression.

---

## 2. Scope Boundaries (Strict)

| Item | Status |
|------|--------|
| Start Trusted Reader Pilot | ❌ PROHIBITED |
| Open to multiple learners concurrently | ❌ PROHIBITED |
| Raise concurrency limits | ❌ PROHIBITED |
| Publish a second Linux lab | ❌ PROHIBITED |
| Enable public article upload | ❌ PROHIBITED |
| Enable live LLM / call LLM API | ❌ PROHIBITED |
| URL scraping / customer pilot / public launch | ❌ PROHIBITED |
| Modify VMID 500-599 | ❌ PROHIBITED |
| Modify K8s runtime / verifier behavior | ❌ PROHIBITED |
| Break K8s Lab 5 article-linked path | ❌ PROHIBITED |
| Global `LinuxRuntimeAdapter(enabled=True)` without allowlist | ❌ PROHIBITED |
| Start without full cleanup closure | ❌ PROHIBITED |

---

## 3. Changes Delivered

### 3.1 `backend/config.py`

```python
LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS: frozenset = _parse_lab_id_set(
    os.getenv("LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", "")
)
LABGEN_LINUX_SANDBOX_ROOT: str = os.getenv(
    "LABGEN_LINUX_SANDBOX_ROOT", "/tmp/labgen-linux-sandboxes"
)
```

- `_parse_lab_id_set()` splits comma-separated UUIDs, strips whitespace, returns `frozenset`.
- Empty env var → `frozenset()` → all Linux learner sessions blocked.

### 3.2 `backend/labgen/failure_reasons.py`

Two new codes:

```python
LINUX_LEARNER_WORKSPACE_CREATE_FAILED = "linux_learner.workspace_create_failed"
LINUX_LEARNER_CLEANUP_FAILED = "linux_learner.cleanup_failed"
```

### 3.3 `backend/labgen/lab_session_service.py`

- `LINUX_LEARNER_VM_SENTINEL = "linux-sandbox"` — sentinel vm_id for Linux sessions.
- `__init__` new params: `linux_adapter`, `linux_learner_enabled_lab_ids`.
- `run_precheck()`: Linux lab in allowlist → skip VM tracker checks; not in allowlist →
  `PRECHECK_LINUX_LEARNER_NOT_SUPPORTED`.
- `create_session()`: Linux+allowlist dispatch → `_do_create_linux_session()`.
- `_do_create_linux_session()`: sets `vm_id=LINUX_LEARNER_VM_SENTINEL`, calls
  `linux_adapter.create_session()`, no K8s namespace, no kubeconfig.
- `_do_cleanup_linux()`: calls `linux_adapter.close_session()`, sets `cleanup_verified=True` on
  success, does NOT call `mark_vm_tainted` (sentinel has no real VM).
- `_do_cleanup()`: dispatches to `_do_cleanup_linux()` for Linux domain drafts.

### 3.4 `backend/labgen/routes.py`

- Module-level singleton `_linux_runtime_adapter` (lazy init when env is non-empty).
- `get_linux_runtime_adapter()`: constructs `LinuxRuntimeAdapter(enabled=True, sandbox_root=...)`.
- `get_session_service()`: passes `linux_adapter` + `linux_learner_enabled_lab_ids`.
- `get_step_progression_service()`: injects `LinuxVerifierService(linux_adapter.workspace_manager)`.
- `create_lab_session()`: if `vm_id` is None and lab is Linux+allowlisted → sets
  `vm_id = LINUX_LEARNER_VM_SENTINEL`, skips Proxmox VM discovery.

---

## 4. Learner Smoke Flow (Verified In-Process)

```
Start(LINUX_LAB_ID, linux-sandbox, STUDENT)
  → LAB_ACTIVE, vm_id=linux-sandbox, session_type=LEARNER

mkdir demo
check_step(step_1) → LINUX_DIRECTORY_EXISTS(demo) → PASS, advanced=True

printf 'hello labgen\n' > demo/message.txt
check_step(step_2) → LINUX_FILE_EXISTS + LINUX_FILE_CONTENT_MATCHES → PASS, advanced=True

chmod 600 demo/message.txt
check_step(step_3) → LINUX_FILE_MODE_MATCHES(600) → PASS, ready_to_complete=True

complete_session()
  → LAB_CLOSED, cleanup_verified=True
  → Workspace removed
  → No residual files
```

Abort path:
```
abort_session() → LAB_CLOSED, cleanup_verified=True
```

---

## 5. Test Coverage

**New test file**: `tests/test_labgen_linux_learner_enablement.py`  
**Test count**: 53  
**Categories**:

| Category | Tests | Description |
|----------|-------|-------------|
| A | 7 | Feature flag / allowlist precheck |
| B | 7 | Learner session create |
| C | 8 | Step check (Linux verifier dispatch) |
| D | 6 | Complete (cleanup, LAB_CLOSED) |
| E | 3 | Abort |
| F | 8 | Negative checks (sudo/su/path escape/non-allowlisted) |
| G | 3 | Catalog isolation |
| H | 4 | K8s regression |
| I | 3 | Full E2E smoke |
| J | 4 | Config parsing |
| K | 3 | Failure reason stability |

**Full suite**: 4285 passed, 92.47% coverage (≥90% gate: PASS)

---

## 6. Safety Invariants Verified

| Invariant | Verified |
|-----------|---------|
| VM tracker not called for Linux learner sessions | ✅ |
| K8s namespace not created for Linux sessions | ✅ |
| Kubeconfig not created for Linux sessions | ✅ |
| `mark_vm_tainted` not called for sentinel vm_id | ✅ |
| `allow_root=True` policy rejected at model validation | ✅ |
| `allow_network=True` policy rejected at model validation | ✅ |
| `..` path escape rejected by WorkspacePathEscapeError | ✅ |
| Absolute path `/etc/shadow` write rejected | ✅ |
| `sudo` / `su` commands rejected (policy_rejected=True) | ✅ |
| Non-allowlisted Linux lab blocked | ✅ |
| Draft Linux lab blocked even if in allowlist | ✅ |
| K8s Lab 5 precheck unaffected | ✅ |
| K8s session create uses K8s path (not linux_adapter) | ✅ |
| K8s cleanup does not call linux_adapter.close_session | ✅ |
| No LLM modules imported during learner smoke | ✅ |

---

## 7. Catalog State

- Published K8s labs: 5 (cf019133 + 4 others)
- Published Linux labs: 1 (6c439064, allowlist-controlled)
- Draft/hidden labs: not visible in catalog
- Linux lab visible to learner catalog: YES (when env var set)
- Linux lab startable without env var: NO (PRECHECK_LINUX_LEARNER_NOT_SUPPORTED)

---

## 8. North Star Alignment

Gate G-45 completes the Linux learner enablement path under feature flag control.
The production toggle `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` is the single-switch
between "blocked" and "enabled for specific labs."

Next gate: Controlled Linux Learner Cohort Pilot (deploy with env var set for one lab,
observe session lifecycle, confirm cleanup_verified=True and residual=0 across real sessions).

---

## 9. Commit Reference

`feat(labgen): Linux Learner Runtime Enablement Gate v0.1 — G-45`
