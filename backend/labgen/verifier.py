"""
Verifier service — dispatches K8s verify checks for active lab sessions.

K8sVerifierClientPort abstracts the real K8s client (not yet implemented).
VerifierService enforces all security constraints before delegating to the client.

Security constraints enforced before any K8s call:
- Only LAB_ACTIVE sessions may be checked.
- Namespace must match session.namespace or the sentinel {{lab_namespace}}.
- cluster_scope=True is rejected (verifier has no cluster-wide permissions).
- Verifier kubeconfig is loaded from VerifierCredentialStore only (no admin fallback).
- No shell verify, no secret data reads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, Optional

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.models import (
    LabSessionStatus,
    VerifyResult,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.verifier_credentials import VerifierCredentialStore

if TYPE_CHECKING:
    from backend.labgen.lab_session_repository import LabSessionRepository


# VerifyResult lives in models.py (to avoid circular imports with LabSessionState).
# Imported above so `from backend.labgen.verifier import VerifyResult` still works.


# ---------------------------------------------------------------------------
# K8s verifier client port
# ---------------------------------------------------------------------------


class K8sVerifierClientPort(ABC):
    """Abstract K8s client scoped to verifier permissions (namespace read-only)."""

    @abstractmethod
    def namespace_exists(self, namespace: str) -> bool: ...

    @abstractmethod
    def pod_running(
        self, namespace: str, name: str, label_selector: Optional[str] = None
    ) -> bool: ...

    @abstractmethod
    def deployment_ready(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def service_exists(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def service_has_endpoints(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def configmap_exists(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def secret_exists(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def deployment_unavailable(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def namespace_not_exists(self, namespace: str) -> bool: ...

    @abstractmethod
    def configmap_value_equals(
        self, namespace: str, name: str, config_key: str, expected_value: str
    ) -> bool: ...

    @abstractmethod
    def deployment_restart_triggered(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def deployment_restart_not_triggered(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def pod_succeeded(
        self, namespace: str, name: str, label_selector: Optional[str] = None
    ) -> bool: ...

    @abstractmethod
    def pod_log_contains(
        self,
        namespace: str,
        name: str,
        contains: str,
        label_selector: Optional[str] = None,
    ) -> bool: ...

    @abstractmethod
    def pod_phase_equals(
        self,
        namespace: str,
        name: str,
        expected_phase: str,
        label_selector: Optional[str] = None,
    ) -> bool: ...

    @abstractmethod
    def pod_scheduling_unschedulable(
        self,
        namespace: str,
        name: str,
        label_selector: Optional[str] = None,
        message_contains: Optional[str] = None,
    ) -> bool: ...


# ---------------------------------------------------------------------------
# Fake client (tests only)
# ---------------------------------------------------------------------------


class FakeK8sVerifierClient(K8sVerifierClientPort):
    """Configurable in-process stub. No real K8s calls. Tests only.

    Responses are keyed by tuple; unmatched keys fall through to ``default``.
    Example: FakeK8sVerifierClient({("pod_running", "lab-ns", "my-pod"): False})
    """

    def __init__(
        self,
        responses: Optional[dict[tuple, bool]] = None,
        default: bool = True,
    ) -> None:
        self._responses: dict[tuple, bool] = responses or {}
        self._default = default

    def _get(self, key: tuple) -> bool:
        return self._responses.get(key, self._default)

    def namespace_exists(self, namespace: str) -> bool:
        return self._get(("namespace_exists", namespace))

    def pod_running(
        self, namespace: str, name: str, label_selector: Optional[str] = None
    ) -> bool:
        return self._get(("pod_running", namespace, name))

    def deployment_ready(self, namespace: str, name: str) -> bool:
        return self._get(("deployment_ready", namespace, name))

    def service_exists(self, namespace: str, name: str) -> bool:
        return self._get(("service_exists", namespace, name))

    def service_has_endpoints(self, namespace: str, name: str) -> bool:
        return self._get(("service_has_endpoints", namespace, name))

    def configmap_exists(self, namespace: str, name: str) -> bool:
        return self._get(("configmap_exists", namespace, name))

    def secret_exists(self, namespace: str, name: str) -> bool:
        return self._get(("secret_exists", namespace, name))

    def deployment_unavailable(self, namespace: str, name: str) -> bool:
        return self._get(("deployment_unavailable", namespace, name))

    def namespace_not_exists(self, namespace: str) -> bool:
        return self._get(("namespace_not_exists", namespace))

    def configmap_value_equals(
        self, namespace: str, name: str, config_key: str, expected_value: str
    ) -> bool:
        return self._get(("configmap_value_equals", namespace, name, config_key, expected_value))

    def deployment_restart_triggered(self, namespace: str, name: str) -> bool:
        return self._get(("deployment_restart_triggered", namespace, name))

    def deployment_restart_not_triggered(self, namespace: str, name: str) -> bool:
        return self._get(("deployment_restart_not_triggered", namespace, name))

    def pod_succeeded(
        self, namespace: str, name: str, label_selector: Optional[str] = None
    ) -> bool:
        return self._get(("pod_succeeded", namespace, name))

    def pod_log_contains(
        self,
        namespace: str,
        name: str,
        contains: str,
        label_selector: Optional[str] = None,
    ) -> bool:
        return self._get(("pod_log_contains", namespace, name, contains))

    def pod_phase_equals(
        self,
        namespace: str,
        name: str,
        expected_phase: str,
        label_selector: Optional[str] = None,
    ) -> bool:
        return self._get(("pod_phase_equals", namespace, name, expected_phase))

    def pod_scheduling_unschedulable(
        self,
        namespace: str,
        name: str,
        label_selector: Optional[str] = None,
        message_contains: Optional[str] = None,
    ) -> bool:
        return self._get(("pod_scheduling_unschedulable", namespace, name, message_contains))


# ---------------------------------------------------------------------------
# Supported verify types
# ---------------------------------------------------------------------------

_SUPPORTED_TYPES: frozenset[VerifyType] = frozenset({
    VerifyType.NAMESPACE_EXISTS,
    VerifyType.NAMESPACE_NOT_EXISTS,
    VerifyType.POD_RUNNING,
    VerifyType.DEPLOYMENT_READY,
    VerifyType.DEPLOYMENT_UNAVAILABLE,
    VerifyType.SERVICE_EXISTS,
    VerifyType.SERVICE_HAS_ENDPOINTS,
    VerifyType.CONFIGMAP_EXISTS,
    VerifyType.SECRET_EXISTS,
    VerifyType.CONFIGMAP_VALUE_EQUALS,
    VerifyType.DEPLOYMENT_RESTART_TRIGGERED,
    VerifyType.DEPLOYMENT_RESTART_NOT_TRIGGERED,
    VerifyType.POD_SUCCEEDED,
    VerifyType.POD_LOG_CONTAINS,
    VerifyType.POD_PHASE_EQUALS,
    VerifyType.POD_SCHEDULING_UNSCHEDULABLE,
})

_NS_SENTINEL = "{{lab_namespace}}"


# ---------------------------------------------------------------------------
# Verifier service
# ---------------------------------------------------------------------------


class VerifierService:
    """Dispatches K8s verify checks for active lab sessions.

    ``k8s_client_factory``: callable(kubeconfig_yaml: str) -> K8sVerifierClientPort.
    Decouples kubeconfig loading from client construction for test injection.
    """

    def __init__(
        self,
        session_repo: "LabSessionRepository",
        credential_store: VerifierCredentialStore,
        k8s_client_factory: Callable[[str], K8sVerifierClientPort],
        verifier_vm_id: Optional[str] = None,
    ) -> None:
        self._session_repo = session_repo
        self._credential_store = credential_store
        self._k8s_client_factory = k8s_client_factory
        # K8s-domain sessions all run their kubectl terminal against the shared
        # platform cluster (LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is a single global
        # config value — see lab_kubectl_ws.py — not looked up per session.vm_id).
        # session.vm_id is a per-student quota-bookkeeping number from the legacy
        # VM pool and is NOT where K8s commands actually run, so verifier
        # credentials must not be looked up by it either. When set, this pins
        # credential lookup to the shared platform VM instead. None preserves the
        # legacy per-session-vm_id lookup (needed for tests and any future
        # non-shared-cluster runtime).
        self._verifier_vm_id = verifier_vm_id

    def check(self, session_id: str, template: VerifyTemplate) -> VerifyResult:
        def _fail(reason: FailureReason, detail: str = "") -> VerifyResult:
            code = reason.value
            return VerifyResult(
                session_id=session_id,
                verify_id=template.verify_id,
                verify_type=template.type.value,
                passed=False,
                error_code=code,
                failure_reason=code,
                detail=detail,
            )

        session = self._session_repo.get(session_id)
        if session is None:
            return _fail(FailureReason.VERIFIER_SESSION_NOT_FOUND)

        if session.lab_session_status != LabSessionStatus.LAB_ACTIVE:
            return _fail(
                FailureReason.VERIFIER_SESSION_NOT_ACTIVE,
                f"status={session.lab_session_status.value}",
            )

        if template.cluster_scope:
            return _fail(FailureReason.VERIFIER_CLUSTER_SCOPE_NOT_SUPPORTED)

        resolved_ns = session.namespace
        if resolved_ns is None or template.namespace not in {_NS_SENTINEL, resolved_ns}:
            # Do not include resolved_ns in detail: namespace is internal and must not
            # appear in learner-facing StepCheckResponse.verify_results.detail.
            return _fail(FailureReason.VERIFIER_NAMESPACE_MISMATCH)

        if template.type not in _SUPPORTED_TYPES:
            return _fail(
                FailureReason.VERIFIER_TYPE_NOT_IMPLEMENTED,
                f"type={template.type.value}",
            )

        credential_vm_id = self._verifier_vm_id or session.vm_id
        if not self._credential_store.exists(credential_vm_id):
            return _fail(FailureReason.VERIFIER_CREDENTIAL_MISSING, f"vm_id={credential_vm_id}")

        kubeconfig, _ = self._credential_store.load(credential_vm_id)
        client = self._k8s_client_factory(kubeconfig)
        passed = self._dispatch(client, resolved_ns, template)
        detail = self._make_detail(template.type, template.name or "", passed)

        return VerifyResult(
            session_id=session_id,
            verify_id=template.verify_id,
            verify_type=template.type.value,
            passed=passed,
            detail=detail,
        )

    @staticmethod
    def _make_detail(vtype: "VerifyType", name: str, passed: bool) -> str:
        """Return a learner-facing message for dispatch-path results.

        Must never include session.namespace or any credential value.
        Returns "" for unknown types so new types are safe by default.
        """
        if vtype == VerifyType.NAMESPACE_EXISTS:
            return (
                "Your isolated namespace is active on the cluster."
                if passed
                else "Your namespace was not found. Try clicking Check Step again in a moment."
            )
        if vtype == VerifyType.CONFIGMAP_EXISTS:
            return (
                f'ConfigMap "{name}" was found in your isolated namespace. '
                "Your Kubernetes resource was created successfully."
                if passed
                else f'ConfigMap "{name}" was not found. '
                f'Check that the name is exactly "{name}" and that it was created in your lab namespace.'
            )
        if vtype == VerifyType.SECRET_EXISTS:
            return (
                f'Secret "{name}" was found in your isolated namespace. '
                "The verifier confirmed the Secret object exists without reading its value."
                if passed
                else f'Secret "{name}" was not found. '
                f'Check that the name is exactly "{name}" and that it was created in your lab namespace.'
            )
        if vtype == VerifyType.POD_RUNNING:
            return (
                f'Pod "{name}" is running in your namespace.'
                if passed
                else f'Pod "{name}" is not running yet. Check the pod status with: kubectl get pods'
            )
        if vtype == VerifyType.DEPLOYMENT_READY:
            return (
                f'Deployment "{name}" is available with 1 ready replica in your isolated namespace. '
                "Kubernetes has created a Pod for this workload."
                if passed
                else f'Deployment "{name}" is not ready yet. '
                f'Check that the Deployment is named "{name}", uses 1 replica, and uses the approved image. '
                "It may take a short time for the Pod to become ready."
            )
        if vtype == VerifyType.SERVICE_EXISTS:
            return (
                f'Service "{name}" exists in your namespace.'
                if passed
                else f'Service "{name}" was not found. Check the service name and namespace.'
            )
        if vtype == VerifyType.SERVICE_HAS_ENDPOINTS:
            return (
                f'Service "{name}" has at least one Endpoint address — '
                "it is now routing traffic to a matching Pod."
                if passed
                else f'Service "{name}" has no Endpoints yet. Its selector does not match any '
                f'Ready Pod\'s labels. Check with: kubectl get endpoints {name} '
                "(not kubectl describe service — its Endpoints field is unreliable on this K3s version)."
            )
        if vtype == VerifyType.DEPLOYMENT_UNAVAILABLE:
            return (
                f'Deployment "{name}" has no available replicas — '
                "CrashLoopBackOff or pending state confirmed. You may proceed to inspect the failure."
                if passed
                else f'Deployment "{name}" has available replicas — pods are not in a crashing state. '
                "Check that the deployment was created correctly with a failing command."
            )
        if vtype == VerifyType.NAMESPACE_NOT_EXISTS:
            return (
                "Namespace cleanup confirmed — the lab namespace no longer exists on the cluster."
                if passed
                else "Namespace still exists. Make sure kubectl delete namespace completed successfully "
                "and wait a moment before checking again."
            )
        if vtype == VerifyType.CONFIGMAP_VALUE_EQUALS:
            return (
                f'ConfigMap "{name}" now has the expected value for this step.'
                if passed
                else f'ConfigMap "{name}" does not yet have the expected value. '
                "Check that you patched the correct key with the correct value."
            )
        if vtype == VerifyType.DEPLOYMENT_RESTART_NOT_TRIGGERED:
            return (
                f'Deployment "{name}" has not been restarted yet — '
                "its currently running Pod predates this step, which is expected at this point."
                if passed
                else f'Deployment "{name}" already shows a restart annotation. '
                "If you already ran kubectl rollout restart, continue to the next step instead."
            )
        if vtype == VerifyType.DEPLOYMENT_RESTART_TRIGGERED:
            return (
                f'Deployment "{name}" has been restarted — Kubernetes created a new Pod '
                "for this workload after the restart."
                if passed
                else f'Deployment "{name}" has not been restarted yet. '
                f"Run: kubectl rollout restart deployment/{name}"
            )
        if vtype == VerifyType.POD_SUCCEEDED:
            return (
                f'Pod "{name}" completed successfully in your namespace.'
                if passed
                else f'Pod "{name}" has not completed successfully yet. '
                "Check its status with: kubectl get pods"
            )
        if vtype == VerifyType.POD_LOG_CONTAINS:
            return (
                f'Pod "{name}" produced the expected diagnostic output.'
                if passed
                else f'Pod "{name}" logs do not yet contain the expected output. '
                f"Check with: kubectl logs {name}"
            )
        if vtype == VerifyType.POD_PHASE_EQUALS:
            return (
                f'Pod "{name}" is in the expected phase.'
                if passed
                else f'Pod "{name}" is not yet in the expected phase. '
                "Check with: kubectl get pods -o wide"
            )
        if vtype == VerifyType.POD_SCHEDULING_UNSCHEDULABLE:
            return (
                f'Pod "{name}" is confirmed unschedulable — the scheduler could not '
                "place it on any node, matching this step's expected failure mode."
                if passed
                else f'Pod "{name}" is not (yet) confirmed unschedulable. '
                f"Check with: kubectl describe pod -l app={name}"
            )
        return ""

    @staticmethod
    def _dispatch(
        client: K8sVerifierClientPort,
        namespace: str,
        template: VerifyTemplate,
    ) -> bool:
        name = template.name
        vtype = template.type
        if vtype == VerifyType.NAMESPACE_EXISTS:
            return client.namespace_exists(namespace)
        if vtype == VerifyType.POD_RUNNING:
            return client.pod_running(namespace, name, template.label_selector)
        if vtype == VerifyType.DEPLOYMENT_READY:
            return client.deployment_ready(namespace, name)
        if vtype == VerifyType.SERVICE_EXISTS:
            return client.service_exists(namespace, name)
        if vtype == VerifyType.SERVICE_HAS_ENDPOINTS:
            return client.service_has_endpoints(namespace, name)
        if vtype == VerifyType.CONFIGMAP_EXISTS:
            return client.configmap_exists(namespace, name)
        if vtype == VerifyType.SECRET_EXISTS:
            return client.secret_exists(namespace, name)
        if vtype == VerifyType.DEPLOYMENT_UNAVAILABLE:
            return client.deployment_unavailable(namespace, name)
        if vtype == VerifyType.NAMESPACE_NOT_EXISTS:
            return client.namespace_not_exists(namespace)
        if vtype == VerifyType.CONFIGMAP_VALUE_EQUALS:
            return client.configmap_value_equals(
                namespace, name, template.config_key or "", template.expected_value or ""
            )
        if vtype == VerifyType.DEPLOYMENT_RESTART_TRIGGERED:
            return client.deployment_restart_triggered(namespace, name)
        if vtype == VerifyType.DEPLOYMENT_RESTART_NOT_TRIGGERED:
            return client.deployment_restart_not_triggered(namespace, name)
        if vtype == VerifyType.POD_SUCCEEDED:
            return client.pod_succeeded(namespace, name, template.label_selector)
        if vtype == VerifyType.POD_LOG_CONTAINS:
            if template.log_contains is None:
                # Fail closed: an empty substring is contained in every string,
                # so falling back to "" would make this verify type silently
                # always pass instead of always fail (StaticValidator blocks
                # publishing a draft missing this field, but dispatch must not
                # depend on that gate alone — see verifier_credentials BLOCKER
                # history for why defense-in-depth here matters).
                return False
            return client.pod_log_contains(
                namespace, name, template.log_contains, template.label_selector
            )
        if vtype == VerifyType.POD_PHASE_EQUALS:
            if template.expected_phase is None:
                # Fail closed — same reasoning as POD_LOG_CONTAINS above: no
                # phase string has a safe "match everything" fallback value.
                return False
            return client.pod_phase_equals(
                namespace, name, template.expected_phase, template.label_selector
            )
        if vtype == VerifyType.POD_SCHEDULING_UNSCHEDULABLE:
            return client.pod_scheduling_unschedulable(
                namespace, name, template.label_selector, template.message_contains
            )
        raise AssertionError(f"_dispatch called for unsupported type {vtype!r}")  # pragma: no cover
