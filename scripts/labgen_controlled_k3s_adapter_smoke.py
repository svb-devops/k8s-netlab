#!/usr/bin/env python3
"""
LabGen Controlled K3s Adapter Smoke v0.1
=========================================
Verifies K3sNamespaceLifecycleAdapter's real path under home_lab_mvp profile.

Scope — this script ONLY tests:
  - namespace create / verify / delete (lifecycle)
  - verifier RoleBinding create / verify

This script does NOT:
  - Execute full lab sessions
  - Execute runtime start
  - Call Proxmox or registry
  - Call LLM pipelines
  - Create VMs
  - Accept client traffic
  - Print secret values

Namespace operations permitted:
  - Create 1 controlled smoke namespace (prefix + "smoke-" + random suffix)
  - Create 1 verifier RoleBinding in that namespace (namespace-scoped only)
  - Delete that namespace
  - Verify deletion accepted

Not permitted:
  - Operating on default / kube-system / kube-public / kube-node-lease
  - Operating on namespaces without the configured allowed prefix
  - Batch namespace creation
  - ClusterRoleBinding creation

Usage:
  # Precheck only (no K8s writes — safe to run anytime):
  python scripts/labgen_controlled_k3s_adapter_smoke.py \\
      --env-file .env.home_lab

  # Execute namespace lifecycle smoke (explicit write authorization required):
  python scripts/labgen_controlled_k3s_adapter_smoke.py \\
      --env-file .env.home_lab --allow-k8s-write

  # JSON output for CI or result artifact:
  python scripts/labgen_controlled_k3s_adapter_smoke.py \\
      --env-file .env.home_lab --allow-k8s-write --json

Exit codes:
  0  K3S_SMOKE_PASSED or K3S_SMOKE_PASSED_WITH_NOTES
  1  K3S_SMOKE_FAILED
  2  K3S_SMOKE_BLOCKED (preconditions not met, env missing, write not authorized)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import string
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Project root on sys.path (for backend imports)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — stable across versions
# ---------------------------------------------------------------------------

FINAL_PASSED = "K3S_SMOKE_PASSED"
FINAL_PASSED_WITH_NOTES = "K3S_SMOKE_PASSED_WITH_NOTES"
FINAL_BLOCKED = "K3S_SMOKE_BLOCKED"
FINAL_FAILED = "K3S_SMOKE_FAILED"

_SEV_PASS = "pass"
_SEV_WARN = "warn"
_SEV_BLOCKED = "blocked"
_SEV_FAIL = "fail"

_PLACEHOLDER_MARKERS: Tuple[str, ...] = ("<", ">", "CHANGEME", "your-", "placeholder")

_FORBIDDEN_NAMESPACES = frozenset({
    "default", "kube-system", "kube-public", "kube-node-lease"
})

_REQUIRED_MODE = "home_lab_mvp"
_REQUIRED_ADAPTER = "k8s"

_SMOKE_SUFFIX_CHARS = string.ascii_lowercase + string.digits


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PhaseResult:
    phase: str
    status: str    # pass | warn | blocked | fail
    message: str


@dataclass
class SmokeResult:
    decision: str
    phases: List[PhaseResult] = field(default_factory=list)
    missing_inputs: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Sanitized evidence — namespace name only, no credentials
    smoke_namespace: Optional[str] = None
    wrote_namespace: bool = False
    wrote_rolebinding: bool = False
    cleanup_confirmed: bool = False
    # Audit: confirm what was NOT done (must all be False)
    runtime_start_executed: bool = False
    proxmox_called: bool = False
    registry_called: bool = False
    llm_called: bool = False


# ---------------------------------------------------------------------------
# Env file loader
# ---------------------------------------------------------------------------


def _load_env_file(path: str) -> Tuple[dict, Optional[str]]:
    """Load key=value pairs from env file. Returns (env_dict, error_or_None)."""
    if not os.path.isfile(path):
        return {}, f"Env file not found: {path}"
    env: dict = {}
    try:
        with open(path) as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    env[key.strip()] = val.strip()
    except OSError as exc:
        return {}, f"Cannot read env file: {type(exc).__name__}"
    return env, None


def _is_placeholder(value: str) -> bool:
    """Return True if value is empty or looks like an unset placeholder."""
    if not value:
        return True
    lower = value.lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker.lower() in lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Namespace name
# ---------------------------------------------------------------------------


def _make_smoke_namespace(prefix: str) -> str:
    """Build a smoke namespace: {prefix}smoke-{6_random_chars}.

    The resulting name starts with the configured prefix. Before any K8s call,
    the adapter's create_namespace() internally invokes NamespaceSafetyValidator
    (DNS label check, forbidden namespace check, prefix allowlist check).
    Additionally, _FORBIDDEN_NAMESPACES is checked here as a defence-in-depth guard.
    """
    suffix = "".join(random.choices(_SMOKE_SUFFIX_CHARS, k=6))
    return f"{prefix}smoke-{suffix}"


# ---------------------------------------------------------------------------
# Phase 0 — env / profile validation
# ---------------------------------------------------------------------------


def _phase0_env_profile(env: dict) -> Tuple[PhaseResult, List[str]]:
    """Validate that env is configured for home_lab_mvp with real K8s adapter."""
    missing: List[str] = []

    runtime_mode = env.get("LABGEN_RUNTIME_MODE", "")
    if runtime_mode != _REQUIRED_MODE:
        missing.append(
            f"LABGEN_RUNTIME_MODE must be '{_REQUIRED_MODE}', got '{runtime_mode}'"
        )

    adapter = env.get("LABGEN_NAMESPACE_ADAPTER", "")
    if adapter != _REQUIRED_ADAPTER:
        missing.append(
            f"LABGEN_NAMESPACE_ADAPTER must be '{_REQUIRED_ADAPTER}', got '{adapter}' "
            "(StubNamespaceLifecycleAdapter is forbidden in home_lab_mvp)"
        )

    kubeconfig = env.get("LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "")
    if _is_placeholder(kubeconfig):
        missing.append(
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is not set or is a placeholder — "
            "inject the real kubeconfig path"
        )

    prefixes_raw = env.get("LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES", "")
    if not prefixes_raw or _is_placeholder(prefixes_raw):
        missing.append("LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES is not configured")
    else:
        prefixes = [p.strip() for p in prefixes_raw.split(",") if p.strip()]
        if not prefixes:
            missing.append(
                "LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES parses to empty list"
            )

    for key in (
        "LABGEN_K8S_VERIFIER_SA_NAME",
        "LABGEN_K8S_VERIFIER_SA_NAMESPACE",
        "LABGEN_K8S_VERIFIER_ROLE_NAME",
        "LABGEN_K8S_VERIFIER_ROLEBINDING_NAME",
    ):
        val = env.get(key, "")
        if not val or _is_placeholder(val):
            missing.append(f"{key} is not configured")

    if missing:
        return (
            PhaseResult("phase0_env_profile", _SEV_BLOCKED, "Profile validation failed"),
            missing,
        )
    return (
        PhaseResult(
            "phase0_env_profile", _SEV_PASS,
            f"Profile: runtime_mode={runtime_mode} adapter={adapter}"
        ),
        [],
    )


# ---------------------------------------------------------------------------
# Phase 1 — secret injection verification
# ---------------------------------------------------------------------------


def _phase1_secret_injection(env: dict) -> Tuple[PhaseResult, List[str]]:
    """Verify kubeconfig path resolves to a real file (not placeholder)."""
    missing: List[str] = []
    kubeconfig = env.get("LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "")

    if kubeconfig and not _is_placeholder(kubeconfig):
        if not os.path.isfile(kubeconfig):
            missing.append(
                "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH points to a non-existent file — "
                "inject the real kubeconfig"
            )

    if missing:
        return (
            PhaseResult(
                "phase1_secret_injection", _SEV_BLOCKED,
                "Kubeconfig not available at configured path"
            ),
            missing,
        )
    return (
        PhaseResult("phase1_secret_injection", _SEV_PASS, "Secret injection verified"),
        [],
    )


# ---------------------------------------------------------------------------
# Core smoke runner
# ---------------------------------------------------------------------------


def run_smoke(
    env: dict,
    allow_k8s_write: bool = False,
    adapter=None,
) -> SmokeResult:
    """Run the controlled K3s adapter smoke.

    Parameters
    ----------
    env:
        Key/value dict loaded from the home_lab env file. Never prints values.
    allow_k8s_write:
        Must be True to execute create / delete operations. Default: precheck only.
    adapter:
        Injectable NamespaceLifecyclePort. For tests: pass a StubNamespaceLifecycleAdapter.
        For real use: leave None — the real K3sNamespaceLifecycleAdapter is built from env.

    Guarantees:
    - Never calls Proxmox, registry, LLM, or runtime start.
    - Never prints kubeconfig content, tokens, or passwords.
    - Always attempts delete if namespace was created (even on failure).
    - Cleanup failure is a K3S_SMOKE_FAILED result, not silently ignored.
    """
    result = SmokeResult(decision=FINAL_BLOCKED)

    # Phase 0 + 1: precondition checks
    phase0, missing0 = _phase0_env_profile(env)
    result.phases.append(phase0)
    result.missing_inputs.extend(missing0)

    phase1, missing1 = _phase1_secret_injection(env)
    result.phases.append(phase1)
    result.missing_inputs.extend(missing1)

    if result.missing_inputs:
        result.decision = FINAL_BLOCKED
        result.phases.append(PhaseResult(
            "phase2_precheck", _SEV_BLOCKED,
            f"Blocked: {len(result.missing_inputs)} precondition(s) not met"
        ))
        return result

    # Parse allowed prefixes (already validated in phase0)
    prefixes_raw = env.get("LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES", "lab-stg-")
    prefixes = [p.strip() for p in prefixes_raw.split(",") if p.strip()]
    smoke_prefix = prefixes[0]

    result.phases.append(PhaseResult(
        "phase2_precheck", _SEV_PASS,
        f"Preconditions met; smoke prefix='{smoke_prefix}'"
    ))

    # K8s write gate
    if not allow_k8s_write:
        result.decision = FINAL_BLOCKED
        result.missing_inputs.append(
            "K8s write not authorized: rerun with --allow-k8s-write to execute "
            "namespace lifecycle smoke"
        )
        result.phases.append(PhaseResult(
            "phase3_k8s_write_gate", _SEV_BLOCKED,
            "K8s write not enabled (precheck-only mode)"
        ))
        return result

    # Build adapter from env if not injected
    if adapter is None:
        try:
            from backend.labgen.namespace_lifecycle import (
                K3sNamespaceLifecycleAdapter,
                K8sAdapterConfig,
            )
            timeout = int(env.get("LABGEN_K8S_API_TIMEOUT_SECONDS", "10"))
            cfg = K8sAdapterConfig(
                kubeconfig_path=env.get("LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", ""),
                in_cluster=False,
                context=env.get("LABGEN_K8S_CONTEXT", ""),
                api_timeout_seconds=timeout,
                allowed_namespace_prefixes=prefixes,
                verifier_sa_name=env.get("LABGEN_K8S_VERIFIER_SA_NAME", "labgen-verifier"),
                verifier_sa_namespace=env.get("LABGEN_K8S_VERIFIER_SA_NAMESPACE", "kube-system"),
                verifier_role_name=env.get("LABGEN_K8S_VERIFIER_ROLE_NAME", "labgen-verifier-role"),
                verifier_rolebinding_name=env.get(
                    "LABGEN_K8S_VERIFIER_ROLEBINDING_NAME", "labgen-verifier-binding"
                ),
            )
            adapter = K3sNamespaceLifecycleAdapter(cfg)
        except Exception as exc:
            result.decision = FINAL_FAILED
            result.phases.append(PhaseResult(
                "adapter_build", _SEV_FAIL,
                f"Failed to build K3sNamespaceLifecycleAdapter: {type(exc).__name__}"
            ))
            return result

    # Generate smoke namespace
    smoke_ns = _make_smoke_namespace(smoke_prefix)
    result.smoke_namespace = smoke_ns  # sanitized namespace name only — no credentials

    # Safety: namespace must not be a system namespace (defence-in-depth)
    if smoke_ns in _FORBIDDEN_NAMESPACES:
        result.decision = FINAL_FAILED
        result.phases.append(PhaseResult(
            "namespace_safety_check", _SEV_FAIL,
            "Generated namespace name collides with a reserved system namespace"
        ))
        return result

    # Phases 3-7: write operations with guaranteed cleanup in finally
    namespace_created = False
    delete_failed = False

    try:
        # Phase 3: create namespace
        created = adapter.create_namespace(smoke_ns)
        if not created:
            result.phases.append(PhaseResult(
                "phase3_namespace_create", _SEV_FAIL,
                "Namespace creation failed (adapter returned False)"
            ))
            # namespace not created → nothing to clean up
        else:
            namespace_created = True
            result.wrote_namespace = True
            result.phases.append(PhaseResult(
                "phase3_namespace_create", _SEV_PASS, "Namespace created"
            ))

            # Phase 4: verify namespace exists
            exists = adapter.namespace_exists(smoke_ns)
            if exists:
                result.phases.append(PhaseResult(
                    "phase4_namespace_exists", _SEV_PASS,
                    "Namespace existence confirmed"
                ))
            else:
                result.phases.append(PhaseResult(
                    "phase4_namespace_exists", _SEV_WARN,
                    "Namespace existence check returned False after create — "
                    "may still be provisioning"
                ))
                result.notes.append("namespace_exists returned False after create")

            # Phase 5: create verifier RoleBinding
            rb_ok = adapter.ensure_verifier_rolebinding(smoke_ns)
            if rb_ok:
                result.wrote_rolebinding = True
                result.phases.append(PhaseResult(
                    "phase5_rolebinding_create", _SEV_PASS,
                    "Verifier RoleBinding created (namespace-scoped, no ClusterRoleBinding)"
                ))
            else:
                result.phases.append(PhaseResult(
                    "phase5_rolebinding_create", _SEV_WARN,
                    "Verifier RoleBinding creation failed"
                ))
                result.notes.append("ensure_verifier_rolebinding returned False")

            # Phase 6: verify RoleBinding exists
            if result.wrote_rolebinding:
                rb_exists = adapter.verifier_rolebinding_exists(smoke_ns)
                if rb_exists:
                    result.phases.append(PhaseResult(
                        "phase6_rolebinding_exists", _SEV_PASS,
                        "Verifier RoleBinding confirmed"
                    ))
                else:
                    result.phases.append(PhaseResult(
                        "phase6_rolebinding_exists", _SEV_WARN,
                        "Verifier RoleBinding not confirmed after create"
                    ))
                    result.notes.append("verifier_rolebinding_exists returned False after create")
            else:
                result.phases.append(PhaseResult(
                    "phase6_rolebinding_exists", _SEV_WARN,
                    "Skipped: RoleBinding was not created in phase 5"
                ))

            # Phase 7: check for stuck terminating
            stuck = adapter.is_namespace_stuck_terminating(smoke_ns)
            if not stuck:
                result.phases.append(PhaseResult(
                    "phase7_stuck_terminating_check", _SEV_PASS,
                    "Namespace is not stuck terminating"
                ))
            else:
                result.phases.append(PhaseResult(
                    "phase7_stuck_terminating_check", _SEV_WARN,
                    "Namespace reports stuck-terminating state"
                ))
                result.notes.append("is_namespace_stuck_terminating returned True")

    except Exception as exc:
        result.phases.append(PhaseResult(
            "unexpected_error", _SEV_FAIL,
            f"Unexpected error during smoke phases: {type(exc).__name__}"
        ))

    finally:
        # Phases 8-10: cleanup — always run if namespace was created
        if namespace_created:
            # Phase 8: delete namespace
            deleted = adapter.delete_namespace(smoke_ns)
            if deleted:
                result.phases.append(PhaseResult(
                    "phase8_namespace_delete", _SEV_PASS,
                    "Namespace deletion initiated"
                ))
                # Phase 9: confirm deletion accepted
                is_gone = adapter.is_namespace_deleted(smoke_ns)
                if is_gone:
                    result.phases.append(PhaseResult(
                        "phase9_deletion_confirmed", _SEV_PASS,
                        "Namespace deleted (confirmed gone)"
                    ))
                else:
                    result.phases.append(PhaseResult(
                        "phase9_deletion_confirmed", _SEV_PASS,
                        "Deletion accepted by API (namespace may still be in Terminating phase)"
                    ))
                result.cleanup_confirmed = True
            else:
                delete_failed = True
                result.phases.append(PhaseResult(
                    "phase8_namespace_delete", _SEV_FAIL,
                    "Namespace deletion FAILED — namespace may be residual"
                ))
                result.phases.append(PhaseResult(
                    "phase9_deletion_confirmed", _SEV_FAIL,
                    "Skipped: delete call failed"
                ))
        else:
            result.cleanup_confirmed = True

        # Phase 10: evidence sanitization confirmation
        if delete_failed or not result.cleanup_confirmed:
            result.phases.append(PhaseResult(
                "phase10_cleanup_confirmed", _SEV_FAIL,
                "CLEANUP FAILED — manual intervention may be required"
            ))
        else:
            result.phases.append(PhaseResult(
                "phase10_cleanup_confirmed", _SEV_PASS,
                "Evidence sanitized — no credentials or raw K8s exception bodies logged"
            ))

    # Determine final decision from phase results
    fail_phases = [p for p in result.phases if p.status == _SEV_FAIL]
    blocked_phases = [p for p in result.phases if p.status == _SEV_BLOCKED]
    warn_phases = [p for p in result.phases if p.status == _SEV_WARN]

    if fail_phases:
        result.decision = FINAL_FAILED
    elif blocked_phases:
        result.decision = FINAL_BLOCKED
    elif warn_phases:
        result.decision = FINAL_PASSED_WITH_NOTES
    else:
        result.decision = FINAL_PASSED

    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _result_to_dict(result: SmokeResult) -> dict:
    """Convert SmokeResult to a stable JSON-serializable dict."""
    return {
        "decision": result.decision,
        "smoke_namespace": result.smoke_namespace,
        "wrote_namespace": result.wrote_namespace,
        "wrote_rolebinding": result.wrote_rolebinding,
        "cleanup_confirmed": result.cleanup_confirmed,
        "runtime_start_executed": result.runtime_start_executed,
        "proxmox_called": result.proxmox_called,
        "registry_called": result.registry_called,
        "llm_called": result.llm_called,
        "phases": [
            {"phase": p.phase, "status": p.status, "message": p.message}
            for p in result.phases
        ],
        "missing_inputs": result.missing_inputs,
        "notes": result.notes,
    }


def _print_result(result: SmokeResult, json_output: bool) -> None:
    """Print result to stdout. Never prints secret values."""
    if json_output:
        print(json.dumps(_result_to_dict(result), indent=2))
        return

    print("\n=== Controlled K3s Adapter Smoke ===")
    for p in result.phases:
        label = p.status.upper().ljust(7)
        print(f"  [{label}] {p.phase}: {p.message}")
    print(f"\nDecision: {result.decision}")
    if result.missing_inputs:
        print("\nMissing inputs:")
        for m in result.missing_inputs:
            print(f"  - {m}")
    if result.notes:
        print("\nNotes:")
        for n in result.notes:
          print(f"  - {n}")
    print(f"\nAudit: runtime_start={result.runtime_start_executed} "
          f"proxmox={result.proxmox_called} "
          f"registry={result.registry_called} "
          f"llm={result.llm_called}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Controlled K3s Adapter Smoke — namespace lifecycle only"
    )
    parser.add_argument(
        "--env-file", required=True,
        help="Path to home_lab_mvp env file (not the .example template)"
    )
    parser.add_argument(
        "--allow-k8s-write", action="store_true",
        help="Authorize real namespace create/delete operations (explicit opt-in)"
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Emit JSON result to stdout"
    )
    args = parser.parse_args(argv)

    # Load env file
    env, load_err = _load_env_file(args.env_file)
    if load_err:
        blocked = SmokeResult(
            decision=FINAL_BLOCKED,
            missing_inputs=[load_err],
            phases=[PhaseResult("env_load", _SEV_BLOCKED, load_err)],
        )
        _print_result(blocked, args.json_output)
        return 2

    result = run_smoke(env, allow_k8s_write=args.allow_k8s_write)
    _print_result(result, args.json_output)

    if result.decision in (FINAL_PASSED, FINAL_PASSED_WITH_NOTES):
        return 0
    if result.decision == FINAL_BLOCKED:
        return 2
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
