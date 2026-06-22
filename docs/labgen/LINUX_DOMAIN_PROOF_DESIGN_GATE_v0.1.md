# Linux Domain Proof Design Gate v0.1

**Date**: 2026-06-21
**Operator**: Claude Sonnet 4.6 (senior dev + ops)
**Preceded by**: Trusted Reader Pilot — PASSED (session a301676a, LAB_CLOSED, cleanup_verified=True, step_1+step_2 PASS, observer-confirmed no hiccups)
**No real secrets in this document.**

---

## A. Executive Summary

| Field | Value |
|-------|-------|
| Gate decision | **LINUX_DOMAIN_PROOF_DESIGN_READY_WITH_NOTES** |
| K8s Trusted Reader Proof | ✅ PASSED — K8s Article-linked Guided Practice confirmed end-to-end |
| Linux implementation unlocked | ✅ Design unlocked; implementation blocked on 5 BLOCKER coupling items |
| Recommended first Linux lab | Linux Files and Permissions Basics |
| Recommended Linux runtime | Container-based sandbox (Docker on Proxmox host) |
| Recommended verifier approach | `docker exec` or SSH-into-container for file/content/mode checks |
| Recommended cleanup | `docker rm -f <container_id>` + residual scan |
| LLM calls in this gate | 0 |
| Code changes in this gate | 0 (design only) |
| Production VMID 500-599 | Untouched |
| Live LLM enabled | No |
| Customer pilot | No |
| Public launch | No |

**Why READY_WITH_NOTES**: The architecture was designed from day one for domain portability. `TargetDomain.LINUX` already exists in `article_models.py`. `ArticleRuntimeType.LINUX_VM` already exists. The Feasibility Gate, Admin Review, StaticValidator, Publish Gate, and Article-to-Lab pipeline are all domain-agnostic. However, 5 K8s-only coupling items are BLOCKER severity — they require schema extension and adapter skeleton work before any Linux lab can be internally rehearsed. The design is sound; the couplings are known and enumerable.

---

## B. North Star Alignment

| Alignment Check | Status |
|-----------------|--------|
| 读了能练，练完即熟 | ✅ Linux domain must produce the same reader→verifier→cleanup loop |
| K8s is domain proof, not final product boundary | ✅ Confirmed — this gate transitions to proof #2 |
| Linux proves multi-domain portability | ✅ That is the point of this gate |
| Admin-curated Article-to-Lab still applies | ✅ Same pipeline, different domain |
| Guided Practice Lab, not Assessment Lab | ✅ Commands, expected output, hints, Check button |
| No public launch | ✅ Not in scope |
| No live LLM | ✅ Stub pipeline only |
| No modification of K8s validated path | ✅ K8s runtime is untouched |

The K8s domain proof established these domain-agnostic platform capabilities:

- Per-session isolation (namespace-scoped)
- Verifier primitives (typed, namespace-scoped, safe_message-compliant)
- Credential separation (platform kubeconfig ≠ verifier kubeconfig)
- Cleanup closed loop (taint-on-failure, residual audit)
- Admin draft → StaticValidator → Publish Gate flow
- Article-to-Lab pipeline (stub classifier, AdminReviewDiff, learner catalog isolation)
- Reader CTA → lab session → step verification → LAB_CLOSED

All of these are portable. The Linux domain proof must exercise the same scaffold with a different runtime underneath.

---

## C. K8s Milestone Closure

### What the K8s Trusted Reader Pilot proved

| Capability | Evidence |
|-----------|---------|
| Article-linked lab can be published via full pipeline | ✅ cf019133 published |
| Admin can curate, review, and patch lab content | ✅ AdminReviewDiff, PATCH endpoint |
| Trusted reader (non-developer) can complete Lab 5 unassisted | ✅ session a301676a, observer-confirmed no hiccups |
| step_1 (configmap_exists) PASS | ✅ |
| step_2 (namespace_exists) PASS | ✅ |
| LAB_CLOSED + cleanup_verified=True | ✅ |
| Zero namespace residual | ✅ |
| Placeholder quality gate (StaticValidator) prevents TODO leakage | ✅ |
| VM isolation guard (409 on delete during active session) | ✅ |

### What it does NOT prove

- Multi-domain portability (Linux, Docker, etc.) — still unproven
- arbitrary Article-to-Lab (LLM live pipeline) — still stub
- Any runtime beyond K8s/K3s
- Production readiness at scale

---

## D. Reusable Core Inventory

The following modules can be reused unchanged by the Linux domain:

