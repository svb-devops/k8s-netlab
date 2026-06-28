#!/usr/bin/env python3
"""
Verifier Client Path Smoke v0.1 — end-to-end integration against real K3s (VM 401).

What this validates:
  - PlatformVerifierInitializer can create verifier credentials from platform kubeconfig
  - K3sNamespaceLifecycleAdapter creates/deletes namespaces on real K3s
  - K8sVerifierClientAdapter reads namespace existence via verifier kubeconfig
  - StepProgressionService routes check_step → VerifierService → K8sVerifierClientAdapter
  - LabSessionService create/complete lifecycle works end-to-end

Usage:
    python scripts/labgen_verifier_client_path_smoke.py [--no-cleanup]

Requires:
    - /etc/labgen/home_lab_mvp.kubeconfig (chmod 600, VM 401 K3s)
    - VM 401 running (qm status 401 | grep running)
    - data-staging/ directory exists

Not required (uses StubVMTracker):
    - Real Proxmox VM at id=400
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load env in production order: .env → home_lab_mvp.env (override)
from backend.labgen.ops_env import load_ops_env
load_ops_env()

from backend.labgen.image_resolver import ImageResolver
from backend.labgen.k8s_verifier_client import K8sVerifierClientAdapter, KubernetesApiFactory
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.lab_session_service import LabSessionService, StubVMTracker
from backend.labgen.models import LabDraft, LabSessionStatus
from backend.labgen.namespace_lifecycle import K3sNamespaceLifecycleAdapter, K8sAdapterConfig
from backend.labgen.repository import LabDraftRepository
from backend.labgen.step_progression_service import StepProgressionService
from backend.labgen.verifier import VerifierService, K8sVerifierClientPort
from backend.labgen.verifier_credentials import VerifierCredentialStore
from backend.storage_utils import safe_update_json
from backend.vm_manager import initialize_verifier_for_vm_host_side

SMOKE_LAB_ID = "e5b5aa73-09dd-42f5-90f4-b60f739b1c97"
SMOKE_VM_ID = "400"
SMOKE_STUDENT = "smoke-admin"
STEP_ID = "step-verify-namespace"
PLATFORM_KUBECONFIG_PATH = "/etc/labgen/home_lab_mvp.kubeconfig"
STAGING_CRED_ROOT = "/var/lib/labgen-staging/verifier-credentials"
STAGING_DATA_DIR = Path("data-staging")
PRODUCTION_DRAFTS = Path("data/lab_drafts.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("smoke.verifier_client_path")


@dataclass
class SmokeResult:
    passed: bool
    steps: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def preflight(
    kubeconfig_path: str = PLATFORM_KUBECONFIG_PATH,
    staging_data_dir: Path = STAGING_DATA_DIR,
) -> dict[str, Any]:
    """Verify prerequisites without making any K8s API calls."""
    issues: list[str] = []

    kc = Path(kubeconfig_path)
    if not kc.exists():
        issues.append(f"kubeconfig missing: {kubeconfig_path}")
    elif kc.stat().st_size == 0:
        issues.append(f"kubeconfig is empty: {kubeconfig_path}")
    else:
        try:
            import yaml
            cfg = yaml.safe_load(kc.read_text())
            server = cfg["clusters"][0]["cluster"]["server"]
            logger.info("Platform kubeconfig server=%s...", server[:40])
        except Exception as exc:
            issues.append(f"kubeconfig parse failed: {exc}")

    if not staging_data_dir.exists():
        issues.append(f"staging data dir missing: {staging_data_dir}")

    if not PRODUCTION_DRAFTS.exists():
        issues.append(f"production drafts missing: {PRODUCTION_DRAFTS}")

    return {"ok": len(issues) == 0, "issues": issues}


# ---------------------------------------------------------------------------
# Seed smoke draft
# ---------------------------------------------------------------------------


def seed_smoke_draft(draft_repo: LabDraftRepository, source_drafts_path: Path) -> LabDraft:
    """Copy the smoke draft from production data into the staging repository."""
    raw = json.loads(source_drafts_path.read_text())
    if SMOKE_LAB_ID not in raw:
        raise RuntimeError(f"Smoke lab draft {SMOKE_LAB_ID} not found in {source_drafts_path}")
    draft = LabDraft.model_validate(raw[SMOKE_LAB_ID])
    existing = draft_repo.get(SMOKE_LAB_ID)
    if existing is None:
        draft_repo.create(draft)
    else:
        draft_repo.update(draft)
    logger.info("Smoke draft seeded: lab_id=%s", SMOKE_LAB_ID)
    return draft


# ---------------------------------------------------------------------------
# Init verifier credentials
# ---------------------------------------------------------------------------


def init_verifier_creds(
    vm_id: int,
    kubeconfig_path: str,
    staging_store: VerifierCredentialStore,
    _factory: Any = None,
) -> dict[str, Any]:
    """Create verifier SA/ClusterRole/token on K3s and store credentials."""
    result = initialize_verifier_for_vm_host_side(
        vm_id,
        kubeconfig_path,
        store=staging_store,
        _factory=_factory,
    )
    return result


# ---------------------------------------------------------------------------
# Build service graph
# ---------------------------------------------------------------------------


def build_services(
    staging_data_dir: Path,
    staging_store: VerifierCredentialStore,
    kubeconfig_path: str,
    ns_lifecycle: Any = None,
    verifier_client_factory: Optional[Callable[[str], K8sVerifierClientPort]] = None,
) -> dict[str, Any]:
    """Construct LabSessionService + StepProgressionService wired to real K3s."""
    draft_repo = LabDraftRepository(staging_data_dir / "lab_drafts.json")
    session_repo = LabSessionRepository(staging_data_dir / "lab_sessions.json")
    vm_tracker = StubVMTracker()
    image_resolver = ImageResolver()

    if ns_lifecycle is None:
        k8s_cfg = K8sAdapterConfig(kubeconfig_path=kubeconfig_path)
        ns_lifecycle = K3sNamespaceLifecycleAdapter(k8s_cfg)

    if verifier_client_factory is None:
        _kube_factory = KubernetesApiFactory()

        def verifier_client_factory(kubeconfig_content: str) -> K8sVerifierClientPort:
            return K8sVerifierClientAdapter(kubeconfig_content, _kube_factory)

    session_svc = LabSessionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        vm_tracker=vm_tracker,
        ns_lifecycle=ns_lifecycle,
        image_resolver=image_resolver,
        ns_delete_poll_interval=2.0,   # K3s async deletion can take 10-20s
        ns_delete_max_retries=15,      # up to 30s total wait
    )

    verifier_svc = VerifierService(
        session_repo=session_repo,
        credential_store=staging_store,
        k8s_client_factory=verifier_client_factory,
    )

    step_svc = StepProgressionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        verifier_svc=verifier_svc,
    )

    return {
        "draft_repo": draft_repo,
        "session_repo": session_repo,
        "session_svc": session_svc,
        "verifier_svc": verifier_svc,
        "step_svc": step_svc,
        "ns_lifecycle": ns_lifecycle,
    }


# ---------------------------------------------------------------------------
# Smoke flow
# ---------------------------------------------------------------------------


def run_smoke(
    services: dict[str, Any],
    lab_id: str = SMOKE_LAB_ID,
    vm_id: str = SMOKE_VM_ID,
    student_username: str = SMOKE_STUDENT,
    step_id: str = STEP_ID,
) -> SmokeResult:
    """Execute create-session → check-step → complete-session and collect results."""
    steps: dict[str, Any] = {}
    session_svc: LabSessionService = services["session_svc"]
    step_svc: StepProgressionService = services["step_svc"]
    ns_lifecycle = services["ns_lifecycle"]

    # 1. Create session
    try:
        session = session_svc.create_session(lab_id, vm_id, student_username)
        active = session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        steps["create_session"] = {
            "ok": active,
            "session_id": session.session_id,
            "namespace": session.namespace,
            "status": session.lab_session_status.value,
            "failure_reason": session.failure_reason,
        }
        logger.info(
            "create_session: status=%s namespace=%s",
            session.lab_session_status.value,
            session.namespace,
        )
        if not active:
            return SmokeResult(
                passed=False,
                steps=steps,
                error=f"session not active: status={session.lab_session_status.value} reason={session.failure_reason}",
            )
    except Exception as exc:
        steps["create_session"] = {"ok": False, "error": str(exc)}
        return SmokeResult(passed=False, steps=steps, error=f"create_session raised: {exc}")

    session_id = session.session_id
    namespace = session.namespace

    # Brief pause for K3s namespace propagation
    time.sleep(1)

    # 2. Confirm namespace exists on K3s
    try:
        ns_exists = ns_lifecycle.namespace_exists(namespace)
        steps["namespace_exists"] = {"ok": ns_exists, "namespace": namespace}
        logger.info("namespace_exists: %s → %s", namespace, ns_exists)
        if not ns_exists:
            return SmokeResult(
                passed=False,
                steps=steps,
                error=f"namespace {namespace} not found on K3s after create",
            )
    except Exception as exc:
        steps["namespace_exists"] = {"ok": False, "error": str(exc)}
        return SmokeResult(passed=False, steps=steps, error=f"namespace_exists raised: {exc}")

    # 3. Check step via verifier client
    try:
        check_resp = step_svc.check_step(session_id, step_id, student_username)
        all_passed = check_resp.all_passed
        steps["check_step"] = {
            "ok": all_passed,
            "advanced": check_resp.advanced,
            "ready_to_complete": check_resp.ready_to_complete,
            "results": [
                {
                    "verify_id": r.verify_id,
                    "passed": r.passed,
                    "error_code": r.error_code,
                }
                for r in check_resp.verify_results
            ],
        }
        logger.info(
            "check_step: all_passed=%s advanced=%s ready=%s",
            all_passed,
            check_resp.advanced,
            check_resp.ready_to_complete,
        )
        if not all_passed:
            return SmokeResult(
                passed=False,
                steps=steps,
                error=f"step check failed: {steps['check_step']['results']}",
            )
    except Exception as exc:
        steps["check_step"] = {"ok": False, "error": str(exc)}
        return SmokeResult(passed=False, steps=steps, error=f"check_step raised: {exc}")

    # 4. Complete session
    try:
        completed = session_svc.complete_session(session_id)
        cleanup_ok = completed.cleanup_verified
        steps["complete_session"] = {
            "ok": cleanup_ok,
            "status": completed.lab_session_status.value,
            "cleanup_verified": completed.cleanup_verified,
            "failure_reason": completed.failure_reason,
        }
        logger.info(
            "complete_session: status=%s cleanup_verified=%s",
            completed.lab_session_status.value,
            completed.cleanup_verified,
        )
        if not cleanup_ok:
            return SmokeResult(
                passed=False,
                steps=steps,
                error=f"cleanup not verified: reason={completed.failure_reason}",
            )
    except Exception as exc:
        steps["complete_session"] = {"ok": False, "error": str(exc)}
        return SmokeResult(passed=False, steps=steps, error=f"complete_session raised: {exc}")

    # Brief pause for K3s namespace deletion propagation
    time.sleep(2)

    # 5. Confirm namespace is gone
    try:
        ns_gone = not ns_lifecycle.namespace_exists(namespace)
        steps["namespace_deleted"] = {"ok": ns_gone, "namespace": namespace}
        logger.info("namespace_deleted: %s → %s", namespace, ns_gone)
    except Exception as exc:
        # Non-fatal: cleanup_verified already confirmed the delete was initiated
        steps["namespace_deleted"] = {"ok": False, "error": str(exc), "non_fatal": True}
        logger.warning("namespace_deleted check raised (non-fatal): %s", exc)

    return SmokeResult(passed=True, steps=steps)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_staging(
    session_id: Optional[str],
    staging_data_dir: Path,
    staging_store: VerifierCredentialStore,
    vm_id: int,
) -> None:
    """Remove staging artifacts created by this smoke run."""
    cred_dir = staging_store._base / str(vm_id)
    if cred_dir.exists():
        shutil.rmtree(cred_dir)
        logger.info("Removed staging verifier creds: %s", cred_dir)

    if session_id is not None:
        try:
            def _remove_session(data: dict) -> dict:
                data.pop(session_id, None)
                return data
            safe_update_json(staging_data_dir / "lab_sessions.json", _remove_session)
            logger.info("Removed staging session: %s", session_id)
        except Exception as exc:
            logger.warning("Failed to remove session %s: %s", session_id, exc)

    try:
        def _remove_draft(data: dict) -> dict:
            data.pop(SMOKE_LAB_ID, None)
            return data
        safe_update_json(staging_data_dir / "lab_drafts.json", _remove_draft)
        logger.info("Removed smoke draft from staging")
    except Exception as exc:
        logger.warning("Failed to remove smoke draft: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifier Client Path Smoke v0.1")
    parser.add_argument("--kubeconfig", default=PLATFORM_KUBECONFIG_PATH)
    parser.add_argument("--staging-data", default=str(STAGING_DATA_DIR), type=Path)
    parser.add_argument("--staging-creds", default=STAGING_CRED_ROOT)
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Skip cleanup (keep staging creds and session for debugging)",
    )
    args = parser.parse_args()

    logger.info("=== Verifier Client Path Smoke v0.1 ===")

    # 1. Preflight
    pf = preflight(args.kubeconfig, args.staging_data)
    if not pf["ok"]:
        for issue in pf["issues"]:
            logger.error("Preflight FAIL: %s", issue)
        return 1
    logger.info("Preflight OK")

    staging_store = VerifierCredentialStore(args.staging_creds)

    # 2. Init verifier credentials (real K3s API call)
    logger.info("Initializing verifier credentials for VM %s...", SMOKE_VM_ID)
    cred_result = init_verifier_creds(int(SMOKE_VM_ID), args.kubeconfig, staging_store)
    if not cred_result["success"]:
        logger.error("Verifier init FAIL: %s", cred_result["error"])
        return 1
    gen = cred_result["data"]["credential_generation"]
    logger.info("Verifier creds initialized: generation=%d", gen)

    # 3. Seed smoke draft
    draft_repo = LabDraftRepository(args.staging_data / "lab_drafts.json")
    seed_smoke_draft(draft_repo, PRODUCTION_DRAFTS)

    # 4. Build service graph
    services = build_services(args.staging_data, staging_store, args.kubeconfig)

    # 5. Run smoke
    logger.info("Running smoke flow...")
    result = run_smoke(services)

    session_id: Optional[str] = None
    cs = result.steps.get("create_session", {})
    if "session_id" in cs:
        session_id = cs["session_id"]

    # 6. Cleanup
    if not args.no_cleanup:
        logger.info("Cleaning up staging artifacts...")
        cleanup_staging(session_id, args.staging_data, staging_store, int(SMOKE_VM_ID))

    # 7. Report
    logger.info("=== SMOKE RESULT ===")
    for step_name, step_data in result.steps.items():
        status = "PASS" if step_data.get("ok") else "FAIL"
        detail = {k: v for k, v in step_data.items() if k != "ok"}
        logger.info("  %-25s %s  %s", step_name, status, json.dumps(detail))

    if result.passed:
        logger.info("SMOKE PASSED ✓")
        return 0
    else:
        logger.error("SMOKE FAILED: %s", result.error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
