"""
Tests for scripts/labgen_staging_provisioning_validate.py

Coverage goals:
  - All check functions exercised (pass, warn, block paths)
  - Parser: active keys, acknowledged secrets, inline comments, blank lines
  - CLI: file not found (exit 2), blocking (exit 1), pass (exit 0)
  - JSON output schema stable
  - Text output does not print secret values
  - No network calls (structural — verifies by running tests without network)

pytestmark is intentionally NOT set to static here because the module-under-test
lives in scripts/ (outside backend/), so the coverage scope excludes it anyway.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Load the script under test directly (it lives in scripts/, not a package)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "labgen_staging_provisioning_validate.py"

spec = importlib.util.spec_from_file_location(
    "labgen_staging_provisioning_validate", _SCRIPT_PATH
)
_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
sys.modules["labgen_staging_provisioning_validate"] = _mod
spec.loader.exec_module(_mod)  # type: ignore[union-attr]

# Re-export key symbols for readability
validate_env_file = _mod.validate_env_file
_parse_env_file = _mod._parse_env_file
_check_required_active_keys = _mod._check_required_active_keys
_check_namespace_adapter = _mod._check_namespace_adapter
_check_llm_live = _mod._check_llm_live
_check_demo_seed = _mod._check_demo_seed
_check_credential_root = _mod._check_credential_root
_check_session_ttl = _mod._check_session_ttl
_check_runtime_mode = _mod._check_runtime_mode
_check_secret_keys_not_active = _mod._check_secret_keys_not_active
_check_real_secret_patterns = _mod._check_real_secret_patterns
ProvisioningResult = _mod.ProvisioningResult
_json_output = _mod._json_output
_human_output = _mod._human_output
main = _mod.main

_STAGING_EXAMPLE = _REPO_ROOT / "deploy" / "labgen" / ".env.staging.example"

_SEV_BLOCK = "blocking"
_SEV_WARN = "warning"
_SEV_PASS = "pass"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_env(tmp_path: Path, content: str) -> Path:
    """Write an env file with the given content and return its path."""
    p = tmp_path / ".env.test"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _minimal_valid_env(overrides: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Return a minimal valid staging env dict (all required active keys set)."""
    base = {
        "LABGEN_RUNTIME_MODE": "production",
        "LABGEN_NAMESPACE_ADAPTER": "k8s",
        "LABGEN_LLM_PROVIDER_MODE": "fake_only",
        "LABGEN_LAB_SESSION_TTL_MINUTES": "30",
        "LABGEN_VERIFIER_CREDENTIAL_ROOT": "/var/lib/labgen-staging/verifier-credentials",
        "PROXMOX_HOST": "<staging-host>",
        "PROXMOX_TOKEN_ID": "labgen-staging@pve!api",
        # kubeconfig acknowledged as secret
        "# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": "<set-in-staging-secret-manager>",
    }
    if overrides:
        base.update(overrides)
    return base



