"""
End-to-end integration tests for the step-check verification chain.

Full path under test:
  POST /api/lab-sessions/{id}/steps/{step_id}/check
    → StepProgressionService.check_step()
      → VerifierService.check()            (real, not mocked away)
        → K8sClientFactory(kubeconfig)     (spy / stub — no real K3s)
          → K8sVerifierClientPort methods

What these tests verify that unit tests cannot:
- VerifierService guards are exercised end-to-end (not bypassed by a fake svc)
- {{lab_namespace}} sentinel resolved from session.namespace before reaching the adapter
- Credential store is consulted; factory receives the stored kubeconfig content
- No credential fallback to any admin kubeconfig
- All-pass / any-fail semantics propagate through the full stack
- ready_to_complete set; session remains LAB_ACTIVE after last step (no auto-cleanup)
- SECRET_EXISTS dispatched to list_namespaced_secret, never read_namespaced_secret

Out of scope:
- Real K3s cluster (no network calls)
- LLM, WebSocket, terminal, frontend, Directus
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from backend.labgen.k8s_verifier_client import K8sVerifierClientAdapter, KubernetesApiFactory
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    Step,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.step_progression_service import StepProgressionService
from backend.labgen.verifier import FakeK8sVerifierClient, VerifierService
from backend.labgen.verifier_credentials import (
    VerifierCredentialMetadata,
    VerifierCredentialStore,
)

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Test constants — domain-based server, no intranet IPs
# ---------------------------------------------------------------------------

_FAKE_KUBECONFIG = (
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

# ---------------------------------------------------------------------------
# In-memory fakes shared across both service layers
# ---------------------------------------------------------------------------


class _FakeSessionRepo:
    def __init__(self, sessions: Optional[dict[str, LabSessionState]] = None) -> None:
        self._sessions: dict[str, LabSessionState] = dict(sessions or {})

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._sessions.get(session_id)

    def update(self, session: LabSessionState) -> LabSessionState:
        self._sessions[session.session_id] = session
        return session

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._sessions.values() if s.student_username == username]

    def create(self, session: LabSessionState) -> LabSessionState:
        self._sessions[session.session_id] = session
        return session


class _FakeDraftRepo:
    def __init__(self, drafts: Optional[dict[str, LabDraft]] = None) -> None:
        self._drafts: dict[str, LabDraft] = dict(drafts or {})

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._drafts.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._drafts[draft.lab_id] = draft
        return draft


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "sess-integ",
    lab_id: str = "lab-integ",
    vm_id: str = "501",
    username: str = "alice",
    namespace: str = "lab-sess-integ",
    current_step_index: int = 0,
) -> LabSessionState:
    s = LabSessionState(
        session_id=session_id,
        lab_id=lab_id,
        vm_id=vm_id,
        student_username=username,
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
        namespace=namespace,
    )
    s.current_step_index = current_step_index
    return s


def _make_verify_template(
    verify_id: str = "v1",
    vtype: VerifyType = VerifyType.NAMESPACE_EXISTS,
    namespace: str = "{{lab_namespace}}",
    name: str = "placeholder",
    cluster_scope: bool = False,
) -> VerifyTemplate:
    return VerifyTemplate(
        verify_id=verify_id,
        type=vtype,
        namespace=namespace,
        name=name,
        cluster_scope=cluster_scope,
    )


def _make_step(
    step_id: str = "step-1",
    order: int = 1,
    verify_templates: Optional[list[VerifyTemplate]] = None,
) -> Step:
    return Step(
        step_id=step_id,
        order=order,
        why="test why",
        do="test do",
        observe="test observe",
        explain=ExplainField(concept="test", observation="test"),
        verify=verify_templates or [],
    )


def _make_draft(
    lab_id: str = "lab-integ",
    steps: Optional[list[Step]] = None,
) -> LabDraft:
    return LabDraft(
        lab_id=lab_id,
        source_article_id="art-integ",
        title="Integration Test Lab",
        description="Integration test",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=steps if steps is not None else [_make_step()],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.PUBLISHED,
    )


def _seed_credential(store: VerifierCredentialStore, vm_id: str = "501") -> None:
    metadata = VerifierCredentialMetadata(
        vm_id=vm_id,
        created_at=datetime.now(tz=timezone.utc),
        expires_at=datetime.now(tz=timezone.utc),
        k3s_endpoint="https://k3s.test:6443",
    )
    store.save(vm_id, _FAKE_KUBECONFIG, metadata)


def _make_chain(
    session: LabSessionState,
    draft: LabDraft,
    store: VerifierCredentialStore,
    k8s_factory,
) -> StepProgressionService:
    """Wire StepProgressionService → VerifierService → k8s_factory on a shared session repo.

    Both services share the same _FakeSessionRepo so VerifierService.check()
    can find the session that StepProgressionService validated.
    """
    shared_repo = _FakeSessionRepo({session.session_id: session})
    verifier_svc = VerifierService(
        session_repo=shared_repo,
        credential_store=store,
        k8s_client_factory=k8s_factory,
    )
    return StepProgressionService(
        session_repo=shared_repo,
        draft_repo=_FakeDraftRepo({draft.lab_id: draft}),
        verifier_svc=verifier_svc,
    )


# ===========================================================================
# Factory receives kubeconfig from credential store
# ===========================================================================


class TestFactoryReceivesKubeconfig:
    def test_factory_called_with_stored_kubeconfig(self) -> None:
        """VerifierService passes the stored kubeconfig content to the K8s factory."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            received: list[str] = []

            def spy(kc: str):
                received.append(kc)
                return FakeK8sVerifierClient(default=True)

            draft = _make_draft(steps=[_make_step(verify_templates=[_make_verify_template()])])
            svc = _make_chain(session, draft, store, spy)
            svc.check_step(session.session_id, "step-1", "alice")

        assert len(received) == 1
        assert received[0] == _FAKE_KUBECONFIG

    def test_factory_receives_vm_specific_kubeconfig(self) -> None:
        """Different VMs store different kubeconfigs; factory gets the right one."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(vm_id="555")
            alt_kc = _FAKE_KUBECONFIG.replace("test-token-xyz", "token-vm-555")
            store.save(
                "555",
                alt_kc,
                VerifierCredentialMetadata(
                    vm_id="555",
                    created_at=datetime.now(tz=timezone.utc),
                    expires_at=datetime.now(tz=timezone.utc),
                    k3s_endpoint="https://k3s.test:6443",
                ),
            )

            received: list[str] = []

            def spy(kc: str):
                received.append(kc)
                return FakeK8sVerifierClient(default=True)

            draft = _make_draft(steps=[_make_step(verify_templates=[_make_verify_template()])])
            svc = _make_chain(session, draft, store, spy)
            svc.check_step(session.session_id, "step-1", "alice")

        assert len(received) == 1
        assert received[0] == alt_kc

    def test_factory_not_called_when_credential_missing(self) -> None:
        """When credential store is empty, the K8s factory is never called."""
        with tempfile.TemporaryDirectory() as tmp:
            empty_store = VerifierCredentialStore(base_dir=Path(tmp) / "empty")
            session = _make_session(vm_id="502")

            called = [False]

            def spy(kc: str):
                called[0] = True
                return FakeK8sVerifierClient()

            draft = _make_draft(steps=[_make_step(verify_templates=[_make_verify_template()])])
            svc = _make_chain(session, draft, empty_store, spy)
            svc.check_step(session.session_id, "step-1", "alice")

        assert called[0] is False


# ===========================================================================
# {{lab_namespace}} sentinel resolution
# ===========================================================================


class TestSentinelResolution:
    def test_sentinel_resolved_to_session_namespace_before_dispatch(self) -> None:
        """{{lab_namespace}} is replaced with session.namespace before reaching the adapter."""
        dispatched_ns: list[str] = []

        class _SpyClient(FakeK8sVerifierClient):
            def namespace_exists(self, namespace: str) -> bool:
                dispatched_ns.append(namespace)
                return True

        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(namespace="lab-my-real-ns")
            _seed_credential(store, session.vm_id)

            tmpl = _make_verify_template(
                vtype=VerifyType.NAMESPACE_EXISTS, namespace="{{lab_namespace}}"
            )
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(session, draft, store, lambda _kc: _SpyClient())

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is True
        assert dispatched_ns == ["lab-my-real-ns"]

    def test_wrong_namespace_in_template_produces_mismatch_error(self) -> None:
        """VerifyTemplate.namespace not matching session → error_code='namespace_mismatch'."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(namespace="lab-real-ns")
            _seed_credential(store, session.vm_id)

            tmpl = _make_verify_template(namespace="kube-system")
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is False
        assert result.advanced is False
        assert result.verify_results[0].error_code == "namespace_mismatch"

    def test_explicit_matching_namespace_accepted(self) -> None:
        """Explicit namespace == session.namespace is accepted (no sentinel needed)."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(namespace="lab-my-session")
            _seed_credential(store, session.vm_id)

            tmpl = _make_verify_template(namespace="lab-my-session")
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is True
        assert result.advanced is True


# ===========================================================================
# Credential guard — missing credential does not fall back to admin
# ===========================================================================


class TestCredentialGuard:
    def test_credential_missing_returns_failed_result(self) -> None:
        """No credential for VM → VerifyResult.error_code='credential_missing'; no advance."""
        with tempfile.TemporaryDirectory() as tmp:
            empty_store = VerifierCredentialStore(base_dir=Path(tmp) / "empty")
            session = _make_session(vm_id="503")

            tmpl = _make_verify_template()
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(session, draft, empty_store, lambda _kc: FakeK8sVerifierClient())

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is False
        assert result.advanced is False
        assert result.verify_results[0].error_code == "credential_missing"
        assert "503" in result.verify_results[0].detail

    def test_credential_present_does_not_produce_missing_error(self) -> None:
        """Seeded credential → no credential_missing error."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(vm_id="504")
            _seed_credential(store, "504")

            tmpl = _make_verify_template()
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.verify_results[0].error_code is None


