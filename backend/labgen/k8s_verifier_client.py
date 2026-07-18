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
    from kubernetes.client import CoreV1Api, AppsV1Api, V1Pod


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
        404 → namespace is gone.
        403 → namespace was deleted and took the namespace-scoped RoleBinding with it;
              treat as "not found" rather than propagating a Forbidden error.
        Other errors propagate to the caller.
        """
        try:
            self._core.list_namespaced_config_map(namespace, limit=1)
            return True
        except ApiException as exc:
            if exc.status in (403, 404):
                return False
            raise

    def pod_running(
        self, namespace: str, name: str, label_selector: Optional[str] = None
    ) -> bool:
        """Return True if at least one Running pod matches the criteria.

        When label_selector is provided, lists pods by label and checks phase.
        Without label_selector, lists pods by field_selector — does not require 'get' RBAC.
        The verifier SA requires only 'list' on pods (not 'get').
        """
        try:
            if label_selector:
                pods = self._core.list_namespaced_pod(
                    namespace, label_selector=label_selector
                )
            else:
                pods = self._core.list_namespaced_pod(
                    namespace, field_selector=f"metadata.name={name}"
                )
            return any(
                p.status is not None and p.status.phase == "Running"
                for p in pods.items
            )
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def deployment_ready(self, namespace: str, name: str) -> bool:
        """Return True if all desired replicas are ready (ready_replicas >= spec.replicas > 0).

        Uses list_namespaced_deployment with field_selector — does not require 'get' RBAC.
        The verifier SA requires only 'list' on apps/deployments (not 'get').
        """
        try:
            result = self._apps.list_namespaced_deployment(
                namespace, field_selector=f"metadata.name={name}"
            )
            if not result.items:
                return False
            dep = result.items[0]
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
        """Return True if a service with this name exists.

        Uses list_namespaced_service with field_selector — does not require 'get' RBAC.
        """
        try:
            result = self._core.list_namespaced_service(
                namespace, field_selector=f"metadata.name={name}"
            )
            return len(result.items) > 0
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def service_has_endpoints(self, namespace: str, name: str) -> bool:
        """Return True if the named Service has at least one ready Endpoint address.

        Uses list_namespaced_endpoints with field_selector — equivalent to
        `kubectl get endpoints <name>` (does not require 'get' RBAC — only 'list').
        Deliberately does NOT use `kubectl describe service`'s Endpoints field: on
        this K3s version that field is unreliable and can show <none> even when
        the Service is correctly routing to Ready Pods (see SERVICE_NO_ENDPOINTS_
        OFFICIAL_ARTICLE_DRAFT_v0.1.md). The core/v1 Endpoints object queried here
        is the same data `kubectl get endpoints` reads and is not affected by that bug.
        Returns False if the Endpoints object does not exist, or exists with zero
        subsets, or every subset has an empty addresses list.
        """
        try:
            result = self._core.list_namespaced_endpoints(
                namespace, field_selector=f"metadata.name={name}"
            )
            if not result.items:
                return False
            endpoints = result.items[0]
            subsets = endpoints.subsets or []
            return any(subset.addresses for subset in subsets)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def configmap_exists(self, namespace: str, name: str) -> bool:
        """Return True if a configmap with this name exists.

        Uses list_namespaced_config_map with field_selector — does not require 'get' RBAC.
        """
        try:
            result = self._core.list_namespaced_config_map(
                namespace, field_selector=f"metadata.name={name}"
            )
            return len(result.items) > 0
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

    def deployment_unavailable(self, namespace: str, name: str) -> bool:
        """Return True if the deployment exists AND has 0 available replicas (pods are crashing).

        Uses list_namespaced_deployment with field_selector — does not require 'get' RBAC.
        Returns False if the deployment does not exist (not found or empty list).
        This is the semantic inverse of deployment_ready: confirms pods are NOT ready.
        """
        try:
            result = self._apps.list_namespaced_deployment(
                namespace, field_selector=f"metadata.name={name}"
            )
            if not result.items:
                return False
            dep = result.items[0]
            available = (
                dep.status.available_replicas
                if dep.status and dep.status.available_replicas is not None
                else 0
            )
            return available == 0
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def namespace_not_exists(self, namespace: str) -> bool:
        """Return True if the namespace does NOT exist.

        Delegates to namespace_exists and inverts the result.
        Used to verify cleanup completion after kubectl delete namespace.
        """
        return not self.namespace_exists(namespace)

    def configmap_value_equals(
        self, namespace: str, name: str, config_key: str, expected_value: str
    ) -> bool:
        """Return True if the ConfigMap exists and .data[config_key] == expected_value.

        Uses list_namespaced_config_map with field_selector — does not require 'get' RBAC.
        Returns False if the ConfigMap, or the key within it, does not exist.
        ConfigMap data is not sensitive (unlike Secret data), so reading and
        comparing its value here does not violate the "no secret value reads"
        constraint that applies to secret_key_exists/secret_value_equals.
        """
        try:
            result = self._core.list_namespaced_config_map(
                namespace, field_selector=f"metadata.name={name}"
            )
            if not result.items:
                return False
            data = result.items[0].data or {}
            return data.get(config_key) == expected_value
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def _deployment_restart_annotation_present(self, namespace: str, name: str) -> Optional[bool]:
        """Shared helper: True if spec.template.metadata.annotations has
        kubectl.kubernetes.io/restartedAt — the annotation `kubectl rollout
        restart` sets on the Pod template, which is what actually forces a
        new ReplicaSet/Pod (env values injected via envFrom/valueFrom are
        resolved once at container creation and are not live-reloaded when
        only the referenced ConfigMap's data changes — verified empirically
        against this K3s version: patching a ConfigMap alone does not touch
        this annotation or create a new Pod; only rollout restart does).

        Returns None (not False) if the deployment does not exist, so callers
        can distinguish "deployment missing" from "deployment exists, not yet
        restarted" with a single API call — avoids a second list call (and
        the TOCTOU window a second call would open) in
        deployment_restart_not_triggered.
        """
        try:
            result = self._apps.list_namespaced_deployment(
                namespace, field_selector=f"metadata.name={name}"
            )
            if not result.items:
                return None
            dep = result.items[0]
            template_meta = (
                dep.spec.template.metadata
                if dep.spec and dep.spec.template
                else None
            )
            annotations = template_meta.annotations if template_meta else None
            if not annotations:
                return False
            return "kubectl.kubernetes.io/restartedAt" in annotations
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise

    def deployment_restart_triggered(self, namespace: str, name: str) -> bool:
        """Return True if this Deployment has been restarted (kubectl rollout restart).

        See _deployment_restart_annotation_present for the mechanism. Returns
        False if the deployment does not exist or has not been restarted yet.
        """
        return bool(self._deployment_restart_annotation_present(namespace, name))

    def deployment_restart_not_triggered(self, namespace: str, name: str) -> bool:
        """Return True if this Deployment exists and has NOT been restarted yet.

        Semantic inverse of deployment_restart_triggered, but also requires
        the deployment to exist (a nonexistent deployment has "not triggered"
        a restart in a literal sense, but that is never the intended meaning
        for a lab step that runs after the deployment was already created).
        Single list call — see _deployment_restart_annotation_present's
        None-means-missing contract.
        """
        present = self._deployment_restart_annotation_present(namespace, name)
        if present is None:
            return False
        return not present

    def _find_pods(
        self, namespace: str, name: str, label_selector: Optional[str]
    ) -> "list[V1Pod]":
        """Shared lookup: return all matching pod objects (possibly empty).

        Mirrors pod_running's field_selector/label_selector convention: when
        label_selector is given, lists by label (does not require pod to be
        named `name`); otherwise lists by exact metadata.name. A label
        selector can match more than one pod (e.g. an old pod still
        terminating alongside a freshly restarted one) — callers must check
        across all matches, not arbitrarily inspect only the first.
        """
        if label_selector:
            result = self._core.list_namespaced_pod(namespace, label_selector=label_selector)
        else:
            result = self._core.list_namespaced_pod(
                namespace, field_selector=f"metadata.name={name}"
            )
        return list(result.items)

    def pod_succeeded(
        self, namespace: str, name: str, label_selector: Optional[str] = None
    ) -> bool:
        """Return True if any matched pod's phase is Succeeded.

        Uses list_namespaced_pod (list, not get) — same RBAC footprint as
        pod_running. Used to confirm a one-shot diagnostic Pod (e.g. a DNS
        lookup probe) ran to completion, without requiring `kubectl exec`.
        """
        try:
            pods = self._find_pods(namespace, name, label_selector)
            return any(p.status is not None and p.status.phase == "Succeeded" for p in pods)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def pod_log_contains(
        self,
        namespace: str,
        name: str,
        contains: str,
        label_selector: Optional[str] = None,
    ) -> bool:
        """Return True if any matched pod's log output contains `contains`.

        Uses read_namespaced_pod_log — a log read, not `kubectl exec` (no
        interactive session, no arbitrary command execution inside the
        container). This is the sanctioned way to observe a diagnostic Pod's
        stdout (e.g. nslookup output) when exec is banned for both learner
        and verifier.
        """
        try:
            pods = self._find_pods(namespace, name, label_selector)
            for pod in pods:
                log = self._core.read_namespaced_pod_log(pod.metadata.name, namespace)
                if contains in (log or ""):
                    return True
            return False
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def pod_phase_equals(
        self,
        namespace: str,
        name: str,
        expected_phase: str,
        label_selector: Optional[str] = None,
    ) -> bool:
        """Return True if any matched pod's phase equals expected_phase.

        Uses list_namespaced_pod (list, not get) — same RBAC footprint as
        pod_running. "Any match" semantics: a label selector can match both
        an old pod (e.g. still Running) and a newly created one (e.g.
        Pending after a rollout triggered by a bad nodeSelector) — must find
        the one that actually matches, not just inspect the first list item.
        """
        try:
            pods = self._find_pods(namespace, name, label_selector)
            return any(p.status is not None and p.status.phase == expected_phase for p in pods)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def pod_scheduling_unschedulable(
        self,
        namespace: str,
        name: str,
        label_selector: Optional[str] = None,
        message_contains: Optional[str] = None,
    ) -> bool:
        """Return True if any matched pod has a PodScheduled condition with
        status=False and reason=Unschedulable (optionally also requiring its
        message to contain `message_contains`, e.g. to confirm the failure
        is specifically a node selector/affinity mismatch rather than
        resource pressure or a taint).

        Pod conditions (not Events) are the source of truth here: Events
        have a TTL and can expire, while status.conditions reflects current
        state and is read via the same list_namespaced_pod call already used
        elsewhere — no extra RBAC needed beyond what pod_running/pod_phase_equals
        already require.
        """
        try:
            pods = self._find_pods(namespace, name, label_selector)
            for pod in pods:
                conditions = pod.status.conditions if pod.status else None
                if not conditions:
                    continue
                for cond in conditions:
                    if cond.type != "PodScheduled" or cond.status != "False":
                        continue
                    if cond.reason != "Unschedulable":
                        continue
                    if message_contains is not None and message_contains not in (cond.message or ""):
                        continue
                    return True
            return False
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
