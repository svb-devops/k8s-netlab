# LabGen Deployment Portability Strategy v0.1

## 1. Home-Lab MVP Reality

LabGen MVP is initially deployed on a single Dell T430 server running Proxmox at a home location in Santa Clara.

| Property | Value |
|----------|-------|
| Hardware | Dell T430, 20 threads (E5-2630L v4), 78 GB RAM |
| Hypervisor | Proxmox VE, single node |
| VM Provider | Proxmox linked clone (VMID 500–599, template 101) |
| Network | Cloudflare Tunnel → no exposed ports on home router |
| Kubernetes | K3s per-VM (one K3s cluster per student VM) |
| Registry | Local `registry:2` pull-through at 172.16.100.1:5000 |
| Secrets | `.env` file, local injection |
| Scale | Small-cohort customer testing only |

**Explicit non-goals for this phase:**
- Not HA — single physical server, single Proxmox node.
- CPU (1.8 GHz Xeon) is the concurrency bottleneck, not RAM.
- Cloudflare Tunnel is the ingress layer — not part of runtime core.
- Downtime from power outage or ISP disruption is accepted at this phase.
- Max concurrent lab sessions: recommend ≤ 5 to stay within CPU headroom.

## 2. Deployment Profiles

LabGen supports three deployment profiles controlled by `LABGEN_RUNTIME_MODE`:

### A. `dev` (also: `test`, `demo`)

- Stub namespace adapter allowed.
- No real K8s operations.
- No customer traffic.
- `LABGEN_NAMESPACE_ADAPTER=stub` is the default.

### B. `home_lab_mvp`

Current production profile for T430 deployment.

