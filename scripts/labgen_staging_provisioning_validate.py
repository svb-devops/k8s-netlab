#!/usr/bin/env python3
"""
LabGen Staging Provisioning Validator
=======================================
Static-only configuration validator for staging environment provisioning.

Reads a specified env file (default: deploy/labgen/.env.staging.example),
validates all required key presence, forbidden unsafe values, placeholder
safety, and staging-specific security conditions.

Guarantees:
  - No network calls of any kind.
  - Does not connect to K3s, Proxmox, or registry.
  - Does not read secret file contents.
  - Does not print secret values — reports presence / length only.
  - Missing required config → exit code 1 (fail closed).

Output fields:
  overall           "pass" | "warning" | "blocking"
  blocking_issues   list of {check, message}
  warnings          list of {check, message}
  missing_keys      list of key names absent from the env file
  checked_at        ISO-8601 UTC timestamp
  env_file          path validated
  active_key_count  number of uncommented KEY=VALUE lines found

Exit codes:
  0  No blocking issues (warnings may be present).
  1  One or more blocking issues detected.
  2  Env file not found or unreadable.

Usage:
  # Validate the example template
  python scripts/labgen_staging_provisioning_validate.py

  # Validate a specific env file
  python scripts/labgen_staging_provisioning_validate.py \\
      --env-file deploy/labgen/.env.staging.example

  # JSON output
  python scripts/labgen_staging_provisioning_validate.py --json

  # Quiet (exit code only)
  python scripts/labgen_staging_provisioning_validate.py --quiet
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
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_ENV_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "deploy", "labgen", ".env.staging.example",
)

_SEV_PASS = "pass"
_SEV_WARN = "warning"
_SEV_BLOCK = "blocking"

# Keys that must be present (uncommented) in the env file.
_REQUIRED_ACTIVE_KEYS: list[str] = [
    "LABGEN_RUNTIME_MODE",
    "LABGEN_NAMESPACE_ADAPTER",
    "LABGEN_LLM_PROVIDER_MODE",
    "LABGEN_LAB_SESSION_TTL_MINUTES",
    "LABGEN_VERIFIER_CREDENTIAL_ROOT",
    "PROXMOX_HOST",
    "PROXMOX_TOKEN_ID",
]

# When LABGEN_NAMESPACE_ADAPTER=k8s, this key must also be present
# (or at least acknowledged as a commented placeholder to inject at runtime).
_K8S_KUBECONFIG_KEY = "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"

# Secret keys that must NOT appear as active (uncommented) entries
# unless they look like placeholders.
_SECRET_KEYS_MUST_NOT_BE_ACTIVE: list[str] = [
    "LABGEN_LLM_OPENAI_API_KEY",
    "PROXMOX_TOKEN_SECRET",
    "ADMIN_TOKEN",
    "VM_SSH_PASSWORD",
    "DEEPSEEK_API_KEY",
]

# Placeholder patterns — values matching these are considered intentional
# placeholders and do not trigger secret-exposure checks.
_PLACEHOLDER_RE = re.compile(r"^<[^>]+>$")

# Patterns in active config values that indicate real credentials.
# Report blocking WITHOUT printing the actual value.
_REAL_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api_key_anthropic", re.compile(r"^sk-ant-")),
    ("api_key_openai", re.compile(r"^sk-proj-|^sk-[A-Za-z0-9]{20,}")),
    ("pem_key_material", re.compile(r"-----BEGIN")),
    ("jwt_token", re.compile(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$")),
]

# Credential root values that are always unsafe.
_UNSAFE_CREDENTIAL_ROOTS: frozenset[str] = frozenset(
    {"", ".", "/", "/tmp", "/var/tmp", "/root", "/home"}
)
_UNSAFE_CREDENTIAL_PREFIXES: tuple[str, ...] = ("/tmp/", "/var/tmp/")

# Runtime modes NOT appropriate for a staging provisioning context.
# "demo" mode implies demo-oriented auto-seeding behaviours.
_DEMO_SEED_RUNTIME_MODES: frozenset[str] = frozenset({"demo"})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ProvisioningIssue:
    check: str
    message: str


@dataclass
class ProvisioningResult:
    overall: str = _SEV_PASS
    blocking_issues: list[ProvisioningIssue] = field(default_factory=list)
    warnings: list[ProvisioningIssue] = field(default_factory=list)
    missing_keys: list[str] = field(default_factory=list)
    env_file: str = ""
    active_key_count: int = 0
    checked_at: str = ""

    def block(self, check: str, message: str) -> None:
        self.blocking_issues.append(ProvisioningIssue(check=check, message=message))
        self.overall = _SEV_BLOCK

    def warn(self, check: str, message: str) -> None:
        self.warnings.append(ProvisioningIssue(check=check, message=message))
        if self.overall == _SEV_PASS:
            self.overall = _SEV_WARN

    def add_missing_key(self, key: str, check: str, message: str) -> None:
        self.missing_keys.append(key)
        self.block(check, message)

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "blocking_issues": [{"check": i.check, "message": i.message} for i in self.blocking_issues],
            "warnings": [{"check": i.check, "message": i.message} for i in self.warnings],
            "missing_keys": self.missing_keys,
            "checked_at": self.checked_at,
            "env_file": self.env_file,
            "active_key_count": self.active_key_count,
        }


# ---------------------------------------------------------------------------
# Env file parser
# ---------------------------------------------------------------------------

def _parse_env_file(path: str) -> tuple[dict[str, str], set[str]]:
    """
    Parse an env file.

    Returns:
        active_config: dict of KEY → VALUE for all uncommented KEY=VALUE lines.
        acknowledged_secrets: set of KEY names that appear as commented placeholders
            matching  ``# KEY=<something>`` or ``# KEY=<set-in-*>`` patterns.
            These represent secrets intentionally deferred to runtime injection.
    """
    active: dict[str, str] = {}
    acknowledged: set[str] = set()

    _commented_secret_re = re.compile(
        r"^#\s*([A-Z][A-Z0-9_]+)\s*=\s*(<[^>]+>|<set-in[^>]*>)$"
    )

    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")

            # Acknowledged secret: commented-out line with placeholder value
            m = _commented_secret_re.match(line)
            if m:
                acknowledged.add(m.group(1))
                continue

            # Skip all other comment lines and blank lines
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue

            # KEY=VALUE (value may be empty)
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()
                # Strip inline comments (value ends at first unquoted #)
                if not value.startswith(("'", '"')):
                    value = value.split("#")[0].strip()
                if key:
                    active[key] = value

    return active, acknowledged


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_required_active_keys(
    active: dict[str, str],
    result: ProvisioningResult,
) -> None:
    for key in _REQUIRED_ACTIVE_KEYS:
        if key not in active:
            result.add_missing_key(
                key,
                check="required_key_present",
                message=f"Required key '{key}' is absent from the env file.",
            )


def _check_namespace_adapter(
    active: dict[str, str],
    acknowledged: set[str],
    result: ProvisioningResult,
) -> None:
    adapter = active.get("LABGEN_NAMESPACE_ADAPTER", "")

    if adapter == "stub":
        result.block(
            check="namespace_adapter_not_stub",
            message=(
                "LABGEN_NAMESPACE_ADAPTER=stub is not allowed for staging trial. "
                "Every lab start will fail with STUB_ADAPTER_IN_PRODUCTION. "
                "Set to 'k8s' and provide LABGEN_K8S_PLATFORM_KUBECONFIG_PATH."
            ),
        )
        return

    if adapter != "k8s":
        # Unknown or empty — only warn if key is present; missing-key check covers absence
        if adapter:
            result.warn(
                check="namespace_adapter_known",
                message=(
                    f"LABGEN_NAMESPACE_ADAPTER='{adapter}' is an unrecognised value. "
                    "Expected 'k8s' for staging trial."
                ),
            )
        return

    # adapter == k8s: kubeconfig key must be acknowledged or active
    if _K8S_KUBECONFIG_KEY in active:
        value = active[_K8S_KUBECONFIG_KEY]
        if not value:
            result.block(
                check="k8s_kubeconfig_present",
                message=(
                    f"{_K8S_KUBECONFIG_KEY} is set but empty. "
                    "Provide an absolute path or inject via secret manager."
                ),
            )
        # Non-empty value (even a placeholder) passes this check
        return

    if _K8S_KUBECONFIG_KEY in acknowledged:
        result.warn(
            check="k8s_kubeconfig_present",
            message=(
                f"{_K8S_KUBECONFIG_KEY} is acknowledged as a commented placeholder. "
                "Inject the real kubeconfig path via secret manager before trial execution."
            ),
        )
        return

    # Key absent entirely with k8s adapter → blocking
    result.add_missing_key(
        _K8S_KUBECONFIG_KEY,
        check="k8s_kubeconfig_present",
        message=(
            f"{_K8S_KUBECONFIG_KEY} is required when LABGEN_NAMESPACE_ADAPTER=k8s "
            "but is absent from the env file (not even as a commented placeholder). "
            "Add it as '# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-secret-manager>' "
            "or set it to an absolute path."
        ),
    )


def _check_llm_live(active: dict[str, str], result: ProvisioningResult) -> None:
    mode = active.get("LABGEN_LLM_PROVIDER_MODE", "")
    if mode == "live_enabled":
        result.block(
            check="llm_live_disabled",
            message=(
                "LABGEN_LLM_PROVIDER_MODE=live_enabled is forbidden in staging provisioning. "
                "Set to 'fake_only' or 'disabled'. "
                "Live LLM must remain disabled until explicitly approved."
            ),
        )


def _check_demo_seed(active: dict[str, str], result: ProvisioningResult) -> None:
    runtime_mode = active.get("LABGEN_RUNTIME_MODE", "")
    if runtime_mode in _DEMO_SEED_RUNTIME_MODES:
        result.block(
            check="demo_seed_disabled",
            message=(
                f"LABGEN_RUNTIME_MODE='{runtime_mode}' enables demo-oriented behaviour "
                "(demo seed, relaxed guards) that is not appropriate for staging trial. "
                "Set LABGEN_RUNTIME_MODE=production."
            ),
        )


def _check_credential_root(active: dict[str, str], result: ProvisioningResult) -> None:
    root = active.get("LABGEN_VERIFIER_CREDENTIAL_ROOT", "")

    if not root or _PLACEHOLDER_RE.match(root):
        # Empty or placeholder — only warn if key is present with placeholder
        if root and _PLACEHOLDER_RE.match(root):
            result.warn(
                check="credential_root_safe",
                message=(
                    "LABGEN_VERIFIER_CREDENTIAL_ROOT contains a placeholder value. "
                    "Replace with an absolute staging-only path before trial execution."
                ),
            )
        # Empty case is covered by required-key check
        return

    if not os.path.isabs(root):
        result.block(
            check="credential_root_safe",
            message=(
                f"LABGEN_VERIFIER_CREDENTIAL_ROOT='{root}' is a relative path. "
                "Production/staging requires an absolute path outside the app directory."
            ),
        )
        return

    if root in _UNSAFE_CREDENTIAL_ROOTS or root.startswith(_UNSAFE_CREDENTIAL_PREFIXES):
        result.block(
            check="credential_root_safe",
            message=(
                f"LABGEN_VERIFIER_CREDENTIAL_ROOT is set to an unsafe path. "
                "Do not use /tmp, /var/tmp, /, /root, or empty string. "
                "Use a dedicated staging directory (e.g. /var/lib/labgen-staging/verifier-credentials)."
            ),
        )
        return

    result.warn(
        check="credential_root_safe",
        message=(
            "LABGEN_VERIFIER_CREDENTIAL_ROOT is set to an absolute non-default path. "
            "Verify the directory exists, is staging-only (not shared with production), "
            "and has chmod 700 before trial execution."
        ),
    ) if root != "/var/lib/labgen-staging/verifier-credentials" else None


def _check_secret_keys_not_active(
    active: dict[str, str],
    result: ProvisioningResult,
) -> None:
    runtime_mode = active.get("LABGEN_RUNTIME_MODE", "")
    for key in _SECRET_KEYS_MUST_NOT_BE_ACTIVE:
        if key not in active:
            continue
        value = active[key]
        if not value:
            continue
        if _PLACEHOLDER_RE.match(value):
            continue
        # home_lab_mvp has no external secret manager; file-based storage (chmod 600,
        # repo-external) is the accepted MVP-level credential store. Downgrade to warning.
        if runtime_mode == "home_lab_mvp":
            result.warn(
                check="secret_key_in_file_home_lab_mvp",
                message=(
                    f"'{key}' is stored as an active env var. "
                    "Acceptable for home_lab_mvp (chmod 600 repo-external file). "
                    "Not acceptable for production."
                ),
            )
            continue
        # Key is active with a non-placeholder value — do NOT print the value.
        result.block(
            check="secret_key_not_active",
            message=(
                f"'{key}' is set as an active (uncommented) env var with a non-placeholder value. "
                "Secret keys must be injected via secret manager at runtime, not stored in the env file. "
                "Comment out this line or replace the value with a placeholder like "
                f"'# {key}=<set-in-secret-manager>'."
            ),
        )


def _check_real_secret_patterns(
    active: dict[str, str],
    result: ProvisioningResult,
) -> None:
    for key, value in active.items():
        if not value or _PLACEHOLDER_RE.match(value):
            continue
        for pattern_name, pattern in _REAL_SECRET_PATTERNS:
            if pattern.search(value):
                # Never print the actual value
                result.block(
                    check="no_real_secret_in_file",
                    message=(
                        f"Key '{key}' contains a value matching the '{pattern_name}' secret pattern. "
                        "Real credentials must not be stored in env files. "
                        "Remove this value and inject via secret manager."
                    ),
                )
                break  # one report per key


def _check_session_ttl(active: dict[str, str], result: ProvisioningResult) -> None:
    raw = active.get("LABGEN_LAB_SESSION_TTL_MINUTES", "")
    if not raw or _PLACEHOLDER_RE.match(raw):
        return  # absence handled by required-key check
    try:
        ttl = int(raw)
    except ValueError:
        result.block(
            check="session_ttl_valid",
            message=f"LABGEN_LAB_SESSION_TTL_MINUTES='{raw}' is not a valid integer.",
        )
        return
    if ttl < 1:
        result.block(
            check="session_ttl_valid",
            message=f"LABGEN_LAB_SESSION_TTL_MINUTES={ttl} must be >= 1.",
        )
    elif ttl > 480:
        result.warn(
            check="session_ttl_valid",
            message=(
                f"LABGEN_LAB_SESSION_TTL_MINUTES={ttl} is unusually long (> 8 hours). "
                "Verify this is intentional for staging."
            ),
        )


def _check_runtime_mode(active: dict[str, str], result: ProvisioningResult) -> None:
    mode = active.get("LABGEN_RUNTIME_MODE", "")
    if not mode or _PLACEHOLDER_RE.match(mode):
        return
    valid_modes = {"test", "dev", "demo", "production", "home_lab_mvp", "cloud"}
    if mode not in valid_modes:
        result.block(
            check="runtime_mode_valid",
            message=(
                f"LABGEN_RUNTIME_MODE='{mode}' is not a recognised value. "
                f"Valid values: {sorted(valid_modes)}."
            ),
        )


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_env_file(
    env_file: str,
) -> ProvisioningResult:
    """
    Parse and statically validate a staging env file.

    No network calls. No secret value printing. No filesystem side effects.

    Args:
        env_file: Path to the env file to validate.

    Returns:
        ProvisioningResult with overall status and issue lists.

    Raises:
        FileNotFoundError: if the file does not exist.
        PermissionError: if the file cannot be read.
    """
    result = ProvisioningResult(
        env_file=env_file,
        checked_at=datetime.now(tz=timezone.utc).isoformat(),
    )

    active, acknowledged = _parse_env_file(env_file)
    result.active_key_count = len(active)

    # Run all checks
    _check_required_active_keys(active, result)
    _check_namespace_adapter(active, acknowledged, result)
    _check_llm_live(active, result)
    _check_demo_seed(active, result)
    _check_credential_root(active, result)
    _check_session_ttl(active, result)
    _check_runtime_mode(active, result)
    _check_secret_keys_not_active(active, result)
    _check_real_secret_patterns(active, result)

    return result


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


def _human_output(result: ProvisioningResult, use_color: bool = True) -> None:
    def _c(sev: str, text: str) -> str:
        if not use_color:
            return text
        return f"{_COLORS.get(sev, '')}{text}{_RESET}"

    print("LabGen Staging Provisioning Validator")
    print("=" * 50)
    print(f"Env file : {result.env_file}")
    print(f"Checked  : {result.checked_at}")
    print(f"Active keys: {result.active_key_count}")
    print()

    if result.blocking_issues:
        print(f"{_c(_SEV_BLOCK, f'BLOCKING ({len(result.blocking_issues)}):')}")
        for issue in result.blocking_issues:
            print(f"  {_ICONS[_SEV_BLOCK]} [{issue.check}] {issue.message}")
        print()

    if result.warnings:
        print(f"{_c(_SEV_WARN, f'WARNINGS ({len(result.warnings)}):')}")
        for issue in result.warnings:
            print(f"  {_ICONS[_SEV_WARN]} [{issue.check}] {issue.message}")
        print()

    if result.missing_keys:
        print(f"Missing keys: {', '.join(result.missing_keys)}")
        print()

    overall_icon = _ICONS.get(result.overall, "?")
    print(_c(result.overall, f"Overall: {result.overall.upper()}  {overall_icon}"))

    if result.blocking_issues:
        print()
        print("PROVISIONING VALIDATION FAILED — resolve blocking issues before trial execution.")


def _json_output(result: ProvisioningResult) -> None:
    print(json.dumps(result.to_dict(), indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str]) -> tuple[str, bool, bool]:
    """Returns (env_file, use_json, quiet)."""
    env_file = _DEFAULT_ENV_FILE
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

    try:
        result = validate_env_file(env_file)
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

    return 0 if not result.blocking_issues else 1


if __name__ == "__main__":
    sys.exit(main())
