#!/usr/bin/env python3
"""
LabGen Staging Missing Inputs Helper
======================================
Ops-facing tool that reads a staging env file and reports which blocking
inputs are missing or still contain placeholder values, grouped by category.

This is an ops-friendly summary wrapper. It reuses the env-file parser from
labgen_staging_provisioning_validate.py and focuses specifically on identifying
which required secrets and config values have not been injected yet.

Guarantees:
  - No network calls of any kind.
  - Does not connect to K3s, Proxmox, or registry.
  - Does not read secret file contents.
  - Does not print secret values — reports key names and status only.
  - Placeholder values (e.g. <set-in-secret-manager>) are treated as missing.
  - Empty string values are treated as missing.

Exit codes:
  0  No missing blocking inputs — all required inputs are set.
  1  One or more missing blocking inputs — live trial rerun is blocked.
  2  Env file not found, unreadable, or invalid invocation.

Usage:
  # Check the staging example template (default)
  python scripts/labgen_staging_missing_inputs.py

  # Check a specific env file
  python scripts/labgen_staging_missing_inputs.py --env-file .env.staging

  # JSON output (for CI / automation)
  python scripts/labgen_staging_missing_inputs.py --env-file .env.staging --json

  # Quiet mode (exit code only)
  python scripts/labgen_staging_missing_inputs.py --env-file .env.staging --quiet
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
# Import shared parser from provisioning validator (no duplication)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)

from labgen_staging_provisioning_validate import (  # noqa: E402
    _parse_env_file,
    _PLACEHOLDER_RE,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_ENV_FILE = os.path.join(
    os.path.dirname(_SCRIPTS_DIR),
    "deploy", "labgen", ".env.staging.example",
)

_VALUE_CONTAINS_PLACEHOLDER_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Input group definitions
# ---------------------------------------------------------------------------

@dataclass
class _InputItemDef:
    key: str
    description: str
    required_for: str
    owner: str


@dataclass
class _InputGroupDef:
    group: str
    label: str
    items: list[_InputItemDef]


_INPUT_GROUPS: list[_InputGroupDef] = [
    _InputGroupDef(
        group="k3s",
        label="K3s / Kubernetes",
        items=[
            _InputItemDef(
                key="LABGEN_K8S_PLATFORM_KUBECONFIG_PATH",
                description=(
                    "Absolute path to staging K3s kubeconfig file "
                    "(inject via secret manager — never commit the kubeconfig)"
                ),
                required_for="all lab session creation (namespace lifecycle adapter)",
                owner="Ops",
            ),
        ],
    ),
    _InputGroupDef(
        group="auth_admin",
        label="Auth / Admin",
        items=[
            _InputItemDef(
                key="ADMIN_TOKEN",
                description="Static admin token, >= 32 characters (inject via secret manager)",
                required_for="admin diagnostic endpoints — required for Phase 6 validation",
                owner="Ops",
            ),
        ],
    ),
    _InputGroupDef(
        group="proxmox",
        label="Proxmox",
        items=[
            _InputItemDef(
                key="PROXMOX_HOST",
                description="Staging Proxmox API hostname (not a placeholder)",
                required_for="VM creation and management",
                owner="Ops",
            ),
            _InputItemDef(
                key="PROXMOX_TOKEN_SECRET",
                description="Proxmox API token secret (inject via secret manager)",
                required_for="Proxmox authentication — VM creation",
                owner="Ops",
            ),
        ],
    ),
    _InputGroupDef(
        group="vm_access",
        label="VM Access",
        items=[
            _InputItemDef(
                key="VM_SSH_PASSWORD",
                description="VM SSH password for K3s configuration (inject via secret manager)",
                required_for="VM SSH access — K3s reset and verifier initialization",
                owner="Ops",
            ),
        ],
    ),
    _InputGroupDef(
        group="registry",
        label="Image Registry",
        items=[
            _InputItemDef(
                key="VM_REGISTRY_MIRROR",
                description=(
                    "Internal image registry URL "
                    "(e.g. http://<staging-registry-host>:5000 — replace placeholder with real host)"
                ),
                required_for="VM registry mirror configuration — all image-gated lab sessions",
                owner="Ops",
            ),
        ],
    ),
    _InputGroupDef(
        group="storage",
        label="Storage",
        items=[
            _InputItemDef(
                key="LABGEN_VERIFIER_CREDENTIAL_ROOT",
                description=(
                    "Absolute path to verifier credential root "
                    "(staging-only, chmod 700 — must not be /tmp or relative)"
                ),
                required_for="verifier credential lifecycle — all lab sessions",
                owner="Ops",
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Missing-input detection logic
# ---------------------------------------------------------------------------

def _is_input_ready(
    key: str,
    active: dict[str, str],
    acknowledged: set[str],
) -> tuple[bool, str]:
    """
    Determine whether a required input key has been set to a real value.

    Returns:
        (is_ready, reason) where reason is one of:
            "set"                 — active, non-empty, no placeholder token
            "empty"               — active but empty string
            "placeholder"         — active with a placeholder (<...>) value, or
                                    an active value that contains a <...> token, or
                                    only appears as an acknowledged commented placeholder
            "absent"              — not present in any form
    """
    if key in active:
        value = active[key]
        if not value:
            return False, "empty"
        if _PLACEHOLDER_RE.match(value):
            return False, "placeholder"
        if _VALUE_CONTAINS_PLACEHOLDER_RE.search(value):
            return False, "placeholder"
        return True, "set"
    if key in acknowledged:
        return False, "placeholder"
    return False, "absent"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class MissingInputItem:
    key: str
    status: str   # always "missing"
    reason: str   # "absent" | "empty" | "placeholder"
    description: str
    required_for: str
    owner: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "status": self.status,
            "reason": self.reason,
            "description": self.description,
            "required_for": self.required_for,
            "owner": self.owner,
        }


@dataclass
class MissingInputGroupResult:
    group: str
    label: str
    missing_items: list[MissingInputItem] = field(default_factory=list)

    @property
    def missing_count(self) -> int:
        return len(self.missing_items)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "missing_count": self.missing_count,
            "items": [i.to_dict() for i in self.missing_items],
        }


@dataclass
class MissingInputsResult:
    overall: str   # "pass" | "blocking"
    missing_count: int
    groups: dict[str, MissingInputGroupResult] = field(default_factory=dict)
    all_missing_keys: list[str] = field(default_factory=list)
    env_file: str = ""
    checked_at: str = ""

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "missing_count": self.missing_count,
            "groups": {k: v.to_dict() for k, v in self.groups.items()},
            "all_missing_keys": self.all_missing_keys,
            "env_file": self.env_file,
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# Main check function
# ---------------------------------------------------------------------------

def check_missing_inputs(env_file: str) -> MissingInputsResult:
    """
    Read env_file and report which blocking inputs are missing or placeholder.

    No network calls. No secret value printing. No filesystem side effects.

    Args:
        env_file: Path to the env file to check.

    Returns:
        MissingInputsResult with overall status, per-group results, and
        a flat list of all missing key names.

    Raises:
        FileNotFoundError: if the file does not exist.
        PermissionError: if the file cannot be read.
    """
    active, acknowledged = _parse_env_file(env_file)

    result = MissingInputsResult(
        overall="pass",
        missing_count=0,
        env_file=env_file,
        checked_at=datetime.now(tz=timezone.utc).isoformat(),
    )

    for group_def in _INPUT_GROUPS:
        group_result = MissingInputGroupResult(
            group=group_def.group,
            label=group_def.label,
        )

        for item_def in group_def.items:
            is_ready, reason = _is_input_ready(item_def.key, active, acknowledged)
            if not is_ready:
                group_result.missing_items.append(MissingInputItem(
                    key=item_def.key,
                    status="missing",
                    reason=reason,
                    description=item_def.description,
                    required_for=item_def.required_for,
                    owner=item_def.owner,
                ))

        result.groups[group_def.group] = group_result
        result.missing_count += group_result.missing_count
        result.all_missing_keys.extend(m.key for m in group_result.missing_items)

    if result.missing_count > 0:
        result.overall = "blocking"

    return result


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_COLOR_RED = "\033[91m"
_COLOR_GREEN = "\033[92m"
_RESET = "\033[0m"


def _human_output(result: MissingInputsResult, use_color: bool = True) -> None:
    def _red(text: str) -> str:
        return f"{_COLOR_RED}{text}{_RESET}" if use_color else text

    def _green(text: str) -> str:
        return f"{_COLOR_GREEN}{text}{_RESET}" if use_color else text

    print("LabGen Staging Missing Inputs")
    print("=" * 50)
    print(f"Env file : {result.env_file}")
    print(f"Checked  : {result.checked_at}")
    print()

    if result.overall == "pass":
        print(_green("All blocking inputs are set."))
        print(_green("No missing inputs — live trial rerun is not blocked by missing inputs."))
        print()
        print("Recommended next steps:")
        print(
            "  1. python scripts/labgen_staging_provisioning_validate.py "
            "--env-file <staging-env-file>"
        )
        print(
            "  2. python scripts/labgen_production_preflight.py "
            "--env-file <staging-env-file>"
        )
        print(
            "  3. python scripts/labgen_staging_dry_run.py "
            "--env-file <staging-env-file> --base-url <staging-base-url>"
        )
        return

    print(_red(f"Missing inputs: {result.missing_count} (blocking live trial rerun)"))
    print()

    for group_result in result.groups.values():
        if not group_result.missing_items:
            continue
        print(f"[{group_result.label}]  {group_result.missing_count} missing")
        for item in group_result.missing_items:
            print(f"  ✗  {item.key}  [{item.reason}]")
            print(f"       Description : {item.description}")
            print(f"       Required for: {item.required_for}")
            print(f"       Owner       : {item.owner}")
        print()

    print("To unblock — inject all missing inputs, then validate:")
    print(
        "  1. python scripts/labgen_staging_missing_inputs.py "
        "--env-file <staging-env-file>          (this script — must return exit 0)"
    )
    print(
        "  2. python scripts/labgen_staging_provisioning_validate.py "
        "--env-file <staging-env-file>"
    )
    print(
        "  3. python scripts/labgen_production_preflight.py "
        "--env-file <staging-env-file>"
    )
    print(
        "  4. python scripts/labgen_staging_dry_run.py "
        "--env-file <staging-env-file> --base-url <staging-base-url>"
    )
    print(
        "  5. python scripts/labgen_controlled_staging_trial.py "
        "--env-file <staging-env-file> --base-url <staging-base-url> [--allow-runtime-start ...]"
    )
    print()
    print(_red("MISSING INPUTS DETECTED — live trial is BLOCKED."))


def _json_output(result: MissingInputsResult) -> None:
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
        result = check_missing_inputs(env_file)
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

    return 0 if result.overall == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
