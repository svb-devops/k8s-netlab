#!/usr/bin/env python3
"""
LabGen Ops Ticket Verification Wrapper v0.1
===========================================
Offline per-ticket static verification for the 6 ops provisioning tickets
required to unblock the Controlled Staging Trial Live Run.

Reads a staging env file and reports whether each ticket's required env/config
is present, non-placeholder, and passes basic format checks.

STATIC verification only — no network calls, no connections to K3s/Proxmox/registry.

Tickets:
  OPS-K3S-001      Provision staging K3s kubeconfig / service account
  OPS-AUTH-001     Inject staging ADMIN_TOKEN
  OPS-PROXMOX-001  Configure staging PROXMOX_HOST
  OPS-PROXMOX-002  Inject staging PROXMOX_TOKEN_SECRET
  OPS-VM-001       Inject staging VM SSH credential
  OPS-REGISTRY-001 Configure staging VM_REGISTRY_MIRROR

Usage:
  python scripts/labgen_ops_ticket_verify.py \\
      --env-file <staging-env-file> --all [--json]
  python scripts/labgen_ops_ticket_verify.py \\
      --env-file <staging-env-file> --ticket OPS-K3S-001 [--json]

Exit codes:
  0  all selected ticket(s) VERIFIED
  1  one or more selected ticket(s) BLOCKED
  2  invalid invocation or unreadable env file
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from labgen_ops_secret_injection_verify import (  # noqa: E402
    STATUS_PRESENT_REDACTED,
    verify_secret_injection,
)

# ---------------------------------------------------------------------------
# Ticket status labels
# ---------------------------------------------------------------------------

TICKET_STATUS_VERIFIED = "VERIFIED"
TICKET_STATUS_BLOCKED = "BLOCKED"

# ---------------------------------------------------------------------------
# Ticket definitions
# ---------------------------------------------------------------------------


@dataclass
class _TicketDef:
    ticket_id: str
    title: str
    owner_role: str
    env_keys: list[str]
    blocks: str
    notes: str = ""


_TICKETS: list[_TicketDef] = [
    _TicketDef(
        ticket_id="OPS-K3S-001",
        title="Provision staging K3s kubeconfig / service account",
        owner_role="Infra / K8s Ops",
        env_keys=["LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"],
        blocks="LabGen lab-session start (K3s namespace lifecycle)",
        notes=(
            "Inject the absolute path to the staging kubeconfig file. "
            "Never commit kubeconfig content. Use RBAC minimum-privilege SA."
        ),
    ),
    _TicketDef(
        ticket_id="OPS-AUTH-001",
        title="Inject staging ADMIN_TOKEN",
        owner_role="Security / Ops",
        env_keys=["ADMIN_TOKEN"],
        blocks="Admin diagnostics and intake gate base-url health check",
        notes="Must be >= 32 random characters. Inject via secret manager.",
    ),
    _TicketDef(
        ticket_id="OPS-PROXMOX-001",
        title="Configure staging PROXMOX_HOST",
        owner_role="Infra / Proxmox Ops",
        env_keys=["PROXMOX_HOST"],
        blocks="Proxmox API VM provisioning calls",
        notes="Staging-only Proxmox host. Must not be the production host.",
    ),
    _TicketDef(
        ticket_id="OPS-PROXMOX-002",
        title="Inject staging PROXMOX_TOKEN_SECRET",
        owner_role="Security / Proxmox Ops",
        env_keys=["PROXMOX_TOKEN_SECRET"],
        blocks="Proxmox API authentication",
        notes=(
            "UUID-format token secret. "
            "Create a staging-only Proxmox API token. Inject via secret manager."
        ),
    ),
    _TicketDef(
        ticket_id="OPS-VM-001",
        title="Inject staging VM SSH credential",
        owner_role="Infra / VM Ops",
        env_keys=["VM_SSH_PASSWORD"],
        blocks="K3s configuration via SSH post-VM-clone",
        notes=(
            "Inject staging SSH credential via secret manager. "
            "If SSH key is used instead, note the mechanism — never commit private key."
        ),
    ),
    _TicketDef(
        ticket_id="OPS-REGISTRY-001",
        title="Configure staging VM_REGISTRY_MIRROR",
        owner_role="Infra / Registry Ops",
        env_keys=["VM_REGISTRY_MIRROR"],
        blocks="Image pull during lab-session namespace creation",
        notes=(
            "Must start with http:// or https://. "
            "Registry must be staging-isolated. Required images must be pre-loaded."
        ),
    ),
]

_TICKET_MAP: dict[str, _TicketDef] = {t.ticket_id: t for t in _TICKETS}

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class TicketVerifyResult:
    ticket_id: str
    title: str
    owner_role: str
    status: str  # VERIFIED | BLOCKED
    env_keys: list[str]
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    next_step: str = ""

    @property
    def is_verified(self) -> bool:
        return self.status == TICKET_STATUS_VERIFIED

    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "title": self.title,
            "owner_role": self.owner_role,
            "status": self.status,
            "env_keys": self.env_keys,
            "blocking_issues": self.blocking_issues,
            "warnings": self.warnings,
            "validation_commands": self.validation_commands,
            "next_step": self.next_step,
        }


@dataclass
class TicketPackVerifyResult:
    checked_at: str
    env_file: str
    tickets: list[TicketVerifyResult] = field(default_factory=list)
    all_warnings: list[str] = field(default_factory=list)

    @property
    def verified_count(self) -> int:
        return sum(1 for t in self.tickets if t.is_verified)

    @property
    def blocked_count(self) -> int:
        return sum(1 for t in self.tickets if not t.is_verified)

    @property
    def all_verified(self) -> bool:
        return len(self.tickets) > 0 and self.blocked_count == 0

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "env_file": self.env_file,
            "summary": {
                "total": len(self.tickets),
                "verified": self.verified_count,
                "blocked": self.blocked_count,
                "all_verified": self.all_verified,
            },
            "tickets": [t.to_dict() for t in self.tickets],
            "all_warnings": self.all_warnings,
        }


# ---------------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------------


def verify_tickets(
    env_file: str,
    ticket_ids: list[str],
) -> TicketPackVerifyResult:
    """
    Verify the specified provisioning tickets by checking env key presence offline.

    No network calls. No secret value printing.

    Args:
        env_file: Path to staging env file.
        ticket_ids: List of ticket IDs to check. All must be known ticket IDs.

    Returns:
        TicketPackVerifyResult with per-ticket status.

    Raises:
        ValueError: unknown ticket_id in ticket_ids
        FileNotFoundError: env file does not exist
        PermissionError: env file cannot be read
    """
    for tid in ticket_ids:
        if tid not in _TICKET_MAP:
            raise ValueError(f"Unknown ticket ID: {tid!r}")

    inj_result = verify_secret_injection(env_file)
    key_map = {kv.key: kv for kv in inj_result.keys}

    ticket_results: list[TicketVerifyResult] = []
    all_warnings: list[str] = []

    for ticket_id in ticket_ids:
        ticket_def = _TICKET_MAP[ticket_id]
        blocking_issues: list[str] = []
        ticket_warnings: list[str] = []

        for key_name in ticket_def.env_keys:
            kv = key_map.get(key_name)
            if kv is None:
                blocking_issues.append(f"{key_name}: not found in verification scope")
            elif not kv.is_ready:
                blocking_issues.extend(kv.blocking_details)
            if kv is not None:
                ticket_warnings.extend(kv.warnings)

        status = TICKET_STATUS_VERIFIED if not blocking_issues else TICKET_STATUS_BLOCKED

        if status == TICKET_STATUS_VERIFIED:
            next_step = (
                f"{ticket_id} VERIFIED. "
                "Re-run full verification: "
                "python scripts/labgen_ops_ticket_verify.py "
                "--env-file <staging-env-file> --all"
            )
        else:
            next_step = (
                f"{ticket_id} BLOCKED — inject required secrets via secret manager, then: "
                "python scripts/labgen_ops_ticket_verify.py "
                f"--env-file <staging-env-file> --ticket {ticket_id}"
            )

        tvr = TicketVerifyResult(
            ticket_id=ticket_id,
            title=ticket_def.title,
            owner_role=ticket_def.owner_role,
            status=status,
            env_keys=ticket_def.env_keys,
            blocking_issues=blocking_issues,
            warnings=ticket_warnings,
            validation_commands=[
                "python scripts/labgen_ops_secret_injection_verify.py "
                "--env-file <staging-env-file> --json",
                "python scripts/labgen_ops_staging_intake_verify.py "
                "--env-file <staging-env-file> --base-url <staging-base-url> --json",
            ],
            next_step=next_step,
        )
        ticket_results.append(tvr)
        all_warnings.extend(ticket_warnings)

    return TicketPackVerifyResult(
        checked_at=inj_result.checked_at,
        env_file=env_file,
        tickets=ticket_results,
        all_warnings=list(dict.fromkeys(all_warnings)),
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_COLOR_RED = "\033[91m"
_COLOR_GREEN = "\033[92m"
_COLOR_YELLOW = "\033[93m"
_RESET = "\033[0m"


def _human_output(result: TicketPackVerifyResult, use_color: bool = True) -> None:
    def _c(color: str, text: str) -> str:
        return f"{color}{text}{_RESET}" if use_color and color else text

    print("LabGen Ops Ticket Verification Wrapper v0.1")
    print("=" * 52)
    print(f"Env file : {result.env_file}")
    print(f"Checked  : {result.checked_at}")
    print()

    for ticket in result.tickets:
        color = _COLOR_GREEN if ticket.is_verified else _COLOR_RED
        print(_c(color, f"[{ticket.ticket_id}] {ticket.title}"))
        print(f"  Owner  : {ticket.owner_role}")
        print(f"  Status : {_c(color, ticket.status)}")
        for issue in ticket.blocking_issues:
            print(f"  {_c(_COLOR_RED, '→')} {issue}")
        for w in ticket.warnings:
            print(f"  {_c(_COLOR_YELLOW, '⚠')} {w}")
        print(f"  Next   : {ticket.next_step}")
        print()

    overall_color = _COLOR_GREEN if result.all_verified else _COLOR_RED
    print(_c(overall_color, f"Summary: {result.verified_count}/{len(result.tickets)} VERIFIED"))
    if result.all_verified:
        print(_c(_COLOR_GREEN, "ALL TICKETS VERIFIED — re-run secret injection verification."))
    else:
        print(
            _c(
                _COLOR_RED,
                f"{result.blocked_count} ticket(s) BLOCKED — inject required secrets first.",
            )
        )


def _json_output(result: TicketPackVerifyResult) -> None:
    print(json.dumps(result.to_dict(), indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(
    argv: list[str],
) -> tuple[Optional[str], list[str], bool, bool]:
    """Return (env_file, ticket_ids, use_json, all_tickets)."""
    env_file: Optional[str] = None
    ticket_ids: list[str] = []
    use_json = False
    all_tickets = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--json":
            use_json = True
        elif arg == "--all":
            all_tickets = True
        elif arg in ("--env-file", "-e") and i + 1 < len(argv):
            i += 1
            env_file = argv[i]
        elif arg.startswith("--env-file="):
            env_file = arg.split("=", 1)[1]
        elif arg in ("--ticket", "-t") and i + 1 < len(argv):
            i += 1
            ticket_ids.append(argv[i])
        elif arg.startswith("--ticket="):
            ticket_ids.append(arg.split("=", 1)[1])
        i += 1

    return env_file, ticket_ids, use_json, all_tickets


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    env_file, ticket_ids, use_json, all_tickets = _parse_args(argv)

    if not env_file:
        print(
            "Error: --env-file <path> is required.\n"
            "Usage: python scripts/labgen_ops_ticket_verify.py "
            "--env-file <staging-env-file> (--all | --ticket <ID>) [--json]",
            file=sys.stderr,
        )
        return 2

    if not all_tickets and not ticket_ids:
        print(
            "Error: specify --all or --ticket <ID>.\n"
            f"Available tickets: {', '.join(_TICKET_MAP.keys())}",
            file=sys.stderr,
        )
        return 2

    if all_tickets:
        ticket_ids = [t.ticket_id for t in _TICKETS]

    for tid in ticket_ids:
        if tid not in _TICKET_MAP:
            print(f"Error: unknown ticket ID '{tid}'.", file=sys.stderr)
            print(f"Available: {', '.join(_TICKET_MAP.keys())}", file=sys.stderr)
            return 2

    try:
        result = verify_tickets(env_file, ticket_ids)
    except FileNotFoundError:
        print(f"ERROR: env file not found: {env_file}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"ERROR: cannot read env file: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: unexpected error: {exc}", file=sys.stderr)
        return 2

    if use_json:
        _json_output(result)
    else:
        _human_output(result)

    return 0 if result.all_verified else 1


if __name__ == "__main__":
    sys.exit(main())
