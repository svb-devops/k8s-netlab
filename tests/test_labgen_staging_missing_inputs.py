"""
Tests for scripts/labgen_staging_missing_inputs.py

Covers:
  A. .env.staging.example → correct missing inputs detected
  B. Complete fake env → no missing inputs
  C. Placeholder values treated as missing
  D. Empty string treated as missing
  E. Secret value never appears in output
  F. JSON output schema stability
  G. Grouping correctness
  H. Unreadable / missing env file → exit code 2
  I. No network calls
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
sys.path.insert(0, _SCRIPTS_DIR)

from labgen_staging_missing_inputs import (
    MissingInputsResult,
    _is_input_ready,
    check_missing_inputs,
    main,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STAGING_EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "deploy", "labgen", ".env.staging.example",
)


def _write_env(content: str) -> str:
    """Write content to a temporary env file; caller must delete."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False)
    f.write(textwrap.dedent(content))
    f.flush()
    f.close()
    return f.name


_COMPLETE_FAKE_ENV = """\
    # Complete fake staging env — all blocking inputs provided
    LABGEN_RUNTIME_MODE=production
    LABGEN_NAMESPACE_ADAPTER=k8s
    LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml
    LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials
    LABGEN_LLM_PROVIDER_MODE=fake_only
    LABGEN_LAB_SESSION_TTL_MINUTES=30
    PROXMOX_HOST=staging-proxmox.internal
    PROXMOX_TOKEN_ID=staging@pve!labgen-api
    PROXMOX_TOKEN_SECRET=aabbcc112233445566778899aabbcc11
    ADMIN_TOKEN=staging-admin-token-32-chars-here-extra
    VM_SSH_PASSWORD=staging-vm-password-secure-value
    VM_REGISTRY_MIRROR=http://staging-registry.internal:5000
"""


# ---------------------------------------------------------------------------
# A. .env.staging.example → missing inputs
# ---------------------------------------------------------------------------