| Module | File | Reusable As-Is | Risk |
|--------|------|----------------|------|
| Article Feasibility Gate | `article_models.py`, `stub_feasibility_classifier.py` | ✅ (needs Linux keyword detection added) | LOW |
| ArticleDraftLabContract schema | `article_models.py` | ✅ | NONE |
| TargetDomain.LINUX enum | `article_models.py` | ✅ already defined | NONE |
| ArticleRuntimeType.LINUX_VM | `article_models.py` | ✅ already defined | NONE |
| ArticleDraftRepository | `article_draft_repository.py` | ✅ | NONE |
| ArticleDraftService (routing/review) | `article_draft_service.py` | ⚠️ `_pick_target_domain` K8s-priority bias | MEDIUM |
| StaticValidator core | `static_validator.py` | ✅ (domain-agnostic guardrails) | LOW |
| StaticValidator cloud_domain_blocked | `static_validator.py` | ✅ pattern reusable for future block rules | NONE |
| PublishService | `publish_service.py` | ✅ | NONE |
| PublishStatus / BlockingLevel enums | `models.py` | ✅ | NONE |
| LabDraft schema (steps, verify, cleanup) | `models.py` | ⚠️ VerifyType and CleanupNamespace are K8s-only | HIGH |
| LabSessionState (state machine) | `models.py` | ⚠️ `namespace` field name K8s-specific; state machine itself is portable | MEDIUM |
| LabSessionRepository | `lab_session_repository.py` | ✅ | NONE |
| LabSessionService (state machine logic) | `lab_session_service.py` | ⚠️ wired to NamespaceLifecyclePort; Linux needs different port | HIGH |
| Admin Review routes and diff tracking | `routes.py`, `review_diff.py` | ✅ | NONE |
| Learner catalog isolation | `learner_catalog.py` | ✅ | NONE |
| StepProgressionService | `step_progression_service.py` | ✅ (verify dispatch abstracted) | NONE |
| RuntimeAuditService | `runtime_audit.py` | ✅ | NONE |
| FailureReason enum | `failure_reasons.py` | ✅ (Linux reasons can be added) | NONE |
| ImageReadiness / ImageResolver | `image_resolver.py`, `image_readiness.py` | ⚠️ Linux sandbox image check is different concept | MEDIUM |
| LabDraftRepository | `repository.py` | ✅ | NONE |
| flock-based storage | `storage_utils.py` | ✅ | NONE |
| VMTrackerPort (session-to-vm binding) | `lab_session_service.py` | ✅ (VM pool reuse) | NONE |
| RealVMTracker / taint tracking | `lab_session_service.py` | ✅ | NONE |
| VerifierCredentialStore | `verifier_credentials.py` | ⚠️ only stores kubeconfig; Linux verifier uses different credential type | HIGH |
| RuntimeAdapterSelectionResult | `runtime_adapter_selection.py` | ⚠️ `NamespaceAdapterKind` has no LINUX option | HIGH |

---

## E. K8s-only Coupling Inventory

### BLOCKER — must resolve before Linux internal rehearsal

| ID | File / Area | Coupling Description | Required Action |
|----|-------------|---------------------|----------------|
| B-01 | `backend/labgen/models.py` — `VerifyType` enum | All 10 verify types are K8s primitives (pod_running, configmap_exists, namespace_exists, etc.). Linux verifier types (linux_file_exists, linux_file_content_matches, linux_file_mode_matches, linux_directory_exists) do not exist in the schema. Lab contracts specifying Linux verify steps cannot be expressed or validated. | Add Linux verify types to VerifyType enum; or create a parallel LinuxVerifyType enum. Without this, Linux LabDraft is inexpressible. |
| B-02 | `backend/labgen/models.py` — `CleanupNamespace` | Cleanup model is hardcoded to `type="delete_namespace"` with `namespace` field. Linux cleanup requires deleting a workspace directory, killing processes, and removing session credentials — none of which map to this model. | Design and add a `CleanupLinuxWorkspace` model (or generalize `CleanupSpec` as a union type). |
| B-03 | `backend/labgen/namespace_lifecycle.py` — `NamespaceLifecyclePort` | The port is conceptually a K8s namespace lifecycle abstraction (create/delete K8s namespace, ensure K8s RoleBinding). Linux sandbox lifecycle is fundamentally different: create workspace directory, destroy workspace directory, manage process context. The port name, method names, and method contracts all assume K8s. | Design a parallel `WorkspaceLifecyclePort` abstract interface for Linux sandbox lifecycle; OR generalize `NamespaceLifecyclePort` to `SandboxLifecyclePort`. A Linux adapter must not implement the K8s-named port. |
| B-04 | `backend/labgen/verifier.py` — `K8sVerifierClientPort` | The verifier port is named `K8sVerifierClientPort` and all methods (pod_running, deployment_ready, configmap_exists) are K8s-native. Linux verifier needs to check file existence, file content, file mode, directory existence — operations that have no mapping to K8s API calls. | Design `LinuxVerifierClientPort` with Linux-native check methods; wire it to a `LinuxSandboxVerifierAdapter` that executes checks inside the Linux sandbox (via `docker exec` or SSH). |
| B-05 | `backend/labgen/runtime_adapter_selection.py` — `NamespaceAdapterKind` | The runtime selection enum only has `STUB` and `K8S`. When a Linux lab session starts, the adapter selection module has no way to select a Linux adapter — it will either fall to K8S (wrong runtime) or fail. | Add `LINUX` (and later `DOCKER`) to `NamespaceAdapterKind`; add Linux-profile selection logic to `RuntimeAdapterSelectionService`. |

### HIGH — must resolve before Linux publish gate

| ID | File / Area | Coupling Description | Required Action |
|----|-------------|---------------------|----------------|
| H-01 | `backend/labgen/article_draft_service.py` — `_pick_target_domain` | `_pick_target_domain` prioritizes `TargetDomain.K8S` unconditionally. A Linux article that has no K8s signals would fall through to `TargetDomain.UNKNOWN`, which is a PUBLISH_BLOCKING check in StaticValidator. Linux articles would never be classified as `TargetDomain.LINUX` via the stub pipeline. | Update `_pick_target_domain` to explicitly return `TargetDomain.LINUX` when the feasibility result contains Linux domain candidates. |
| H-02 | `backend/labgen/stub_feasibility_classifier.py` | The stub classifier only detects K8s signals (`namespace`, `kubectl`, `configmap`, etc.) and cloud signals. Linux article signals (filesystem, permissions, `chmod`, `bash`, `ls`, `mkdir`, `stat`, etc.) are not detected — Linux articles fall to `TargetDomain.UNKNOWN`. | Add Linux keyword detection to `StubFeasibilityClassifier`; add `TargetDomain.LINUX` to the domain candidate list. |
| H-03 | `backend/labgen/verifier_credentials.py` — `VerifierCredentialStore` | Currently stores only kubeconfig (YAML) for K8s verifier access. Linux sandbox verifier needs a different credential type — either an SSH key, a Docker container ID, or no persistent credential (ephemeral exec). The store's data model (`kubeconfig.yaml` + `metadata.json`) is K8s-specific. | Design credential model for Linux verifier; determine whether Linux sandbox verifier uses SSH, Docker API socket, or no credential (exec into container). |
| H-04 | `backend/labgen/models.py` — `LabSessionState.namespace` | `namespace` field is semantically K8s-specific. For Linux sessions the isolation unit is a workspace directory path, not a namespace. Using `namespace` for a directory path is misleading and makes the code harder to reason about. | Consider renaming to `sandbox_id` or adding a `workspace_path` field; or document that `namespace` is repurposed as a generic sandbox identifier in non-K8s sessions. Design decision needed before Linux implementation. |

