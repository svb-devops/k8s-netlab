# First Pilot Lab Release Result v0.1

**Final Decision**: PILOT_LAB_READY_WITH_NOTES

| Field | Value |
|-------|-------|
| Date | 2026-06-13 |
| Commit | (see git log after this file is committed) |
| Operator | Claude Code acting as senior dev+ops (both roles) |
| Runtime mode | home_lab_mvp (home_lab_mvp profile, K3s on VM 401) |
| Platform K3s | VM 401 — labgen-home-k3s-staging-01 |
| Proxmox pool | k8s-netlab-staging (isolated from production) |
| Production VMID 500-599 touched | NO |
| Production pool touched | NO |
| VM 101 template modified | NO |
| LLM called | NO |
| Customer traffic admitted | NO |

---

## Selected Pilot Lab

| Field | Value |
|-------|-------|
| Lab ID | `67fca5e4-2e8a-4c51-b62e-f3b8f6bd1fd6` |
| Title | Kubernetes Basics: Your Isolated Lab Environment |
| Source | `pilot:k8s-basics-namespace` |
| Steps | 1 |
| Verifiers | 1 (`namespace_exists`) |
| Images | none (image_resolution=[]) |
| Estimated duration | 10 min |
| Pollution level | namespace_only |
| External network dependency | none |

**Selection rationale**: Only `namespace_exists` verifier type is proven end-to-end
(Verifier Client Path Smoke v0.1, 2026-06-13, SMOKE PASSED). No images, no external
network, minimum resource footprint, maximum verifier confidence.

---

## Publish Gate Results

### Manual Review

Reviewed by: Claude Code (senior dev+ops role)
Reviewed at: 2026-06-13
Duration: ~300s

| Field | Decision | Note |
|-------|----------|------|
| title | APPROVE | Accurate scope: single namespace isolation step |
| steps[0].verify[0].type | APPROVE | namespace_exists proven in smoke |
| steps[0].explain | CONFIRM | admin_verified=true, published_to_student=true |
| cleanup | CONFIRM | delete_namespace only, no cluster-scoped resources |
| image_resolution | CONFIRM | empty — zero image risk |

### StaticValidator

Result: **14/14 PASSED**, 0 blocked

| Check | Result |
|-------|--------|
| image.no_latest_tag | PASSED |
| image.no_unknown_registry | PASSED |
| image.all_resolved | PASSED |
| image.all_exist_in_registry | PASSED |
| explain.verified_if_published | PASSED |
| namespace.no_hardcoded | PASSED |
| verify.no_shell_commands | PASSED |
| verify.no_secret_value | PASSED |
| cleanup.declared | PASSED |
| cluster_scoped.cleanup_declared | PASSED |
| helm.no_generation | PASSED |
| service.nodeport | PASSED |
| operator.crd | PASSED |
| pollution.known | PASSED |

### Image Readiness

Result: **PASS** — no images, zero image risk

### Publish Decision

Result: **publish_status=published** (PublishService.publish() returned PUBLISHED)

### Learner Catalog Visibility

Published labs in catalog: **1** (only the pilot lab)

Internal smoke lab (`e5b5aa73-09dd-42f5-90f4-b60f739b1c97`) status set to `draft`
before catalog check — it is NOT visible to students.

### Unpublished Lab Non-Leak Check

Smoke lab (`internal-verifier-client-smoke`) is `draft` and therefore excluded from
the learner catalog. A student calling the catalog API will see only the pilot lab.

---

## Internal Runtime Rehearsal

Rehearsal VM: 400 (staging, NOT production 500-599)
Rehearsal student: `rehearsal-pilot-admin`
K3s: VM 401 (labgen-home-k3s-staging-01)

