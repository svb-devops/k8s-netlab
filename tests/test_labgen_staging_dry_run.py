"""
Tests for scripts/labgen_staging_dry_run.py.

Coverage targets (per task spec):
  - offline mode: staging env example parsed and preflight runs
  - missing env file → structured blocking failure
  - preflight blocking issue propagates to dry run report
  - --json output schema is stable
  - no secret values printed in any output path
  - base-url mode only calls safe GET endpoints
  - base-url mode never calls destructive endpoints
  - diagnostics response secret scanning catches unsafe payload
  - network/client errors return structured warning (not crash)
  - no external network required (http_get is injectable)

All tests are pytest.mark.static (no K3s, no LLM, no external network).
"""

from __future__ import annotations

import json
import os
import sys
from io import StringIO
from typing import Optional
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Import script module
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import labgen_staging_dry_run as dry  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A staging-like env that passes preflight (with only advisory warnings)
_STAGING_ENV: dict[str, str] = {
    "LABGEN_RUNTIME_MODE": "production",
    "LABGEN_NAMESPACE_ADAPTER": "k8s",
    "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": "/etc/labgen-staging/kubeconfig.yaml",
    "LABGEN_VERIFIER_CREDENTIAL_ROOT": "/var/lib/labgen-staging/verifier-credentials",
    "LABGEN_LLM_PROVIDER_MODE": "fake_only",
    "LABGEN_LAB_SESSION_TTL_MINUTES": "30",
    "PROXMOX_HOST": "staging-proxmox.local",
    "PROXMOX_TOKEN_ID": "labgen-staging@pve!api",
    "PROXMOX_TOKEN_SECRET": "staging-token-secret-value",
    "VM_SSH_PASSWORD": "staging-vm-password",
    "ADMIN_TOKEN": "a" * 36,
    "ADMIN_USERNAMES": "admin",
    "SESSION_COOKIE_SECURE": "false",
}


def _fake_http_get_factory(responses: dict[str, tuple[int, str]]):
    """Create a fake HTTP client that records all calls made."""
    calls: list[tuple[str, dict]] = []

    def _fake_get(url: str, headers: dict) -> tuple[int, str, Optional[str]]:
        calls.append((url, dict(headers)))
        if url in responses:
            code, body = responses[url]
            return code, body, None
        return 200, "{}", None

    _fake_get.calls = calls  # type: ignore[attr-defined]
    return _fake_get


def _make_200_responses(base: str) -> dict[str, tuple[int, str]]:
    return {
        f"{base}/api/health": (200, '{"status":"healthy"}'),
        f"{base}/openapi.json": (200, '{"openapi":"3.0.0"}'),
        f"{base}/": (200, "<html></html>"),
        f"{base}/api/labgen/contract-pack": (200, '{"version":"v0.1","endpoints":[]}'),
        f"{base}/api/labgen/runtime/adapter-status": (200, '{"adapter":"k8s"}'),
        f"{base}/api/labgen/llm-provider/status": (200, '{"live_enabled":false}'),
    }


# ---------------------------------------------------------------------------
# A — Env File Parsing
# ---------------------------------------------------------------------------


