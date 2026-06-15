# Home-Lab MVP Ops Runbook v0.1

**Profile**: `home_lab_mvp` (T430 / Proxmox VE, single physical host)  
**Status**: ACTIVE — controlled pilot onboarding  
**Date**: 2026-06-14  
**Basis**: Second Trusted Pilot User Gate v0.1 (commit `2da3136`, SECOND_PILOT_USER_ONBOARDED)  
**Related profile doc**: `docs/labgen/HOME_LAB_MVP_STAGING_PROFILE_v0.1.md`  
**No real secrets in this document.**

---

## A. Scope

### What this runbook covers

Operational procedures for running LabGen in `home_lab_mvp` mode on a single Proxmox host
(Dell T430), specifically for controlled pilot onboarding of a small number of trusted users.

- Hardware: Dell T430 / Proxmox VE, single physical host, `pve`.
- K3s control plane: staging VM in VMID range 400–499 (currently VM 401,
  hostname `labgen-home-k3s-staging-01`, IP `<VM-IP>` — check with `qm guest info 401`).
- Staging pool: `k8s-netlab-staging`.
- Verifier credential root: `/var/lib/labgen-staging/verifier-credentials/`.
- Platform kubeconfig: `/etc/labgen/home_lab_mvp.kubeconfig` (chmod 600, repo-external).
- Env file: `/etc/labgen/home_lab_mvp.env` (chmod 600, repo-external).
- Backend service: `k8s-netlab.service` (FastAPI, port 8000).

### What this runbook does NOT cover

| Excluded | Reason |
|---------|--------|
| Production VMID range 500–599 | Must not be touched in home_lab_mvp ops |
| HA or multi-node Proxmox | Single server, no HA, no SLA |
| LLM pipeline operations | `LABGEN_LLM_PROVIDER_MODE=fake_only` in this profile |
| Cloud deployment (EKS/ACK) | Separate profile; see Section G |
| Public launch or general availability | Small trusted pilot only |
| Concurrent sessions > 1 | Enforced limit for this profile |

---

## B. Critical Rules

These rules apply unconditionally. Violating them stops pilot immediately.

| Rule | Enforcement |
|------|-------------|
| VMID 500–599 must NEVER be touched | Explicit check before any `qm` command |
| Staging VMs must use pool `k8s-netlab-staging` | Verify with `pvesh get /pools/k8s-netlab-staging` |
| Staging VMID range: 400–499 | Any clone or creation must be inside this range |
| LLM disabled: `LABGEN_LLM_PROVIDER_MODE=fake_only` | Check at startup; do not change |
| Max active runtime session: 1 | Enforced by backend; do not raise |
| Max staging VMs: 3 | `MAX_TOTAL_VMS=3` in env file; do not raise |
| No secrets in repo/docs/logs | kubeconfig content, token, password must never appear in files, logs, or responses |
| Cleanup failure stops new sessions | VM taint prevents reuse until cleared by ops; do not bypass |
| Tainted VM stops new sessions | See Section D.4 for recovery |
| Namespace residual stops new sessions | Confirm 0 `lab-*` namespaces before next session |
| home_lab_mvp is NOT HA production | Never describe this profile as HA or production-grade |

---

## C. Verifier Initialization: Correct home_lab_mvp Path

### C.1 Function to use

For the `home_lab_mvp` profile, verifier initialization MUST use:

```python
from backend.vm_manager import initialize_verifier_for_vm_host_side

result = initialize_verifier_for_vm_host_side(
    vm_id=401,
    platform_kubeconfig_path="/etc/labgen/home_lab_mvp.kubeconfig",
)
assert result["success"] is True
```

**This is the only accepted verifier initialization path for home_lab_mvp.**

### C.2 Why host-side, not QEMU-agent

Two functions exist. They are NOT interchangeable for home_lab_mvp:

| Function | Mechanism | kubeconfig server field | Usable for home_lab_mvp? |
|----------|-----------|------------------------|--------------------------|
| `initialize_verifier_for_vm` | QEMU guest agent — runs inside student VM | `server: https://127.0.0.1:6443` (VM-local) | **NO — FORBIDDEN** |
| `initialize_verifier_for_vm_host_side` | Python kubernetes client — connects from Proxmox host using platform kubeconfig | `server: https://<VM-IP>:6443` (host-reachable) | **YES — REQUIRED** |

**Why `initialize_verifier_for_vm` is forbidden for home_lab_mvp:**

