# Second Pilot Lab Design Gate v0.1 — Result

**Verdict: SECOND_PILOT_LAB_READY**
Date: 2026-06-14
Operator: Claude Code (claude-sonnet-4-6), acting as senior dev+ops
Lab: Kubernetes ConfigMap Basics: Store Your First Config
Lab ID: `b0b97742-80e4-4715-9a66-1fdd3009cfea`
Rehearsal user: pilot-user-04 (staging, internal rehearsal only)
Session ID: `ce08d629-8704-42bd-a61d-812be73c4024` (staging, not for external use)
Commit basis: `b26addf` (Third Trusted Pilot User Gate v0.1)

---

## A. Scope

This gate verifies that LabGen can extend from the first single-step pilot lab to a
second, more educationally-valuable multi-step verifier-enabled lab. It does not onboard
a new user, perform public launch, enable LLM, or raise concurrency.

Constraints held throughout:
- LLM calls: 0 (LABGEN_LLM_PROVIDER_MODE=fake_only)
- Production VMID 500-599: untouched
- Production pool/registry: unmodified
- Max active session: 1
- Max staging VMs: 1 (VM 401)
- QEMU-agent verifier init path: not used
- home_lab_mvp is NOT HA production

---

## B. Lab Selection

**Selected topic: Kubernetes ConfigMap Basics**

Rationale over alternatives:
- Aligns with K3s/verifier capability (configmap_exists is already in _SUPPORTED_TYPES)
- Does not require external networking, high CPU, or long-running processes
- Produces a learner-created artifact (ConfigMap my-app-config) that the verifier can
  confirm independently of how it was created
- No LLM required; no new verifier type code required
- Maintains cloud portability (K8s API is platform-agnostic)
- 2 meaningful steps with distinct learning objectives

---

## C. Lab Design

**Title**: Kubernetes ConfigMap Basics: Store Your First Config
**Lab ID**: `b0b97742-80e4-4715-9a66-1fdd3009cfea`
**Estimated duration**: 15 minutes
**Steps**: 2
**Pollution level**: namespace_only
**Shared namespace candidate**: false (creates named resource my-app-config)

### Step 1: 查看你的专属命名空间
- why: Namespace isolation is the foundation of multi-tenant Kubernetes
- do: Run `kubectl get namespaces` and `kubectl get namespace {{lab_namespace}}`
- verify: namespace_exists (verify_id=configmap-lab-v1)
- learner-created artifact: No (namespace auto-created by platform)

### Step 2: 创建你的第一个 ConfigMap
- why: ConfigMaps store non-sensitive config data that pods consume via env vars/volumes
- do: `kubectl create configmap my-app-config --from-literal=env=learning --from-literal=app=k8s-basics -n {{lab_namespace}}`
- verify: configmap_exists(name="my-app-config") (verify_id=configmap-lab-v2)
- learner-created artifact: Yes — my-app-config must exist for step to PASS

**Verifier improvement over first lab**:
- First lab: namespace_exists (platform-created, not learner-created)
- Second lab step 2: configmap_exists (learner-created artifact — stronger gate)

---

## D. Gate Checks

### D.1 Contract Validation
- source_article_id: pilot:k8s-configmap-basics
- 2 steps with clear why/do/commands/observe/explain structure
- Each step has a non-empty verify template
- No `verify: []` published step
- No destructive commands, no external network, no admin/internal endpoints
- explain.admin_verified=true, explain.published_to_student=true for both steps
- No LLM dependency

**Result: PASS**

### D.2 StaticValidator (14 checks)
All 14 checks passed:
- image.no_latest_tag: PASS
- image.no_unknown_registry: PASS
- image.all_resolved: PASS
- image.all_exist_in_registry: PASS
- explain.verified_if_published: PASS
- namespace.no_hardcoded: PASS
- verify.no_shell_commands: PASS
- verify.no_secret_value: PASS
- cleanup.declared: PASS
- cluster_scoped.cleanup_declared: PASS
- helm.no_generation: PASS
- service.nodeport: PASS
- operator.crd: PASS
- pollution.known: PASS

