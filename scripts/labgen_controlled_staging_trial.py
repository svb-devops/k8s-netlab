#!/usr/bin/env python3
"""
LabGen Controlled Staging Trial Helper
=======================================
Validates a staging environment and optionally runs controlled trial phases
(runtime start, timeout expiry dry run, cleanup check).

Guarantees:
  - Never connects to real K3s / Proxmox / LLM in default mode.
  - Default mode: safe GET diagnostics only (no POST).
  - POST phases require explicit allow flags (--allow-runtime-start,
    --allow-timeout-expiry, --allow-cleanup-check).
  - Never calls demo seed / publish / generate endpoints.
  - Never prints secret values.
  - All HTTP responses scanned for sensitive patterns.
  - No external network required (http_get / http_post are injectable).

Usage:
  # Offline preflight only
  python scripts/labgen_controlled_staging_trial.py \\
      --env-file deploy/labgen/.env.staging.example

  # Diagnostics only (safe GET probes)
  python scripts/labgen_controlled_staging_trial.py \\
      --env-file deploy/labgen/.env.staging.example \\
      --base-url http://<staging-host>:8000

  # With controlled runtime start
  python scripts/labgen_controlled_staging_trial.py \\
      --env-file .env.staging \\
      --base-url http://<staging-host>:8000 \\
      --allow-runtime-start \\
      --staging-lab-draft-id <published-lab-id>

  # With timeout expiry dry run (admin, dry_run=true — no mutation)
  python scripts/labgen_controlled_staging_trial.py \\
      --env-file .env.staging \\
      --base-url http://<staging-host>:8000 \\
      --allow-timeout-expiry

  # JSON output for CI
  python scripts/labgen_controlled_staging_trial.py --env-file ... --json

Exit codes:
  0  All required checks pass (warnings may be present).
  1  One or more blocking issues detected.
  2  Env file not found or unreadable.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Callable, Optional, Tuple

# ---------------------------------------------------------------------------
# Import sibling modules
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import labgen_production_preflight as _pf  # noqa: E402
import labgen_staging_dry_run as _dry  # noqa: E402

# ---------------------------------------------------------------------------
# Phase constants (extends dry-run phases)
# ---------------------------------------------------------------------------

_PHASE_ENV = _dry._PHASE_ENV
_PHASE_PREFLIGHT = _dry._PHASE_PREFLIGHT
_PHASE_DIAGNOSTICS = "diagnostics"
_PHASE_RUNTIME = "runtime"
_PHASE_EXPIRY = "expiry"
_PHASE_CLEANUP = "cleanup"

_SEV_PASS = _dry._SEV_PASS
_SEV_WARN = _dry._SEV_WARN
_SEV_BLOCK = _dry._SEV_BLOCK

# Reuse check / report types from dry run (identical structure)
TrialCheck = _dry.DryRunCheck
TrialReport = _dry.DryRunReport

# Reuse HTTP GET type
HttpGetFn = _dry.HttpGetFn

# HTTP POST type: (url, headers, json_body) -> (status_code, body, error_or_None)
HttpPostResult = Tuple[int, str, Optional[str]]
HttpPostFn = Callable[[str, dict, dict], HttpPostResult]

# ---------------------------------------------------------------------------
# HTTP POST client
# ---------------------------------------------------------------------------


def _default_http_post(url: str, headers: dict, body: dict) -> HttpPostResult:
    """Stdlib urllib POST with 10-second timeout."""
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return e.code, body_text, None
    except Exception as e:
        return 0, "", str(e)


# ---------------------------------------------------------------------------
# Safe diagnostics checks (identical allowlist to dry run)
# ---------------------------------------------------------------------------

# (name, path, needs_admin_token, description)
_SAFE_DIAGNOSTICS_CHECKS = _dry._SAFE_GET_CHECKS

# Endpoints that MUST NEVER be called during any phase of this script
_FORBIDDEN_POST_PATHS = {
    "/api/labgen/seed/demo",        # demo seed (destructive)
    "/api/labgen/drafts",           # draft create (destructive)
    "/api/labgen/generate",         # LLM generation
    "/api/lab-drafts/generate",     # LLM generation
    "/api/labgen/llm-provider/dry-run",  # LLM dry run
}

# POST endpoints allowed only with explicit flags
_GATED_POST_PATHS = {
    "/api/lab-sessions",                        # --allow-runtime-start
    "/api/labgen/runtime/expire-sessions",      # --allow-timeout-expiry
    # /api/lab-sessions/{id}/complete            # --allow-cleanup-check (path prefix)
    # /api/lab-sessions/{id}/abort               # --allow-cleanup-check (path prefix)
}


# ---------------------------------------------------------------------------
# Phase: diagnostics
# ---------------------------------------------------------------------------


def _run_diagnostics_phase(
    report: TrialReport,
    base_url: str,
    admin_token: str,
    http_get: HttpGetFn,
) -> dict:
    """Run safe GET diagnostics; parse adapter and LLM status for safety gates.

    Returns:
        dict with keys:
          "adapter_production_safe": True | False | None (None = not parseable)
          "llm_live_enabled":        True | False | None
    """
    admin_headers: dict[str, str] = {"X-Admin-Token": admin_token} if admin_token else {}
    metadata: dict = {"adapter_production_safe": None, "llm_live_enabled": None}

    for name, path, needs_admin, desc in _SAFE_DIAGNOSTICS_CHECKS:
        url = base_url + path
        headers = admin_headers if needs_admin else {}
        status, body, err = http_get(url, headers)

        if err:
            report.add(TrialCheck(
                phase=_PHASE_DIAGNOSTICS,
                name=f"diag_{name}",
                severity=_SEV_WARN,
                message=f"{desc}: network error",
                detail=err,
            ))
            continue

        # Admin endpoint, no token supplied: 401/403/503 are expected
        if needs_admin and not admin_token and status in (401, 403, 503):
            report.add(TrialCheck(
                phase=_PHASE_DIAGNOSTICS,
                name=f"diag_{name}",
                severity=_SEV_PASS,
                message=f"{desc}: {status} (no admin token — expected for staging without credentials)",
            ))
            continue

        # Health connects to Proxmox — may fail in staging without Proxmox
        if name == "health" and status not in range(200, 300):
            report.add(TrialCheck(
                phase=_PHASE_DIAGNOSTICS,
                name=f"diag_{name}",
                severity=_SEV_WARN,
                message=f"{desc}: {status} — expected if staging has no Proxmox",
                detail="Health endpoint requires Proxmox connectivity. 5xx is acceptable in staging.",
            ))
            continue

        if status in range(200, 300):
            hits = _dry._scan_for_secrets(body)
            if hits:
                report.add(TrialCheck(
                    phase=_PHASE_DIAGNOSTICS,
                    name=f"diag_{name}_secret_leak",
                    severity=_SEV_BLOCK,
                    message=f"{desc}: sensitive data pattern in response body",
                    detail=f"Patterns detected: {hits}",
                ))
            else:
                report.add(TrialCheck(
                    phase=_PHASE_DIAGNOSTICS,
                    name=f"diag_{name}",
                    severity=_SEV_PASS,
                    message=f"{desc}: {status} OK (no sensitive patterns)",
                ))

            # Parse adapter-status for safety gate
            if name == "runtime_adapter_status":
                try:
                    data = json.loads(body)
                    production_safe = data.get("production_safe")
                    adapter_kind = data.get("namespace_adapter_kind", "unknown")
                    metadata["adapter_production_safe"] = production_safe

                    if production_safe is False:
                        report.add(TrialCheck(
                            phase=_PHASE_DIAGNOSTICS,
                            name="adapter_safety_gate",
                            severity=_SEV_BLOCK,
                            message=(
                                f"Runtime adapter not production-safe: "
                                f"namespace_adapter_kind={adapter_kind!r}, production_safe=false"
                            ),
                            detail=(
                                "Stub adapter in production mode is blocked by Gap 1 guard. "
                                "Set LABGEN_NAMESPACE_ADAPTER=k8s for K3s staging trials."
                            ),
                        ))
                    elif adapter_kind == "stub":
                        report.add(TrialCheck(
                            phase=_PHASE_DIAGNOSTICS,
                            name="adapter_safety_gate",
                            severity=_SEV_BLOCK,
                            message=f"Stub adapter detected: namespace_adapter_kind={adapter_kind!r}",
                            detail=(
                                "Controlled staging trial requires k8s adapter, not stub. "
                                "Set LABGEN_NAMESPACE_ADAPTER=k8s."
                            ),
                        ))
                    else:
                        report.add(TrialCheck(
                            phase=_PHASE_DIAGNOSTICS,
                            name="adapter_safety_gate",
                            severity=_SEV_PASS,
                            message=f"Adapter safety gate: {adapter_kind!r}, production_safe={production_safe}",
                        ))
                except (json.JSONDecodeError, AttributeError):
                    report.add(TrialCheck(
                        phase=_PHASE_DIAGNOSTICS,
                        name="adapter_safety_gate",
                        severity=_SEV_WARN,
                        message="Could not parse adapter-status response as JSON",
                    ))

            # Parse llm-provider/status for live-mode gate
            if name == "llm_provider_status":
                try:
                    data = json.loads(body)
                    live_enabled = data.get("live_enabled")
                    metadata["llm_live_enabled"] = live_enabled

                    if live_enabled is True:
                        report.add(TrialCheck(
                            phase=_PHASE_DIAGNOSTICS,
                            name="llm_live_gate",
                            severity=_SEV_BLOCK,
                            message="LLM live_enabled=true detected — live LLM must not be active in staging trial",
                            detail=(
                                "Set LABGEN_LLM_PROVIDER_MODE=fake_only or disabled. "
                                "Live LLM calls are not permitted in controlled staging trial."
                            ),
                        ))
                    else:
                        report.add(TrialCheck(
                            phase=_PHASE_DIAGNOSTICS,
                            name="llm_live_gate",
                            severity=_SEV_PASS,
                            message=f"LLM live gate: live_enabled={live_enabled!r} (not live)",
                        ))
                except (json.JSONDecodeError, AttributeError):
                    report.add(TrialCheck(
                        phase=_PHASE_DIAGNOSTICS,
                        name="llm_live_gate",
                        severity=_SEV_WARN,
                        message="Could not parse llm-provider/status response as JSON",
                    ))
        else:
            report.add(TrialCheck(
                phase=_PHASE_DIAGNOSTICS,
                name=f"diag_{name}",
                severity=_SEV_WARN,
                message=f"{desc}: unexpected status {status}",
            ))

    return metadata


# ---------------------------------------------------------------------------
# Phase: runtime start
# ---------------------------------------------------------------------------


def _run_runtime_start(
    report: TrialReport,
    base_url: str,
    admin_token: str,
    user_session: str,
    lab_draft_id: str,
    http_post: HttpPostFn,
) -> Optional[str]:
    """POST /api/lab-sessions for controlled trial. Returns session_id if created."""
    if not user_session:
        # POST /api/lab-sessions requires user session cookie auth — admin token alone is not valid.
        # Fail closed: do not send a request that will return 401/403 and could reach the server.
        report.add(TrialCheck(
            phase=_PHASE_RUNTIME,
            name="runtime_start",
            severity=_SEV_BLOCK,
            message="Runtime start blocked: STAGING_USER_SESSION is required for POST /api/lab-sessions",
            detail=(
                "POST /api/lab-sessions requires user session cookie authentication. "
                "Set STAGING_USER_SESSION in env vars to the session cookie value from "
                "a logged-in staging test account. X-Admin-Token alone is not sufficient."
            ),
        ))
        return None

    url = f"{base_url}/api/lab-sessions"
    headers: dict[str, str] = {"Cookie": f"session={user_session}"}

    status, body, err = http_post(url, headers, {"lab_draft_id": lab_draft_id})

    if err:
        report.add(TrialCheck(
            phase=_PHASE_RUNTIME,
            name="runtime_start",
            severity=_SEV_WARN,
            message="Runtime start: network error",
            detail=err,
        ))
        return None

    hits = _dry._scan_for_secrets(body)
    if hits:
        report.add(TrialCheck(
            phase=_PHASE_RUNTIME,
            name="runtime_start_secret_leak",
            severity=_SEV_BLOCK,
            message="Runtime start response contains sensitive data pattern",
            detail=f"Patterns detected: {hits}",
        ))
        return None

    if status == 201:
        session_id: Optional[str] = None
        try:
            data = json.loads(body)
            session_id = data.get("id") or data.get("session_id")
        except json.JSONDecodeError:
            pass
        report.add(TrialCheck(
            phase=_PHASE_RUNTIME,
            name="runtime_start",
            severity=_SEV_PASS,
            message="Lab session created: 201 (session_id recorded, secrets not printed)",
        ))
        return session_id

    if status in (401, 403):
        report.add(TrialCheck(
            phase=_PHASE_RUNTIME,
            name="runtime_start",
            severity=_SEV_BLOCK,
            message=f"Runtime start: {status} — user session authentication required",
            detail=(
                "POST /api/lab-sessions requires authenticated user (session cookie). "
                "Set STAGING_USER_SESSION in env vars to the session cookie value from "
                "a logged-in staging test account."
            ),
        ))
        return None

    if status == 422:
        report.add(TrialCheck(
            phase=_PHASE_RUNTIME,
            name="runtime_start",
            severity=_SEV_WARN,
            message="Runtime start: 422 — preconditions not met",
            detail=(
                "Possible causes: no VM assigned to test account, VM tainted, "
                "K3sNamespaceLifecycleAdapter not yet implemented (NotImplementedError). "
                "422 is expected in staging without a fully configured K3s + VM environment. "
                "See CONTROLLED_STAGING_TRIAL_v0.1.md Section D for pass/fail criteria."
            ),
        ))
        return None

    report.add(TrialCheck(
        phase=_PHASE_RUNTIME,
        name="runtime_start",
        severity=_SEV_WARN,
        message=f"Runtime start: unexpected status {status}",
    ))
    return None


# ---------------------------------------------------------------------------
# Phase: timeout expiry (dry run only, admin)
# ---------------------------------------------------------------------------


def _run_expiry_dry_run(
    report: TrialReport,
    base_url: str,
    admin_token: str,
    http_post: HttpPostFn,
) -> None:
    """POST /api/labgen/runtime/expire-sessions with dry_run=true (admin, no mutation)."""
    url = f"{base_url}/api/labgen/runtime/expire-sessions"
    headers: dict[str, str] = {"X-Admin-Token": admin_token} if admin_token else {}

    status, body, err = http_post(url, headers, {"dry_run": True, "limit": 1})

    if err:
        report.add(TrialCheck(
            phase=_PHASE_EXPIRY,
            name="expiry_dry_run",
            severity=_SEV_WARN,
            message="Expiry dry run: network error",
            detail=err,
        ))
        return

    hits = _dry._scan_for_secrets(body)
    if hits:
        report.add(TrialCheck(
            phase=_PHASE_EXPIRY,
            name="expiry_dry_run_secret_leak",
            severity=_SEV_BLOCK,
            message="Expiry dry run response contains sensitive data",
            detail=f"Patterns detected: {hits}",
        ))
        return

    if status in range(200, 300):
        report.add(TrialCheck(
            phase=_PHASE_EXPIRY,
            name="expiry_dry_run",
            severity=_SEV_PASS,
            message=f"Expiry dry run (dry_run=true, limit=1): {status} OK — no sessions mutated",
        ))
    elif status in (401, 403):
        report.add(TrialCheck(
            phase=_PHASE_EXPIRY,
            name="expiry_dry_run",
            severity=_SEV_BLOCK,
            message=f"Expiry dry run: {status} — ADMIN_TOKEN required",
            detail="Set ADMIN_TOKEN in env vars (≥ 32 characters).",
        ))
    else:
        report.add(TrialCheck(
            phase=_PHASE_EXPIRY,
            name="expiry_dry_run",
            severity=_SEV_WARN,
            message=f"Expiry dry run: unexpected status {status}",
        ))


# ---------------------------------------------------------------------------
# Phase: cleanup check
# ---------------------------------------------------------------------------


def _run_cleanup_check(
    report: TrialReport,
    base_url: str,
    admin_token: str,
    user_session: str,
    session_id: str,
    http_post: HttpPostFn,
) -> None:
    """POST /api/lab-sessions/{id}/complete to exercise cleanup path."""
    url = f"{base_url}/api/lab-sessions/{session_id}/complete"
    headers: dict[str, str] = {}
    if user_session:
        headers["Cookie"] = f"session={user_session}"
    elif admin_token:
        headers["X-Admin-Token"] = admin_token

    status, body, err = http_post(url, headers, {})

    if err:
        report.add(TrialCheck(
            phase=_PHASE_CLEANUP,
            name="cleanup_complete",
            severity=_SEV_WARN,
            message="Cleanup complete: network error",
            detail=err,
        ))
        return

    hits = _dry._scan_for_secrets(body)
    if hits:
        report.add(TrialCheck(
            phase=_PHASE_CLEANUP,
            name="cleanup_complete_secret_leak",
            severity=_SEV_BLOCK,
            message="Cleanup response contains sensitive data",
            detail=f"Patterns detected: {hits}",
        ))
        return

    if status in range(200, 300):
        report.add(TrialCheck(
            phase=_PHASE_CLEANUP,
            name="cleanup_complete",
            severity=_SEV_PASS,
            message=f"Cleanup complete: {status} OK",
        ))
    elif status == 409:
        report.add(TrialCheck(
            phase=_PHASE_CLEANUP,
            name="cleanup_complete",
            severity=_SEV_WARN,
            message="Cleanup complete: 409 — session not ready to complete (steps not finished)",
            detail=(
                "Expected if the session was just created and no lab steps were verified. "
                "Use /abort instead, or complete all lab steps first."
            ),
        ))
    elif status in (401, 403):
        report.add(TrialCheck(
            phase=_PHASE_CLEANUP,
            name="cleanup_complete",
            severity=_SEV_BLOCK,
            message=f"Cleanup complete: {status} — user session authentication required",
            detail="Set STAGING_USER_SESSION in env vars.",
        ))
    else:
        report.add(TrialCheck(
            phase=_PHASE_CLEANUP,
            name="cleanup_complete",
            severity=_SEV_WARN,
            message=f"Cleanup complete: unexpected status {status}",
        ))


# ---------------------------------------------------------------------------
# Core trial runner
# ---------------------------------------------------------------------------


def run_trial(
    *,
    env_vars: dict[str, str],
    base_url: Optional[str] = None,
    allow_runtime_start: bool = False,
    allow_timeout_expiry: bool = False,
    allow_cleanup_check: bool = False,
    staging_lab_draft_id: Optional[str] = None,
    staging_session_id: Optional[str] = None,
    http_get: HttpGetFn = _dry._default_http_get,
    http_post: HttpPostFn = _default_http_post,
) -> TrialReport:
    """Execute controlled staging trial checks.

    Default mode (no allow flags): static preflight + safe GET diagnostics.
    POST phases require explicit allow flags AND base_url.

    Args:
        env_vars:              Pre-parsed environment variables.
        base_url:              If provided, run HTTP probes against this base URL.
        allow_runtime_start:   If True, POST /api/lab-sessions (requires staging_lab_draft_id).
        allow_timeout_expiry:  If True, POST /api/labgen/runtime/expire-sessions (dry_run=True).
        allow_cleanup_check:   If True, POST /api/lab-sessions/{id}/complete.
        staging_lab_draft_id:  Published lab draft ID for controlled runtime start.
        staging_session_id:    Existing session ID for cleanup check.
        http_get:              Injectable GET client.
        http_post:             Injectable POST client.

    Returns:
        TrialReport with all check results across all phases.
    """
    report = TrialReport()

    with _dry._env_context(env_vars):
        # Always: static preflight
        pf = _pf.run_preflight()
        for check in pf.checks:
            report.add(TrialCheck(
                phase=_PHASE_PREFLIGHT,
                name=check.name,
                severity=check.severity,
                message=check.message,
                detail=check.detail,
            ))

        admin_token = env_vars.get("ADMIN_TOKEN", "")
        user_session = env_vars.get("STAGING_USER_SESSION", "")

        # Diagnostics phase (if base_url provided)
        metadata: dict = {}
        if base_url:
            metadata = _run_diagnostics_phase(
                report,
                base_url=base_url.rstrip("/"),
                admin_token=admin_token,
                http_get=http_get,
            )

        # Runtime start phase
        runtime_session_id: Optional[str] = None
        if allow_runtime_start:
            if not base_url:
                report.add(TrialCheck(
                    phase=_PHASE_RUNTIME,
                    name="runtime_start",
                    severity=_SEV_BLOCK,
                    message="Runtime start blocked: --base-url is required with --allow-runtime-start",
                ))
            elif not staging_lab_draft_id:
                report.add(TrialCheck(
                    phase=_PHASE_RUNTIME,
                    name="runtime_start",
                    severity=_SEV_BLOCK,
                    message=(
                        "Runtime start blocked: --staging-lab-draft-id is required "
                        "with --allow-runtime-start"
                    ),
                    detail="Provide the published lab draft ID to use for the controlled staging session.",
                ))
            elif metadata.get("adapter_production_safe") is not True:
                # Whitelist gate: only proceed if adapter is CONFIRMED production-safe.
                # None means the diagnostics check failed/was not reached — fail closed.
                safe_val = metadata.get("adapter_production_safe")
                report.add(TrialCheck(
                    phase=_PHASE_RUNTIME,
                    name="runtime_start",
                    severity=_SEV_BLOCK,
                    message=(
                        f"Runtime start blocked: adapter safety not confirmed "
                        f"(adapter_production_safe={safe_val!r} — must be True)"
                    ),
                    detail=(
                        "Either the adapter-status endpoint was unreachable/unparseable, "
                        "or production_safe=false. Runtime start requires confirmed safe adapter."
                    ),
                ))
            elif metadata.get("llm_live_enabled") is not False:
                # Whitelist gate: only proceed if LLM is CONFIRMED not live.
                # None means the diagnostics check failed/was not reached — fail closed.
                live_val = metadata.get("llm_live_enabled")
                report.add(TrialCheck(
                    phase=_PHASE_RUNTIME,
                    name="runtime_start",
                    severity=_SEV_BLOCK,
                    message=(
                        f"Runtime start blocked: LLM live status not confirmed safe "
                        f"(llm_live_enabled={live_val!r} — must be False)"
                    ),
                    detail=(
                        "Either the llm-provider/status endpoint was unreachable/unparseable, "
                        "or live_enabled=true. Runtime start requires confirmed live_enabled=false."
                    ),
                ))
            else:
                runtime_session_id = _run_runtime_start(
                    report,
                    base_url=base_url.rstrip("/"),
                    admin_token=admin_token,
                    user_session=user_session,
                    lab_draft_id=staging_lab_draft_id,
                    http_post=http_post,
                )

        # Expiry phase
        if allow_timeout_expiry:
            if not base_url:
                report.add(TrialCheck(
                    phase=_PHASE_EXPIRY,
                    name="expiry_dry_run",
                    severity=_SEV_BLOCK,
                    message="Expiry check blocked: --base-url is required with --allow-timeout-expiry",
                ))
            else:
                _run_expiry_dry_run(
                    report,
                    base_url=base_url.rstrip("/"),
                    admin_token=admin_token,
                    http_post=http_post,
                )

        # Cleanup phase
        if allow_cleanup_check:
            effective_session = staging_session_id or runtime_session_id
            if not base_url:
                report.add(TrialCheck(
                    phase=_PHASE_CLEANUP,
                    name="cleanup_complete",
                    severity=_SEV_BLOCK,
                    message="Cleanup check blocked: --base-url is required with --allow-cleanup-check",
                ))
            elif not effective_session:
                report.add(TrialCheck(
                    phase=_PHASE_CLEANUP,
                    name="cleanup_complete",
                    severity=_SEV_BLOCK,
                    message=(
                        "Cleanup check blocked: --staging-session-id is required "
                        "with --allow-cleanup-check (or combine with --allow-runtime-start "
                        "to use the newly created session)"
                    ),
                    detail="Provide an existing staging session ID, or use --allow-runtime-start first.",
                ))
            else:
                _run_cleanup_check(
                    report,
                    base_url=base_url.rstrip("/"),
                    admin_token=admin_token,
                    user_session=user_session,
                    session_id=effective_session,
                    http_post=http_post,
                )

    return report


def run_from_env_file(
    env_file_path: str,
    *,
    base_url: Optional[str] = None,
    allow_runtime_start: bool = False,
    allow_timeout_expiry: bool = False,
    allow_cleanup_check: bool = False,
    staging_lab_draft_id: Optional[str] = None,
    staging_session_id: Optional[str] = None,
    http_get: HttpGetFn = _dry._default_http_get,
    http_post: HttpPostFn = _default_http_post,
) -> TrialReport:
    """Load env file and run trial. Returns structured report even on file error."""
    report = TrialReport()
    env_vars, err = _dry.load_env_file(env_file_path)
    if err:
        report.add(TrialCheck(
            phase=_PHASE_ENV,
            name="env_file_loaded",
            severity=_SEV_BLOCK,
            message=err,
        ))
        return report

    report.add(TrialCheck(
        phase=_PHASE_ENV,
        name="env_file_loaded",
        severity=_SEV_PASS,
        message=f"Env file loaded: {len(env_vars)} variables (secrets not printed)",
    ))

    sub = run_trial(
        env_vars=env_vars,
        base_url=base_url,
        allow_runtime_start=allow_runtime_start,
        allow_timeout_expiry=allow_timeout_expiry,
        allow_cleanup_check=allow_cleanup_check,
        staging_lab_draft_id=staging_lab_draft_id,
        staging_session_id=staging_session_id,
        http_get=http_get,
        http_post=http_post,
    )
    for check in sub.checks:
        report.add(check)

    return report


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_ICONS = {_SEV_PASS: "✓", _SEV_WARN: "⚠", _SEV_BLOCK: "✗"}
_COLORS = {
    _SEV_PASS: "\033[92m",
    _SEV_WARN: "\033[93m",
    _SEV_BLOCK: "\033[91m",
}
_RESET = "\033[0m"
_PHASE_LABELS = {
    _PHASE_ENV: "Env Load",
    _PHASE_PREFLIGHT: "Preflight",
    _PHASE_DIAGNOSTICS: "Diagnostics",
    _PHASE_RUNTIME: "Runtime",
    _PHASE_EXPIRY: "Expiry",
    _PHASE_CLEANUP: "Cleanup",
}


def _human_output(report: TrialReport, execution_mode: str) -> None:
    print("LabGen Controlled Staging Trial")
    print(f"Execution mode: {execution_mode}")
    print("=" * 52)
    current_phase = None
    for check in report.checks:
        if check.phase != current_phase:
            current_phase = check.phase
            label = _PHASE_LABELS.get(current_phase, current_phase)
            print(f"\n[{label}]")
        icon = _ICONS.get(check.severity, "?")
        color = _COLORS.get(check.severity, "")
        print(f"  {color}{icon} [{check.name}] {check.message}{_RESET}")
        if check.detail:
            print(f"      → {check.detail}")

    print()
    print(
        f"Checks: {report.pass_count()} passed, "
        f"{report.warning_count()} warnings, "
        f"{report.blocking_count()} blocking"
    )
    overall_color = _COLORS.get(report.overall, "")
    print(f"{overall_color}Overall: {report.overall.upper()}{_RESET}")
    print()
    if report.blocking_count() > 0:
        print("TRIAL BLOCKED — fix blocking issues before proceeding.")
    elif report.warning_count() > 0:
        print("TRIAL READY WITH WARNINGS — review warnings before proceeding.")
    else:
        print("TRIAL CHECKS PASSED.")


def _json_output(report: TrialReport, execution_mode: str) -> None:
    phases_seen: list[str] = []
    for c in report.checks:
        if c.phase not in phases_seen:
            phases_seen.append(c.phase)

    out = {
        "tool": "labgen_controlled_staging_trial",
        "execution_mode": execution_mode,
        "overall": report.overall,
        "pass_count": report.pass_count(),
        "warning_count": report.warning_count(),
        "blocking_count": report.blocking_count(),
        "phases": phases_seen,
        "checks": [
            {
                "phase": c.phase,
                "name": c.name,
                "severity": c.severity,
                "message": c.message,
                **({"detail": c.detail} if c.detail else {}),
            }
            for c in report.checks
        ],
    }
    print(json.dumps(out, indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_flag(args: list[str], flag: str, *, has_value: bool = False) -> tuple:
    """Return (True, value) if flag present, else (False, None)."""
    if flag not in args:
        return False, None
    idx = args.index(flag)
    if has_value:
        if idx + 1 < len(args):
            return True, args[idx + 1]
        return True, None  # flag present but no value
    return True, None


def main() -> int:
    args = sys.argv[1:]

    use_json = "--json" in args
    allow_runtime_start = "--allow-runtime-start" in args
    allow_timeout_expiry = "--allow-timeout-expiry" in args
    allow_cleanup_check = "--allow-cleanup-check" in args

    _, env_file = _parse_flag(args, "--env-file", has_value=True)
    if "--env-file" in args and env_file is None:
        print("Error: --env-file requires a path argument", file=sys.stderr)
        return 2

    _, base_url = _parse_flag(args, "--base-url", has_value=True)
    if "--base-url" in args and base_url is None:
        print("Error: --base-url requires a URL argument", file=sys.stderr)
        return 2

    _, staging_lab_draft_id = _parse_flag(args, "--staging-lab-draft-id", has_value=True)
    _, staging_session_id = _parse_flag(args, "--staging-session-id", has_value=True)

    # Determine execution mode label
    active_flags = []
    if allow_runtime_start:
        active_flags.append("runtime_start")
    if allow_timeout_expiry:
        active_flags.append("timeout_expiry")
    if allow_cleanup_check:
        active_flags.append("cleanup_check")
    execution_mode = "with_" + "+".join(active_flags) if active_flags else "diagnostics_only"

    if env_file:
        report = run_from_env_file(
            env_file,
            base_url=base_url,
            allow_runtime_start=allow_runtime_start,
            allow_timeout_expiry=allow_timeout_expiry,
            allow_cleanup_check=allow_cleanup_check,
            staging_lab_draft_id=staging_lab_draft_id,
            staging_session_id=staging_session_id,
        )
    else:
        report = run_trial(
            env_vars={},
            base_url=base_url,
            allow_runtime_start=allow_runtime_start,
            allow_timeout_expiry=allow_timeout_expiry,
            allow_cleanup_check=allow_cleanup_check,
            staging_lab_draft_id=staging_lab_draft_id,
            staging_session_id=staging_session_id,
        )

    if use_json:
        _json_output(report, execution_mode)
    else:
        _human_output(report, execution_mode)

    return 0 if report.blocking_count() == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
