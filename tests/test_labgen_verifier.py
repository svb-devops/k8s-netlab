"""
Tests for backend/labgen/verifier.py — VerifierService, FakeK8sVerifierClient,
VerifyResult, and the POST /internal/verifier/check HTTP endpoint.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

from backend.labgen.models import (
    LabSessionState,
    LabSessionStatus,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.verifier import (
    FakeK8sVerifierClient,
    K8sVerifierClientPort,
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


class _FakeSessionRepo:
    """Minimal in-memory session repo for VerifierService tests."""

    def __init__(self, sessions: Optional[dict[str, LabSessionState]] = None) -> None:
        self._sessions: dict[str, LabSessionState] = sessions or {}

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._sessions.get(session_id)


def _active_session(
    session_id: str = "sess-abc",
    vm_id: str = "501",
    namespace: str = "lab-sess-abc",
    status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
) -> LabSessionState:
    s = LabSessionState(
        session_id=session_id,
        lab_id="lab-1",
        vm_id=vm_id,
        student_username="student1",
        lab_session_status=status,
    )
    s.namespace = namespace
    return s


def _make_store(tmp_dir: Path, vm_id: str = "501") -> VerifierCredentialStore:
    """Create a VerifierCredentialStore with one seeded credential."""
    store = VerifierCredentialStore(base_dir=tmp_dir)
    kubeconfig = (
        "apiVersion: v1\n"
        "kind: Config\n"
        "clusters:\n"
        "- cluster:\n"
        "    server: https://k3s.test:6443\n"
        "    certificate-authority-data: dGVzdA==\n"
        "  name: k3s-lab\n"
        "users:\n"
        "- name: lab-verifier\n"
        "  user:\n"
        "    token: test-token-xyz\n"
    )
    metadata = VerifierCredentialMetadata(
        vm_id=vm_id,
        created_at=datetime.now(tz=timezone.utc),
        expires_at=datetime.now(tz=timezone.utc),
        k3s_endpoint="https://k3s.test:6443",
    )
    store.save(vm_id, kubeconfig, metadata)
    return store


def _make_template(
    verify_id: str = "v1",
    vtype: VerifyType = VerifyType.NAMESPACE_EXISTS,
    namespace: str = _NS_SENTINEL,
    name: str = "placeholder",
    cluster_scope: bool = False,
    label_selector: Optional[str] = None,
    log_contains: Optional[str] = None,
    expected_phase: Optional[str] = None,
    message_contains: Optional[str] = None,
) -> VerifyTemplate:
    return VerifyTemplate(
        verify_id=verify_id,
        type=vtype,
        namespace=namespace,
        name=name,
        cluster_scope=cluster_scope,
        label_selector=label_selector,
        log_contains=log_contains,
        expected_phase=expected_phase,
        message_contains=message_contains,
    )


def _make_service(
    sessions: dict,
    store: VerifierCredentialStore,
    fake_client: Optional[FakeK8sVerifierClient] = None,
) -> VerifierService:
    if fake_client is None:
        fake_client = FakeK8sVerifierClient()
    return VerifierService(
        session_repo=_FakeSessionRepo(sessions),
        credential_store=store,
        k8s_client_factory=lambda _kc: fake_client,
    )


# ===========================================================================
# VerifyResult model
# ===========================================================================


class TestVerifyResultModel:
    def test_schema_version_default(self) -> None:
        r = VerifyResult(session_id="s", verify_id="v", verify_type="namespace_exists", passed=True)
        assert r.schema_version == "1.0"

    def test_error_code_optional(self) -> None:
        r = VerifyResult(session_id="s", verify_id="v", verify_type="namespace_exists", passed=True)
        assert r.error_code is None
        assert r.detail == ""

    def test_failed_result_carries_error_code(self) -> None:
        r = VerifyResult(
            session_id="s",
            verify_id="v",
            verify_type="namespace_exists",
            passed=False,
            error_code="session_not_found",
        )
        assert not r.passed
        assert r.error_code == "session_not_found"


# ===========================================================================
# FakeK8sVerifierClient
# ===========================================================================


class TestFakeK8sVerifierClient:
    def test_default_true(self) -> None:
        c = FakeK8sVerifierClient(default=True)
        assert c.namespace_exists("any-ns") is True
        assert c.pod_running("any-ns", "any-pod") is True
        assert c.deployment_ready("any-ns", "any-deploy") is True
        assert c.service_exists("any-ns", "any-svc") is True
        assert c.service_has_endpoints("any-ns", "any-svc") is True
        assert c.configmap_exists("any-ns", "any-cm") is True
        assert c.secret_exists("any-ns", "any-secret") is True

    def test_default_false(self) -> None:
        c = FakeK8sVerifierClient(default=False)
        assert c.namespace_exists("any-ns") is False
        assert c.pod_running("any-ns", "any-pod") is False

    def test_per_key_namespace_exists(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("namespace_exists", "lab-abc"): False},
            default=True,
        )
        assert c.namespace_exists("lab-abc") is False
        assert c.namespace_exists("lab-other") is True

    def test_per_key_pod_running(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("pod_running", "lab-ns", "my-pod"): False},
        )
        assert c.pod_running("lab-ns", "my-pod") is False
        assert c.pod_running("lab-ns", "other-pod") is True

    def test_per_key_deployment_ready(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("deployment_ready", "lab-ns", "nginx"): False},
        )
        assert c.deployment_ready("lab-ns", "nginx") is False

    def test_per_key_service_exists(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("service_exists", "lab-ns", "my-svc"): False},
        )
        assert c.service_exists("lab-ns", "my-svc") is False

    def test_per_key_service_has_endpoints(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("service_has_endpoints", "lab-ns", "web-svc"): False},
        )
        assert c.service_has_endpoints("lab-ns", "web-svc") is False
        assert c.service_has_endpoints("lab-ns", "other-svc") is True

    def test_per_key_configmap_exists(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("configmap_exists", "lab-ns", "app-config"): False},
        )
        assert c.configmap_exists("lab-ns", "app-config") is False

    def test_per_key_secret_exists(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("secret_exists", "lab-ns", "tls-cert"): False},
        )
        assert c.secret_exists("lab-ns", "tls-cert") is False

    def test_pod_running_label_selector_ignored_in_lookup(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("pod_running", "lab-ns", "app"): True},
        )
        assert c.pod_running("lab-ns", "app", label_selector="app=nginx") is True
        assert c.pod_running("lab-ns", "app", label_selector=None) is True

    def test_is_k8s_client_port_subclass(self) -> None:
        assert issubclass(FakeK8sVerifierClient, K8sVerifierClientPort)

    def test_per_key_pod_succeeded(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("pod_succeeded", "lab-ns", "dns-check"): False},
        )
        assert c.pod_succeeded("lab-ns", "dns-check") is False
        assert c.pod_succeeded("lab-ns", "other-pod") is True

    def test_per_key_pod_log_contains(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("pod_log_contains", "lab-ns", "dns-check", "SERVICE_FQDN_RESOLVED"): False},
        )
        assert c.pod_log_contains("lab-ns", "dns-check", "SERVICE_FQDN_RESOLVED") is False
        assert c.pod_log_contains("lab-ns", "dns-check", "OTHER_MARKER") is True

    def test_per_key_pod_phase_equals(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("pod_phase_equals", "lab-ns", "demo", "Pending"): False},
        )
        assert c.pod_phase_equals("lab-ns", "demo", "Pending") is False
        assert c.pod_phase_equals("lab-ns", "demo", "Running") is True

    def test_per_key_pod_scheduling_unschedulable(self) -> None:
        c = FakeK8sVerifierClient(
            responses={("pod_scheduling_unschedulable", "lab-ns", "demo", "node affinity/selector"): False},
        )
        assert c.pod_scheduling_unschedulable("lab-ns", "demo", message_contains="node affinity/selector") is False
        assert c.pod_scheduling_unschedulable("lab-ns", "demo", message_contains="other") is True


# ===========================================================================
# VerifierService — guard checks
# ===========================================================================


class TestVerifierServiceGuards:
    def setup_method(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._store = _make_store(Path(self._tmp))

    def test_session_not_found(self) -> None:
        svc = _make_service({}, self._store)
        result = svc.check("missing-id", _make_template())
        assert not result.passed
        assert result.error_code == "session_not_found"
        assert result.session_id == "missing-id"

    def test_session_not_active_start_failed(self) -> None:
        s = _active_session(status=LabSessionStatus.LAB_START_FAILED)
        svc = _make_service({s.session_id: s}, self._store)
        result = svc.check(s.session_id, _make_template())
        assert not result.passed
        assert result.error_code == "session_not_active"
        assert "LAB_START_FAILED" in result.detail

    def test_session_not_active_namespace_creating(self) -> None:
        s = _active_session(status=LabSessionStatus.NAMESPACE_CREATING)
        svc = _make_service({s.session_id: s}, self._store)
        result = svc.check(s.session_id, _make_template())
        assert not result.passed
        assert result.error_code == "session_not_active"

    def test_session_not_active_lab_aborted(self) -> None:
        s = _active_session(status=LabSessionStatus.LAB_ABORTED)
        svc = _make_service({s.session_id: s}, self._store)
        result = svc.check(s.session_id, _make_template())
        assert not result.passed
        assert result.error_code == "session_not_active"

    def test_cluster_scope_rejected(self) -> None:
        s = _active_session()
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(cluster_scope=True)
        result = svc.check(s.session_id, t)
        assert not result.passed
        assert result.error_code == "cluster_scope_not_supported"

    def test_namespace_mismatch_different_ns(self) -> None:
        s = _active_session(namespace="lab-real-ns")
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(namespace="lab-attacker-ns")
        result = svc.check(s.session_id, t)
        assert not result.passed
        assert result.error_code == "namespace_mismatch"

    def test_namespace_mismatch_kube_system_rejected(self) -> None:
        s = _active_session(namespace="lab-real-ns")
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(namespace="kube-system")
        result = svc.check(s.session_id, t)
        assert not result.passed
        assert result.error_code == "namespace_mismatch"

    def test_namespace_mismatch_when_session_namespace_is_none(self) -> None:
        s = _active_session()
        s.namespace = None
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(namespace=_NS_SENTINEL)
        result = svc.check(s.session_id, t)
        assert not result.passed
        assert result.error_code == "namespace_mismatch"

    def test_verify_type_not_implemented_pod_ready(self) -> None:
        s = _active_session()
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(vtype=VerifyType.POD_READY)
        result = svc.check(s.session_id, t)
        assert not result.passed
        assert result.error_code == "verify_type_not_implemented"

    def test_verify_type_not_implemented_node_ready(self) -> None:
        s = _active_session()
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(vtype=VerifyType.NODE_READY)
        result = svc.check(s.session_id, t)
        assert not result.passed
        assert result.error_code == "verify_type_not_implemented"

    def test_verify_type_not_implemented_pvc_bound(self) -> None:
        s = _active_session()
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(vtype=VerifyType.PVC_BOUND)
        result = svc.check(s.session_id, t)
        assert not result.passed
        assert result.error_code == "verify_type_not_implemented"

    def test_verify_type_not_implemented_job_completed(self) -> None:
        s = _active_session()
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(vtype=VerifyType.JOB_COMPLETED)
        result = svc.check(s.session_id, t)
        assert not result.passed
        assert result.error_code == "verify_type_not_implemented"

    def test_credential_missing(self) -> None:
        empty_store = VerifierCredentialStore(base_dir=Path(self._tmp) / "empty")
        s = _active_session(vm_id="502")
        svc = _make_service({s.session_id: s}, empty_store)
        result = svc.check(s.session_id, _make_template())
        assert not result.passed
        assert result.error_code == "credential_missing"
        assert "502" in result.detail


# ===========================================================================
# VerifierService — verifier_vm_id pin (shared platform cluster)
#
# Regression: K8s-domain sessions always run their kubectl terminal against
# the shared platform K3s cluster (LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is a
# single global config value, not looked up per session.vm_id — see
# lab_kubectl_ws.py). But VerifierService.check() looked up credentials by
# session.vm_id, which is the student's own per-quota VM number (e.g. "500"
# from the legacy 500-599 pool) — a number that never has its own verifier
# credentials provisioned (only the shared platform VM(s) do). Any session
# whose vm_id isn't one of those shared VMs would always fail verify with
# credential_missing, even though the learner's own kubectl commands were
# genuinely succeeding against the real cluster. This went undetected
# because the "no VM assigned" precheck used to block brand-new users
# before they ever reached a verify call; P0 Reader Path Repair's
# auto-provisioning let new users past that gate for the first time,
# exposing this pre-existing gap.
# ===========================================================================


class TestVerifierServicePinnedVmId:
    def setup_method(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def test_pinned_vm_id_used_instead_of_session_vm_id(self) -> None:
        """A session with vm_id="500" (student's own quota VM, no credentials
        provisioned) must still succeed when verifier_vm_id="401" (the shared
        platform VM) is configured — credentials are looked up by the pinned
        value, not session.vm_id."""
        store = _make_store(Path(self._tmp), vm_id="401")
        s = _active_session(vm_id="500")
        svc = VerifierService(
            session_repo=_FakeSessionRepo({s.session_id: s}),
            credential_store=store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(),
            verifier_vm_id="401",
        )
        result = svc.check(s.session_id, _make_template())
        assert result.passed
        assert result.error_code is None

    def test_without_pin_falls_back_to_session_vm_id(self) -> None:
        """Backward compatible default: verifier_vm_id=None (or omitted)
        preserves the original per-session-vm_id lookup behavior."""
        store = _make_store(Path(self._tmp), vm_id="501")
        s = _active_session(vm_id="501")
        svc = VerifierService(
            session_repo=_FakeSessionRepo({s.session_id: s}),
            credential_store=store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(),
        )
        result = svc.check(s.session_id, _make_template())
        assert result.passed

    def test_pin_set_but_session_vm_id_differs_still_fails_closed_if_pin_missing(self) -> None:
        """If the pinned VM itself has no credentials (misconfiguration),
        this must fail closed with credential_missing referencing the pinned
        id, not silently fall back to session.vm_id."""
        empty_store = VerifierCredentialStore(base_dir=Path(self._tmp) / "empty")
        s = _active_session(vm_id="500")
        svc = VerifierService(
            session_repo=_FakeSessionRepo({s.session_id: s}),
            credential_store=empty_store,
            k8s_client_factory=lambda _kc: FakeK8sVerifierClient(),
            verifier_vm_id="401",
        )
        result = svc.check(s.session_id, _make_template())
        assert not result.passed
        assert result.error_code == "credential_missing"
        assert "401" in result.detail


# ===========================================================================
# VerifierService — namespace resolution
# ===========================================================================


class TestVerifierServiceNamespaceResolution:
    def setup_method(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._store = _make_store(Path(self._tmp))

    def test_sentinel_resolves_to_session_namespace(self) -> None:
        s = _active_session(namespace="lab-my-session-id")
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(namespace=_NS_SENTINEL)
        result = svc.check(s.session_id, t)
        assert result.passed
        assert result.error_code is None

    def test_exact_namespace_match_accepted(self) -> None:
        s = _active_session(namespace="lab-my-session-id")
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(namespace="lab-my-session-id")
        result = svc.check(s.session_id, t)
        assert result.passed
        assert result.error_code is None


# ===========================================================================
# VerifierService — dispatch to supported types
# ===========================================================================


class TestVerifierServiceDispatch:
    def setup_method(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._store = _make_store(Path(self._tmp))
        self._session = _active_session(namespace="lab-test-ns")

    def _svc(self, fake: FakeK8sVerifierClient) -> VerifierService:
        return _make_service({self._session.session_id: self._session}, self._store, fake)

    def test_namespace_exists_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.NAMESPACE_EXISTS),
        )
        assert result.passed
        assert result.verify_type == "namespace_exists"

    def test_namespace_exists_false(self) -> None:
        result = self._svc(
            FakeK8sVerifierClient({("namespace_exists", "lab-test-ns"): False})
        ).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.NAMESPACE_EXISTS),
        )
        assert not result.passed

    def test_pod_running_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.POD_RUNNING, name="my-app"),
        )
        assert result.passed
        assert result.verify_type == "pod_running"

    def test_pod_running_false(self) -> None:
        result = self._svc(
            FakeK8sVerifierClient({("pod_running", "lab-test-ns", "my-app"): False})
        ).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.POD_RUNNING, name="my-app"),
        )
        assert not result.passed

    def test_pod_running_with_label_selector(self) -> None:
        fake = FakeK8sVerifierClient(
            responses={("pod_running", "lab-test-ns", "labeled-pod"): True},
        )
        result = self._svc(fake).check(
            self._session.session_id,
            _make_template(
                vtype=VerifyType.POD_RUNNING,
                name="labeled-pod",
                label_selector="app=nginx",
            ),
        )
        assert result.passed

    def test_deployment_ready_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.DEPLOYMENT_READY, name="my-deploy"),
        )
        assert result.passed

    def test_deployment_ready_false(self) -> None:
        result = self._svc(
            FakeK8sVerifierClient({("deployment_ready", "lab-test-ns", "my-deploy"): False})
        ).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.DEPLOYMENT_READY, name="my-deploy"),
        )
        assert not result.passed

    def test_service_exists_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.SERVICE_EXISTS, name="nginx-svc"),
        )
        assert result.passed

    def test_service_has_endpoints_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.SERVICE_HAS_ENDPOINTS, name="web-svc"),
        )
        assert result.passed
        assert result.verify_type == "service_has_endpoints"

    def test_service_has_endpoints_false(self) -> None:
        result = self._svc(
            FakeK8sVerifierClient({("service_has_endpoints", "lab-test-ns", "web-svc"): False})
        ).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.SERVICE_HAS_ENDPOINTS, name="web-svc"),
        )
        assert not result.passed

    def test_configmap_exists_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.CONFIGMAP_EXISTS, name="app-config"),
        )
        assert result.passed

    def test_secret_exists_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.SECRET_EXISTS, name="tls-cert"),
        )
        assert result.passed

    def test_pod_succeeded_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.POD_SUCCEEDED, name="dns-check"),
        )
        assert result.passed
        assert result.verify_type == "pod_succeeded"

    def test_pod_succeeded_false(self) -> None:
        result = self._svc(
            FakeK8sVerifierClient({("pod_succeeded", "lab-test-ns", "dns-check"): False})
        ).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.POD_SUCCEEDED, name="dns-check"),
        )
        assert not result.passed

    def test_pod_log_contains_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(
                vtype=VerifyType.POD_LOG_CONTAINS,
                name="dns-check",
                log_contains="SERVICE_FQDN_RESOLVED",
            ),
        )
        assert result.passed
        assert result.verify_type == "pod_log_contains"

    def test_pod_log_contains_false(self) -> None:
        result = self._svc(
            FakeK8sVerifierClient(
                {("pod_log_contains", "lab-test-ns", "dns-check", "SERVICE_FQDN_RESOLVED"): False}
            )
        ).check(
            self._session.session_id,
            _make_template(
                vtype=VerifyType.POD_LOG_CONTAINS,
                name="dns-check",
                log_contains="SERVICE_FQDN_RESOLVED",
            ),
        )
        assert not result.passed

    def test_pod_phase_equals_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.POD_PHASE_EQUALS, name="demo", expected_phase="Pending"),
        )
        assert result.passed
        assert result.verify_type == "pod_phase_equals"

    def test_pod_phase_equals_false(self) -> None:
        result = self._svc(
            FakeK8sVerifierClient({("pod_phase_equals", "lab-test-ns", "demo", "Pending"): False})
        ).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.POD_PHASE_EQUALS, name="demo", expected_phase="Pending"),
        )
        assert not result.passed

    def test_pod_phase_equals_missing_expected_phase_fails_closed(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.POD_PHASE_EQUALS, name="demo", expected_phase=None),
        )
        assert not result.passed

    def test_pod_scheduling_unschedulable_true(self) -> None:
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(
                vtype=VerifyType.POD_SCHEDULING_UNSCHEDULABLE,
                name="demo",
                message_contains="node affinity/selector",
            ),
        )
        assert result.passed
        assert result.verify_type == "pod_scheduling_unschedulable"

    def test_pod_scheduling_unschedulable_false(self) -> None:
        result = self._svc(
            FakeK8sVerifierClient(
                {("pod_scheduling_unschedulable", "lab-test-ns", "demo", "node affinity/selector"): False}
            )
        ).check(
            self._session.session_id,
            _make_template(
                vtype=VerifyType.POD_SCHEDULING_UNSCHEDULABLE,
                name="demo",
                message_contains="node affinity/selector",
            ),
        )
        assert not result.passed

    def test_pod_scheduling_unschedulable_without_message_contains(self) -> None:
        # message_contains is genuinely optional for this type.
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(vtype=VerifyType.POD_SCHEDULING_UNSCHEDULABLE, name="demo"),
        )
        assert result.passed

    def test_pod_log_contains_missing_log_contains_fails_closed(self) -> None:
        # Regression: log_contains=None must not be dispatched as "" — an empty
        # substring is contained in every string, so falling back to "" would
        # make this verify type silently always pass instead of always fail.
        result = self._svc(FakeK8sVerifierClient(default=True)).check(
            self._session.session_id,
            _make_template(
                vtype=VerifyType.POD_LOG_CONTAINS,
                name="dns-check",
                log_contains=None,
            ),
        )
        assert not result.passed


# ===========================================================================
# VerifierService — result fields
# ===========================================================================


class TestVerifierServiceResultFields:
    def setup_method(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._store = _make_store(Path(self._tmp))

    def test_verify_id_preserved_in_success(self) -> None:
        s = _active_session()
        svc = _make_service({s.session_id: s}, self._store)
        t = _make_template(verify_id="check-001")
        result = svc.check(s.session_id, t)
        assert result.verify_id == "check-001"

    def test_verify_id_preserved_in_failure(self) -> None:
        svc = _make_service({}, self._store)
        t = _make_template(verify_id="check-002")
        result = svc.check("no-such-session", t)
        assert result.verify_id == "check-002"

    def test_session_id_in_result(self) -> None:
        s = _active_session(session_id="my-unique-session")
        svc = _make_service({s.session_id: s}, self._store)
        result = svc.check("my-unique-session", _make_template())
        assert result.session_id == "my-unique-session"

    def test_success_has_no_error_code(self) -> None:
        s = _active_session()
        svc = _make_service({s.session_id: s}, self._store)
        result = svc.check(s.session_id, _make_template())
        assert result.error_code is None
        # detail is populated with a learner-facing message on dispatch-path success
        assert result.detail != ""


# ===========================================================================
# _make_detail — learner-facing messages
# ===========================================================================


class TestMakeDetail:
    """VerifierService._make_detail produces learner-facing messages for dispatch results.

    Security invariant: must never include session.namespace (tested separately
    in TestVerifierDetailSafetyRC in test_labgen_production_readiness_rc.py).
    """

    def _svc(self, tmp_path, default_pass: bool = True) -> tuple:
        store = _make_store(tmp_path)
        session = _active_session()
        fake = FakeK8sVerifierClient(default=default_pass)
        svc = _make_service({session.session_id: session}, store, fake)
        return svc, session

    def test_namespace_exists_pass_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=True)
        result = svc.check(session.session_id, _make_template(vtype=VerifyType.NAMESPACE_EXISTS))
        assert result.passed is True
        assert "namespace" in result.detail.lower()
        assert result.detail != ""

    def test_namespace_exists_fail_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=False)
        result = svc.check(session.session_id, _make_template(vtype=VerifyType.NAMESPACE_EXISTS))
        assert result.passed is False
        assert result.detail != ""
        assert result.error_code is None  # dispatch failure, not a security failure

    def test_configmap_exists_pass_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=True)
        tmpl = _make_template(vtype=VerifyType.CONFIGMAP_EXISTS, name="my-app-config")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is True
        assert "my-app-config" in result.detail
        assert "found" in result.detail.lower()

    def test_configmap_exists_fail_detail_contains_hint(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=False)
        tmpl = _make_template(vtype=VerifyType.CONFIGMAP_EXISTS, name="my-app-config")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is False
        assert "my-app-config" in result.detail
        assert result.detail != ""

    def test_secret_exists_pass_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=True)
        tmpl = _make_template(vtype=VerifyType.SECRET_EXISTS, name="my-secret")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is True
        assert "my-secret" in result.detail
        assert "without reading its value" in result.detail

    def test_secret_exists_fail_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=False)
        tmpl = _make_template(vtype=VerifyType.SECRET_EXISTS, name="my-secret")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is False
        assert "my-secret" in result.detail
        assert result.detail != ""

    def test_pod_running_pass_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=True)
        tmpl = _make_template(vtype=VerifyType.POD_RUNNING, name="my-pod")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is True
        assert "my-pod" in result.detail

    def test_deployment_ready_pass_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=True)
        tmpl = _make_template(vtype=VerifyType.DEPLOYMENT_READY, name="my-deploy")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is True
        assert "my-deploy" in result.detail
        assert "available" in result.detail
        assert "replica" in result.detail
        assert "Pod" in result.detail

    def test_deployment_ready_fail_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=False)
        tmpl = _make_template(vtype=VerifyType.DEPLOYMENT_READY, name="my-deploy")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is False
        assert "my-deploy" in result.detail
        assert "not ready" in result.detail
        assert "approved image" in result.detail
        assert "short time" in result.detail

    def test_service_exists_pass_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=True)
        tmpl = _make_template(vtype=VerifyType.SERVICE_EXISTS, name="my-svc")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is True
        assert "my-svc" in result.detail

    def test_service_has_endpoints_pass_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=True)
        tmpl = _make_template(vtype=VerifyType.SERVICE_HAS_ENDPOINTS, name="web-svc")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is True
        assert "web-svc" in result.detail

    def test_service_has_endpoints_fail_detail(self, tmp_path: Path) -> None:
        svc, session = self._svc(tmp_path, default_pass=False)
        tmpl = _make_template(vtype=VerifyType.SERVICE_HAS_ENDPOINTS, name="web-svc")
        result = svc.check(session.session_id, tmpl)
        assert result.passed is False
        assert "web-svc" in result.detail
        assert "kubectl get endpoints" in result.detail
        assert "describe service" in result.detail

    def test_security_fail_paths_no_detail(self, tmp_path: Path) -> None:
        """_fail() paths (session_not_found, not_active, etc.) must keep detail=""."""
        store = _make_store(tmp_path)
        svc = _make_service({}, store)  # empty sessions → not_found

        result = svc.check("nonexistent-session", _make_template())
        assert result.passed is False
        assert result.detail == ""  # _fail() path stays empty

    def test_security_fail_cluster_scope_no_detail(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        session = _active_session()
        svc = _make_service({session.session_id: session}, store)
        tmpl = _make_template(cluster_scope=True)
        result = svc.check(session.session_id, tmpl)
        assert result.passed is False
        assert result.detail == ""  # cluster_scope rejection stays empty

    def test_detail_never_contains_resolved_namespace(self, tmp_path: Path) -> None:
        """Regression: detail must not expose session.namespace."""
        store = _make_store(tmp_path)
        session = _active_session(namespace="lab-private-ns-xyz")
        svc = _make_service({session.session_id: session}, store)
        result = svc.check(session.session_id, _make_template(vtype=VerifyType.NAMESPACE_EXISTS))
        assert "lab-private-ns-xyz" not in result.detail


# ===========================================================================
# _SUPPORTED_TYPES coverage
# ===========================================================================


class TestSupportedTypesSet:
    def test_supported_types_count(self) -> None:
        # 6 original + 2 for CrashLoopBackOff/cleanup + 1 for service_has_endpoints
        # + 3 for ConfigMap-not-effective (configmap_value_equals,
        # deployment_restart_triggered, deployment_restart_not_triggered)
        # + 2 for DNS Service Discovery (pod_succeeded, pod_log_contains)
        # + 2 for Pod Pending (pod_phase_equals, pod_scheduling_unschedulable)
        assert len(_SUPPORTED_TYPES) == 16
        assert VerifyType.POD_SUCCEEDED in _SUPPORTED_TYPES
        assert VerifyType.POD_LOG_CONTAINS in _SUPPORTED_TYPES
        assert VerifyType.POD_PHASE_EQUALS in _SUPPORTED_TYPES
        assert VerifyType.POD_SCHEDULING_UNSCHEDULABLE in _SUPPORTED_TYPES
        assert VerifyType.DEPLOYMENT_UNAVAILABLE in _SUPPORTED_TYPES
        assert VerifyType.NAMESPACE_NOT_EXISTS in _SUPPORTED_TYPES
        assert VerifyType.SERVICE_HAS_ENDPOINTS in _SUPPORTED_TYPES
        assert VerifyType.CONFIGMAP_VALUE_EQUALS in _SUPPORTED_TYPES
        assert VerifyType.DEPLOYMENT_RESTART_TRIGGERED in _SUPPORTED_TYPES
        assert VerifyType.DEPLOYMENT_RESTART_NOT_TRIGGERED in _SUPPORTED_TYPES

    def test_shell_not_supported(self) -> None:
        unsupported = {
            VerifyType.POD_READY,
            VerifyType.NODE_READY,
            VerifyType.PVC_BOUND,
            VerifyType.JOB_COMPLETED,
        }
        assert unsupported.isdisjoint(_SUPPORTED_TYPES)


# ===========================================================================
# HTTP endpoint — POST /internal/verifier/check
# ===========================================================================


class TestVerifierCheckRoute:
    def _build_body(self, session_id: str = "sess-123") -> dict:
        return {
            "session_id": session_id,
            "template": {
                "verify_id": "v-http-test",
                "type": "namespace_exists",
                "namespace": "{{lab_namespace}}",
                "name": "placeholder",
                "schema_version": "1.0",
            },
        }

    def test_returns_200_with_valid_token(self) -> None:
        from backend.main import app
        from backend.labgen.routes import get_verifier_service, require_internal_token

        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(Path(tmp))
            session = _active_session(session_id="sess-123", namespace="lab-sess-123")
            fake_svc = VerifierService(
                session_repo=_FakeSessionRepo({"sess-123": session}),
                credential_store=store,
                k8s_client_factory=lambda _kc: FakeK8sVerifierClient(default=True),
            )
            app.dependency_overrides[get_verifier_service] = lambda: fake_svc
            app.dependency_overrides[require_internal_token] = lambda: None
            from fastapi.testclient import TestClient
            c = TestClient(app, raise_server_exceptions=True)
            resp = c.post(
                "/internal/verifier/check",
                json=self._build_body("sess-123"),
            )
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-123"
        assert data["verify_id"] == "v-http-test"
        assert data["passed"] is True

    def test_returns_401_without_token(self) -> None:
        from backend.main import app
        from fastapi.testclient import TestClient

        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post(
            "/internal/verifier/check",
            json=self._build_body(),
        )
        assert resp.status_code == 401

    def test_returns_401_with_wrong_token(self) -> None:
        from backend.main import app
        from fastapi.testclient import TestClient

        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post(
            "/internal/verifier/check",
            json=self._build_body(),
            headers={"X-Admin-Token": "wrong-token"},
        )
        assert resp.status_code == 401

    def test_session_not_found_returns_200_with_error_code(self) -> None:
        from backend.main import app
        from backend.labgen.routes import get_verifier_service, require_internal_token

        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp) / "empty")
            fake_svc = VerifierService(
                session_repo=_FakeSessionRepo({}),
                credential_store=store,
                k8s_client_factory=lambda _kc: FakeK8sVerifierClient(),
            )
            app.dependency_overrides[get_verifier_service] = lambda: fake_svc
            app.dependency_overrides[require_internal_token] = lambda: None
            from fastapi.testclient import TestClient
            c = TestClient(app, raise_server_exceptions=True)
            resp = c.post(
                "/internal/verifier/check",
                json=self._build_body("no-such-session"),
            )
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert data["error_code"] == "session_not_found"
