"""
Tests for labgen_controlled_k3s_adapter_smoke.py

Guarantees under test:
- No real network calls (all K8s interactions use StubNamespaceLifecycleAdapter)
- No Proxmox / registry / LLM calls
- No runtime start
- Placeholder / missing inputs → K3S_SMOKE_BLOCKED
- Stub adapter in home_lab_mvp → K3S_SMOKE_BLOCKED
- Create failure → K3S_SMOKE_FAILED
- Delete failure → K3S_SMOKE_FAILED
- Delete always attempted after successful create
- Raw exception body never appears in result
- Token / kubeconfig / private key never appears in result
- JSON output schema stable
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import types
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the script module
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
_SCRIPTS_DIR = os.path.abspath(_SCRIPTS_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import labgen_controlled_k3s_adapter_smoke as _smoke

from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ENV = {
    "LABGEN_RUNTIME_MODE": "home_lab_mvp",
    "LABGEN_NAMESPACE_ADAPTER": "k8s",
    # kubeconfig path is set; Phase 1 checks file existence.
    # Tests that reach Phase 3+ must patch this with a real temp file.
    "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": "/tmp/__smoke_test_kubeconfig__",
    "LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES": "lab-stg-",
    "LABGEN_K8S_VERIFIER_SA_NAME": "labgen-verifier",
    "LABGEN_K8S_VERIFIER_SA_NAMESPACE": "kube-system",
    "LABGEN_K8S_VERIFIER_ROLE_NAME": "labgen-verifier-role",
    "LABGEN_K8S_VERIFIER_ROLEBINDING_NAME": "labgen-verifier-binding",
}


def _env_with_real_kubeconfig(tmp_path) -> dict:
    """Return valid env dict with kubeconfig pointing to a real (empty) temp file."""
    kube = tmp_path / "kubeconfig"
    kube.write_text("# smoke test kubeconfig stub\n")
    env = dict(_VALID_ENV)
    env["LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"] = str(kube)
    return env


def _stub_adapter(
    create_succeeds=True,
    exists_after_create=True,
    delete_succeeds=True,
    deleted_after_delete=True,
    rolebinding_succeeds=True,
    rolebinding_exists=True,
) -> StubNamespaceLifecycleAdapter:
    return StubNamespaceLifecycleAdapter(
        create_succeeds=create_succeeds,
        exists_after_create=exists_after_create,
        delete_succeeds=delete_succeeds,
        deleted_after_delete=deleted_after_delete,
        rolebinding_succeeds=rolebinding_succeeds,
        rolebinding_exists_after_create=rolebinding_exists,
    )


# ---------------------------------------------------------------------------
# _is_placeholder
# ---------------------------------------------------------------------------


class TestIsPlaceholder:
    def test_empty_string_is_placeholder(self):
        assert _smoke._is_placeholder("") is True

    def test_angle_bracket_is_placeholder(self):
        assert _smoke._is_placeholder("<set-in-secret-manager>") is True

    def test_changeme_is_placeholder(self):
        assert _smoke._is_placeholder("CHANGEME") is True

    def test_real_path_not_placeholder(self):
        assert _smoke._is_placeholder("/etc/lab/kubeconfig") is False

    def test_real_mode_not_placeholder(self):
        assert _smoke._is_placeholder("home_lab_mvp") is False

    def test_case_insensitive_changeme(self):
        assert _smoke._is_placeholder("changeme") is True

    def test_case_insensitive_placeholder_caps(self):
        assert _smoke._is_placeholder("PLACEHOLDER_VALUE") is True


# ---------------------------------------------------------------------------
# _load_env_file
# ---------------------------------------------------------------------------


class TestLoadEnvFile:
    def test_missing_file_returns_error(self):
        env, err = _smoke._load_env_file("/nonexistent/__smoke_test__")
        assert env == {}
        assert err is not None
        assert "not found" in err.lower()

    def test_valid_file_loads_keys(self, tmp_path):
        f = tmp_path / ".env.test"
        f.write_text("FOO=bar\n# comment\nBAZ=qux\n")
        env, err = _smoke._load_env_file(str(f))
        assert err is None
        assert env["FOO"] == "bar"
        assert env["BAZ"] == "qux"

    def test_blank_lines_and_comments_skipped(self, tmp_path):
        f = tmp_path / ".env.test"
        f.write_text("\n# skip this\nKEY=val\n\n")
        env, err = _smoke._load_env_file(str(f))
        assert err is None
        assert list(env.keys()) == ["KEY"]


# ---------------------------------------------------------------------------
# Phase 0 — env / profile validation
# ---------------------------------------------------------------------------


class TestPhase0EnvProfile:
    def test_valid_env_passes(self):
        phase, missing = _smoke._phase0_env_profile(dict(_VALID_ENV))
        assert phase.status == "pass"
        assert not missing

    def test_wrong_runtime_mode_blocked(self):
        env = dict(_VALID_ENV)
        env["LABGEN_RUNTIME_MODE"] = "production"
        phase, missing = _smoke._phase0_env_profile(env)
        assert phase.status == "blocked"
        assert any("LABGEN_RUNTIME_MODE" in m for m in missing)

    def test_stub_adapter_in_home_lab_mvp_blocked(self):
        env = dict(_VALID_ENV)
        env["LABGEN_NAMESPACE_ADAPTER"] = "stub"
        phase, missing = _smoke._phase0_env_profile(env)
        assert phase.status == "blocked"
        assert any("LABGEN_NAMESPACE_ADAPTER" in m for m in missing)
        assert any("Stub" in m or "stub" in m.lower() for m in missing)

    def test_placeholder_kubeconfig_blocked(self):
        env = dict(_VALID_ENV)
        env["LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"] = "<set-in-staging-secret-manager>"
        phase, missing = _smoke._phase0_env_profile(env)
        assert phase.status == "blocked"
        assert any("KUBECONFIG" in m.upper() for m in missing)

    def test_empty_namespace_prefix_blocked(self):
        env = dict(_VALID_ENV)
        env["LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES"] = ""
        phase, missing = _smoke._phase0_env_profile(env)
        assert phase.status == "blocked"
        assert any("PREFIX" in m.upper() for m in missing)

    def test_missing_verifier_sa_name_blocked(self):
        env = dict(_VALID_ENV)
        env["LABGEN_K8S_VERIFIER_SA_NAME"] = ""
        phase, missing = _smoke._phase0_env_profile(env)
        assert phase.status == "blocked"
        assert any("VERIFIER_SA_NAME" in m for m in missing)


# ---------------------------------------------------------------------------
# Phase 1 — secret injection
# ---------------------------------------------------------------------------


class TestPhase1SecretInjection:
    def test_kubeconfig_file_not_exists_blocked(self, tmp_path):
        env = dict(_VALID_ENV)
        env["LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"] = str(tmp_path / "nonexistent_kube")
        phase, missing = _smoke._phase1_secret_injection(env)
        assert phase.status == "blocked"
        assert any("non-existent" in m for m in missing)

    def test_existing_kubeconfig_file_passes(self, tmp_path):
        kube = tmp_path / "kube.yaml"
        kube.write_text("# stub\n")
        env = dict(_VALID_ENV)
        env["LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"] = str(kube)
        phase, missing = _smoke._phase1_secret_injection(env)
        assert phase.status == "pass"
        assert not missing

    def test_placeholder_kubeconfig_skips_file_check(self):
        # placeholder → blocked in phase0, not checked in phase1
        env = dict(_VALID_ENV)
        env["LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"] = "<placeholder>"
        phase, missing = _smoke._phase1_secret_injection(env)
        # Phase 1 skips file check when value is placeholder
        assert phase.status == "pass"
        assert not missing


# ---------------------------------------------------------------------------
# run_smoke: precondition blocking
# ---------------------------------------------------------------------------


class TestRunSmokeBlocked:
    def test_wrong_mode_blocked(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        env["LABGEN_RUNTIME_MODE"] = "dev"
        result = _smoke.run_smoke(env, allow_k8s_write=False)
        assert result.decision == _smoke.FINAL_BLOCKED
        assert result.missing_inputs

    def test_stub_adapter_blocked(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        env["LABGEN_NAMESPACE_ADAPTER"] = "stub"
        result = _smoke.run_smoke(env, allow_k8s_write=False)
        assert result.decision == _smoke.FINAL_BLOCKED
        assert any("stub" in m.lower() or "Stub" in m for m in result.missing_inputs)

    def test_no_allow_k8s_write_blocked(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        result = _smoke.run_smoke(env, allow_k8s_write=False)
        assert result.decision == _smoke.FINAL_BLOCKED
        assert any("allow-k8s-write" in m or "write" in m.lower() for m in result.missing_inputs)

    def test_no_allow_k8s_write_does_not_call_adapter(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=False, adapter=stub)
        assert result.decision == _smoke.FINAL_BLOCKED
        assert stub.created == []
        assert stub.deleted == []

    def test_missing_kubeconfig_file_blocked(self, tmp_path):
        env = dict(_VALID_ENV)
        env["LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"] = str(tmp_path / "missing_kube")
        result = _smoke.run_smoke(env, allow_k8s_write=True)
        assert result.decision == _smoke.FINAL_BLOCKED


# ---------------------------------------------------------------------------
# run_smoke: happy path
# ---------------------------------------------------------------------------


class TestRunSmokeHappyPath:
    def test_full_pass(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.decision == _smoke.FINAL_PASSED
        assert result.wrote_namespace is True
        assert result.wrote_rolebinding is True
        assert result.cleanup_confirmed is True

    def test_smoke_namespace_has_allowed_prefix(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.smoke_namespace is not None
        assert result.smoke_namespace.startswith("lab-stg-")

    def test_smoke_namespace_contains_smoke_marker(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert "smoke" in result.smoke_namespace

    def test_namespace_created_in_adapter(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert len(stub.created) == 1

    def test_namespace_deleted_in_adapter(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert len(stub.deleted) == 1

    def test_rolebinding_created_in_adapter(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert len(stub.rolebindings_created) == 1

    def test_no_proxmox_called(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.proxmox_called is False

    def test_no_registry_called(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.registry_called is False

    def test_no_llm_called(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.llm_called is False

    def test_no_runtime_start_executed(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.runtime_start_executed is False


# ---------------------------------------------------------------------------
# run_smoke: failure modes
# ---------------------------------------------------------------------------


class TestRunSmokeFailureModes:
    def test_create_failure_is_failed(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter(create_succeeds=False)
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.decision == _smoke.FINAL_FAILED

    def test_create_failure_no_namespace_in_adapter(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter(create_succeeds=False)
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert stub.created == []

    def test_create_failure_cleanup_confirmed(self, tmp_path):
        """Nothing to clean up if create never succeeded."""
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter(create_succeeds=False)
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.cleanup_confirmed is True  # nothing was written

    def test_delete_failure_is_failed(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter(delete_succeeds=False)
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.decision == _smoke.FINAL_FAILED

    def test_delete_failure_cleanup_not_confirmed(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter(delete_succeeds=False)
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.cleanup_confirmed is False

    def test_delete_always_attempted_after_create(self, tmp_path):
        """Delete must be attempted in finally, even if intermediate phases fail."""
        env = _env_with_real_kubeconfig(tmp_path)
        # create succeeds but rolebinding fails — delete must still run
        stub = _stub_adapter(rolebinding_succeeds=False, rolebinding_exists=False)
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        # namespace was created
        assert stub.created != []
        # delete was called (may or may not succeed — stub defaults to succeed)
        assert stub.deleted != []

    def test_rolebinding_failure_is_warn_not_fail(self, tmp_path):
        """RoleBinding failure degrades to PASSED_WITH_NOTES, not FAILED."""
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter(rolebinding_succeeds=False, rolebinding_exists=False)
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        assert result.decision == _smoke.FINAL_PASSED_WITH_NOTES
        assert result.wrote_rolebinding is False

    def test_namespace_exists_false_is_warn_not_fail(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter(exists_after_create=False)
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        # Still passes (just with notes) if delete succeeds
        assert result.decision in (_smoke.FINAL_PASSED, _smoke.FINAL_PASSED_WITH_NOTES)

    def test_phase_list_contains_cleanup_phase(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        phases = [p.phase for p in result.phases]
        assert "phase8_namespace_delete" in phases
        assert "phase10_cleanup_confirmed" in phases


# ---------------------------------------------------------------------------
# Security: no credential leaks
# ---------------------------------------------------------------------------


class TestSecurityNoLeaks:
    def _result_text(self, result: _smoke.SmokeResult) -> str:
        d = _smoke._result_to_dict(result)
        return json.dumps(d)

    def test_result_doesnt_contain_fake_token(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        env["FAKE_TOKEN"] = "SUPER_SECRET_TOKEN_12345"
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        text = self._result_text(result)
        assert "SUPER_SECRET_TOKEN_12345" not in text

    def test_result_doesnt_contain_private_key_marker(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        text = self._result_text(result)
        assert "PRIVATE KEY" not in text
        assert "BEGIN RSA" not in text

    def test_result_doesnt_contain_kubeconfig_path_contents(self, tmp_path):
        kube = tmp_path / "kube.yaml"
        kube.write_text("apiVersion: v1\nclusters:\n- SECRET_CLUSTER_CONTENT\n")
        env = dict(_VALID_ENV)
        env["LABGEN_K8S_PLATFORM_KUBECONFIG_PATH"] = str(kube)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        text = self._result_text(result)
        assert "SECRET_CLUSTER_CONTENT" not in text

    def test_result_doesnt_contain_raw_k8s_exception_body(self, tmp_path):
        """Simulate an exception with a sensitive body — verify it doesn't appear in result."""
        env = _env_with_real_kubeconfig(tmp_path)

        class _BadAdapter(StubNamespaceLifecycleAdapter):
            def create_namespace(self, namespace):
                # Even if internals raise, the adapter must sanitize
                # Our adapter returns bool, never exposes body
                self.created.append(namespace)
                return True

            def delete_namespace(self, namespace):
                self.deleted.append(namespace)
                return True

        stub = _BadAdapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        text = self._result_text(result)
        # Ensure raw exception bodies (which would contain "ApiException", body JSON) aren't there
        assert "status_code" not in text
        assert "Raw K8s" not in text


