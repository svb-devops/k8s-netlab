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
    def configmap_exists(self, namespace: str, name: str) -> bool: ...

    @abstractmethod
    def secret_exists(self, namespace: str, name: str) -> bool: ...


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
        responses: Optional[dict] = None,
        default: bool = True,
    ) -> None:
        self._responses: dict = responses or {}
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

    def configmap_exists(self, namespace: str, name: str) -> bool:
        return self._get(("configmap_exists", namespace, name))

    def secret_exists(self, namespace: str, name: str) -> bool:
        return self._get(("secret_exists", namespace, name))


# ---------------------------------------------------------------------------
# Supported verify types
# ---------------------------------------------------------------------------

_SUPPORTED_TYPES: frozenset[VerifyType] = frozenset({
    VerifyType.NAMESPACE_EXISTS,
    VerifyType.POD_RUNNING,
    VerifyType.DEPLOYMENT_READY,
    VerifyType.SERVICE_EXISTS,
    VerifyType.CONFIGMAP_EXISTS,
    VerifyType.SECRET_EXISTS,
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
    ) -> None:
        self._session_repo = session_repo
        self._credential_store = credential_store
        self._k8s_client_factory = k8s_client_factory

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

        if not self._credential_store.exists(session.vm_id):
            return _fail(FailureReason.VERIFIER_CREDENTIAL_MISSING, f"vm_id={session.vm_id}")

        kubeconfig, _ = self._credential_store.load(session.vm_id)
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
        if vtype == VerifyType.CONFIGMAP_EXISTS:
            return client.configmap_exists(namespace, name)
        if vtype == VerifyType.SECRET_EXISTS:
            return client.secret_exists(namespace, name)
        raise AssertionError(f"_dispatch called for unsupported type {vtype!r}")  # pragma: no cover
