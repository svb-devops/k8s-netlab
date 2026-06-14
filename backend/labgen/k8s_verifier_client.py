"""
Real K8s verifier client — implements K8sVerifierClientPort via kubernetes-client/python.

Constraints:
- Kubeconfig loaded from content string only; never reads ~/.kube/config or admin kubeconfig.
- All calls are namespace-scoped (no cluster-wide write/exec).
- secret_exists uses list_namespaced_secret (list only — no data/key access).
- ApiException status 404 → returns False.
- Other ApiException propagates; VerifierService maps it to error_code="k8s_error".
- No shell verify, no node-level access, no cluster-scope operations.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import yaml
from kubernetes import client as k8s_client
from kubernetes.client.exceptions import ApiException
from kubernetes.config.kube_config import KubeConfigLoader

from backend.labgen.verifier import K8sVerifierClientPort

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api, AppsV1Api


# ---------------------------------------------------------------------------
# KubernetesApiFactory  (injectable — replace in tests with a stub)
# ---------------------------------------------------------------------------


class KubernetesApiFactory:
    """Constructs (CoreV1Api, AppsV1Api) from a kubeconfig YAML string.

    Both API objects share one ApiClient (single connection pool).
    Injectable for testing: tests replace this with a stub that returns
    mock API objects without touching the network.
    """

    def build(
        self, kubeconfig_content: str
    ) -> tuple["CoreV1Api", "AppsV1Api"]:
        """Parse kubeconfig_content and return (CoreV1Api, AppsV1Api)."""
        config_dict = yaml.safe_load(kubeconfig_content)
        cfg = k8s_client.Configuration()
        loader = KubeConfigLoader(config_dict=config_dict)
        loader.load_and_set(cfg)
        api = k8s_client.ApiClient(configuration=cfg)
        return k8s_client.CoreV1Api(api_client=api), k8s_client.AppsV1Api(api_client=api)


# ---------------------------------------------------------------------------
# K8sVerifierClientAdapter  (real implementation)
# ---------------------------------------------------------------------------


class K8sVerifierClientAdapter(K8sVerifierClientPort):
    """Real K8s verifier client backed by kubernetes-client/python.

    Args:
        kubeconfig_content: Raw kubeconfig YAML string (verifier identity only).
        factory: KubernetesApiFactory (or test stub) that builds API objects.
    """

    def __init__(
        self,
        kubeconfig_content: str,
        factory: KubernetesApiFactory,
    ) -> None:
        self._core, self._apps = factory.build(kubeconfig_content)

    # ------------------------------------------------------------------
    # K8sVerifierClientPort implementation
    # ------------------------------------------------------------------

    def namespace_exists(self, namespace: str) -> bool:
        """Return True if the namespace exists.

        Uses list_namespaced_config_map (namespace-scoped, limit=1) so only
        the per-session RoleBinding is required — not a ClusterRoleBinding.
        404 → namespace is gone; other errors propagate to the caller.
        """
        try:
            self._core.list_namespaced_config_map(namespace, limit=1)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def pod_running(
        self, namespace: str, name: str, label_selector: Optional[str] = None
    ) -> bool:
        """Return True if at least one Running pod matches the criteria.

        When label_selector is provided, lists pods by label and checks phase.
        Without label_selector, reads the pod by name and checks phase.
        """
        try:
            if label_selector:
                pods = self._core.list_namespaced_pod(
                    namespace, label_selector=label_selector
                )
                return any(
                    p.status is not None and p.status.phase == "Running"
                    for p in pods.items
                )
            else:
                pod = self._core.read_namespaced_pod(name, namespace)
                return pod.status is not None and pod.status.phase == "Running"
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def deployment_ready(self, namespace: str, name: str) -> bool:
        """Return True if all desired replicas are ready (ready_replicas >= spec.replicas > 0)."""
        try:
            dep = self._apps.read_namespaced_deployment(name, namespace)
            desired = (
                dep.spec.replicas
                if dep.spec and dep.spec.replicas is not None
                else 0
            )
            ready = (
                dep.status.ready_replicas
                if dep.status and dep.status.ready_replicas is not None
                else 0
            )
            return desired > 0 and ready >= desired
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def service_exists(self, namespace: str, name: str) -> bool:
        try:
            self._core.read_namespaced_service(name, namespace)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def configmap_exists(self, namespace: str, name: str) -> bool:
        try:
            self._core.read_namespaced_config_map(name, namespace)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def secret_exists(self, namespace: str, name: str) -> bool:
        """Return True if a secret with this name exists.

        Uses list_namespaced_secret with field_selector — never reads secret data.
        The verifier SA requires only 'list' on secrets (not 'get').
        """
        try:
            result = self._core.list_namespaced_secret(
                namespace, field_selector=f"metadata.name={name}"
            )
            return len(result.items) > 0
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise


# ---------------------------------------------------------------------------
# K8sVerifierClientFactory  (module-level factory function for routes.py)
# ---------------------------------------------------------------------------

_default_factory = KubernetesApiFactory()


def K8sVerifierClientFactory(kubeconfig_content: str) -> K8sVerifierClientPort:
    """Production factory: build a real K8sVerifierClientAdapter from kubeconfig content."""
    return K8sVerifierClientAdapter(kubeconfig_content, _default_factory)