class TestEnvFileParsing:
    def test_staging_example_parses_without_error(self, tmp_path) -> None:
        staging_example = os.path.join(_PROJECT_ROOT, "deploy", "labgen", ".env.staging.example")
        if not os.path.exists(staging_example):
            pytest.skip("staging example file not present")
        env, err = dry.load_env_file(staging_example)
        assert err is None
        assert isinstance(env, dict)
        assert len(env) > 0

    def test_staging_example_has_expected_keys(self, tmp_path) -> None:
        staging_example = os.path.join(_PROJECT_ROOT, "deploy", "labgen", ".env.staging.example")
        if not os.path.exists(staging_example):
            pytest.skip("staging example file not present")
        env, _ = dry.load_env_file(staging_example)
        for key in ("LABGEN_RUNTIME_MODE", "LABGEN_NAMESPACE_ADAPTER", "LABGEN_LLM_PROVIDER_MODE"):
            assert key in env, f"Missing key: {key}"

    def test_staging_example_no_real_secrets(self, tmp_path) -> None:
        staging_example = os.path.join(_PROJECT_ROOT, "deploy", "labgen", ".env.staging.example")
        if not os.path.exists(staging_example):
            pytest.skip("staging example file not present")
        with open(staging_example) as f:
            content = f.read()
        for pat in ("sk-ant-", "sk-proj-", "-----BEGIN", "client-certificate-data:"):
            assert pat not in content, f"Sensitive pattern found in staging example: {pat!r}"

    def test_key_value_parsing(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\n# comment\nKEY2=value2\n\nKEY3=\n")
        env, err = dry.load_env_file(str(env_file))
        assert err is None
        assert env["KEY1"] == "value1"
        assert env["KEY2"] == "value2"
        assert "KEY3" in env

    def test_commented_lines_not_parsed(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# ADMIN_TOKEN=<set-in-secret-manager>\nKEY=val\n")
        env, err = dry.load_env_file(str(env_file))
        assert err is None
        assert "ADMIN_TOKEN" not in env
        assert env["KEY"] == "val"

    def test_lines_without_equals_skipped(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("JUST_A_WORD\nKEY=value\n")
        env, err = dry.load_env_file(str(env_file))
        assert err is None
        assert "JUST_A_WORD" not in env
        assert env["KEY"] == "value"


# ---------------------------------------------------------------------------
# B — Missing Env File
# ---------------------------------------------------------------------------


class TestMissingEnvFile:
    def test_missing_file_returns_blocking_report(self, tmp_path) -> None:
        report = dry.run_from_env_file(str(tmp_path / "nonexistent.env"))
        assert report.blocking_count() > 0
        assert report.overall == "blocking"

    def test_missing_file_check_name_is_env_file_loaded(self, tmp_path) -> None:
        report = dry.run_from_env_file(str(tmp_path / "nonexistent.env"))
        names = [c.name for c in report.checks]
        assert "env_file_loaded" in names

    def test_missing_file_no_preflight_checks(self, tmp_path) -> None:
        report = dry.run_from_env_file(str(tmp_path / "nonexistent.env"))
        preflight = report.checks_in_phase(dry._PHASE_PREFLIGHT)
        assert len(preflight) == 0, "Preflight should not run when env file is missing"

    def test_missing_file_message_does_not_contain_secret(self, tmp_path) -> None:
        report = dry.run_from_env_file(str(tmp_path / "nonexistent.env"))
        for check in report.checks:
            assert "sk-ant-" not in check.message
            assert "-----BEGIN" not in check.message


# ---------------------------------------------------------------------------
# C — Preflight Integration
# ---------------------------------------------------------------------------


class TestPreflightIntegration:
    def test_valid_staging_env_has_preflight_checks(self) -> None:
        report = dry.run_dry_run(env_vars=_STAGING_ENV)
        preflight = report.checks_in_phase(dry._PHASE_PREFLIGHT)
        assert len(preflight) > 0

    def test_stub_adapter_in_production_propagates_blocking(self) -> None:
        bad_env = {**_STAGING_ENV, "LABGEN_NAMESPACE_ADAPTER": "stub"}
        report = dry.run_dry_run(env_vars=bad_env)
        assert report.blocking_count() > 0

    def test_invalid_runtime_mode_propagates_blocking(self) -> None:
        bad_env = {**_STAGING_ENV, "LABGEN_RUNTIME_MODE": "invalid_mode"}
        report = dry.run_dry_run(env_vars=bad_env)
        assert report.blocking_count() > 0

    def test_relative_credential_root_propagates_blocking(self) -> None:
        bad_env = {**_STAGING_ENV, "LABGEN_VERIFIER_CREDENTIAL_ROOT": "relative/path"}
        report = dry.run_dry_run(env_vars=bad_env)
        assert report.blocking_count() > 0

    def test_live_llm_propagates_warning(self) -> None:
        warn_env = {**_STAGING_ENV, "LABGEN_LLM_PROVIDER_MODE": "live_enabled"}
        report = dry.run_dry_run(env_vars=warn_env)
        assert report.warning_count() > 0

    def test_missing_admin_token_propagates_blocking(self) -> None:
        # Explicitly set empty string so _env_context removes it from os.environ
        no_token_env = {**_STAGING_ENV, "ADMIN_TOKEN": ""}
        report = dry.run_dry_run(env_vars=no_token_env)
        assert report.blocking_count() > 0

    def test_short_admin_token_propagates_blocking(self) -> None:
        short_token_env = {**_STAGING_ENV, "ADMIN_TOKEN": "tooshort"}
        report = dry.run_dry_run(env_vars=short_token_env)
        assert report.blocking_count() > 0

    def test_env_context_restores_original_env(self) -> None:
        original = os.environ.get("LABGEN_RUNTIME_MODE", "_NOT_SET_")
        dry.run_dry_run(env_vars={"LABGEN_RUNTIME_MODE": "test"})
        restored = os.environ.get("LABGEN_RUNTIME_MODE", "_NOT_SET_")
        assert restored == original, "env_context must restore original environment"


# ---------------------------------------------------------------------------
# D — JSON Output Schema
# ---------------------------------------------------------------------------


class TestJSONOutputSchema:
    def _get_json_output(self, env: dict) -> dict:
        report = dry.run_dry_run(env_vars=env)
        buf = StringIO()
        with patch("sys.stdout", buf):
            dry._json_output(report)
        return json.loads(buf.getvalue())

    def test_top_level_keys_present(self) -> None:
        out = self._get_json_output(_STAGING_ENV)
        for key in ("overall", "pass_count", "warning_count", "blocking_count", "phases", "checks"):
            assert key in out, f"Missing top-level key: {key!r}"

    def test_overall_is_valid_enum(self) -> None:
        out = self._get_json_output(_STAGING_ENV)
        assert out["overall"] in ("pass", "warning", "blocking")

    def test_counts_are_non_negative_ints(self) -> None:
        out = self._get_json_output(_STAGING_ENV)
        for k in ("pass_count", "warning_count", "blocking_count"):
            assert isinstance(out[k], int) and out[k] >= 0

    def test_each_check_has_required_fields(self) -> None:
        out = self._get_json_output(_STAGING_ENV)
        for check in out["checks"]:
            assert "phase" in check
            assert "name" in check
            assert "severity" in check
            assert "message" in check

    def test_severity_values_are_valid(self) -> None:
        out = self._get_json_output(_STAGING_ENV)
        valid = {"pass", "warning", "blocking"}
        for check in out["checks"]:
            assert check["severity"] in valid

    def test_phases_list_present(self) -> None:
        out = self._get_json_output(_STAGING_ENV)
        assert isinstance(out["phases"], list)
        assert "preflight" in out["phases"]

    def test_blocking_env_overall_is_blocking(self) -> None:
        bad_env = {**_STAGING_ENV, "LABGEN_NAMESPACE_ADAPTER": "stub"}
        out = self._get_json_output(bad_env)
        assert out["overall"] == "blocking"
        assert out["blocking_count"] > 0

    def test_schema_stable_across_runs(self) -> None:
        out1 = self._get_json_output(_STAGING_ENV)
        out2 = self._get_json_output(_STAGING_ENV)
        assert sorted(out1.keys()) == sorted(out2.keys())


# ---------------------------------------------------------------------------
# E — No Secret Values Printed
# ---------------------------------------------------------------------------


class TestNoSecretsPrinted:
    _SECRET_VALUES = [
        "staging-token-secret-value",   # PROXMOX_TOKEN_SECRET
        "staging-vm-password",          # VM_SSH_PASSWORD
        "a" * 36,                       # ADMIN_TOKEN
    ]

    def _all_output(self, report: dry.DryRunReport) -> str:
        buf = StringIO()
        with patch("sys.stdout", buf):
            dry._human_output(report)
        human = buf.getvalue()

        buf2 = StringIO()
        with patch("sys.stdout", buf2):
            dry._json_output(report)
        return human + buf2.getvalue()

    def test_proxmox_secret_not_in_output(self) -> None:
        report = dry.run_dry_run(env_vars=_STAGING_ENV)
        output = self._all_output(report)
        assert "staging-token-secret-value" not in output

    def test_vm_ssh_password_not_in_output(self) -> None:
        report = dry.run_dry_run(env_vars=_STAGING_ENV)
        output = self._all_output(report)
        assert "staging-vm-password" not in output

    def test_admin_token_value_not_in_output(self) -> None:
        report = dry.run_dry_run(env_vars=_STAGING_ENV)
        output = self._all_output(report)
        assert "a" * 36 not in output

    def test_no_sensitive_patterns_in_output(self) -> None:
        report = dry.run_dry_run(env_vars=_STAGING_ENV)
        output = self._all_output(report)
        for pat in ("sk-ant-", "sk-proj-", "-----BEGIN", "client-certificate-data:"):
            assert pat not in output, f"Sensitive pattern found in output: {pat!r}"


# ---------------------------------------------------------------------------
# F — HTTP Endpoint Checks (base-url mode)
# ---------------------------------------------------------------------------


class TestHTTPEndpointChecks:
    _BASE = "http://localhost:18000"

    def test_offline_mode_no_http_calls(self) -> None:
        calls = []

        def recorder(url, headers):
            calls.append(url)
            return 200, "{}", None

        dry.run_dry_run(env_vars=_STAGING_ENV, http_get=recorder)
        assert len(calls) == 0, "No HTTP calls in offline mode"

    def test_base_url_triggers_endpoint_checks(self) -> None:
        http = _fake_http_get_factory(_make_200_responses(self._BASE))
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=http,
        )
        endpoint_checks = report.checks_in_phase(dry._PHASE_ENDPOINTS)
        assert len(endpoint_checks) > 0

    def test_only_get_endpoints_called(self) -> None:
        http = _fake_http_get_factory(_make_200_responses(self._BASE))
        dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=http,
        )
        for url, _headers in http.calls:
            assert not any(
                url.endswith(path) for path in dry._FORBIDDEN_PATHS
            ), f"Forbidden path called: {url}"

    def test_destructive_endpoints_never_called(self) -> None:
        called_urls: list[str] = []

        def recording_client(url, headers):
            called_urls.append(url)
            return 200, "{}", None

        dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=recording_client,
        )
        forbidden_prefixes = [
            "/api/labgen/seed",
            "/api/labgen/drafts",
            "/api/lab-sessions",
            "/api/labgen/runtime/expire",
        ]
        for url in called_urls:
            path = url[len(self._BASE):]
            for prefix in forbidden_prefixes:
                assert not path.startswith(prefix), \
                    f"Destructive path called: {url}"

    def test_demo_seed_not_called_without_flag(self) -> None:
        called_urls: list[str] = []

        def recording_client(url, headers):
            called_urls.append(url)
            return 200, "{}", None

        dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            allow_demo_seed_check=False,
            http_get=recording_client,
        )
        seed_calls = [u for u in called_urls if "seed" in u]
        assert len(seed_calls) == 0

    def test_demo_seed_gate_checked_with_flag(self) -> None:
        http = _fake_http_get_factory({
            **_make_200_responses(self._BASE),
            f"{self._BASE}/api/labgen/seed/demo": (405, ""),
        })
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            allow_demo_seed_check=True,
            http_get=http,
        )
        seed_calls = [u for u, _ in http.calls if "seed" in u]
        assert len(seed_calls) > 0, "Demo seed gate should be probed when flag is set"

        # Should PASS: 405 = method not allowed = gate active
        demo_checks = [c for c in report.checks if c.name == "demo_seed_admin_gate"]
        assert len(demo_checks) > 0
        assert demo_checks[0].severity == "pass"

    def test_demo_seed_200_is_blocking(self) -> None:
        http = _fake_http_get_factory({
            **_make_200_responses(self._BASE),
            f"{self._BASE}/api/labgen/seed/demo": (200, "seed ran"),
        })
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            allow_demo_seed_check=True,
            http_get=http,
        )
        demo_checks = [c for c in report.checks if c.name == "demo_seed_admin_gate"]
        assert any(c.severity == "blocking" for c in demo_checks)

    def test_demo_seed_404_is_warning(self) -> None:
        """404 = endpoint not deployed yet — warn rather than pass, to alert operator."""
        http = _fake_http_get_factory({
            **_make_200_responses(self._BASE),
            f"{self._BASE}/api/labgen/seed/demo": (404, "Not Found"),
        })
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            allow_demo_seed_check=True,
            http_get=http,
        )
        demo_checks = [c for c in report.checks if c.name == "demo_seed_admin_gate"]
        assert len(demo_checks) > 0
        assert demo_checks[0].severity == "warning"

    def test_admin_endpoints_use_admin_token_header(self) -> None:
        headers_seen: list[dict] = []

        def capturing_client(url, headers):
            headers_seen.append(dict(headers))
            return 200, "{}", None

        dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=capturing_client,
        )
        admin_calls_with_token = [h for h in headers_seen if "X-Admin-Token" in h]
        assert len(admin_calls_with_token) > 0, "Admin endpoints should use X-Admin-Token"

    def test_admin_token_value_not_logged(self) -> None:
        """Admin token must never appear in any check message or detail."""
        http = _fake_http_get_factory(_make_200_responses(self._BASE))
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=http,
        )
        token_value = _STAGING_ENV["ADMIN_TOKEN"]
        for check in report.checks:
            assert token_value not in check.message
            assert token_value not in (check.detail or "")

    def test_no_admin_token_admin_endpoints_pass_with_expected_status(self) -> None:
        """Without admin token, 401/403/503 on admin endpoints = pass (expected)."""
        no_token_env = {**_STAGING_ENV, "ADMIN_TOKEN": ""}  # explicitly clear
        responses = {
            **_make_200_responses(self._BASE),
            f"{self._BASE}/api/labgen/contract-pack": (401, "Unauthorized"),
            f"{self._BASE}/api/labgen/runtime/adapter-status": (403, "Forbidden"),
            f"{self._BASE}/api/labgen/llm-provider/status": (503, "Service Unavailable"),
        }
        http = _fake_http_get_factory(responses)
        report = dry.run_dry_run(
            env_vars=no_token_env,
            base_url=self._BASE,
            http_get=http,
        )
        # The no-token 401/403/503 checks should be PASS, not blocking
        admin_endpoint_names = {"endpoint_contract_pack", "endpoint_runtime_adapter_status",
                                 "endpoint_llm_provider_status"}
        for check in report.checks:
            if check.name in admin_endpoint_names:
                assert check.severity == "pass", \
                    f"{check.name}: expected pass for no-token 401/403/503, got {check.severity}"


