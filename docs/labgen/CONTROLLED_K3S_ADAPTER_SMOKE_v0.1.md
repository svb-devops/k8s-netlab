# Controlled K3s Adapter Smoke v0.1

**Date:** 2026-06-12
**Author:** Claude Code (automated)
**Executed by:** dev — code and precheck complete; write phase awaiting ops

---

## A. Scope

This document covers one specific verification:

| In scope | Out of scope |
|----------|-------------|
| Namespace create / verify / delete | Full lab session |
| Verifier RoleBinding create / verify | Runtime start |
| K3sNamespaceLifecycleAdapter real path | Proxmox VM lifecycle |
| Namespace prefix enforcement | Registry image lifecycle |
| Cleanup confirmation | LLM pipeline |
| Evidence sanitization | Client traffic |

**Decision impact:** K3S_SMOKE_PASSED means only that namespace lifecycle works under home_lab_mvp profile. It does NOT mean:
- Full live trial passed
- Production cutover is ready
- HA is guaranteed
- cloud portability constraints removed

The next milestone after K3S_SMOKE_PASSED is **Controlled Home-Lab Runtime Session Smoke v0.1**.

---

## B. Preconditions

All must be satisfied before executing the write phase. The precheck (`--env-file` without `--allow-k8s-write`) validates them automatically.

| # | Precondition | Check |
|---|-------------|-------|
| B-1 | Real home_lab_mvp env file exists (not `.env.staging.example`) | Phase 0 |
| B-2 | `LABGEN_RUNTIME_MODE=home_lab_mvp` | Phase 0 |
| B-3 | `LABGEN_NAMESPACE_ADAPTER=k8s` (stub forbidden) | Phase 0 |
| B-4 | `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` set, not a placeholder | Phase 0 |
| B-5 | `LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES` configured (e.g. `lab-stg-`) | Phase 0 |
| B-6 | Verifier SA / role / rolebinding config set | Phase 0 |
| B-7 | Kubeconfig file exists at configured path | Phase 1 |
| B-8 | Not using production secrets | Operator check |
| B-9 | Not using production namespace prefix | Phase 0 (prefix must differ from `lab-`) |
| B-10 | Proxmox / registry NOT required for namespace-only smoke | N/A — not blocked |

---

## C. Smoke Phases

| Phase | Description | Required |
|-------|-------------|---------|
| Phase 0 | Env / profile validation | Blocking |
| Phase 1 | Secret injection verification (kubeconfig file exists) | Blocking |
| Phase 2 | Precheck gate | Blocking |
| Phase 3 | Create one controlled smoke namespace | Required for PASSED |
| Phase 4 | Verify namespace exists | Warning only |
| Phase 5 | Create verifier RoleBinding (namespace-scoped) | Warning only |
| Phase 6 | Verify RoleBinding exists | Warning only |
| Phase 7 | Check namespace not stuck terminating | Warning only |
| Phase 8 | Delete namespace (always in finally) | Required — fail = K3S_SMOKE_FAILED |
| Phase 9 | Confirm deletion accepted | Required — fail = K3S_SMOKE_FAILED |
| Phase 10 | Evidence sanitization confirmation | Informational |

### Namespace operation limits

The smoke creates exactly:
- 1 namespace with name: `{allowed_prefix}smoke-{6_random_chars}`
- 1 verifier RoleBinding (namespace-scoped only — no ClusterRoleBinding)

Forbidden during smoke:
- Touching `default`, `kube-system`, `kube-public`, `kube-node-lease`
- Any namespace without the configured allowed prefix
- Operating on existing business namespaces
- Batch namespace creation

---

## D. Final Decision

Exactly four possible outcomes:

| Decision | Meaning |
|----------|---------|
| `K3S_SMOKE_PASSED` | All phases pass, cleanup confirmed |
| `K3S_SMOKE_PASSED_WITH_NOTES` | All required phases pass; warnings present (e.g. RoleBinding issue) |
| `K3S_SMOKE_BLOCKED` | Preconditions not met — no K8s writes executed |
| `K3S_SMOKE_FAILED` | K8s write attempt failed, or cleanup failed (namespace may be residual) |

---

## E. Evidence Rules

The smoke script enforces:

- Only sanitized namespace names are recorded (e.g. `lab-stg-smoke-abc123`)
- Kubeconfig content is never logged or included in result
- Tokens are never logged or included in result
- Raw Kubernetes exception bodies are never exposed — sanitized to `status=N reason=X`
- Sensitive env values are never printed
- Production endpoints are never accessed

