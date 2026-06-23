"""
Tests for FailureReason enum and its integration with service/verifier layer.

Design rule: tests assert on FailureReason.*.value, never on raw strings.
"""

import pytest

pytestmark = pytest.mark.static

from backend.labgen.failure_reasons import FailureReason


# ---------------------------------------------------------------------------
# 1. Enum stability — values must never change (wire-protocol contract)
# ---------------------------------------------------------------------------


class TestFailureReasonValues:
    def test_precheck_draft_not_found(self):
        assert FailureReason.PRECHECK_DRAFT_NOT_FOUND.value == "precheck.draft_not_found"

    def test_precheck_draft_not_published(self):
        assert FailureReason.PRECHECK_DRAFT_NOT_PUBLISHED.value == "precheck.draft_not_published"

    def test_precheck_cleanup_not_declared(self):
        assert FailureReason.PRECHECK_CLEANUP_NOT_DECLARED.value == "precheck.cleanup_not_declared"

    def test_precheck_vm_not_found(self):
        assert FailureReason.PRECHECK_VM_NOT_FOUND.value == "precheck.vm_not_found"

    def test_precheck_vm_not_owned(self):
        assert (
            FailureReason.PRECHECK_VM_NOT_OWNED_BY_STUDENT.value
            == "precheck.vm_not_owned_by_student"
        )

    def test_precheck_vm_tainted(self):
        assert FailureReason.PRECHECK_VM_TAINTED.value == "precheck.vm_tainted"

    def test_precheck_session_already_active(self):
        assert (
            FailureReason.PRECHECK_SESSION_ALREADY_ACTIVE.value
            == "precheck.session_already_active"
        )

    def test_image_unresolved(self):
        assert FailureReason.IMAGE_UNRESOLVED.value == "image_unresolved"

    def test_image_unavailable(self):
        assert FailureReason.IMAGE_UNAVAILABLE.value == "image_unavailable"

    def test_namespace_create_failed(self):
        assert FailureReason.NAMESPACE_CREATE_FAILED.value == "namespace_create_failed"

    def test_verifier_rolebinding_create_failed(self):
        assert (
            FailureReason.VERIFIER_ROLEBINDING_CREATE_FAILED.value
            == "verifier_rolebinding_create_failed"
        )

    def test_verifier_rolebinding_verify_failed(self):
        assert (
            FailureReason.VERIFIER_ROLEBINDING_VERIFY_FAILED.value
            == "verifier_rolebinding_verify_failed"
        )

    def test_namespace_cleanup_failed(self):
        assert FailureReason.NAMESPACE_CLEANUP_FAILED.value == "namespace_cleanup_failed"

    def test_verifier_session_not_found(self):
        assert FailureReason.VERIFIER_SESSION_NOT_FOUND.value == "session_not_found"

    def test_verifier_session_not_active(self):
        assert FailureReason.VERIFIER_SESSION_NOT_ACTIVE.value == "session_not_active"

    def test_verifier_cluster_scope_not_supported(self):
        assert (
            FailureReason.VERIFIER_CLUSTER_SCOPE_NOT_SUPPORTED.value
            == "cluster_scope_not_supported"
        )

    def test_verifier_namespace_mismatch(self):
        assert FailureReason.VERIFIER_NAMESPACE_MISMATCH.value == "namespace_mismatch"

    def test_verifier_type_not_implemented(self):
        assert (
            FailureReason.VERIFIER_TYPE_NOT_IMPLEMENTED.value == "verify_type_not_implemented"
        )

    def test_verifier_credential_missing(self):
        assert FailureReason.VERIFIER_CREDENTIAL_MISSING.value == "credential_missing"

    def test_lab_not_ready_to_complete(self):
        assert FailureReason.LAB_NOT_READY_TO_COMPLETE.value == "lab_not_ready_to_complete"


# ---------------------------------------------------------------------------
# 2. FailureReason is a str enum — values can be compared to plain strings
# ---------------------------------------------------------------------------


class TestFailureReasonIsStr:
    def test_member_equals_string(self):
        assert FailureReason.PRECHECK_VM_TAINTED == "precheck.vm_tainted"

    def test_member_in_list(self):
        failures = [FailureReason.PRECHECK_VM_TAINTED.value, FailureReason.PRECHECK_VM_NOT_FOUND.value]
        assert "precheck.vm_tainted" in failures
        assert "precheck.vm_not_found" in failures

    def test_all_members_are_strings(self):
        for member in FailureReason:
            assert isinstance(member.value, str)
            assert member.value  # non-empty

    def test_no_duplicate_values(self):
        values = [m.value for m in FailureReason]
        assert len(values) == len(set(values)), "Duplicate FailureReason values detected"