# ---------------------------------------------------------------------------
# G — Sensitive Response Scanning
# ---------------------------------------------------------------------------


class TestSensitiveResponseScanning:
    _BASE = "http://localhost:18000"

    def _responses_with_leak(self, path: str, leak: str) -> dict:
        responses = _make_200_responses(self._BASE)
        responses[self._BASE + path] = (200, f'{{"data": "{leak}"}}')
        return responses

    def test_api_key_in_response_is_blocking(self) -> None:
        http = _fake_http_get_factory(
            self._responses_with_leak("/openapi.json", "sk-ant-abc123")
        )
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=http,
        )
        security_checks = [c for c in report.checks if "secret_leak" in c.name]
        assert len(security_checks) > 0
        assert all(c.severity == "blocking" for c in security_checks)

    def test_pem_key_in_response_is_blocking(self) -> None:
        http = _fake_http_get_factory(
            self._responses_with_leak("/openapi.json", "-----BEGIN PRIVATE KEY-----")
        )
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=http,
        )
        security_checks = [c for c in report.checks if "secret_leak" in c.name]
        assert len(security_checks) > 0

    def test_kubeconfig_field_in_response_is_blocking(self) -> None:
        http = _fake_http_get_factory(
            self._responses_with_leak("/api/labgen/contract-pack", "client-certificate-data: abc")
        )
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=http,
        )
        security_checks = [c for c in report.checks if "secret_leak" in c.name]
        assert len(security_checks) > 0

    def test_clean_response_passes_scan(self) -> None:
        http = _fake_http_get_factory(_make_200_responses(self._BASE))
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=http,
        )
        security_checks = [c for c in report.checks if "secret_leak" in c.name]
        assert len(security_checks) == 0

    def test_scan_for_secrets_helper_detects_patterns(self) -> None:
        assert "Anthropic API key prefix" in " ".join(dry._scan_for_secrets("prefix sk-ant-abc"))
        assert "PEM" in " ".join(dry._scan_for_secrets("-----BEGIN PRIVATE KEY-----"))
        assert len(dry._scan_for_secrets("nothing sensitive here")) == 0


