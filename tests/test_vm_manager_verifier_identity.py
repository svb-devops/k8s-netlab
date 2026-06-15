"""Tests for verifier identity initialization — AgentVMCommandExecutor,
VerifierIdentityManager, and initialize_verifier_for_vm."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.static

from backend.labgen.models import VerifierCredentialMetadata
from backend.labgen.verifier_credentials import (
    CommandResult,
    StubVMCommandExecutor,
    VerifierCredentialStore,
    VerifierIdentityManager,
    VMCommandExecutorPort,
    _CLUSTER_ROLE_MANIFEST,
    _SA_MANIFEST,
    _build_kubeconfig,
    _kubectl_apply_cmd,
)
from backend.vm_manager import AgentVMCommandExecutor, initialize_verifier_for_vm


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

# Use non-IP hostnames to avoid pre-commit IP detection hook
_SERVER = "https://k3s-test.lab.local:6443"
_CA = "FAKECADATABASE64=="
_TOKEN = "eyJhbGciOiJSUzI1NiJ9.test.token"


class _ScriptedExecutor(VMCommandExecutorPort):
    """Returns a fixed sequence of CommandResults, one per call.  Tests only."""

    def __init__(self, responses: list[CommandResult]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, list[str]]] = []

    def execute(self, vm_id: str, command: list[str]) -> CommandResult:
        self.calls.append((vm_id, list(command)))
        if self._index >= len(self._responses):
            raise RuntimeError(
                f"Unexpected call #{self._index} for command: {command[0]!r}"
            )
        result = self._responses[self._index]
        self._index += 1
        return result


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(exit_code=0, stdout=stdout, stderr="")


def _fail(stderr: str = "error") -> CommandResult:
    return CommandResult(exit_code=1, stdout="", stderr=stderr)


def _success_responses() -> list[CommandResult]:
    """Five responses covering the full ensure_verifier_identity call sequence."""
    return [
        _ok("serviceaccount/lab-verifier configured"),     # SA apply
        _ok("clusterrole.rbac.../readonly configured"),     # ClusterRole apply
        _ok(_SERVER),                                       # K3s server URL
        _ok(_CA),                                           # CA data
        _ok(_TOKEN),                                        # SA token
    ]


def _make_metadata(vm_id: str = "501") -> VerifierCredentialMetadata:
    now = datetime.now(tz=timezone.utc)
    return VerifierCredentialMetadata(
        vm_id=vm_id,
        created_at=now,
        expires_at=now,
        k3s_endpoint=_SERVER,
    )


@pytest.fixture()
def store(tmp_path: Path) -> VerifierCredentialStore:
    return VerifierCredentialStore(base_dir=tmp_path / "creds")


def _mgr(store: VerifierCredentialStore, executor: VMCommandExecutorPort) -> VerifierIdentityManager:
    return VerifierIdentityManager(store=store, executor=executor)


# ---------------------------------------------------------------------------
# _kubectl_apply_cmd structure
# ---------------------------------------------------------------------------


class TestKubectlApplyCmd:
    def test_uses_python3(self):
        cmd = _kubectl_apply_cmd(_SA_MANIFEST)
        assert cmd[0] == "python3"

    def test_has_minus_c_flag(self):
        cmd = _kubectl_apply_cmd(_SA_MANIFEST)
        assert cmd[1] == "-c"

    def test_script_contains_kubectl_apply(self):
        cmd = _kubectl_apply_cmd(_SA_MANIFEST)
        assert "kubectl" in cmd[2]
        assert "apply" in cmd[2]

    def test_sa_manifest_embedded_in_script(self):
        cmd = _kubectl_apply_cmd(_SA_MANIFEST)
        assert "lab-verifier" in cmd[2]
        assert "ServiceAccount" in cmd[2]

    def test_clusterrole_manifest_embedded(self):
        cmd = _kubectl_apply_cmd(_CLUSTER_ROLE_MANIFEST)
        assert "lab-verifier-namespace-readonly" in cmd[2]
        assert "ClusterRole" in cmd[2]

    def test_clusterrole_manifest_includes_secrets(self):
        # secret_exists verifier type requires list permission on secrets.
        # This regression test prevents removing secrets from the ClusterRole.
        assert "secrets" in _CLUSTER_ROLE_MANIFEST

    def test_clusterrole_manifest_secrets_no_get_verb(self):
        # Principle of least privilege: secrets rule must not grant get verb.
        # get allows reading .data; list (for existence check) is sufficient.
        lines = _CLUSTER_ROLE_MANIFEST.splitlines()
        in_secrets_rule = False
        for line in lines:
            if "secrets" in line and "resources" in line:
                in_secrets_rule = True
            if in_secrets_rule and "verbs" in line:
                assert "get" not in line, f"secrets rule must not grant get: {line}"
                break

    def test_clusterrole_manifest_includes_deployments(self):
        # deployment_ready verifier requires list permission on apps/deployments.
        assert "deployments" in _CLUSTER_ROLE_MANIFEST

    def test_clusterrole_manifest_deployments_no_get_verb(self):
        # deployment_ready uses list_namespaced_deployment (not get).
        # apps/deployments rule must not grant get — list+watch is sufficient.
        lines = _CLUSTER_ROLE_MANIFEST.splitlines()
        in_apps_rule = False
        for line in lines:
            if "apps" in line and "apiGroups" in line:
                in_apps_rule = True
            if in_apps_rule and "verbs" in line:
                assert "get" not in line, f"apps rule must not grant get: {line}"
                break


# ---------------------------------------------------------------------------
# _build_kubeconfig
# ---------------------------------------------------------------------------


class TestBuildKubeconfig:
    def test_contains_server(self):
        kc = _build_kubeconfig(_SERVER, _CA, _TOKEN)
        assert _SERVER in kc

    def test_contains_ca(self):
        kc = _build_kubeconfig(_SERVER, _CA, _TOKEN)
        assert _CA in kc

    def test_contains_token(self):
        kc = _build_kubeconfig(_SERVER, _CA, _TOKEN)
        assert _TOKEN in kc

    def test_has_clusters_key(self):
        kc = _build_kubeconfig(_SERVER, _CA, _TOKEN)
        assert "clusters:" in kc

    def test_has_users_key(self):
        kc = _build_kubeconfig(_SERVER, _CA, _TOKEN)
        assert "users:" in kc

    def test_has_contexts_key(self):
        kc = _build_kubeconfig(_SERVER, _CA, _TOKEN)
        assert "contexts:" in kc

    def test_lab_verifier_sa_name(self):
        kc = _build_kubeconfig(_SERVER, _CA, _TOKEN)
        assert "lab-verifier" in kc

    def test_rejects_server_with_newline(self):
        with pytest.raises(ValueError, match="server URL"):
            _build_kubeconfig(_SERVER + "\ninjected: evil", _CA, _TOKEN)

    def test_rejects_ca_with_non_base64(self):
        with pytest.raises(ValueError, match="base64"):
            _build_kubeconfig(_SERVER, "not!base64\n", _TOKEN)

    def test_rejects_token_with_newline(self):
        with pytest.raises(ValueError, match="unexpected characters"):
            _build_kubeconfig(_SERVER, _CA, _TOKEN + "\ninjected: evil")


# ---------------------------------------------------------------------------
# VerifierIdentityManager.ensure_verifier_identity
# ---------------------------------------------------------------------------


class TestEnsureVerifierIdentity:
    def test_applies_sa_yaml(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        _mgr(store, scripted).ensure_verifier_identity("501")
        sa_script = scripted.calls[0][1][2]
        assert "ServiceAccount" in sa_script
        assert "lab-verifier" in sa_script

    def test_applies_clusterrole_yaml(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        _mgr(store, scripted).ensure_verifier_identity("501")
        cr_script = scripted.calls[1][1][2]
        assert "ClusterRole" in cr_script
        assert "lab-verifier-namespace-readonly" in cr_script

    def test_no_clusterrolebinding_created(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        _mgr(store, scripted).ensure_verifier_identity("501")
        all_calls_str = " ".join(
            " ".join(str(x) for x in cmd) for _, cmd in scripted.calls
        )
        assert "ClusterRoleBinding" not in all_calls_str
        assert "RoleBinding" not in all_calls_str

    def test_saves_kubeconfig_to_store(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        _mgr(store, scripted).ensure_verifier_identity("501")
        assert store.exists("501")

    def test_kubeconfig_contains_server(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        _mgr(store, scripted).ensure_verifier_identity("501")
        kube, _ = store.load("501")
        assert _SERVER in kube

    def test_kubeconfig_contains_token(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        _mgr(store, scripted).ensure_verifier_identity("501")
        kube, _ = store.load("501")
        assert _TOKEN in kube

    def test_metadata_k3s_endpoint_is_server(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        meta = _mgr(store, scripted).ensure_verifier_identity("501")
        assert meta.k3s_endpoint == _SERVER

    def test_metadata_schema_version(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        meta = _mgr(store, scripted).ensure_verifier_identity("501")
        assert meta.schema_version == "1.0"

    def test_metadata_generation_starts_at_1(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        meta = _mgr(store, scripted).ensure_verifier_identity("501")
        assert meta.credential_generation == 1

    def test_generation_increments_on_second_call(self, store):
        scripted = _ScriptedExecutor(_success_responses() + _success_responses())
        mgr = _mgr(store, scripted)
        mgr.ensure_verifier_identity("501")
        meta2 = mgr.ensure_verifier_identity("501")
        assert meta2.credential_generation == 2

    def test_raises_if_sa_apply_fails(self, store):
        scripted = _ScriptedExecutor([_fail("error applying SA")])
        with pytest.raises(RuntimeError, match="ServiceAccount"):
            _mgr(store, scripted).ensure_verifier_identity("501")

    def test_raises_if_clusterrole_apply_fails(self, store):
        scripted = _ScriptedExecutor([_ok(), _fail("ClusterRole error")])
        with pytest.raises(RuntimeError, match="ClusterRole"):
            _mgr(store, scripted).ensure_verifier_identity("501")

    def test_raises_if_server_empty(self, store):
        # SA + ClusterRole succeed, but server URL returns empty string
        scripted = _ScriptedExecutor([_ok(), _ok(), _ok("")])
        with pytest.raises(RuntimeError, match="server URL"):
            _mgr(store, scripted).ensure_verifier_identity("501")

    def test_raises_if_token_empty(self, store):
        responses = [_ok(), _ok(), _ok(_SERVER), _ok(_CA), _ok("")]
        scripted = _ScriptedExecutor(responses)
        with pytest.raises(RuntimeError, match="token"):
            _mgr(store, scripted).ensure_verifier_identity("501")

    def test_makes_exactly_5_calls(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        _mgr(store, scripted).ensure_verifier_identity("501")
        assert len(scripted.calls) == 5

    def test_all_calls_use_correct_vm_id(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        _mgr(store, scripted).ensure_verifier_identity("501")
        for vm_id, _ in scripted.calls:
            assert vm_id == "501"


# ---------------------------------------------------------------------------
# VerifierIdentityManager.export_verifier_kubeconfig
# ---------------------------------------------------------------------------


class TestExportVerifierKubeconfig:
    def test_returns_saved_kubeconfig(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        mgr = _mgr(store, scripted)
        mgr.ensure_verifier_identity("501")
        kube = mgr.export_verifier_kubeconfig("501")
        assert _SERVER in kube
        assert _TOKEN in kube

    def test_raises_if_no_credentials(self, store):
        mgr = _mgr(store, StubVMCommandExecutor())
        with pytest.raises(FileNotFoundError):
            mgr.export_verifier_kubeconfig("501")

    def test_returns_same_content_on_second_call(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        mgr = _mgr(store, scripted)
        mgr.ensure_verifier_identity("501")
        assert mgr.export_verifier_kubeconfig("501") == mgr.export_verifier_kubeconfig("501")


# ---------------------------------------------------------------------------
# VerifierIdentityManager.run_smoke_test
# ---------------------------------------------------------------------------


class TestRunSmokeTest:
    def test_passes_after_ensure(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        mgr = _mgr(store, scripted)
        mgr.ensure_verifier_identity("501")
        result = mgr.run_smoke_test("501")
        assert result.passed is True

    def test_all_checks_pass_after_ensure(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        mgr = _mgr(store, scripted)
        mgr.ensure_verifier_identity("501")
        result = mgr.run_smoke_test("501")
        assert all(c.passed for c in result.checks)

    def test_fails_if_no_credentials(self, store):
        result = _mgr(store, StubVMCommandExecutor()).run_smoke_test("501")
        assert result.passed is False

    def test_credentials_exist_check_fails_when_missing(self, store):
        result = _mgr(store, StubVMCommandExecutor()).run_smoke_test("501")
        cred_check = next(c for c in result.checks if c.check_name == "credentials_exist")
        assert cred_check.passed is False

    def test_smoke_result_schema_version(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        mgr = _mgr(store, scripted)
        mgr.ensure_verifier_identity("501")
        result = mgr.run_smoke_test("501")
        assert result.schema_version == "1.0"

    def test_fails_if_kubeconfig_missing_token(self, store):
        # Save a kubeconfig without the token field
        broken = "apiVersion: v1\nclusters:\n- cluster:\n    server: x\n  name: k\nusers:\n"
        store.save("501", broken, _make_metadata())
        result = _mgr(store, StubVMCommandExecutor()).run_smoke_test("501")
        assert result.passed is False
        token_check = next(c for c in result.checks if c.check_name == "has_token")
        assert token_check.passed is False

    def test_vm_id_in_smoke_result(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        mgr = _mgr(store, scripted)
        mgr.ensure_verifier_identity("501")
        result = mgr.run_smoke_test("501")
        assert result.vm_id == "501"


# ---------------------------------------------------------------------------
# initialize_verifier_for_vm
# ---------------------------------------------------------------------------


class TestInitializeVerifierForVm:
    def test_returns_success(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        result = initialize_verifier_for_vm(501, store=store, executor=scripted)
        assert result["success"] is True
        assert result["error"] is None

    def test_returns_generation_in_data(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        result = initialize_verifier_for_vm(501, store=store, executor=scripted)
        assert result["data"]["credential_generation"] == 1

    def test_second_call_increments_generation(self, store):
        s1 = _ScriptedExecutor(_success_responses())
        initialize_verifier_for_vm(501, store=store, executor=s1)
        s2 = _ScriptedExecutor(_success_responses())
        result = initialize_verifier_for_vm(501, store=store, executor=s2)
        assert result["data"]["credential_generation"] == 2

    def test_returns_failure_if_ensure_raises(self, store):
        scripted = _ScriptedExecutor([_fail("SA apply error")])
        result = initialize_verifier_for_vm(501, store=store, executor=scripted)
        assert result["success"] is False
        assert result["error"] is not None

    def test_returns_failure_on_smoke_fail(self, store):
        # Save a kubeconfig that fails the smoke test, then call the function
        # We inject a custom executor that succeeds ensure but store has bad data
        scripted = _ScriptedExecutor(_success_responses())
        initialize_verifier_for_vm(501, store=store, executor=scripted)
        # Overwrite store with broken kubeconfig to trigger smoke failure
        broken = "not: valid: kubeconfig\n"
        store.save("501", broken, _make_metadata())
        # run_smoke_test now checks the broken file — but initialize re-runs ensure first
        # so we test smoke failure by using a store that has broken data BEFORE the call
        broken_store = VerifierCredentialStore(base_dir=store._base)
        broken_store.save("501", broken, _make_metadata())
        # Use a scripted executor that returns success for ensure, but then
        # the smoke test runs on the corrupted store data
        # Actually, ensure_verifier_identity overwrites the store, so we need to
        # corrupt it AFTER ensure. Test the smoke-test-fails path via a failing store.
        # Simplest: monkeypatch run_smoke_test to return failure
        from unittest.mock import patch as _patch
        from backend.labgen.verifier_credentials import VerifierSmokeTestResult, SmokeCheckResult
        failing_result = VerifierSmokeTestResult(vm_id="501", passed=False, checks=[
            SmokeCheckResult(check_name="has_token", passed=False)
        ])
        s3 = _ScriptedExecutor(_success_responses())
        store3 = VerifierCredentialStore(base_dir=store._base.parent / "new_creds")
        with _patch.object(VerifierIdentityManager, "run_smoke_test", return_value=failing_result):
            result2 = initialize_verifier_for_vm(501, store=store3, executor=s3)
        assert result2["success"] is False
        assert "smoke_test_failed" in result2["error"]

    def test_invalid_vm_id_raises(self, store):
        with pytest.raises(ValueError):
            initialize_verifier_for_vm(0, store=store, executor=StubVMCommandExecutor())

    def test_kubeconfig_not_in_success_result(self, store):
        scripted = _ScriptedExecutor(_success_responses())
        result = initialize_verifier_for_vm(501, store=store, executor=scripted)
        assert _TOKEN not in str(result)

    def test_kubeconfig_not_in_error_result(self, store):
        scripted = _ScriptedExecutor([_fail()])
        result = initialize_verifier_for_vm(501, store=store, executor=scripted)
        assert _TOKEN not in str(result)


# ---------------------------------------------------------------------------
# AgentVMCommandExecutor (mocked Proxmox)
# ---------------------------------------------------------------------------


class TestAgentVMCommandExecutor:
    def _mock_proxmox(
        self,
        pid: int = 42,
        exitcode: int = 0,
        out_data: str = "hello",
        exited: bool = True,
    ) -> MagicMock:
        mock_proxmox = MagicMock()
        mock_agent = MagicMock()
        mock_proxmox.nodes.return_value.qemu.return_value.agent = mock_agent
        mock_agent.post.return_value = {"pid": pid}
        mock_agent.get.return_value = {
            "exited": exited,
            "exitcode": exitcode,
            "out-data": out_data,
            "err-data": "",
        }
        return mock_proxmox

    def test_calls_agent_post_exec(self):
        mock_prox = self._mock_proxmox()
        with patch("backend.vm_manager.connect_proxmox", return_value=mock_prox):
            with patch("time.sleep"):
                AgentVMCommandExecutor().execute("501", ["kubectl", "version"])
        mock_prox.nodes.return_value.qemu.return_value.agent.post.assert_called_once_with(
            "exec", command=["kubectl", "version"]
        )

    def test_returns_exit_code(self):
        mock_prox = self._mock_proxmox(exitcode=0)
        with patch("backend.vm_manager.connect_proxmox", return_value=mock_prox):
            with patch("time.sleep"):
                result = AgentVMCommandExecutor().execute("501", ["kubectl", "version"])
        assert result.exit_code == 0

    def test_returns_stdout(self):
        mock_prox = self._mock_proxmox(out_data="output text")
        with patch("backend.vm_manager.connect_proxmox", return_value=mock_prox):
            with patch("time.sleep"):
                result = AgentVMCommandExecutor().execute("501", ["kubectl", "version"])
        assert result.stdout == "output text"

    def test_succeeded_true_on_exit_zero(self):
        mock_prox = self._mock_proxmox(exitcode=0)
        with patch("backend.vm_manager.connect_proxmox", return_value=mock_prox):
            with patch("time.sleep"):
                result = AgentVMCommandExecutor().execute("501", ["kubectl", "get", "ns"])
        assert result.succeeded is True

    def test_succeeded_false_on_nonzero(self):
        mock_prox = self._mock_proxmox(exitcode=1)
        with patch("backend.vm_manager.connect_proxmox", return_value=mock_prox):
            with patch("time.sleep"):
                result = AgentVMCommandExecutor().execute("501", ["kubectl", "get", "ns"])
        assert result.succeeded is False

    def test_raises_timeout_when_never_exits(self):
        mock_prox = self._mock_proxmox(exited=False)
        executor = AgentVMCommandExecutor()
        executor._poll_iterations = 2  # limit to 2 iterations for speed
        with patch("backend.vm_manager.connect_proxmox", return_value=mock_prox):
            with patch("time.sleep"):
                with pytest.raises(TimeoutError):
                    executor.execute("501", ["kubectl", "wait", "--timeout=999s"])

    def test_uses_correct_vm_id(self):
        mock_prox = self._mock_proxmox()
        with patch("backend.vm_manager.connect_proxmox", return_value=mock_prox):
            with patch("time.sleep"):
                AgentVMCommandExecutor().execute("501", ["kubectl", "version"])
        mock_prox.nodes.return_value.qemu.assert_called_once_with(501)

    def test_is_vmcommandexecutorport_subtype(self):
        assert issubclass(AgentVMCommandExecutor, VMCommandExecutorPort)

    def test_rejects_non_allowlisted_command(self):
        executor = AgentVMCommandExecutor()
        with pytest.raises(ValueError, match="allowlist"):
            executor.execute("501", ["bash", "-c", "rm -rf /"])

    def test_rejects_alpha_vm_id(self):
        executor = AgentVMCommandExecutor()
        with pytest.raises(ValueError, match="numeric"):
            executor.execute("abc", ["kubectl", "version"])