### MEDIUM — can defer but must track

| ID | File / Area | Coupling Description | Notes |
|----|-------------|---------------------|-------|
| M-01 | `backend/labgen/models.py` — `DomainContract.namespace_template` | The field is named `namespace_template` and defaults to `"lab-{{lab_id}}-{{session_id}}"`. For Linux sandbox, the template would refer to a workspace directory name, not a K8s namespace. | Rename or document; non-blocking for design gate |
| M-02 | `backend/labgen/image_resolver.py` — `ImageResolver` | Currently checks images against a Docker registry whitelist for K8s pod pulls. Linux sandbox (container-based) also uses container images, so this is partially reusable — but the whitelist policy and registry check semantics differ. | Review when Linux runtime choice is finalized |
| M-03 | `backend/labgen/lab_session_service.py` — NamespaceLifecyclePort wiring | Session startup is tightly coupled to `NamespaceLifecyclePort` method calls (create_namespace, ensure_verifier_rolebinding, etc.). A Linux adapter must implement this port if we don't redesign the port. | Resolved by B-03 fix |
| M-04 | `deploy/labgen/staging_ops_ticket_status.md` | All ops tickets are K8s/Proxmox-specific. Linux domain will require additional ops ticket: Linux sandbox runtime provisioning (Docker daemon, base image, user isolation policy). | Add Linux ops ticket when implementation begins |
| M-05 | `frontend/labgen-lab.html` / `frontend/labgen-catalog.html` | Frontend may contain K8s-specific language (e.g., "namespace", "kubectl"). Linux lab context should use Linux-appropriate language. | Review and adjust as part of Linux lab publish |

### LOW / NOTE

| ID | Area | Note |
|----|------|------|
| L-01 | Static validator: cloud_domain_blocked_v1 check | Linux domain is NOT blocked by this check — only `cloud` is blocked. Linux articles pass the domain block check. ✅ |
| L-02 | Static validator: unknown_domain_cannot_publish check | Linux articles currently fall to UNKNOWN (see H-01/H-02), which IS blocked. Fixing H-01+H-02 resolves this. |
| N-01 | models.py: LabSessionStatus state machine | The status names (NAMESPACE_CREATING, NAMESPACE_READY, VERIFIER_BINDING_CREATING, NAMESPACE_TERMINATING_WAIT) are K8s-specific labels. Linux sessions will reuse these states but with different underlying operations. This is cosmetically misleading but not a functional blocker. |
| N-02 | models.py: PollutionLevel enum | NAMESPACE_ONLY, CLUSTER_SCOPED, NODE_LEVEL — all K8s concepts. Linux pollution level equivalents: WORKSPACE_ONLY, HOST_TEMP_ONLY, PROCESS_SCOPED. Not blocking now. |

---

## F. Linux Domain Contract Proposal

The following fields extend `ArticleDraftLabContract` and `LabDraft` for Linux domain:

```python
# TargetDomain.LINUX (already exists in article_models.py)
# ArticleRuntimeType.LINUX_VM (already exists in article_models.py)

class LinuxSandboxPolicy(BaseModel):
    """Constraints on what learner may do inside the Linux sandbox."""
    sandbox_type: str = "container"          # "container" | "vm_user" | "vm_home"
    base_image: str = "ubuntu:22.04"         # Container image if sandbox_type=container
    shell: str = "/bin/bash"
    working_directory: str = "/home/learner/workspace"
    learner_user: str = "learner"
    privilege_level: str = "unprivileged"    # no sudo, no root
    network_policy: str = "none"             # no internet access
    allowed_workspace_prefix: str = "/home/learner/workspace"
    forbidden_paths: list[str] = ["/etc", "/root", "/var", "/proc/sys", "/sys"]
    allowed_commands: list[str] = []         # empty = no allowlist enforcement (rely on user privilege)
    session_timeout_seconds: int = 1800
    cleanup_strategy: str = "destroy_container"   # "destroy_container" | "rm_workspace" | "reset_vm"
    max_output_bytes: int = 65536
    verifier_timeout_seconds: int = 10
    ai_tutor_domain_scope: str = "linux_basics"

class LinuxVerifyType(str, Enum):
    """Linux-native verifier primitives."""
    LINUX_FILE_EXISTS = "linux_file_exists"
    LINUX_FILE_CONTENT_MATCHES = "linux_file_content_matches"
    LINUX_FILE_MODE_MATCHES = "linux_file_mode_matches"
    LINUX_DIRECTORY_EXISTS = "linux_directory_exists"
    LINUX_COMMAND_OUTPUT_CONTAINS = "linux_command_output_contains"
    LINUX_NO_RESIDUAL_FILES = "linux_no_residual_files"

# Proposed addition to LabDraft cleanup spec:
class CleanupLinuxWorkspace(BaseModel):
    type: str = "destroy_linux_sandbox"
    workspace_path: str = "{{sandbox_workspace}}"   # resolved at session time
    kill_processes: bool = True
    revoke_credentials: bool = True
    residual_scan_paths: list[str] = ["{{sandbox_workspace}}"]
```