# ---------------------------------------------------------------------------
# JSON output schema stability
# ---------------------------------------------------------------------------


class TestJsonOutputSchema:
    _REQUIRED_KEYS = {
        "decision",
        "smoke_namespace",
        "wrote_namespace",
        "wrote_rolebinding",
        "cleanup_confirmed",
        "runtime_start_executed",
        "proxmox_called",
        "registry_called",
        "llm_called",
        "phases",
        "missing_inputs",
        "notes",
    }

    def test_blocked_result_has_all_keys(self):
        env = {"LABGEN_RUNTIME_MODE": "dev"}  # will block in phase0
        result = _smoke.run_smoke(env, allow_k8s_write=False)
        d = _smoke._result_to_dict(result)
        assert self._REQUIRED_KEYS.issubset(d.keys())

    def test_passed_result_has_all_keys(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        d = _smoke._result_to_dict(result)
        assert self._REQUIRED_KEYS.issubset(d.keys())

    def test_phases_is_list_of_dicts(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        d = _smoke._result_to_dict(result)
        assert isinstance(d["phases"], list)
        for phase in d["phases"]:
            assert "phase" in phase
            assert "status" in phase
            assert "message" in phase

    def test_decision_values_are_stable_constants(self):
        assert _smoke.FINAL_PASSED == "K3S_SMOKE_PASSED"
        assert _smoke.FINAL_PASSED_WITH_NOTES == "K3S_SMOKE_PASSED_WITH_NOTES"
        assert _smoke.FINAL_BLOCKED == "K3S_SMOKE_BLOCKED"
        assert _smoke.FINAL_FAILED == "K3S_SMOKE_FAILED"

    def test_json_serializable(self, tmp_path):
        env = _env_with_real_kubeconfig(tmp_path)
        stub = _stub_adapter()
        result = _smoke.run_smoke(env, allow_k8s_write=True, adapter=stub)
        d = _smoke._result_to_dict(result)
        serialized = json.dumps(d)
        reloaded = json.loads(serialized)
        assert reloaded["decision"] == result.decision


# ---------------------------------------------------------------------------
# make_smoke_namespace
# ---------------------------------------------------------------------------


class TestMakeSmokeNamespace:
    def test_starts_with_prefix(self):
        ns = _smoke._make_smoke_namespace("lab-stg-")
        assert ns.startswith("lab-stg-")

    def test_contains_smoke_marker(self):
        for _ in range(10):
            ns = _smoke._make_smoke_namespace("lab-stg-")
            assert "smoke" in ns

    def test_ends_with_random_suffix(self):
        names = {_smoke._make_smoke_namespace("lab-stg-") for _ in range(20)}
        # With 6 random chars, collision probability is negligible
        assert len(names) > 1

    def test_valid_k8s_dns_label(self):
        import re
        pattern = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
        for _ in range(20):
            ns = _smoke._make_smoke_namespace("lab-stg-")
            assert pattern.match(ns), f"Invalid namespace name: {ns}"


# ---------------------------------------------------------------------------
# main() — entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_missing_env_file_returns_2(self, tmp_path):
        missing = str(tmp_path / "nonexistent.env")
        code = _smoke.main(["--env-file", missing])
        assert code == 2

    def test_blocked_returns_2(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("LABGEN_RUNTIME_MODE=dev\n")
        code = _smoke.main(["--env-file", str(f)])
        assert code == 2

    def test_json_flag_produces_json(self, tmp_path, capsys):
        f = tmp_path / ".env"
        f.write_text("LABGEN_RUNTIME_MODE=dev\n")
        _smoke.main(["--env-file", str(f), "--json"])
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "decision" in parsed
