"""Tests for backend/labgen/verifier_credentials.py."""

import os
import stat
import yaml
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.static

from backend.labgen.models import VerifierCredentialMetadata
from backend.labgen.verifier_credentials import (
    CommandResult,
    SmokeCheckResult,
    StubVMCommandExecutor,
    VerifierCredentialStore,
    VerifierIdentityManager,
    VerifierSmokeTestResult,
    VMCommandExecutorPort,
    _CLUSTER_ROLE_MANIFEST,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> VerifierCredentialStore:
    return VerifierCredentialStore(base_dir=tmp_path / "creds")


_EXPIRES = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_CREATED = datetime(2026, 6, 8, 0, 0, 0, tzinfo=timezone.utc)
_K3S_ENDPOINT = "https://k3s-test.lab.local:6443"


def _metadata(vm_id: str = "501", generation: int = 1) -> VerifierCredentialMetadata:
    return VerifierCredentialMetadata(
        vm_id=vm_id,
        created_at=_CREATED,
        expires_at=_EXPIRES,
        k3s_endpoint=_K3S_ENDPOINT,
        credential_generation=generation,
    )


_KUBECONFIG = "apiVersion: v1\nclusters: []\nkind: Config\n"


# ---------------------------------------------------------------------------
# VerifierCredentialMetadata (from models.py)
# ---------------------------------------------------------------------------


class TestVerifierCredentialMetadata:
    def test_schema_version_default(self):
        m = _metadata()
        assert m.schema_version == "1.0"

    def test_credential_generation_stored(self):
        m = _metadata(generation=3)
        assert m.credential_generation == 3

    def test_vm_id_stored(self):
        m = _metadata(vm_id="599")
        assert m.vm_id == "599"

    def test_created_at_stored(self):
        m = _metadata()
        assert m.created_at == _CREATED

    def test_round_trip_json(self):
        m = _metadata(vm_id="501", generation=2)
        restored = VerifierCredentialMetadata.model_validate_json(m.model_dump_json())
        assert restored.vm_id == "501"
        assert restored.credential_generation == 2
        assert restored.schema_version == "1.0"

    def test_revoked_at_optional(self):
        m = _metadata()
        assert m.revoked_at is None


# ---------------------------------------------------------------------------
# VerifierCredentialStore — path safety
# ---------------------------------------------------------------------------


class TestVerifierCredentialStorePathSafety:
    def test_rejects_dotdot_vm_id(self, store):
        with pytest.raises(ValueError, match="Invalid vm_id"):
            store.exists("../etc")

    def test_rejects_slash_vm_id(self, store):
        with pytest.raises(ValueError, match="Invalid vm_id"):
            store.exists("/etc/passwd")

    def test_rejects_alpha_vm_id(self, store):
        with pytest.raises(ValueError, match="Invalid vm_id"):
            store.exists("abc")

    def test_accepts_numeric_vm_id(self, store):
        assert store.exists("501") is False  # does not raise

    def test_rejects_dotdot_in_save(self, store):
        with pytest.raises(ValueError, match="Invalid vm_id"):
            store.save("../escape", _KUBECONFIG, _metadata())

    def test_rejects_dotdot_in_delete(self, store):
        with pytest.raises(ValueError, match="Invalid vm_id"):
            store.delete("../escape")

    def test_rejects_dotdot_in_load(self, store):
        with pytest.raises(ValueError, match="Invalid vm_id"):
            store.load("../escape")


# ---------------------------------------------------------------------------
# VerifierCredentialStore — exists / save / load / delete
# ---------------------------------------------------------------------------


class TestVerifierCredentialStore:
    def test_exists_false_initially(self, store):
        assert store.exists("501") is False

    def test_save_creates_files(self, store):
        store.save("501", _KUBECONFIG, _metadata())
        assert store.exists("501") is True

    def test_load_returns_kubeconfig(self, store):
        store.save("501", _KUBECONFIG, _metadata())
        kubeconfig, _ = store.load("501")
        assert kubeconfig == _KUBECONFIG

    def test_load_returns_metadata(self, store):
        meta = _metadata(vm_id="501", generation=2)
        store.save("501", _KUBECONFIG, meta)
        _, loaded = store.load("501")
        assert loaded.vm_id == "501"
        assert loaded.credential_generation == 2
        assert loaded.schema_version == "1.0"

    def test_load_raises_when_missing(self, store):
        with pytest.raises(FileNotFoundError):
            store.load("999")

    def test_delete_removes_files(self, store):
        store.save("501", _KUBECONFIG, _metadata())
        store.delete("501")
        assert store.exists("501") is False

    def test_delete_nonexistent_is_safe(self, store):
        store.delete("999")  # should not raise

    def test_exists_false_if_only_kubeconfig_present(self, store, tmp_path):
        base = tmp_path / "creds" / "501"
        base.mkdir(parents=True)
        (base / "kubeconfig.yaml").write_text(_KUBECONFIG)
        assert store.exists("501") is False

    def test_exists_false_if_only_metadata_present(self, store, tmp_path):
        base = tmp_path / "creds" / "501"
        base.mkdir(parents=True)
        (base / "metadata.json").write_text(_metadata().model_dump_json())
        assert store.exists("501") is False

    def test_vm_dir_permission_700(self, store):
        store.save("501", _KUBECONFIG, _metadata())
        vm_dir = store._vm_dir("501")
        mode = stat.filemode(os.stat(vm_dir).st_mode)
        assert mode == "drwx------"

    def test_kubeconfig_permission_600(self, store):
        store.save("501", _KUBECONFIG, _metadata())
        kube_path = store._kubeconfig_path("501")
        mode = stat.filemode(os.stat(kube_path).st_mode)
        assert mode == "-rw-------"

    def test_metadata_permission_600(self, store):
        store.save("501", _KUBECONFIG, _metadata())
        meta_path = store._metadata_path("501")
        mode = stat.filemode(os.stat(meta_path).st_mode)
        assert mode == "-rw-------"

    def test_kubeconfig_not_stored_under_data(self, store, tmp_path):
        store.save("501", _KUBECONFIG, _metadata())
        data_dir = tmp_path / "data"
        assert not data_dir.exists()

    def test_save_overwrites_existing(self, store):
        store.save("501", _KUBECONFIG, _metadata(generation=1))
        store.save("501", _KUBECONFIG + "# v2\n", _metadata(generation=2))
        kubeconfig, meta = store.load("501")
        assert "# v2" in kubeconfig
        assert meta.credential_generation == 2

    def test_multiple_vms_independent(self, store):
        store.save("501", _KUBECONFIG, _metadata(vm_id="501"))
        store.save("502", _KUBECONFIG + "# vm502\n", _metadata(vm_id="502"))
        store.delete("501")
        assert store.exists("501") is False
        assert store.exists("502") is True


# ---------------------------------------------------------------------------
# CommandResult
# ---------------------------------------------------------------------------


class TestCommandResult:
    def test_succeeded_on_zero_exit(self):
        r = CommandResult(exit_code=0, stdout="ok", stderr="")
        assert r.succeeded is True

    def test_succeeded_false_on_nonzero(self):
        r = CommandResult(exit_code=1, stdout="", stderr="err")
        assert r.succeeded is False


# ---------------------------------------------------------------------------
# StubVMCommandExecutor
# ---------------------------------------------------------------------------


class TestStubVMCommandExecutor:
    def test_returns_configured_exit_code(self):
        stub = StubVMCommandExecutor(exit_code=0, stdout="hi", stderr="")
        result = stub.execute("501", ["kubectl", "version"])
        assert result.exit_code == 0
        assert result.stdout == "hi"

    def test_returns_configured_failure(self):
        stub = StubVMCommandExecutor(exit_code=1, stdout="", stderr="error")
        result = stub.execute("501", ["kubectl", "get", "ns"])
        assert result.succeeded is False
        assert result.stderr == "error"

    def test_records_calls(self):
        stub = StubVMCommandExecutor()
        stub.execute("501", ["kubectl", "version"])
        stub.execute("502", ["kubectl", "get", "ns"])
        assert len(stub.calls) == 2
        assert stub.calls[0] == ("501", ["kubectl", "version"])
        assert stub.calls[1] == ("502", ["kubectl", "get", "ns"])

    def test_call_list_starts_empty(self):
        stub = StubVMCommandExecutor()
        assert stub.calls == []

    def test_command_list_is_copied(self):
        stub = StubVMCommandExecutor()
        cmd = ["kubectl", "version"]
        stub.execute("501", cmd)
        cmd.append("--extra")
        assert stub.calls[0][1] == ["kubectl", "version"]

    def test_is_vmcommandexecutorport_subtype(self):
        assert isinstance(StubVMCommandExecutor(), VMCommandExecutorPort)


# ---------------------------------------------------------------------------
# SmokeCheckResult / VerifierSmokeTestResult
# ---------------------------------------------------------------------------


class TestSmokeResultModels:
    def test_smoke_check_schema_version(self):
        r = SmokeCheckResult(check_name="api_reachable", passed=True)
        assert r.schema_version == "1.0"

    def test_smoke_check_detail_default_empty(self):
        r = SmokeCheckResult(check_name="api_reachable", passed=False)
        assert r.detail == ""

    def test_verifier_smoke_test_schema_version(self):
        r = VerifierSmokeTestResult(vm_id="501", passed=True)
        assert r.schema_version == "1.0"

    def test_verifier_smoke_test_checks_default_empty(self):
        r = VerifierSmokeTestResult(vm_id="501", passed=False)
        assert r.checks == []

    def test_verifier_smoke_test_with_checks(self):
        checks = [
            SmokeCheckResult(check_name="api_reachable", passed=True),
            SmokeCheckResult(check_name="namespace_list", passed=False, detail="timeout"),
        ]
        r = VerifierSmokeTestResult(vm_id="501", passed=False, checks=checks)
        assert len(r.checks) == 2
        assert r.checks[1].detail == "timeout"


# ---------------------------------------------------------------------------
# VerifierIdentityManager wiring
# ---------------------------------------------------------------------------


class TestVerifierIdentityManagerWiring:
    def test_store_and_executor_wired(self, tmp_path):
        store = VerifierCredentialStore(base_dir=tmp_path / "creds")
        executor = StubVMCommandExecutor()
        mgr = VerifierIdentityManager(store=store, executor=executor)
        assert mgr._store is store
        assert mgr._executor is executor


# ---------------------------------------------------------------------------
# ClusterRole RBAC guardrail — prevents get-verb regression
# Verifier uses list+field_selector only; 'get' on any resource is unnecessary
# and violates least-privilege. If these tests fail, the verifier likely
# regressed to using read/get K8s calls.
# ---------------------------------------------------------------------------


def _parse_cluster_role_rules(manifest: str) -> list[dict]:
    doc = yaml.safe_load(manifest)
    return doc.get("rules", [])


class TestClusterRoleManifestGuardrail:
    """Regression guard: _CLUSTER_ROLE_MANIFEST must never grant 'get'."""

    def test_no_get_verb_in_any_rule(self):
        rules = _parse_cluster_role_rules(_CLUSTER_ROLE_MANIFEST)
        for rule in rules:
            assert "get" not in rule.get("verbs", []), (
                f"ClusterRole rule grants 'get' on {rule.get('resources')}: "
                "verifier uses list+field_selector only — 'get' is unnecessary "
                "and violates least-privilege"
            )

    def test_namespaces_not_in_core_rule(self):
        rules = _parse_cluster_role_rules(_CLUSTER_ROLE_MANIFEST)
        core_rules = [r for r in rules if "" in r.get("apiGroups", [])]
        all_core_resources: list[str] = []
        for r in core_rules:
            all_core_resources.extend(r.get("resources", []))
        assert "namespaces" not in all_core_resources, (
            "namespaces is a cluster-scoped resource; verifier does not call "
            "get_namespace or list_namespace — remove from ClusterRole"
        )

    def test_endpoints_has_list_watch_only(self):
        # endpoints is used by service_has_endpoints (K8sVerifierClientAdapter) —
        # must be granted list+watch, same as pods/services/configmaps, never 'get'.
        rules = _parse_cluster_role_rules(_CLUSTER_ROLE_MANIFEST)
        for rule in rules:
            if "endpoints" in rule.get("resources", []):
                verbs = set(rule.get("verbs", []))
                assert verbs == {"list", "watch"}, (
                    f"endpoints must grant exactly list+watch, got {verbs}"
                )
                return
        raise AssertionError("endpoints resource not found in any ClusterRole rule")

    def test_secrets_has_list_watch_only(self):
        rules = _parse_cluster_role_rules(_CLUSTER_ROLE_MANIFEST)
        for rule in rules:
            if "secrets" in rule.get("resources", []):
                verbs = set(rule.get("verbs", []))
                assert "get" not in verbs, "secrets must not grant 'get'"
                assert "list" in verbs, "secrets must grant 'list'"

    def test_deployments_has_list_watch_only(self):
        rules = _parse_cluster_role_rules(_CLUSTER_ROLE_MANIFEST)
        for rule in rules:
            if "deployments" in rule.get("resources", []):
                verbs = set(rule.get("verbs", []))
                assert "get" not in verbs, "deployments must not grant 'get'"
                assert "list" in verbs, "deployments must grant 'list'"

    def test_deployments_in_apps_group(self):
        rules = _parse_cluster_role_rules(_CLUSTER_ROLE_MANIFEST)
        apps_rules = [r for r in rules if "apps" in r.get("apiGroups", [])]
        apps_resources: list[str] = []
        for r in apps_rules:
            apps_resources.extend(r.get("resources", []))
        assert "deployments" in apps_resources, "deployments must be in apps apiGroup"

    def test_pods_services_configmaps_have_list_watch_only(self):
        rules = _parse_cluster_role_rules(_CLUSTER_ROLE_MANIFEST)
        for rule in rules:
            resources = rule.get("resources", [])
            verbs = rule.get("verbs", [])
            for res in ["pods", "services", "configmaps"]:
                if res in resources:
                    assert "get" not in verbs, (
                        f"{res} must not grant 'get' — verifier uses list+field_selector"
                    )