| Step | Result | Detail |
|------|--------|--------|
| seed_draft | PASS | Pilot lab seeded to staging, publish_status=published |
| init_verifier | PASS | Verifier creds initialized for VM 400, generation=1 |
| build_services | PASS | K3sNamespaceLifecycleAdapter + K8sVerifierClientAdapter |
| create_session | PASS | LAB_ACTIVE, namespace=`lab-5da55ed4-581d-4d3c-bf87-14143d98bfb3` |
| namespace_exists | PASS | Namespace confirmed on K3s via platform kubeconfig |
| check_step | PASS | all_passed=True, ready_to_complete=True, verify_id=k8s-ns-v1 passed |
| session_snapshot | PASS | ready_to_complete=True in persisted session |
| complete_session | PASS | LAB_CLOSED, cleanup_verified=True, failure_reason=None |
| namespace_deleted | PASS | Namespace confirmed deleted from K3s |
| no_tainted_vm | PASS | failure_reason=None, no taint |
| residual_check | PASS | No namespace residual confirmed |

**Rehearsal decision**: PASSED — complete student flow verified end-to-end.

ns_delete parameters used (K3s async deletion):
- `ns_delete_max_retries=15`
- `ns_delete_poll_interval=2.0`

---

## Verifier Client Result

Verifier: `K8sVerifierClientAdapter` with verifier kubeconfig from `VerifierCredentialStore`
Verify type: `namespace_exists`
Result: passed=True, error_code=None

---

## Cleanup / Residual Check

| Check | Result |
|-------|--------|
| Namespace `lab-5da55ed4-*` deleted from K3s | CONFIRMED |
| Verifier creds `/var/lib/labgen-staging/verifier-credentials/400` removed | CONFIRMED |
| Staging lab session removed | CONFIRMED |
| Staging draft removed | CONFIRMED |
| No tainted VM | CONFIRMED |
| Production data untouched | CONFIRMED |
| VM 401 stopped after rehearsal | CONFIRMED |

---

## Accepted MVP Risks

| Risk | Mitigation | Status |
|------|-----------|--------|
| home_lab_mvp is non-HA (VM 401 single node) | Only used for internal pilot | Accepted |
| No production SLA | Pilot scope: 1-2 trusted users, no SLA | Accepted |
| Cloud portability not yet proven for pilot lab | home_lab_mvp profile only | Accepted |
| Pilot ready ≠ production ready | Explicitly documented, not claimed otherwise | Accepted |

---

## Rollback / Emergency Stop Plan

If anything goes wrong during the pilot:

1. Kill / stop the staging backend process (if running separately)
2. `qm stop 401` — stop staging K3s (prevents new namespace creation)
3. Stop VMID 400-499 only — never touch VMID 500-599 (production)
4. Disable new session creation: set `LABGEN_RUNTIME_MODE=dev` in .env and restart service
5. Archive / unpublish pilot lab:
   ```python
   # Run in venv
   from backend.labgen.repository import LabDraftRepository
   from backend.labgen.models import PublishStatus
   from pathlib import Path
   repo = LabDraftRepository(Path('data/lab_drafts.json'))
   draft = repo.get('67fca5e4-2e8a-4c51-b62e-f3b8f6bd1fd6')
   draft.publish_status = PublishStatus.DRAFT
   repo.update(draft)
   ```
6. Inspect audit events in `data-staging/lab_sessions.json`
7. Clean up namespaces manually if needed: `kubectl delete ns <namespace> --kubeconfig /etc/labgen/home_lab_mvp.kubeconfig`
8. Reclaim verifier credentials: `rm -rf /var/lib/labgen-staging/verifier-credentials/<vm_id>`
9. Preserve logs: `journalctl -u k8s-netlab --since "today" > /tmp/pilot-incident-logs.txt`
10. Never delete production resources (VMID 500-599, pool k8s-netlab, template VM 101)

---

## Notes

- This is the first real pilot lab release gate, not customer onboarding itself.
- Next step: First Pilot User Onboarding v0.1 (when a trusted user is identified).
- Pilot lab uses only `namespace_exists` verifier — the only type proven end-to-end.
- No kubectl access required from the student for this lab (observation-only step).
- This result supersedes the Verifier Client Path Smoke v0.1 notes about pilot readiness.

---

## Pilot Onboarding Doc

`docs/labgen/FIRST_PILOT_USER_ONBOARDING_v0.1.md`
