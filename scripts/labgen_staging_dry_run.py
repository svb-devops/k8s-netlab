#!/usr/bin/env python3
"""
LabGen Staging Deployment Dry Run
===================================
Validates a staging-like environment configuration and optionally probes
live HTTP endpoints to confirm service readiness.

Guarantees:
  - Never connects to real K3s, Proxmox, or LLM providers.
  - Never calls destructive endpoints (POST /seed, /publish, /start, /complete, /abort).
  - Never prints secret values (lengths and presence only).
  - Offline-only by default; HTTP probes opt-in via --base-url.
  - No external runtime dependencies (stdlib only + sibling preflight module).

Usage:
  # Offline env check only
  python scripts/labgen_staging_dry_run.py \\
      --env-file deploy/labgen/.env.staging.example

  # Offline check + live HTTP probes
  python scripts/labgen_staging_dry_run.py \\
      --env-file deploy/labgen/.env.staging.example \\
      --base-url http://localhost:8000

  # Machine-readable output
  python scripts/labgen_staging_dry_run.py --env-file ... --json

  # Also verify demo-seed endpoint is admin-gated (does NOT run the seed)
  python scripts/labgen_staging_dry_run.py \\
      --env-file ... --base-url ... --allow-demo-seed-check

Exit codes:
  0  All required checks pass (warnings may be present).
  1  One or more blocking issues detected.
  2  Env file not found or unreadable.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

# ---------------------------------------------------------------------------
# Import sibling preflight module
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import labgen_production_preflight as _pf  # noqa: E402

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

_SEV_PASS = "pass"
_SEV_WARN = "warning"
_SEV_BLOCK = "blocking"

# Phases
_PHASE_ENV = "env_load"
_PHASE_PREFLIGHT = "preflight"
_PHASE_ENDPOINTS = "endpoints"


@dataclass
class DryRunCheck:
    phase: str
    name: str
    severity: str      # "pass" | "warning" | "blocking"
    message: str
    detail: Optional[str] = None


@dataclass
class DryRunReport:
    checks: list[DryRunCheck] = field(default_factory=list)
    overall: str = _SEV_PASS

    def add(self, check: DryRunCheck) -> None:
        self.checks.append(check)
        if check.severity == _SEV_BLOCK:
            self.overall = _SEV_BLOCK
        elif check.severity == _SEV_WARN and self.overall == _SEV_PASS:
            self.overall = _SEV_WARN

    def blocking_count(self) -> int:
        return sum(1 for c in self.checks if c.severity == _SEV_BLOCK)

    def warning_count(self) -> int:
        return sum(1 for c in self.checks if c.severity == _SEV_WARN)

    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.severity == _SEV_PASS)

    def checks_in_phase(self, phase: str) -> list[DryRunCheck]:
        return [c for c in self.checks if c.phase == phase]


# ---------------------------------------------------------------------------
# HTTP client type
# ---------------------------------------------------------------------------

# (status_code, body_text, error_message_or_None)
HttpGetResult = Tuple[int, str, Optional[str]]
HttpGetFn = Callable[[str, dict], HttpGetResult]


def _default_http_get(url: str, headers: dict) -> HttpGetResult:
    """Stdlib urllib GET with 10s timeout."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body, None
    except Exception as e:
        return 0, "", str(e)


# ---------------------------------------------------------------------------
# Env file loader
# ---------------------------------------------------------------------------


def load_env_file(path: str) -> tuple[dict[str, str], Optional[str]]:
    """Parse KEY=VALUE env file. Return (vars_dict, error_or_None).

    Skips blank lines and lines starting with #.
    Commented-out assignments (# KEY=VALUE) are correctly ignored.
    """
    try:
        result: dict[str, str] = {}
        with open(path) as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                key = key.strip()
                if key:
                    result[key] = value
        return result, None
    except FileNotFoundError:
        return {}, f"Env file not found: {path!r}"
    except OSError as e:
        return {}, f"Cannot read env file {path!r}: {e.strerror}"


