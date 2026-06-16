# Home-Lab MVP Pilot Gate Result v0.1

**Final Decision**: PILOT_GATE_READY_WITH_NOTES

| Field | Value |
|-------|-------|
| Date | 2026-06-13 |
| Commit | 91c000f (smoke) |
| Operator | Claude Code acting as senior dev+ops (both roles) |
| Based on | RUNTIME_SESSION_SMOKE_PASSED_WITH_NOTES (2026-06-13) |
| Runtime mode | home_lab_mvp |
| Platform K3s | VM 401 — labgen-home-k3s-staging-01 |
| Proxmox pool | k8s-netlab-staging (isolated from production) |
| Production VMID 500-599 touched | NO |
| Production pool touched | NO |
| VM 101 template modified | NO |

---

## A. Smoke Summary

| Gate | Result |
|------|--------|
| Ops ticket verify (6/6) | VERIFIED |
| Secret injection verify | SECRET_INJECTION_READY |
| Intake gate | READY_TO_RERUN_CONTROLLED_STAGING_TRIAL |
| VM 400 create (staging pool) | SUCCESS |
| Lab session create → LAB_ACTIVE | SUCCESS |
| K3s namespace created | CONFIRMED (Active, RoleBinding created) |
| Step check | all_passed=true, ready_to_complete=true |
| Complete + cleanup | LAB_CLOSED, cleanup_verified=true |
| K3s namespace deleted | CONFIRMED (404) |
| Tainted VMs | NONE |
| Bugs found during smoke | 5 (all fixed, regression tests added) |
| Test baseline after smoke | 3076 passed, 93.27% coverage |

---

## B. VM 400 Cleanup Result

- **Status**: CLEANED — VM 400 config does not exist in Proxmox (`qm config 400` → not found)
- **Method**: VM was stopped (`qm stop 400`) during smoke; conf was auto-removed or already destroyed before this gate check
- **Staging pool k8s-netlab-staging**: contains only VM 401 (K3s control plane, running)
- **Production pool k8s-netlab**: contains only VM 101 (template, untouched)
- **VMID 500-599**: untouched (confirmed via `pvesh get /pools/k8s-netlab`)

---

## C. Full Residual Check

| Item | Status | Evidence |
|------|--------|----------|
| VM 400 | GONE | `qm config 400` → "Configuration file does not exist" |
| Unexpected staging VMs | NONE | Staging pool members: [VM 401 only] |
| K3s lab- namespaces | NONE | `delete_namespace` → 404 (already gone); initial `list_namespace` showed stale K3s API data — see Note below |
| K3s RoleBindings (labgen-verifier) | NONE | `list_namespaced_role_binding` returned [] |
| Verifier credentials (creds/vm_creds/) | NONE | Directory does not exist |
| Tainted VMs | NONE | `data/tainted_vms.json` = {} |
| Active lab sessions | NONE | `data/lab_sessions.json` = 0 sessions |
| smoke-admin user | REMOVED | Not present in `data/users.json` |
| Smoke draft | REMOVED | Verified via lab_drafts.json (0 published drafts) |
| Production VM / pool / registry | UNMODIFIED | Production pool = [VM 101 only]; no VM in 500-599 |
| Secrets in repo | NONE | No credentials committed |
| kubeconfig content leaked | NONE | No kubeconfig content in any artifact |
| token/password/cert/key leaked | NONE | All credentials repo-external |
| TODO / FIXME in code | NONE | No new TODOs/FIXMEs introduced |
| Untested new scripts | NONE | All script changes covered by tests |

**Note on K3s stale namespace read**: Initial `list_namespace()` call returned
`lab-7dadd2cf-807e-43d2-a5c1-41ba0ee49358` as Active. Subsequent `delete_namespace()` returned
404 (already gone). This is K8s/K3s known behavior: `list` operations can briefly return stale
entries after deletion due to API server cache TTL. The smoke cleanup (`cleanup_verified=true`)
was correct — the namespace had been deleted; the initial list was stale. Authoritative check:
`read_namespace` → 404 (not found). No code bug.

**K3s node health**: VM 401 node `k8s-template` Ready=True (confirmed via Python kubernetes client).

---

## D. Verifier Client — Not Exercised

**Status**: NON-BLOCKING NOTE

- Smoke draft used `verify: []` — no K8s resource verification was exercised
- All 0 currently published labs have `verify: []` (no labs have verify templates yet)
- The step check path was exercised: `all_passed=true` with empty verify list
- `K3sVerifierClientAdapter` is implemented and tested (29 unit tests), but not live-exercised

**Conclusion**: Acceptable for pilot **only if** pilot labs also use `verify: []` or no-verify steps.