**Safety constraints on the Linux domain contract:**
- `privilege_level` must always be `"unprivileged"` for v0.1 — no sudo
- `allowed_workspace_prefix` must be validated before any verifier path check — no traversal outside sandbox
- `forbidden_paths` are enforced by verifier adapter before any check operation
- `network_policy: "none"` is enforced at container/sandbox creation time
- `base_image` must be from the whitelist (nginx/busybox/alpine/ubuntu only in v0.1)

---

## G. Linux Runtime Strategy

### Options Compared

**Option A: Isolated Linux user/home directory on existing VM (VM 401)**

Reuse VM 401 (currently running K3s). Create a per-session Linux user (or per-session subdirectory under a shared `learner` user). The learner SSHes into the VM as that user. The verifier SSHes in to check file states.

Pros:
- Closest to real Linux experience
- Natural terminal feel
- Supports file, permissions, process experiments

Cons:
- Process cleanup is hard (need to kill all learner-owned processes at session end)
- Filesystem cleanup: must delete only the learner's workspace, not system files
- User isolation: creating and deleting OS users per session is fragile
- K3s sharing: VM 401 runs K3s; mixing K8s workloads and Linux shell sessions on the same node is fragile
- Privilege boundary: preventing `sudo` abuse or path traversal is operationally complex

**Option B: Container-based Linux sandbox (Docker on Proxmox host)**

Run Docker daemon on the Proxmox host (or in a dedicated lightweight VM). Each lab session gets a fresh container from a standard Linux image. The learner gets a shell session inside the container. The verifier executes checks via `docker exec`. Cleanup destroys the container.

Pros:
- Clean isolation — container lifecycle = session lifecycle
- Cleanup is atomic: `docker rm -f <id>` removes all traces
- No user management complexity
- Supports file, permissions, directory experiments naturally
- Does not share resources with K3s
- Container image whitelist reuses existing `ImageResolver` concepts

Cons:
- Requires Docker daemon available (needs ops verification)
- Terminal attachment via `docker exec` requires an adapter (not SSH-based like current K8s terminal)
- Container image pull policy must be enforced
- `docker exec` for verifier requires Docker API access from FastAPI process

**Option C: K8s Pod as Linux shell sandbox**

Run a standard Linux container image (e.g., `ubuntu:22.04`) as a K8s Pod inside a lab namespace on K3s. The learner gets a `kubectl exec` shell session inside the pod. The verifier uses `kubectl exec` to check file states.

Pros:
- Reuses existing K3s infrastructure (VM 401)
- Cleanup reuses namespace delete
- No new infrastructure dependency