**Result: 14/14 PASS**

### D.3 Image Readiness
No images in this lab (namespace + configmap only — no container images).

**Result: PASS (no images to check)**

### D.4 Publish Decision
- status: ALLOWED
- is_publishable: true
- validation_status: passed
- issues: []

**Result: PASS — lab published**

### D.5 Learner Catalog Visibility
- Before publish: catalog shows 1 lab (first pilot lab only)
- After publish: catalog shows 2 labs (first + second)
- Internal smoke lab (e5b5aa73): 404 — not visible (correct)
- Unpublished drafts: not visible (correct)

**Result: PASS**

### D.6 Verifier Design
- configmap_exists already in _SUPPORTED_TYPES — no new code required
- ClusterRole lab-verifier-namespace-readonly includes configmaps in resources with get/list/watch verbs
- configmap_exists dispatches to read_namespaced_config_map(name, namespace) — namespace-scoped only
- No ClusterRoleBinding required
- No secret data accessed
- No new verifier type code — no additional tests required

**Result: PASS (no code changes)**

---

## E. VM Recovery

VM 401 was absent at gate start (config file missing — same pattern as Third Pilot Gate).
Runbook Section D.5 executed:
1. `qm clone 101 401 --full 1 --storage local-lvm --name labgen-home-k3s-staging-01` ✓
2. `pvesh set /pools/k8s-netlab-staging --vms 401` ✓
3. `qm set 401 --memory 4096` ✓
4. `qm start 401` ✓
5. hostname fixed → labgen-home-k3s-staging-01, etcd reset, K3s restarted ✓
6. Stale node `k8s-template` deleted ✓
7. `initialize_verifier_for_vm_host_side(vm_id=401, ...)` → success, gen=None ✓

**Runbook compliance: PASS**

---

## F. Frontend Rehearsal

Test method: Playwright headless Chromium via `playwright.async_api`
URL: https://lab.cloudnetops.tech
User: pilot-user-04 (staging internal rehearsal)

| Step | Action | Result |
|------|--------|--------|
| 1 | Login as pilot-user-04 at `/login.html` | PASS |
| 1 | Redirect to `/app` after login | PASS |
| 2 | Navigate to `/labgen-catalog.html` | PASS |
| 2 | Catalog renders (JS module, CSP compliant) | PASS |
| 2 | First lab visible in catalog | PASS |
| 2 | Second lab (ConfigMap Basics) visible | PASS |
| 2 | Internal smoke lab not visible | PASS |
| 2 | No sensitive data in catalog | PASS |
| 3 | Lab detail page loaded | PASS |
| 3 | Lab title contains 'ConfigMap' | PASS |
| 3 | Step content visible | PASS |
| 3 | Start button present | PASS |
| 4 | Start lab session → 201 created | PASS |
| 4 | Session status LAB_ACTIVE | PASS |
| 4 | Namespace assigned | PASS |
| 4 | Session page `/labgen-session.html` loaded | PASS |
| 4 | No sensitive data on session page | PASS |
| 5 | Step 1 check → 200 | PASS |
| 5 | Step 1 all_passed=True (namespace_exists) | PASS |
| 5 | Step 1 advanced to step 2 | PASS |
| 6 | ConfigMap my-app-config created in namespace | PASS |
| 7 | Step 2 check → 200 | PASS |
| 7 | Step 2 all_passed=True (configmap_exists) | PASS |
| 7 | Step 2 verify_results non-empty | PASS |
| 7 | ready_to_complete=True | PASS |
| 7 | verify configmap-lab-v2 type=configmap_exists | PASS |
| 8 | Complete session → 200 | PASS |
| 8 | Session status LAB_CLOSED | PASS |
| 8 | cleanup_verified=True | PASS |
| 9 | No lab-* namespace residual | PASS |
| 9 | No tainted VMs | PASS |

