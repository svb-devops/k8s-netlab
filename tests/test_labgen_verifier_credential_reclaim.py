"""
Verifier Credential Reclaim Hardening — tests.

Validates:
  A. VerifierCredentialReclaimer unit tests (path safety, idempotency, failure modes)
  B. Complete cleanup integration (success + credential failure)
  C. Abort cleanup integration
  D. no-namespace session with credential reclaim
  E. Audit event content (safe metadata only)
  F. Learner snapshot shows safe CLEANUP_FAILED issue
  G. Regression (reclaimer=None backward-compatible with existing cleanup paths)
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.lab_session_service import (
    LabSessionService,
    StubVMTracker,
    VMTrackerPort,
)
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ConnectionState,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeAuditEventType,
    RuntimeRequirements,
    Step,
)
from backend.labgen.namespace_lifecycle import (
    NamespaceLifecyclePort,
    StubNamespaceLifecycleAdapter,
)
from backend.labgen.verifier_credentials import (
    CredentialReclaimResult,
    VerifierCredentialReclaimer,
    VerifierCredentialStore,
)

pytestmark = pytest.mark.static

_KUBECONFIG = "apiVersion: v1\nclusters: []\nkind: Config\n"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> VerifierCredentialStore:
    return VerifierCredentialStore(base_dir=tmp_path / "creds")


@pytest.fixture()
def reclaimer(store: VerifierCredentialStore) -> VerifierCredentialReclaimer:
    return VerifierCredentialReclaimer(store)


def _make_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Reclaim Test Lab",
        description="desc",
        estimated_duration_minutes=20,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="w", do="d", observe="o",
            explain=ExplainField(concept="c", observation="o"),
        )],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.PUBLISHED,
    )
    defaults.update(kw)
    return LabDraft(**defaults)


def _make_session(**kw) -> LabSessionState:
    defaults = dict(
        lab_id="lab-1",
        vm_id="501",
        student_username="student1",
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
        namespace="lab-test-ns",
        ready_to_complete=True,
    )
    defaults.update(kw)
    return LabSessionState(**defaults)


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


class _MemDraftRepo:
    def __init__(self, drafts: dict[str, LabDraft] | None = None) -> None:
        self._store: dict[str, LabDraft] = dict(drafts or {})

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft


class _RecordingNamespaceAdapter(NamespaceLifecyclePort):
    def __init__(self, delete_succeeds: bool = True) -> None:
        self._delete_succeeds = delete_succeeds

    def create_namespace(self, ns: str) -> bool:
        return True

    def namespace_exists(self, ns: str) -> bool:
        return True

    def delete_namespace(self, ns: str) -> bool:
        return self._delete_succeeds

    def is_namespace_deleted(self, ns: str) -> bool:
        return self._delete_succeeds

    def ensure_verifier_rolebinding(self, ns: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, ns: str) -> bool:
        return True


class _RecordingVMTracker(VMTrackerPort):
    def __init__(self) -> None:
        self._tainted: set[str] = set()
        self.mark_calls: list[str] = []

    def vm_exists(self, vm_id: str) -> bool:
        return True

    def is_vm_owned_by(self, vm_id: str, username: str) -> bool:
        return True

    def mark_vm_tainted(self, vm_id: str) -> None:
        self._tainted.add(vm_id)
        self.mark_calls.append(vm_id)

    def is_vm_tainted(self, vm_id: str) -> bool:
        return vm_id in self._tainted


class _StubImageResolver:
    def needs_recheck(self, img) -> bool:
        return False

    def check_registry_existence(self, img):
        return img


def _make_svc(
    session_repo: _MemSessionRepo,
    *,
    ns_lifecycle: NamespaceLifecyclePort | None = None,
    vm_tracker: VMTrackerPort | None = None,
    credential_reclaimer: VerifierCredentialReclaimer | None = None,
    audit_svc=None,
) -> LabSessionService:
    return LabSessionService(
        session_repo=session_repo,
        draft_repo=_MemDraftRepo({"lab-1": _make_draft()}),
        vm_tracker=vm_tracker or _RecordingVMTracker(),
        ns_lifecycle=ns_lifecycle or StubNamespaceLifecycleAdapter(),
        image_resolver=_StubImageResolver(),
        audit_svc=audit_svc,
        credential_reclaimer=credential_reclaimer,
    )


def _save_cred(store: VerifierCredentialStore, vm_id: str = "501") -> None:
    from datetime import datetime, timezone
    from backend.labgen.models import VerifierCredentialMetadata
    meta = VerifierCredentialMetadata(
        vm_id=vm_id,
        created_at=datetime.now(tz=timezone.utc),
        expires_at=datetime.now(tz=timezone.utc),
        k3s_endpoint="https://k3s-test.local:6443",
        credential_generation=1,
    )
    store.save(vm_id, _KUBECONFIG, meta)


# ---------------------------------------------------------------------------
# A. VerifierCredentialReclaimer unit tests
# ---------------------------------------------------------------------------


class TestVerifierCredentialReclaimerUnit:
    def test_deletes_existing_credential_directory(self, store, reclaimer):
        _save_cred(store, "501")
        assert store.exists("501")
        result = reclaimer.reclaim_for_vm("501")
        assert result.success is True
        assert not store.exists("501")

    def test_missing_directory_is_idempotent_success(self, reclaimer):
        result = reclaimer.reclaim_for_vm("999")
        assert result.success is True
        assert result.failure_reason is None

    def test_double_reclaim_is_idempotent(self, store, reclaimer):
        _save_cred(store, "501")
        r1 = reclaimer.reclaim_for_vm("501")
        r2 = reclaimer.reclaim_for_vm("501")
        assert r1.success is True
        assert r2.success is True

    def test_rejects_non_numeric_vm_id(self, reclaimer):
        result = reclaimer.reclaim_for_vm("abc")
        assert result.success is False
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_PATH_UNSAFE.value

    def test_rejects_dotdot_vm_id(self, reclaimer):
        result = reclaimer.reclaim_for_vm("../etc")
        assert result.success is False
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_PATH_UNSAFE.value

    def test_rejects_slash_in_vm_id(self, reclaimer):
        result = reclaimer.reclaim_for_vm("/etc/passwd")
        assert result.success is False
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_PATH_UNSAFE.value

    def test_rejects_symlink_at_vm_dir(self, tmp_path):
        base = tmp_path / "creds"
        base.mkdir()
        # Create a symlink at base/501 pointing outside base
        outside = tmp_path / "outside"
        outside.mkdir()
        (base / "501").symlink_to(outside)
        store = VerifierCredentialStore(base_dir=base)
        rec = VerifierCredentialReclaimer(store)
        result = rec.reclaim_for_vm("501")
        assert result.success is False
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_PATH_UNSAFE.value
        # symlink must not have been followed/deleted
        assert (base / "501").is_symlink()
        assert outside.exists()

    def test_delete_failure_returns_delete_failed(self, store, reclaimer):
        _save_cred(store, "501")
        with patch("shutil.rmtree", side_effect=OSError("permission denied")):
            result = reclaimer.reclaim_for_vm("501")
        assert result.success is False
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_DELETE_FAILED.value

    def test_result_never_contains_path(self, store, reclaimer):
        _save_cred(store, "501")
        result = reclaimer.reclaim_for_vm("501")
        # failure_reason is None on success — no path info
        assert result.failure_reason is None

    def test_failure_reason_is_machine_code_not_raw_error(self, store, reclaimer):
        _save_cred(store, "501")
        with patch("shutil.rmtree", side_effect=OSError("permission denied: /secret/path")):
            result = reclaimer.reclaim_for_vm("501")
        # failure_reason must be the stable machine code, not a raw OSError string
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_DELETE_FAILED.value
        assert "/secret/path" not in (result.failure_reason or "")

    def test_result_never_contains_credential_content(self, store, reclaimer):
        _save_cred(store, "501")
        result = reclaimer.reclaim_for_vm("501")
        # CredentialReclaimResult has only success + failure_reason — no kubeconfig/content
        assert not hasattr(result, "kubeconfig")
        assert not hasattr(result, "content")
        assert not hasattr(result, "path")


# ---------------------------------------------------------------------------
# B. Complete cleanup integration
# ---------------------------------------------------------------------------


class TestCompleteCleanupWithCredentialReclaim:
    def test_complete_success_deletes_credential_file(self, store, reclaimer):
        _save_cred(store, "501")
        assert store.exists("501")

        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert result.cleanup_verified is True
        assert not store.exists("501")

    def test_complete_success_no_credential_file_still_closes(self, store, reclaimer):
        # No credential file exists — idempotent success
        assert not store.exists("501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_credential_delete_failure_blocks_complete_success(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            result = svc.complete_session(session.session_id)

        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_DELETE_FAILED.value
        assert result.cleanup_verified is False

    def test_credential_delete_failure_marks_vm_tainted(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        vm_tracker = _RecordingVMTracker()
        svc = _make_svc(repo, credential_reclaimer=reclaimer, vm_tracker=vm_tracker)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            svc.complete_session(session.session_id)

        assert "501" in vm_tracker.mark_calls

    def test_complete_response_does_not_leak_credential_path(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        with patch("shutil.rmtree", side_effect=OSError("oops")):
            result = svc.complete_session(session.session_id)

        result_json = result.model_dump_json()
        # failure_reason is machine code only — no path content
        assert "creds" not in result_json
        assert "kubeconfig" not in result_json
        assert "vm_creds" not in result_json


# ---------------------------------------------------------------------------
# C. Abort cleanup integration
# ---------------------------------------------------------------------------


class TestAbortCleanupWithCredentialReclaim:
    def test_abort_success_deletes_credential_file(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501")
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert not store.exists("501")

    def test_abort_credential_failure_marks_cleanup_failed(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501")
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            result = svc.abort_session(session.session_id)

        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_DELETE_FAILED.value

    def test_abort_credential_failure_marks_vm_tainted(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501")
        repo.create(session)
        vm_tracker = _RecordingVMTracker()
        svc = _make_svc(repo, credential_reclaimer=reclaimer, vm_tracker=vm_tracker)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            svc.abort_session(session.session_id)

        assert "501" in vm_tracker.mark_calls

    def test_abort_does_not_need_ready_flag(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=False)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert not store.exists("501")


# ---------------------------------------------------------------------------
# D. No-namespace session with credential reclaim
# ---------------------------------------------------------------------------


class TestNoNamespaceSessionCredentialReclaim:
    def test_no_namespace_success_deletes_credential(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", namespace=None, ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert not store.exists("501")

    def test_no_namespace_credential_failure_marks_cleanup_failed(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", namespace=None, ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        with patch("shutil.rmtree", side_effect=OSError("io error")):
            result = svc.complete_session(session.session_id)

        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED
        assert result.failure_reason == FailureReason.VERIFIER_CREDENTIAL_DELETE_FAILED.value


# ---------------------------------------------------------------------------
# E. Audit event content
# ---------------------------------------------------------------------------


class TestAuditEventContent:
    def test_credential_failure_produces_cleanup_failed_event(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        audit_svc = MagicMock()
        svc = _make_svc(repo, credential_reclaimer=reclaimer, audit_svc=audit_svc)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            svc.complete_session(session.session_id)

        cleanup_failed_calls = [
            c for c in audit_svc.record.call_args_list
            if c.args[1] == RuntimeAuditEventType.CLEANUP_FAILED
        ]
        assert len(cleanup_failed_calls) == 1

    def test_credential_failure_audit_has_safe_cleanup_phase(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        audit_svc = MagicMock()
        svc = _make_svc(repo, credential_reclaimer=reclaimer, audit_svc=audit_svc)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            svc.complete_session(session.session_id)

        cleanup_call = next(
            c for c in audit_svc.record.call_args_list
            if c.args[1] == RuntimeAuditEventType.CLEANUP_FAILED
        )
        metadata = cleanup_call.kwargs.get("metadata") or {}
        assert metadata.get("cleanup_phase") == "verifier_credential_reclaim"

    def test_credential_failure_audit_metadata_no_path(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        audit_svc = MagicMock()
        svc = _make_svc(repo, credential_reclaimer=reclaimer, audit_svc=audit_svc)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            svc.complete_session(session.session_id)

        for call in audit_svc.record.call_args_list:
            metadata = call.kwargs.get("metadata") or {}
            meta_str = str(metadata)
            assert "creds" not in meta_str
            assert "kubeconfig" not in meta_str
            assert "vm_creds" not in meta_str

    def test_credential_failure_produces_vm_tainted_event(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        audit_svc = MagicMock()
        svc = _make_svc(repo, credential_reclaimer=reclaimer, audit_svc=audit_svc)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            svc.complete_session(session.session_id)

        tainted_calls = [
            c for c in audit_svc.record.call_args_list
            if c.args[1] == RuntimeAuditEventType.VM_TAINTED
        ]
        assert len(tainted_calls) == 1

    def test_success_produces_cleanup_success_event(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        audit_svc = MagicMock()
        svc = _make_svc(repo, credential_reclaimer=reclaimer, audit_svc=audit_svc)

        svc.complete_session(session.session_id)

        success_calls = [
            c for c in audit_svc.record.call_args_list
            if c.args[1] == RuntimeAuditEventType.CLEANUP_SUCCESS
        ]
        assert len(success_calls) == 1

    def test_success_produces_no_cleanup_failed_event(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        audit_svc = MagicMock()
        svc = _make_svc(repo, credential_reclaimer=reclaimer, audit_svc=audit_svc)

        svc.complete_session(session.session_id)

        failed_calls = [
            c for c in audit_svc.record.call_args_list
            if c.args[1] == RuntimeAuditEventType.CLEANUP_FAILED
        ]
        assert len(failed_calls) == 0


# ---------------------------------------------------------------------------
# F. Learner snapshot — credential failure shows safe CLEANUP_FAILED issue
# ---------------------------------------------------------------------------


class TestLearnerSnapshotCredentialFailure:
    def test_cleanup_failed_shows_cleanup_failed_issue(self, store, reclaimer):
        from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService

        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            result = svc.complete_session(session.session_id)

        draft_repo = _MemDraftRepo({"lab-1": _make_draft()})
        snapshot_svc = LearnerSessionSnapshotService(
            session_repo=repo, draft_repo=draft_repo
        )
        snapshot = snapshot_svc.build_snapshot(
            result.session_id, actor_user="student1", is_admin=False
        )
        issue_codes = [i.code for i in snapshot.issues]
        assert "CLEANUP_FAILED" in issue_codes

    def test_cleanup_failed_message_does_not_leak_path(self, store, reclaimer):
        from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService

        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            result = svc.complete_session(session.session_id)

        draft_repo = _MemDraftRepo({"lab-1": _make_draft()})
        snapshot_svc = LearnerSessionSnapshotService(
            session_repo=repo, draft_repo=draft_repo
        )
        snapshot = snapshot_svc.build_snapshot(
            result.session_id, actor_user="student1", is_admin=False
        )
        snapshot_json = snapshot.model_dump_json()
        assert "creds" not in snapshot_json
        assert "kubeconfig" not in snapshot_json
        assert "vm_creds" not in snapshot_json

    def test_cleanup_failed_runtime_summary_shows_failed(self, store, reclaimer):
        from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService

        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo, credential_reclaimer=reclaimer)

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            result = svc.complete_session(session.session_id)

        draft_repo = _MemDraftRepo({"lab-1": _make_draft()})
        snapshot_svc = LearnerSessionSnapshotService(
            session_repo=repo, draft_repo=draft_repo
        )
        snapshot = snapshot_svc.build_snapshot(
            result.session_id, actor_user="student1", is_admin=False
        )
        assert snapshot.runtime_summary.cleanup_status == "failed"
        assert snapshot.runtime_summary.tainted is True
        # failure_reason in snapshot is the stable machine code
        assert snapshot.runtime_summary.failure_reason == FailureReason.VERIFIER_CREDENTIAL_DELETE_FAILED.value


# ---------------------------------------------------------------------------
# G. Regression — reclaimer=None is backward-compatible
# ---------------------------------------------------------------------------


class TestSharedVMCredentialReclaimExemption:
    """Shared/staging VMs (e.g. home_lab_mvp VM 401) are reused across many
    sequential student sessions. Reclaiming verifier credentials after every
    single session's cleanup destroys credentials the NEXT session on the
    same VM needs — discovered during Real Human Re-validation for Labs 2-4
    v0.1 when Lab 3 failed at step 1 with credential_missing right after
    Lab 2's cleanup ran on the same shared VM 401.
    """

    def test_exempt_vm_credential_survives_complete_cleanup(self, store, reclaimer):
        _save_cred(store, "401")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="401", ready_to_complete=True)
        repo.create(session)
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({"lab-1": _make_draft()}),
            vm_tracker=_RecordingVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
            credential_reclaimer=reclaimer,
            credential_reclaim_exempt_vm_ids=frozenset({"401"}),
        )

        result = svc.complete_session(session.session_id)

        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert store.exists("401")

    def test_exempt_vm_credential_survives_abort_cleanup(self, store, reclaimer):
        _save_cred(store, "401")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="401")
        repo.create(session)
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({"lab-1": _make_draft()}),
            vm_tracker=_RecordingVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
            credential_reclaimer=reclaimer,
            credential_reclaim_exempt_vm_ids=frozenset({"401"}),
        )

        result = svc.abort_session(session.session_id)

        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert store.exists("401")

    def test_non_exempt_vm_still_reclaimed(self, store, reclaimer):
        _save_cred(store, "501")
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = LabSessionService(
            session_repo=repo,
            draft_repo=_MemDraftRepo({"lab-1": _make_draft()}),
            vm_tracker=_RecordingVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=_StubImageResolver(),
            credential_reclaimer=reclaimer,
            credential_reclaim_exempt_vm_ids=frozenset({"401"}),
        )

        result = svc.complete_session(session.session_id)

        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED
        assert not store.exists("501")


class TestRegressionReclaimerNone:
    def test_complete_without_reclaimer_still_closes(self):
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        svc = _make_svc(repo)  # credential_reclaimer=None (default)

        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_abort_without_reclaimer_still_closes(self):
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501")
        repo.create(session)
        svc = _make_svc(repo)

        result = svc.abort_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_namespace_failure_without_reclaimer_marks_tainted(self):
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        vm_tracker = _RecordingVMTracker()
        svc = _make_svc(
            repo,
            ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=False),
            vm_tracker=vm_tracker,
        )

        result = svc.complete_session(session.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED
        assert result.failure_reason == FailureReason.NAMESPACE_CLEANUP_FAILED.value
        assert "501" in vm_tracker.mark_calls

    def test_both_namespace_and_credential_fail_uses_namespace_reason(self, store, reclaimer):
        # When namespace deletion fails AND credential reclaim also fails,
        # namespace failure_reason takes precedence.
        repo = _MemSessionRepo()
        session = _make_session(vm_id="501", ready_to_complete=True)
        repo.create(session)
        _save_cred(store, "501")
        svc = _make_svc(
            repo,
            ns_lifecycle=_RecordingNamespaceAdapter(delete_succeeds=False),
            credential_reclaimer=reclaimer,
        )

        with patch("shutil.rmtree", side_effect=OSError("locked")):
            result = svc.complete_session(session.session_id)

        assert result.lab_session_status == LabSessionStatus.LAB_CLEANUP_FAILED
        assert result.failure_reason == FailureReason.NAMESPACE_CLEANUP_FAILED.value
