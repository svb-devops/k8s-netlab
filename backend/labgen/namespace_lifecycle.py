"""
NamespaceLifecyclePort — abstract interface for K8s namespace CRUD.

Separates namespace create/verify/delete from VMTrackerPort.
K3sNamespaceLifecycleAdapter is a portable Kubernetes API adapter — it does NOT depend
on Proxmox, T430 paths, or Cloudflare Tunnel.  It works on home-lab K3s today and
migrates unchanged to EKS/ACK/managed K8s later.

StubNamespaceLifecycleAdapter is for tests / dev mode only — never production.

Constraint: verifier kubeconfig must NOT be used here.
Namespace management uses the platform kubeconfig (separate credential).

Portability guarantee:
  - No Proxmox calls in this module.
  - No local filesystem paths beyond what is passed via K8sAdapterConfig.
  - No shell commands (kubectl-free).
  - No hardcoded hostnames, IPs, VMIDs, or home-server paths.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Tuple

from backend.labgen.failure_reasons import FailureReason

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api, RbacAuthorizationV1Api

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Forbidden / reserved Kubernetes system namespaces
# ---------------------------------------------------------------------------

_SYSTEM_NAMESPACES: frozenset[str] = frozenset({
    "default",
    "kube-system",
    "kube-public",
    "kube-node-lease",
})

# Kubernetes DNS label: lowercase alphanumeric + hyphens, start/end alphanumeric.
_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# Characters that are unsafe in namespace names — path chars, shell metacharacters.
_UNSAFE_CHARS: frozenset[str] = frozenset("/\\$`!|&;<>(){}[]*? \t\n")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NamespaceValidationError(ValueError):
    """Raised when a namespace name fails safety validation."""
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class NamespaceAdapterConfigError(RuntimeError):
    """Raised when K8sAdapterConfig is invalid or K8s client cannot be loaded."""
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


# ---------------------------------------------------------------------------
# NamespaceSafetyValidator
# ---------------------------------------------------------------------------


class NamespaceSafetyValidator:
    """Validates namespace names before any K8s API call.

    Rules (all mandatory):
    1. Not empty.
    2. No path characters, shell metacharacters, or whitespace.
    3. Matches Kubernetes DNS label format (^[a-z0-9]([a-z0-9-]*[a-z0-9])?$).
    4. Not a system/reserved namespace (default, kube-*).
    5. Starts with one of the configured allowed prefixes.

    Raises NamespaceValidationError on any violation.
    """

    @classmethod
    def validate(cls, namespace: str, allowed_prefixes: list[str]) -> None:
        if not namespace:
            raise NamespaceValidationError(
                FailureReason.NAMESPACE_INVALID_NAME.value,
                "Namespace must not be empty",
            )
        bad = _UNSAFE_CHARS & set(namespace)
        if bad:
            raise NamespaceValidationError(
                FailureReason.NAMESPACE_INVALID_NAME.value,
                "Namespace contains unsafe characters",
            )
        if not _DNS_LABEL_RE.match(namespace):
            raise NamespaceValidationError(
                FailureReason.NAMESPACE_INVALID_NAME.value,
                f"'{namespace}' is not a valid Kubernetes DNS label",
            )
        if namespace in _SYSTEM_NAMESPACES:
            raise NamespaceValidationError(
                FailureReason.NAMESPACE_INVALID_NAME.value,
                f"'{namespace}' is a reserved system namespace",
            )
        if not any(namespace.startswith(p) for p in allowed_prefixes):
            raise NamespaceValidationError(
                FailureReason.NAMESPACE_INVALID_NAME.value,
                f"Namespace does not start with an allowed prefix",
            )

    @classmethod
    def is_valid_k8s_name(cls, name: str) -> bool:
        """Check that a K8s resource name (SA/role/rolebinding) is safe."""
        if not name:
            return False
        unsafe = _UNSAFE_CHARS & set(name)
        if unsafe:
            return False
        return bool(_DNS_LABEL_RE.match(name))


# ---------------------------------------------------------------------------
# K8sAdapterConfig
# ---------------------------------------------------------------------------


@dataclass
class K8sAdapterConfig:
    """Configuration for K3sNamespaceLifecycleAdapter.

    Portable across K3s (home-lab), EKS, ACK, and any conformant K8s cluster.
    No hardcoded host assumptions.  All values come from env/config injection.
    """

    kubeconfig_path: str = ""
    in_cluster: bool = False
    context: str = ""
    api_timeout_seconds: int = 10
    allowed_namespace_prefixes: list[str] = field(default_factory=lambda: ["lab-"])
    verifier_sa_name: str = "lab-verifier"
    verifier_sa_namespace: str = "kube-system"
    verifier_role_name: str = "lab-verifier-namespace-readonly"
    verifier_rolebinding_name: str = "lab-verifier-readonly"

    def __post_init__(self) -> None:
        if not self.kubeconfig_path and not self.in_cluster:
            raise NamespaceAdapterConfigError(
                FailureReason.NAMESPACE_CONFIG_MISSING.value,
                "K8sAdapterConfig requires either kubeconfig_path or in_cluster=True",
            )
        if self.kubeconfig_path and self.in_cluster:
            raise NamespaceAdapterConfigError(
                FailureReason.NAMESPACE_ADAPTER_CONFIG_UNSAFE.value,
                "K8sAdapterConfig must specify kubeconfig_path or in_cluster, not both",
            )
        if self.api_timeout_seconds < 1:
            raise NamespaceAdapterConfigError(
                FailureReason.NAMESPACE_ADAPTER_CONFIG_UNSAFE.value,
                "api_timeout_seconds must be >= 1",
            )
        if not self.allowed_namespace_prefixes:
            raise NamespaceAdapterConfigError(
                FailureReason.NAMESPACE_ADAPTER_CONFIG_UNSAFE.value,
                "allowed_namespace_prefixes must not be empty",
            )
        for name_field in (
            self.verifier_sa_name,
            self.verifier_sa_namespace,
            self.verifier_role_name,
            self.verifier_rolebinding_name,
        ):
            if not NamespaceSafetyValidator.is_valid_k8s_name(name_field):
                raise NamespaceAdapterConfigError(
                    FailureReason.NAMESPACE_ADAPTER_CONFIG_UNSAFE.value,
                    "K8sAdapterConfig contains an invalid K8s resource name",
                )

    @classmethod
    def from_config(cls) -> "K8sAdapterConfig":
        """Build from the application config module.  No hardcoded defaults beyond config.py."""
        from backend import config as _cfg
        prefixes = [
            p.strip()
            for p in _cfg.LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES.split(",")
            if p.strip()
        ]
        if not prefixes:
            prefixes = ["lab-"]
        return cls(
            kubeconfig_path=_cfg.LABGEN_K8S_PLATFORM_KUBECONFIG_PATH,
            in_cluster=_cfg.LABGEN_K8S_IN_CLUSTER,
            context=_cfg.LABGEN_K8S_CONTEXT,
            api_timeout_seconds=_cfg.LABGEN_K8S_API_TIMEOUT_SECONDS,
            allowed_namespace_prefixes=prefixes,
            verifier_sa_name=_cfg.LABGEN_K8S_VERIFIER_SA_NAME,
            verifier_sa_namespace=_cfg.LABGEN_K8S_VERIFIER_SA_NAMESPACE,
            verifier_role_name=_cfg.LABGEN_K8S_VERIFIER_ROLE_NAME,
            verifier_rolebinding_name=_cfg.LABGEN_K8S_VERIFIER_ROLEBINDING_NAME,
        )


# ---------------------------------------------------------------------------
# PlatformKubernetesClientLoader  (injectable for testing)
# ---------------------------------------------------------------------------


class PlatformKubernetesClientLoader:
    """Constructs (CoreV1Api, RbacAuthorizationV1Api) from K8sAdapterConfig.

    Both API objects share one ApiClient (single connection pool).
    Injectable for testing — replace with a stub that returns mock API objects
    without making any network calls.

    Supports:
    - kubeconfig path (home-lab K3s, any cluster with a kubeconfig file)
    - in-cluster config (cloud-managed K8s: EKS pod, ACK pod, GKE pod)
    Never reads ~/.kube/config or any path not in K8sAdapterConfig.
    Never reads verifier kubeconfig content — that is managed by VerifierCredentialStore.
    """

    def build(
        self, config: K8sAdapterConfig
    ) -> Tuple["CoreV1Api", "RbacAuthorizationV1Api"]:
        from kubernetes import client as k8s_client

        configuration = k8s_client.Configuration()
        try:
            if config.in_cluster:
                from kubernetes.config import load_incluster_config
                load_incluster_config(client_configuration=configuration)
            else:
                from kubernetes.config import load_kube_config
                load_kube_config(
                    config_file=config.kubeconfig_path,
                    context=config.context or None,
                    client_configuration=configuration,
                )
        except Exception as exc:
            raise NamespaceAdapterConfigError(
                FailureReason.NAMESPACE_CONFIG_MISSING.value,
                "Failed to load Kubernetes client configuration",
            ) from exc

        api = k8s_client.ApiClient(configuration=configuration)
        return (
            k8s_client.CoreV1Api(api_client=api),
            k8s_client.RbacAuthorizationV1Api(api_client=api),
        )


# ---------------------------------------------------------------------------
# Error sanitization
# ---------------------------------------------------------------------------


def _sanitize_api_error(exc: Exception) -> str:
    """Return a safe description of a Kubernetes API error.

    Never exposes raw response body, token values, or kubeconfig content.
    Only uses exc.status (int) and exc.reason (string) from ApiException.
    """
    try:
        from kubernetes.client.exceptions import ApiException
        if isinstance(exc, ApiException):
            return f"Kubernetes API error: status={exc.status} reason={exc.reason}"
    except ImportError:
        pass
    return f"Kubernetes error: {type(exc).__name__}"


# ---------------------------------------------------------------------------
# NamespaceLifecyclePort
# ---------------------------------------------------------------------------


class NamespaceLifecyclePort(ABC):
    @abstractmethod
    def create_namespace(self, namespace: str) -> bool: ...

    @abstractmethod
    def namespace_exists(self, namespace: str) -> bool: ...

    @abstractmethod
    def delete_namespace(self, namespace: str) -> bool: ...

    @abstractmethod
    def is_namespace_deleted(self, namespace: str) -> bool: ...

    def is_namespace_stuck_terminating(self, namespace: str, threshold_seconds: int = 300) -> bool:
        """Return True if namespace is in K8s Terminating phase and has been so for
        longer than *threshold_seconds*.

        Returns False when:
        - The namespace does not exist (already deleted).
        - The namespace exists but is NOT in Terminating phase.
        - The namespace entered Terminating less than *threshold_seconds* ago.

        Default implementation returns False (safe for test doubles).
        Production adapters override this method.
        """
        return False

    @abstractmethod
    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        """Create (idempotent) a RoleBinding in namespace granting lab-verifier read access.

        Subject: <verifier_sa_namespace>/<verifier_sa_name> SA.
        RoleRef: <verifier_role_name> ClusterRole.
        Must NOT use verifier kubeconfig — platform kubeconfig only.
        Must NOT create ClusterRoleBinding.
        Returns True when the RoleBinding was applied without error (or already existed).
        """
        ...

    @abstractmethod
    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        """Confirm the verifier RoleBinding exists in namespace after creation."""
        ...


# ---------------------------------------------------------------------------
# StubNamespaceLifecycleAdapter  (tests / dev mode only)
# ---------------------------------------------------------------------------


class StubNamespaceLifecycleAdapter(NamespaceLifecyclePort):
    """Configurable in-process stub.  No real K8s calls.  Tests and dev mode only.

    Must NOT be used in home_lab_mvp, cloud, or production profiles.
    """

    def __init__(
        self,
        create_succeeds: bool = True,
        exists_after_create: bool = True,
        delete_succeeds: bool = True,
        deleted_after_delete: bool = True,
        rolebinding_succeeds: bool = True,
        rolebinding_exists_after_create: bool = True,
        stuck_terminating_namespaces: "set[str] | None" = None,
    ) -> None:
        self.create_succeeds = create_succeeds
        self.exists_after_create = exists_after_create
        self.delete_succeeds = delete_succeeds
        self.deleted_after_delete = deleted_after_delete
        self.rolebinding_succeeds = rolebinding_succeeds
        self.rolebinding_exists_after_create = rolebinding_exists_after_create
        self.stuck_terminating_namespaces: set[str] = stuck_terminating_namespaces or set()
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.rolebindings_created: list[str] = []

    def create_namespace(self, namespace: str) -> bool:
        if self.create_succeeds:
            self.created.append(namespace)
        return self.create_succeeds

    def namespace_exists(self, namespace: str) -> bool:
        return self.exists_after_create

    def delete_namespace(self, namespace: str) -> bool:
        if self.delete_succeeds:
            self.deleted.append(namespace)
        return self.delete_succeeds

    def is_namespace_deleted(self, namespace: str) -> bool:
        return self.deleted_after_delete

    def is_namespace_stuck_terminating(self, namespace: str, threshold_seconds: int = 300) -> bool:
        return namespace in self.stuck_terminating_namespaces

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        if self.rolebinding_succeeds:
            self.rolebindings_created.append(namespace)
        return self.rolebinding_succeeds

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        return self.rolebinding_exists_after_create


# ---------------------------------------------------------------------------
# K3sNamespaceLifecycleAdapter  (portable Kubernetes implementation)
# ---------------------------------------------------------------------------


class K3sNamespaceLifecycleAdapter(NamespaceLifecyclePort):
    """Portable Kubernetes namespace lifecycle adapter.

    Works on:
    - Home-lab K3s (kubeconfig path from LABGEN_K8S_PLATFORM_KUBECONFIG_PATH)
    - AWS EKS (kubeconfig path or in-cluster)
    - Alibaba Cloud ACK (kubeconfig path or in-cluster)
    - Any conformant Kubernetes 1.20+ cluster

    Does NOT depend on:
    - Proxmox or any VM provider
    - T430 or any specific host path
    - Cloudflare Tunnel or any ingress
    - kubectl CLI
    - ~/.kube/config (only reads kubeconfig_path from K8sAdapterConfig)

    Security:
    - All namespace names validated before any API call.
    - Raw Kubernetes exception bodies never exposed to callers or API responses.
    - Verifier kubeconfig not used here — only platform kubeconfig.
    - RoleBinding is namespace-scoped; no ClusterRoleBinding created.
    - Config validation fails fast at construction time.
    """

    def __init__(
        self,
        config: K8sAdapterConfig,
        loader: Optional[PlatformKubernetesClientLoader] = None,
    ) -> None:
        self._config = config  # validated in K8sAdapterConfig.__post_init__
        self._loader = loader or PlatformKubernetesClientLoader()
        self._core_v1: Optional["CoreV1Api"] = None
        self._rbac_v1: Optional["RbacAuthorizationV1Api"] = None

    def _clients(self) -> Tuple["CoreV1Api", "RbacAuthorizationV1Api"]:
        """Lazy-initialize Kubernetes clients on first call.

        Raises NamespaceAdapterConfigError if the kubeconfig cannot be loaded.
        This propagates as a lab start failure (NAMESPACE_CONFIG_MISSING).
        """
        if self._core_v1 is None:
            self._core_v1, self._rbac_v1 = self._loader.build(self._config)
        return self._core_v1, self._rbac_v1  # type: ignore[return-value]

    def _validate(self, namespace: str) -> None:
        NamespaceSafetyValidator.validate(namespace, self._config.allowed_namespace_prefixes)

    def create_namespace(self, namespace: str) -> bool:
        try:
            self._validate(namespace)
        except NamespaceValidationError as exc:
            logger.error("create_namespace rejected namespace: %s", exc)
            return False

        from kubernetes import client as k8s_client
        from kubernetes.client.exceptions import ApiException

        try:
            core_v1, _ = self._clients()
            body = k8s_client.V1Namespace(
                metadata=k8s_client.V1ObjectMeta(name=namespace)
            )
            core_v1.create_namespace(body, _request_timeout=self._config.api_timeout_seconds)
            return True
        except ApiException as exc:
            logger.error("create_namespace API failure: %s", _sanitize_api_error(exc))
            return False
        except NamespaceAdapterConfigError as exc:
            logger.error("create_namespace config error: %s", exc)
            return False
        except Exception as exc:
            logger.error("create_namespace unexpected error: %s", _sanitize_api_error(exc))
            return False

    def namespace_exists(self, namespace: str) -> bool:
        try:
            self._validate(namespace)
        except NamespaceValidationError:
            return False

        from kubernetes.client.exceptions import ApiException

        try:
            core_v1, _ = self._clients()
            core_v1.read_namespace(namespace, _request_timeout=self._config.api_timeout_seconds)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            logger.error("namespace_exists API failure: %s", _sanitize_api_error(exc))
            return False
        except NamespaceAdapterConfigError as exc:
            logger.error("namespace_exists config error: %s", exc)
            return False
        except Exception as exc:
            logger.error("namespace_exists unexpected error: %s", _sanitize_api_error(exc))
            return False

    def delete_namespace(self, namespace: str) -> bool:
        try:
            self._validate(namespace)
        except NamespaceValidationError as exc:
            logger.error("delete_namespace rejected namespace: %s", exc)
            return False

        from kubernetes.client.exceptions import ApiException

        try:
            core_v1, _ = self._clients()
            core_v1.delete_namespace(
                namespace, _request_timeout=self._config.api_timeout_seconds
            )
            return True
        except ApiException as exc:
            if exc.status == 404:
                return True  # already deleted — idempotent success
            logger.error("delete_namespace API failure: %s", _sanitize_api_error(exc))
            return False
        except NamespaceAdapterConfigError as exc:
            logger.error("delete_namespace config error: %s", exc)
            return False
        except Exception as exc:
            logger.error("delete_namespace unexpected error: %s", _sanitize_api_error(exc))
            return False

    def is_namespace_deleted(self, namespace: str) -> bool:
        try:
            self._validate(namespace)
        except NamespaceValidationError:
            return False  # invalid name — cannot confirm deletion safely

        from kubernetes.client.exceptions import ApiException

        try:
            core_v1, _ = self._clients()
            core_v1.read_namespace(namespace, _request_timeout=self._config.api_timeout_seconds)
            return False  # namespace still exists (Active or Terminating)
        except ApiException as exc:
            if exc.status == 404:
                return True  # truly gone
            logger.error("is_namespace_deleted API failure: %s", _sanitize_api_error(exc))
            return False  # unknown state — fail closed (assume not deleted)
        except NamespaceAdapterConfigError as exc:
            logger.error("is_namespace_deleted config error: %s", exc)
            return False
        except Exception as exc:
            logger.error("is_namespace_deleted unexpected error: %s", _sanitize_api_error(exc))
            return False

    def is_namespace_stuck_terminating(
        self, namespace: str, threshold_seconds: int = 300
    ) -> bool:
        """Return True if namespace is Terminating and deletion_timestamp is >= threshold_seconds ago."""
        try:
            self._validate(namespace)
        except NamespaceValidationError:
            return False

        from kubernetes.client.exceptions import ApiException

        try:
            core_v1, _ = self._clients()
            ns = core_v1.read_namespace(
                namespace, _request_timeout=self._config.api_timeout_seconds
            )
            if ns.status is None or ns.status.phase != "Terminating":
                return False
            if ns.metadata is None or ns.metadata.deletion_timestamp is None:
                return False
            elapsed = (
                datetime.now(timezone.utc) - ns.metadata.deletion_timestamp
            ).total_seconds()
            return elapsed >= threshold_seconds
        except ApiException as exc:
            if exc.status == 404:
                return False  # already deleted — not stuck
            logger.error(
                "is_namespace_stuck_terminating API failure: %s", _sanitize_api_error(exc)
            )
            return False  # fail safe: do not claim stuck when state is unknown
        except NamespaceAdapterConfigError as exc:
            logger.error("is_namespace_stuck_terminating config error: %s", exc)
            return False
        except Exception as exc:
            logger.error(
                "is_namespace_stuck_terminating unexpected error: %s", _sanitize_api_error(exc)
            )
            return False

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        """Create the verifier RoleBinding in namespace (idempotent).

        - Subject: ServiceAccount <verifier_sa_namespace>/<verifier_sa_name>
        - RoleRef: ClusterRole <verifier_role_name>  (namespace-scoped binding)
        - Returns True if created or already existed (409).
        - Does NOT create ClusterRoleBinding.
        - Does NOT use verifier kubeconfig.
        """
        try:
            self._validate(namespace)
        except NamespaceValidationError as exc:
            logger.error("ensure_verifier_rolebinding rejected namespace: %s", exc)
            return False

        from kubernetes import client as k8s_client
        from kubernetes.client.exceptions import ApiException

        try:
            _, rbac_v1 = self._clients()
            # V1Subject was renamed to RbacV1Subject in kubernetes-client/python 26+
            SubjectClass = getattr(k8s_client, "RbacV1Subject", None) or getattr(
                k8s_client, "V1Subject"
            )
            rb = k8s_client.V1RoleBinding(
                metadata=k8s_client.V1ObjectMeta(
                    name=self._config.verifier_rolebinding_name,
                    namespace=namespace,
                ),
                subjects=[
                    SubjectClass(
                        kind="ServiceAccount",
                        name=self._config.verifier_sa_name,
                        namespace=self._config.verifier_sa_namespace,
                    )
                ],
                role_ref=k8s_client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io",
                    kind="ClusterRole",
                    name=self._config.verifier_role_name,
                ),
            )
            rbac_v1.create_namespaced_role_binding(
                namespace, rb, _request_timeout=self._config.api_timeout_seconds
            )
            return True
        except ApiException as exc:
            if exc.status == 409:
                return True  # already exists — idempotent success
            logger.error(
                "ensure_verifier_rolebinding API failure: %s", _sanitize_api_error(exc)
            )
            return False
        except NamespaceAdapterConfigError as exc:
            logger.error("ensure_verifier_rolebinding config error: %s", exc)
            return False
        except Exception as exc:
            logger.error(
                "ensure_verifier_rolebinding unexpected error: %s", _sanitize_api_error(exc)
            )
            return False

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        try:
            self._validate(namespace)
        except NamespaceValidationError:
            return False

        from kubernetes.client.exceptions import ApiException

        try:
            _, rbac_v1 = self._clients()
            rbac_v1.read_namespaced_role_binding(
                self._config.verifier_rolebinding_name,
                namespace,
                _request_timeout=self._config.api_timeout_seconds,
            )
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            logger.error(
                "verifier_rolebinding_exists API failure: %s", _sanitize_api_error(exc)
            )
            return False
        except NamespaceAdapterConfigError as exc:
            logger.error("verifier_rolebinding_exists config error: %s", exc)
            return False
        except Exception as exc:
            logger.error(
                "verifier_rolebinding_exists unexpected error: %s", _sanitize_api_error(exc)
            )
            return False


# ---------------------------------------------------------------------------
# LinuxContainerLifecycleAdapter  (spike skeleton — NOT production-ready)
# ---------------------------------------------------------------------------


class LinuxContainerLifecycleAdapter(NamespaceLifecyclePort):
    """Skeleton adapter for the Linux domain proof (Task 2 of 7).

    Maps the NamespaceLifecyclePort interface to Linux workspace concepts for
    adapter-selection compatibility.  All methods raise NotImplementedError
    because Linux workspace lifecycle is handled by LinuxRuntimeAdapter, not
    through K8s namespace semantics.

    This class exists to:
    1. Prove NamespaceAdapterKind.LINUX can be selected and instantiated.
    2. Confirm K8s adapter selection is unchanged when kind=K8S.
    3. Unblock Tasks 3-7 (verifier, lab template, rehearsal, publish gate).

    NOT learner-visible.  NOT production-ready.  Linux lab publish remains
    blocked by StaticValidator.linux.publish_blocked_until_runtime.
    """

    def create_namespace(self, namespace: str) -> bool:
        raise NotImplementedError(
            "LinuxContainerLifecycleAdapter.create_namespace: "
            "Linux domain does not use K8s namespaces. "
            "Use LinuxRuntimeAdapter.create_session() instead."
        )

    def namespace_exists(self, namespace: str) -> bool:
        raise NotImplementedError(
            "LinuxContainerLifecycleAdapter.namespace_exists: not implemented in spike."
        )

    def delete_namespace(self, namespace: str) -> bool:
        raise NotImplementedError(
            "LinuxContainerLifecycleAdapter.delete_namespace: "
            "Linux cleanup is handled by LinuxRuntimeAdapter.close_session()."
        )

    def is_namespace_deleted(self, namespace: str) -> bool:
        raise NotImplementedError(
            "LinuxContainerLifecycleAdapter.is_namespace_deleted: not implemented in spike."
        )

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        raise NotImplementedError(
            "LinuxContainerLifecycleAdapter.ensure_verifier_rolebinding: "
            "Linux verifier credentials are not implemented in Task 2. "
            "LinuxVerifierClientPort is a future task (Task 4)."
        )

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        raise NotImplementedError(
            "LinuxContainerLifecycleAdapter.verifier_rolebinding_exists: not implemented."
        )
