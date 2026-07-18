"""
Tests for backend/labgen/k8s_verifier_client.py.

No real K3s cluster is accessed.  KubernetesApiFactory.build() is replaced
with a stub that injects mock CoreV1Api / AppsV1Api objects.

Test scope:
- K8sVerifierClientAdapter: all 7 methods, True/False/404/non-404 paths
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

    def test_returns_false_on_403_forbidden(self) -> None:
        """403 means namespace was deleted (namespace-scoped RoleBinding deleted with it).
        Treat as 'namespace not found' — same as 404."""
        core = MagicMock()
        core.list_namespaced_config_map.side_effect = _api_403()
        adapter = _adapter(core, MagicMock())
        assert adapter.namespace_exists("lab-test") is False

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


def _mock_pod_list(*phases: str) -> MagicMock:
    pod_list = MagicMock()
    pod_list.items = [_mock_pod(p) for p in phases]
    return pod_list


class TestPodRunning:
    def test_returns_true_when_pod_is_running_by_name(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Running")
        adapter = _adapter(core, MagicMock())
        assert adapter.pod_running("lab-ns", "my-pod") is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=my-pod"
        )

    def test_does_not_call_read_namespaced_pod(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Running")
        _adapter(core, MagicMock()).pod_running("lab-ns", "my-pod")
        core.read_namespaced_pod.assert_not_called()

    def test_returns_false_when_pod_is_pending(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Pending")
        assert _adapter(core, MagicMock()).pod_running("lab-ns", "my-pod") is False

    def test_returns_false_when_pod_is_failed(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Failed")
        assert _adapter(core, MagicMock()).pod_running("lab-ns", "my-pod") is False

    def test_returns_false_on_empty_list_by_name(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list()
        assert _adapter(core, MagicMock()).pod_running("lab-ns", "no-pod") is False

    def test_propagates_non_404_by_name(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).pod_running("lab-ns", "my-pod")

    def test_uses_label_selector_when_provided(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Running")
        adapter = _adapter(core, MagicMock())
        assert adapter.pod_running("lab-ns", "ignored", label_selector="app=nginx") is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", label_selector="app=nginx"
        )

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


def _mock_list(*deps: MagicMock) -> MagicMock:
    """Return a mock list result with given items."""
    result = MagicMock()
    result.items = list(deps)
    return result


class TestDeploymentReady:
    """deployment_ready uses list_namespaced_deployment (not get) for least-privilege RBAC."""

    def test_returns_true_when_all_replicas_ready(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list(_mock_deployment(3, 3))
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is True
        apps.list_namespaced_deployment.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=nginx"
        )

    def test_returns_false_when_partially_ready(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list(_mock_deployment(3, 1))
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is False

    def test_returns_false_when_ready_is_none(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list(_mock_deployment(1, None))
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is False

    def test_returns_false_when_desired_is_zero(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list(_mock_deployment(0, 0))
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is False

    def test_returns_false_when_desired_is_none(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list(_mock_deployment(None, None))
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx") is False

    def test_returns_false_when_deployment_not_found(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list()  # empty list
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "missing") is False

    def test_returns_false_on_404(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.side_effect = _api_404()
        assert _adapter(MagicMock(), apps).deployment_ready("lab-ns", "missing") is False

    def test_propagates_non_404(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx")

    def test_does_not_call_read_namespaced_deployment(self) -> None:
        """Regression: must use list, not get, to stay within list-only RBAC."""
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list(_mock_deployment(1, 1))
        _adapter(MagicMock(), apps).deployment_ready("lab-ns", "nginx")
        apps.read_namespaced_deployment.assert_not_called()


# ---------------------------------------------------------------------------
# service_exists
# ---------------------------------------------------------------------------


def _mock_svc_list(count: int) -> MagicMock:
    svc_list = MagicMock()
    svc_list.items = [MagicMock() for _ in range(count)]
    return svc_list


class TestServiceExists:
    def test_returns_true_when_service_found(self) -> None:
        core = MagicMock()
        core.list_namespaced_service.return_value = _mock_svc_list(1)
        assert _adapter(core, MagicMock()).service_exists("lab-ns", "nginx-svc") is True
        core.list_namespaced_service.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=nginx-svc"
        )

    def test_returns_false_when_list_is_empty(self) -> None:
        core = MagicMock()
        core.list_namespaced_service.return_value = _mock_svc_list(0)
        assert _adapter(core, MagicMock()).service_exists("lab-ns", "missing") is False

    def test_does_not_call_read_namespaced_service(self) -> None:
        core = MagicMock()
        core.list_namespaced_service.return_value = _mock_svc_list(1)
        _adapter(core, MagicMock()).service_exists("lab-ns", "nginx-svc")
        core.read_namespaced_service.assert_not_called()

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_service.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).service_exists("lab-ns", "nginx-svc")


# ---------------------------------------------------------------------------
# service_has_endpoints
# ---------------------------------------------------------------------------


def _mock_endpoints_list(subsets: Optional[list] = None) -> MagicMock:
    """subsets=None -> no Endpoints object found (empty items list)."""
    ep_list = MagicMock()
    if subsets is None:
        ep_list.items = []
    else:
        ep = MagicMock()
        ep.subsets = subsets
        ep_list.items = [ep]
    return ep_list


def _subset(addresses: Optional[list]) -> MagicMock:
    s = MagicMock()
    s.addresses = addresses
    return s


class TestServiceHasEndpoints:
    def test_returns_true_when_subset_has_addresses(self) -> None:
        core = MagicMock()
        core.list_namespaced_endpoints.return_value = _mock_endpoints_list(
            subsets=[_subset(["10.0.0.5"])]
        )
        assert _adapter(core, MagicMock()).service_has_endpoints("lab-ns", "web-svc") is True
        core.list_namespaced_endpoints.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=web-svc"
        )

    def test_returns_false_when_endpoints_object_missing(self) -> None:
        core = MagicMock()
        core.list_namespaced_endpoints.return_value = _mock_endpoints_list(subsets=None)
        assert _adapter(core, MagicMock()).service_has_endpoints("lab-ns", "web-svc") is False

    def test_returns_false_when_subsets_empty_list(self) -> None:
        core = MagicMock()
        core.list_namespaced_endpoints.return_value = _mock_endpoints_list(subsets=[])
        assert _adapter(core, MagicMock()).service_has_endpoints("lab-ns", "web-svc") is False

    def test_returns_false_when_subset_has_no_addresses(self) -> None:
        """selector-mismatch case: Endpoints object exists but every subset's
        addresses list is empty (or None) — this is the exact state the
        Service-no-Endpoints lab reproduces before the selector fix."""
        core = MagicMock()
        core.list_namespaced_endpoints.return_value = _mock_endpoints_list(
            subsets=[_subset(None)]
        )
        assert _adapter(core, MagicMock()).service_has_endpoints("lab-ns", "web-svc") is False

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_endpoints.side_effect = _api_404()
        assert _adapter(core, MagicMock()).service_has_endpoints("lab-ns", "web-svc") is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_endpoints.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).service_has_endpoints("lab-ns", "web-svc")

    def test_does_not_call_read_namespaced_endpoints(self) -> None:
        core = MagicMock()
        core.list_namespaced_endpoints.return_value = _mock_endpoints_list(
            subsets=[_subset(["10.0.0.5"])]
        )
        _adapter(core, MagicMock()).service_has_endpoints("lab-ns", "web-svc")
        core.read_namespaced_endpoints.assert_not_called()


# ---------------------------------------------------------------------------
# configmap_exists
# ---------------------------------------------------------------------------


def _mock_cm_list(count: int) -> MagicMock:
    cm_list = MagicMock()
    cm_list.items = [MagicMock() for _ in range(count)]
    return cm_list


class TestConfigmapExists:
    def test_returns_true_when_configmap_found(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_list(1)
        assert _adapter(core, MagicMock()).configmap_exists("lab-ns", "app-config") is True
        core.list_namespaced_config_map.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=app-config"
        )

    def test_returns_false_when_list_is_empty(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_list(0)
        assert _adapter(core, MagicMock()).configmap_exists("lab-ns", "missing") is False

    def test_does_not_call_read_namespaced_config_map(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_list(1)
        _adapter(core, MagicMock()).configmap_exists("lab-ns", "app-config")
        core.read_namespaced_config_map.assert_not_called()

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.side_effect = _api_500()
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
# configmap_value_equals
# ---------------------------------------------------------------------------


def _mock_cm_with_data(data: Optional[dict]) -> MagicMock:
    cm = MagicMock()
    cm.data = data
    cm_list = MagicMock()
    cm_list.items = [cm]
    return cm_list


class TestConfigmapValueEquals:
    def test_returns_true_when_key_matches(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_with_data({"APP_MODE": "new"})
        result = _adapter(core, MagicMock()).configmap_value_equals(
            "lab-ns", "app-config", "APP_MODE", "new"
        )
        assert result is True
        core.list_namespaced_config_map.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=app-config"
        )

    def test_returns_false_when_key_does_not_match(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_with_data({"APP_MODE": "old"})
        result = _adapter(core, MagicMock()).configmap_value_equals(
            "lab-ns", "app-config", "APP_MODE", "new"
        )
        assert result is False

    def test_returns_false_when_key_missing(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_with_data({"OTHER_KEY": "x"})
        result = _adapter(core, MagicMock()).configmap_value_equals(
            "lab-ns", "app-config", "APP_MODE", "new"
        )
        assert result is False

    def test_returns_false_when_data_is_none(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_with_data(None)
        result = _adapter(core, MagicMock()).configmap_value_equals(
            "lab-ns", "app-config", "APP_MODE", "new"
        )
        assert result is False

    def test_returns_false_when_configmap_not_found(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_list(0)
        result = _adapter(core, MagicMock()).configmap_value_equals(
            "lab-ns", "missing", "APP_MODE", "new"
        )
        assert result is False

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.side_effect = _api_404()
        result = _adapter(core, MagicMock()).configmap_value_equals(
            "lab-ns", "missing", "APP_MODE", "new"
        )
        assert result is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).configmap_value_equals(
                "lab-ns", "app-config", "APP_MODE", "new"
            )

    def test_never_calls_read_namespaced_config_map(self) -> None:
        core = MagicMock()
        core.list_namespaced_config_map.return_value = _mock_cm_with_data({"APP_MODE": "new"})
        _adapter(core, MagicMock()).configmap_value_equals("lab-ns", "app-config", "APP_MODE", "new")
        core.read_namespaced_config_map.assert_not_called()


# ---------------------------------------------------------------------------
# deployment_restart_triggered / deployment_restart_not_triggered
# ---------------------------------------------------------------------------


def _mock_deployment_with_annotations(annotations: Optional[dict]) -> MagicMock:
    dep = MagicMock()
    dep.spec.template.metadata.annotations = annotations
    dep_list = MagicMock()
    dep_list.items = [dep]
    return dep_list


class TestDeploymentRestartTriggered:
    def test_returns_true_when_restarted_at_annotation_present(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_deployment_with_annotations(
            {"kubectl.kubernetes.io/restartedAt": "2026-07-17T12:00:00-07:00"}
        )
        result = _adapter(MagicMock(), apps).deployment_restart_triggered("lab-ns", "demo")
        assert result is True
        apps.list_namespaced_deployment.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=demo"
        )

    def test_returns_false_when_annotations_empty(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_deployment_with_annotations(None)
        assert _adapter(MagicMock(), apps).deployment_restart_triggered("lab-ns", "demo") is False

    def test_returns_false_when_annotations_present_but_key_missing(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_deployment_with_annotations(
            {"some-other-annotation": "x"}
        )
        assert _adapter(MagicMock(), apps).deployment_restart_triggered("lab-ns", "demo") is False

    def test_returns_false_when_deployment_not_found(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list()
        assert _adapter(MagicMock(), apps).deployment_restart_triggered("lab-ns", "missing") is False

    def test_returns_false_on_404(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.side_effect = _api_404()
        assert _adapter(MagicMock(), apps).deployment_restart_triggered("lab-ns", "missing") is False

    def test_propagates_non_404(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(MagicMock(), apps).deployment_restart_triggered("lab-ns", "demo")


class TestDeploymentRestartNotTriggered:
    def test_returns_true_when_no_restart_annotation_and_deployment_exists(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_deployment_with_annotations(None)
        result = _adapter(MagicMock(), apps).deployment_restart_not_triggered("lab-ns", "demo")
        assert result is True

    def test_calls_list_namespaced_deployment_exactly_once(self) -> None:
        """Regression: an earlier version called list_namespaced_deployment twice
        (once to check existence, once via the shared annotation-check helper),
        opening a narrow TOCTOU window — if the deployment was deleted between
        the two calls, it would incorrectly report "not yet restarted" (True)
        for a deployment that no longer exists. Single call closes that window."""
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_deployment_with_annotations(None)
        _adapter(MagicMock(), apps).deployment_restart_not_triggered("lab-ns", "demo")
        assert apps.list_namespaced_deployment.call_count == 1

    def test_returns_false_when_restart_annotation_present(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_deployment_with_annotations(
            {"kubectl.kubernetes.io/restartedAt": "2026-07-17T12:00:00-07:00"}
        )
        result = _adapter(MagicMock(), apps).deployment_restart_not_triggered("lab-ns", "demo")
        assert result is False

    def test_returns_false_when_deployment_does_not_exist(self) -> None:
        """Unlike the bare annotation-absent check, a nonexistent deployment
        must NOT read as "not triggered" — this type is only meaningful for a
        step that runs after the deployment was already created."""
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value = _mock_list()
        result = _adapter(MagicMock(), apps).deployment_restart_not_triggered("lab-ns", "missing")
        assert result is False

    def test_returns_false_on_404(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.side_effect = _api_404()
        result = _adapter(MagicMock(), apps).deployment_restart_not_triggered("lab-ns", "missing")
        assert result is False

    def test_propagates_non_404(self) -> None:
        apps = MagicMock()
        apps.list_namespaced_deployment.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(MagicMock(), apps).deployment_restart_not_triggered("lab-ns", "demo")


# ---------------------------------------------------------------------------
# pod_succeeded
# ---------------------------------------------------------------------------


class TestPodSucceeded:
    def test_returns_true_when_pod_succeeded_by_name(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Succeeded")
        assert _adapter(core, MagicMock()).pod_succeeded("lab-ns", "dns-check") is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=dns-check"
        )

    def test_returns_false_when_pod_running(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Running")
        assert _adapter(core, MagicMock()).pod_succeeded("lab-ns", "dns-check") is False

    def test_returns_false_when_pod_failed(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Failed")
        assert _adapter(core, MagicMock()).pod_succeeded("lab-ns", "dns-check") is False

    def test_returns_false_on_empty_list(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list()
        assert _adapter(core, MagicMock()).pod_succeeded("lab-ns", "missing") is False

    def test_uses_label_selector_when_provided(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Succeeded")
        adapter = _adapter(core, MagicMock())
        assert adapter.pod_succeeded("lab-ns", "ignored", label_selector="job-name=dns-check") is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", label_selector="job-name=dns-check"
        )

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_404()
        assert _adapter(core, MagicMock()).pod_succeeded("lab-ns", "dns-check") is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).pod_succeeded("lab-ns", "dns-check")

    def test_label_selector_true_if_any_pod_succeeded(self) -> None:
        # Regression: label_selector can match multiple pods (e.g. an old pod
        # still terminating alongside a new one). Must match pod_running's
        # "any match" semantics, not arbitrarily inspect the first list item.
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod("Running"), _mock_pod("Succeeded")]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_succeeded(
            "lab-ns", "any", label_selector="job-name=dns-check"
        ) is True

    def test_label_selector_false_if_no_pod_succeeded(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod("Running"), _mock_pod("Pending")]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_succeeded(
            "lab-ns", "any", label_selector="job-name=dns-check"
        ) is False


# ---------------------------------------------------------------------------
# pod_log_contains
# ---------------------------------------------------------------------------


def _mock_pod_named(name: str) -> MagicMock:
    pod = MagicMock()
    pod.metadata = MagicMock()
    pod.metadata.name = name
    return pod


class TestPodLogContains:
    def test_returns_true_when_substring_present(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_named("dns-check-abc")]
        core.list_namespaced_pod.return_value = pod_list
        core.read_namespaced_pod_log.return_value = "some\nSERVICE_FQDN_RESOLVED\nmore"
        result = _adapter(core, MagicMock()).pod_log_contains(
            "lab-ns", "dns-check", "SERVICE_FQDN_RESOLVED"
        )
        assert result is True
        core.read_namespaced_pod_log.assert_called_once_with("dns-check-abc", "lab-ns")

    def test_returns_false_when_substring_absent(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_named("dns-check-abc")]
        core.list_namespaced_pod.return_value = pod_list
        core.read_namespaced_pod_log.return_value = "unrelated output"
        result = _adapter(core, MagicMock()).pod_log_contains(
            "lab-ns", "dns-check", "SERVICE_FQDN_RESOLVED"
        )
        assert result is False

    def test_returns_false_when_pod_not_found(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = []
        core.list_namespaced_pod.return_value = pod_list
        result = _adapter(core, MagicMock()).pod_log_contains(
            "lab-ns", "dns-check", "SERVICE_FQDN_RESOLVED"
        )
        assert result is False
        core.read_namespaced_pod_log.assert_not_called()

    def test_uses_label_selector_when_provided(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_named("dns-check-xyz")]
        core.list_namespaced_pod.return_value = pod_list
        core.read_namespaced_pod_log.return_value = "SERVICE_FQDN_RESOLVED"
        result = _adapter(core, MagicMock()).pod_log_contains(
            "lab-ns", "ignored", "SERVICE_FQDN_RESOLVED", label_selector="job-name=dns-check"
        )
        assert result is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", label_selector="job-name=dns-check"
        )

    def test_label_selector_true_if_any_matching_pod_log_contains(self) -> None:
        # Regression: label_selector can match multiple pods (e.g. old pod still
        # terminating alongside new one after a restart). Must check across all
        # matched pods, not arbitrarily inspect only the first list item.
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_named("dns-check-old"), _mock_pod_named("dns-check-new")]
        core.list_namespaced_pod.return_value = pod_list
        core.read_namespaced_pod_log.side_effect = [
            "unrelated output",
            "SERVICE_FQDN_RESOLVED",
        ]
        result = _adapter(core, MagicMock()).pod_log_contains(
            "lab-ns", "ignored", "SERVICE_FQDN_RESOLVED", label_selector="app=dns-check"
        )
        assert result is True

    def test_label_selector_false_if_no_matching_pod_log_contains(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_named("dns-check-old"), _mock_pod_named("dns-check-new")]
        core.list_namespaced_pod.return_value = pod_list
        core.read_namespaced_pod_log.side_effect = ["unrelated a", "unrelated b"]
        result = _adapter(core, MagicMock()).pod_log_contains(
            "lab-ns", "ignored", "SERVICE_FQDN_RESOLVED", label_selector="app=dns-check"
        )
        assert result is False

    def test_never_calls_exec(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_named("dns-check-abc")]
        core.list_namespaced_pod.return_value = pod_list
        core.read_namespaced_pod_log.return_value = "SERVICE_FQDN_RESOLVED"
        _adapter(core, MagicMock()).pod_log_contains("lab-ns", "dns-check", "SERVICE_FQDN_RESOLVED")
        assert not hasattr(core, "connect_get_namespaced_pod_exec") or (
            not core.connect_get_namespaced_pod_exec.called
        )

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_404()
        result = _adapter(core, MagicMock()).pod_log_contains(
            "lab-ns", "dns-check", "SERVICE_FQDN_RESOLVED"
        )
        assert result is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).pod_log_contains(
                "lab-ns", "dns-check", "SERVICE_FQDN_RESOLVED"
            )


# ---------------------------------------------------------------------------
# pod_phase_equals
# ---------------------------------------------------------------------------


class TestPodPhaseEquals:
    def test_returns_true_when_phase_matches_by_name(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Pending")
        assert _adapter(core, MagicMock()).pod_phase_equals("lab-ns", "demo", "Pending") is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", field_selector="metadata.name=demo"
        )

    def test_returns_false_when_phase_does_not_match(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list("Running")
        assert _adapter(core, MagicMock()).pod_phase_equals("lab-ns", "demo", "Pending") is False

    def test_returns_false_on_empty_list(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list()
        assert _adapter(core, MagicMock()).pod_phase_equals("lab-ns", "demo", "Pending") is False

    def test_label_selector_true_if_any_pod_matches(self) -> None:
        # Regression-by-design: label_selector can match multiple pods (e.g.
        # an old Running pod alongside a new Pending one after a rollout) —
        # must check across all matches, same "any" semantics as pod_running.
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod("Running"), _mock_pod("Pending")]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_phase_equals(
            "lab-ns", "any", "Pending", label_selector="app=demo"
        ) is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", label_selector="app=demo"
        )

    def test_label_selector_false_if_no_pod_matches(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod("Running"), _mock_pod("Running")]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_phase_equals(
            "lab-ns", "any", "Pending", label_selector="app=demo"
        ) is False

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_404()
        assert _adapter(core, MagicMock()).pod_phase_equals("lab-ns", "demo", "Pending") is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).pod_phase_equals("lab-ns", "demo", "Pending")


# ---------------------------------------------------------------------------
# pod_scheduling_unschedulable
# ---------------------------------------------------------------------------


def _mock_pod_scheduled_condition(status: str, reason: str = "", message: str = "") -> MagicMock:
    cond = MagicMock()
    cond.type = "PodScheduled"
    cond.status = status
    cond.reason = reason
    cond.message = message
    pod = MagicMock()
    pod.status = MagicMock()
    pod.status.conditions = [cond]
    return pod


class TestPodSchedulingUnschedulable:
    def test_returns_true_when_unschedulable(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_scheduled_condition(
            "False", "Unschedulable", "0/1 nodes are available: 1 node(s) didn't match Pod's node affinity/selector."
        )]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_scheduling_unschedulable("lab-ns", "demo") is True

    def test_returns_false_when_scheduled_condition_true(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_scheduled_condition("True")]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_scheduling_unschedulable("lab-ns", "demo") is False

    def test_returns_false_when_reason_is_not_unschedulable(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_scheduled_condition("False", "SchedulerError", "some other reason")]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_scheduling_unschedulable("lab-ns", "demo") is False

    def test_returns_false_when_no_pod_scheduled_condition_present(self) -> None:
        core = MagicMock()
        pod = MagicMock()
        pod.status = MagicMock()
        pod.status.conditions = []
        pod_list = MagicMock()
        pod_list.items = [pod]
        core.list_namespaced_pod.return_value = pod_list
        assert _adapter(core, MagicMock()).pod_scheduling_unschedulable("lab-ns", "demo") is False

    def test_returns_false_on_empty_pod_list(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.return_value = _mock_pod_list()
        assert _adapter(core, MagicMock()).pod_scheduling_unschedulable("lab-ns", "demo") is False

    def test_message_contains_true_when_substring_present(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_scheduled_condition(
            "False", "Unschedulable", "0/1 nodes are available: 1 node(s) didn't match Pod's node affinity/selector."
        )]
        core.list_namespaced_pod.return_value = pod_list
        result = _adapter(core, MagicMock()).pod_scheduling_unschedulable(
            "lab-ns", "demo", message_contains="node affinity/selector"
        )
        assert result is True

    def test_message_contains_false_when_substring_absent(self) -> None:
        core = MagicMock()
        pod_list = MagicMock()
        pod_list.items = [_mock_pod_scheduled_condition("False", "Unschedulable", "insufficient cpu")]
        core.list_namespaced_pod.return_value = pod_list
        result = _adapter(core, MagicMock()).pod_scheduling_unschedulable(
            "lab-ns", "demo", message_contains="node affinity/selector"
        )
        assert result is False

    def test_label_selector_true_if_any_matching_pod_unschedulable(self) -> None:
        core = MagicMock()
        running_pod = _mock_pod_scheduled_condition("True")
        unschedulable_pod = _mock_pod_scheduled_condition("False", "Unschedulable", "didn't match")
        pod_list = MagicMock()
        pod_list.items = [running_pod, unschedulable_pod]
        core.list_namespaced_pod.return_value = pod_list
        result = _adapter(core, MagicMock()).pod_scheduling_unschedulable(
            "lab-ns", "ignored", label_selector="app=demo"
        )
        assert result is True
        core.list_namespaced_pod.assert_called_once_with(
            "lab-ns", label_selector="app=demo"
        )

    def test_returns_false_on_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_404()
        assert _adapter(core, MagicMock()).pod_scheduling_unschedulable("lab-ns", "demo") is False

    def test_propagates_non_404(self) -> None:
        core = MagicMock()
        core.list_namespaced_pod.side_effect = _api_500()
        with pytest.raises(ApiException):
            _adapter(core, MagicMock()).pod_scheduling_unschedulable("lab-ns", "demo")


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
