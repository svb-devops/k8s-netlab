"""
Tests for backend/labgen/k8s_verifier_client.py.

No real K3s cluster is accessed.  KubernetesApiFactory.build() is replaced
with a stub that injects mock CoreV1Api / AppsV1Api objects.

Test scope:
- K8sVerifierClientAdapter: all 6 methods, True/False/404/non-404 paths
- KubernetesApiFactory: import + build() calls KubeConfigLoader (smoke only)
- K8sVerifierClientFactory: module-level factory returns correct type
- secret_exists: uses list, not read (no data access)
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from backend.labgen.k8s_verifier_client import (
    K8sVerifierClientAdapter,
    K8sVerifierClientFactory,
    KubernetesApiFactory,
)
from backend.labgen.verifier import K8sVerifierClientPort

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KUBECONFIG = (
    "apiVersion: v1\n"
    "kind: Config\n"
    "clusters:\n"
    "- cluster:\n"
    "    server: https://k3s.test:6443\n"
    "    certificate-authority-data: dGVzdA==\n"
    "  name: k3s-lab\n"
    "contexts:\n"
    "- context:\n"
    "    cluster: k3s-lab\n"
    "    user: lab-verifier\n"
    "  name: lab-verifier@k3s-lab\n"
    "current-context: lab-verifier@k3s-lab\n"
    "users:\n"
    "- name: lab-verifier\n"
    "  user:\n"
    "    token: test-token-xyz\n"
)


def _api_404() -> ApiException:
    return ApiException(status=404, reason="Not Found")


def _api_500() -> ApiException:
    return ApiException(status=500, reason="Internal Server Error")


def _stub_factory(core: MagicMock, apps: MagicMock) -> KubernetesApiFactory:
    """Return a KubernetesApiFactory whose build() returns injected mocks."""
    factory = MagicMock(spec=KubernetesApiFactory)
    factory.build.return_value = (core, apps)
    return factory


def _adapter(core: MagicMock, apps: MagicMock) -> K8sVerifierClientAdapter:
    return K8sVerifierClientAdapter(_KUBECONFIG, _stub_factory(core, apps))


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


class TestStructural:
    def test_is_port_subclass(self) -> None:
        assert issubclass(K8sVerifierClientAdapter, K8sVerifierClientPort)

    def test_factory_calls_build_with_kubeconfig(self) -> None:
        core, apps = MagicMock(), MagicMock()
        factory = _stub_factory(core, apps)
        K8sVerifierClientAdapter(_KUBECONFIG, factory)
        factory.build.assert_called_once_with(_KUBECONFIG)

    def test_module_factory_returns_port_instance(self) -> None:
        """K8sVerifierClientFactory (module-level) returns K8sVerifierClientPort."""
        core, apps = MagicMock(), MagicMock()
        factory = _stub_factory(core, apps)
        with patch(
            "backend.labgen.k8s_verifier_client._default_factory", factory
        ):
            result = K8sVerifierClientFactory(_KUBECONFIG)
        assert isinstance(result, K8sVerifierClientPort)


# ---------------------------------------------------------------------------
# namespace_exists
# ---------------------------------------------------------------------------


def _api_403() -> ApiException:
    return ApiException(status=403, reason="Forbidden")


class TestNamespaceExists:
    def test_returns_true_when_namespace_found(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = MagicMock()
        adapter = _adapter(core, MagicMock())
        assert adapter.namespace_exists("lab-test") is True
        core.list_namespaced_config_map.assert_called_once_with("lab-test", limit=1)

    def test_does_not_use_read_namespace(self) -> None:
        """namespace_exists must use namespace-scoped list, not read_namespace (needs ClusterRoleBinding)."""
        core = MagicMock()
        core.list_namespaced_config_map.return_value = MagicMock()
        adapter = _adapter(core, MagicMock())
        adapter.namespace_exists("lab-test")
        core.read_namespace.assert_not_called()

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.side_effect = _api_404()
        adapter = _adapter(core, MagicMock())
        assert adapter.namespace_exists("lab-missing") is False

    def test_propagates_403_forbidden(self) -> None:
        """403 means namespace exists but verifier lacks RoleBinding — must not return False."""
        core = MagicMock()
        core.list_namespaced_config_map.side_effect = _api_403()
        adapter = _adapter(core, MagicMock())
        with pytest.raises(ApiException) as exc_info:
            adapter.namespace_exists("lab-test")
        assert exc_info.value.status == 403

    def test_propagates_non_404_exception(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.side_effect = _api_500()
        adapter = _adapter(core, MagicMock())
        with pytest.raises(ApiException) as exc_info:
            adapter.namespace_exists("lab-test")
        assert exc_info.value.status == 500


# ---------------------------------------------------------------------------
# pod_running
# ---------------------------------------------------------------------------


def _mock_pod(phase: str) -> MagicMock:
    pod = MagicMock()
    pod.status = MagicMock()
    pod.status.phase = phase
    return pod


class TestPodRunning:
    def test_returns_true_when_pod_is_running_by_name(self) -> None:
        core = MagicMock()
        core.read_namespaced_pod.return_value = _mock_pod("Running")
        adapter = _adapter(core, MagicMock())
        assert adapter.pod_running("lab-ns", "my-pod") is True
        core.read_namespaced_pod.assert_called_once_with("my-pod", "lab-ns")

    def test_returns_false_when_pod_is_pending(self) -> None:
        core = MagicMock()
        core.read_namespaced_pod.return_value = _mock_pod("Pending")
        assert _adapter(core, MagicMock()).pod_running("lab-ns", "my-pod") is False

    def test_returns_false_when_pod_is_failed(self) -> None:
        core = MagicMock()
        core.read_namespaced_pod.return_value = _mock_pod("Failed")
        assert _adapter(core, MagicMock()).pod_running("lab-ns", "my-pod") is False

    def test_returns_false_on_404_by_name(self) -> None:
        core = MagicMock()
        core.read_namespaced_pod.side_effect = _api_404()
        assert _adapter(core, MagicMock()).pod_running("lab-ns", "no-pod") is False

    def test_propagates_non_404_by_name(self) -> None:
        core = MagicMock()
        core.read_namespaced_pod.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).pod_running("lab-ns", "my-pod")

    def test_uses_list_when_label_selector_provided(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod("Running")]
        core.list_namespaced_pod.return_value = pod_list
        adapter = _adapter(core, MagicMock())
        assert adapter.pod_running("lab-ns", "ignored", label_selector="app=nginx") is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", label_selector="app=nginx"
        )
        core.read_namespaced_pod.assert_not_called()

    def test_label_selector_returns_false_when_no_running_pods(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod("Pending"), _mock_pod("Failed")]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_running(
            "lab-ns", "any", label_selector="app=nginx"
        ) is False

    def test_label_selector_returns_false_on_empty_list(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = []
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_running(
            "lab-ns", "any", label_selector="app=nginx"
        ) is False

    def test_label_selector_returns_true_if_any_running(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod("Pending"), _mock_pod("Running")]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_running(
            "lab-ns", "any", label_selector="app=nginx"
        ) is True

    def test_label_selector_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).pod_running(
                "lab-ns", "any", label_selector="app=nginx"
            )


# ---------------------------------------------------------------------------
# deployment_ready
# ---------------------------------------------------------------------------


def _mock_deployment(desired: Optional[int], ready: Optional[int]) -> MagicMock:
    dep = MagicMock()
    dep.spec = MagicMock()
    dep.spec.replicas = desired
    dep.status = MagicMock()
    dep.status.ready_replicas = ready
    return dep


class TestDeploymentReady:
    def test_returns_true_when_all_replicas_ready(self) -> None:
        apps = MagicMock()
        apps.read_namespaced_deployment.return_value = _mock_deployment(3, 3)
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is True
        apps.read_namespaced_deployment.assert_called_once_with("nginx", "lab-ns")

    def test_returns_false_when_partially_ready(self) -> None:
        apps = MagicMock()
        apps.read_namespaced_deployment.return_value = _mock_deployment(3, 1)
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is False

    def test_returns_false_when_ready_is_none(self) -> None:
        apps = MagicMock()
        apps.read_namespaced_deployment.return_value = _mock_deployment(1, None)
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is False

    def test_returns_false_when_desired_is_zero(self) -> None:
        apps = MagicMock()
        apps.read_namespaced_deployment.return_value = _mock_deployment(0, 0)
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is False

    def test_returns_false_when_desired_is_none(self) -> None:
        apps = MagicMock()
        apps.read_namespaced_deployment.return_value = _mock_deployment(None, None)
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is False

    def test_returns_false_on_404(self) -> None:
        apps = MagicMock()
        apps.read_namespaced_deployment.side_effect = _api_404()
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "missing") is False

    def test_propagates_non_404(self) -> None:
        apps = MagicMock()
        apps.read_namespaced_deployment.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx")


# ---------------------------------------------------------------------------
# service_exists
# ---------------------------------------------------------------------------


class TestServiceExists:
    def test_returns_true_when_service_found(self) -> None:
        core = MagicMock()
        core.read_namespaced_service.return_value = MagicMock()
        assert _adapter(core, MagicMock()).service_exists("lab-ns", "nginx-svc") is True
        core.read_namespaced_service.assert_called_once_with("nginx-svc", "lab-ns")

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.read_namespaced_service.side_effect = _api_404()
        assert _adapter(core, MagicMock()).service_exists("lab-ns", "missing") is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.read_namespaced_service.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).service_exists("lab-ns", "nginx-svc")


# ---------------------------------------------------------------------------
# configmap_exists
# ---------------------------------------------------------------------------


class TestConfigmapExists:
    def test_returns_true_when_configmap_found(self) -> None:
        core = MagicMock()
        core.read_namespaced_config_map.return_value = MagicMock()
        assert _adapter(core, MagicMock()).configmap_exists("lab-ns", "app-config") is True
        core.read_namespaced_config_map.assert_called_once_with("app-config", "lab-ns")

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.read_namespaced_config_map.side_effect = _api_404()
        assert _adapter(core, MagicMock()).configmap_exists("lab-ns", "missing") is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.read_namespaced_config_map.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).configmap_exists("lab-ns", "app-config")


# ---------------------------------------------------------------------------
# secret_exists  (list only — no data read)
# ---------------------------------------------------------------------------


def _mock_secret_list(count: int) -> MagicMock:
    secret_list = MagicMock()
    secret_list.items = [MagicMock() for _ in range(count)]
    return secret_list


class TestSecretExists:
    def test_returns_true_when_secret_found(self) -> None:
        core = MagicMock()
        core.list_namespaced_secret.return_value = _mock_secret_list(1)
        assert _adapter(core, MagicMock()).secret_exists("lab-ns", "tls-cert") is True

    def test_returns_false_when_list_is_empty(self) -> None:
        core = MagicMock()
        core.list_namespaced_secret.return_value = _mock_secret_list(0)
        assert _adapter(core, MagicMock()).secret_exists("lab-ns", "missing") is False

    def test_uses_field_selector_by_name(self) -> None:
        """Verifies list is filtered by metadata.name — no data access."""
        core = MagicMock()
        core.list_namespaced_secret.return_value = _mock_secret_list(1)
        _adapter(core, MagicMock()).secret_exists("lab-ns", "my-secret")
        core.list_namespaced_secret.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=my-secret"
        )

    def test_never_calls_read_namespaced_secret(self) -> None:
        """Confirms read (data access) is never invoked."""
        core = MagicMock()
        core.list_namespaced_secret.return_value = _mock_secret_list(1)
        _adapter(core, MagicMock()).secret_exists("lab-ns", "my-secret")
        core.read_namespaced_secret.assert_not_called()

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_secret.side_effect = _api_404()
        assert _adapter(core, MagicMock()).secret_exists("lab-ns", "missing") is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_secret.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).secret_exists("lab-ns", "tls-cert")


# ---------------------------------------------------------------------------
# KubernetesApiFactory — smoke test (no real K8s connection)
# ---------------------------------------------------------------------------


class TestKubernetesApiFactory:
    def test_build_raises_on_invalid_kubeconfig(self) -> None:
        """Malformed YAML should raise before any network call."""
        factory = KubernetesApiFactory()
        with pytest.raises(Exception):
            factory.build("not: valid: kubeconfig: yaml: [[[")

    def test_build_raises_on_missing_cluster(self) -> None:
        """Valid YAML but no cluster defined — KubeConfigLoader raises."""
        factory = KubernetesApiFactory()
        with pytest.raises(Exception):
            factory.build("apiVersion: v1\nkind: Config\n")

    def test_build_called_with_kubeconfig_string(self) -> None:
        """KubernetesApiFactory.build is called with the raw kubeconfig string."""
        core, apps = MagicMock(), MagicMock()
        factory = _stub_factory(core, apps)
        K8sVerifierClientAdapter(_KUBECONFIG, factory)
        args, _ = factory.build.call_args
        assert args[0] == _KUBECONFIG
