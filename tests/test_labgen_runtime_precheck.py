"""
RuntimePrecheckService unit tests — Contract §11 conditions 4 and 6.

Validates:
  A. Precheck service
     - condition 4 pass / block / dependency exception → BLOCKED safe issue
     - condition 6 pass / block / draft-not-found fail-closed / dependency exception
     - multiple failures aggregate into single result
     - issue messages are sanitized (no tokens / secrets / tracebacks)
     - result schema has required fields

  B. _sanitize_message safety net
     - strips Bearer tokens, API keys, JWT-shaped strings, long base64, passwords,
       private_key labels, traceback headers
"""

from __future__ import annotations

import re
from typing import Optional

import pytest

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ClusterScopedResource,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    Step,
)
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
from backend.labgen.runtime_precheck import (
    RuntimePrecheckCondition,
    RuntimePrecheckService,
    RuntimePrecheckStatus,
    _sanitize_message,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# In-memory stubs
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


class _RaisingNsAdapter(StubNamespaceLifecycleAdapter):
    """Raises RuntimeError from is_namespace_stuck_terminating."""

    def is_namespace_stuck_terminating(self, namespace: str, threshold_seconds: int = 300) -> bool:
        raise RuntimeError("connection failed: Bearer sk-abc123xyz456789012345678")


class _RaisingSessionRepo:
    """Raises RuntimeError from list_by_vm_id (used by condition checks)."""

    def list_by_student(self, username: str) -> list[LabSessionState]:
        raise RuntimeError("db error: password=s3cr3t_P@$$word token=eyJsomething")

    def list_by_vm_id(self, vm_id: str) -> list[LabSessionState]:
        raise RuntimeError("db error: password=s3cr3t_P@$$word token=eyJsomething")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(
    lab_id: str = "lab-1",
    cluster_scoped: bool = False,
    **kw,
) -> LabDraft:
    csr: list[ClusterScopedResource] = (
        [ClusterScopedResource(kind="ClusterRole", name="lab-cr", api_group="rbac.authorization.k8s.io", cleanup="kubectl delete clusterrole lab-cr")]
        if cluster_scoped
        else []
    )
    defaults = dict(
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
    defaults.update(kw)
    return LabDraft(**defaults)


def _make_session(
    lab_id: str = "lab-1",
    vm_id: str = "500",
    username: str = "alice",
    status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
    namespace: Optional[str] = "lab-prev-ns",
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


def _build_svc(
    ns: StubNamespaceLifecycleAdapter | None = None,
    sessions: list[LabSessionState] | None = None,
    drafts: dict[str, LabDraft] | None = None,
    session_repo=None,
) -> RuntimePrecheckService:
    ns_adapter = ns or StubNamespaceLifecycleAdapter()
    repo = session_repo or _MemSessionRepo()
    draft_repo = _MemDraftRepo(drafts)
    if sessions:
        for s in sessions:
            repo.create(s)
    return RuntimePrecheckService(
        ns_lifecycle=ns_adapter,
        session_repo=repo,
        draft_repo=draft_repo,
    )


# ===========================================================================
# A. Precheck service
# ===========================================================================


# --- Condition 4 ------------------------------------------------------------


class TestCondition4:
    def test_passes_when_no_prior_sessions(self):
        svc = _build_svc()
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed
        assert RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING in result.passed_conditions

    def test_passes_when_no_namespace_on_prior_session(self):
        session = _make_session(namespace=None)
        svc = _build_svc(sessions=[session])
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed
        assert RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING in result.passed_conditions

    def test_passes_when_namespace_not_stuck(self):
        session = _make_session(namespace="lab-prev-ns")
        svc = _build_svc(
            ns=StubNamespaceLifecycleAdapter(),
            sessions=[session],
        )
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed
        assert RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING in result.passed_conditions

    def test_blocked_when_namespace_stuck(self):
        session = _make_session(namespace="lab-stuck-ns")
        svc = _build_svc(
            ns=StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"}),
            sessions=[session],
        )
        result = svc.check(vm_id="500", student_username="alice")
        assert not result.passed
        assert result.status == RuntimePrecheckStatus.BLOCKED
        assert RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING in result.blocked_conditions
        assert len(result.issues) >= 1
        issue = next(i for i in result.issues if i.condition == RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING)
        assert issue.code == FailureReason.RUNTIME_PRECHECK_CONDITION_4_FAILED.value
        assert issue.severity == "blocking"

    def test_only_checks_sessions_for_this_vm(self):
        """Sessions on a different VM must not affect checks for vm_id=500."""
        s_other_vm = _make_session(vm_id="999", namespace="lab-other-ns")
        svc = _build_svc(
            ns=StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-other-ns"}),
            sessions=[s_other_vm],
        )
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed

    def test_blocks_stuck_namespace_from_prior_owner(self):
        """VM reassignment: prior owner's stuck namespace must block new student."""
        s_prior_owner = _make_session(vm_id="500", username="bob", namespace="lab-old-ns")
        svc = _build_svc(
            ns=StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-old-ns"}),
            sessions=[s_prior_owner],
        )
        # New student "alice" queries the same VM — should be blocked by bob's stuck NS
        result = svc.check(vm_id="500", student_username="alice")
        assert not result.passed
        assert RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING in result.blocked_conditions

    def test_dependency_exception_blocks_fail_closed(self):
        session = _make_session(namespace="lab-prev-ns")
        svc = _build_svc(
            ns=_RaisingNsAdapter(),
            sessions=[session],
        )
        result = svc.check(vm_id="500", student_username="alice")
        assert not result.passed
        assert RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING in result.blocked_conditions
        issue = next(i for i in result.issues if i.condition == RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING)
        assert issue.code == FailureReason.RUNTIME_PRECHECK_CONDITION_4_FAILED.value

    def test_dependency_exception_message_is_safe(self):
        session = _make_session(namespace="lab-prev-ns")
        svc = _build_svc(
            ns=_RaisingNsAdapter(),
            sessions=[session],
        )
        result = svc.check(vm_id="500", student_username="alice")
        issue = next(i for i in result.issues if i.condition == RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING)
        # Must not leak the Bearer token from the raised exception
        assert "sk-abc" not in issue.message
        assert "Bearer" not in issue.message
        assert "Traceback" not in issue.message


# --- Condition 6 ------------------------------------------------------------


class TestCondition6:
    def test_passes_when_no_prior_sessions(self):
        svc = _build_svc()
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed
        assert RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED in result.passed_conditions

    def test_passes_when_cleanup_verified(self):
        session = _make_session(status=LabSessionStatus.LAB_ACTIVE, cleanup_verified=True)
        draft = _make_draft(cluster_scoped=True)
        svc = _build_svc(sessions=[session], drafts={"lab-1": draft})
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed
        assert RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED in result.passed_conditions

    def test_passes_when_draft_has_no_cluster_scoped(self):
        session = _make_session(status=LabSessionStatus.LAB_ACTIVE, cleanup_verified=False)
        draft = _make_draft(cluster_scoped=False)
        svc = _build_svc(sessions=[session], drafts={"lab-1": draft})
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed

    def test_blocked_when_cluster_scoped_not_cleaned(self):
        session = _make_session(status=LabSessionStatus.LAB_ACTIVE, cleanup_verified=False)
        draft = _make_draft(cluster_scoped=True)
        svc = _build_svc(sessions=[session], drafts={"lab-1": draft})
        result = svc.check(vm_id="500", student_username="alice")
        assert not result.passed
        assert RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED in result.blocked_conditions
        issue = next(i for i in result.issues if i.condition == RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED)
        assert issue.code == FailureReason.RUNTIME_PRECHECK_CONDITION_6_FAILED.value
        assert issue.severity == "blocking"

    def test_blocked_fail_closed_when_draft_not_found(self):
        """Active session with unverified cleanup and missing draft must block fail-closed."""
        session = _make_session(status=LabSessionStatus.LAB_ACTIVE, cleanup_verified=False)
        svc = _build_svc(sessions=[session], drafts={})
        result = svc.check(vm_id="500", student_username="alice")
        assert not result.passed
        assert RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED in result.blocked_conditions
        issue = next(i for i in result.issues if i.condition == RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED)
        assert issue.code == FailureReason.RUNTIME_PRECHECK_CONDITION_6_FAILED.value

    def test_skips_lab_start_failed_sessions(self):
        """LAB_START_FAILED sessions never deployed runtime resources — must be skipped."""
        session = _make_session(
            status=LabSessionStatus.LAB_START_FAILED,
            cleanup_verified=False,
        )
        svc = _build_svc(sessions=[session], drafts={})
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed

    def test_skips_sessions_without_namespace(self):
        """Sessions with namespace=None never reached namespace creation — skip."""
        session = _make_session(namespace=None, cleanup_verified=False)
        draft = _make_draft(cluster_scoped=True)
        svc = _build_svc(sessions=[session], drafts={"lab-1": draft})
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed

    def test_only_checks_sessions_for_this_vm(self):
        session = _make_session(vm_id="999", cleanup_verified=False)
        draft = _make_draft(cluster_scoped=True)
        svc = _build_svc(sessions=[session], drafts={"lab-1": draft})
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed

    def test_skips_lab_closed_with_cleanup_not_verified(self):
        """LAB_CLOSED + cleanup_verified=False must not permanently block the VM.

        This handles sessions written before the cleanup_verified field existed
        (migration scenario) and sessions closed via a code path that neglected
        to set the flag.  LAB_CLOSED is a definitively terminal state.
        """
        session = _make_session(
            status=LabSessionStatus.LAB_CLOSED,
            cleanup_verified=False,
        )
        draft = _make_draft(cluster_scoped=True)
        svc = _build_svc(sessions=[session], drafts={"lab-1": draft})
        result = svc.check(vm_id="500", student_username="alice")
        assert result.passed

    def test_dependency_exception_blocks_fail_closed(self):
        svc = _build_svc(session_repo=_RaisingSessionRepo())
        result = svc.check(vm_id="500", student_username="alice")
        assert not result.passed
        assert RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED in result.blocked_conditions
        issue = next(i for i in result.issues if i.condition == RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED)
        assert issue.code == FailureReason.RUNTIME_PRECHECK_CONDITION_6_FAILED.value

    def test_dependency_exception_message_is_safe(self):
        svc = _build_svc(session_repo=_RaisingSessionRepo())
        result = svc.check(vm_id="500", student_username="alice")
        issue = next(i for i in result.issues if i.condition == RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED)
        assert "password" not in issue.message.lower() or "s3cr3t" not in issue.message
        assert "token" not in issue.message.lower() or "eyJ" not in issue.message
        assert "Traceback" not in issue.message


# --- Multi-condition and schema tests ----------------------------------------


class TestMultiConditionAndSchema:
    def test_both_conditions_blocked_aggregates(self):
        session = _make_session(namespace="lab-stuck-ns", cleanup_verified=False)
        draft = _make_draft(cluster_scoped=True)
        svc = _build_svc(
            ns=StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"}),
            sessions=[session],
            drafts={"lab-1": draft},
        )
        result = svc.check(vm_id="500", student_username="alice")
        assert result.status == RuntimePrecheckStatus.BLOCKED
        assert len(result.blocked_conditions) == 2
        assert len(result.issues) == 2
        codes = {i.code for i in result.issues}
        assert FailureReason.RUNTIME_PRECHECK_CONDITION_4_FAILED.value in codes
        assert FailureReason.RUNTIME_PRECHECK_CONDITION_6_FAILED.value in codes

    def test_result_schema_has_required_fields(self):
        svc = _build_svc()
        result = svc.check(vm_id="500", student_username="alice")
        assert result.status is not None
        assert isinstance(result.passed_conditions, list)
        assert isinstance(result.blocked_conditions, list)
        assert isinstance(result.issues, list)
        assert result.checked_at is not None

    def test_issue_schema_has_required_fields(self):
        session = _make_session(namespace="lab-stuck-ns", cleanup_verified=False)
        draft = _make_draft(cluster_scoped=True)
        svc = _build_svc(
            ns=StubNamespaceLifecycleAdapter(stuck_terminating_namespaces={"lab-stuck-ns"}),
            sessions=[session],
            drafts={"lab-1": draft},
        )
        result = svc.check(vm_id="500", student_username="alice")
        for issue in result.issues:
            assert issue.code
            assert issue.message
            assert issue.severity == "blocking"
            assert issue.condition is not None
            assert issue.source

    def test_passed_result_has_all_conditions_in_passed(self):
        svc = _build_svc()
        result = svc.check(vm_id="500", student_username="alice")
        assert RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING in result.passed_conditions
        assert RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED in result.passed_conditions
        assert len(result.blocked_conditions) == 0
        assert len(result.issues) == 0


# ===========================================================================
# B. _sanitize_message safety net
# ===========================================================================


class TestSanitizeMessage:
    def test_strips_anthropic_api_key(self):
        msg = "error: sk-ant-api03-someverylongkeyvalue12345678901234 returned"
        out = _sanitize_message(msg)
        assert "sk-ant-api03" not in out
        assert "[REDACTED]" in out

    def test_strips_openai_api_key(self):
        msg = "error: sk-abcdefghijklmnopqrstuvwxyz123456 was invalid"
        out = _sanitize_message(msg)
        assert "sk-abcdefghij" not in out

    def test_strips_bearer_token(self):
        msg = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.signature"
        out = _sanitize_message(msg)
        assert "eyJhbGciOiJSUzI1NiJ9" not in out

    def test_strips_jwt_shaped_string(self):
        msg = "token was eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.xxxxx"
        out = _sanitize_message(msg)
        assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in out

    def test_strips_long_base64(self):
        long_b64 = "A" * 50 + "=="
        msg = f"kubeconfig data: {long_b64}"
        out = _sanitize_message(msg)
        assert long_b64 not in out

    def test_strips_password_label(self):
        msg = "connect error: password=super_secret_123"
        out = _sanitize_message(msg)
        assert "super_secret_123" not in out

    def test_strips_private_key_label(self):
        msg = "private_key=BEGIN_RSA_PRIVATE_KEY_CONTENT"
        out = _sanitize_message(msg)
        assert "BEGIN_RSA_PRIVATE_KEY_CONTENT" not in out

    def test_strips_traceback(self):
        msg = "Traceback (most recent call last):\n  File test.py, line 1\nRuntimeError: db failure"
        out = _sanitize_message(msg)
        assert "Traceback" not in out or "[REDACTED:traceback]" in out
        assert "RuntimeError: db failure" not in out

    def test_safe_message_unchanged(self):
        msg = "Prior namespace is stuck in Terminating state"
        out = _sanitize_message(msg)
        assert out == msg

    def test_returns_string(self):
        assert isinstance(_sanitize_message("hello"), str)