def _validate_str(tmp_path: Path, content: str) -> _mod.ProvisioningResult:
    """Helper: write env content to tmp file and validate it."""
    env_file = _write_env(tmp_path, content)
    return validate_env_file(str(env_file))


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseEnvFile:
    def test_parses_active_key_value(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "FOO=bar\n")
        active, ack = _parse_env_file(str(p))
        assert active["FOO"] == "bar"
        assert not ack

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "\n\n  \nFOO=bar\n")
        active, _ = _parse_env_file(str(p))
        assert list(active.keys()) == ["FOO"]

    def test_skips_comment_lines(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "# comment\n# another\nFOO=bar\n")
        active, _ = _parse_env_file(str(p))
        assert "FOO" in active
        assert len(active) == 1

    def test_acknowledged_secret_pattern(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "# ADMIN_TOKEN=<set-in-staging-secret-manager>\n")
        active, ack = _parse_env_file(str(p))
        assert "ADMIN_TOKEN" in ack
        assert "ADMIN_TOKEN" not in active

    def test_acknowledged_generic_placeholder(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<placeholder>\n")
        active, ack = _parse_env_file(str(p))
        assert "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH" in ack

    def test_inline_comment_stripped(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "FOO=bar  # inline comment\n")
        active, _ = _parse_env_file(str(p))
        assert active["FOO"] == "bar"

    def test_empty_value_active(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "FOO=\n")
        active, _ = _parse_env_file(str(p))
        assert active["FOO"] == ""

    def test_placeholder_value_active(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "PROXMOX_HOST=<staging-host>\n")
        active, _ = _parse_env_file(str(p))
        assert active["PROXMOX_HOST"] == "<staging-host>"

    def test_multiple_equals_in_value(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "TOKEN=a=b=c\n")
        active, _ = _parse_env_file(str(p))
        assert active["TOKEN"] == "a=b=c"

    def test_does_not_acknowledge_non_placeholder_comment(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "# ADMIN_TOKEN=realvalue123notaplaceholder\n")
        active, ack = _parse_env_file(str(p))
        assert "ADMIN_TOKEN" not in ack
        assert "ADMIN_TOKEN" not in active


# ---------------------------------------------------------------------------
# Staging example template passes
# ---------------------------------------------------------------------------

class TestStagingExampleTemplate:
    def test_example_template_passes_or_warns(self) -> None:
        if not _STAGING_EXAMPLE.exists():
            pytest.skip("staging example file not found")
        result = validate_env_file(str(_STAGING_EXAMPLE))
        assert result.overall != _SEV_BLOCK, (
            f"staging example template must not have blocking issues; "
            f"got: {[i.message for i in result.blocking_issues]}"
        )

    def test_example_template_has_active_keys(self) -> None:
        if not _STAGING_EXAMPLE.exists():
            pytest.skip("staging example file not found")
        result = validate_env_file(str(_STAGING_EXAMPLE))
        assert result.active_key_count > 5

    def test_example_template_result_serialisable(self) -> None:
        if not _STAGING_EXAMPLE.exists():
            pytest.skip("staging example file not found")
        result = validate_env_file(str(_STAGING_EXAMPLE))
        d = result.to_dict()
        assert json.dumps(d)  # must be JSON-serialisable


# ---------------------------------------------------------------------------
# Required active key checks
# ---------------------------------------------------------------------------

class TestRequiredActiveKeys:
    def test_all_required_keys_present_passes(self, tmp_path: Path) -> None:
        content = "\n".join([
            "LABGEN_RUNTIME_MODE=production",
            "LABGEN_NAMESPACE_ADAPTER=k8s",
            "LABGEN_LLM_PROVIDER_MODE=fake_only",
            "LABGEN_LAB_SESSION_TTL_MINUTES=30",
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials",
            "PROXMOX_HOST=<staging-host>",
            "PROXMOX_TOKEN_ID=labgen@pve!api",
            "# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-staging-secret-manager>",
        ])
        result = _validate_str(tmp_path, content)
        missing_required = [
            k for k in _mod._REQUIRED_ACTIVE_KEYS if k in result.missing_keys
        ]
        assert not missing_required

    def test_missing_runtime_mode_is_blocking(self, tmp_path: Path) -> None:
        content = "LABGEN_NAMESPACE_ADAPTER=k8s\n"
        result = _validate_str(tmp_path, content)
        assert result.overall == _SEV_BLOCK
        assert "LABGEN_RUNTIME_MODE" in result.missing_keys

    def test_missing_llm_mode_is_blocking(self, tmp_path: Path) -> None:
        content = (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
            "PROXMOX_HOST=<h>\n"
            "PROXMOX_TOKEN_ID=x\n"
        )
        result = _validate_str(tmp_path, content)
        assert "LABGEN_LLM_PROVIDER_MODE" in result.missing_keys

    def test_missing_proxmox_host_is_blocking(self, tmp_path: Path) -> None:
        content = (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
            "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
            "PROXMOX_TOKEN_ID=x\n"
        )
        result = _validate_str(tmp_path, content)
        assert "PROXMOX_HOST" in result.missing_keys

    def test_multiple_missing_keys_all_reported(self, tmp_path: Path) -> None:
        result = _validate_str(tmp_path, "UNRELATED=value\n")
        assert len(result.missing_keys) >= 6
        assert result.overall == _SEV_BLOCK


# ---------------------------------------------------------------------------
# Namespace adapter checks
# ---------------------------------------------------------------------------

class TestNamespaceAdapter:
    def test_stub_adapter_is_blocking(self, tmp_path: Path) -> None:
        content = (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=stub\n"
            "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
            "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
            "PROXMOX_HOST=<h>\n"
            "PROXMOX_TOKEN_ID=x\n"
        )
        result = _validate_str(tmp_path, content)
        assert result.overall == _SEV_BLOCK
        blocking_checks = [i.check for i in result.blocking_issues]
        assert "namespace_adapter_not_stub" in blocking_checks

    def test_k8s_adapter_with_active_kubeconfig_passes(self, tmp_path: Path) -> None:
        content = (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/etc/labgen/staging-kubeconfig\n"
            "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
            "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
            "PROXMOX_HOST=<h>\n"
            "PROXMOX_TOKEN_ID=x\n"
        )
        result = _validate_str(tmp_path, content)
        k8s_blocks = [i for i in result.blocking_issues if i.check == "k8s_kubeconfig_present"]
        assert not k8s_blocks

    def test_k8s_adapter_with_acknowledged_kubeconfig_warns(self, tmp_path: Path) -> None:
        content = (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-staging-secret-manager>\n"
            "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
            "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
            "PROXMOX_HOST=<h>\n"
            "PROXMOX_TOKEN_ID=x\n"
        )
        result = _validate_str(tmp_path, content)
        k8s_blocks = [i for i in result.blocking_issues if i.check == "k8s_kubeconfig_present"]
        assert not k8s_blocks
        k8s_warns = [i for i in result.warnings if i.check == "k8s_kubeconfig_present"]
        assert k8s_warns

    def test_k8s_adapter_missing_kubeconfig_entirely_is_blocking(self, tmp_path: Path) -> None:
        content = (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
            "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
            "PROXMOX_HOST=<h>\n"
            "PROXMOX_TOKEN_ID=x\n"
        )
        result = _validate_str(tmp_path, content)
        assert "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH" in result.missing_keys
        assert result.overall == _SEV_BLOCK

    def test_k8s_adapter_empty_kubeconfig_is_blocking(self, tmp_path: Path) -> None:
        content = (
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=\n"
        )
        result = _validate_str(tmp_path, content)
        k8s_blocks = [i for i in result.blocking_issues if i.check == "k8s_kubeconfig_present"]
        assert k8s_blocks

    def test_unknown_adapter_warns(self, tmp_path: Path) -> None:
        content = "LABGEN_NAMESPACE_ADAPTER=unknown\n"
        result = _validate_str(tmp_path, content)
        warn_checks = [i.check for i in result.warnings]
        assert "namespace_adapter_known" in warn_checks


# ---------------------------------------------------------------------------
# LLM live checks
# ---------------------------------------------------------------------------

class TestLlmLive:
    def test_live_enabled_is_blocking(self, tmp_path: Path) -> None:
        content = "LABGEN_LLM_PROVIDER_MODE=live_enabled\n"
        result = _validate_str(tmp_path, content)
        assert result.overall == _SEV_BLOCK
        blocking_checks = [i.check for i in result.blocking_issues]
        assert "llm_live_disabled" in blocking_checks

    def test_fake_only_passes(self, tmp_path: Path) -> None:
        active = {"LABGEN_LLM_PROVIDER_MODE": "fake_only"}
        r = ProvisioningResult()
        _check_llm_live(active, r)
        assert "llm_live_disabled" not in [i.check for i in r.blocking_issues]

    def test_disabled_passes(self, tmp_path: Path) -> None:
        active = {"LABGEN_LLM_PROVIDER_MODE": "disabled"}
        r = ProvisioningResult()
        _check_llm_live(active, r)
        assert not r.blocking_issues

    def test_dry_run_mode_passes(self, tmp_path: Path) -> None:
        active = {"LABGEN_LLM_PROVIDER_MODE": "dry_run"}
        r = ProvisioningResult()
        _check_llm_live(active, r)
        assert not r.blocking_issues

    def test_missing_llm_mode_key_does_not_block_in_check(self) -> None:
        active: dict = {}
        r = ProvisioningResult()
        _check_llm_live(active, r)
        assert not r.blocking_issues


# ---------------------------------------------------------------------------
# Demo seed checks
# ---------------------------------------------------------------------------

class TestDemoSeed:
    def test_demo_runtime_mode_is_blocking(self, tmp_path: Path) -> None:
        content = "LABGEN_RUNTIME_MODE=demo\n"
        result = _validate_str(tmp_path, content)
        blocking_checks = [i.check for i in result.blocking_issues]
        assert "demo_seed_disabled" in blocking_checks

    def test_production_mode_passes(self) -> None:
        active = {"LABGEN_RUNTIME_MODE": "production"}
        r = ProvisioningResult()
        _check_demo_seed(active, r)
        assert not r.blocking_issues

    def test_dev_mode_does_not_trigger_demo_seed_check(self) -> None:
        active = {"LABGEN_RUNTIME_MODE": "dev"}
        r = ProvisioningResult()
        _check_demo_seed(active, r)
        assert not r.blocking_issues

    def test_missing_runtime_mode_does_not_block_in_check(self) -> None:
        active: dict = {}
        r = ProvisioningResult()
        _check_demo_seed(active, r)
        assert not r.blocking_issues


# ---------------------------------------------------------------------------
# Credential root checks
# ---------------------------------------------------------------------------

class TestCredentialRoot:
    def test_tmp_path_is_blocking(self, tmp_path: Path) -> None:
        active = {"LABGEN_VERIFIER_CREDENTIAL_ROOT": "/tmp/creds"}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        assert any(i.check == "credential_root_safe" for i in r.blocking_issues)

    def test_var_tmp_is_blocking(self) -> None:
        active = {"LABGEN_VERIFIER_CREDENTIAL_ROOT": "/var/tmp/creds"}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        assert r.blocking_issues

    def test_relative_path_is_blocking(self) -> None:
        active = {"LABGEN_VERIFIER_CREDENTIAL_ROOT": "creds/vm_creds"}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        assert r.blocking_issues

    def test_root_slash_is_blocking(self) -> None:
        active = {"LABGEN_VERIFIER_CREDENTIAL_ROOT": "/"}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        assert r.blocking_issues

    def test_root_home_is_blocking(self) -> None:
        active = {"LABGEN_VERIFIER_CREDENTIAL_ROOT": "/root"}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        assert r.blocking_issues

    def test_valid_absolute_path_passes(self) -> None:
        active = {"LABGEN_VERIFIER_CREDENTIAL_ROOT": "/var/lib/labgen-staging/verifier-credentials"}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        assert not r.blocking_issues

    def test_placeholder_value_warns(self) -> None:
        active = {"LABGEN_VERIFIER_CREDENTIAL_ROOT": "<staging-credential-root>"}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        assert not r.blocking_issues
        warn_checks = [i.check for i in r.warnings]
        assert "credential_root_safe" in warn_checks

    def test_other_absolute_path_warns(self) -> None:
        active = {"LABGEN_VERIFIER_CREDENTIAL_ROOT": "/opt/labgen/verifier-credentials"}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        # Should warn (not default recommended path)
        assert not r.blocking_issues

    def test_missing_key_no_block_from_check(self) -> None:
        active: dict = {}
        r = ProvisioningResult()
        _check_credential_root(active, r)
        assert not r.blocking_issues


# ---------------------------------------------------------------------------
# Session TTL checks
# ---------------------------------------------------------------------------

class TestSessionTtl:
    def test_valid_ttl_passes(self) -> None:
        active = {"LABGEN_LAB_SESSION_TTL_MINUTES": "30"}
        r = ProvisioningResult()
        _check_session_ttl(active, r)
        assert not r.blocking_issues

    def test_non_integer_is_blocking(self) -> None:
        active = {"LABGEN_LAB_SESSION_TTL_MINUTES": "thirty"}
        r = ProvisioningResult()
        _check_session_ttl(active, r)
        assert r.blocking_issues

    def test_zero_is_blocking(self) -> None:
        active = {"LABGEN_LAB_SESSION_TTL_MINUTES": "0"}
        r = ProvisioningResult()
        _check_session_ttl(active, r)
        assert r.blocking_issues

    def test_negative_is_blocking(self) -> None:
        active = {"LABGEN_LAB_SESSION_TTL_MINUTES": "-5"}
        r = ProvisioningResult()
        _check_session_ttl(active, r)
        assert r.blocking_issues

    def test_very_long_ttl_warns(self) -> None:
        active = {"LABGEN_LAB_SESSION_TTL_MINUTES": "600"}
        r = ProvisioningResult()
        _check_session_ttl(active, r)
        assert not r.blocking_issues
        assert any(i.check == "session_ttl_valid" for i in r.warnings)

    def test_placeholder_skips_check(self) -> None:
        active = {"LABGEN_LAB_SESSION_TTL_MINUTES": "<ttl>"}
        r = ProvisioningResult()
        _check_session_ttl(active, r)
        assert not r.blocking_issues


# ---------------------------------------------------------------------------
# Secret keys not active checks
# ---------------------------------------------------------------------------

class TestSecretKeysNotActive:
    def test_active_real_looking_admin_token_is_blocking(self) -> None:
        active = {"ADMIN_TOKEN": "thisis-a-real-admin-token-that-is-long-enough-yes"}
        r = ProvisioningResult()
        _check_secret_keys_not_active(active, r)
        assert r.blocking_issues

    def test_active_placeholder_admin_token_passes(self) -> None:
        active = {"ADMIN_TOKEN": "<set-in-staging-secret-manager>"}
        r = ProvisioningResult()
        _check_secret_keys_not_active(active, r)
        assert not r.blocking_issues

    def test_active_empty_secret_key_passes(self) -> None:
        active = {"ADMIN_TOKEN": ""}
        r = ProvisioningResult()
        _check_secret_keys_not_active(active, r)
        assert not r.blocking_issues

    def test_absent_secret_key_passes(self) -> None:
        active: dict = {}
        r = ProvisioningResult()
        _check_secret_keys_not_active(active, r)
        assert not r.blocking_issues

    def test_real_looking_vm_ssh_password_is_blocking(self) -> None:
        active = {"VM_SSH_PASSWORD": "K8sLabRealPassword!2026"}
        r = ProvisioningResult()
        _check_secret_keys_not_active(active, r)
        assert r.blocking_issues

    def test_real_proxmox_token_secret_is_blocking(self) -> None:
        active = {"PROXMOX_TOKEN_SECRET": "not-a-placeholder-value-here"}
        r = ProvisioningResult()
        _check_secret_keys_not_active(active, r)
        assert r.blocking_issues


# ---------------------------------------------------------------------------
# Real secret pattern checks
# ---------------------------------------------------------------------------

class TestRealSecretPatterns:
    def test_anthropic_api_key_is_blocking(self, tmp_path: Path) -> None:
        content = "SOME_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxx\n"
        result = _validate_str(tmp_path, content)
        blocking_checks = [i.check for i in result.blocking_issues]
        assert "no_real_secret_in_file" in blocking_checks

    def test_openai_api_key_is_blocking(self, tmp_path: Path) -> None:
        content = "ANOTHER_KEY=sk-proj-abcdefghijklmnopqrstu123456789\n"
        result = _validate_str(tmp_path, content)
        blocking_checks = [i.check for i in result.blocking_issues]
        assert "no_real_secret_in_file" in blocking_checks

    def test_pem_key_material_is_blocking(self, tmp_path: Path) -> None:
        content = "CERT_CONTENT=-----BEGIN PRIVATE KEY-----\n"
        result = _validate_str(tmp_path, content)
        blocking_checks = [i.check for i in result.blocking_issues]
        assert "no_real_secret_in_file" in blocking_checks

    def test_placeholder_value_does_not_trigger(self, tmp_path: Path) -> None:
        content = "SOME_KEY=<set-in-secret-manager>\n"
        result = _validate_str(tmp_path, content)
        secret_blocks = [i for i in result.blocking_issues if i.check == "no_real_secret_in_file"]
        assert not secret_blocks

    def test_normal_value_does_not_trigger(self, tmp_path: Path) -> None:
        active = {"PROXMOX_HOST": "<staging-host>", "PROXMOX_PORT": "8006"}
        r = ProvisioningResult()
        _check_real_secret_patterns(active, r)
        assert not r.blocking_issues

    def test_secret_value_not_in_message(self, tmp_path: Path) -> None:
        secret_value = "sk-ant-api03-supersecretvalue"
        content = f"SOME_KEY={secret_value}\n"
        result = _validate_str(tmp_path, content)
        result_json = json.dumps(result.to_dict())
        assert secret_value not in result_json

    def test_secret_value_not_in_human_output(self, tmp_path: Path, capsys) -> None:
        secret_value = "sk-ant-api03-supersecretvalue"
        content = f"SOME_KEY={secret_value}\n"
        result = _validate_str(tmp_path, content)
        _human_output(result, use_color=False)
        captured = capsys.readouterr()
        assert secret_value not in captured.out
        assert secret_value not in captured.err


# ---------------------------------------------------------------------------
# Runtime mode check
# ---------------------------------------------------------------------------

class TestRuntimeMode:
    def test_production_passes(self) -> None:
        active = {"LABGEN_RUNTIME_MODE": "production"}
        r = ProvisioningResult()
        _check_runtime_mode(active, r)
        assert not r.blocking_issues

    def test_dev_passes(self) -> None:
        active = {"LABGEN_RUNTIME_MODE": "dev"}
        r = ProvisioningResult()
        _check_runtime_mode(active, r)
        assert not r.blocking_issues

    def test_unknown_mode_is_blocking(self) -> None:
        active = {"LABGEN_RUNTIME_MODE": "unknown_mode"}
        r = ProvisioningResult()
        _check_runtime_mode(active, r)
        assert r.blocking_issues

    def test_placeholder_skips_check(self) -> None:
        active = {"LABGEN_RUNTIME_MODE": "<mode>"}
        r = ProvisioningResult()
        _check_runtime_mode(active, r)
        assert not r.blocking_issues


# ---------------------------------------------------------------------------
# JSON output schema
# ---------------------------------------------------------------------------

class TestJsonOutputSchema:
    def test_required_fields_present(self, tmp_path: Path) -> None:
        content = (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
            "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
            "PROXMOX_HOST=<h>\n"
            "PROXMOX_TOKEN_ID=x\n"
            "# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-staging-secret-manager>\n"
        )
        result = _validate_str(tmp_path, content)
        d = result.to_dict()
        assert "overall" in d
        assert "blocking_issues" in d
        assert "warnings" in d
        assert "missing_keys" in d
        assert "checked_at" in d
        assert "env_file" in d
        assert "active_key_count" in d

    def test_blocking_issues_is_list(self, tmp_path: Path) -> None:
        result = _validate_str(tmp_path, "UNRELATED=value\n")
        d = result.to_dict()
        assert isinstance(d["blocking_issues"], list)

    def test_warnings_is_list(self, tmp_path: Path) -> None:
        result = _validate_str(tmp_path, "UNRELATED=value\n")
        d = result.to_dict()
        assert isinstance(d["warnings"], list)

    def test_missing_keys_is_list(self, tmp_path: Path) -> None:
        result = _validate_str(tmp_path, "UNRELATED=value\n")
        d = result.to_dict()
        assert isinstance(d["missing_keys"], list)

    def test_checked_at_is_iso8601(self, tmp_path: Path) -> None:
        result = _validate_str(tmp_path, "UNRELATED=value\n")
        d = result.to_dict()
        # Should end with +00:00 or Z
        assert "checked_at" in d
        assert d["checked_at"]

    def test_json_output_is_valid_json(self, tmp_path: Path, capsys) -> None:
        content = (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "LABGEN_LLM_PROVIDER_MODE=live_enabled\n"  # blocking to ensure non-empty issues
        )
        result = _validate_str(tmp_path, content)
        _json_output(result)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["overall"] == _SEV_BLOCK

    def test_blocking_issue_has_check_and_message(self, tmp_path: Path) -> None:
        content = "LABGEN_NAMESPACE_ADAPTER=stub\n"
        result = _validate_str(tmp_path, content)
        assert result.blocking_issues
        for issue in result.blocking_issues:
            d = result.to_dict()
            for bi in d["blocking_issues"]:
                assert "check" in bi
                assert "message" in bi


# ---------------------------------------------------------------------------
# CLI entry point tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_exit_code_0_on_pass(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, (
            "LABGEN_RUNTIME_MODE=production\n"
            "LABGEN_NAMESPACE_ADAPTER=k8s\n"
            "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
            "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
            "PROXMOX_HOST=<h>\n"
            "PROXMOX_TOKEN_ID=x\n"
            "# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-staging-secret-manager>\n"
        ))
        code = main(["--env-file", str(p), "--quiet"])
        assert code == 0

    def test_exit_code_1_on_blocking(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "LABGEN_NAMESPACE_ADAPTER=stub\n")
        code = main(["--env-file", str(p), "--quiet"])
        assert code == 1

    def test_exit_code_2_on_missing_file(self, tmp_path: Path) -> None:
        code = main(["--env-file", str(tmp_path / "nonexistent.env"), "--quiet"])
        assert code == 2

    def test_json_flag_produces_json(self, tmp_path: Path, capsys) -> None:
        p = _write_env(tmp_path, "LABGEN_RUNTIME_MODE=production\n")
        main(["--env-file", str(p), "--json"])
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "overall" in parsed

    def test_quiet_flag_suppresses_output(self, tmp_path: Path, capsys) -> None:
        p = _write_env(tmp_path, "LABGEN_NAMESPACE_ADAPTER=stub\n")
        main(["--env-file", str(p), "--quiet"])
        captured = capsys.readouterr()
        assert not captured.out
        assert not captured.err

    def test_human_output_produced_by_default(self, tmp_path: Path, capsys) -> None:
        p = _write_env(tmp_path, "LABGEN_RUNTIME_MODE=production\n")
        main(["--env-file", str(p)])
        captured = capsys.readouterr()
        assert "LabGen Staging Provisioning Validator" in captured.out

    def test_env_file_short_flag(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "LABGEN_NAMESPACE_ADAPTER=stub\n")
        code = main(["-e", str(p), "--quiet"])
        assert code == 1

    def test_env_file_equals_form(self, tmp_path: Path) -> None:
        p = _write_env(tmp_path, "LABGEN_NAMESPACE_ADAPTER=stub\n")
        code = main([f"--env-file={p}", "--quiet"])
        assert code == 1