# ---------------------------------------------------------------------------
# Sensitive pattern scanner
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = [
    ("sk-ant-", "Anthropic API key prefix"),
    ("sk-proj-", "OpenAI project key prefix"),
    ("-----BEGIN", "PEM private key / certificate header"),
    ("client-certificate-data:", "kubeconfig client-certificate field"),
    ("client-key-data:", "kubeconfig client-key field"),
]


def _scan_for_secrets(text: str) -> list[str]:
    """Return list of human-readable descriptions of patterns found."""
    return [desc for pat, desc in _SENSITIVE_PATTERNS if pat in text]


# ---------------------------------------------------------------------------
# Env context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _env_context(env_vars: dict[str, str]):
    """Temporarily apply env_vars to os.environ, restore on exit."""
    old: dict[str, Optional[str]] = {}
    for k, v in env_vars.items():
        old[k] = os.environ.get(k)
        if v:
            os.environ[k] = v
        elif k in os.environ:
            del os.environ[k]
    try:
        yield
    finally:
        for k, old_v in old.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v


# ---------------------------------------------------------------------------
# HTTP endpoint checks
# ---------------------------------------------------------------------------

# (check_name, path, requires_admin_token, description)
_SAFE_GET_CHECKS = [
    ("health", "/api/health", False, "health endpoint"),
    ("openapi", "/openapi.json", False, "OpenAPI schema"),
    ("frontend_root", "/", False, "frontend root"),
    ("contract_pack", "/api/labgen/contract-pack", True, "LabGen contract pack"),
    ("runtime_adapter_status", "/api/labgen/runtime/adapter-status", True, "runtime adapter status"),
    ("llm_provider_status", "/api/labgen/llm-provider/status", True, "LLM provider status"),
]

# Endpoints that must NEVER be called during dry run (not even for probing)
_FORBIDDEN_PATHS = {
    "/api/labgen/seed/demo",     # POST — demo seed (destructive)
    "/api/labgen/drafts",        # POST — create draft
    "/api/lab-sessions",         # POST — start session
    "/api/labgen/runtime/expire-sessions",  # POST — expire sessions
}


def _run_endpoint_checks(
    report: DryRunReport,
    base_url: str,
    admin_token: str,
    allow_demo_seed_check: bool,
    http_get: HttpGetFn,
) -> None:
    """Run safe GET endpoint probes. Never calls destructive endpoints."""
    admin_headers: dict[str, str] = {}
    if admin_token:
        admin_headers["X-Admin-Token"] = admin_token

    for name, path, needs_admin, desc in _SAFE_GET_CHECKS:
        url = base_url + path
        headers = admin_headers if needs_admin else {}
        status, body, err = http_get(url, headers)

        if err:
            report.add(DryRunCheck(
                phase=_PHASE_ENDPOINTS,
                name=f"endpoint_{name}",
                severity=_SEV_WARN,
                message=f"{desc}: network error",
                detail=err,
            ))
            continue

        # Admin endpoint with no token: 401/403/503 are all expected
        if needs_admin and not admin_token and status in (401, 403, 503):
            report.add(DryRunCheck(
                phase=_PHASE_ENDPOINTS,
                name=f"endpoint_{name}",
                severity=_SEV_PASS,
                message=f"{desc}: {status} (no admin token — expected, not a failure)",
            ))
            continue

        # Health endpoint connecting to Proxmox may fail in staging
        if name == "health" and status not in range(200, 300):
            report.add(DryRunCheck(
                phase=_PHASE_ENDPOINTS,
                name=f"endpoint_{name}",
                severity=_SEV_WARN,
                message=f"{desc}: {status} — may require Proxmox connectivity",
                detail="Health endpoint connects to Proxmox. In staging without Proxmox, 500 is expected.",
            ))
            continue

        if status in range(200, 300):
            # Scan response body for leaked secrets
            hits = _scan_for_secrets(body)
            if hits:
                report.add(DryRunCheck(
                    phase=_PHASE_ENDPOINTS,
                    name=f"endpoint_{name}_secret_leak",
                    severity=_SEV_BLOCK,
                    message=f"{desc}: sensitive data pattern in response body",
                    detail=f"Patterns detected: {hits}",
                ))
            else:
                report.add(DryRunCheck(
                    phase=_PHASE_ENDPOINTS,
                    name=f"endpoint_{name}",
                    severity=_SEV_PASS,
                    message=f"{desc}: {status} OK (no sensitive patterns detected)",
                ))
        else:
            report.add(DryRunCheck(
                phase=_PHASE_ENDPOINTS,
                name=f"endpoint_{name}",
                severity=_SEV_WARN,
                message=f"{desc}: unexpected status {status}",
            ))

    if allow_demo_seed_check:
        _check_demo_seed_gate(report, base_url, http_get)