# ---------------------------------------------------------------------------
# 3. VerifyResult carries failure_reason field
# ---------------------------------------------------------------------------


class TestVerifyResultFailureReasonField:
    def test_failure_reason_defaults_to_none(self):
        from backend.labgen.models import VerifyResult

        r = VerifyResult(
            session_id="s",
            verify_id="v",
            verify_type="pod_running",
            passed=True,
        )
        assert r.failure_reason is None

    def test_failure_reason_can_be_set(self):
        from backend.labgen.models import VerifyResult

        r = VerifyResult(
            session_id="s",
            verify_id="v",
            verify_type="pod_running",
            passed=False,
            failure_reason=FailureReason.VERIFIER_SESSION_NOT_FOUND.value,
        )
        assert r.failure_reason == FailureReason.VERIFIER_SESSION_NOT_FOUND.value


# ---------------------------------------------------------------------------
# 4. StepCheckResponse carries failure_reason field
# ---------------------------------------------------------------------------


class TestStepCheckResponseFailureReasonField:
    def test_failure_reason_defaults_to_none(self):
        from backend.labgen.step_progression_service import StepCheckResponse

        resp = StepCheckResponse(
            session_id="s",
            step_id="step-1",
            all_passed=True,
            advanced=True,
            ready_to_complete=False,
            verify_results=[],
        )
        assert resp.failure_reason is None

    def test_failure_reason_can_be_set(self):
        from backend.labgen.step_progression_service import StepCheckResponse

        resp = StepCheckResponse(
            session_id="s",
            step_id="step-1",
            all_passed=False,
            advanced=False,
            ready_to_complete=False,
            verify_results=[],
            failure_reason=FailureReason.VERIFIER_CREDENTIAL_MISSING.value,
        )
        assert resp.failure_reason == FailureReason.VERIFIER_CREDENTIAL_MISSING.value


# ---------------------------------------------------------------------------
# 5. VerifierService emits normalized failure_reason on VerifyResult
# ---------------------------------------------------------------------------


class TestVerifierServiceEmitsFailureReason:
    def _make_template(self, cluster_scope: bool = False):
        from backend.labgen.models import VerifyTemplate, VerifyType

        return VerifyTemplate(
            verify_id="v1",
            type=VerifyType.POD_RUNNING,
            namespace="{{lab_namespace}}",
            name="my-pod",
            cluster_scope=cluster_scope,
        )

    def _make_store_with_creds(self, vm_id: str, tmp_path):
        from backend.labgen.verifier_credentials import VerifierCredentialStore

        store = VerifierCredentialStore(base_dir=tmp_path)
        kubeconfig = (
            "apiVersion: v1\nclusters:\n- cluster:\n    server: https://127.0.0.1:6443\n"
            "    certificate-authority-data: dGVzdA==\n  name: k3s\n"
            "contexts:\n- context:\n    cluster: k3s\n    user: verifier\n  name: default\n"
            "current-context: default\nkind: Config\nusers:\n"
            "- name: verifier\n  user:\n    token: fake-token\n"
        )
        store.store(vm_id, kubeconfig, "verifier")
        return store

    def test_session_not_found_emits_failure_reason(self):
        from unittest.mock import MagicMock

        from backend.labgen.verifier import FakeK8sVerifierClient, VerifierService

        repo = MagicMock()
        repo.get.return_value = None
        store = MagicMock()
        svc = VerifierService(repo, store, lambda _: FakeK8sVerifierClient())

        result = svc.check("no-such-session", self._make_template())
        assert result.failure_reason == FailureReason.VERIFIER_SESSION_NOT_FOUND.value
        assert result.error_code == FailureReason.VERIFIER_SESSION_NOT_FOUND.value
        assert not result.passed

    def test_session_not_active_emits_failure_reason(self):
        from unittest.mock import MagicMock

        from backend.labgen.models import LabSessionState, LabSessionStatus
        from backend.labgen.verifier import FakeK8sVerifierClient, VerifierService

        session = MagicMock(spec=LabSessionState)
        session.lab_session_status = LabSessionStatus.LAB_CLOSED
        repo = MagicMock()
        repo.get.return_value = session
        store = MagicMock()
        svc = VerifierService(repo, store, lambda _: FakeK8sVerifierClient())

        result = svc.check("s1", self._make_template())
        assert result.failure_reason == FailureReason.VERIFIER_SESSION_NOT_ACTIVE.value
        assert not result.passed

    def test_cluster_scope_emits_failure_reason(self):
        from unittest.mock import MagicMock

        from backend.labgen.models import LabSessionState, LabSessionStatus
        from backend.labgen.verifier import FakeK8sVerifierClient, VerifierService

        session = MagicMock(spec=LabSessionState)
        session.lab_session_status = LabSessionStatus.LAB_ACTIVE
        session.namespace = "lab-abc"
        repo = MagicMock()
        repo.get.return_value = session
        store = MagicMock()
        svc = VerifierService(repo, store, lambda _: FakeK8sVerifierClient())

        result = svc.check("s1", self._make_template(cluster_scope=True))
        assert result.failure_reason == FailureReason.VERIFIER_CLUSTER_SCOPE_NOT_SUPPORTED.value
        assert not result.passed

    def test_credential_missing_emits_failure_reason(self, tmp_path):
        from unittest.mock import MagicMock

        from backend.labgen.models import LabSessionState, LabSessionStatus
        from backend.labgen.verifier import FakeK8sVerifierClient, VerifierService
        from backend.labgen.verifier_credentials import VerifierCredentialStore

        session = MagicMock(spec=LabSessionState)
        session.lab_session_status = LabSessionStatus.LAB_ACTIVE
        session.namespace = "lab-abc"
        session.vm_id = "500"
        repo = MagicMock()
        repo.get.return_value = session
        store = VerifierCredentialStore(base_dir=tmp_path)  # empty store
        svc = VerifierService(repo, store, lambda _: FakeK8sVerifierClient())

        result = svc.check("s1", self._make_template())
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_MISSING.value
        assert not result.passed