| Requirement | Value |
|-------------|-------|
| `LABGEN_NAMESPACE_ADAPTER` | `k8s` |
| `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Required (path to platform kubeconfig) |
| `LABGEN_K8S_IN_CLUSTER` | `false` (not running inside K8s) |
| Stub adapter | **Forbidden — fail closed** |
| HA | No |
| Cloudflare Tunnel | Ingress only — not referenced by runtime core |
| Proxmox | VM provider only — not referenced by namespace lifecycle core |

### C. `cloud`

Future profile for AWS EKS, Alibaba Cloud ACK, or any conformant managed K8s.

| Requirement | Value |
|-------------|-------|
| `LABGEN_NAMESPACE_ADAPTER` | `k8s` |
| Config | Either `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` OR `LABGEN_K8S_IN_CLUSTER=true` |
| Stub adapter | **Forbidden — fail closed** |
| HA | Supported (provider-managed) |
| VM provider | AWS EC2 / Alibaba ECS / managed node pool (swap Proxmox adapter) |
| Registry | ECR / Alibaba ACR / any OCI registry |
| Secrets | AWS Secrets Manager / Alibaba KMS / Vault |
| Ingress | ALB / NLB / SLB / API Gateway |

## 3. Portability Architecture — Anti-Lock-In Rules

These rules are enforced in code and verified by tests.

### LabGen Core (namespace lifecycle, session state machine, draft/publish, verifier)

| Rule | Status |
|------|--------|
| No Proxmox call in namespace lifecycle adapter | Enforced — `K3sNamespaceLifecycleAdapter` has no Proxmox imports |
| No T430 path in core | Enforced — no hardcoded server paths in any core module |
| No Cloudflare Tunnel logic in runtime core | Enforced — Tunnel is an infrastructure concern outside LabGen |
| No local registry assumption in draft/publish | Enforced — `image_whitelist.json` is config-driven |
| No hardcoded VMID range in LabGen core | Enforced — range comes from config |
| Namespace lifecycle via Kubernetes API only | Enforced — `K3sNamespaceLifecycleAdapter` uses `kubernetes-client/python` |
| No kubectl CLI dependency | Enforced — all K8s calls use Python client API |
| No `~/.kube/config` reads | Enforced — only reads `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` |

### Namespace Safety Boundary

All namespace names are validated before any K8s API call:
- Must match Kubernetes DNS label format.
- Must start with a configured allowed prefix (default: `lab-`).
- System namespaces (`default`, `kube-system`, `kube-public`, `kube-node-lease`) are blocked.
- Path characters, shell metacharacters, and whitespace are rejected.

### RoleBinding Permission Boundary

- RoleBinding is **namespace-scoped** — never ClusterRoleBinding.
- Subject: ServiceAccount in `kube-system` (configurable via `LABGEN_K8S_VERIFIER_SA_NAMESPACE`).
- RoleRef: ClusterRole (read-only verifier role).
- No cross-namespace permissions granted.

### Error Sanitization

Raw Kubernetes API response bodies are **never** exposed to:
- API responses returned to students or admins.
- Application audit logs.
- Frontend error messages.

Only `exc.status` (HTTP status code) and `exc.reason` (HTTP reason phrase) are used in log messages. `exc.body` is never accessed.

## 4. Migration Path

| Phase | Description | Trigger |
|-------|-------------|---------|
| **Now** | K3s adapter smoke (namespace lifecycle only) | `home_lab_mvp` profile; K3S_SMOKE_BLOCKED (ops kubeconfig pending); see `docs/labgen/CONTROLLED_K3S_ADAPTER_SMOKE_v0.1.md` |
| **Next** | K3s adapter smoke write phase | After kubeconfig injected; then controlled home-lab runtime session smoke |
| **Then** | Small customer pilot (home-lab) | ≤ 10 concurrent students, monitored |
| **Later** | Cloud deployment design | When T430 CPU becomes the bottleneck |
| **Later** | Cloud staging migration | New `cloud` profile, EKS/ACK kubeconfig or in-cluster |
| **Eventually** | Production cloud cutover | Proxmox adapter replaced with cloud VM provider |

## 5. Replaceable Adapters

Each infrastructure concern is isolated behind a port/adapter:

| Concern | Current Adapter | Future Replacement |
|---------|-----------------|--------------------|
| Namespace lifecycle | `K3sNamespaceLifecycleAdapter` (K8s API) | Same class — works on EKS/ACK |
| VM provider | Proxmox linked clone | AWS EC2 / ECS / managed node pool |
| Image registry | `registry:2` at `172.16.100.1:5000` | ECR / Alibaba ACR / GCR |
| Secrets | Local `.env` file | AWS Secrets Manager / Alibaba KMS / Vault |
| Ingress | Cloudflare Tunnel | ALB / NLB / API Gateway / SLB |

## 6. Config Keys (K8s Namespace Lifecycle)

All values are read from environment variables — no hardcoded defaults beyond sensible fallbacks.

| Variable | Purpose | Required In |
|----------|---------|-------------|
| `LABGEN_RUNTIME_MODE` | Deployment profile | All |
| `LABGEN_NAMESPACE_ADAPTER` | `stub` or `k8s` | All |
| `LABGEN_K8S_PLATFORM_KUBECONFIG_PATH` | Path to platform kubeconfig | `home_lab_mvp`, `production` |
| `LABGEN_K8S_IN_CLUSTER` | Use in-cluster config | `cloud` |
| `LABGEN_K8S_CONTEXT` | Optional kubeconfig context | Optional |
| `LABGEN_K8S_API_TIMEOUT_SECONDS` | K8s API timeout (default: 10) | Optional |
| `LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES` | Comma-separated prefix list (default: `lab-`) | Optional |
| `LABGEN_K8S_VERIFIER_SA_NAME` | Verifier ServiceAccount name | Optional |
| `LABGEN_K8S_VERIFIER_SA_NAMESPACE` | Verifier SA namespace | Optional |
| `LABGEN_K8S_VERIFIER_ROLE_NAME` | Verifier ClusterRole name | Optional |
| `LABGEN_K8S_VERIFIER_ROLEBINDING_NAME` | Verifier RoleBinding name | Optional |

## 7. What Has NOT Changed

- `namespace = f"lab-{session_id}"` naming convention is unchanged.
- LabDraft, PublishService, StaticValidator, StepProgressionService contracts unchanged.
- Verifier kubeconfig (per-VM) is distinct from platform kubeconfig (namespace management).
- Proxmox VM provisioning flow is unchanged.
- Cloudflare Tunnel configuration is unchanged.
