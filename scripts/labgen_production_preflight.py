#!/usr/bin/env python3
"""
LabGen Production Preflight Check
==================================
Read-only static configuration validator.

Reads environment variables, checks production-readiness requirements,
and reports pass/fail per check.

Guarantees:
  - Never connects to K8s, Proxmox, or any external service.
  - Never reads secret file contents.
  - Never prints secret values.
  - No network calls of any kind.
  - Missing required config → exit code 1 (fail closed).

Exit codes:
  0  All required checks pass (warnings may be present).
  1  One or more blocking issues detected.

Usage:
  python scripts/labgen_production_preflight.py
  python scripts/labgen_production_preflight.py --json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Check result types
# ---------------------------------------------------------------------------

_SEV_PASS = "pass"
_SEV_WARN = "warning"
_SEV_BLOCK = "blocking"


@dataclass
class PreflightCheck:
    name: str
    severity: str          # "pass" | "warning" | "blocking"
    message: str
    detail: Optional[str] = None


@dataclass
class PreflightReport:
    checks: list[PreflightCheck] = field(default_factory=list)
    overall: str = "pass"   # "pass" | "warning" | "blocking"

    def add(self, check: PreflightCheck) -> None:
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


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

_SAFE_RUNTIME_MODES = {"test", "dev", "demo", "production", "home_lab_mvp"}
_SAFE_ADAPTER_KINDS = {"stub", "k8s"}
_SAFE_LLM_MODES = {"disabled", "fake_only", "dry_run", "live_disabled", "live_enabled"}
_UNSAFE_CREDENTIAL_ROOTS = {"", ".", "/", "/tmp", "/var/tmp", "/root"}
_UNSAFE_CREDENTIAL_PREFIXES = ("/tmp/", "/var/tmp/")


def _check_runtime_mode(report: PreflightReport) -> str:
    mode = os.getenv("LABGEN_RUNTIME_MODE", "dev")
    if mode not in _SAFE_RUNTIME_MODES:
        report.add(PreflightCheck(
            name="runtime_mode_valid",
            severity=_SEV_BLOCK,
            message=f"LABGEN_RUNTIME_MODE='{mode}' is not a valid value.",
            detail=f"Valid values: {sorted(_SAFE_RUNTIME_MODES)}",
        ))
    else:
        report.add(PreflightCheck(
            name="runtime_mode_valid",
            severity=_SEV_PASS,
            message=f"LABGEN_RUNTIME_MODE={mode}",
        ))
    return mode


def _check_namespace_adapter(report: PreflightReport, runtime_mode: str) -> str:
    adapter = os.getenv("LABGEN_NAMESPACE_ADAPTER", "stub")

    if adapter not in _SAFE_ADAPTER_KINDS:
        report.add(PreflightCheck(
            name="namespace_adapter_valid",
            severity=_SEV_BLOCK,
            message=f"LABGEN_NAMESPACE_ADAPTER='{adapter}' is not a valid value.",
            detail=f"Valid values: {sorted(_SAFE_ADAPTER_KINDS)}",
        ))
        return adapter

    report.add(PreflightCheck(
        name="namespace_adapter_valid",
        severity=_SEV_PASS,
        message=f"LABGEN_NAMESPACE_ADAPTER={adapter}",
    ))

    # production + stub → blocking
    if runtime_mode == "production" and adapter == "stub":
        report.add(PreflightCheck(
            name="production_no_stub_adapter",
            severity=_SEV_BLOCK,
            message=(
                "LABGEN_NAMESPACE_ADAPTER=stub is not allowed in production mode. "
                "Every lab start will fail with STUB_ADAPTER_IN_PRODUCTION."
            ),
            detail=(
                "Set LABGEN_NAMESPACE_ADAPTER=k8s and provide "
                "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH. "
                "Note: K3sNamespaceLifecycleAdapter must be implemented before lab starts work."
            ),
        ))
    elif adapter == "stub":
        report.add(PreflightCheck(
            name="production_no_stub_adapter",
            severity=_SEV_WARN,
            message=(
                f"LABGEN_NAMESPACE_ADAPTER=stub in {runtime_mode} mode. "
                "No real K8s operations will occur. Not for production use."
            ),
        ))
    else:
        report.add(PreflightCheck(
            name="production_no_stub_adapter",
            severity=_SEV_PASS,
            message="LABGEN_NAMESPACE_ADAPTER=k8s (production-safe adapter)",
        ))

    return adapter


def _check_k8s_kubeconfig(report: PreflightReport, adapter: str) -> None:
    kubeconfig = os.getenv("LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "")
    if adapter == "k8s":
        if not kubeconfig:
            report.add(PreflightCheck(
                name="k8s_kubeconfig_set",
                severity=_SEV_BLOCK,
                message=(
                    "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is required when "
                    "LABGEN_NAMESPACE_ADAPTER=k8s."
                ),
            ))
        elif not os.path.isabs(kubeconfig):
            report.add(PreflightCheck(
                name="k8s_kubeconfig_set",
                severity=_SEV_WARN,
                message=(
                    "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is a relative path. "
                    "Use an absolute path in production."
                ),
                detail=f"Current value (path not checked): {kubeconfig!r}",
            ))
        else:
            report.add(PreflightCheck(
                name="k8s_kubeconfig_set",
                severity=_SEV_PASS,
                message="LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is set (absolute path, not verified)",
            ))
    else:
        report.add(PreflightCheck(
            name="k8s_kubeconfig_set",
            severity=_SEV_PASS,
            message="LABGEN_K8S_PLATFORM_KUBECONFIG_PATH check skipped (adapter=stub)",
        ))


def _check_credential_root(report: PreflightReport) -> None:
    root = os.getenv("LABGEN_VERIFIER_CREDENTIAL_ROOT", "creds/vm_creds")

    # Missing / empty
    if not root:
        report.add(PreflightCheck(
            name="credential_root_configured",
            severity=_SEV_BLOCK,
            message="LABGEN_VERIFIER_CREDENTIAL_ROOT is empty.",
            detail="Set to an absolute path outside the app directory (e.g. /var/lib/labgen/verifier-credentials).",
        ))
        return

    # Relative path
    if not os.path.isabs(root):
        report.add(PreflightCheck(
            name="credential_root_configured",
            severity=_SEV_BLOCK,
            message=(
                f"LABGEN_VERIFIER_CREDENTIAL_ROOT='{root}' is a relative path. "
                "Production requires an absolute path."
            ),
            detail="Relative paths depend on CWD and are unsafe for credential storage.",
        ))
        return

    # Dangerous root-level or temp paths
    if root in _UNSAFE_CREDENTIAL_ROOTS or root.startswith(_UNSAFE_CREDENTIAL_PREFIXES):
        report.add(PreflightCheck(
            name="credential_root_configured",
            severity=_SEV_BLOCK,
            message=f"LABGEN_VERIFIER_CREDENTIAL_ROOT='{root}' is an unsafe path.",
            detail="Do not use /tmp, /var/tmp, /, or empty string for credential storage.",
        ))
        return

    report.add(PreflightCheck(
        name="credential_root_configured",
        severity=_SEV_PASS,
        message=f"LABGEN_VERIFIER_CREDENTIAL_ROOT is set (absolute path, directory not verified)",
    ))


def _check_llm_provider(report: PreflightReport) -> None:
    mode = os.getenv("LABGEN_LLM_PROVIDER_MODE", "fake_only")

    if mode not in _SAFE_LLM_MODES:
        report.add(PreflightCheck(
            name="llm_provider_mode_valid",
            severity=_SEV_BLOCK,
            message=f"LABGEN_LLM_PROVIDER_MODE='{mode}' is not a valid value.",
            detail=f"Valid values: {sorted(_SAFE_LLM_MODES)}",
        ))
        return

    report.add(PreflightCheck(
        name="llm_provider_mode_valid",
        severity=_SEV_PASS,
        message=f"LABGEN_LLM_PROVIDER_MODE={mode}",
    ))

    if mode == "live_enabled":
        report.add(PreflightCheck(
            name="llm_live_disabled",
            severity=_SEV_WARN,
            message=(
                "LABGEN_LLM_PROVIDER_MODE=live_enabled. "
                "Live LLM generation is enabled. Verify this is intentional and "
                "that LABGEN_LLM_OPENAI_API_KEY is injected via secret manager."
            ),
            detail=(
                "At initial production deployment, this should be fake_only or disabled. "
                "Enable live providers only after explicit approval."
            ),
        ))
    else:
        report.add(PreflightCheck(
            name="llm_live_disabled",
            severity=_SEV_PASS,
            message=f"LLM provider is not live ({mode}) — no real LLM calls will be made",
        ))


def _check_llm_api_key_not_exposed(report: PreflightReport) -> None:
    # We only check presence, not the value — never print secret values.
    api_key = os.getenv("LABGEN_LLM_OPENAI_API_KEY", "")
    mode = os.getenv("LABGEN_LLM_PROVIDER_MODE", "fake_only")

    if api_key and mode != "live_enabled":
        report.add(PreflightCheck(
            name="llm_api_key_not_exposed",
            severity=_SEV_WARN,
            message=(
                "LABGEN_LLM_OPENAI_API_KEY is set but LABGEN_LLM_PROVIDER_MODE is not live_enabled. "
                "The key is loaded but unused. Consider removing it from the environment."
            ),
        ))
    else:
        report.add(PreflightCheck(
            name="llm_api_key_not_exposed",
            severity=_SEV_PASS,
            message="LABGEN_LLM_OPENAI_API_KEY check passed (value not inspected)",
        ))


def _check_session_ttl(report: PreflightReport) -> None:
    raw = os.getenv("LABGEN_LAB_SESSION_TTL_MINUTES", "30")
    try:
        ttl = int(raw)
    except ValueError:
        report.add(PreflightCheck(
            name="session_ttl_valid",
            severity=_SEV_BLOCK,
            message=f"LABGEN_LAB_SESSION_TTL_MINUTES='{raw}' is not a valid integer.",
        ))
        return

    if ttl < 1:
        report.add(PreflightCheck(
            name="session_ttl_valid",
            severity=_SEV_BLOCK,
            message=f"LABGEN_LAB_SESSION_TTL_MINUTES={ttl} must be >= 1.",
        ))
        return

    if ttl > 480:
        report.add(PreflightCheck(
            name="session_ttl_valid",
            severity=_SEV_WARN,
            message=(
                f"LABGEN_LAB_SESSION_TTL_MINUTES={ttl} is unusually long (> 8 hours). "
                "Verify this is intentional."
            ),
        ))
        return

    report.add(PreflightCheck(
        name="session_ttl_valid",
        severity=_SEV_PASS,
        message=f"LABGEN_LAB_SESSION_TTL_MINUTES={ttl}",
    ))


def _check_demo_seed_not_exposed(report: PreflightReport) -> None:
    # There is no LABGEN_DEMO_SEED_ENABLED flag — the endpoint is always registered
    # and admin-gated.  We check that ADMIN_USERNAMES is set (non-empty) so the
    # gate has a meaningful allow-list.
    admin_usernames = os.getenv("ADMIN_USERNAMES", "")
    if not admin_usernames.strip():
        report.add(PreflightCheck(
            name="demo_seed_gated",
            severity=_SEV_WARN,
            message=(
                "ADMIN_USERNAMES is empty. The demo seed endpoint "
                "(POST /api/labgen/seed/demo) is admin-gated but the admin list is empty, "
                "which means no user can access it — but also the admin diagnostic "
                "endpoints will return 503."
            ),
            detail="Set ADMIN_USERNAMES to a small, known list of admin usernames.",
        ))
    else:
        report.add(PreflightCheck(
            name="demo_seed_gated",
            severity=_SEV_PASS,
            message="ADMIN_USERNAMES is set — demo seed endpoint is admin-gated",
        ))


def _check_admin_token(report: PreflightReport) -> None:
    # Only checks presence and minimum length — never prints the value.
    token = os.getenv("ADMIN_TOKEN", "")
    if not token:
        report.add(PreflightCheck(
            name="admin_token_set",
            severity=_SEV_BLOCK,
            message="ADMIN_TOKEN is not set. Admin API endpoints will return 503.",
            detail="Set ADMIN_TOKEN to a random string of >= 32 characters via secret manager.",
        ))
        return

    if len(token) < 32:
        report.add(PreflightCheck(
            name="admin_token_set",
            severity=_SEV_BLOCK,
            message=f"ADMIN_TOKEN is too short ({len(token)} chars, minimum 32).",
            detail="Short tokens are vulnerable to brute-force. Generate a new one.",
        ))
        return

    report.add(PreflightCheck(
        name="admin_token_set",
        severity=_SEV_PASS,
        message=f"ADMIN_TOKEN is set (length: {len(token)}, value not inspected)",
    ))


def _check_proxmox_auth(report: PreflightReport) -> None:
    # Check presence of one complete auth method — never print values.
    token_id = os.getenv("PROXMOX_TOKEN_ID", "")
    token_secret = os.getenv("PROXMOX_TOKEN_SECRET", "")
    user = os.getenv("PROXMOX_USER", "")
    password = os.getenv("PROXMOX_PASSWORD", "")
    host = os.getenv("PROXMOX_HOST", "")

    if not host:
        report.add(PreflightCheck(
            name="proxmox_auth",
            severity=_SEV_BLOCK,
            message="PROXMOX_HOST is not set.",
        ))
        return

    if token_id and token_secret:
        report.add(PreflightCheck(
            name="proxmox_auth",
            severity=_SEV_PASS,
            message="Proxmox token auth configured (PROXMOX_TOKEN_ID + PROXMOX_TOKEN_SECRET, values not inspected)",
        ))
    elif user and password:
        report.add(PreflightCheck(
            name="proxmox_auth",
            severity=_SEV_WARN,
            message=(
                "Proxmox password auth is configured (PROXMOX_USER + PROXMOX_PASSWORD). "
                "Token auth is recommended for production."
            ),
        ))
    else:
        report.add(PreflightCheck(
            name="proxmox_auth",
            severity=_SEV_BLOCK,
            message=(
                "Proxmox authentication is not configured. "
                "Set PROXMOX_TOKEN_ID + PROXMOX_TOKEN_SECRET (recommended) "
                "or PROXMOX_USER + PROXMOX_PASSWORD."
            ),
        ))


def _check_vm_ssh_password(report: PreflightReport) -> None:
    pw = os.getenv("VM_SSH_PASSWORD", "")
    if not pw:
        report.add(PreflightCheck(
            name="vm_ssh_password_set",
            severity=_SEV_BLOCK,
            message="VM_SSH_PASSWORD is not set.",
            detail="Required for VM SSH access during lab initialization.",
        ))
    else:
        report.add(PreflightCheck(
            name="vm_ssh_password_set",
            severity=_SEV_PASS,
            message="VM_SSH_PASSWORD is set (value not inspected)",
        ))


def _check_session_cookie_secure(report: PreflightReport) -> None:
    raw = os.getenv("SESSION_COOKIE_SECURE", "true")
    if raw.lower() not in ("true", "1", "yes"):
        report.add(PreflightCheck(
            name="session_cookie_secure",
            severity=_SEV_WARN,
            message=(
                f"SESSION_COOKIE_SECURE={raw!r} — session cookies will not require HTTPS. "
                "Set to true in production."
            ),
        ))
    else:
        report.add(PreflightCheck(
            name="session_cookie_secure",
            severity=_SEV_PASS,
            message="SESSION_COOKIE_SECURE=true",
        ))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_preflight() -> PreflightReport:
    """Execute all checks and return a report. No network calls, no secret output."""
    report = PreflightReport()

    runtime_mode = _check_runtime_mode(report)
    adapter = _check_namespace_adapter(report, runtime_mode)
    _check_k8s_kubeconfig(report, adapter)
    _check_credential_root(report)
    _check_llm_provider(report)
    _check_llm_api_key_not_exposed(report)
    _check_session_ttl(report)
    _check_demo_seed_not_exposed(report)
    _check_admin_token(report)
    _check_proxmox_auth(report)
    _check_vm_ssh_password(report)
    _check_session_cookie_secure(report)

    return report


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_ICONS = {_SEV_PASS: "✓", _SEV_WARN: "⚠", _SEV_BLOCK: "✗"}
_COLORS = {
    _SEV_PASS: "\033[92m",    # green
    _SEV_WARN: "\033[93m",    # yellow
    _SEV_BLOCK: "\033[91m",   # red
}
_RESET = "\033[0m"


def _human_output(report: PreflightReport) -> None:
    print("LabGen Production Preflight Check")
    print("=" * 50)
    for check in report.checks:
        icon = _ICONS.get(check.severity, "?")
        color = _COLORS.get(check.severity, "")
        print(f"{color}{icon} [{check.name}] {check.message}{_RESET}")
        if check.detail:
            print(f"  → {check.detail}")

    print()
    print(f"Checks: {report.pass_count()} passed, "
          f"{report.warning_count()} warnings, "
          f"{report.blocking_count()} blocking")
    overall_color = _COLORS.get(report.overall, "")
    print(f"{overall_color}Overall: {report.overall.upper()}{_RESET}")

    if report.blocking_count() > 0:
        print()
        print("PREFLIGHT FAILED — fix blocking issues before deploying.")


def _json_output(report: PreflightReport) -> None:
    out = {
        "overall": report.overall,
        "pass_count": report.pass_count(),
        "warning_count": report.warning_count(),
        "blocking_count": report.blocking_count(),
        "checks": [
            {
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
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    use_json = "--json" in sys.argv
    report = run_preflight()

    if use_json:
        _json_output(report)
    else:
        _human_output(report)

    return 0 if report.blocking_count() == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
