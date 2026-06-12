"""
Tests for labgen_ops_ticket_verify.py — Ops Ticket Verification Wrapper v0.1
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from labgen_ops_ticket_verify import (
    TICKET_STATUS_BLOCKED,
    TICKET_STATUS_VERIFIED,
    TicketPackVerifyResult,
    TicketVerifyResult,
    _TICKET_MAP,
    _TICKETS,
    main,
    verify_tickets,
)

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TICKET_IDS = [t.ticket_id for t in _TICKETS]


def _all_ready_env(tmp_path: Path) -> Path:
    """Create a staging env file with all 7 required keys set to non-placeholder values."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/staging/k8s/kubeconfig\n"
        "ADMIN_TOKEN=stagingadmintokenforthisenvonly1234567\n"
        "PROXMOX_HOST=staging.proxmox.example\n"
        "PROXMOX_TOKEN_ID=staging@pve!labgen-token\n"
        "PROXMOX_TOKEN_SECRET=staging-proxmox-secret-uuid-abcdefgh1234\n"
        "VM_SSH_PASSWORD=StagingVmCred2026\n"
        "VM_REGISTRY_MIRROR=http://staging.registry.example:5000\n"
    )
    return env_file


def _env_without_key(tmp_path: Path, key: str) -> Path:
    """Return env file with the given key line removed."""
    base = _all_ready_env(tmp_path)
    lines = [ln for ln in base.read_text().splitlines() if not ln.startswith(f"{key}=")]
    base.write_text("\n".join(lines) + "\n")
    return base


def _env_with_placeholder(tmp_path: Path, key: str, placeholder: str = "<set-in-secret-manager>") -> Path:
    """Return env file with the given key replaced by a placeholder value."""
    base = _all_ready_env(tmp_path)
    lines = [
        f"{key}={placeholder}" if ln.startswith(f"{key}=") else ln
        for ln in base.read_text().splitlines()
    ]
    base.write_text("\n".join(lines) + "\n")
    return base


def _env_with_empty(tmp_path: Path, key: str) -> Path:
    """Return env file with the given key set to empty string."""
    base = _all_ready_env(tmp_path)
    lines = [
        f"{key}=" if ln.startswith(f"{key}=") else ln
        for ln in base.read_text().splitlines()
    ]
    base.write_text("\n".join(lines) + "\n")
    return base


# ---------------------------------------------------------------------------
# TestTicketCoverage — ticket definitions
# ---------------------------------------------------------------------------


class TestTicketCoverage:
    def test_exactly_six_tickets_defined(self) -> None:
        expected = {
            "OPS-K3S-001",
            "OPS-AUTH-001",
            "OPS-PROXMOX-001",
            "OPS-PROXMOX-002",
            "OPS-VM-001",
            "OPS-REGISTRY-001",
        }
        assert set(_TICKET_MAP.keys()) == expected

    def test_each_ticket_has_required_fields(self) -> None:
        for ticket in _TICKETS:
            assert ticket.ticket_id, f"{ticket.ticket_id}: ticket_id empty"
            assert ticket.title, f"{ticket.ticket_id}: title empty"
            assert ticket.owner_role, f"{ticket.ticket_id}: owner_role empty"
            assert ticket.env_keys, f"{ticket.ticket_id}: env_keys empty"
            assert ticket.blocks, f"{ticket.ticket_id}: blocks empty"

    def test_ticket_ids_match_map_keys(self) -> None:
        for ticket in _TICKETS:
            assert ticket.ticket_id in _TICKET_MAP

    def test_k3s_ticket_covers_kubeconfig_key(self) -> None:
        assert "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH" in _TICKET_MAP["OPS-K3S-001"].env_keys

    def test_auth_ticket_covers_admin_token(self) -> None:
        assert "ADMIN_TOKEN" in _TICKET_MAP["OPS-AUTH-001"].env_keys

    def test_proxmox_host_ticket_covers_proxmox_host(self) -> None:
        assert "PROXMOX_HOST" in _TICKET_MAP["OPS-PROXMOX-001"].env_keys

    def test_proxmox_secret_ticket_covers_token_secret(self) -> None:
        assert "PROXMOX_TOKEN_SECRET" in _TICKET_MAP["OPS-PROXMOX-002"].env_keys

    def test_vm_ticket_covers_ssh_credential(self) -> None:
        assert "VM_SSH_PASSWORD" in _TICKET_MAP["OPS-VM-001"].env_keys

    def test_registry_ticket_covers_mirror(self) -> None:
        assert "VM_REGISTRY_MIRROR" in _TICKET_MAP["OPS-REGISTRY-001"].env_keys


