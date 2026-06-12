"""
Tests for scripts/labgen_ops_secret_injection_verify.py

Coverage targets:
  - all 6 (+1) keys present and non-placeholder → SECRET_INJECTION_READY
  - missing key → SECRET_INJECTION_BLOCKED
  - placeholder key (acknowledged) → blocked / PLACEHOLDER status
  - placeholder token in value → blocked / PLACEHOLDER status
  - empty string value → blocked / EMPTY status
  - INVALID_FORMAT: ADMIN_TOKEN < 32 chars → blocked
  - INVALID_FORMAT: VM_REGISTRY_MIRROR not http(s):// → blocked
  - PROXMOX_TOKEN_ID present with valid value → PRESENT_REDACTED
  - production-marker warning → warning emitted, not blocking
  - secret values never printed
  - kubeconfig path value not printed beyond redacted summary
  - JSON output schema stable
  - unreadable env file → exit code 2
  - missing --env-file arg → exit code 2
  - no network calls in any test
"""

from __future__ import annotations

import json
import os
import sys
from io import StringIO
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure scripts/ is on the path
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = str(Path(__file__).parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from labgen_ops_secret_injection_verify import (  # noqa: E402
    _DECISION_READY,
    _DECISION_BLOCKED,
    STATUS_PRESENT_REDACTED,
    STATUS_MISSING,
    STATUS_PLACEHOLDER,
    STATUS_EMPTY,
    STATUS_INVALID_FORMAT,
    KeyVerificationResult,
    SecretInjectionResult,
    verify_secret_injection,
    main,
    _human_output,
    _json_output,
)

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENV_EXAMPLE = str(
    Path(__file__).parent.parent / "deploy" / "labgen" / ".env.staging.example"
)


def _write_env(tmp_path: Path, lines: list[str]) -> str:
    f = tmp_path / ".env.test"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(f)


def _all_ready_env(tmp_path: Path, overrides: dict[str, str] | None = None) -> str:
    """Create an env file where all 7 required keys have valid values."""
    base = {
        "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": "/var/lib/labgen-staging/kubeconfig.yaml",
        "ADMIN_TOKEN": "a" * 32,
        "PROXMOX_HOST": "staging-proxmox.internal",
        "PROXMOX_TOKEN_ID": "labgen-staging@pve!labgen-staging-api",
        "PROXMOX_TOKEN_SECRET": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "VM_SSH_PASSWORD": "Stag1ng$Password!",
        "VM_REGISTRY_MIRROR": "http://staging-registry.internal:5000",
    }
    if overrides:
        base.update(overrides)
    lines = [f"{k}={v}" for k, v in base.items()]
    return _write_env(tmp_path, lines)


# ---------------------------------------------------------------------------
# Env example (staging template) — always BLOCKED
# ---------------------------------------------------------------------------


class TestEnvExampleBlocked:
    def test_decision_is_blocked(self):
        result = verify_secret_injection(_ENV_EXAMPLE)
        assert result.decision == _DECISION_BLOCKED

    def test_blocked_keys_include_all_six(self):
        result = verify_secret_injection(_ENV_EXAMPLE)
        blocked = set(result.all_blocking_keys)
        expected = {
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH",
            "ADMIN_TOKEN",
            "PROXMOX_HOST",
            "PROXMOX_TOKEN_SECRET",
            "VM_SSH_PASSWORD",
            "VM_REGISTRY_MIRROR",
        }
        # All 6 original blocking inputs must remain blocked
        assert expected.issubset(blocked), (
            f"Expected all 6 inputs to be blocked; got: {blocked}"
        )

    def test_proxmox_token_id_present_redacted(self):
        # PROXMOX_TOKEN_ID has a non-placeholder value in the example
        result = verify_secret_injection(_ENV_EXAMPLE)
        kv = next(k for k in result.keys if k.key == "PROXMOX_TOKEN_ID")
        assert kv.status == STATUS_PRESENT_REDACTED

    def test_ready_count_is_one(self):
        # Only PROXMOX_TOKEN_ID should be ready in the example
        result = verify_secret_injection(_ENV_EXAMPLE)
        assert result.ready_count == 1

    def test_exit_code_one(self):
        code = main(["--env-file", _ENV_EXAMPLE])
        assert code == 1


# ---------------------------------------------------------------------------
# All keys ready → SECRET_INJECTION_READY
# ---------------------------------------------------------------------------


class TestAllReady:
    def test_decision_ready(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        assert result.decision == _DECISION_READY

    def test_no_blocking_keys(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        assert result.all_blocking_keys == []

    def test_ready_count_equals_total(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        assert result.ready_count == len(result.keys)

    def test_exit_code_zero(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path)
        code = main(["--env-file", env_file])
        assert code == 0

    def test_all_statuses_present_redacted(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        for kv in result.keys:
            assert kv.status == STATUS_PRESENT_REDACTED, (
                f"{kv.key} expected PRESENT_REDACTED, got {kv.status}"
            )


# ---------------------------------------------------------------------------
# Missing key → MISSING status
# ---------------------------------------------------------------------------


class TestMissingKey:
    def test_missing_admin_token(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path, overrides={"ADMIN_TOKEN": None})
        # Write without that key
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        assert result.decision == _DECISION_BLOCKED
        kv = next(k for k in result.keys if k.key == "ADMIN_TOKEN")
        assert kv.status == STATUS_MISSING
        assert "ADMIN_TOKEN" in result.all_blocking_keys

    def test_missing_proxmox_host(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "PROXMOX_HOST")
        assert kv.status == STATUS_MISSING
        assert "PROXMOX_HOST" in result.all_blocking_keys


# ---------------------------------------------------------------------------
# Placeholder values → PLACEHOLDER status
# ---------------------------------------------------------------------------


class TestPlaceholderKey:
    def test_angle_bracket_placeholder_in_value(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path, overrides={"PROXMOX_HOST": "<staging-host>"})
        # re-write with that override
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=<staging-host>",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "PROXMOX_HOST")
        assert kv.status == STATUS_PLACEHOLDER
        assert "PROXMOX_HOST" in result.all_blocking_keys

    def test_registry_mirror_with_placeholder_host(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://<staging-host>:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "VM_REGISTRY_MIRROR")
        assert kv.status == STATUS_PLACEHOLDER
        assert "VM_REGISTRY_MIRROR" in result.all_blocking_keys

    def test_acknowledged_placeholder_kubeconfig(self, tmp_path: Path):
        # Kubeconfig commented out — acknowledged placeholder
        lines = [
            "# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-staging-secret-manager>",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH")
        assert kv.status == STATUS_PLACEHOLDER
        assert "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH" in result.all_blocking_keys


# ---------------------------------------------------------------------------
# Empty string value → EMPTY status
# ---------------------------------------------------------------------------


class TestEmptyValue:
    def test_empty_vm_ssh_password(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=",  # empty
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "VM_SSH_PASSWORD")
        assert kv.status == STATUS_EMPTY
        assert "VM_SSH_PASSWORD" in result.all_blocking_keys
        assert result.decision == _DECISION_BLOCKED

    def test_empty_admin_token(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=",
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "ADMIN_TOKEN")
        assert kv.status == STATUS_EMPTY


# ---------------------------------------------------------------------------
# INVALID_FORMAT
# ---------------------------------------------------------------------------


class TestInvalidFormat:
    def test_admin_token_too_short(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=shorttoken",  # < 32 chars
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "ADMIN_TOKEN")
        assert kv.status == STATUS_INVALID_FORMAT
        assert "ADMIN_TOKEN" in result.all_blocking_keys
        assert result.decision == _DECISION_BLOCKED

    def test_admin_token_exactly_32_chars_passes(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path, overrides={"ADMIN_TOKEN": "x" * 32})
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "x" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "ADMIN_TOKEN")
        assert kv.status == STATUS_PRESENT_REDACTED

    def test_registry_mirror_missing_scheme(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=staging-registry.internal:5000",  # no scheme
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "VM_REGISTRY_MIRROR")
        assert kv.status == STATUS_INVALID_FORMAT
        assert "VM_REGISTRY_MIRROR" in result.all_blocking_keys

    def test_registry_mirror_https_passes(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=https://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "VM_REGISTRY_MIRROR")
        assert kv.status == STATUS_PRESENT_REDACTED


# ---------------------------------------------------------------------------
# Secret values are never printed
# ---------------------------------------------------------------------------


class TestSecretNotPrinted:
    def test_human_output_does_not_print_values(self, tmp_path: Path, capsys):
        secret_value = "super-secret-token-do-not-print-12345"
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            f"ADMIN_TOKEN={secret_value}",
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        _human_output(result, use_color=False)
        out, _ = capsys.readouterr()
        assert secret_value not in out

    def test_json_output_does_not_print_values(self, tmp_path: Path, capsys):
        secret_value = "proxmox-secret-uuid-should-not-appear-9876"
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            f"PROXMOX_TOKEN_SECRET={secret_value}",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        _json_output(result)
        out, _ = capsys.readouterr()
        assert secret_value not in out

    def test_kubeconfig_path_value_not_printed_in_json(self, tmp_path: Path, capsys):
        kubeconfig_path = "/var/lib/labgen-staging/super-secret-kubeconfig.yaml"
        lines = [
            f"LABGEN_K8S_PLATFORM_KUBECONFIG_PATH={kubeconfig_path}",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        _json_output(result)
        out, _ = capsys.readouterr()
        assert kubeconfig_path not in out

    def test_human_output_does_not_print_vm_password(self, tmp_path: Path, capsys):
        vm_pw = "Stag!ng-P4ssw0rd-Secret-9999"
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            f"VM_SSH_PASSWORD={vm_pw}",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        _human_output(result, use_color=False)
        out, _ = capsys.readouterr()
        assert vm_pw not in out


# ---------------------------------------------------------------------------
# Production-marker warning (not blocking)
# ---------------------------------------------------------------------------


class TestProductionMarkerWarning:
    def test_production_domain_in_registry_emits_warning(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            # VM_REGISTRY_MIRROR points at production domain — should warn, not block
            "VM_REGISTRY_MIRROR=http://lab.cloudnetops.tech:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        # Still PRESENT_REDACTED (not blocking)
        kv = next(k for k in result.keys if k.key == "VM_REGISTRY_MIRROR")
        assert kv.status == STATUS_PRESENT_REDACTED
        # But a warning should be emitted
        assert len(kv.warnings) > 0
        assert len(result.all_warnings) > 0

    def test_production_marker_does_not_block_decision(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=labgen-staging@pve!labgen-staging-api",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://lab.cloudnetops.tech:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        # Even with the production domain marker, decision should be READY (warning only)
        assert result.decision == _DECISION_READY


# ---------------------------------------------------------------------------
# JSON output schema stability
# ---------------------------------------------------------------------------


class TestJsonSchema:
    def test_json_schema_required_top_level_keys(self, tmp_path: Path, capsys):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        _json_output(result)
        out, _ = capsys.readouterr()
        data = json.loads(out)

        for key in ("decision", "checked_at", "env_file", "summary", "keys",
                    "all_blocking_keys", "all_warnings", "next_step"):
            assert key in data, f"Missing top-level key: {key}"

    def test_json_schema_summary_fields(self, tmp_path: Path, capsys):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        _json_output(result)
        out, _ = capsys.readouterr()
        data = json.loads(out)
        assert "total" in data["summary"]
        assert "ready" in data["summary"]
        assert "blocked" in data["summary"]

    def test_json_schema_per_key_fields(self, tmp_path: Path, capsys):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        _json_output(result)
        out, _ = capsys.readouterr()
        data = json.loads(out)
        for kobj in data["keys"]:
            for field in ("key", "status", "category", "owner", "description",
                          "blocking_details", "warnings"):
                assert field in kobj, f"Missing per-key field: {field}"

    def test_json_decision_values_are_stable(self, tmp_path: Path):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        assert result.decision == "SECRET_INJECTION_READY"

    def test_json_blocked_decision_value(self):
        result = verify_secret_injection(_ENV_EXAMPLE)
        assert result.decision == "SECRET_INJECTION_BLOCKED"

    def test_json_status_labels_are_stable(self, tmp_path: Path, capsys):
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        _json_output(result)
        out, _ = capsys.readouterr()
        data = json.loads(out)
        # All ready → all should be PRESENT_REDACTED
        for kobj in data["keys"]:
            assert kobj["status"] == "PRESENT_REDACTED"

    def test_json_blocked_statuses_appear(self, capsys):
        result = verify_secret_injection(_ENV_EXAMPLE)
        _json_output(result)
        out, _ = capsys.readouterr()
        data = json.loads(out)
        statuses = {kobj["status"] for kobj in data["keys"]}
        # At least one PLACEHOLDER should appear (most blocked keys are acknowledged)
        assert "PLACEHOLDER" in statuses or "MISSING" in statuses


# ---------------------------------------------------------------------------
# CLI invocation errors
# ---------------------------------------------------------------------------


class TestCLIErrors:
    def test_missing_env_file_arg_exit_2(self, capsys):
        code = main([])
        assert code == 2

    def test_nonexistent_env_file_exit_2(self, tmp_path: Path):
        code = main(["--env-file", str(tmp_path / "nonexistent.env")])
        assert code == 2

    def test_unreadable_env_file_exit_2(self, tmp_path: Path):
        # Root bypasses file-permission checks, so simulate unreadability by
        # patching the imported reference inside the script module.
        import unittest.mock as mock_mod
        from pathlib import Path as _Path
        target = str(tmp_path / "unreadable.env")
        _Path(target).write_text("KEY=value\n")
        with mock_mod.patch(
            "labgen_ops_secret_injection_verify._parse_env_file",
            side_effect=PermissionError("permission denied"),
        ):
            code = main(["--env-file", target])
        assert code == 2

    def test_quiet_mode_suppresses_output(self, capsys):
        code = main(["--env-file", _ENV_EXAMPLE, "--quiet"])
        out, err = capsys.readouterr()
        assert out == ""
        # exit code still reflects result
        assert code == 1


# ---------------------------------------------------------------------------
# No network calls — verify by ensuring no socket is opened
# ---------------------------------------------------------------------------


class TestNoNetworkCalls:
    def test_no_network_calls_on_example(self, monkeypatch):
        """Verify that verify_secret_injection makes no network calls."""
        import socket
        original_connect = socket.socket.connect

        def _fail_connect(self, *args, **kwargs):
            raise AssertionError(
                f"Network call detected in verify_secret_injection: {args}"
            )

        monkeypatch.setattr(socket.socket, "connect", _fail_connect)
        # Should not raise
        result = verify_secret_injection(_ENV_EXAMPLE)
        assert result.decision == _DECISION_BLOCKED

    def test_no_network_calls_on_ready_env(self, tmp_path: Path, monkeypatch):
        import socket

        def _fail_connect(self, *args, **kwargs):
            raise AssertionError(
                f"Network call detected in verify_secret_injection: {args}"
            )

        monkeypatch.setattr(socket.socket, "connect", _fail_connect)
        env_file = _all_ready_env(tmp_path)
        result = verify_secret_injection(env_file)
        assert result.decision == _DECISION_READY


# ---------------------------------------------------------------------------
# PROXMOX_TOKEN_ID — closely related required key
# ---------------------------------------------------------------------------


class TestProxmoxTokenId:
    def test_token_id_missing_blocks_decision(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            # PROXMOX_TOKEN_ID omitted
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "PROXMOX_TOKEN_ID")
        assert kv.status == STATUS_MISSING
        assert result.decision == _DECISION_BLOCKED

    def test_token_id_placeholder_blocks_decision(self, tmp_path: Path):
        lines = [
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml",
            "ADMIN_TOKEN=" + "a" * 32,
            "PROXMOX_HOST=staging-proxmox.internal",
            "PROXMOX_TOKEN_ID=<set-in-secret-manager>",
            "PROXMOX_TOKEN_SECRET=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "VM_SSH_PASSWORD=Stag1ng$Password!",
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000",
        ]
        env_file = _write_env(tmp_path, lines)
        result = verify_secret_injection(env_file)
        kv = next(k for k in result.keys if k.key == "PROXMOX_TOKEN_ID")
        assert kv.status == STATUS_PLACEHOLDER
        assert result.decision == _DECISION_BLOCKED