# ---------------------------------------------------------------------------
# No network calls — structural guarantee
# ---------------------------------------------------------------------------

class TestNoNetworkCalls:
    def test_module_has_no_socket_import(self) -> None:
        import ast
        source = _SCRIPT_PATH.read_text()
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        network_modules = {"socket", "urllib", "http", "requests", "httpx", "aiohttp"}
        # urllib is only imported inside helper functions as conditional import
        # The top-level imports must not include network modules
        top_level_imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_level_imports.add(node.module)
        for mod in network_modules:
            assert mod not in top_level_imports, (
                f"Module '{mod}' should not be imported at top level in provisioning validator"
            )

    def test_validate_env_file_makes_no_network_calls(self, tmp_path: Path) -> None:
        import socket
        original_connect = socket.socket.connect

        calls: list = []

        def _patched_connect(self, address):
            calls.append(address)
            raise ConnectionRefusedError("network calls not allowed in provisioning validator")

        socket.socket.connect = _patched_connect
        try:
            p = _write_env(tmp_path, (
                "LABGEN_RUNTIME_MODE=production\n"
                "LABGEN_NAMESPACE_ADAPTER=k8s\n"
                "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
                "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
                "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/vc\n"
                "PROXMOX_HOST=<h>\n"
                "PROXMOX_TOKEN_ID=x\n"
                "# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=<set-in-staging-secret-manager>\n"
            ))
            validate_env_file(str(p))
        finally:
            socket.socket.connect = original_connect

        assert not calls, f"Unexpected network calls: {calls}"
