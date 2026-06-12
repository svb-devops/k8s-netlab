#!/usr/bin/env python3
"""
LabGen Ops Secret Injection Verification v0.1
==============================================
Ops-facing tool that reads a staging env file and reports the per-key
injection status of the 6 required blocking inputs that must be set
before the Ops Staging Intake Gate can reach READY_TO_RERUN.

Reports key-level status only — never prints secret values.

Per-key status labels:
  PRESENT_REDACTED  — present, non-empty, no placeholder token, passes format check
  MISSING           — absent from env file (not active, not acknowledged)
  PLACEHOLDER       — value is or contains a <...> token, or is a known placeholder
  EMPTY             — key is present but value is empty string
  INVALID_FORMAT    — present and non-placeholder but fails a format check

Final decision:
  SECRET_INJECTION_READY    — all required keys are PRESENT_REDACTED (exit 0)
  SECRET_INJECTION_BLOCKED  — one or more keys are not PRESENT_REDACTED (exit 1)

Guarantees:
  - No network calls of any kind.
  - Does not connect to K3s, Proxmox, registry, or any external service.
  - Does not read kubeconfig file contents — only checks whether the path
    value is a non-placeholder string (does not verify file existence).
  - Does not print any secret value — shows key name and status only.
  - Placeholder / empty / absent values → blocked.
  - Suspicious production-looking values → warning (not blocking).
  - Exit code 2 on invocation error or unreadable env file.

Usage:
  python scripts/labgen_ops_secret_injection_verify.py \\
      --env-file <staging-env-file> [--json] [--quiet]
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Shared parser from provisioning validator (no duplication)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from labgen_staging_provisioning_validate import (  # noqa: E402
    _parse_env_file,
    _PLACEHOLDER_RE,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DECISION_READY = "SECRET_INJECTION_READY"
_DECISION_BLOCKED = "SECRET_INJECTION_BLOCKED"

# Matches any <...> token anywhere in a value
_VALUE_CONTAINS_PLACEHOLDER_RE = re.compile(r"<[^>]+>")

# Suspicious production-indicator patterns (hostname / domain / IP format)
# Used for warning only — not blocking, because we can't know the operator's
# real staging hostname without a reference.  We only warn if the value looks
# indistinguishable from a known-production marker.
_PRODUCTION_MARKERS = re.compile(
    r"lab\.cloudnetops\.tech"
    r"|172\.16\.100\."   # production vmbr1 subnet
    r"|10\.0\.0\."       # production management subnet
)

# ---------------------------------------------------------------------------
# Per-key definitions for the 6 required blocking inputs
# (+PROXMOX_TOKEN_ID as a closely related required key)
# ---------------------------------------------------------------------------

# Status labels (stable strings — tests assert against these)
STATUS_PRESENT_REDACTED = "PRESENT_REDACTED"
STATUS_MISSING = "MISSING"
STATUS_PLACEHOLDER = "PLACEHOLDER"
STATUS_EMPTY = "EMPTY"
STATUS_INVALID_FORMAT = "INVALID_FORMAT"


@dataclass
class _KeyDef:
    key: str
    description: str
    category: str
    owner: str
    format_check: Optional[str] = None  # "min32" | "http_url" | None


_REQUIRED_KEYS: list[_KeyDef] = [
    _KeyDef(
        key="LABGEN_K8S_PLATFORM_KUBECONFIG_PATH",
        description=(
            "Absolute path to staging K3s kubeconfig "
            "(inject via secret manager — never commit the kubeconfig)"
        ),
        category="K3s / Kubernetes",
        owner="Ops",
        format_check=None,
    ),
    _KeyDef(
        key="ADMIN_TOKEN",
        description="Static admin token (must be >= 32 characters — inject via secret manager)",
        category="Auth / Admin",
        owner="Ops",
        format_check="min32",
    ),
    _KeyDef(
        key="PROXMOX_HOST",
        description="Staging Proxmox API hostname (no placeholder, no angle brackets)",
        category="Proxmox",
        owner="Ops",
        format_check=None,
    ),
    _KeyDef(
        key="PROXMOX_TOKEN_ID",
        description="Proxmox API token ID (e.g. user@pve!token-name)",
        category="Proxmox",
        owner="Ops",
        format_check=None,
    ),
    _KeyDef(
        key="PROXMOX_TOKEN_SECRET",
        description="Proxmox API token secret UUID (inject via secret manager)",
        category="Proxmox",
        owner="Ops",
        format_check=None,
    ),
    _KeyDef(
        key="VM_SSH_PASSWORD",
        description="VM SSH password for K3s configuration (inject via secret manager)",
        category="VM Access",
        owner="Ops",
        format_check=None,
    ),
    _KeyDef(
        key="VM_REGISTRY_MIRROR",
        description=(
            "Internal image registry URL — must start with http:// or https:// "
            "and not contain <...> placeholders"
        ),
        category="Image Registry",
        owner="Ops",
        format_check="http_url",
    ),
]


# ---------------------------------------------------------------------------
# Per-key status determination
# ---------------------------------------------------------------------------


def _classify_key(
    key: str,
    key_def: _KeyDef,
    active: dict[str, str],
    acknowledged: set[str],
) -> tuple[str, list[str], list[str]]:
    """
    Classify one key into a status label.

    Returns:
        (status, blocking_details, warnings)
        blocking_details and warnings are human-readable strings about key names only,
        never about values.
    """
    # ---- absent ----
    if key not in active and key not in acknowledged:
        return STATUS_MISSING, [f"{key}: absent from env file"], []

    # ---- acknowledged placeholder (commented-out placeholder) ----
    if key not in active and key in acknowledged:
        return STATUS_PLACEHOLDER, [f"{key}: acknowledged as placeholder — not yet injected"], []

    value = active[key]

    # ---- empty ----
    if not value:
        return STATUS_EMPTY, [f"{key}: present but empty"], []

    # ---- placeholder token in value ----
    if _PLACEHOLDER_RE.match(value) or _VALUE_CONTAINS_PLACEHOLDER_RE.search(value):
        return STATUS_PLACEHOLDER, [f"{key}: value contains placeholder token"], []

    # ---- format checks ----
    if key_def.format_check == "min32":
        if len(value) < 32:
            return (
                STATUS_INVALID_FORMAT,
                [f"{key}: value too short (must be >= 32 characters)"],
                [],
            )

    if key_def.format_check == "http_url":
        if not (value.startswith("http://") or value.startswith("https://")):
            return (
                STATUS_INVALID_FORMAT,
                [f"{key}: value must start with http:// or https://"],
                [],
            )

    # ---- production-marker warning ----
    warnings: list[str] = []
    if _PRODUCTION_MARKERS.search(value):
        warnings.append(
            f"{key}: value resembles a known-production marker "
            "(verify this is a staging-only value)"
        )

    return STATUS_PRESENT_REDACTED, [], warnings


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class KeyVerificationResult:
    key: str
    status: str
    category: str
    owner: str
    description: str
    blocking_details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.status == STATUS_PRESENT_REDACTED

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "status": self.status,
            "category": self.category,
            "owner": self.owner,
            "description": self.description,
            "blocking_details": self.blocking_details,
            "warnings": self.warnings,
        }


@dataclass
class SecretInjectionResult:
    decision: str
    checked_at: str
    env_file: str
    keys: list[KeyVerificationResult] = field(default_factory=list)
    all_blocking_keys: list[str] = field(default_factory=list)
    all_warnings: list[str] = field(default_factory=list)
    next_step: str = ""

    @property
    def ready_count(self) -> int:
        return sum(1 for k in self.keys if k.is_ready)

    @property
    def blocked_count(self) -> int:
        return sum(1 for k in self.keys if not k.is_ready)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "checked_at": self.checked_at,
            "env_file": self.env_file,
            "summary": {
                "total": len(self.keys),
                "ready": self.ready_count,
                "blocked": self.blocked_count,
            },
            "keys": [k.to_dict() for k in self.keys],
            "all_blocking_keys": self.all_blocking_keys,
            "all_warnings": self.all_warnings,
            "next_step": self.next_step,
        }


# ---------------------------------------------------------------------------
# Main verification function
# ---------------------------------------------------------------------------


def verify_secret_injection(env_file: str) -> SecretInjectionResult:
    """
    Read env_file and verify per-key injection status for the 6 required
    blocking inputs.

    No network calls. No secret value printing. No filesystem side effects.

    Args:
        env_file: Path to the staging env file to check.

    Returns:
        SecretInjectionResult with decision and per-key status.

    Raises:
        FileNotFoundError: if the file does not exist.
        PermissionError: if the file cannot be read.
    """
    active, acknowledged = _parse_env_file(env_file)
    checked_at = datetime.now(tz=timezone.utc).isoformat()

    key_results: list[KeyVerificationResult] = []
    all_blocking_keys: list[str] = []
    all_warnings: list[str] = []

    for key_def in _REQUIRED_KEYS:
        status, blocking_details, warnings = _classify_key(
            key_def.key, key_def, active, acknowledged
        )
        kv = KeyVerificationResult(
            key=key_def.key,
            status=status,
            category=key_def.category,
            owner=key_def.owner,
            description=key_def.description,
            blocking_details=blocking_details,
            warnings=warnings,
        )
        key_results.append(kv)

        if not kv.is_ready:
            all_blocking_keys.append(key_def.key)
        all_warnings.extend(warnings)

    decision = _DECISION_READY if not all_blocking_keys else _DECISION_BLOCKED

    if decision == _DECISION_READY:
        next_step = (
            "All required secrets are present. "
            "Re-run the Ops Staging Intake Gate to confirm readiness:\n"
            "  python scripts/labgen_ops_staging_intake_verify.py "
            "--env-file <staging-env-file> --json"
        )
    else:
        next_step = (
            f"{len(all_blocking_keys)} key(s) are not ready. "
            "Inject all missing/placeholder secrets via secret manager, "
            "then re-run this verification:\n"
            "  python scripts/labgen_ops_secret_injection_verify.py "
            "--env-file <staging-env-file> --json"
        )

    return SecretInjectionResult(
        decision=decision,
        checked_at=checked_at,
        env_file=env_file,
        keys=key_results,
        all_blocking_keys=all_blocking_keys,
        all_warnings=all_warnings,
        next_step=next_step,
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_COLOR_RED = "\033[91m"
_COLOR_GREEN = "\033[92m"
_COLOR_YELLOW = "\033[93m"
_RESET = "\033[0m"

_STATUS_ICON = {
    STATUS_PRESENT_REDACTED: "✓",
    STATUS_MISSING: "✗",
    STATUS_PLACEHOLDER: "✗",
    STATUS_EMPTY: "✗",
    STATUS_INVALID_FORMAT: "✗",
}
_STATUS_COLOR = {
    STATUS_PRESENT_REDACTED: _COLOR_GREEN,
    STATUS_MISSING: _COLOR_RED,
    STATUS_PLACEHOLDER: _COLOR_RED,
    STATUS_EMPTY: _COLOR_RED,
    STATUS_INVALID_FORMAT: _COLOR_RED,
}


def _human_output(result: SecretInjectionResult, use_color: bool = True) -> None:
    def _c(color: str, text: str) -> str:
        return f"{color}{text}{_RESET}" if use_color and color else text

    print("LabGen Ops Secret Injection Verification v0.1")
    print("=" * 52)
    print(f"Env file : {result.env_file}")
    print(f"Checked  : {result.checked_at}")
    print()

    current_category = ""
    for kv in result.keys:
        if kv.category != current_category:
            current_category = kv.category
            print(f"[{current_category}]")

        icon = _STATUS_ICON.get(kv.status, "?")
        color = _STATUS_COLOR.get(kv.status, "")
        print(f"  {_c(color, icon)}  {kv.key}")
        print(f"       Status: {_c(color, kv.status)}")
        for detail in kv.blocking_details:
            print(f"       {_c(_COLOR_RED, '→')} {detail}")
        for w in kv.warnings:
            print(f"       {_c(_COLOR_YELLOW, '⚠')} {w}")
    print()

    decision_color = _COLOR_GREEN if result.decision == _DECISION_READY else _COLOR_RED
    print(_c(decision_color, f"Decision: {result.decision}"))
    print(
        f"  Ready: {result.ready_count} / {len(result.keys)}  "
        f"Blocked: {result.blocked_count} / {len(result.keys)}"
    )
    print()
    print(f"Next step:\n  {result.next_step}")

    if result.all_warnings:
        print()
        print(_c(_COLOR_YELLOW, f"Warnings ({len(result.all_warnings)}):"))
        for w in result.all_warnings:
            print(f"  ⚠ {w}")

    print()
    if result.decision == _DECISION_READY:
        print(_c(_COLOR_GREEN, "SECRET INJECTION READY — proceed to intake gate."))
    else:
        print(_c(
            _COLOR_RED,
            f"SECRET INJECTION BLOCKED — {result.blocked_count} key(s) not ready.",
        ))


def _json_output(result: SecretInjectionResult) -> None:
    print(json.dumps(result.to_dict(), indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> tuple[Optional[str], bool, bool]:
    """Return (env_file, use_json, quiet)."""
    env_file: Optional[str] = None
    use_json = False
    quiet = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--json":
            use_json = True
        elif arg == "--quiet":
            quiet = True
        elif arg in ("--env-file", "-e") and i + 1 < len(argv):
            i += 1
            env_file = argv[i]
        elif arg.startswith("--env-file="):
            env_file = arg.split("=", 1)[1]
        i += 1

    return env_file, use_json, quiet


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    env_file, use_json, quiet = _parse_args(argv)

    if not env_file:
        print(
            "Error: --env-file <path> is required.\n"
            "Usage: python scripts/labgen_ops_secret_injection_verify.py "
            "--env-file <staging-env-file> [--json] [--quiet]",
            file=sys.stderr,
        )
        return 2

    try:
        result = verify_secret_injection(env_file)
    except FileNotFoundError:
        if not quiet:
            print(f"ERROR: env file not found: {env_file}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        if not quiet:
            print(f"ERROR: cannot read env file: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        if not quiet:
            print(f"ERROR: unexpected error reading env file: {exc}", file=sys.stderr)
        return 2

    if not quiet:
        if use_json:
            _json_output(result)
        else:
            _human_output(result)

    return 0 if result.decision == _DECISION_READY else 1


if __name__ == "__main__":
    sys.exit(main())
