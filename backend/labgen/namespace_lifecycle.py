"""
NamespaceLifecyclePort — abstract interface for K8s namespace CRUD.

Separates namespace create/verify/delete from VMTrackerPort.
K3sNamespaceLifecycleAdapter is a skeleton (not yet wired to real K8s).
StubNamespaceLifecycleAdapter is for tests only — no real K8s calls.

Constraint: verifier kubeconfig must NOT be used here.
Namespace management uses the platform kubeconfig (separate credential).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class NamespaceLifecyclePort(ABC):
    @abstractmethod
    def create_namespace(self, namespace: str) -> bool: ...

    @abstractmethod
    def namespace_exists(self, namespace: str) -> bool: ...

    @abstractmethod
    def delete_namespace(self, namespace: str) -> bool: ...

    @abstractmethod
    def is_namespace_deleted(self, namespace: str) -> bool: ...

    @abstractmethod
    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        """Create (idempotent) a RoleBinding in namespace granting lab-verifier read access.

        Subject: kube-system/lab-verifier SA.
        RoleRef: lab-verifier-namespace-readonly ClusterRole.
        Must NOT use verifier kubeconfig — platform kubeconfig only.
        Must NOT create ClusterRoleBinding.
        Returns True when the RoleBinding was applied without error.
        """
        ...

    @abstractmethod
    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        """Confirm the verifier RoleBinding exists in namespace after creation."""
        ...


class StubNamespaceLifecycleAdapter(NamespaceLifecyclePort):
    """Configurable in-process stub.  No real K8s calls.  Tests only."""

    def __init__(
        self,
        create_succeeds: bool = True,
        exists_after_create: bool = True,
        delete_succeeds: bool = True,
        deleted_after_delete: bool = True,
        rolebinding_succeeds: bool = True,
        rolebinding_exists_after_create: bool = True,
    ) -> None:
        self.create_succeeds = create_succeeds
        self.exists_after_create = exists_after_create
        self.delete_succeeds = delete_succeeds
        self.deleted_after_delete = deleted_after_delete
        self.rolebinding_succeeds = rolebinding_succeeds
        self.rolebinding_exists_after_create = rolebinding_exists_after_create
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

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        if self.rolebinding_succeeds:
            self.rolebindings_created.append(namespace)
        return self.rolebinding_succeeds

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        return self.rolebinding_exists_after_create


class K3sNamespaceLifecycleAdapter(NamespaceLifecyclePort):
    """Skeleton — calls K8s API via platform kubeconfig.

    Verifier kubeconfig is reserved for step verification and must not be used here.
    Real implementation pending: requires platform kubeconfig path from config.
    """

    def create_namespace(self, namespace: str) -> bool:
        raise NotImplementedError("K3s namespace lifecycle adapter not yet implemented")

    def namespace_exists(self, namespace: str) -> bool:
        raise NotImplementedError("K3s namespace lifecycle adapter not yet implemented")

    def delete_namespace(self, namespace: str) -> bool:
        raise NotImplementedError("K3s namespace lifecycle adapter not yet implemented")

    def is_namespace_deleted(self, namespace: str) -> bool:
        raise NotImplementedError("K3s namespace lifecycle adapter not yet implemented")

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        raise NotImplementedError("K3s namespace lifecycle adapter not yet implemented")

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        raise NotImplementedError("K3s namespace lifecycle adapter not yet implemented")