class TestStagingExampleMissingInputs:
    def test_staging_example_is_blocking(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        assert result.overall == "blocking"

    def test_staging_example_has_expected_missing_count(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        # K3s kubeconfig, ADMIN_TOKEN, PROXMOX_HOST, PROXMOX_TOKEN_SECRET,
        # VM_SSH_PASSWORD, VM_REGISTRY_MIRROR (contains <staging-host>)
        assert result.missing_count == 6

    def test_k3s_kubeconfig_missing(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        assert "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH" in result.all_missing_keys

    def test_admin_token_missing(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        assert "ADMIN_TOKEN" in result.all_missing_keys

    def test_proxmox_host_missing(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        assert "PROXMOX_HOST" in result.all_missing_keys

    def test_proxmox_token_secret_missing(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        assert "PROXMOX_TOKEN_SECRET" in result.all_missing_keys

    def test_vm_ssh_password_missing(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        assert "VM_SSH_PASSWORD" in result.all_missing_keys

    def test_registry_mirror_missing_due_to_placeholder_host(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        assert "VM_REGISTRY_MIRROR" in result.all_missing_keys

    def test_verifier_credential_root_not_missing(self):
        # staging example has LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/...
        result = check_missing_inputs(_STAGING_EXAMPLE)
        assert "LABGEN_VERIFIER_CREDENTIAL_ROOT" not in result.all_missing_keys


# ---------------------------------------------------------------------------
# B. Complete fake env → no missing inputs
# ---------------------------------------------------------------------------

class TestCompleteFakeEnv:
    def test_complete_env_passes(self):
        env_file = _write_env(_COMPLETE_FAKE_ENV)
        try:
            result = check_missing_inputs(env_file)
            assert result.overall == "pass"
        finally:
            os.unlink(env_file)

    def test_complete_env_missing_count_zero(self):
        env_file = _write_env(_COMPLETE_FAKE_ENV)
        try:
            result = check_missing_inputs(env_file)
            assert result.missing_count == 0
        finally:
            os.unlink(env_file)

    def test_complete_env_all_missing_keys_empty(self):
        env_file = _write_env(_COMPLETE_FAKE_ENV)
        try:
            result = check_missing_inputs(env_file)
            assert result.all_missing_keys == []
        finally:
            os.unlink(env_file)


# ---------------------------------------------------------------------------
# C. Placeholder secrets treated as missing
# ---------------------------------------------------------------------------

class TestPlaceholderTreatedAsMissing:
    def test_pure_placeholder_value_is_missing(self):
        env_file = _write_env("""\
            ADMIN_TOKEN=<set-in-secret-manager>
            LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml
            PROXMOX_HOST=staging.internal
            PROXMOX_TOKEN_SECRET=aabbccdd11223344
            VM_SSH_PASSWORD=staging-password
            VM_REGISTRY_MIRROR=http://staging-registry.internal:5000
            LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials
        """)
        try:
            result = check_missing_inputs(env_file)
            assert "ADMIN_TOKEN" in result.all_missing_keys
        finally:
            os.unlink(env_file)

    def test_commented_placeholder_is_missing(self):
        env_file = _write_env("""\
            # ADMIN_TOKEN=<set-in-secret-manager>
            LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml
            PROXMOX_HOST=staging.internal
            PROXMOX_TOKEN_SECRET=aabbccdd11223344
            VM_SSH_PASSWORD=staging-password
            VM_REGISTRY_MIRROR=http://staging-registry.internal:5000
            LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials
        """)
        try:
            result = check_missing_inputs(env_file)
            assert "ADMIN_TOKEN" in result.all_missing_keys
        finally:
            os.unlink(env_file)

    def test_value_containing_placeholder_token_is_missing(self):
        # e.g. http://<staging-host>:5000 — contains <staging-host>
        env_file = _write_env("""\
            LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml
            ADMIN_TOKEN=staging-admin-token-32-chars-here-extra
            PROXMOX_HOST=staging.internal
            PROXMOX_TOKEN_SECRET=aabbccdd11223344
            VM_SSH_PASSWORD=staging-password
            VM_REGISTRY_MIRROR=http://<staging-host>:5000
            LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials
        """)
        try:
            result = check_missing_inputs(env_file)
            assert "VM_REGISTRY_MIRROR" in result.all_missing_keys
        finally:
            os.unlink(env_file)

    def test_key_absent_entirely_is_missing(self):
        env_file = _write_env("""\
            LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml
            ADMIN_TOKEN=staging-admin-token-32-chars-here-extra
            PROXMOX_HOST=staging.internal
            VM_SSH_PASSWORD=staging-password
            VM_REGISTRY_MIRROR=http://staging-registry.internal:5000
            LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials
        """)
        # PROXMOX_TOKEN_SECRET is completely absent
        try:
            result = check_missing_inputs(env_file)
            assert "PROXMOX_TOKEN_SECRET" in result.all_missing_keys
        finally:
            os.unlink(env_file)

    def test_reason_for_placeholder_is_placeholder(self):
        env_file = _write_env("ADMIN_TOKEN=<set-in-secret-manager>\n")
        try:
            result = check_missing_inputs(env_file)
            admin_items = result.groups["auth_admin"].missing_items
            assert len(admin_items) == 1
            assert admin_items[0].reason == "placeholder"
        finally:
            os.unlink(env_file)

    def test_reason_for_absent_key_is_absent(self):
        env_file = _write_env("# nothing here\n")
        try:
            result = check_missing_inputs(env_file)
            admin_items = result.groups["auth_admin"].missing_items
            assert len(admin_items) == 1
            assert admin_items[0].reason == "absent"
        finally:
            os.unlink(env_file)


# ---------------------------------------------------------------------------
# D. Empty string treated as missing
# ---------------------------------------------------------------------------

class TestEmptyStringTreatedAsMissing:
    def test_empty_active_value_is_missing(self):
        env_file = _write_env("ADMIN_TOKEN=\n")
        try:
            result = check_missing_inputs(env_file)
            assert "ADMIN_TOKEN" in result.all_missing_keys
        finally:
            os.unlink(env_file)

    def test_empty_active_reason_is_empty(self):
        env_file = _write_env("ADMIN_TOKEN=\n")
        try:
            result = check_missing_inputs(env_file)
            items = result.groups["auth_admin"].missing_items
            assert items[0].reason == "empty"
        finally:
            os.unlink(env_file)

    def test_empty_kubeconfig_path_is_missing(self):
        env_file = _write_env("LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=\n")
        try:
            result = check_missing_inputs(env_file)
            assert "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH" in result.all_missing_keys
        finally:
            os.unlink(env_file)


# ---------------------------------------------------------------------------
# E. Secret value never appears in output
# ---------------------------------------------------------------------------

class TestSecretValueNotInOutput:
    _REAL_SECRET = "sk-ant-api03-SUPERSECRETVALUE12345678901234567890"

    def _result_with_real_secret_in_env(self) -> MissingInputsResult:
        env_file = _write_env(
            f"PROXMOX_TOKEN_SECRET={self._REAL_SECRET}\n"
            "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/tmp/kc.yaml\n"
            "ADMIN_TOKEN=staging-admin-token-32chars-x\n"
            "PROXMOX_HOST=staging.internal\n"
            "VM_SSH_PASSWORD=staging-pass\n"
            "VM_REGISTRY_MIRROR=http://staging-registry.internal:5000\n"
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/creds\n"
        )
        try:
            return check_missing_inputs(env_file)
        finally:
            os.unlink(env_file)

    def test_secret_not_in_result_dict(self):
        result = self._result_with_real_secret_in_env()
        serialized = json.dumps(result.to_dict())
        assert self._REAL_SECRET not in serialized

    def test_secret_not_in_human_output(self):
        result = self._result_with_real_secret_in_env()
        captured = StringIO()
        with patch("sys.stdout", captured):
            from labgen_staging_missing_inputs import _human_output
            _human_output(result, use_color=False)
        assert self._REAL_SECRET not in captured.getvalue()

    def test_secret_not_in_json_output(self):
        result = self._result_with_real_secret_in_env()
        captured = StringIO()
        with patch("sys.stdout", captured):
            from labgen_staging_missing_inputs import _json_output
            _json_output(result)
        assert self._REAL_SECRET not in captured.getvalue()

    def test_all_missing_keys_contain_only_key_names_not_values(self):
        result = self._result_with_real_secret_in_env()
        for key in result.all_missing_keys:
            assert self._REAL_SECRET not in key

    def test_ready_key_value_not_in_result(self):
        # PROXMOX_TOKEN_SECRET is a "real" secret value — it should not appear
        # even if it's classified as "set" (i.e., it passes the check)
        env_file = _write_env(
            f"PROXMOX_TOKEN_SECRET={self._REAL_SECRET}\n"
        )
        try:
            result = check_missing_inputs(env_file)
            serialized = json.dumps(result.to_dict())
            assert self._REAL_SECRET not in serialized
        finally:
            os.unlink(env_file)


# ---------------------------------------------------------------------------
# F. JSON output schema stability
# ---------------------------------------------------------------------------

class TestJsonOutputSchema:
    def _get_json_output(self, env_file: str) -> dict:
        captured = StringIO()
        with patch("sys.stdout", captured):
            main(["--env-file", env_file, "--json"])
        return json.loads(captured.getvalue())

    def test_top_level_keys_present(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        assert "overall" in output
        assert "missing_count" in output
        assert "groups" in output
        assert "all_missing_keys" in output
        assert "env_file" in output
        assert "checked_at" in output

    def test_overall_is_string(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        assert isinstance(output["overall"], str)
        assert output["overall"] in ("pass", "blocking")

    def test_missing_count_is_int(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        assert isinstance(output["missing_count"], int)

    def test_all_missing_keys_is_list_of_strings(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        assert isinstance(output["all_missing_keys"], list)
        for key in output["all_missing_keys"]:
            assert isinstance(key, str)

    def test_groups_keys_are_expected(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        expected_groups = {"k3s", "auth_admin", "proxmox", "vm_access", "registry", "storage"}
        assert set(output["groups"].keys()) == expected_groups

    def test_group_structure(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        for group_id, group in output["groups"].items():
            assert "label" in group
            assert "missing_count" in group
            assert "items" in group
            assert isinstance(group["items"], list)

    def test_item_structure(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        k3s_group = output["groups"]["k3s"]
        assert k3s_group["missing_count"] >= 1
        item = k3s_group["items"][0]
        assert "key" in item
        assert "status" in item
        assert "reason" in item
        assert "description" in item
        assert "required_for" in item
        assert "owner" in item

    def test_item_status_is_missing(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        for group in output["groups"].values():
            for item in group["items"]:
                assert item["status"] == "missing"

    def test_item_reason_valid_values(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        valid_reasons = {"absent", "empty", "placeholder"}
        for group in output["groups"].values():
            for item in group["items"]:
                assert item["reason"] in valid_reasons

    def test_pass_env_schema(self):
        env_file = _write_env(_COMPLETE_FAKE_ENV)
        try:
            output = self._get_json_output(env_file)
            assert output["overall"] == "pass"
            assert output["missing_count"] == 0
            assert output["all_missing_keys"] == []
            for group in output["groups"].values():
                assert group["missing_count"] == 0
                assert group["items"] == []
        finally:
            os.unlink(env_file)

    def test_checked_at_is_iso8601(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        # Should contain 'T' and end with timezone info
        assert "T" in output["checked_at"]

    def test_env_file_matches_input(self):
        output = self._get_json_output(_STAGING_EXAMPLE)
        assert output["env_file"] == _STAGING_EXAMPLE


# ---------------------------------------------------------------------------
# G. Grouping correctness
# ---------------------------------------------------------------------------

class TestGrouping:
    def test_kubeconfig_in_k3s_group(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        k3s_keys = [i.key for i in result.groups["k3s"].missing_items]
        assert "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH" in k3s_keys

    def test_admin_token_in_auth_admin_group(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        auth_keys = [i.key for i in result.groups["auth_admin"].missing_items]
        assert "ADMIN_TOKEN" in auth_keys

    def test_proxmox_host_and_token_in_proxmox_group(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        proxmox_keys = [i.key for i in result.groups["proxmox"].missing_items]
        assert "PROXMOX_HOST" in proxmox_keys
        assert "PROXMOX_TOKEN_SECRET" in proxmox_keys

    def test_vm_ssh_password_in_vm_access_group(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        vm_keys = [i.key for i in result.groups["vm_access"].missing_items]
        assert "VM_SSH_PASSWORD" in vm_keys

    def test_registry_mirror_in_registry_group(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        reg_keys = [i.key for i in result.groups["registry"].missing_items]
        assert "VM_REGISTRY_MIRROR" in reg_keys

    def test_verifier_root_in_storage_group(self):
        env_file = _write_env("LABGEN_VERIFIER_CREDENTIAL_ROOT=<placeholder>\n")
        try:
            result = check_missing_inputs(env_file)
            storage_keys = [i.key for i in result.groups["storage"].missing_items]
            assert "LABGEN_VERIFIER_CREDENTIAL_ROOT" in storage_keys
        finally:
            os.unlink(env_file)

    def test_all_groups_present_even_if_empty(self):
        env_file = _write_env(_COMPLETE_FAKE_ENV)
        try:
            result = check_missing_inputs(env_file)
            expected_groups = {"k3s", "auth_admin", "proxmox", "vm_access", "registry", "storage"}
            assert set(result.groups.keys()) == expected_groups
        finally:
            os.unlink(env_file)

    def test_empty_group_has_zero_missing_count(self):
        env_file = _write_env(_COMPLETE_FAKE_ENV)
        try:
            result = check_missing_inputs(env_file)
            for group in result.groups.values():
                assert group.missing_count == 0
        finally:
            os.unlink(env_file)

    def test_total_missing_count_equals_sum_of_groups(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        total = sum(g.missing_count for g in result.groups.values())
        assert total == result.missing_count

    def test_all_missing_keys_matches_group_items(self):
        result = check_missing_inputs(_STAGING_EXAMPLE)
        group_keys: list[str] = []
        for group in result.groups.values():
            group_keys.extend(i.key for i in group.missing_items)
        assert sorted(group_keys) == sorted(result.all_missing_keys)


# ---------------------------------------------------------------------------
# H. Unreadable / missing env file → exit code 2
# ---------------------------------------------------------------------------

class TestEnvFileErrors:
    def test_missing_file_returns_exit_2(self):
        rc = main(["--env-file", "/nonexistent/path/to/.env.staging"])
        assert rc == 2

    def test_missing_file_quiet_no_output(self, capsys):
        main(["--env-file", "/nonexistent/path/.env", "--quiet"])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_missing_file_prints_error(self, capsys):
        main(["--env-file", "/nonexistent/path/.env"])
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "ERROR" in captured.err

    def test_unreadable_file_returns_exit_2(self):
        from unittest.mock import patch
        with patch(
            "labgen_staging_missing_inputs._parse_env_file",
            side_effect=PermissionError("Permission denied: /secure/path/.env"),
        ):
            rc = main(["--env-file", "/secure/path/.env"])
            assert rc == 2

    def test_blocking_inputs_returns_exit_1(self):
        rc = main(["--env-file", _STAGING_EXAMPLE])
        assert rc == 1

    def test_all_inputs_set_returns_exit_0(self):
        env_file = _write_env(_COMPLETE_FAKE_ENV)
        try:
            rc = main(["--env-file", env_file])
            assert rc == 0
        finally:
            os.unlink(env_file)

    def test_quiet_blocking_no_stdout(self, capsys):
        main(["--env-file", _STAGING_EXAMPLE, "--quiet"])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_quiet_pass_no_stdout(self, capsys):
        env_file = _write_env(_COMPLETE_FAKE_ENV)
        try:
            main(["--env-file", env_file, "--quiet"])
            captured = capsys.readouterr()
            assert captured.out == ""
        finally:
            os.unlink(env_file)


# ---------------------------------------------------------------------------
# I. No network calls
# ---------------------------------------------------------------------------

class TestNoNetworkCalls:
    def test_check_missing_inputs_no_socket_call(self):
        import socket
        original_connect = socket.socket.connect

        def _fail_connect(*args, **kwargs):
            raise AssertionError("Network call detected — should not happen")

        socket.socket.connect = _fail_connect
        try:
            check_missing_inputs(_STAGING_EXAMPLE)
        finally:
            socket.socket.connect = original_connect

    def test_main_no_socket_call(self):
        import socket
        original_connect = socket.socket.connect

        def _fail_connect(*args, **kwargs):
            raise AssertionError("Network call detected — should not happen")

        socket.socket.connect = _fail_connect
        try:
            main(["--env-file", _STAGING_EXAMPLE, "--quiet"])
        finally:
            socket.socket.connect = original_connect


# ---------------------------------------------------------------------------
# Unit tests for _is_input_ready
# ---------------------------------------------------------------------------

class TestIsInputReady:
    def test_active_real_value_is_ready(self):
        ready, reason = _is_input_ready(
            "ADMIN_TOKEN",
            {"ADMIN_TOKEN": "real-admin-token-value-32chars-xx"},
            set(),
        )
        assert ready is True
        assert reason == "set"

    def test_active_empty_is_not_ready(self):
        ready, reason = _is_input_ready("ADMIN_TOKEN", {"ADMIN_TOKEN": ""}, set())
        assert ready is False
        assert reason == "empty"

    def test_active_pure_placeholder_is_not_ready(self):
        ready, reason = _is_input_ready(
            "ADMIN_TOKEN", {"ADMIN_TOKEN": "<set-in-secret-manager>"}, set()
        )
        assert ready is False
        assert reason == "placeholder"

    def test_active_value_with_embedded_placeholder_is_not_ready(self):
        ready, reason = _is_input_ready(
            "VM_REGISTRY_MIRROR",
            {"VM_REGISTRY_MIRROR": "http://<staging-host>:5000"},
            set(),
        )
        assert ready is False
        assert reason == "placeholder"

    def test_acknowledged_only_is_not_ready(self):
        ready, reason = _is_input_ready("ADMIN_TOKEN", {}, {"ADMIN_TOKEN"})
        assert ready is False
        assert reason == "placeholder"

    def test_absent_entirely_is_not_ready(self):
        ready, reason = _is_input_ready("ADMIN_TOKEN", {}, set())
        assert ready is False
        assert reason == "absent"

    def test_multiple_placeholder_formats(self):
        placeholders = [
            "<placeholder>",
            "<set-in-secret-manager>",
            "<staging-value>",
            "<redacted>",
        ]
        for ph in placeholders:
            ready, reason = _is_input_ready("SOME_KEY", {"SOME_KEY": ph}, set())
            assert ready is False, f"Expected {ph!r} to be not ready"
            assert reason == "placeholder"