def _check_demo_seed_gate(
    report: DryRunReport,
    base_url: str,
    http_get: HttpGetFn,
) -> None:
    """Verify demo seed endpoint is admin-gated WITHOUT running it.

    Sends GET (not POST) to /api/labgen/seed/demo without auth.
    Expects 405 (method not allowed) or 401/403/503 (auth guard).
    A 2xx response would mean the endpoint is unprotected — BLOCKING.
    """
    url = base_url + "/api/labgen/seed/demo"
    status, _body, err = http_get(url, {})

    if err:
        report.add(DryRunCheck(
            phase=_PHASE_ENDPOINTS,
            name="demo_seed_admin_gate",
            severity=_SEV_WARN,
            message="demo seed gate check: network error (check skipped)",
            detail=err,
        ))
        return

    if status in range(200, 300):
        report.add(DryRunCheck(
            phase=_PHASE_ENDPOINTS,
            name="demo_seed_admin_gate",
            severity=_SEV_BLOCK,
            message=f"demo seed endpoint returned {status} without auth — endpoint is NOT admin-gated",
            detail="Expected 405 (method not allowed via GET) or 401/403 (auth required).",
        ))
    elif status == 404:
        report.add(DryRunCheck(
            phase=_PHASE_ENDPOINTS,
            name="demo_seed_admin_gate",
            severity=_SEV_WARN,
            message="demo seed endpoint returned 404 — endpoint may not be deployed yet",
            detail="Expected 405 (method not allowed) if the endpoint is deployed. 404 means the route does not exist.",
        ))
    else:
        # 405 = method not allowed (correct), 401/403/503 = auth guard active
        report.add(DryRunCheck(
            phase=_PHASE_ENDPOINTS,
            name="demo_seed_admin_gate",
            severity=_SEV_PASS,
            message=f"demo seed endpoint returned {status} without auth — "
                    f"{'method guard active (POST only)' if status == 405 else 'auth gate active'}",
        ))


# ---------------------------------------------------------------------------
# Core dry run runner
# ---------------------------------------------------------------------------


def run_dry_run(
    *,
    env_vars: dict[str, str],
    base_url: Optional[str] = None,
    allow_demo_seed_check: bool = False,
    http_get: HttpGetFn = _default_http_get,
) -> DryRunReport:
    """Execute dry run checks.

    Temporarily applies env_vars to os.environ, runs preflight,
    and optionally probes HTTP endpoints.

    Args:
        env_vars:              Pre-parsed environment variables.
        base_url:              If provided, run HTTP endpoint probes against this base URL.
        allow_demo_seed_check: If True, verify demo seed endpoint is admin-gated (GET only).
        http_get:              Injectable HTTP client for testing.

    Returns:
        DryRunReport with all check results.
    """
    report = DryRunReport()

    with _env_context(env_vars):
        # Phase: preflight
        pf_report = _pf.run_preflight()
        for check in pf_report.checks:
            report.add(DryRunCheck(
                phase=_PHASE_PREFLIGHT,
                name=check.name,
                severity=check.severity,
                message=check.message,
                detail=check.detail,
            ))

        # Phase: endpoint checks (only if base_url provided)
        if base_url:
            admin_token = env_vars.get("ADMIN_TOKEN", "")
            _run_endpoint_checks(
                report=report,
                base_url=base_url.rstrip("/"),
                admin_token=admin_token,
                allow_demo_seed_check=allow_demo_seed_check,
                http_get=http_get,
            )

    return report