# ===========================================================================
# Multi-verify advancement semantics
# ===========================================================================


class TestMultiVerifyAdvancement:
    def test_all_verify_pass_advances_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(
                verify_templates=[
                    _make_verify_template("v1", VerifyType.NAMESPACE_EXISTS),
                    _make_verify_template("v2", VerifyType.SERVICE_EXISTS, name="nginx"),
                    _make_verify_template("v3", VerifyType.DEPLOYMENT_READY, name="nginx"),
                ]
            )
            draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is True
        assert result.advanced is True
        assert len(result.verify_results) == 3
        assert all(r.passed for r in result.verify_results)

    def test_one_verify_fails_blocks_advance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(namespace="lab-test-ns")
            _seed_credential(store, session.vm_id)

            step = _make_step(
                verify_templates=[
                    _make_verify_template("v-pass", VerifyType.NAMESPACE_EXISTS),
                    _make_verify_template("v-fail", VerifyType.DEPLOYMENT_READY, name="nginx"),
                ]
            )
            draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
            fake = FakeK8sVerifierClient(
                responses={("deployment_ready", "lab-test-ns", "nginx"): False},
                default=True,
            )
            svc = _make_chain(session, draft, store, lambda _kc: fake)

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is False
        assert result.advanced is False
        assert any(not r.passed for r in result.verify_results)

    def test_error_result_counts_as_failure(self) -> None:
        """verify_type_not_implemented is passed=False → no advance."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(
                verify_templates=[
                    _make_verify_template("v-bad", VerifyType.POD_READY, name="mypod"),
                ]
            )
            draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is False
        assert result.advanced is False
        assert result.verify_results[0].error_code == "verify_type_not_implemented"

    def test_namespace_mismatch_counts_as_failure(self) -> None:
        """namespace_mismatch produces passed=False → no advance."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(namespace="lab-correct-ns")
            _seed_credential(store, session.vm_id)

            step = _make_step(
                verify_templates=[
                    _make_verify_template("v-mismatch", namespace="lab-wrong-ns"),
                ]
            )
            draft = _make_draft(steps=[step])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is False
        assert result.advanced is False


