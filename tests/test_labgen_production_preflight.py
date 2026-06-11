"""
Tests for scripts/labgen_production_preflight.py.

Guarantees verified:
  - Valid production-like config → overall pass, exit 0
  - production + stub adapter → blocking
  - Missing namespace adapter value → blocking (invalid value)
  - Missing credential root → blocking (default relative path is blocking)
  - Unsafe credential roots → blocking
  - live LLM enabled → explicit warning (not blocking — operator choice)
  - demo seed ADMIN_USERNAMES empty → warning (endpoint is gated but list is empty)
  - Secret env values are never printed in output or messages
  - No network calls (script is pure env + stdlib)
  - JSON output schema is stable
  - Config module TTL validation (startup fail-closed)
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Import the script as a module — it is importable (no side-effects on import)
# ---------------------------------------------------------------------------

# Ensure the project root is importable (conftest already handles this for pytest,
# but we need the scripts/ dir too)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import labgen_production_preflight as pf  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRODUCTION_ENV = {
    "LABGEN_RUNTIME_MODE": "production",
    "LABGEN_NAMESPACE_ADAPTER": "k8s",
    "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": "/etc/labgen/platform.yaml",
    "LABGEN_VERIFIER_CREDENTIAL_ROOT": "/var/lib/labgen/verifier-credentials",
    "LABGEN_LLM_PROVIDER_MODE": "fake_only",
    "LABGEN_LLM_OPENAI_API_KEY": "",
    "LABGEN_LAB_SESSION_TTL_MINUTES": "30",
    "ADMIN_USERNAMES": "admin",
    "ADMIN_TOKEN": "a" * 40,
    "PROXMOX_HOST": "proxmox.internal",
    "PROXMOX_TOKEN_ID": "labgen@pve!api",
    "PROXMOX_TOKEN_SECRET": "placeholder-secret",
    "VM_SSH_PASSWORD": "placeholder-pass",
    "SESSION_COOKIE_SECURE": "true",
}


def _run(env_overrides: dict[str, str] | None = None) -> pf.PreflightReport:
    """Run preflight against a clean env derived from _PRODUCTION_ENV + overrides."""
    env = {**_PRODUCTION_ENV, **(env_overrides or {})}
    # Remove keys whose override is None (simulate absence)
    absent = {k for k, v in env.items() if v is None}
    final_env = {k: v for k, v in env.items() if v is not None}
    with patch.dict(os.environ, final_env, clear=True):
        # Also unset keys marked as absent
        for k in absent:
            os.environ.pop(k, None)
        return pf.run_preflight()


def _check(report: pf.PreflightReport, name: str) -> pf.PreflightCheck:
    for c in report.checks:
        if c.name == name:
            return c
    raise AssertionError(f"Check '{name}' not found in report. Got: {[c.name for c in report.checks]}")


pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestProductionLikeConfigPasses:
    def test_overall_pass(self) -> None:
        report = _run()
        assert report.overall == "pass"

    def test_no_blocking_issues(self) -> None:
        report = _run()
        assert report.blocking_count() == 0

    def test_no_warnings(self) -> None:
        report = _run()
        assert report.warning_count() == 0

    def test_exit_code_zero(self) -> None:
        report = _run()
        assert report.blocking_count() == 0  # main() returns 0

    def test_all_checks_present(self) -> None:
        report = _run()
        names = {c.name for c in report.checks}
        expected = {
            "runtime_mode_valid",
            "namespace_adapter_valid",
            "production_no_stub_adapter",
            "k8s_kubeconfig_set",
            "credential_root_configured",
            "llm_provider_mode_valid",
            "llm_live_disabled",
            "llm_api_key_not_exposed",
            "session_ttl_valid",
            "demo_seed_gated",
            "admin_token_set",
            "proxmox_auth",
            "vm_ssh_password_set",
            "session_cookie_secure",
        }
        assert expected.issubset(names), f"Missing checks: {expected - names}"


# ---------------------------------------------------------------------------
# Namespace adapter / runtime mode checks
# ---------------------------------------------------------------------------


class TestStubAdapterInProductionFails:
    def test_production_stub_is_blocking(self) -> None:
        report = _run({"LABGEN_RUNTIME_MODE": "production", "LABGEN_NAMESPACE_ADAPTER": "stub"})
        check = _check(report, "production_no_stub_adapter")
        assert check.severity == pf._SEV_BLOCK

    def test_overall_is_blocking(self) -> None:
        report = _run({"LABGEN_RUNTIME_MODE": "production", "LABGEN_NAMESPACE_ADAPTER": "stub"})
        assert report.overall == "blocking"

    def test_dev_stub_is_only_warning(self) -> None:
        report = _run({"LABGEN_RUNTIME_MODE": "dev", "LABGEN_NAMESPACE_ADAPTER": "stub"})
        check = _check(report, "production_no_stub_adapter")
        assert check.severity == pf._SEV_WARN

    def test_demo_stub_is_only_warning(self) -> None:
        report = _run({"LABGEN_RUNTIME_MODE": "demo", "LABGEN_NAMESPACE_ADAPTER": "stub"})
        check = _check(report, "production_no_stub_adapter")
        assert check.severity == pf._SEV_WARN


class TestInvalidRuntimeModeFails:
    def test_invalid_runtime_mode_is_blocking(self) -> None:
        report = _run({"LABGEN_RUNTIME_MODE": "staging"})
        check = _check(report, "runtime_mode_valid")
        assert check.severity == pf._SEV_BLOCK

    def test_invalid_adapter_is_blocking(self) -> None:
        report = _run({"LABGEN_NAMESPACE_ADAPTER": "fake"})
        check = _check(report, "namespace_adapter_valid")
        assert check.severity == pf._SEV_BLOCK


class TestMissingNamespaceAdapterFails:
    def test_k8s_adapter_no_kubeconfig_is_blocking(self) -> None:
        report = _run({"LABGEN_NAMESPACE_ADAPTER": "k8s", "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": ""})
        check = _check(report, "k8s_kubeconfig_set")
        assert check.severity == pf._SEV_BLOCK

    def test_k8s_adapter_relative_kubeconfig_is_warning(self) -> None:
        report = _run({"LABGEN_NAMESPACE_ADAPTER": "k8s", "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": "relative/path.yaml"})
        check = _check(report, "k8s_kubeconfig_set")
        assert check.severity == pf._SEV_WARN

    def test_stub_adapter_kubeconfig_check_skipped(self) -> None:
        report = _run({"LABGEN_RUNTIME_MODE": "dev", "LABGEN_NAMESPACE_ADAPTER": "stub", "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": ""})
        check = _check(report, "k8s_kubeconfig_set")
        assert check.severity == pf._SEV_PASS


# ---------------------------------------------------------------------------
# Credential root checks
# ---------------------------------------------------------------------------


class TestMissingCredentialRootFails:
    def test_empty_root_is_blocking(self) -> None:
        report = _run({"LABGEN_VERIFIER_CREDENTIAL_ROOT": ""})
        check = _check(report, "credential_root_configured")
        assert check.severity == pf._SEV_BLOCK

    def test_default_relative_root_is_blocking(self) -> None:
        # creds/vm_creds is the default — relative paths are blocking
        report = _run({"LABGEN_VERIFIER_CREDENTIAL_ROOT": "creds/vm_creds"})
        check = _check(report, "credential_root_configured")
        assert check.severity == pf._SEV_BLOCK

    def test_any_relative_path_is_blocking(self) -> None:
        report = _run({"LABGEN_VERIFIER_CREDENTIAL_ROOT": "./creds"})
        check = _check(report, "credential_root_configured")
        assert check.severity == pf._SEV_BLOCK


class TestUnsafeCredentialRootFails:
    @pytest.mark.parametrize("unsafe", ["/tmp", "/tmp/labgen", "/var/tmp", "/", "/root"])
    def test_unsafe_path_is_blocking(self, unsafe: str) -> None:
        report = _run({"LABGEN_VERIFIER_CREDENTIAL_ROOT": unsafe})
        check = _check(report, "credential_root_configured")
        assert check.severity == pf._SEV_BLOCK

    def test_safe_absolute_path_passes(self) -> None:
        report = _run({"LABGEN_VERIFIER_CREDENTIAL_ROOT": "/var/lib/labgen/verifier-credentials"})
        check = _check(report, "credential_root_configured")
        assert check.severity == pf._SEV_PASS


# ---------------------------------------------------------------------------
# LLM provider checks
# ---------------------------------------------------------------------------


class TestLiveLLMEnabledProducesWarning:
    def test_live_enabled_is_warning_not_blocking(self) -> None:
        report = _run({"LABGEN_LLM_PROVIDER_MODE": "live_enabled"})
        check = _check(report, "llm_live_disabled")
        assert check.severity == pf._SEV_WARN

    def test_fake_only_passes(self) -> None:
        report = _run({"LABGEN_LLM_PROVIDER_MODE": "fake_only"})
        check = _check(report, "llm_live_disabled")
        assert check.severity == pf._SEV_PASS

    def test_disabled_passes(self) -> None:
        report = _run({"LABGEN_LLM_PROVIDER_MODE": "disabled"})
        check = _check(report, "llm_live_disabled")
        assert check.severity == pf._SEV_PASS

    def test_invalid_mode_is_blocking(self) -> None:
        report = _run({"LABGEN_LLM_PROVIDER_MODE": "yolo"})
        check = _check(report, "llm_provider_mode_valid")
        assert check.severity == pf._SEV_BLOCK

    def test_api_key_set_but_not_live_is_warning(self) -> None:
        report = _run({
            "LABGEN_LLM_PROVIDER_MODE": "fake_only",
            "LABGEN_LLM_OPENAI_API_KEY": "sk-some-key-value",
        })
        check = _check(report, "llm_api_key_not_exposed")
        assert check.severity == pf._SEV_WARN


# ---------------------------------------------------------------------------
# Demo seed check
# ---------------------------------------------------------------------------


class TestDemoSeedGated:
    def test_empty_admin_usernames_is_warning(self) -> None:
        report = _run({"ADMIN_USERNAMES": ""})
        check = _check(report, "demo_seed_gated")
        assert check.severity == pf._SEV_WARN

    def test_non_empty_admin_usernames_passes(self) -> None:
        report = _run({"ADMIN_USERNAMES": "admin"})
        check = _check(report, "demo_seed_gated")
        assert check.severity == pf._SEV_PASS


# ---------------------------------------------------------------------------
# Secret values not printed
# ---------------------------------------------------------------------------


class TestSecretValuesNotPrinted:
    _FAKE_SECRET = "this-is-a-very-secret-value-that-must-not-appear"

    def _collect_all_text(self, report: pf.PreflightReport) -> str:
        parts = []
        for c in report.checks:
            parts.append(c.message)
            if c.detail:
                parts.append(c.detail)
        return "\n".join(parts)

    def test_admin_token_value_not_in_output(self) -> None:
        report = _run({"ADMIN_TOKEN": self._FAKE_SECRET})
        text = self._collect_all_text(report)
        assert self._FAKE_SECRET not in text

    def test_proxmox_token_secret_not_in_output(self) -> None:
        report = _run({"PROXMOX_TOKEN_SECRET": self._FAKE_SECRET})
        text = self._collect_all_text(report)
        assert self._FAKE_SECRET not in text

    def test_vm_ssh_password_not_in_output(self) -> None:
        report = _run({"VM_SSH_PASSWORD": self._FAKE_SECRET})
        text = self._collect_all_text(report)
        assert self._FAKE_SECRET not in text

    def test_llm_api_key_not_in_output(self) -> None:
        report = _run({"LABGEN_LLM_OPENAI_API_KEY": self._FAKE_SECRET})
        text = self._collect_all_text(report)
        assert self._FAKE_SECRET not in text

    def test_kubeconfig_path_not_in_message_when_pass(self) -> None:
        # path appears only when it's a warning/detail (relative path),
        # not in the pass message itself
        report = _run({"LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": "/etc/labgen/platform.yaml"})
        check = _check(report, "k8s_kubeconfig_set")
        assert check.severity == pf._SEV_PASS
        # path is NOT included in pass message (no need to expose it)
        assert "/etc/labgen/platform.yaml" not in check.message


# ---------------------------------------------------------------------------
# No network calls (structural: script has no import of network libs)
# ---------------------------------------------------------------------------


class TestNoNetworkCalls:
    def test_no_socket_import_in_preflight(self) -> None:
        import ast
        import inspect
        source = inspect.getsource(pf)
        tree = ast.parse(source)
        import_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    import_names.add(node.module.split(".")[0])
        network_libs = {"socket", "httpx", "requests", "urllib3", "aiohttp", "http"}
        used = import_names & network_libs
        assert not used, f"preflight script imports network libraries: {used}"

    def test_run_preflight_makes_no_network_calls(self) -> None:
        # Patch socket to raise on any network access
        import socket

        original_getaddrinfo = socket.getaddrinfo

        calls: list[Any] = []

        def _no_network(*args: Any, **kwargs: Any) -> Any:
            calls.append(args)
            raise ConnectionRefusedError("network call detected in preflight")

        with patch.object(socket, "getaddrinfo", _no_network):
            # Should not raise — preflight never calls network
            report = _run()
        assert not calls, f"Network calls detected: {calls}"


# ---------------------------------------------------------------------------
# JSON output schema
# ---------------------------------------------------------------------------


class TestJSONOutputSchemaStable:
    def test_json_output_has_required_keys(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _run()
        pf._json_output(report)
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert "overall" in data
        assert "pass_count" in data
        assert "warning_count" in data
        assert "blocking_count" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_json_check_schema(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _run()
        pf._json_output(report)
        captured = capsys.readouterr().out
        data = json.loads(captured)
        for check in data["checks"]:
            assert "name" in check
            assert "severity" in check
            assert "message" in check
            assert check["severity"] in {"pass", "warning", "blocking"}

    def test_json_overall_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _run()
        pf._json_output(report)
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data["overall"] in {"pass", "warning", "blocking"}

    def test_json_blocking_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _run({"LABGEN_RUNTIME_MODE": "production", "LABGEN_NAMESPACE_ADAPTER": "stub"})
        pf._json_output(report)
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data["overall"] == "blocking"
        assert data["blocking_count"] >= 1


# ---------------------------------------------------------------------------
# Session TTL validation
# ---------------------------------------------------------------------------


class TestSessionTTLValidation:
    def test_valid_ttl_passes(self) -> None:
        report = _run({"LABGEN_LAB_SESSION_TTL_MINUTES": "45"})
        check = _check(report, "session_ttl_valid")
        assert check.severity == pf._SEV_PASS

    def test_zero_ttl_is_blocking(self) -> None:
        report = _run({"LABGEN_LAB_SESSION_TTL_MINUTES": "0"})
        check = _check(report, "session_ttl_valid")
        assert check.severity == pf._SEV_BLOCK

    def test_negative_ttl_is_blocking(self) -> None:
        report = _run({"LABGEN_LAB_SESSION_TTL_MINUTES": "-5"})
        check = _check(report, "session_ttl_valid")
        assert check.severity == pf._SEV_BLOCK

    def test_non_integer_ttl_is_blocking(self) -> None:
        report = _run({"LABGEN_LAB_SESSION_TTL_MINUTES": "thirty"})
        check = _check(report, "session_ttl_valid")
        assert check.severity == pf._SEV_BLOCK

    def test_very_long_ttl_is_warning(self) -> None:
        report = _run({"LABGEN_LAB_SESSION_TTL_MINUTES": "600"})
        check = _check(report, "session_ttl_valid")
        assert check.severity == pf._SEV_WARN


# ---------------------------------------------------------------------------
# Config module TTL fail-closed (startup validation)
# ---------------------------------------------------------------------------


class TestConfigModuleTTLFailClosed:
    """Verifies that LABGEN_LAB_SESSION_TTL_MINUTES < 1 raises RuntimeError at reload."""

    # Base env that satisfies all other required config vars.
    _BASE_ENV = {
        "PROXMOX_HOST": "x",
        "PROXMOX_TOKEN_ID": "u@r!t",
        "PROXMOX_TOKEN_SECRET": "s",
        "VM_SSH_PASSWORD": "p",
        "ADMIN_TOKEN": "a" * 33,
    }

    def test_invalid_ttl_raises_at_config_load(self) -> None:
        # Import BEFORE patching so the module is already cached in sys.modules.
        import backend.config as _cfg
        bad_env = {**self._BASE_ENV, "LABGEN_LAB_SESSION_TTL_MINUTES": "0"}
        good_env = {**self._BASE_ENV, "LABGEN_LAB_SESSION_TTL_MINUTES": "30"}
        try:
            with patch.dict(os.environ, bad_env, clear=False):
                with pytest.raises(RuntimeError, match="LABGEN_LAB_SESSION_TTL_MINUTES"):
                    importlib.reload(_cfg)
        finally:
            # Always restore to a valid state so downstream tests are not affected.
            with patch.dict(os.environ, good_env, clear=False):
                importlib.reload(_cfg)

    def test_valid_ttl_does_not_raise(self) -> None:
        import backend.config as _cfg
        env = {**self._BASE_ENV, "LABGEN_LAB_SESSION_TTL_MINUTES": "30"}
        with patch.dict(os.environ, env, clear=False):
            importlib.reload(_cfg)
            assert _cfg.LABGEN_LAB_SESSION_TTL_MINUTES == 30
        # Restore to current real env after the test.
        importlib.reload(_cfg)

    def test_empty_credential_root_env_uses_default(self) -> None:
        # Codex P2: empty env var must fall back to default, not silently use "".
        import backend.config as _cfg
        env = {**self._BASE_ENV, "LABGEN_VERIFIER_CREDENTIAL_ROOT": ""}
        with patch.dict(os.environ, env, clear=False):
            importlib.reload(_cfg)
            assert _cfg.LABGEN_VERIFIER_CREDENTIAL_ROOT == "creds/vm_creds"
        importlib.reload(_cfg)