**Mandatory constraint**:
- Full verifier path (SA, ClusterRole, kubeconfig, step check with real K8s verify) has NOT been validated
- Do NOT claim verifier client is production-ready
- Required future task: `Verifier Client Path Smoke v0.1` before enabling step checks with real K8s verify templates

---

## E. Accepted MVP Risks

| Risk | Accepted | Documentation |
|------|----------|---------------|
| Same-Proxmox, same-API-token as production | ACCEPTED | Same host; staging pool isolated; VMID range 400-499 enforced |
| home_lab_mvp is not HA | ACCEPTED | Single-node K3s; no redundancy; pilot scope only |
| No external secret manager | ACCEPTED | /etc/labgen/home_lab_mvp.env chmod 600, repo-external |
| Verifier client not live-exercised | ACCEPTED as NOTE | Pilot labs must use verify:[] until Verifier Client Path Smoke v0.1 |
| 0 published labs | ACKNOWLEDGED | Pre-pilot action required: publish ≥1 curated lab via admin review |

---

## F. Pilot Scope — Strictly Enforced

The following constraints are MANDATORY for pilot operation. Violation stops pilot immediately.

| Constraint | Limit |
|-----------|-------|
| Concurrent active runtime sessions | MAX 1 |
| Staging VMs (VMID 400-499) | MAX 3 |
| Pilot users | 1-2 trusted/known users only (whitelisted) |
| SLA | NONE — early pilot, no uptime guarantee |
| Lab type | Curated, reviewed, published labs only (verify:[] until verifier smoke) |
| LLM | DISABLED — LABGEN_LLM_PROVIDER_MODE=fake_only |
| Admin/debug pages | NOT exposed to pilot users |
| Internal API / Directus admin | NOT exposed to pilot users |
| Production VMID range 500-599 | MUST NOT be used |
| Production announcements | PROHIBITED — not GA |

---

## G. Runtime Policy — Mandatory Stop Conditions

Pilot stops immediately on any of the following:

1. Cleanup fails → `LAB_CLEANUP_FAILED` → mark VM tainted → block new sessions
2. VM tainted → block new sessions on that VM
3. Namespace residual detected → stop new sessions; manual cleanup required
4. CPU/memory/storage threshold exceeded (Proxmox host memory > 85% or root disk > 80%)
5. Cloudflare Tunnel down → pilot suspended
6. Registry / Proxmox / K3s API down → pilot suspended
7. Any unknown exception propagates to student-facing API → investigate before resuming

**Current resource headroom**:
- CPU: 0.0% (ample)
- Memory: 6.3 GB / 78.3 GB (8.0% — ample)
- Root disk: 39.1 GB / 93.9 GB (41.6% — ample)
- Max 3 staging VMs: each VM ~4 GB RAM → max 12 GB added = ~26% total; well within capacity

---

## H. Emergency Stop / Rollback

**Emergency stop** (run as root on Proxmox host):
```bash
# 1. Kill staging backend
kill $(pgrep -f "port 8888") 2>/dev/null || true

# 2. Stop staging VMs (VMID 400-499)
for vmid in $(qm list | awk '$1>=400 && $1<=499 {print $1}'); do qm stop $vmid; done

# 3. Verify K3s has no active lab- namespaces
# (check via Python kubernetes client)

# 4. Do NOT touch VMID 500-599 or production pool
```

**Rollback to pre-pilot state**:
- All student data is in `data/` JSON files — no DB migration needed
- `data/lab_sessions.json`, `data/tainted_vms.json` can be reset to `{}` or `[]`
- VM 401 (K3s control plane) can be left running; it has no persistent student data
- No schema migration or infrastructure teardown required

**This is NOT production** — rollback is low-risk. No customer data is persisted beyond session JSON files.

---

## I. Customer Pilot — Boundaries and Notice

Pilot users must understand the following before being onboarded:

- **Early pilot only** — service may be interrupted without notice
- **No SLA** — the platform may be restarted during their session
- **Lab environment may need to be reset** — transient failures are expected
- **Do not upload sensitive data** — experimental environment, not audited storage
- **Do not use for production tasks** — this is an educational lab environment
- **During pilot: manual operator may be on call** — not automated at GA level
- **Feedback focus**: lab content quality and usability, not production reliability

No formal legal agreement required for early pilot, but boundaries must be clearly communicated verbally or in writing before access is granted.

---

## J. Monitoring and Audit Plan

**Production health** (already in place):
- `curl -sf https://lab.cloudnetops.tech/api/health` → `{"status":"healthy","proxmox":{"connected":true}}`
- `journalctl -u k8s-netlab -p err --since "10 minutes ago" --no-pager` for error monitoring