- It creates a verifier kubeconfig with `server: https://127.0.0.1:6443`.
- The backend runs on the Proxmox host, not inside the VM.
- `127.0.0.1:6443` is unreachable from the host — every step check will return
  `credential_missing` or a connection error.
- The platform K3s cluster runs on VM 401; the host-side function connects to
  `<VM-IP>:6443` (the VM's actual IP) via the platform kubeconfig, which is the correct endpoint.

**Do not use `initialize_verifier_for_vm` for home_lab_mvp under any circumstances.**

### C.3 Precheck before running host-side initialization

```bash
# 1. Platform kubeconfig exists outside repo, correct permissions
ls -la /etc/labgen/home_lab_mvp.kubeconfig
# Expected: -rw------- (600 or stricter)

# 2. kubeconfig is not a placeholder
grep -c "server:" /etc/labgen/home_lab_mvp.kubeconfig
# Expected: 1 or more (must contain a real server entry)

# 3. K3s VM 401 is running and K3s is Ready
ssh <VM-IP> "kubectl get nodes --no-headers"
# Expected: labgen-home-k3s-staging-01   Ready   ...

# 4. Verifier credential root exists with correct permissions
ls -la /var/lib/labgen-staging/verifier-credentials/
# Expected: drwx------ (700 or stricter)

# 5. No stale credential generation for this VM
ls /var/lib/labgen-staging/verifier-credentials/401/ 2>/dev/null || echo "not found (clean)"
```

### C.4 Running host-side initialization

```bash
cd /root/k8s-netlab
source venv/bin/activate

python3 - <<'EOF'
from backend.vm_manager import initialize_verifier_for_vm_host_side
result = initialize_verifier_for_vm_host_side(
    401,
    "/etc/labgen/home_lab_mvp.kubeconfig",
)
print("success:", result["success"])
print("generation:", result.get("data", {}).get("credential_generation"))
if not result["success"]:
    print("ERROR:", result["error"])
    raise SystemExit(1)
EOF
```

Expected output:
```
success: True
generation: <integer ≥ 1>
```

### C.5 Verify credential was stored

```bash
ls /var/lib/labgen-staging/verifier-credentials/401/
# Expected: kubeconfig file present
```

**Security: never print kubeconfig content. Never log kubeconfig. Never commit
kubeconfig path contents to repo.**

### C.6 Forbidden patterns

```python
# FORBIDDEN for home_lab_mvp
from backend.vm_manager import initialize_verifier_for_vm
initialize_verifier_for_vm(401)  # Creates kubeconfig with 127.0.0.1 — UNUSABLE from host

# FORBIDDEN
# Do not copy kubeconfig into repo
# Do not print token or cert in logs
# Do not use production VMIDs (500–599)
# Do not create ClusterRoleBinding unless explicitly justified and gated
```

---

## D. VM and K3s Recovery Procedures

### D.1 Full health check sequence

Run before any pilot session:

```bash
# 1. Production VMID 500–599 — confirm untouched
qm list | awk '$1 >= 500 && $1 <= 599 {print}'
# Expected: only production VMs (do not modify them)

# 2. Staging VM 401 status
qm status 401
# Expected: status: running

# 3. K3s node Ready
kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get nodes
# Expected: labgen-home-k3s-staging-01   Ready   ...

# 4. No lab namespaces residual
kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get ns | grep "^lab-"
# Expected: (no output)

# 5. No tainted VMs
cat /root/k8s-netlab/data-staging/tainted_vms.json
# Expected: [] or {}

# 6. Verifier credential store populated
ls /var/lib/labgen-staging/verifier-credentials/401/
# Expected: kubeconfig file present

# 7. Backend service running
curl -sf http://localhost:8000/api/health
# Expected: {"status":"healthy"}

# 8. No active lab sessions
cat /root/k8s-netlab/data-staging/lab_sessions.json | python3 -c \
  "import json,sys; d=json.load(sys.stdin); active=[s for s in d.values() if s.get('lab_session_status') not in ('LAB_CLOSED','LAB_ABORTED','LAB_CLEANUP_FAILED')]; print('active:', len(active))"
# Expected: active: 0
```

### D.2 K3s VM 401 is stopped or unreachable

```bash
# Start VM 401
qm start 401

# Wait for K3s to become Ready (up to 3 minutes)
for i in $(seq 1 18); do
  kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get nodes --no-headers 2>/dev/null \
    | grep -q "Ready" && echo "K3s Ready" && break
  echo "Waiting... ($i/18)"
  sleep 10
done

# Confirm K3s is Ready before proceeding
kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get nodes
```

### D.3 K3s not starting (hostname conflict / stale etcd)

Symptom: `systemctl status k3s` shows `activating (auto-restart)` in a loop.

Root cause: stale etcd identity from template hostname (e.g., `k8s-template`).

```bash
# SSH into VM 401
ssh root@<VM-IP>   # get VM IP via: qm guest info 401 | grep ip

# Fix hostname to match expected identity
hostnamectl set-hostname labgen-home-k3s-staging-01

# Clear stale etcd and restart K3s
systemctl stop k3s
rm -rf /var/lib/rancher/k3s/server/db/etcd
systemctl start k3s

# Wait for K3s to start (up to 3 minutes)
systemctl is-active k3s
```

After K3s restarts:

```bash
# Remove stale node entry (if k8s-template node appears)
kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get nodes
# If stale node exists (not labgen-home-k3s-staging-01):
kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig delete node k8s-template
```

After K3s recovery, re-run host-side verifier initialization (Section C.4) to refresh
credentials pointing to the correct endpoint.

### D.4 Tainted VM recovery

A VM is tainted when cleanup fails. Tainted VMs cannot host new sessions.

```bash
# Check tainted VMs
cat /root/k8s-netlab/data-staging/tainted_vms.json

# If VM 401 is tainted:
# 1. Confirm no active sessions
# 2. Confirm namespace cleanup is complete:
kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get ns | grep "^lab-"
# Expected: no output

# 3. Clear taint via admin API
curl -X POST http://localhost:8000/internal/vms/401/untaint \
  -H "X-Admin-Token: <staging-admin-token>"
# Or manually edit data-staging/tainted_vms.json and remove VM 401 entry
```

**Do not untaint a VM while a cleanup operation is still in progress.**

### D.5 VM 401 rebuild from template

Required when VM 401 is unrecoverable (disk corruption, permanent K3s failure).

```bash
# STOP any running sessions first (admin abort via API)
# Confirm production VMID 500–599 are safe — do not clone into that range

# Clone from template 101 into staging range (400–499)
qm clone 101 401 --full 1 --storage local-lvm --name labgen-home-k3s-staging-01

# Add to staging pool
pvesh set /pools/k8s-netlab-staging --vms 401

# Set memory (4096 MB)
qm set 401 --memory 4096

# Start VM
qm start 401

# Wait for SSH availability (up to 2 minutes)
# Then follow D.3 to fix hostname and reset K3s etcd if needed

# After K3s is Ready, re-run host-side verifier initialization
# DO NOT call initialize_verifier_for_vm — use initialize_verifier_for_vm_host_side
```

---

## E. Pilot Operation Procedures

### E.1 Pre-session checklist (before each pilot user session)

| Check | Command | Expected |
|-------|---------|----------|
| Production VMID 500–599 untouched | `qm list \| awk '$1 >= 500 && $1 <= 599'` | Production VMs only; do not modify |
| VM 401 running | `qm status 401` | `status: running` |
| K3s Ready | `kubectl --kubeconfig ... get nodes` | `Ready` |
| No active lab sessions | Check `data-staging/lab_sessions.json` | 0 active |
| No lab namespaces | `kubectl --kubeconfig ... get ns \| grep '^lab-'` | No output |
| No tainted VMs | `cat data-staging/tainted_vms.json` | `[]` |
| Verifier credentials present | `ls /var/lib/labgen-staging/verifier-credentials/401/` | kubeconfig present |
| Backend healthy | `curl -sf http://localhost:8000/api/health` | `{"status":"healthy"}` |
| LLM disabled | Check `/proc/<pid>/environ` or env file | `LABGEN_LLM_PROVIDER_MODE=fake_only` |

All checks must pass before admitting a pilot user.

### E.2 During user session monitoring

```bash
# Watch lab sessions in real time
watch -n 5 'cat /root/k8s-netlab/data-staging/lab_sessions.json | python3 -c \
  "import json,sys; d=json.load(sys.stdin); [print(k[:8], v.get(\"lab_session_status\")) for k,v in d.items()]"'

# Check K3s namespaces
watch -n 10 'kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get ns | grep "^lab-"'

# Watch backend logs for errors
journalctl -u k8s-netlab -f --no-pager
```

### E.3 Post-session cleanup checklist

After each pilot session (LAB_CLOSED or LAB_ABORTED):

| Check | Command | Expected |
|-------|---------|----------|
| Session state | Check lab_sessions.json | `LAB_CLOSED` or `LAB_ABORTED` |
| cleanup_verified | Check lab_sessions.json | `true` |
| Namespace removed | `kubectl --kubeconfig ... get ns \| grep '^lab-'` | No output |
| RoleBinding removed | `kubectl --kubeconfig ... get rolebinding -A \| grep lab-verifier` | No output |
| Tainted VMs | `cat data-staging/tainted_vms.json` | `[]` |
| Backend error logs | `journalctl -u k8s-netlab -p err --since "10 minutes ago"` | No new errors |

If any check fails, block the next session until resolved.

### E.4 Audit preservation

After each pilot session, preserve evidence:

```bash
# Copy session state snapshot
cp /root/k8s-netlab/data-staging/lab_sessions.json \
   /root/k8s-netlab/data-staging/snapshots/lab_sessions_$(date +%Y%m%d_%H%M%S).json

# Preserve backend logs for session window
journalctl -u k8s-netlab --since "60 minutes ago" --no-pager \
  > /root/k8s-netlab/data-staging/snapshots/service_log_$(date +%Y%m%d_%H%M%S).log
```

### E.5 Feedback capture

After each session, capture:
1. Did the user complete the lab or abort?
2. Was `cleanup_verified=True`?
3. Were any backend errors logged?
4. User-reported confusion or friction (if human user, capture verbatim).
5. Any new bugs or ops gaps discovered.

File feedback in `docs/labgen/` as a result artifact before the next gate.

---

## F. Emergency Stop

Use when: unexpected session failure, VM taint, credential leak, security incident,
or backend crash during a live pilot session.

### F.1 Stop accepting new sessions

```bash
# Temporarily set max total VMs to 0 (prevents new sessions)
# Update /etc/labgen/home_lab_mvp.env:
# MAX_TOTAL_VMS=0
# Then restart service:
systemctl restart k8s-netlab
sleep 3
curl -sf http://localhost:8000/api/health
```

### F.2 Abort in-flight sessions

```bash
# List active session IDs from lab_sessions.json, then abort each
curl -X POST http://localhost:8000/api/lab-sessions/<session-id>/abort \
  -H "X-Admin-Token: <staging-admin-token>"
```

### F.3 Stop staging VMs (VMID 400–499 only)

```bash
# List and stop staging VMs only
qm list | awk '$1 >= 400 && $1 <= 499 {print $1}' | while read vmid; do
  echo "Stopping staging VM $vmid"
  qm stop "$vmid"
done
# NEVER run qm stop on VMID 500–599 (production range)
```

### F.4 Cleanup residual namespaces

```bash
kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig get ns \
  | grep "^lab-" | awk '{print $1}' | while read ns; do
  echo "Deleting namespace $ns"
  kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig delete ns "$ns"
done
```

### F.5 Reclaim verifier credentials

```bash
# If credential leak is suspected, rotate by re-initializing (see Section C.4)
# New generation will invalidate old kubeconfig
```

### F.6 Preserve audit logs

```bash
journalctl -u k8s-netlab --since "2 hours ago" --no-pager \
  > /root/k8s-netlab/data-staging/snapshots/emergency_log_$(date +%Y%m%d_%H%M%S).log
```

### F.7 Record incident

Create `docs/labgen/INCIDENT_<date>_<short-description>.md` with:
- What happened
- Timeline
- Impact (sessions affected, users affected)
- Root cause (if known)
- Recovery steps taken
- Prevention

---

## G. Cloud Portability Notes

### G.1 Why this runbook is home_lab_mvp-specific

This runbook describes Proxmox-specific operations (VM cloning, `qm` commands, pool management).
These are provider-specific and do not belong in the core LabGen contract.

### G.2 What does NOT change on cloud migration

The following are stable across `home_lab_mvp` and `cloud` profiles:
- `K3sNamespaceLifecycleAdapter` — uses Kubernetes API only, no Proxmox coupling.
- `VerifierCredentialStore` — file-based, path-configurable.
- `LabSessionService` state machine — provider-agnostic.
- All backend logic in `backend/labgen/` — no Proxmox imports.
- Verifier client (`K8sVerifierClientAdapter`) — uses kubeconfig, not QEMU agent.

### G.3 Mapping host-side verifier init to cloud

On cloud (EKS, ACK, GKE):
- Replace `/etc/labgen/home_lab_mvp.kubeconfig` with the cloud-managed kubeconfig
  (e.g., from `aws eks update-kubeconfig` or equivalent).
- `initialize_verifier_for_vm_host_side` continues to work — it accepts any kubeconfig
  path that points to a reachable K8s API server.
- The QEMU-agent path (`initialize_verifier_for_vm`) is Proxmox-only and has no cloud equivalent.
  Do not attempt to port it to cloud deployments.

### G.4 Cloud migration trigger

See `docs/labgen/HOME_LAB_MVP_STAGING_PROFILE_v0.1.md` Section G for exit criteria.
When any trigger fires, provision a cloud K8s cluster, set `LABGEN_RUNTIME_MODE=cloud`,
and provide the cloud kubeconfig to `initialize_verifier_for_vm_host_side`.

---

## H. OPS-INIT-001 Resolution Record

**Issue**: `initialize_verifier_for_vm` (QEMU-agent path) was mistakenly called for VM 401
during Second Trusted Pilot User Gate v0.1 (2026-06-14). This created a verifier kubeconfig
with `server: https://127.0.0.1:6443`, which is unreachable from the Proxmox host.

**Correct path**: `initialize_verifier_for_vm_host_side(vm_id, platform_kubeconfig_path)`.

**Status**: DOCUMENTED in this runbook (Section C). The function `initialize_verifier_for_vm`
remains available for student VM scenarios (not home_lab_mvp).

**Evidence**: `docs/labgen/SECOND_PILOT_USER_ONBOARDING_RESULT_v0.1.md` Section K,
commit `2da3136`, verifier re-initialized with host-side path, gen=2, smoke passed.

---

## I. RBAC-DRIFT-001 Resolution Record (2026-06-15)

**Issue**: ClusterRole `lab-verifier-namespace-readonly` on K3s contained stale rules after
multiple code commits had narrowed the intended RBAC. The live ClusterRole still had:
- `get` verb granted on pods, services, configmaps, namespaces, endpoints
- `namespaces` and `endpoints` resources (not used by any verifier method)
- `daemonsets`, `statefulsets`, `replicasets` in the apps group (not used)

**Root cause**: `PlatformVerifierInitializer.ensure_verifier_identity` used a create+409-skip
pattern. When `create_cluster_role` returned 409 AlreadyExists, the exception was silently
discarded. Re-running `ensure_verifier_identity` never updated the live ClusterRole — code
fixes narrowed the manifest, but the K3s live rules were never applied.

**Fix** (commit `b48a9a2`):
- `ensure_verifier_identity` now calls `replace_cluster_role` (PUT semantics) first.
  If K3s returns 404 (ClusterRole does not exist), it falls back to `create_cluster_role`.
- Re-running `ensure_verifier_identity` always applies the current manifest rules.
- `_CLUSTER_ROLE_MANIFEST` and `V1ClusterRole` SDK object now contain:
  - Core: pods, services, configmaps — list, watch only (no get)
  - Secrets: secrets — list, watch only
  - Apps: deployments only — list, watch only
  - No namespaces, no endpoints, no get on any resource

**Operator behavior after this fix**:
Running `initialize_verifier_for_vm_host_side(401, platform_kubeconfig)` (Section C)
will call `ensure_verifier_identity` which REPLACES the live ClusterRole with the current
manifest. No manual kubectl intervention is needed. This is idempotent: re-running it
is safe and always converges to the correct least-privilege state.

**Precheck guardrail** (add to Section E.1 mental model):
After `initialize_verifier_for_vm_host_side`, you can confirm the live ClusterRole via:
```bash
kubectl --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig \
  get clusterrole lab-verifier-namespace-readonly -o yaml | grep -A3 "verbs:"
# Expected: only "list" and "watch" — no "get" on any rule
```

**Evidence**: `docs/labgen/SEVENTH_PILOT_USER_DEPLOYMENT_LAB_RESULT_v0.1.md` Section D,
commit `b48a9a2`, 12 regression tests added (guardrail + parity + replace semantics).

---

*Not HA. Not production-grade. Not for general availability.*  
*home_lab_mvp is a controlled pilot profile on single-node Proxmox (T430).*  
*No real secrets appear in this document.*  
*Production VMID range 500–599 must not be touched during home_lab_mvp operations.*