# ---------------------------------------------------------------------------
# TestAllTicketsVerified — happy path
# ---------------------------------------------------------------------------


class TestAllTicketsVerified:
    def test_all_verified_with_complete_env(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        result = verify_tickets(str(env_file), _TICKET_IDS)
        assert result.all_verified
        assert result.verified_count == 6
        assert result.blocked_count == 0

    def test_each_ticket_verified_individually(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        for ticket in _TICKETS:
            result = verify_tickets(str(env_file), [ticket.ticket_id])
            assert result.tickets[0].is_verified, (
                f"{ticket.ticket_id} should be VERIFIED with complete env"
            )

    def test_all_flag_exits_zero_with_complete_env(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        code = main(["--env-file", str(env_file), "--all"])
        assert code == 0

    def test_verified_result_has_correct_counts(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        result = verify_tickets(str(env_file), _TICKET_IDS)
        assert result.verified_count + result.blocked_count == len(_TICKET_IDS)


# ---------------------------------------------------------------------------
# TestPerTicketBlocking — missing key
# ---------------------------------------------------------------------------


class TestPerTicketBlockedMissingKey:
    @pytest.mark.parametrize("ticket_id,key", [
        ("OPS-K3S-001", "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"),
        ("OPS-AUTH-001", "ADMIN_TOKEN"),
        ("OPS-PROXMOX-001", "PROXMOX_HOST"),
        ("OPS-PROXMOX-002", "PROXMOX_TOKEN_SECRET"),
        ("OPS-VM-001", "VM_SSH_PASSWORD"),
        ("OPS-REGISTRY-001", "VM_REGISTRY_MIRROR"),
    ])
    def test_ticket_blocked_when_key_absent(
        self, tmp_path: Path, ticket_id: str, key: str
    ) -> None:
        env_file = _env_without_key(tmp_path, key)
        result = verify_tickets(str(env_file), [ticket_id])
        assert result.tickets[0].status == TICKET_STATUS_BLOCKED

    @pytest.mark.parametrize("ticket_id,key", [
        ("OPS-K3S-001", "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"),
        ("OPS-AUTH-001", "ADMIN_TOKEN"),
        ("OPS-PROXMOX-001", "PROXMOX_HOST"),
        ("OPS-PROXMOX-002", "PROXMOX_TOKEN_SECRET"),
        ("OPS-VM-001", "VM_SSH_PASSWORD"),
        ("OPS-REGISTRY-001", "VM_REGISTRY_MIRROR"),
    ])
    def test_ticket_blocked_when_key_is_placeholder(
        self, tmp_path: Path, ticket_id: str, key: str
    ) -> None:
        env_file = _env_with_placeholder(tmp_path, key)
        result = verify_tickets(str(env_file), [ticket_id])
        assert result.tickets[0].status == TICKET_STATUS_BLOCKED

    @pytest.mark.parametrize("ticket_id,key", [
        ("OPS-K3S-001", "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"),
        ("OPS-AUTH-001", "ADMIN_TOKEN"),
        ("OPS-PROXMOX-001", "PROXMOX_HOST"),
        ("OPS-PROXMOX-002", "PROXMOX_TOKEN_SECRET"),
        ("OPS-VM-001", "VM_SSH_PASSWORD"),
        ("OPS-REGISTRY-001", "VM_REGISTRY_MIRROR"),
    ])
    def test_ticket_blocked_when_key_is_empty(
        self, tmp_path: Path, ticket_id: str, key: str
    ) -> None:
        env_file = _env_with_empty(tmp_path, key)
        result = verify_tickets(str(env_file), [ticket_id])
        assert result.tickets[0].status == TICKET_STATUS_BLOCKED


# ---------------------------------------------------------------------------
# TestFormatChecks — format-specific blocking
# ---------------------------------------------------------------------------


class TestFormatChecks:
    def test_admin_token_too_short_blocks_auth_ticket(self, tmp_path: Path) -> None:
        base = _all_ready_env(tmp_path)
        lines = [
            "ADMIN_TOKEN=short" if ln.startswith("ADMIN_TOKEN=") else ln
            for ln in base.read_text().splitlines()
        ]
        base.write_text("\n".join(lines) + "\n")
        result = verify_tickets(str(base), ["OPS-AUTH-001"])
        assert result.tickets[0].status == TICKET_STATUS_BLOCKED

    def test_registry_mirror_without_scheme_blocks_registry_ticket(self, tmp_path: Path) -> None:
        base = _all_ready_env(tmp_path)
        lines = [
            "VM_REGISTRY_MIRROR=staging.registry.example:5000" if ln.startswith("VM_REGISTRY_MIRROR=") else ln
            for ln in base.read_text().splitlines()
        ]
        base.write_text("\n".join(lines) + "\n")
        result = verify_tickets(str(base), ["OPS-REGISTRY-001"])
        assert result.tickets[0].status == TICKET_STATUS_BLOCKED

    def test_registry_mirror_with_https_scheme_is_verified(self, tmp_path: Path) -> None:
        base = _all_ready_env(tmp_path)
        lines = [
            "VM_REGISTRY_MIRROR=https://staging.registry.example:5000"
            if ln.startswith("VM_REGISTRY_MIRROR=")
            else ln
            for ln in base.read_text().splitlines()
        ]
        base.write_text("\n".join(lines) + "\n")
        result = verify_tickets(str(base), ["OPS-REGISTRY-001"])
        assert result.tickets[0].status == TICKET_STATUS_VERIFIED


# ---------------------------------------------------------------------------
# TestAllFlag — --all behaviour
# ---------------------------------------------------------------------------


class TestAllFlag:
    def test_all_with_complete_env_exits_zero(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        assert main(["--env-file", str(env_file), "--all"]) == 0

    def test_all_with_partial_missing_exits_one(self, tmp_path: Path) -> None:
        env_file = _env_without_key(tmp_path, "ADMIN_TOKEN")
        assert main(["--env-file", str(env_file), "--all"]) == 1

    def test_all_with_json_exits_zero(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        assert main(["--env-file", str(env_file), "--all", "--json"]) == 0

    def test_all_selects_all_six_tickets(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        result = verify_tickets(str(env_file), _TICKET_IDS)
        assert len(result.tickets) == 6

    def test_all_with_multiple_missing_returns_correct_counts(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env.staging"
        # PROXMOX_TOKEN_ID is not a ticket key, so providing it verifies nothing.
        # PROXMOX_HOST=<staging-host> is placeholder → OPS-PROXMOX-001 BLOCKED.
        # All other ticket keys are absent → all 6 tickets BLOCKED.
        env_file.write_text(
            "PROXMOX_HOST=<staging-host>\n"
            "PROXMOX_TOKEN_ID=staging@pve!test\n"
        )
        result = verify_tickets(str(env_file), _TICKET_IDS)
        assert result.blocked_count == 6
        assert result.verified_count == 0


# ---------------------------------------------------------------------------
# TestExitCodes
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_unknown_ticket_returns_exit_2(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        assert main(["--env-file", str(env_file), "--ticket", "OPS-UNKNOWN-999"]) == 2

    def test_nonexistent_env_file_returns_exit_2(self, tmp_path: Path) -> None:
        assert main(["--env-file", str(tmp_path / "nonexistent.env"), "--all"]) == 2

    def test_missing_env_flag_returns_exit_2(self) -> None:
        assert main(["--all"]) == 2

    def test_no_ticket_and_no_all_returns_exit_2(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        assert main(["--env-file", str(env_file)]) == 2

    def test_verify_tickets_raises_for_unknown_id(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        with pytest.raises(ValueError, match="Unknown ticket ID"):
            verify_tickets(str(env_file), ["OPS-UNKNOWN-999"])

    def test_single_verified_ticket_exits_zero(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        assert main(["--env-file", str(env_file), "--ticket", "OPS-K3S-001"]) == 0

    def test_single_blocked_ticket_exits_one(self, tmp_path: Path) -> None:
        env_file = _env_without_key(tmp_path, "ADMIN_TOKEN")
        assert main(["--env-file", str(env_file), "--ticket", "OPS-AUTH-001"]) == 1


# ---------------------------------------------------------------------------
# TestJsonSchema — JSON output structure
# ---------------------------------------------------------------------------


class TestJsonSchema:
    def test_json_output_top_level_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        main(["--env-file", str(env_file), "--all", "--json"])
        out = capsys.readouterr().out
        data: dict[str, Any] = json.loads(out)

        assert "checked_at" in data
        assert "env_file" in data
        assert "summary" in data
        assert "tickets" in data
        assert "all_warnings" in data

    def test_json_summary_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        main(["--env-file", str(env_file), "--all", "--json"])
        out = capsys.readouterr().out
        summary = json.loads(out)["summary"]

        assert summary["total"] == 6
        assert summary["verified"] == 6
        assert summary["blocked"] == 0
        assert summary["all_verified"] is True

    def test_json_ticket_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        main(["--env-file", str(env_file), "--ticket", "OPS-K3S-001", "--json"])
        out = capsys.readouterr().out
        ticket = json.loads(out)["tickets"][0]

        assert "ticket_id" in ticket
        assert "title" in ticket
        assert "owner_role" in ticket
        assert "status" in ticket
        assert "env_keys" in ticket
        assert "blocking_issues" in ticket
        assert "warnings" in ticket
        assert "validation_commands" in ticket
        assert "next_step" in ticket

    def test_json_blocked_ticket_contains_blocking_issues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _env_without_key(tmp_path, "ADMIN_TOKEN")
        main(["--env-file", str(env_file), "--ticket", "OPS-AUTH-001", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        ticket = data["tickets"][0]
        assert ticket["status"] == TICKET_STATUS_BLOCKED
        assert len(ticket["blocking_issues"]) > 0

    def test_json_schema_stable_across_runs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        main(["--env-file", str(env_file), "--ticket", "OPS-PROXMOX-001", "--json"])
        out1 = capsys.readouterr().out
        main(["--env-file", str(env_file), "--ticket", "OPS-PROXMOX-001", "--json"])
        out2 = capsys.readouterr().out

        d1, d2 = json.loads(out1), json.loads(out2)
        assert set(d1.keys()) == set(d2.keys())
        assert d1["summary"] == d2["summary"]


# ---------------------------------------------------------------------------
# TestSecretNotPrinted — security assertions
# ---------------------------------------------------------------------------


class TestSecretNotPrinted:
    def test_json_output_does_not_print_secret_values(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        env_content = env_file.read_text()

        actual_values = []
        for line in env_content.splitlines():
            if "=" in line and not line.startswith("#"):
                _, _, val = line.partition("=")
                if val and not val.startswith("<") and len(val) > 10:
                    actual_values.append(val)

        main(["--env-file", str(env_file), "--all", "--json"])
        out = capsys.readouterr().out

        for val in actual_values:
            assert val not in out, "Secret value appeared in JSON output"

    def test_human_output_does_not_print_ssh_credential(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        ssh_cred = "StagingVmCred2026"
        main(["--env-file", str(env_file), "--all"])
        out = capsys.readouterr().out
        assert ssh_cred not in out

    def test_human_output_does_not_print_admin_token(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        admin_tok = "stagingadmintokenforthisenvonly1234567"
        main(["--env-file", str(env_file), "--all"])
        out = capsys.readouterr().out
        assert admin_tok not in out

    def test_human_output_does_not_print_proxmox_secret(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        proxmox_sec = "staging-proxmox-secret-uuid-abcdefgh1234"
        main(["--env-file", str(env_file), "--all"])
        out = capsys.readouterr().out
        assert proxmox_sec not in out


# ---------------------------------------------------------------------------
# TestNoNetworkCalls — offline guarantee
# ---------------------------------------------------------------------------


class TestNoNetworkCalls:
    def test_no_socket_connection_made(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _no_connect(self: Any, address: Any) -> None:  # noqa: ANN001
            raise AssertionError(f"Unexpected network call to {address}")

        monkeypatch.setattr(socket.socket, "connect", _no_connect)

        env_file = _all_ready_env(tmp_path)
        result = verify_tickets(str(env_file), _TICKET_IDS)
        assert result is not None

    def test_no_socket_connection_with_blocked_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _no_connect(self: Any, address: Any) -> None:  # noqa: ANN001
            raise AssertionError(f"Unexpected network call to {address}")

        monkeypatch.setattr(socket.socket, "connect", _no_connect)

        env_file = tmp_path / ".env.staging"
        env_file.write_text(
            "PROXMOX_HOST=<staging-host>\n"
            "VM_REGISTRY_MIRROR=http://<staging-host>:5000\n"
        )
        result = verify_tickets(str(env_file), _TICKET_IDS)
        assert result.blocked_count > 0


# ---------------------------------------------------------------------------
# TestHumanOutput — text output
# ---------------------------------------------------------------------------


class TestHumanOutput:
    def test_human_output_shows_all_ticket_ids(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        main(["--env-file", str(env_file), "--all"])
        out = capsys.readouterr().out
        for ticket in _TICKETS:
            assert ticket.ticket_id in out

    def test_human_output_shows_blocked_status(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _env_with_placeholder(tmp_path, "PROXMOX_HOST")
        main(["--env-file", str(env_file), "--ticket", "OPS-PROXMOX-001"])
        out = capsys.readouterr().out
        assert TICKET_STATUS_BLOCKED in out

    def test_human_output_shows_verified_status(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        main(["--env-file", str(env_file), "--ticket", "OPS-K3S-001"])
        out = capsys.readouterr().out
        assert TICKET_STATUS_VERIFIED in out

    def test_human_output_shows_summary_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        main(["--env-file", str(env_file), "--all"])
        out = capsys.readouterr().out
        assert "Summary:" in out

    def test_human_output_all_verified_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env_file = _all_ready_env(tmp_path)
        main(["--env-file", str(env_file), "--all"])
        out = capsys.readouterr().out
        assert "ALL TICKETS VERIFIED" in out


# ---------------------------------------------------------------------------
# TestResultModel — TicketPackVerifyResult properties
# ---------------------------------------------------------------------------


class TestResultModel:
    def test_all_verified_false_when_no_tickets(self) -> None:
        r = TicketPackVerifyResult(checked_at="t", env_file="f", tickets=[], all_warnings=[])
        assert r.all_verified is False

    def test_all_verified_true_when_all_pass(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        result = verify_tickets(str(env_file), _TICKET_IDS)
        assert result.all_verified is True

    def test_blocked_count_increments_per_missing(self, tmp_path: Path) -> None:
        env_file = _env_without_key(tmp_path, "ADMIN_TOKEN")
        result = verify_tickets(str(env_file), _TICKET_IDS)
        assert result.blocked_count == 1
        assert result.verified_count == 5

    def test_to_dict_is_json_serializable(self, tmp_path: Path) -> None:
        env_file = _all_ready_env(tmp_path)
        result = verify_tickets(str(env_file), _TICKET_IDS)
        serialized = json.dumps(result.to_dict())
        parsed = json.loads(serialized)
        assert parsed["summary"]["total"] == 6