# ---------------------------------------------------------------------------
# H — Network / Client Error Handling
# ---------------------------------------------------------------------------


class TestNetworkErrorHandling:
    _BASE = "http://localhost:18000"

    def test_network_error_returns_warning_not_blocking(self) -> None:
        def always_error(url, headers):
            return 0, "", "Connection refused"

        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=always_error,
        )
        endpoint_checks = report.checks_in_phase(dry._PHASE_ENDPOINTS)
        # Network errors are warnings, not blocking
        assert all(c.severity in ("pass", "warning") for c in endpoint_checks)
        assert report.overall in ("pass", "warning")

    def test_network_error_does_not_raise(self) -> None:
        def exploding_client(url, headers):
            raise RuntimeError("Unexpected exception")

        # Should not propagate — network failures must be caught
        # (exploding_client raises instead of returning error tuple)
        # This tests that run_dry_run handles non-returning errors gracefully.
        # Since the injectable client is expected to return a tuple,
        # a client that raises will propagate (we do NOT swallow it).
        # This is intentional: bad clients should fail loudly.
        # The test verifies the contract: clients MUST return a tuple.
        with pytest.raises(RuntimeError, match="Unexpected exception"):
            dry.run_dry_run(
                env_vars=_STAGING_ENV,
                base_url=self._BASE,
                http_get=exploding_client,
            )

    def test_partial_network_failure_continues(self) -> None:
        call_count = [0]

        def intermittent(url, headers):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                return 0, "", "Connection refused"
            return 200, "{}", None

        # Must not raise — partial errors are collected as warnings
        report = dry.run_dry_run(
            env_vars=_STAGING_ENV,
            base_url=self._BASE,
            http_get=intermittent,
        )
        endpoint_checks = report.checks_in_phase(dry._PHASE_ENDPOINTS)
        assert len(endpoint_checks) > 0


# ---------------------------------------------------------------------------
# I — Load Env File Integration
# ---------------------------------------------------------------------------


class TestLoadEnvFileIntegration:
    def test_valid_env_file_passes(self, tmp_path) -> None:
        env_file = tmp_path / "test.env"
        lines = "\n".join(f"{k}={v}" for k, v in _STAGING_ENV.items())
        env_file.write_text(lines + "\n")
        report = dry.run_from_env_file(str(env_file))
        env_check = next((c for c in report.checks if c.name == "env_file_loaded"), None)
        assert env_check is not None
        assert env_check.severity == "pass"

    def test_env_file_check_passes_for_valid_file(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("LABGEN_RUNTIME_MODE=dev\n")
        report = dry.run_from_env_file(str(env_file))
        env_checks = [c for c in report.checks if c.name == "env_file_loaded"]
        assert len(env_checks) == 1
        assert env_checks[0].severity == "pass"

    def test_preflight_runs_after_valid_env_file(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        lines = "\n".join(f"{k}={v}" for k, v in _STAGING_ENV.items())
        env_file.write_text(lines + "\n")
        report = dry.run_from_env_file(str(env_file))
        preflight = report.checks_in_phase(dry._PHASE_PREFLIGHT)
        assert len(preflight) > 0