Cons:
- **The learner is doing Linux operations but the platform is using K8s API — this is architecturally misleading**
- Does not prove that the runtime layer is replaceable (it's still K8s underneath everything)
- The LabGen architecture goal is to prove multi-domain portability — K8s-pod-as-Linux-sandbox does not prove this
- Verifier would still use K8s credentials and K8s API (contradicts the goal of Linux-native verifier)
- Risk: the "Linux Domain Proof" becomes just another K8s lab with a different image

### Recommendation: Option B (Container-based Linux Sandbox)

Docker containers provide the cleanest isolation for v0.1 Linux domain proof:

1. **Lifecycle match**: Container create = session start. Container destroy = cleanup. No residual state.
2. **Architecture honesty**: The runtime layer is explicitly NOT K8s. The `WorkspaceLifecyclePort` adapter for Linux uses Docker API, not Kubernetes API. This is the proof that the runtime is swappable.
3. **Verifier independence**: `LinuxVerifierClientAdapter` uses `docker exec` to check file states. No kubeconfig. No K8s RBAC. Proves that the verifier port abstraction works with a different backend.
4. **Cleanup simplicity**: `docker rm -f <container_id>` eliminates the workspace atomically. No stuck-terminating analogues. No taint complexity for v0.1.
5. **Infrastructure delta**: Requires Docker daemon on Proxmox host or a dedicated Linux VM. This is a single ops ticket (OPS-LINUX-001).

**Risk**: Docker daemon availability on Proxmox host must be confirmed before implementation begins. If Docker is not available, a lightweight VM (e.g., a new Proxmox VM with Docker pre-installed) is an acceptable alternative — the architecture is identical, only the network path changes.

**Deferred decisions:**
- Whether to use Docker socket directly or a Docker-over-TCP endpoint
- Whether to pre-pull base images or pull on demand (with pull timeout risk)
- Whether the learner terminal attaches via WebSocket→`docker exec` or SSH-into-container
- Long-term: migration from Docker to Podman, to VM-per-session, or to cloud sandboxes

**Critical boundary**: The v0.1 Linux Domain Proof uses containers as a temporary sandbox mechanism. It does NOT represent the final Linux runtime architecture. The design explicitly documents that:
- The `WorkspaceLifecyclePort` abstraction remains the canonical interface
- The Docker adapter is one implementation, not the canonical one
- Future Linux runtime may use VMs, cloud sandboxes, or other mechanisms
- The K8s domain remains unchanged and continues to use `NamespaceLifecyclePort`

---

## H. First Linux Guided Practice Lab Candidate

### Linux Files and Permissions Basics

**Article summary**: A technical article introducing Linux file management, directory structure, and file permissions using `chmod`, `ls -l`, and `stat`. The article explains octal permission notation, the meaning of rwx bits, and how to verify permission changes.

**Experiment background** (to be derived from article content brief):
This experiment reproduces the core operations from the article in a temporary, isolated Linux environment. You will create files, set permissions, and verify the result — the same operations you read about, now running live in a real shell.

**Objectives**:
1. Create a file in a workspace directory.
2. Write content to the file.
3. Verify the file exists and contains expected content.
4. Change file permissions.
5. Verify the permission change using `stat`.

**Guided steps**:

```
Step 1: Create workspace directory and file
  do: mkdir -p ~/workspace && echo "hello lab" > ~/workspace/greeting.txt
  expected output: (no output, prompt returns)
  observe: File created in ~/workspace/
  verify: linux_file_exists: ~/workspace/greeting.txt

Step 2: Verify file content
  do: cat ~/workspace/greeting.txt
  expected output: hello lab
  observe: Content matches what was written
  verify: linux_file_content_matches: path=~/workspace/greeting.txt, contains="hello lab"

Step 3: Check default permissions
  do: ls -l ~/workspace/greeting.txt
  expected output: -rw-rw-r-- (or similar)
  observe: Default permissions include owner read+write

Step 4: Change permissions to 644
  do: chmod 644 ~/workspace/greeting.txt
  expected output: (no output)
  observe: Command returns without error
  verify: linux_file_mode_matches: path=~/workspace/greeting.txt, mode=644

Step 5: Verify final state
  do: stat ~/workspace/greeting.txt
  expected output: Access: (0644/-rw-r--r--)
  observe: Mode field shows 0644
  verify: linux_file_mode_matches (recheck)
```

**Verifier candidates**:
- `linux_file_exists`: check path within workspace prefix
- `linux_file_content_matches`: `grep` or exact match on expected string
- `linux_file_mode_matches`: `stat -c %a <path>` compared to expected octal

**Cleanup strategy**:
- Destroy container (Option B) or `rm -rf ~/workspace` (Option A)
- Cleanup verification: confirm workspace path no longer accessible
- Taint policy: mark sandbox tainted if cleanup fails; block reuse

**AI tutor context**:
- Domain scope: Linux basics (files, directories, permissions)
- May explain: what chmod does, what octal notation means, what stat output shows
- Must not: reveal verifier logic, complete steps for learner, suggest dangerous operations
- System prompt includes: current lab title, step number, expected operations, sandbox type

**Reject boundaries**:
- No `sudo` — all operations run as unprivileged learner user
- No `/etc`, `/root`, `/var` — restricted by path policy
- No network operations — sandbox has no internet access
- No process spawning that outlives the step (no background daemons)
- No file size > 1MB

**Why this is the right first Linux lab**:
1. All operations are safe (no root, no network, no destructive ops)
2. Cleanup is trivial (delete one directory)
3. Verifier is straightforward (file exists, content match, mode match)
4. Article signals are clear (chmod, stat, ls, mkdir — easily detected by feasibility classifier)
5. Proves three Linux verifier primitives in one lab
6. No dependency on external services
7. No credentials required
8. Directly maps to the North Star: reader reads about file permissions → practices in 5 minutes → result speaks for itself

---

## I. Linux Verifier Strategy

### Primitives (v0.1 scope)

| Primitive | Type Code | Check Method | Parameters |
|-----------|-----------|-------------|------------|
| File exists | `linux_file_exists` | `docker exec <id> test -f <path>` | `path` |
| Directory exists | `linux_directory_exists` | `docker exec <id> test -d <path>` | `path` |
| File content matches | `linux_file_content_matches` | `docker exec <id> grep -q <pattern> <path>` | `path`, `contains` |
| File mode matches | `linux_file_mode_matches` | `docker exec <id> stat -c %a <path>` compared to expected | `path`, `mode` (octal string) |
| No residual files | `linux_no_residual_files` | `docker exec <id> test ! -d <workspace>` (post-cleanup) | `workspace_path` |

`linux_command_output_contains` is **deferred from v0.1** — arbitrary command execution by the verifier is risky (injection, output redaction complexity, timeout enforcement). It can be added in v0.2 with strict allowlist enforcement.

### Verifier identity and permissions

- Verifier does NOT run as the learner user — it runs as a privileged agent with Docker API access
- Verifier has read-only access inside the container (via `docker exec --user root` for file reads; learner cannot impersonate verifier)
- No verifier credential is exposed to the learner
- All `docker exec` calls use the container ID from the session state (not learner-controlled input)

### Path security

All path parameters are validated before any `docker exec` call:
- Must be an absolute path
- Must start with `allowed_workspace_prefix` (e.g., `/home/learner/workspace`)
- Must not contain `..`, `//`, or shell metacharacters
- Must not be in `forbidden_paths` list
- Path length limit: 256 chars

### Timeout and output policy

- Per-check timeout: 10 seconds (configurable via `LinuxSandboxPolicy.verifier_timeout_seconds`)
- Max output captured: 65536 bytes (excess truncated, not exposed to learner)
- Verifier output is never directly returned to learner in raw form — only `passed: true/false` + `safe_message`
- No shell expansion in check commands (use `docker exec` with explicit argument list, not `sh -c`)

### Sandbox security guarantees

- Container runs with `--no-new-privileges`
- No `--privileged`
- No volume mounts outside the workspace directory
- No host network
- Read-only root filesystem except `/home/learner/workspace` and `/tmp`
- User: `learner` (UID 1000, non-root, no sudo)

---

## J. Linux Cleanup Strategy

### Per-session workspace lifecycle

```
Session Start
  → container_id assigned (from docker run)
  → session.sandbox_id = container_id

Session Active
  → learner operates inside container

Session Complete / Abort / Timeout
  → CLEANUP_REQUESTED
  → docker stop <container_id>  (SIGTERM, 10s timeout)
  → docker rm -f <container_id>  (force remove)
  → verify: docker ps -a | grep <container_id> → empty
  → cleanup_verified = True
  → LAB_CLOSED

Cleanup Failure
  → LAB_CLEANUP_FAILED
  → mark_sandbox_tainted(container_id)
  → log: cleanup_failure_reason
  → block reuse of this sandbox_id
```

### "练完即熟" in Linux domain

The Linux sandbox's "bind exactly" (练完即熟) moment:
- **Temporary workspace**: created per session, destroyed on completion
- **Credential reclaim**: no persistent credentials are issued (container access via Docker API, not SSH keys)
- **Process cleanup**: container stop kills all processes atomically (no orphaned processes)
- **Terminal close**: container removal closes the WebSocket shell session
- **Residual scan**: `docker ps -a | grep <id>` confirms container is gone
- **Taint on failure**: failed cleanup marks the container ID as tainted; the Docker API can be used to force-remove tainted containers on next admin audit

### Taint policy for Linux

| Event | Action |
|-------|--------|
| `docker rm` fails | mark container_id tainted; log failure_reason |
| Tainted container found at precheck | block session start (same as K8s taint policy) |
| Admin taint audit | `docker ps -a --filter label=labgen.tainted=true` → force remove |

---

## K. Linux Feasibility Gate

Linux-specific classification criteria:

### Directly Lab-Ready (Linux)

Must have all of:
- Clear bash/shell commands
- File paths within a standard home directory (no /etc, /root, /var/system)
- Expected command output that can be verified (file exists, content matches, mode matches)
- No root / sudo required
- No network access required
- No external service dependency
- No destructive system operations (no `rm -rf /`, no `dd`, no `mkfs`)
- Cleanup is trivial (delete workspace directory or destroy container)
- All operations completable in < 30 minutes
- Does not require real credentials, secrets, or production data

### Partially Lab-Ready (Linux)

Missing one or more of:
- File paths not specified precisely
- Commands given but expected output not described
- Root access required but could be redesigned for non-root
- Cleanup path unclear
- Depends on an external service (e.g., `curl` to internet)

### Reject (Linux)

Any of:
- Requires modifying `/etc/passwd`, `/etc/sudoers`, system services
- Requires real SSH keys, API tokens, or production credentials
- Requires internet access that cannot be substituted
- Requires kernel module loading, device file access, or hardware ops
- Operations are destructive to the host system
- Cannot be automatically verified
- Cannot be cleaned up (persistent state outside workspace)
- Involves security testing, privilege escalation, or vulnerability exploitation
- Requires multi-user concurrent interactions
- Article describes concept only, no executable steps

**Linux safety keywords that trigger automatic reject**:
`sudo rm -rf`, `chmod 777 /`, `dd if=`, `mkfs`, `fdisk`, `/etc/passwd`, `/etc/shadow`, `visudo`, `modprobe`, `insmod`, `reboot`, `shutdown`, `kill -9 1`, `iptables -F`, `ip link set`, `wget <external>`, `curl <external>`.

---

## L. Implementation Plan

Tasks in sequence. Each is a separate milestone gate.

### Task 1: Linux Domain Contract Schema Extension
**Scope**: Extend `models.py` and `article_models.py` with Linux-specific types.
- Add `LinuxVerifyType` enum (5 types: file_exists, file_content_matches, file_mode_matches, directory_exists, no_residual_files)
- Add `CleanupLinuxWorkspace` model
- Add `LinuxSandboxPolicy` model
- Unify `VerifyType` or create a union type for K8s + Linux
- Update `StaticValidator` to accept LinuxVerifyType in verify lists (not block as unknown)
- Tests: LinuxVerifyType not rejected by StaticValidator; CleanupLinuxWorkspace serializes correctly; K8s schemas unchanged
- Exit criteria: K8s tests unchanged; Linux schema expressible; StaticValidator can validate a Linux LabDraft

**Forbidden**: Do not modify K8s verifier, K8s adapter, or K8s session lifecycle.

### Task 2: Linux Sandbox Runtime Adapter Skeleton
**Scope**: Design and implement `WorkspaceLifecyclePort` + `DockerWorkspaceLifecycleAdapter` (skeleton, `NotImplementedError` stubs for real operations).
- Define `WorkspaceLifecyclePort(ABC)` with: `create_workspace`, `workspace_exists`, `destroy_workspace`, `is_workspace_destroyed`
- Implement `StubWorkspaceLifecycleAdapter` for tests
- Implement `DockerWorkspaceLifecycleAdapter` skeleton (real Docker calls: NotImplementedError in v0.1)
- Add `LINUX` to `NamespaceAdapterKind` in `runtime_adapter_selection.py`
- Add Linux adapter selection logic to `RuntimeAdapterSelectionService`
- Tests: Stub adapter correctly creates/destroys workspaces; selection logic returns Linux adapter for Linux runtime mode
- Exit criteria: Lab session can start with Linux runtime mode using stub adapter; K8s session unchanged

**Forbidden**: Do not implement real Docker calls. Do not modify K8s session lifecycle.

### Task 3: Linux Verifier Primitive Skeleton
**Scope**: Design `LinuxVerifierClientPort` + stub adapter + security validation.
- Define `LinuxVerifierClientPort(ABC)` with 5 methods matching `LinuxVerifyType`
- Implement `StubLinuxVerifierClientAdapter`
- Implement path security validator (workspace prefix check, forbidden path check, metacharacter rejection)
- Update `VerifierService` or create `LinuxVerifierService` to dispatch `LinuxVerifyType` checks
- Tests: All 5 primitive check types with stub adapter; path security rejects forbidden paths; metacharacters rejected; out-of-workspace paths rejected
- Exit criteria: Linux lab step check works end-to-end with stub adapter; K8s step check unchanged

**Forbidden**: Do not implement real `docker exec` calls. Do not modify K8s verifier.

### Task 4: Linux Guided Practice Draft Template
**Scope**: Create Lab 6 (Linux Files and Permissions Basics) as an admin-curated LabDraft using new Linux schema.
- Create article draft for "Linux Files and Permissions Basics" as a `pasted_text` input
- Run through stub feasibility classifier (with Linux keyword detection added from H-01/H-02)
- Admin reviews draft; fills in step content (why, observe, explain)
- Run StaticValidator (must pass with Linux verify types)
- Rehearsal required before publish
- Tests: Stub classifier detects Linux signals; draft passes StaticValidator; catalog isolation preserved
- Exit criteria: Linux LabDraft in APPROVED_FOR_INTERNAL_REHEARSAL status; all K8s tests unchanged

**Forbidden**: Do not publish Lab 6. Do not modify production VMID 500-599. Do not add K8s-coupled logic.

### Task 5: Linux Internal Rehearsal Bridge
**Scope**: Run Linux Lab 6 through internal rehearsal with Docker adapter (when Docker ops ticket is verified).
- OPS-LINUX-001: Provision Docker daemon + Linux sandbox base image
- Wire `DockerWorkspaceLifecycleAdapter` (real Docker calls)
- Wire `DockerLinuxVerifierClientAdapter` (real `docker exec` calls)
- Run internal rehearsal: start session → execute steps → step check PASS → complete → cleanup verified
- Tests: Integration test with real Docker (skipped in CI; only in home_lab_mvp mode)
- Exit criteria: LAB_CLOSED, cleanup_verified=True, container residual=0

**Forbidden**: Do not open to learners. Do not publish. Do not modify K8s runtime.

### Task 6: Linux Publish Gate Dry Run
**Scope**: Publish Linux Lab 6; admin verify catalog; internal dry run as learner.
- Full publish gate: StaticValidator PASS, Publish Gate PASS, catalog isolation
- Internal dry run: developer account executes Lab 6 end-to-end
- Guided Practice content quality check (no TODO placeholders)
- Tests: Placeholder gate PASS; catalog shows Linux lab; K8s labs unaffected
- Exit criteria: LINUX_DOMAIN_PROOF_DESIGN_READY_FOR_INTERNAL_REHEARSAL

**Forbidden**: Do not open to external learners. Do not increase concurrency. Do not modify K8s labs.

### Task 7: Linux Trusted Reader Pilot
**Scope**: Same as K8s Trusted Reader Pilot, for Linux Lab 6.
- Invite one trusted reader (non-developer)
- Observe and record session
- Verify: complete, cleanup_verified=True, no container residual, observer-confirmed no hiccups
- Exit criteria: LINUX_DOMAIN_PROOF_COMPLETE

**Forbidden**: Do not open to general readers. Do not customer pilot. Do not public launch.

---

## M. Risks and Blockers

### BLOCKER

| ID | Risk | Mitigation |
|----|------|-----------|
| R-B-01 | `VerifyType` enum is K8s-only — Linux lab contract cannot be expressed until schema extension is done | Task 1 must complete before Tasks 2-7 |
| R-B-02 | Docker daemon availability on Proxmox host is unconfirmed | OPS-LINUX-001 must be verified before Task 5; if Docker unavailable, need alternative sandbox runtime |
| R-B-03 | `CleanupNamespace` is K8s-only — Linux cleanup cannot be modeled | Task 1 (CleanupLinuxWorkspace) resolves this |
| R-B-04 | `NamespaceAdapterKind` has no LINUX option — runtime selection will fail for Linux sessions | Task 2 resolves this |

### HIGH

| ID | Risk | Mitigation |
|----|------|-----------|
| R-H-01 | `_pick_target_domain` K8s-priority bias means Linux articles fall to UNKNOWN (blocked by StaticValidator) | Fix in Task 4 (stub classifier + domain pick logic) |
| R-H-02 | Container terminal session (learner shell in Docker) requires a new WebSocket adapter — current terminal is SSH-based (K8s VM SSH) | Design and implement in Task 5; prototype needed before user testing |
| R-H-03 | Linux verifier using `docker exec` adds a new privileged path — FastAPI process needs Docker socket access | Security review required: Docker socket access = root-equivalent on host. Mitigations: dedicated verifier process, Docker-over-TCP with TLS, or rootless Docker. Must not expose Docker socket to learner in any scenario. |

### MEDIUM

| ID | Risk | Mitigation |
|----|------|-----------|
| R-M-01 | K8s lab tests may be broken by `VerifyType` union changes | Run full test suite after Task 1; K8s verify types must remain working |
| R-M-02 | Linux sandbox base image pulls may be slow (cold start) | Pre-pull and cache base images; add image check to OPS-LINUX-001 ticket |
| R-M-03 | `LabSessionState.namespace` field repurposing for Linux sandbox_id is confusing | Document repurposing OR add `sandbox_id` field in Task 1 |
| R-M-04 | Frontend labgen-lab.html uses K8s-specific language ("namespace", "kubectl terminal") | Needs conditional rendering by domain; defer to Task 6 |

### LOW / NOTE

| ID | Note |
|----|------|
| N-01 | `LabSessionStatus` names (NAMESPACE_CREATING, etc.) remain K8s-labeled even for Linux sessions — cosmetic issue, not functional |
| N-02 | AI tutor context for Linux must be different from K8s tutor (different domain, different hints, different forbidden operations) — design when Lab 6 content is written |
| N-03 | Linux sandbox does not need verifier RBAC (no K8s RoleBinding) — VERIFIER_BINDING_CREATING state is a no-op for Linux; must be handled gracefully |

---

## N. Final Decision

**LINUX_DOMAIN_PROOF_DESIGN_READY_WITH_NOTES**

The Linux domain proof design is sound and grounded in the existing architecture. The platform was designed for domain portability from the start — `TargetDomain.LINUX` exists, `ArticleRuntimeType.LINUX_VM` exists, port abstractions are in place. The 5 BLOCKER coupling items are enumerable and bounded. Implementation can begin immediately with Task 1 (schema extension) — no architectural redesign is required.

The key risks are:
1. Docker daemon availability (ops dependency — must verify before Task 5)
2. Container terminal WebSocket adapter (new implementation required)
3. Docker socket security (must not expose to learner; verifier-only privileged path)

The North Star is preserved: the platform proves it can turn "Linux files and permissions" article content into a 5-minute, isolated, verifiable, cleanable experiment — the same reader-to-result loop that the K8s domain proof established.

**What this decision does NOT mean:**
- Linux support is not implemented yet
- Multi-domain portability is not yet proven (only designed)
- arbitrary Article-to-Linux is not yet possible
- Production Linux labs do not exist
- K8s is not the only domain (it is still the only working one)

---

## O. Recommended Next Step

**Linux Domain Contract Schema Extension** (Task 1)

This is the right first step because:
1. It unblocks everything else (Tasks 2-7 all depend on Linux schema expressibility)
2. It is docs+code only, with zero risk to K8s runtime
3. It can be done immediately (no ops dependency)
4. It produces a verifiable exit criterion: a Linux LabDraft can be expressed and pass StaticValidator

After Task 1 completes:
- OPS-LINUX-001 (Docker provisioning) can run in parallel with Tasks 2-3
- Tasks 2 and 3 (adapter skeleton + verifier skeleton) can also proceed in parallel

---

## P. Modified Files

| File | Change |
|------|--------|
| `docs/labgen/LINUX_DOMAIN_PROOF_DESIGN_GATE_v0.1.md` | Created (this document) |
| `docs/labgen/PROJECT_NORTH_STAR_v0.1.md` | Pipeline progress table updated (see below) |
| `docs/labgen/GUIDED_PRACTICE_QUALITY_ITERATION_LAB5_RESULT_v0.1.md` | Status confirmed: PASSED for Trusted Reader |
| `deploy/labgen/staging_ops_ticket_status.md` | Linux Domain Proof Design Gate status recorded |
| `CHANGELOG.md` | Updated |

---

## Q. North Star Gate Table Update

| Gate | Status | Evidence |
|------|--------|----------|
| K8s Domain Proof (4 labs, 3 rounds real human validation) | ✅ COMPLETE | `REAL_HUMAN_COHORT_ROUND2_RESULT_v0.1.md` |
| Article-to-Lab Pipeline Design Gate | ✅ COMPLETE | `ARTICLE_TO_LAB_PIPELINE_DESIGN_GATE_v0.1.md` |
| Article-to-Lab Implementation Prerequisites | ✅ COMPLETE | `ARTICLE_TO_LAB_IMPLEMENTATION_PREREQUISITES_v0.1.md` |
| Article-to-Lab MVP Contract Schema Gate | ✅ COMPLETE | `ARTICLE_TO_LAB_MVP_CONTRACT_SCHEMA_GATE_v0.1.md` |
| K8s Article-to-Lab Draft Mode Implementation | ✅ COMPLETE | `K8S_ARTICLE_TO_LAB_DRAFT_MODE_IMPLEMENTATION_RESULT_v0.1.md` |
| K8s Article-to-Lab Admin Review Rehearsal | ✅ COMPLETE | `K8S_ARTICLE_TO_LAB_ADMIN_REVIEW_REHEARSAL_RESULT_v0.1.md` |
| K8s Article-to-Lab Reader-facing CTA Dry Run | ✅ COMPLETE | `READER_FACING_ARTICLE_CTA_DRY_RUN_RESULT_v0.1.md` |
| K8s Guided Practice Quality Iteration Lab 5 | ✅ COMPLETE | `GUIDED_PRACTICE_QUALITY_ITERATION_LAB5_RESULT_v0.1.md` |
| **K8s Article-linked Lab Trusted Reader Pilot** | ✅ **COMPLETE** | session a301676a, LAB_CLOSED, cleanup_verified=True, both steps PASS, observer no hiccups |
| **Linux Domain Proof Design Gate** | ✅ **COMPLETE** | This document — LINUX_DOMAIN_PROOF_DESIGN_READY_WITH_NOTES |
| Linux Domain Contract Schema Extension | ⬜ NEXT | After this gate |
| Linux Sandbox Runtime Adapter Skeleton | ⬜ PENDING | After schema extension |
| Linux Verifier Primitive Skeleton | ⬜ PENDING | After schema extension |
| Linux Guided Practice Draft Template | ⬜ PENDING | After adapter skeleton |
| Linux Internal Rehearsal Bridge | ⬜ PENDING | After Docker ops provisioning |
| Linux Publish Gate Dry Run | ⬜ PENDING | After internal rehearsal |
| Linux Trusted Reader Pilot | ⬜ PENDING | After publish gate |
| Docker Domain Proof | ⬜ PENDING | After Linux domain proof |
