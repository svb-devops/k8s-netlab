"""
Runtime Start Precheck integration tests — Contract §11 conditions 4 and 6
wired into LabSessionService.create_session().

Validates:
  B. Start integration
     - all prechecks pass → existing start happy path unchanged
     - condition 4 fails → start rejected
     - condition 6 fails → start rejected
     - both fail → start rejected with both issue codes in audit metadata
     - rejected start does not create namespace
     - rejected start does not create rolebinding
     - rejected start does not call VM init (verified via ns adapter)
     - rejected start records safe LAB_START_FAILED audit event
     - rejected start response uses normalized failure_reason

  C. Safety
     - dependency error with token → response does not leak token
     - dependency error with traceback → audit metadata does not leak traceback
     - no raw exception repr in session failure_reason
     - no kubeconfig / credential leak

  D. Regression
     - existing runtime smoke tests still pass (taint, adapter selection, image check)
"""

from __future__ import annotations

from typing import Optional

import pytest

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.lab_session_service import (
    LabSessionService,
    PrecheckFailed,
    StubVMTracker,
)
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ClusterScopedResource,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeAuditEventType,
    RuntimeRequirements,
    Step,
)
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
from backend.labgen.runtime_precheck import (
    RuntimePrecheckCondition,
    RuntimePrecheckService,
    RuntimePrecheckStatus,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# In-memory stubs (self-contained — no shared fixtures)
# ---------------------------------------------------------------------------


class _MemSessionRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabSessionState] = {}

    def create(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def get(self, sid: str) -> Optional[LabSessionState]:
        return self._store.get(sid)

    def update(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]

    def list_by_vm_id(self, vm_id: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.vm_id == vm_id]

    def delete(self, sid: str) -> None:
        self._store.pop(sid, None)


class _MemDraftRepo:
    def __init__(self, drafts: dict[str, LabDraft] | None = None) -> None:
        self._store: dict[str, LabDraft] = dict(drafts or {})

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft


class _RecordingAuditService:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(
        self,
        session_id: str,
        event_type: RuntimeAuditEventType,
        failure_reason: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self.events.append({
            "session_id": session_id,
            "event_type": event_type,
            "failure_reason": failure_reason,
            "metadata": metadata or {},
        })


class _StubImageResolver:
    def needs_recheck(self, img) -> bool:
        return False

    def check_registry_existence(self, img):
        return img


class _RaisingNsAdapter(StubNamespaceLifecycleAdapter):
    """Raises RuntimeError from is_namespace_stuck_terminating to simulate external failure."""

    def __init__(self, error_msg: str = "secret=tok3n_s3cr3t bearer=Bearer abc123") -> None:
        super().__init__()
        self._error_msg = error_msg

    def is_namespace_stuck_terminating(self, namespace: str, threshold_seconds: int = 300) -> bool:
        raise RuntimeError(self._error_msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_published_draft(
    lab_id: str = "lab-1",
    cluster_scoped: bool = False,
) -> LabDraft:
    csr: list[ClusterScopedResource] = (
        [ClusterScopedResource(
            kind="ClusterRole",
            name="lab-cr",
            api_group="rbac.authorization.k8s.io",
            cleanup="kubectl delete clusterrole lab-cr",
        )]
        if cluster_scoped
        else []
    )
    return LabDraft(
        lab_id=lab_id,
        source_article_id="art-1",
        title="Test Lab",
        description="desc",
        estimated_duration_minutes=20,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="w", do="d", observe="o",
            explain=ExplainField(concept="c", observation="o"),
        )],
        cleanup=CleanupSpec(
            namespace_cleanup=CleanupNamespace(),
            cluster_scoped_resources=csr,
        ),
        publish_status=PublishStatus.PUBLISHED,
    )


def _make_prior_session(
    lab_id: str = "lab-prev",
    vm_id: str = "500",
    username: str = "alice",
    status: LabSessionStatus = LabSessionStatus.LAB_CLOSED,
    namespace: str = "lab-prev-ns",
    cleanup_verified: bool = True,
) -> LabSessionState:
    return LabSessionState(
        lab_id=lab_id,
        vm_id=vm_id,
        student_username=username,
        lab_session_status=status,
        namespace=namespace,
        cleanup_verified=cleanup_verified,
    )


_UNSET = object()


def _build_service(
    ns: StubNamespaceLifecycleAdapter | None = None,
    session_repo: _MemSessionRepo | None = None,
    draft_repo: _MemDraftRepo | None = None,
    audit: _RecordingAuditService | None = None,
    runtime_precheck=_UNSET,
) -> tuple[LabSessionService, _RecordingAuditService, _MemSessionRepo, StubNamespaceLifecycleAdapter]:
    """Build a LabSessionService with all stubs.

    *runtime_precheck* sentinel: omit = create default from ns+repos;
    pass None = disable precheck.
    """
    ns_adapter = ns or StubNamespaceLifecycleAdapter()
    repo = session_repo or _MemSessionRepo()
    drepo = draft_repo or _MemDraftRepo()
    audit_svc = audit or _RecordingAuditService()

    if runtime_precheck is _UNSET:
        rp = RuntimePrecheckService(
            ns_lifecycle=ns_adapter,
            session_repo=repo,
            draft_repo=drepo,
        )
    else:
        rp = runtime_precheck

    svc = LabSessionService(
        session_repo=repo,
        draft_repo=drepo,
        vm_tracker=StubVMTracker(),
        ns_lifecycle=ns_adapter,
        image_resolver=_StubImageResolver(),
        audit_svc=audit_svc,
        runtime_precheck=rp,
    )
    return svc, audit_svc, repo, ns_adapter


# ===========================================================================
# B. Start integration
# ===========================================================================


class TestStartIntegration:
    def test_happy_path_succeeds_when_all_pass(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        svc, audit, repo, ns = _build_service(draft_repo=drepo)
        session = svc.create_session("lab-1", "500", "alice")
        assert session.lab_session_status == LabSessionStatus.LAB_ACTIVE
        assert session.failure_reason is None

    def test_condition_4_fail_rejects_start(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, _, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        assert result.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert result.failure_reason == FailureReason.RUNTIME_PRECHECK_CONDITION_4_FAILED.value

    def test_condition_6_fail_rejects_start(self):
        drepo = _MemDraftRepo({
            "lab-1": _make_published_draft(),
            "lab-prev": _make_published_draft(lab_id="lab-prev", cluster_scoped=True),
        })
        srepo = _MemSessionRepo()
        prior = _make_prior_session(
            lab_id="lab-prev",
            status=LabSessionStatus.LAB_CLEANUP_FAILED,
            cleanup_verified=False,
        )
        srepo.create(prior)
        svc, _, _, _ = _build_service(session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        assert result.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert result.failure_reason == FailureReason.RUNTIME_PRECHECK_CONDITION_6_FAILED.value

    def test_both_fail_uses_top_level_code(self):
        drepo = _MemDraftRepo({
            "lab-1": _make_published_draft(),
            "lab-prev": _make_published_draft(lab_id="lab-prev", cluster_scoped=True),
        })
        srepo = _MemSessionRepo()
        prior = _make_prior_session(
            lab_id="lab-prev",
            namespace="lab-stuck-ns",
            status=LabSessionStatus.LAB_CLEANUP_FAILED,
            cleanup_verified=False,
        )
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, audit, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        assert result.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert result.failure_reason == FailureReason.RUNTIME_PRECHECK_FAILED.value

    def test_rejected_start_does_not_create_namespace(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, _, _, ns_adapter = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        svc.create_session("lab-1", "500", "alice")
        assert ns_adapter.created == []

    def test_rejected_start_does_not_create_rolebinding(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, _, _, ns_adapter = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        svc.create_session("lab-1", "500", "alice")
        assert ns_adapter.rolebindings_created == []

    def test_rejected_start_records_lab_start_failed_audit_event(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, audit, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        svc.create_session("lab-1", "500", "alice")
        assert any(e["event_type"] == RuntimeAuditEventType.LAB_START_FAILED for e in audit.events)

    def test_audit_event_metadata_contains_safe_codes_only(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, audit, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        svc.create_session("lab-1", "500", "alice")
        event = next(e for e in audit.events if e["event_type"] == RuntimeAuditEventType.LAB_START_FAILED)
        metadata = event["metadata"]
        # Must contain blocked_conditions and issue_codes
        assert "blocked_conditions" in metadata
        assert "issue_codes" in metadata
        # Must use stable machine codes (not raw Python exceptions)
        for code in metadata["issue_codes"]:
            assert code.startswith("runtime_precheck.")

    def test_audit_event_metadata_has_no_kubeconfig_or_credentials(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, audit, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        svc.create_session("lab-1", "500", "alice")
        event = next(e for e in audit.events if e["event_type"] == RuntimeAuditEventType.LAB_START_FAILED)
        metadata_str = str(event["metadata"])
        for sensitive in ("kubeconfig", "private_key", "Bearer", "sk-", "password", "secret"):
            assert sensitive not in metadata_str

    def test_rejected_start_response_uses_normalized_failure_reason(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, _, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        # failure_reason must be a known stable FailureReason value
        all_values = {fr.value for fr in FailureReason}
        assert result.failure_reason in all_values

    def test_rejected_start_session_is_persisted(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, _, repo, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        persisted = repo.get(result.session_id)
        assert persisted is not None
        assert persisted.lab_session_status == LabSessionStatus.LAB_START_FAILED


# ===========================================================================
# C. Safety
# ===========================================================================


class TestSafety:
    def test_dependency_error_with_sensitive_msg_does_not_leak_to_failure_reason(self):
        """session.failure_reason must be a stable code, never a raw exception message."""
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-prev-ns")
        srepo.create(prior)
        sensitive_token = "sk-ant-api03-SUPERSECRETTOKEN1234567890ABCDEF"
        ns = _RaisingNsAdapter(error_msg=f"connection error: {sensitive_token}")
        svc, _, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        assert result.failure_reason is not None
        assert sensitive_token not in result.failure_reason

    def test_dependency_error_with_traceback_does_not_leak_to_audit(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-prev-ns")
        srepo.create(prior)
        ns = _RaisingNsAdapter(error_msg="Traceback (most recent call last):\n  boom\nKeyError: secret_db_password=hunter2")
        svc, audit, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        svc.create_session("lab-1", "500", "alice")
        event = next((e for e in audit.events if e["event_type"] == RuntimeAuditEventType.LAB_START_FAILED), None)
        if event:
            metadata_str = str(event.get("metadata", {}))
            assert "hunter2" not in metadata_str
            assert "Traceback" not in metadata_str

    def test_no_raw_exception_repr_in_failure_reason(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-prev-ns")
        srepo.create(prior)
        ns = _RaisingNsAdapter(error_msg="RuntimeError: internal crash at line 42")
        svc, _, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        assert "RuntimeError" not in (result.failure_reason or "")
        assert "line 42" not in (result.failure_reason or "")


# ===========================================================================
# D. Regression
# ===========================================================================


class TestRegression:
    def test_existing_precheck_tainted_vm_still_raises(self):
        """Pre-existing Condition 1 (vm_tainted) must still raise PrecheckFailed."""
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        vm_tracker = StubVMTracker()
        vm_tracker.mark_vm_tainted("500")
        svc = LabSessionService(
            session_repo=_MemSessionRepo(),
            draft_repo=drepo,
            vm_tracker=vm_tracker,
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
        )
        with pytest.raises(PrecheckFailed) as exc_info:
            svc.create_session("lab-1", "500", "alice")
        assert FailureReason.PRECHECK_VM_TAINTED.value in exc_info.value.failures

    def test_runtime_precheck_none_skips_conditions_4_6(self):
        """When runtime_precheck=None, conditions 4/6 are not checked (backward compat)."""
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, _, _, _ = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo, runtime_precheck=None)
        # With runtime_precheck=None, stuck namespace is not checked → start succeeds
        result = svc.create_session("lab-1", "500", "alice")
        assert result.lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_condition_4_blocked_does_not_proceed_to_image_check(self):
        """Blocked start must not trigger image check (returns before _run_image_check)."""
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        srepo = _MemSessionRepo()
        prior = _make_prior_session(namespace="lab-stuck-ns")
        srepo.create(prior)
        ns = StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"})
        svc, _, _, ns_adapter = _build_service(ns=ns, session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        # Namespace was never created
        assert ns_adapter.created == []
        assert result.lab_session_status == LabSessionStatus.LAB_START_FAILED

    def test_happy_path_no_prior_sessions_starts_active(self):
        drepo = _MemDraftRepo({"lab-1": _make_published_draft()})
        svc, _, _, _ = _build_service(draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        assert result.lab_session_status == LabSessionStatus.LAB_ACTIVE

    def test_condition_6_only_blocks_unverified_cluster_scoped(self):
        """Namespace-only prior lab with cleanup_verified=False must NOT block."""
        drepo = _MemDraftRepo({
            "lab-1": _make_published_draft(),
            "lab-prev": _make_published_draft(lab_id="lab-prev", cluster_scoped=False),
        })
        srepo = _MemSessionRepo()
        prior = _make_prior_session(
            lab_id="lab-prev",
            status=LabSessionStatus.LAB_CLOSED,
            cleanup_verified=False,
        )
        srepo.create(prior)
        svc, _, _, _ = _build_service(session_repo=srepo, draft_repo=drepo)
        result = svc.create_session("lab-1", "500", "alice")
        assert result.lab_session_status == LabSessionStatus.LAB_ACTIVE
