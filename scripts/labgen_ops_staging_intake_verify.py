#!/usr/bin/env python3
"""
LabGen Ops Staging Intake Verification Gate v0.1
=================================================
Unified gate that determines whether the staging environment has advanced from
LIVE_TRIAL_BLOCKED to READY_TO_RERUN_CONTROLLED_STAGING_TRIAL.

Calls existing helpers in sequence:
  Phase 0: env file readability
  Phase 1: missing inputs (labgen_staging_missing_inputs)
  Phase 2: staging provisioning validate (labgen_staging_provisioning_validate)
  Phase 3: production preflight (labgen_production_preflight, via env context)
  Phase 4: staging dry run offline (labgen_staging_dry_run, no base-url)
  Phase 5: safe GET diagnostics (optional, only when --base-url provided)
  Phase 6: readiness decision

Guarantees:
  - Never executes runtime start, namespace creation, or any destructive action.
  - Never calls POST/PUT/PATCH endpoints.
  - Never connects to real K3s, Proxmox, or LLM providers.
  - Never prints secret values — reports key names and presence only.
  - Treats placeholder / empty / absent values as missing.
  - Fails closed on unreachable diagnostics or secret-looking response content.
  - HTTP client is injectable for testing (no real network calls in tests).

Decision values:
  READY_TO_RERUN_CONTROLLED_STAGING_TRIAL   — all phases pass
  BLOCKED_MISSING_INPUTS                    — phase 0 or 1 blocks
  BLOCKED_INVALID_CONFIG                    — phase 2, 3, or 4 blocks
  BLOCKED_DIAGNOSTICS_UNREACHABLE           — phase 5 network or parse failure
  BLOCKED_SECRET_LEAK_RISK                  — phase 5 secret pattern in response

Exit codes:
  0  READY_TO_RERUN_CONTROLLED_STAGING_TRIAL
  1  Any BLOCKED_* decision
  2  Script invocation error (bad args, env file not found)

Usage:
  # Full offline gate check
  python scripts/labgen_ops_staging_intake_verify.py \\
      --env-file <staging-env-file> --json

  # With optional safe diagnostics (service must be running)
  python scripts/labgen_ops_staging_intake_verify.py \\
      --env-file <staging-env-file> \\
      --base-url <staging-host> --json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

# ---------------------------------------------------------------------------
# Sibling module imports
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from labgen_staging_missing_inputs import (  # noqa: E402
    check_missing_inputs,
    MissingInputsResult,
)
from labgen_staging_provisioning_validate import (  # noqa: E402
    validate_env_file,
    ProvisioningResult,
)
from labgen_production_preflight import (  # noqa: E402
    run_preflight,
    PreflightReport,
)
from labgen_staging_dry_run import (  # noqa: E402
    load_env_file,
    run_from_env_file,
    DryRunReport,
    _env_context,
    _scan_for_secrets,
    _default_http_get,
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

HttpGetResult = Tuple[int, str, Optional[str]]
HttpGetFn = Callable[[str, dict], HttpGetResult]

# ---------------------------------------------------------------------------
# Decision values
# ---------------------------------------------------------------------------

DECISION_READY = "READY_TO_RERUN_CONTROLLED_STAGING_TRIAL"
DECISION_BLOCKED_MISSING = "BLOCKED_MISSING_INPUTS"
DECISION_BLOCKED_CONFIG = "BLOCKED_INVALID_CONFIG"
DECISION_BLOCKED_UNREACHABLE = "BLOCKED_DIAGNOSTICS_UNREACHABLE"
DECISION_BLOCKED_SECRET_LEAK = "BLOCKED_SECRET_LEAK_RISK"

# ---------------------------------------------------------------------------
# Safe GET diagnostics endpoints (GET only — never POST)
# ---------------------------------------------------------------------------

# (name, path, requires_admin_token, description, expect_json)
_SAFE_GET_CHECKS = [
    ("health", "/api/health", False, "health endpoint", True),
    ("openapi", "/openapi.json", False, "OpenAPI schema", True),
    ("frontend_root", "/", False, "frontend root", False),
    ("contract_pack", "/api/labgen/contract-pack", True, "LabGen contract pack", True),
    ("runtime_adapter_status", "/api/labgen/runtime/adapter-status", True, "runtime adapter status", True),
    ("llm_provider_status", "/api/labgen/llm-provider/status", True, "LLM provider status", True),
]

# Paths that must NEVER be called by this script under any circumstances
_FORBIDDEN_PATHS = frozenset({
    "/api/labgen/seed/demo",
    "/api/labgen/drafts",
    "/api/lab-sessions",
    "/api/labgen/runtime/expire-sessions",
    "/api/labgen/drafts/publish",
    "/complete",
    "/abort",
})

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class IntakePhaseResult:
    phase_id: str
    status: str           # "pass" | "warning" | "blocking" | "skipped" | "error"
    summary: str
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    diag_kind: Optional[str] = None  # phase5 only: "unreachable" | "secret_leak"

    def to_dict(self) -> dict:
        d: dict = {
            "status": self.status,
            "summary": self.summary,
            "blocking_issues": self.blocking_issues,
            "warnings": self.warnings,
        }
        if self.extra:
            d.update(self.extra)
        if self.diag_kind is not None:
            d["diag_kind"] = self.diag_kind
        return d


@dataclass
class IntakeVerificationResult:
    decision: str
    phase_results: dict[str, IntakePhaseResult]
    blocking_issues: list[str]
    warnings: list[str]
    checked_at: str
    next_step: str
    env_file: str
    base_url: Optional[str]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "phase_results": {
                k: (v.to_dict() if v is not None else None)
                for k, v in self.phase_results.items()
            },
            "blocking_issues": self.blocking_issues,
            "warnings": self.warnings,
            "checked_at": self.checked_at,
            "next_step": self.next_step,
            "env_file": self.env_file,
            "base_url": self.base_url,
        }


# ---------------------------------------------------------------------------
# Individual phase runners
# ---------------------------------------------------------------------------


def _run_phase0(env_file: str) -> IntakePhaseResult:
    """Phase 0: verify env file is readable."""
    try:
        with open(env_file, encoding="utf-8"):
            pass
        return IntakePhaseResult(
            phase_id="phase0_env_readability",
            status="pass",
            summary=f"Env file readable: {env_file}",
        )
    except FileNotFoundError:
        return IntakePhaseResult(
            phase_id="phase0_env_readability",
            status="error",
            summary=f"Env file not found: {env_file}",
            blocking_issues=[f"Env file not found: {env_file}"],
        )
    except PermissionError as exc:
        return IntakePhaseResult(
            phase_id="phase0_env_readability",
            status="error",
            summary=f"Env file not readable: {exc}",
            blocking_issues=[f"Env file not readable: {exc}"],
        )
    except OSError as exc:
        return IntakePhaseResult(
            phase_id="phase0_env_readability",
            status="error",
            summary=f"Env file error: {exc}",
            blocking_issues=[f"Env file error: {exc}"],
        )


def _run_phase1(
    env_file: str,
    missing_inputs_fn: Callable[[str], MissingInputsResult],
) -> IntakePhaseResult:
    """Phase 1: missing inputs check."""
    try:
        result: MissingInputsResult = missing_inputs_fn(env_file)
    except Exception as exc:  # noqa: BLE001
        return IntakePhaseResult(
            phase_id="phase1_missing_inputs",
            status="error",
            summary=f"Missing inputs check failed: {exc}",
            blocking_issues=[f"missing_inputs_check_error: {exc}"],
        )

    if result.overall == "blocking":
        # Report key names only — never values
        issues = [
            f"Missing required input: {key}"
            for key in result.all_missing_keys
        ]
        return IntakePhaseResult(
            phase_id="phase1_missing_inputs",
            status="blocking",
            summary=f"{result.missing_count} required input(s) missing or placeholder",
            blocking_issues=issues,
            extra={
                "missing_count": result.missing_count,
                "missing_keys": result.all_missing_keys,
            },
        )

    return IntakePhaseResult(
        phase_id="phase1_missing_inputs",
        status="pass",
        summary="All required inputs are set (no missing or placeholder values)",
        extra={
            "missing_count": 0,
            "missing_keys": [],
        },
    )


def _run_phase2(
    env_file: str,
    validate_fn: Callable[[str], ProvisioningResult],
) -> IntakePhaseResult:
    """Phase 2: staging provisioning validate (static env file checks)."""
    try:
        result: ProvisioningResult = validate_fn(env_file)
    except Exception as exc:  # noqa: BLE001
        return IntakePhaseResult(
            phase_id="phase2_provisioning_validate",
            status="error",
            summary=f"Provisioning validate failed unexpectedly: {exc}",
            blocking_issues=[f"provisioning_validate_error: {exc}"],
        )

    blocking = [i.message for i in result.blocking_issues]
    warnings = [i.message for i in result.warnings]

    if blocking:
        return IntakePhaseResult(
            phase_id="phase2_provisioning_validate",
            status="blocking",
            summary=f"Provisioning validate: {len(blocking)} blocking issue(s)",
            blocking_issues=blocking,
            warnings=warnings,
            extra={"blocking_count": len(blocking), "warning_count": len(warnings)},
        )

    return IntakePhaseResult(
        phase_id="phase2_provisioning_validate",
        status="warning" if warnings else "pass",
        summary=(
            f"Provisioning validate passed ({len(warnings)} warning(s))"
            if warnings
            else "Provisioning validate passed"
        ),
        warnings=warnings,
        extra={"blocking_count": 0, "warning_count": len(warnings)},
    )


def _run_phase3(
    env_file: str,
    preflight_fn: Callable[[], PreflightReport],
) -> IntakePhaseResult:
    """Phase 3: production preflight (reads os.environ via env_context)."""
    env_vars, load_err = load_env_file(env_file)
    if load_err:
        return IntakePhaseResult(
            phase_id="phase3_production_preflight",
            status="error",
            summary=f"Cannot load env file for preflight: {load_err}",
            blocking_issues=[f"env_load_error: {load_err}"],
        )

    try:
        with _env_context(env_vars):
            report: PreflightReport = preflight_fn()
    except Exception as exc:  # noqa: BLE001
        return IntakePhaseResult(
            phase_id="phase3_production_preflight",
            status="error",
            summary=f"Production preflight failed unexpectedly: {exc}",
            blocking_issues=[f"preflight_error: {exc}"],
        )

    blocking = [
        f"[{c.name}] {c.message}"
        for c in report.checks
        if c.severity == "blocking"
    ]
    warnings = [
        f"[{c.name}] {c.message}"
        for c in report.checks
        if c.severity == "warning"
    ]

    if blocking:
        return IntakePhaseResult(
            phase_id="phase3_production_preflight",
            status="blocking",
            summary=f"Production preflight: {len(blocking)} blocking issue(s)",
            blocking_issues=blocking,
            warnings=warnings,
            extra={"blocking_count": len(blocking), "warning_count": len(warnings)},
        )

    return IntakePhaseResult(
        phase_id="phase3_production_preflight",
        status="warning" if warnings else "pass",
        summary=(
            f"Production preflight passed ({len(warnings)} warning(s))"
            if warnings
            else "Production preflight passed"
        ),
        warnings=warnings,
        extra={"blocking_count": 0, "warning_count": len(warnings)},
    )


def _run_phase4(
    env_file: str,
    dry_run_fn: Callable[..., DryRunReport],
) -> IntakePhaseResult:
    """Phase 4: staging dry run offline mode (no HTTP probes)."""
    try:
        report: DryRunReport = dry_run_fn(env_file, base_url=None)
    except Exception as exc:  # noqa: BLE001
        return IntakePhaseResult(
            phase_id="phase4_dry_run_offline",
            status="error",
            summary=f"Staging dry run offline failed unexpectedly: {exc}",
            blocking_issues=[f"dry_run_error: {exc}"],
        )

    blocking = [
        f"[{c.phase}/{c.name}] {c.message}"
        for c in report.checks
        if c.severity == "blocking"
    ]
    warnings = [
        f"[{c.phase}/{c.name}] {c.message}"
        for c in report.checks
        if c.severity == "warning"
    ]

    if blocking:
        return IntakePhaseResult(
            phase_id="phase4_dry_run_offline",
            status="blocking",
            summary=f"Staging dry run offline: {len(blocking)} blocking issue(s)",
            blocking_issues=blocking,
            warnings=warnings,
            extra={"blocking_count": len(blocking), "warning_count": len(warnings)},
        )

    return IntakePhaseResult(
        phase_id="phase4_dry_run_offline",
        status="warning" if warnings else "pass",
        summary=(
            f"Staging dry run offline passed ({len(warnings)} warning(s))"
            if warnings
            else "Staging dry run offline passed"
        ),
        warnings=warnings,
        extra={"blocking_count": 0, "warning_count": len(warnings)},
    )


def _run_phase5(
    env_file: str,
    base_url: str,
    http_get: HttpGetFn,
) -> IntakePhaseResult:
    """Phase 5: optional safe GET diagnostics (only when --base-url provided).

    Never calls destructive endpoints. Never prints secret values.
    Fails closed on unreachable endpoints or secret-looking response content.
    """
    env_vars, load_err = load_env_file(env_file)
    if load_err:
        return IntakePhaseResult(
            phase_id="phase5_diagnostics",
            status="error",
            summary=f"Cannot load env file for diagnostics: {load_err}",
            blocking_issues=[f"env_load_error: {load_err}"],
            diag_kind="unreachable",
        )

    admin_token = env_vars.get("ADMIN_TOKEN", "")
    admin_headers: dict[str, str] = {}
    if admin_token:
        admin_headers["X-Admin-Token"] = admin_token

    base = base_url.rstrip("/")

    unreachable_issues: list[str] = []
    secret_leak_issues: list[str] = []
    warnings: list[str] = []

    for name, path, needs_admin, desc, expect_json in _SAFE_GET_CHECKS:
        # Safety guard: never call forbidden paths
        if any(fp in path for fp in _FORBIDDEN_PATHS):
            continue

        url = base + path
        headers = admin_headers if needs_admin else {}
        status, body, err = http_get(url, headers)

        if err:
            unreachable_issues.append(
                f"{desc} ({path}): network error — {err}"
            )
            continue

        # Secret leak check (regardless of status code)
        if body:
            hits = _scan_for_secrets(body)
            if hits:
                secret_leak_issues.append(
                    f"{desc} ({path}): secret-looking pattern in response: {hits}"
                )
                continue

        # Invalid JSON where JSON is expected
        if expect_json and body and status in range(200, 300):
            try:
                json.loads(body)
            except (json.JSONDecodeError, ValueError):
                unreachable_issues.append(
                    f"{desc} ({path}): invalid JSON in 2xx response"
                )
                continue

        if status in range(200, 300):
            pass  # pass — already checked for secrets above

        elif needs_admin and not admin_token and status in (401, 403, 503):
            pass  # expected: admin endpoint without token

        elif name == "health" and status not in range(200, 300):
            # Health endpoint may fail if Proxmox unreachable — treat as warning
            warnings.append(
                f"{desc} ({path}): {status} — may require Proxmox connectivity"
            )

        else:
            warnings.append(
                f"{desc} ({path}): unexpected status {status}"
            )

    # Determine phase status (secret_leak takes priority over unreachable)
    if secret_leak_issues:
        return IntakePhaseResult(
            phase_id="phase5_diagnostics",
            status="blocking",
            summary=f"Safe diagnostics: secret-looking content in {len(secret_leak_issues)} response(s)",
            blocking_issues=secret_leak_issues,
            warnings=warnings,
            extra={"base_url": base_url},
            diag_kind="secret_leak",
        )

    if unreachable_issues:
        return IntakePhaseResult(
            phase_id="phase5_diagnostics",
            status="blocking",
            summary=f"Safe diagnostics: {len(unreachable_issues)} endpoint(s) unreachable or returned invalid JSON",
            blocking_issues=unreachable_issues,
            warnings=warnings,
            extra={"base_url": base_url},
            diag_kind="unreachable",
        )

    return IntakePhaseResult(
        phase_id="phase5_diagnostics",
        status="warning" if warnings else "pass",
        summary=(
            f"Safe diagnostics passed ({len(warnings)} warning(s))"
            if warnings
            else "Safe diagnostics passed"
        ),
        warnings=warnings,
        extra={"base_url": base_url},
    )


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def _determine_decision(
    phases: dict[str, Optional[IntakePhaseResult]],
) -> str:
    """Map phase results to final decision value.

    Priority (highest to lowest):
      1. BLOCKED_MISSING_INPUTS  — env not readable, or missing/placeholder inputs
      2. BLOCKED_INVALID_CONFIG  — provisioning validate / preflight / dry run fails
      3. BLOCKED_SECRET_LEAK_RISK — secret pattern found in diagnostics response
      4. BLOCKED_DIAGNOSTICS_UNREACHABLE — diagnostics network/parse failure
      5. READY_TO_RERUN_CONTROLLED_STAGING_TRIAL
    """
    p0 = phases.get("phase0_env_readability")
    p1 = phases.get("phase1_missing_inputs")
    p2 = phases.get("phase2_provisioning_validate")
    p3 = phases.get("phase3_production_preflight")
    p4 = phases.get("phase4_dry_run_offline")
    p5 = phases.get("phase5_diagnostics")

    # Phase 0: env file not readable
    if p0 and p0.status in ("error", "blocking"):
        return DECISION_BLOCKED_MISSING

    # Phase 1: missing inputs
    if p1 and p1.status in ("error", "blocking"):
        return DECISION_BLOCKED_MISSING

    # Phase 2/3/4: config / preflight / dry run
    for phase in (p2, p3, p4):
        if phase and phase.status in ("error", "blocking"):
            return DECISION_BLOCKED_CONFIG

    # Phase 5: diagnostics (if provided)
    if p5 and p5.status in ("error", "blocking"):
        if p5.diag_kind == "secret_leak":
            return DECISION_BLOCKED_SECRET_LEAK
        return DECISION_BLOCKED_UNREACHABLE

    return DECISION_READY


def _determine_next_step(decision: str, base_url: Optional[str]) -> str:
    if decision == DECISION_READY:
        return (
            "All checks passed. Ops may re-execute Controlled Staging Trial Live Run "
            "with explicit operator approval. "
            "Run: scripts/labgen_controlled_staging_trial.py "
            "--env-file <staging-env-file> --base-url <staging-host> [--allow-runtime-start ...]"
        )
    if decision == DECISION_BLOCKED_MISSING:
        return (
            "Inject all missing inputs via secret manager, then re-run this gate. "
            "Run: python scripts/labgen_staging_missing_inputs.py --env-file <staging-env-file>"
        )
    if decision == DECISION_BLOCKED_CONFIG:
        return (
            "Fix the config issues listed in blocking_issues, then re-run this gate. "
            "Run: python scripts/labgen_staging_provisioning_validate.py --env-file <staging-env-file>"
        )
    if decision == DECISION_BLOCKED_SECRET_LEAK:
        return (
            "Investigate secret-looking patterns found in diagnostic responses. "
            "Do NOT proceed until the source of the leak is identified and resolved."
        )
    if decision == DECISION_BLOCKED_UNREACHABLE:
        suffix = f" at {base_url}" if base_url else ""
        return (
            f"Confirm the staging service is running and accessible{suffix}, "
            "then re-run this gate."
        )
    return "Unknown decision — re-run with --json for details."


# ---------------------------------------------------------------------------
# Main gate runner
# ---------------------------------------------------------------------------


def run_intake_verification(
    env_file: str,
    *,
    base_url: Optional[str] = None,
    http_get: HttpGetFn = _default_http_get,
    # Injectable sub-helpers (for testing)
    _missing_inputs_fn: Callable[[str], MissingInputsResult] = check_missing_inputs,
    _validate_env_file_fn: Callable[[str], ProvisioningResult] = validate_env_file,
    _run_preflight_fn: Callable[[], PreflightReport] = run_preflight,
    _dry_run_offline_fn: Callable[..., DryRunReport] = run_from_env_file,
) -> IntakeVerificationResult:
    """Run all intake verification phases and return a structured result.

    Does NOT execute runtime start, namespace creation, or any destructive action.
    Does NOT connect to K3s, Proxmox, LLM providers, or real registry.
    Does NOT print secret values.

    Args:
        env_file:            Path to staging env file.
        base_url:            If provided, run safe GET diagnostics against this URL.
        http_get:            HTTP GET callable (injectable for testing).
        _missing_inputs_fn:  Injectable: check_missing_inputs
        _validate_env_file_fn: Injectable: validate_env_file
        _run_preflight_fn:   Injectable: run_preflight
        _dry_run_offline_fn: Injectable: run_from_env_file
    """
    checked_at = datetime.now(tz=timezone.utc).isoformat()

    phases: dict[str, Optional[IntakePhaseResult]] = {}

    # Phase 0
    p0 = _run_phase0(env_file)
    phases["phase0_env_readability"] = p0

    # Phase 1
    if p0.status in ("error", "blocking"):
        # Can't proceed — env file unreadable
        phases["phase1_missing_inputs"] = IntakePhaseResult(
            phase_id="phase1_missing_inputs",
            status="skipped",
            summary="Skipped — env file not readable",
        )
        phases["phase2_provisioning_validate"] = IntakePhaseResult(
            phase_id="phase2_provisioning_validate",
            status="skipped",
            summary="Skipped — env file not readable",
        )
        phases["phase3_production_preflight"] = IntakePhaseResult(
            phase_id="phase3_production_preflight",
            status="skipped",
            summary="Skipped — env file not readable",
        )
        phases["phase4_dry_run_offline"] = IntakePhaseResult(
            phase_id="phase4_dry_run_offline",
            status="skipped",
            summary="Skipped — env file not readable",
        )
        phases["phase5_diagnostics"] = None
    else:
        phases["phase1_missing_inputs"] = _run_phase1(env_file, _missing_inputs_fn)
        phases["phase2_provisioning_validate"] = _run_phase2(env_file, _validate_env_file_fn)
        phases["phase3_production_preflight"] = _run_phase3(env_file, _run_preflight_fn)
        phases["phase4_dry_run_offline"] = _run_phase4(env_file, _dry_run_offline_fn)

        if base_url:
            phases["phase5_diagnostics"] = _run_phase5(env_file, base_url, http_get)
        else:
            phases["phase5_diagnostics"] = None

    decision = _determine_decision(phases)

    # Consolidate all blocking issues and warnings (no secret values — only messages)
    all_blocking: list[str] = []
    all_warnings: list[str] = []
    for phase in phases.values():
        if phase is not None:
            all_blocking.extend(phase.blocking_issues)
            all_warnings.extend(phase.warnings)

    next_step = _determine_next_step(decision, base_url)

    return IntakeVerificationResult(
        decision=decision,
        phase_results=phases,
        blocking_issues=all_blocking,
        warnings=all_warnings,
        checked_at=checked_at,
        next_step=next_step,
        env_file=env_file,
        base_url=base_url,
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_COLOR_RED = "\033[91m"
_COLOR_GREEN = "\033[92m"
_COLOR_YELLOW = "\033[93m"
_COLOR_BOLD = "\033[1m"
_RESET = "\033[0m"

_STATUS_COLORS = {
    "pass": _COLOR_GREEN,
    "warning": _COLOR_YELLOW,
    "blocking": _COLOR_RED,
    "error": _COLOR_RED,
    "skipped": "",
}
_STATUS_ICONS = {
    "pass": "✓",
    "warning": "⚠",
    "blocking": "✗",
    "error": "✗",
    "skipped": "-",
}


def _human_output(result: IntakeVerificationResult, use_color: bool = True) -> None:
    def _c(color: str, text: str) -> str:
        return f"{color}{text}{_RESET}" if use_color and color else text

    print("LabGen Ops Staging Intake Verification Gate v0.1")
    print("=" * 55)
    print(f"Env file  : {result.env_file}")
    if result.base_url:
        print(f"Base URL  : {result.base_url}")
    print(f"Checked   : {result.checked_at}")
    print()

    phase_labels = {
        "phase0_env_readability": "Phase 0 — Env Readability",
        "phase1_missing_inputs": "Phase 1 — Missing Inputs",
        "phase2_provisioning_validate": "Phase 2 — Provisioning Validate",
        "phase3_production_preflight": "Phase 3 — Production Preflight",
        "phase4_dry_run_offline": "Phase 4 — Dry Run Offline",
        "phase5_diagnostics": "Phase 5 — Safe Diagnostics",
    }

    for phase_id, label in phase_labels.items():
        phase = result.phase_results.get(phase_id)
        if phase is None:
            print(f"  {label}: skipped (base-url not provided)")
            continue
        icon = _STATUS_ICONS.get(phase.status, "?")
        color = _STATUS_COLORS.get(phase.status, "")
        print(f"  {_c(color, icon)} {label}: {_c(color, phase.status.upper())}")
        print(f"      {phase.summary}")
        for issue in phase.blocking_issues:
            print(f"      {_c(_COLOR_RED, '✗')} {issue}")
        for w in phase.warnings:
            print(f"      {_c(_COLOR_YELLOW, '⚠')} {w}")

    print()
    decision_color = _COLOR_GREEN if result.decision == DECISION_READY else _COLOR_RED
    print(_c(decision_color, f"Decision: {result.decision}"))
    print()
    print(f"Next step: {result.next_step}")

    if result.blocking_issues:
        print()
        print(_c(_COLOR_RED, f"Blocking issues ({len(result.blocking_issues)}):"))
        for issue in result.blocking_issues:
            print(f"  ✗ {issue}")

    print()
    if result.decision == DECISION_READY:
        print(_c(_COLOR_GREEN, "INTAKE GATE PASSED — operator may proceed with live trial rerun."))
    else:
        print(_c(_COLOR_RED, "INTAKE GATE BLOCKED — resolve blocking issues before live trial rerun."))


def _json_output(result: IntakeVerificationResult) -> None:
    print(json.dumps(result.to_dict(), indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> tuple[str, Optional[str], bool]:
    """Return (env_file, base_url, use_json)."""
    env_file: Optional[str] = None
    base_url: Optional[str] = None
    use_json = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--json":
            use_json = True
        elif arg in ("--env-file", "-e") and i + 1 < len(argv):
            i += 1
            env_file = argv[i]
        elif arg.startswith("--env-file="):
            env_file = arg.split("=", 1)[1]
        elif arg in ("--base-url",) and i + 1 < len(argv):
            i += 1
            base_url = argv[i]
        elif arg.startswith("--base-url="):
            base_url = arg.split("=", 1)[1]
        i += 1

    if not env_file:
        print(
            "Error: --env-file <path> is required.\n"
            "Usage: python scripts/labgen_ops_staging_intake_verify.py "
            "--env-file <staging-env-file> [--base-url <staging-host>] [--json]",
            file=sys.stderr,
        )
        sys.exit(2)

    return env_file, base_url, use_json


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    env_file, base_url, use_json = _parse_args(argv)

    result = run_intake_verification(env_file, base_url=base_url)

    if use_json:
        _json_output(result)
    else:
        _human_output(result)

    return 0 if result.decision == DECISION_READY else 1


if __name__ == "__main__":
    sys.exit(main())
