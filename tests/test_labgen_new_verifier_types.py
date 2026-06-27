"""
Tests for new VerifyType values: DEPLOYMENT_UNAVAILABLE and NAMESPACE_NOT_EXISTS.

TDD: these tests were written BEFORE implementation — they fail on missing enum
values and missing abstract methods, then pass once the implementation is added.

Covers:
- VerifyType enum values exist
- FakeK8sVerifierClient has deployment_unavailable / namespace_not_exists methods
- _SUPPORTED_TYPES includes the new types
- _dispatch routes correctly for each new type
- VerifierService.check() returns passed=True/False for each new type
- K8sVerifierClientAdapter implements both methods (True/False/404/500 paths)
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest
from kubernetes.client.exceptions import ApiException

from backend.labgen.k8s_verifier_client import K8sVerifierClientAdapter, KubernetesApiFactory
from backend.labgen.models import (
    LabSessionState,
    LabSessionStatus,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.verifier import (
    FakeK8sVerifierClient,
    VerifierService,
    VerifyResult,
    _NS_SENTINEL,
    _SUPPORTED_TYPES,
)
from backend.labgen.verifier_credentials import (
    VerifierCredentialMetadata,
    VerifierCredentialStore,
)

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


class _FakeSessionRepo:
    def __init__(self, sessions: Optional[dict[str, LabSessionState]] = None) -> None:
        self._sessions: dict[str, LabSessionState] = sessions or {}

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._sessions.get(session_id)


def _active_session(
    session_id: str = "sess-abc",
    vm_id: str = "501",
    namespace: str = "lab-sess-abc",
) -> LabSessionState:
    s = LabSessionState(
        session_id=session_id,
        lab_id="lab-1",
        vm_id=vm_id,
        student_username="student1",
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
    )
    s.namespace = namespace
    return s


def _make_store(tmp_dir: Path, vm_id: str = "501") -> VerifierCredentialStore:
    store = VerifierCredentialStore(base_dir=tmp_dir)
    metadata = VerifierCredentialMetadata(
        vm_id=vm_id,
        created_at=datetime.now(tz=timezone.utc),
        expires_at=datetime.now(tz=timezone.utc),
        k3s_endpoint="https://k3s.test:6443",
    )
    store.save(vm_id, _KUBECONFIG, metadata)
    return store


def _make_template(
    verify_id: str = "v1",
    vtype: VerifyType = VerifyType.DEPLOYMENT_UNAVAILABLE,
    namespace: str = _NS_SENTINEL,
    name: str = "crash-demo",
    cluster_scope: bool = False,
) -> VerifyTemplate:
    return VerifyTemplate(
        verify_id=verify_id,
        type=vtype,
        namespace=namespace,
        name=name,
        cluster_scope=cluster_scope,
    )


def _stub_factory(core: MagicMock, apps: MagicMock) -> KubernetesApiFactory:
    factory = MagicMock(spec=KubernetesApiFactory)
    factory.build.return_value = (core, apps)
    return factory


def _adapter(core: MagicMock, apps: MagicMock) -> K8sVerifierClientAdapter:
    return K8sVerifierClientAdapter(_KUBECONFIG, _stub_factory(core, apps))


def _api_404() -> ApiException:
    return ApiException(status=404, reason="Not Found")


def _api_500() -> ApiException:
    return ApiException(status=500, reason="Internal Server Error")


# ---------------------------------------------------------------------------
# VerifyType enum
# ---------------------------------------------------------------------------


def test_verify_type_deployment_unavailable_exists():
    assert VerifyType.DEPLOYMENT_UNAVAILABLE == "deployment_unavailable"


def test_verify_type_namespace_not_exists_exists():
    assert VerifyType.NAMESPACE_NOT_EXISTS == "namespace_not_exists"


# ---------------------------------------------------------------------------
# _SUPPORTED_TYPES
# ---------------------------------------------------------------------------


def test_deployment_unavailable_in_supported_types():
    assert VerifyType.DEPLOYMENT_UNAVAILABLE in _SUPPORTED_TYPES


def test_namespace_not_exists_in_supported_types():
    assert VerifyType.NAMESPACE_NOT_EXISTS in _SUPPORTED_TYPES


# ---------------------------------------------------------------------------
# FakeK8sVerifierClient
# ---------------------------------------------------------------------------


def test_fake_client_deployment_unavailable_default_true():
    client = FakeK8sVerifierClient()
    assert client.deployment_unavailable("ns", "crash-demo") is True


def test_fake_client_deployment_unavailable_configured_false():
    client = FakeK8sVerifierClient({("deployment_unavailable", "ns", "crash-demo"): False})
    assert client.deployment_unavailable("ns", "crash-demo") is False


def test_fake_client_namespace_not_exists_default_true():
    client = FakeK8sVerifierClient()
    assert client.namespace_not_exists("ns") is True


def test_fake_client_namespace_not_exists_configured_false():
    client = FakeK8sVerifierClient({("namespace_not_exists", "ns"): False})
    assert client.namespace_not_exists("ns") is False


# ---------------------------------------------------------------------------
# VerifierService._dispatch via VerifierService.check()
# ---------------------------------------------------------------------------


def test_verifier_service_deployment_unavailable_pass():
    session = _active_session()
    repo = _FakeSessionRepo({"sess-abc": session})
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        # FakeK8sVerifierClient default=True → deployment IS unavailable → passed
        svc = VerifierService(
            session_repo=repo,
            credential_store=store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(default=True),
        )
        tmpl = _make_template(vtype=VerifyType.DEPLOYMENT_UNAVAILABLE, name="crash-demo")
        result = svc.check("sess-abc", tmpl)
    assert result.passed is True
    assert result.verify_type == "deployment_unavailable"


def test_verifier_service_deployment_unavailable_fail():
    session = _active_session()
    repo = _FakeSessionRepo({"sess-abc": session})
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        svc = VerifierService(
            session_repo=repo,
            credential_store=store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(
                responses={("deployment_unavailable", "lab-sess-abc", "crash-demo"): False},
                default=False,
            ),
        )
        tmpl = _make_template(vtype=VerifyType.DEPLOYMENT_UNAVAILABLE, name="crash-demo")
        result = svc.check("sess-abc", tmpl)
    assert result.passed is False


def test_verifier_service_namespace_not_exists_pass():
    session = _active_session()
    repo = _FakeSessionRepo({"sess-abc": session})
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        svc = VerifierService(
            session_repo=repo,
            credential_store=store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(default=True),
        )
        tmpl = _make_template(vtype=VerifyType.NAMESPACE_NOT_EXISTS, name="lab-sess-abc")
        result = svc.check("sess-abc", tmpl)
    assert result.passed is True
    assert result.verify_type == "namespace_not_exists"


def test_verifier_service_namespace_not_exists_fail():
    session = _active_session()
    repo = _FakeSessionRepo({"sess-abc": session})
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        svc = VerifierService(
            session_repo=repo,
            credential_store=store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(
                responses={("namespace_not_exists", "lab-sess-abc"): False},
                default=False,
            ),
        )
        tmpl = _make_template(vtype=VerifyType.NAMESPACE_NOT_EXISTS, name="lab-sess-abc")
        result = svc.check("sess-abc", tmpl)
    assert result.passed is False


# ---------------------------------------------------------------------------
# _make_detail: learner-facing messages
# ---------------------------------------------------------------------------


def test_make_detail_deployment_unavailable_passed():
    session = _active_session()
    repo = _FakeSessionRepo({"sess-abc": session})
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        svc = VerifierService(
            session_repo=repo,
            credential_store=store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(default=True),
        )
        tmpl = _make_template(vtype=VerifyType.DEPLOYMENT_UNAVAILABLE, name="crash-demo")
        result = svc.check("sess-abc", tmpl)
    assert result.detail != ""
    assert "crash-demo" in result.detail or "CrashLoopBackOff" in result.detail or "unavailable" in result.detail.lower()


def test_make_detail_namespace_not_exists_passed():
    session = _active_session()
    repo = _FakeSessionRepo({"sess-abc": session})
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        svc = VerifierService(
            session_repo=repo,
            credential_store=store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(default=True),
        )
        tmpl = _make_template(vtype=VerifyType.NAMESPACE_NOT_EXISTS, name="lab-sess-abc")
        result = svc.check("sess-abc", tmpl)
    assert result.detail != ""


# ---------------------------------------------------------------------------
# K8sVerifierClientAdapter — deployment_unavailable
# ---------------------------------------------------------------------------


def test_adapter_deployment_unavailable_true_when_available_zero():
    apps = MagicMock()
    dep = MagicMock()
    dep.spec.replicas = 1
    dep.status.available_replicas = 0
    apps.list_namespaced_deployment.return_value.items = [dep]
    client = _adapter(MagicMock(), apps)
    assert client.deployment_unavailable("ns", "crash-demo") is True


def test_adapter_deployment_unavailable_true_when_available_none():
    apps = MagicMock()
    dep = MagicMock()
    dep.spec.replicas = 1
    dep.status.available_replicas = None
    apps.list_namespaced_deployment.return_value.items = [dep]
    client = _adapter(MagicMock(), apps)
    assert client.deployment_unavailable("ns", "crash-demo") is True


def test_adapter_deployment_unavailable_false_when_deployment_ready():
    apps = MagicMock()
    dep = MagicMock()
    dep.spec.replicas = 1
    dep.status.available_replicas = 1
    apps.list_namespaced_deployment.return_value.items = [dep]
    client = _adapter(MagicMock(), apps)
    assert client.deployment_unavailable("ns", "crash-demo") is False


def test_adapter_deployment_unavailable_false_when_not_found():
    apps = MagicMock()
    apps.list_namespaced_deployment.return_value.items = []
    client = _adapter(MagicMock(), apps)
    assert client.deployment_unavailable("ns", "crash-demo") is False


def test_adapter_deployment_unavailable_false_on_404():
    apps = MagicMock()
    apps.list_namespaced_deployment.side_effect = _api_404()
    client = _adapter(MagicMock(), apps)
    assert client.deployment_unavailable("ns", "crash-demo") is False


def test_adapter_deployment_unavailable_propagates_500():
    apps = MagicMock()
    apps.list_namespaced_deployment.side_effect = _api_500()
    client = _adapter(MagicMock(), apps)
    with pytest.raises(ApiException):
        client.deployment_unavailable("ns", "crash-demo")


# ---------------------------------------------------------------------------
# K8sVerifierClientAdapter — namespace_not_exists
# ---------------------------------------------------------------------------


def test_adapter_namespace_not_exists_true_on_404():
    core = MagicMock()
    core.list_namespaced_config_map.side_effect = _api_404()
    client = _adapter(core, MagicMock())
    assert client.namespace_not_exists("deleted-ns") is True


def test_adapter_namespace_not_exists_false_when_namespace_exists():
    core = MagicMock()
    core.list_namespaced_config_map.return_value = MagicMock(items=[])
    client = _adapter(core, MagicMock())
    assert client.namespace_not_exists("live-ns") is False


def test_adapter_namespace_not_exists_propagates_500():
    core = MagicMock()
    core.list_namespaced_config_map.side_effect = _api_500()
    client = _adapter(core, MagicMock())
    with pytest.raises(ApiException):
        client.namespace_not_exists("ns")