# ===========================================================================
# Last step: ready_to_complete only — no auto-cleanup, still LAB_ACTIVE
# ===========================================================================


class TestLastStepBehavior:
    def test_last_step_sets_ready_to_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(verify_templates=[_make_verify_template()])
            draft = _make_draft(steps=[step])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.ready_to_complete is True

    def test_last_step_session_remains_lab_active(self) -> None:
        """After last step passes, session status stays LAB_ACTIVE — no auto-cleanup."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(verify_templates=[_make_verify_template()])
            draft = _make_draft(steps=[step])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            svc.check_step(session.session_id, "step-1", "alice")
            updated = svc._session_repo.get(session.session_id)

        assert updated is not None
        assert updated.lab_session_status == LabSessionStatus.LAB_ACTIVE
        assert updated.ready_to_complete is True

    def test_non_last_step_not_ready_to_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            steps = [
                _make_step("step-1", 1, [_make_verify_template("v1")]),
                _make_step("step-2", 2, [_make_verify_template("v2")]),
            ]
            draft = _make_draft(steps=steps)
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.ready_to_complete is False

    def test_last_step_fail_does_not_set_ready_to_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(verify_templates=[_make_verify_template()])
            draft = _make_draft(steps=[step])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=False)
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.ready_to_complete is False
        assert result.advanced is False


# ===========================================================================
# SECRET_EXISTS: uses list, never reads secret data
# ===========================================================================


class TestSecretExistsSafety:
    def _make_secret_adapter_factory(self, core: MagicMock, apps: MagicMock):
        stub_factory = MagicMock(spec=KubernetesApiFactory)
        stub_factory.build.return_value = (core, apps)

        def factory(kc: str):
            return K8sVerifierClientAdapter(kc, stub_factory)

        return factory

    def test_dispatches_to_list_not_read(self) -> None:
        """SECRET_EXISTS → list_namespaced_secret called; read_namespaced_secret never called."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            core = MagicMock()
            secret_list = MagicMock()
            secret_list.items = [MagicMock()]
            core.list_namespaced_secret.return_value = secret_list

            tmpl = _make_verify_template("v-sec", VerifyType.SECRET_EXISTS, name="my-secret")
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(
                session, draft, store, self._make_secret_adapter_factory(core, MagicMock())
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is True
        core.list_namespaced_secret.assert_called_once()
        core.read_namespaced_secret.assert_not_called()

    def test_field_selector_filters_by_name(self) -> None:
        """field_selector=metadata.name={name} passed to list_namespaced_secret."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(namespace="lab-my-ns")
            _seed_credential(store, session.vm_id)

            core = MagicMock()
            secret_list = MagicMock()
            secret_list.items = [MagicMock()]
            core.list_namespaced_secret.return_value = secret_list

            tmpl = _make_verify_template("v-sec", VerifyType.SECRET_EXISTS, name="tls-cert")
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(
                session, draft, store, self._make_secret_adapter_factory(core, MagicMock())
            )
            svc.check_step(session.session_id, "step-1", "alice")

        core.list_namespaced_secret.assert_called_once_with(
            "lab-my-ns", field_selector="metadata.name=tls-cert"
        )

    def test_secret_not_found_produces_false_result(self) -> None:
        """Empty list → passed=False (secret doesn't exist)."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            core = MagicMock()
            empty_list = MagicMock()
            empty_list.items = []
            core.list_namespaced_secret.return_value = empty_list

            tmpl = _make_verify_template("v-sec", VerifyType.SECRET_EXISTS, name="missing")
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(
                session, draft, store, self._make_secret_adapter_factory(core, MagicMock())
            )

            result = svc.check_step(session.session_id, "step-1", "alice")

        assert result.all_passed is False
        assert result.verify_results[0].passed is False


# ===========================================================================
# Unsupported verify types rejected at VerifierService level
# ===========================================================================


class TestUnsupportedVerifyTypes:
    def _run(self, vtype: VerifyType) -> "StepCheckResponse":  # type: ignore[name-defined]
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            tmpl = _make_verify_template("v-unsupported", vtype, name="resource")
            draft = _make_draft(steps=[_make_step(verify_templates=[tmpl])])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )
            return svc.check_step(session.session_id, "step-1", "alice")

    def test_pod_ready_rejected_as_not_implemented(self) -> None:
        result = self._run(VerifyType.POD_READY)
        assert result.all_passed is False
        assert result.verify_results[0].error_code == "verify_type_not_implemented"

    def test_node_ready_rejected_as_not_implemented(self) -> None:
        result = self._run(VerifyType.NODE_READY)
        assert result.all_passed is False
        assert result.verify_results[0].error_code == "verify_type_not_implemented"

    def test_pvc_bound_rejected_as_not_implemented(self) -> None:
        result = self._run(VerifyType.PVC_BOUND)
        assert result.all_passed is False
        assert result.verify_results[0].error_code == "verify_type_not_implemented"

    def test_job_completed_rejected_as_not_implemented(self) -> None:
        result = self._run(VerifyType.JOB_COMPLETED)
        assert result.all_passed is False
        assert result.verify_results[0].error_code == "verify_type_not_implemented"

    def test_unsupported_type_does_not_advance_step(self) -> None:
        """verify_type_not_implemented → step index unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(
                "step-1",
                verify_templates=[
                    _make_verify_template("v-bad", VerifyType.NODE_READY, name="node1"),
                ],
            )
            draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
            svc = _make_chain(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )

            svc.check_step(session.session_id, "step-1", "alice")
            updated = svc._session_repo.get(session.session_id)

        assert updated is not None
        assert updated.current_step_index == 0


# ===========================================================================
# HTTP integration — full chain wired via TestClient
# ===========================================================================


class TestHTTPChainIntegration:
    _URL = "/api/lab-sessions/{session_id}/steps/{step_id}/check"

    def _make_test_client(
        self,
        session: LabSessionState,
        draft: LabDraft,
        store: VerifierCredentialStore,
        k8s_factory,
    ):
        from fastapi.testclient import TestClient
        from backend.auth_deps import get_current_user
        from backend.labgen.routes import get_step_progression_service
        from backend.main import app

        svc = _make_chain(session, draft, store, k8s_factory)
        app.dependency_overrides[get_current_user] = lambda: session.student_username
        app.dependency_overrides[get_step_progression_service] = lambda: svc
        return TestClient(app, raise_server_exceptions=True)

    def _clear_overrides(self) -> None:
        from backend.main import app
        app.dependency_overrides.clear()

    def test_200_all_passed_returns_advanced_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(verify_templates=[_make_verify_template()])
            draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
            c = self._make_test_client(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )
            resp = c.post(
                self._URL.format(session_id=session.session_id, step_id="step-1")
            )
            self._clear_overrides()

        assert resp.status_code == 200
        data = resp.json()
        assert data["all_passed"] is True
        assert data["advanced"] is True
        assert data["session_id"] == session.session_id
        assert len(data["verify_results"]) == 1

    def test_200_verify_failed_advanced_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(verify_templates=[_make_verify_template()])
            draft = _make_draft(steps=[step, _make_step("step-2", order=2)])
            c = self._make_test_client(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=False)
            )
            resp = c.post(
                self._URL.format(session_id=session.session_id, step_id="step-1")
            )
            self._clear_overrides()

        assert resp.status_code == 200
        data = resp.json()
        assert data["all_passed"] is False
        assert data["advanced"] is False

    def test_200_credential_missing_error_code_in_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty_store = VerifierCredentialStore(base_dir=Path(tmp) / "empty")
            session = _make_session(vm_id="509")

            step = _make_step(verify_templates=[_make_verify_template()])
            draft = _make_draft(steps=[step])
            c = self._make_test_client(
                session, draft, empty_store, lambda _kc: FakeK8sVerifierClient()
            )
            resp = c.post(
                self._URL.format(session_id=session.session_id, step_id="step-1")
            )
            self._clear_overrides()

        assert resp.status_code == 200
        data = resp.json()
        assert data["all_passed"] is False
        assert data["verify_results"][0]["error_code"] == "credential_missing"

    def test_200_last_step_ready_to_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session()
            _seed_credential(store, session.vm_id)

            step = _make_step(verify_templates=[_make_verify_template()])
            draft = _make_draft(steps=[step])
            c = self._make_test_client(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )
            resp = c.post(
                self._URL.format(session_id=session.session_id, step_id="step-1")
            )
            self._clear_overrides()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ready_to_complete"] is True

    def test_200_namespace_mismatch_in_result(self) -> None:
        """Template with wrong namespace → 200 with namespace_mismatch error code."""
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifierCredentialStore(base_dir=Path(tmp))
            session = _make_session(namespace="lab-correct")
            _seed_credential(store, session.vm_id)

            tmpl = _make_verify_template(namespace="lab-attacker")
            step = _make_step(verify_templates=[tmpl])
            draft = _make_draft(steps=[step])
            c = self._make_test_client(
                session, draft, store, lambda _kc: FakeK8sVerifierClient(default=True)
            )
            resp = c.post(
                self._URL.format(session_id=session.session_id, step_id="step-1")
            )
            self._clear_overrides()

        assert resp.status_code == 200
        data = resp.json()
        assert data["all_passed"] is False
        assert data["verify_results"][0]["error_code"] == "namespace_mismatch"