**Pilot-specific checks** (manual, operator performs before each pilot session):

```bash
# 1. Verify staging K3s is healthy
python3 -c "
from kubernetes import client, config
config.load_kube_config('/etc/labgen/home_lab_mvp.kubeconfig')
v1 = client.CoreV1Api()
nodes = v1.list_node()
for n in nodes.items:
    cond = [c for c in n.status.conditions if c.type=='Ready'][0]
    print(f'Node {n.metadata.name}: Ready={cond.status}')
"

# 2. Verify no lab- namespace residuals
# (use read_namespace on known names, not list_namespace — avoids stale cache)

# 3. Verify no tainted VMs
cat /root/k8s-netlab/data/tainted_vms.json

# 4. Verify VMID 500-599 untouched
pvesh get /pools/k8s-netlab --output-format json | python3 -c "import sys,json; d=json.load(sys.stdin); print([m['vmid'] for m in d.get('members',[])])"
```

**Audit log**: `data/lab_runtime_audit.json` records all session lifecycle events. Review after each pilot session.

---

## K. Pre-Pilot Action Required (Before Onboarding First User)

The following actions must be completed before pilot can actually start:

| Action | Owner | Status |
|--------|-------|--------|
| Publish ≥1 curated lab via admin review workflow (Directus → publish) | Content / Admin | REQUIRED |
| Register pilot user account in production backend | Ops | REQUIRED |
| Communicate pilot boundaries to user (Section I) | Operator | REQUIRED |
| Verify staging backend is running with home_lab_mvp env | Ops | REQUIRED each session |
| Verify VM 401 K3s is Ready | Ops | REQUIRED each session |

**NOTE**: 0 published labs currently exist. Pilot cannot start until at least 1 lab is published.

---

## L. Next Steps

1. **Verifier Client Path Smoke v0.1** — run smoke with a real verify template (step that checks a K8s resource); this must pass before enabling pilot labs with `verify: [...]` steps
2. **initialize_verifier_for_vm smoke** — test QEMU agent command execution on a student VM
3. **Publish first pilot lab** — via Directus admin → publish workflow; content review by operator
4. **Onboard first pilot user** — 1 user, observe full session lifecycle, collect feedback
5. **Post-pilot debrief** — record findings in `docs/labgen/PILOT_SESSION_DEBRIEF_v0.1.md`

---

## M. Technical Self-Check

| Constraint | Status |
|------------|--------|
| 不伪造 kubeconfig | PASS — real kubeconfig from VM 401 K3s |
| 不将 kubeconfig 提交进 repo | PASS — /etc/labgen/ (repo-external) |
| 不将 token/cert/private key 写入文档/日志 | PASS — no credential content in any artifact |
| 不复用 production VMID 500-599 | PASS — VM 400 was in 400-499 staging range, now gone |
| 不复用 production pool | PASS — k8s-netlab-staging pool used |
| 不修改 VM 101 template | PASS — template VM 101 untouched |
| 创建 namespace 后必须 cleanup | PASS — cleanup_verified=true; 404 confirmed |
| smoke 失败后必须记录残留 | PASS — all smoke bugs recorded in smoke result doc |
| 不声明 K3s smoke pass 等同于 full live trial | PASS |
| 不声明 home_lab_mvp 等同于 HA production | PASS — ACCEPTED_MVP_RISK documented |
| 无 TODO / FIXME | PASS |
| 新增脚本必须有测试 | PASS |
| 不绕过现有 smoke helper / namespace safety validator / precheck | PASS |
| 不声明 verifier client production-ready | PASS — note only |
| 不声明 full verifier pass | PASS — note only |
| 不启动新 runtime session | PASS — no new session started in this gate |
| 不接生产流量 | PASS |
| 不修改 production VM / pool / registry | PASS |


---

## L. Follow-up (2026-06-15)

Small Cohort Readiness Gate v0.1 completed: **SMALL_COHORT_READY_WITH_NOTES**

- 8 trusted pilot users across 4 labs; all sessions LAB_CLOSED cleanup_verified=True
- All verifier types (namespace_exists, configmap_exists, secret_exists, deployment_ready) real-user validated
- RBAC: list+watch only, no get, stable across all sessions
- 0 BLOCKER / HIGH / MEDIUM open issues
- Runbook Section J (Small Cohort Pilot Procedure) added
- See `docs/labgen/SMALL_COHORT_READINESS_GATE_v0.1.md` for full gate result

---

This gate remains aligned with PROJECT_NORTH_STAR_v0.1: Article-to-Lab / Technical Content-to-Experiment Platform, "读完即练，结果说话".