def run_from_env_file(
    env_file_path: str,
    *,
    base_url: Optional[str] = None,
    allow_demo_seed_check: bool = False,
    http_get: HttpGetFn = _default_http_get,
) -> DryRunReport:
    """Load env file and run dry run. Returns structured report even on file error."""
    report = DryRunReport()

    env_vars, err = load_env_file(env_file_path)
    if err:
        report.add(DryRunCheck(
            phase=_PHASE_ENV,
            name="env_file_loaded",
            severity=_SEV_BLOCK,
            message=err,
        ))
        return report

    report.add(DryRunCheck(
        phase=_PHASE_ENV,
        name="env_file_loaded",
        severity=_SEV_PASS,
        message=f"Env file loaded: {len(env_vars)} variables (secrets not printed)",
    ))

    sub = run_dry_run(
        env_vars=env_vars,
        base_url=base_url,
        allow_demo_seed_check=allow_demo_seed_check,
        http_get=http_get,
    )
    for check in sub.checks:
        report.add(check)

    return report


# ---------------------------------------------------------------------------
# Output
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
    _PHASE_ENDPOINTS: "Endpoints",
}


def _human_output(report: DryRunReport) -> None:
    print("LabGen Staging Deployment Dry Run")
    print("=" * 50)
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
    print(f"Checks: {report.pass_count()} passed, "
          f"{report.warning_count()} warnings, "
          f"{report.blocking_count()} blocking")
    overall_color = _COLORS.get(report.overall, "")
    print(f"{overall_color}Overall: {report.overall.upper()}{_RESET}")

    if report.blocking_count() > 0:
        print()
        print("DRY RUN FAILED — fix blocking issues before staging deployment.")
    elif report.warning_count() > 0:
        print()
        print("DRY RUN PASSED WITH WARNINGS — review warnings before proceeding.")
    else:
        print()
        print("DRY RUN PASSED.")


def _json_output(report: DryRunReport) -> None:
    phases_seen: list[str] = []
    for c in report.checks:
        if c.phase not in phases_seen:
            phases_seen.append(c.phase)

    out = {
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


def main() -> int:
    args = sys.argv[1:]

    use_json = "--json" in args
    allow_demo_seed_check = "--allow-demo-seed-check" in args

    # --env-file
    env_file: Optional[str] = None
    if "--env-file" in args:
        idx = args.index("--env-file")
        if idx + 1 < len(args):
            env_file = args[idx + 1]
        else:
            print("Error: --env-file requires a path argument", file=sys.stderr)
            return 2

    # --base-url
    base_url: Optional[str] = None
    if "--base-url" in args:
        idx = args.index("--base-url")
        if idx + 1 < len(args):
            base_url = args[idx + 1]
        else:
            print("Error: --base-url requires a URL argument", file=sys.stderr)
            return 2

    if env_file:
        report = run_from_env_file(
            env_file,
            base_url=base_url,
            allow_demo_seed_check=allow_demo_seed_check,
        )
    else:
        # No env file: run against current environment
        report = run_dry_run(
            env_vars={},
            base_url=base_url,
            allow_demo_seed_check=allow_demo_seed_check,
        )

    if use_json:
        _json_output(report)
    else:
        _human_output(report)

    return 0 if report.blocking_count() == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