---

## F. Execution

### Step 1: Precheck (safe, no K8s writes)

```bash
python scripts/labgen_controlled_k3s_adapter_smoke.py \
    --env-file <home-lab-env-file>
```

Or with JSON output:

```bash
python scripts/labgen_controlled_k3s_adapter_smoke.py \
    --env-file <home-lab-env-file> --json
```

### Step 2: Namespace lifecycle smoke (requires operator authorization)

Only run after confirming all preconditions are met and operator explicitly authorizes:

```bash
python scripts/labgen_controlled_k3s_adapter_smoke.py \
    --env-file <home-lab-env-file> --allow-k8s-write --json
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | K3S_SMOKE_PASSED or K3S_SMOKE_PASSED_WITH_NOTES |
| 1 | K3S_SMOKE_FAILED |
| 2 | K3S_SMOKE_BLOCKED |

---

## G. Current Execution Result (2026-06-12)

### Precheck Result

```
Decision: K3S_SMOKE_BLOCKED
```

Executed against: `deploy/labgen/.env.staging.example`

| Phase | Status | Message |
|-------|--------|---------|
| phase0_env_profile | BLOCKED | Profile validation failed |
| phase1_secret_injection | PASS | Secret injection verified |
| phase2_precheck | BLOCKED | Blocked: 1 precondition(s) not met |

Missing inputs:
- `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` is not set or is a placeholder — inject the real kubeconfig path

Audit confirmation:
- `runtime_start_executed: false` ✓
- `proxmox_called: false` ✓
- `registry_called: false` ✓
- `llm_called: false` ✓
- `wrote_namespace: false` ✓
- `wrote_rolebinding: false` ✓

### Why BLOCKED

No real home_lab_mvp env file exists. The `.env.staging.example` template has
`LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-staging-secret-manager>` which is a placeholder.

The code path (K3sNamespaceLifecycleAdapter) is fully implemented and tested with
57 unit tests. The blocker is an **ops-side input** (kubeconfig injection), not a code blocker.

---

## H. Unblock Path

To reach K3S_SMOKE_PASSED, ops must complete:

1. Create real `.env.home_lab` (or `.env.staging`) — not the example template
2. Set `LABGEN_RUNTIME_MODE=home_lab_mvp`
3. Set `LABGEN_NAMESPACE_ADAPTER=k8s`
4. Inject real kubeconfig path: `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/path/to/kubeconfig`
   - Same-cluster option: use the K3s cluster kubeconfig from the T430 host
   - Separate-VM option: deploy a separate K3s VM, use its kubeconfig
5. Set `LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES=lab-stg-` (staging prefix, distinct from `lab-`)
6. Configure verifier SA / role / rolebinding names
7. Run precheck: `python scripts/labgen_controlled_k3s_adapter_smoke.py --env-file .env.home_lab`
8. Confirm all preconditions pass (K3S_SMOKE_BLOCKED with only "write not authorized" remaining)
9. Get operator authorization
10. Execute: `python scripts/labgen_controlled_k3s_adapter_smoke.py --env-file .env.home_lab --allow-k8s-write --json`
11. Confirm K3S_SMOKE_PASSED or K3S_SMOKE_PASSED_WITH_NOTES
12. Confirm cleanup_confirmed=true and no namespace residual
13. Update this document with the write phase result

---

## I. Code Status

| Component | Status | Commit |
|-----------|--------|--------|
| K3sNamespaceLifecycleAdapter | Fully implemented | 44cce73 |
| home_lab_mvp profile guardrails | 57 tests, PASS | 3bb58bc |
| Controlled K3s Adapter Smoke helper | Implemented + 57 tests | this commit |
| Namespace safety validator | Integrated | 44cce73 |
| Error sanitization | Integrated | 44cce73 |

No code blockers remain. Remaining blocker: **ops kubeconfig injection**.

---

## J. Portability Note

The K3sNamespaceLifecycleAdapter and this smoke script have no dependencies on:
- Proxmox or any specific VM provider
- T430 or any home-lab host
- Cloudflare Tunnel or any ingress
- kubectl CLI (uses kubernetes Python client directly)

When migrating to AWS EKS or Alibaba Cloud ACK:
- Change `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` to the managed cluster kubeconfig
- Change `LABGEN_RUNTIME_MODE=cloud` and `LABGEN_K8S_IN_CLUSTER=true` (if in-pod)
- Rerun this smoke against the cloud cluster — no code changes required

---

*This document records smoke state as of 2026-06-12. Update section G when write phase is executed.*