# ---------------------------------------------------------------------------
# 6. Precheck emits FailureReason values (not raw strings)
# ---------------------------------------------------------------------------


class TestPrecheckEmitsFailureReasonValues:
    def _make_svc(
        self,
        draft=None,
        vm_exists=True,
        vm_owned=True,
        vm_tainted=False,
        active_sessions=None,
    ):
        from unittest.mock import MagicMock

        from backend.labgen.lab_session_service import (
            LabSessionService,
            StubVMTracker,
        )
        from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter

        class _PatchedVMTracker(StubVMTracker):
            def vm_exists(self, vm_id):
                return vm_exists

            def is_vm_owned_by(self, vm_id, username):
                return vm_owned

            def is_vm_tainted(self, vm_id):
                return vm_tainted

        draft_repo = MagicMock()
        draft_repo.get.return_value = draft
        session_repo = MagicMock()
        session_repo.list_by_student.return_value = active_sessions or []
        svc = LabSessionService(
            draft_repo=draft_repo,
            session_repo=session_repo,
            vm_tracker=_PatchedVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=MagicMock(),
        )
        return svc

    def test_draft_not_found_uses_enum(self):
        svc = self._make_svc(draft=None)
        result = svc.run_precheck("no-lab", "vm-500", "alice")
        assert FailureReason.PRECHECK_DRAFT_NOT_FOUND.value in result.failures

    def test_vm_tainted_uses_enum(self):
        from unittest.mock import MagicMock

        from backend.labgen.models import CleanupNamespace, CleanupSpec, LabDomainType, LabDraft, PublishStatus

        draft = MagicMock(spec=LabDraft)
        draft.publish_status = PublishStatus.PUBLISHED
        draft.target_domain = LabDomainType.K8S
        draft.cleanup = CleanupSpec(namespace_cleanup=CleanupNamespace())
        svc = self._make_svc(draft=draft, vm_tainted=True)
        result = svc.run_precheck("lab-1", "vm-500", "alice")
        assert FailureReason.PRECHECK_VM_TAINTED.value in result.failures

    def test_vm_not_found_uses_enum(self):
        svc = self._make_svc(vm_exists=False)
        result = svc.run_precheck("lab-1", "vm-500", "alice")
        assert FailureReason.PRECHECK_VM_NOT_FOUND.value in result.failures

    def test_vm_not_owned_uses_enum(self):
        svc = self._make_svc(vm_owned=False)
        result = svc.run_precheck("lab-1", "vm-500", "alice")
        assert FailureReason.PRECHECK_VM_NOT_OWNED_BY_STUDENT.value in result.failures
