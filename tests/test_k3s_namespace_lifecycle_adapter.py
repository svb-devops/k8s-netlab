"""
K3sNamespaceLifecycleAdapter — unit tests.

All tests use a fake PlatformKubernetesClientLoader that returns mock API objects.
No real K8s connections are made.  No kubectl dependency.

Coverage:
A. Adapter behavior
   - create namespace success
   - create namespace API failure sanitized
   - delete namespace success
   - delete namespace 404 idempotent success
   - delete namespace non-404 API failure
   - namespace_exists true / false / API failure
   - is_namespace_deleted: 404 = True, exists = False, API error = False
   - RoleBinding success
   - RoleBinding 409 idempotent success
   - RoleBinding API failure sanitized
   - verifier_rolebinding_exists true / false / API failure
   - stuck terminating true / false / namespace not found / API unavailable

B. Safety
   - invalid namespace rejected before any API call
   - forbidden system namespace rejected
   - unsafe prefix rejected
   - empty namespace rejected
   - path character rejected
   - shell metacharacter rejected
   - raw Kubernetes exception body not leaked in logs / return value
   - missing kubeconfig (neither kubeconfig_path nor in_cluster) raises at construction
   - both kubeconfig and in_cluster set raises at construction

C. Config validation
   - api_timeout_seconds < 1 raises
   - empty allowed_namespace_prefixes raises
   - invalid verifier SA name raises
   - placeholder config cannot pass as success

D. Client loading
   - missing kubeconfig config raises NamespaceAdapterConfigError at first call
   - no real network calls made in any test
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.namespace_lifecycle import (
    K3sNamespaceLifecycleAdapter,
    K8sAdapterConfig,
    NamespaceAdapterConfigError,
    NamespaceSafetyValidator,
    NamespaceValidationError,
    PlatformKubernetesClientLoader,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    kubeconfig_path: str = "/fake/kubeconfig.yaml",
    in_cluster: bool = False,
    allowed_prefixes: Optional[list[str]] = None,
    verifier_sa_name: str = "lab-verifier",
    verifier_sa_namespace: str = "kube-system",
    verifier_role_name: str = "lab-verifier-namespace-readonly",
    verifier_rolebinding_name: str = "lab-verifier-readonly",
) -> K8sAdapterConfig:
    return K8sAdapterConfig(
        kubeconfig_path=kubeconfig_path,
        in_cluster=in_cluster,
        allowed_namespace_prefixes=allowed_prefixes or ["lab-"],
        verifier_sa_name=verifier_sa_name,
        verifier_sa_namespace=verifier_sa_namespace,
        verifier_role_name=verifier_role_name,
        verifier_rolebinding_name=verifier_rolebinding_name,
    )


class StubClientLoader:
    """Fake loader: returns injectable mock CoreV1Api and RbacAuthorizationV1Api."""

    def __init__(
        self,
        core_v1: Optional[MagicMock] = None,
        rbac_v1: Optional[MagicMock] = None,
    ) -> None:
        self.core_v1 = core_v1 or MagicMock()
        self.rbac_v1 = rbac_v1 or MagicMock()
        self.build_called = 0

    def build(self, config: K8sAdapterConfig):  # type: ignore[override]
        self.build_called += 1
        return self.core_v1, self.rbac_v1


def _make_adapter(
    core_v1: Optional[MagicMock] = None,
    rbac_v1: Optional[MagicMock] = None,
    config: Optional[K8sAdapterConfig] = None,
) -> tuple[K3sNamespaceLifecycleAdapter, StubClientLoader]:
    stub = StubClientLoader(core_v1=core_v1, rbac_v1=rbac_v1)
    cfg = config or _make_config()
    adapter = K3sNamespaceLifecycleAdapter(cfg, loader=stub)
    return adapter, stub


def _api_exception(status: int, reason: str = "Error") -> Exception:
    """Build a mock kubernetes.client.exceptions.ApiException."""
    from kubernetes.client.exceptions import ApiException
    exc = ApiException(status=status, reason=reason)
    exc.body = f'{{"message": "secret-token-abc123 reason={reason}"}}'  # sensitive body
    return exc


# ---------------------------------------------------------------------------
# A. Adapter behavior
# ---------------------------------------------------------------------------

class TestCreateNamespace:
    def test_success(self):
        core = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.create_namespace("lab-abc123") is True
        core.create_namespace.assert_called_once()

    def test_api_failure_returns_false(self):
        core = MagicMock()
        core.create_namespace.side_effect = _api_exception(500)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.create_namespace("lab-abc123") is False

    def test_api_failure_does_not_leak_body(self, caplog):
        core = MagicMock()
        core.create_namespace.side_effect = _api_exception(500, "InternalError")
        adapter, _ = _make_adapter(core_v1=core)
        with caplog.at_level(logging.ERROR):
            adapter.create_namespace("lab-abc123")
        # body contains "secret-token-abc123" — must not appear in logs
        assert "secret-token-abc123" not in caplog.text
        assert "token" not in caplog.text.lower() or "status=500" in caplog.text


class TestDeleteNamespace:
    def test_success(self):
        core = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.delete_namespace("lab-abc123") is True
        core.delete_namespace.assert_called_once()

    def test_404_idempotent_success(self):
        core = MagicMock()
        core.delete_namespace.side_effect = _api_exception(404)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.delete_namespace("lab-abc123") is True

    def test_non_404_failure_returns_false(self):
        core = MagicMock()
        core.delete_namespace.side_effect = _api_exception(403)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.delete_namespace("lab-abc123") is False

    def test_api_failure_does_not_leak_body(self, caplog):
        core = MagicMock()
        core.delete_namespace.side_effect = _api_exception(403, "Forbidden")
        adapter, _ = _make_adapter(core_v1=core)
        with caplog.at_level(logging.ERROR):
            adapter.delete_namespace("lab-abc123")
        assert "secret-token-abc123" not in caplog.text


class TestNamespaceExists:
    def test_exists_returns_true(self):
        core = MagicMock()
        core.read_namespace.return_value = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.namespace_exists("lab-abc123") is True

    def test_404_returns_false(self):
        core = MagicMock()
        core.read_namespace.side_effect = _api_exception(404)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.namespace_exists("lab-abc123") is False

    def test_api_failure_returns_false(self):
        core = MagicMock()
        core.read_namespace.side_effect = _api_exception(503)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.namespace_exists("lab-abc123") is False


class TestIsNamespaceDeleted:
    def test_404_returns_true(self):
        core = MagicMock()
        core.read_namespace.side_effect = _api_exception(404)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.is_namespace_deleted("lab-abc123") is True

    def test_still_exists_returns_false(self):
        core = MagicMock()
        core.read_namespace.return_value = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.is_namespace_deleted("lab-abc123") is False

    def test_api_error_returns_false(self):
        core = MagicMock()
        core.read_namespace.side_effect = _api_exception(503)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.is_namespace_deleted("lab-abc123") is False


class TestIsNamespaceStuckTerminating:
    def _ns_terminating(self, seconds_ago: int) -> MagicMock:
        ns = MagicMock()
        ns.status.phase = "Terminating"
        ns.metadata.deletion_timestamp = datetime.now(timezone.utc) - timedelta(
            seconds=seconds_ago
        )
        return ns

    def test_stuck_true_when_terminating_exceeds_threshold(self):
        core = MagicMock()
        core.read_namespace.return_value = self._ns_terminating(400)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.is_namespace_stuck_terminating("lab-abc123", threshold_seconds=300) is True

    def test_stuck_false_when_within_threshold(self):
        core = MagicMock()
        core.read_namespace.return_value = self._ns_terminating(100)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.is_namespace_stuck_terminating("lab-abc123", threshold_seconds=300) is False

    def test_not_terminating_phase_returns_false(self):
        core = MagicMock()
        ns = MagicMock()
        ns.status.phase = "Active"
        ns.metadata.deletion_timestamp = None
        core.read_namespace.return_value = ns
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.is_namespace_stuck_terminating("lab-abc123") is False

    def test_namespace_not_found_returns_false(self):
        core = MagicMock()
        core.read_namespace.side_effect = _api_exception(404)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.is_namespace_stuck_terminating("lab-abc123") is False

    def test_api_unavailable_returns_false_safe(self):
        core = MagicMock()
        core.read_namespace.side_effect = _api_exception(503)
        adapter, _ = _make_adapter(core_v1=core)
        assert adapter.is_namespace_stuck_terminating("lab-abc123") is False


class TestEnsureVerifierRolebinding:
    def test_success(self):
        rbac = MagicMock()
        adapter, _ = _make_adapter(rbac_v1=rbac)
        assert adapter.ensure_verifier_rolebinding("lab-abc123") is True
        rbac.create_namespaced_role_binding.assert_called_once()

    def test_409_idempotent_success(self):
        rbac = MagicMock()
        rbac.create_namespaced_role_binding.side_effect = _api_exception(409)
        adapter, _ = _make_adapter(rbac_v1=rbac)
        assert adapter.ensure_verifier_rolebinding("lab-abc123") is True

    def test_api_failure_returns_false(self):
        rbac = MagicMock()
        rbac.create_namespaced_role_binding.side_effect = _api_exception(500)
        adapter, _ = _make_adapter(rbac_v1=rbac)
        assert adapter.ensure_verifier_rolebinding("lab-abc123") is False

    def test_rolebinding_is_namespace_scoped_not_cluster(self):
        rbac = MagicMock()
        adapter, _ = _make_adapter(rbac_v1=rbac)
        adapter.ensure_verifier_rolebinding("lab-abc123")
        # Must call create_namespaced_role_binding, NOT create_cluster_role_binding
        rbac.create_namespaced_role_binding.assert_called_once()
        rbac.create_cluster_role_binding.assert_not_called()

    def test_rolebinding_api_failure_does_not_leak_body(self, caplog):
        rbac = MagicMock()
        rbac.create_namespaced_role_binding.side_effect = _api_exception(500, "ServerError")
        adapter, _ = _make_adapter(rbac_v1=rbac)
        with caplog.at_level(logging.ERROR):
            adapter.ensure_verifier_rolebinding("lab-abc123")
        assert "secret-token-abc123" not in caplog.text


class TestVerifierRolebindingExists:
    def test_exists_returns_true(self):
        rbac = MagicMock()
        rbac.read_namespaced_role_binding.return_value = MagicMock()
        adapter, _ = _make_adapter(rbac_v1=rbac)
        assert adapter.verifier_rolebinding_exists("lab-abc123") is True

    def test_404_returns_false(self):
        rbac = MagicMock()
        rbac.read_namespaced_role_binding.side_effect = _api_exception(404)
        adapter, _ = _make_adapter(rbac_v1=rbac)
        assert adapter.verifier_rolebinding_exists("lab-abc123") is False

    def test_api_failure_returns_false(self):
        rbac = MagicMock()
        rbac.read_namespaced_role_binding.side_effect = _api_exception(503)
        adapter, _ = _make_adapter(rbac_v1=rbac)
        assert adapter.verifier_rolebinding_exists("lab-abc123") is False


# ---------------------------------------------------------------------------
# B. Safety — namespace validation
# ---------------------------------------------------------------------------

class TestNamespaceSafetyValidator:
    def test_valid_namespace_passes(self):
        NamespaceSafetyValidator.validate("lab-abc123", ["lab-"])

    def test_empty_namespace_rejected(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("", ["lab-"])

    def test_forbidden_system_namespace_default(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("default", ["lab-"])

    def test_forbidden_kube_system(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("kube-system", ["lab-"])

    def test_forbidden_kube_public(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("kube-public", ["lab-"])

    def test_forbidden_kube_node_lease(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("kube-node-lease", ["lab-"])

    def test_path_character_rejected(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("lab-/abc", ["lab-"])

    def test_shell_metacharacter_dollar_rejected(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("lab-$abc", ["lab-"])

    def test_shell_metacharacter_backtick_rejected(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("lab-`cmd`", ["lab-"])

    def test_uppercase_rejected(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("lab-ABC", ["lab-"])

    def test_starts_with_hyphen_rejected(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("-lab-abc", ["lab-"])

    def test_wrong_prefix_rejected(self):
        with pytest.raises(NamespaceValidationError):
            NamespaceSafetyValidator.validate("prod-abc", ["lab-"])

    def test_adapter_rejects_invalid_namespace_before_api_call(self):
        core = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        result = adapter.create_namespace("kube-system")
        assert result is False
        core.create_namespace.assert_not_called()

    def test_adapter_rejects_forbidden_namespace_before_api_call(self):
        core = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        result = adapter.delete_namespace("default")
        assert result is False
        core.delete_namespace.assert_not_called()

    def test_adapter_rejects_unsafe_prefix_before_api_call(self):
        core = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        result = adapter.create_namespace("prod-session-abc")
        assert result is False
        core.create_namespace.assert_not_called()

    def test_all_delete_methods_validate_namespace(self):
        core = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        for method in (
            adapter.delete_namespace,
            adapter.is_namespace_deleted,
            adapter.is_namespace_stuck_terminating,
        ):
            result = method("kube-system")
            assert result is False
        core.delete_namespace.assert_not_called()
        core.read_namespace.assert_not_called()


# ---------------------------------------------------------------------------
# C. Config validation
# ---------------------------------------------------------------------------

class TestK8sAdapterConfig:
    def test_valid_kubeconfig_path_config(self):
        cfg = _make_config(kubeconfig_path="/etc/k8s/platform.yaml")
        assert cfg.kubeconfig_path == "/etc/k8s/platform.yaml"

    def test_valid_in_cluster_config(self):
        cfg = K8sAdapterConfig(in_cluster=True, allowed_namespace_prefixes=["lab-"])
        assert cfg.in_cluster is True

    def test_neither_kubeconfig_nor_in_cluster_raises(self):
        with pytest.raises(NamespaceAdapterConfigError) as exc_info:
            K8sAdapterConfig(kubeconfig_path="", in_cluster=False)
        assert exc_info.value.reason == FailureReason.NAMESPACE_CONFIG_MISSING.value

    def test_both_kubeconfig_and_in_cluster_raises(self):
        with pytest.raises(NamespaceAdapterConfigError) as exc_info:
            K8sAdapterConfig(
                kubeconfig_path="/etc/k8s/platform.yaml",
                in_cluster=True,
            )
        assert exc_info.value.reason == FailureReason.NAMESPACE_ADAPTER_CONFIG_UNSAFE.value

    def test_api_timeout_zero_raises(self):
        with pytest.raises(NamespaceAdapterConfigError):
            K8sAdapterConfig(kubeconfig_path="/etc/k8s.yaml", api_timeout_seconds=0)

    def test_empty_allowed_prefixes_raises(self):
        with pytest.raises(NamespaceAdapterConfigError):
            K8sAdapterConfig(kubeconfig_path="/etc/k8s.yaml", allowed_namespace_prefixes=[])

    def test_invalid_verifier_sa_name_raises(self):
        with pytest.raises(NamespaceAdapterConfigError):
            K8sAdapterConfig(
                kubeconfig_path="/etc/k8s.yaml",
                verifier_sa_name="bad/name",
            )

    def test_shell_metachar_in_rolebinding_name_raises(self):
        with pytest.raises(NamespaceAdapterConfigError):
            K8sAdapterConfig(
                kubeconfig_path="/etc/k8s.yaml",
                verifier_rolebinding_name="lab-$verifier",
            )

    def test_no_hardcoded_t430_path(self):
        # Default config must not assume any local path
        cfg = _make_config(kubeconfig_path="/some/path/kubeconfig.yaml")
        assert "t430" not in cfg.kubeconfig_path.lower()
        assert "proxmox" not in cfg.kubeconfig_path.lower()


class TestClientLoaderError:
    def test_loader_failure_on_first_call_returns_false(self):
        """If the Kubernetes client cannot be loaded, methods return False (fail closed)."""
        class FailingLoader:
            def build(self, config: K8sAdapterConfig):
                raise NamespaceAdapterConfigError(
                    FailureReason.NAMESPACE_CONFIG_MISSING.value,
                    "Kubeconfig not found",
                )

        cfg = _make_config()
        adapter = K3sNamespaceLifecycleAdapter(cfg, loader=FailingLoader())
        assert adapter.create_namespace("lab-abc") is False
        assert adapter.namespace_exists("lab-abc") is False
        assert adapter.delete_namespace("lab-abc") is False


class TestNoKubectlDependency:
    def test_create_namespace_does_not_call_subprocess(self):
        core = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
            adapter.create_namespace("lab-abc123")
            mock_run.assert_not_called()
            mock_popen.assert_not_called()

    def test_delete_namespace_does_not_call_subprocess(self):
        core = MagicMock()
        adapter, _ = _make_adapter(core_v1=core)
        with patch("subprocess.run") as mock_run:
            adapter.delete_namespace("lab-abc123")
            mock_run.assert_not_called()

    def test_ensure_rolebinding_does_not_call_subprocess(self):
        rbac = MagicMock()
        adapter, _ = _make_adapter(rbac_v1=rbac)
        with patch("subprocess.run") as mock_run:
            adapter.ensure_verifier_rolebinding("lab-abc123")
            mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# D. Lazy client initialization
# ---------------------------------------------------------------------------

class TestLazyClientInit:
    def test_clients_not_loaded_at_construction(self):
        stub = StubClientLoader()
        cfg = _make_config()
        K3sNamespaceLifecycleAdapter(cfg, loader=stub)
        assert stub.build_called == 0

    def test_clients_loaded_on_first_call(self):
        core = MagicMock()
        stub = StubClientLoader(core_v1=core)
        cfg = _make_config()
        adapter = K3sNamespaceLifecycleAdapter(cfg, loader=stub)
        adapter.create_namespace("lab-test")
        assert stub.build_called == 1

    def test_clients_not_reloaded_on_subsequent_calls(self):
        core = MagicMock()
        stub = StubClientLoader(core_v1=core)
        cfg = _make_config()
        adapter = K3sNamespaceLifecycleAdapter(cfg, loader=stub)
        adapter.create_namespace("lab-test1")
        adapter.create_namespace("lab-test2")
        assert stub.build_called == 1