**Frontend flow: 31/31 PASS**
LLM calls: 0
JS errors: 0 (observed)
Residuals: All clean

---

## G. Post-Rehearsal State

- VM 401: RUNNING, K3s Ready, node labgen-home-k3s-staging-01
- Active sessions: 0
- Lab namespaces: 0
- Tainted VMs: {}
- Verifier credentials: /var/lib/labgen-staging/verifier-credentials/401/ (kubeconfig present)
- First pilot lab: published (lab_id=67fca5e4)
- Second pilot lab: published (lab_id=b0b97742)
- Catalog: 2 published labs visible to authenticated users
- Internal smoke lab: unpublished (not in catalog)

---

## H. Runbook Compliance Check

| Rule | Status |
|------|--------|
| Used `initialize_verifier_for_vm_host_side` | PASS |
| Used platform kubeconfig | PASS |
| QEMU-agent verifier init path NOT used | PASS |
| K3s control plane healthy (VM 401) | PASS |
| Staging VMID range 400-499 only | PASS |
| Production VMID 500-599 untouched | PASS |
| No active session before rehearsal | PASS |
| No namespace residual before/after | PASS |
| No verifier credential residual | PASS |
| No tainted VM | PASS |
| Max active session = 1 | PASS |
| LLM disabled | PASS |
| home_lab_mvp not described as HA/production | PASS |

**Runbook compliance: 13/13 PASS**

---

## I. Technical Blocker Self-Check

- No TODO / FIXME introduced: ✓
- No placeholder-as-success: ✓
- No hardcoded credentials: ✓
- No kubeconfig content in repo/docs/logs: ✓
- No token/password/cert/private key leaked: ✓
- No verifier credential leaked: ✓
- No raw K8s exception body leaked: ✓
- No frontend raw stack trace leaked: ✓
- No admin/internal endpoint leakage: ✓
- No unpublished lab leakage: ✓
- No customer-visible internal smoke lab: ✓
- No namespace residual: ✓
- No RoleBinding residual: ✓
- No verifier credential residual: ✓
- No unmanaged VM residual: ✓
- No tainted VM: ✓
- Production VM/pool/registry unmodified: ✓
- LLM calls: 0 ✓
- QEMU-agent verifier init path not used: ✓
- No runbook drift: ✓
- No premature public launch: ✓
- No premature HA production claim: ✓
- No untested new scripts: ✓
- Cloud portability maintained: ✓

---

## J. Recommendation

**SECOND_PILOT_LAB_READY**

The second pilot lab (Kubernetes ConfigMap Basics) has:
- Passed all 14 StaticValidator checks
- Passed publish decision gate
- Appeared correctly in learner catalog
- Completed a full frontend rehearsal: 31/31 PASS
- Demonstrated multi-step flow with learner-created artifact verification
- Achieved LAB_CLOSED with cleanup_verified=True and zero residuals

**Recommendation**: Allow a fourth trusted user (pilot-user-04 or a new account) to
test the second lab under the same constraints (max 1 concurrent session, LLM disabled,
staging VMID 400-499 only). Do not open to public traffic yet.

**Next gate**: Fourth Trusted Pilot User on Second Lab v0.1

---

## K. Notes

1. **VM 401 absent at gate start**: Same pattern as Third Pilot Gate. The D.5 rebuild is
   reliable and fast (~5 minutes). Runbook is accurate and sufficient.

2. **pilot-user-04 created for rehearsal**: This account exists in data/users.json as a
   staging-only account for internal rehearsal. It can be used as the fourth trusted pilot
   user, or a separate account can be created for the actual onboarding.

3. **ConfigMap creation in rehearsal**: Step 2 creates my-app-config via Python kubernetes
   client (simulating kubectl). In a real learner session, the learner uses the SSH terminal.
   The verifier checks the K8s API regardless of creation method, so the verification path
   is identical.

4. **No new verifier code**: configmap_exists was already implemented and tested. This gate
   exercised an existing code path for the first time in a live rehearsal.
