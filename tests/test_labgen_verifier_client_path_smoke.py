"""
Unit tests for scripts/labgen_verifier_client_path_smoke.py.

All tests are static — no real K8s, Proxmox, or filesystem calls.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

from backend.labgen.models import LabDraft, LabSessionState, LabSessionStatus, VerifyResult
from backend.labgen.repository import LabDraftRepository
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.lab_session_service import StubVMTracker
from backend.labgen.step_progression_service import StepCheckResponse
from backend.labgen.verifier import K8sVerifierClientPort
from backend.labgen.verifier_credentials import VerifierCredentialStore

# Import the smoke script module
import importlib.util
import sys

_SMOKE_PATH = Path(__file__).parent.parent / "scripts" / "labgen_verifier_client_path_smoke.py"
_spec = importlib.util.spec_from_file_location("smoke_script", _SMOKE_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["smoke_script"] = _mod  # must register before exec so @dataclass resolves __module__
_spec.loader.exec_module(_mod)

preflight = _mod.preflight
seed_smoke_draft = _mod.seed_smoke_draft
init_verifier_creds = _mod.init_verifier_creds
build_services = _mod.build_services
run_smoke = _mod.run_smoke
cleanup_staging = _mod.cleanup_staging
SmokeResult = _mod.SmokeResult
SMOKE_LAB_ID = _mod.SMOKE_LAB_ID
SMOKE_VM_ID = _mod.SMOKE_VM_ID
SMOKE_STUDENT = _mod.SMOKE_STUDENT
STEP_ID = _mod.STEP_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_SMOKE_DRAFT = {
    "schema_version": "1.0",
    "lab_id": SMOKE_LAB_ID,
    "source_article_id": "internal-verifier-client-smoke",
    "title": "internal-verifier-client-smoke",
    "description": "Smoke lab",
    "estimated_duration_minutes": 5,
    "prerequisites": [],
    "runtime_requirements": {
        "schema_version": "1.0",
        "runtime": "dedicated_vm",
        "namespace_template": "lab-{{lab_id}}-{{session_id}}",
        "cluster_scoped_resources": [],
        "pollution_level": "namespace_only",
        "shared_namespace_candidate": True,
        "shared_namespace_candidate_reason": "",
    },
    "steps": [
        {
            "schema_version": "1.0",
            "step_id": "step-verify-namespace",
            "order": 1,
            "why": "Verify",
            "do": "Internal smoke",
            "commands": [],
            "observe": "Namespace exists",
            "explain": {
                "concept": "Namespace isolation",
                "observation": "Each lab gets a dedicated namespace.",
                "confidence": "admin_verified",
                "admin_verified": True,
                "published_to_student": False,
            },
            "verify": [
                {
                    "schema_version": "1.0",
                    "verify_id": "verify-namespace-exists",
                    "type": "namespace_exists",
                    "namespace": "{{lab_namespace}}",
                    "name": "lab-namespace",
                    "label_selector": None,
                    "cluster_scope": False,
                    "supported_runtimes": ["dedicated_vm"],
                    "blocking_level_on_fail": "publish_blocking",
                    "manual_review_required": False,
                    "notes": "",
                }
            ],
        }
    ],
    "cleanup": {
        "namespace_cleanup": {
            "type": "delete_namespace",
            "namespace": "{{lab_namespace}}",
        },
        "cluster_scoped_resources": [],
        "cleanup_verified": False,
    },
    "image_resolution": [],
    "pollution_level": "namespace_only",
    "shared_namespace_candidate": True,
    "shared_namespace_candidate_reason": "",
    "publish_status": "published",
    "validator_results": [],
    "created_at": "2026-06-13T00:00:00",
    "updated_at": "2026-06-13T00:00:00",
}


@pytest.fixture()
def tmp_staging(tmp_path: Path) -> Path:
    """Create a temp staging data directory with empty JSON files."""
    for name in ["lab_drafts.json", "lab_sessions.json"]:
        (tmp_path / name).write_text("{}")
    return tmp_path


@pytest.fixture()
def production_drafts(tmp_path: Path) -> Path:
    """Write a minimal smoke draft into a temp production drafts file."""
    p = tmp_path / "prod_drafts.json"
    p.write_text(json.dumps({SMOKE_LAB_ID: MINIMAL_SMOKE_DRAFT}))
    return p


@pytest.fixture()
def tmp_cred_root(tmp_path: Path) -> Path:
    cred = tmp_path / "verifier-credentials"
    cred.mkdir(parents=True)
    return cred


# ---------------------------------------------------------------------------
# preflight tests
# ---------------------------------------------------------------------------


class TestPreflight:
    def test_ok_when_kubeconfig_and_staging_exist(self, tmp_path: Path) -> None:
        kc = tmp_path / "kubeconfig.yaml"
        kc.write_text("clusters:\n  - cluster:\n      server: https://k3s.test:6443\n    name: k3s")
        staging = tmp_path / "data-staging"
        staging.mkdir()
        (tmp_path / "prod_drafts.json").write_text("{}")
        with patch.object(_mod, "PRODUCTION_DRAFTS", tmp_path / "prod_drafts.json"):
            result = preflight(str(kc), staging)
        assert result["ok"] is True
        assert result["issues"] == []

    def test_fail_when_kubeconfig_missing(self, tmp_path: Path) -> None:
        staging = tmp_path / "data-staging"
        staging.mkdir()
        (tmp_path / "prod_drafts.json").write_text("{}")
        with patch.object(_mod, "PRODUCTION_DRAFTS", tmp_path / "prod_drafts.json"):
            result = preflight("/nonexistent/kubeconfig.yaml", staging)
        assert result["ok"] is False
        assert any("kubeconfig missing" in i for i in result["issues"])

    def test_fail_when_staging_dir_missing(self, tmp_path: Path) -> None:
        kc = tmp_path / "kubeconfig.yaml"
        kc.write_text("clusters:\n  - cluster:\n      server: https://k3s.test:6443\n    name: k3s")
        (tmp_path / "prod_drafts.json").write_text("{}")
        with patch.object(_mod, "PRODUCTION_DRAFTS", tmp_path / "prod_drafts.json"):
            result = preflight(str(kc), tmp_path / "nonexistent")
        assert result["ok"] is False
        assert any("staging data dir missing" in i for i in result["issues"])

    def test_fail_when_production_drafts_missing(self, tmp_path: Path) -> None:
        kc = tmp_path / "kubeconfig.yaml"
        kc.write_text("clusters:\n  - cluster:\n      server: https://x:6443\n    name: k3s")
        staging = tmp_path / "data-staging"
        staging.mkdir()
        with patch.object(_mod, "PRODUCTION_DRAFTS", tmp_path / "missing.json"):
            result = preflight(str(kc), staging)
        assert result["ok"] is False
        assert any("production drafts missing" in i for i in result["issues"])

    def test_fail_when_kubeconfig_empty(self, tmp_path: Path) -> None:
        kc = tmp_path / "kubeconfig.yaml"
        kc.write_text("")
        staging = tmp_path / "data-staging"
        staging.mkdir()
        (tmp_path / "prod_drafts.json").write_text("{}")
        with patch.object(_mod, "PRODUCTION_DRAFTS", tmp_path / "prod_drafts.json"):
            result = preflight(str(kc), staging)
        assert result["ok"] is False
        assert any("empty" in i for i in result["issues"])

    def test_fail_when_kubeconfig_invalid_yaml(self, tmp_path: Path) -> None:
        kc = tmp_path / "kubeconfig.yaml"
        kc.write_text("{bad yaml: [}")
        staging = tmp_path / "data-staging"
        staging.mkdir()
        (tmp_path / "prod_drafts.json").write_text("{}")
        with patch.object(_mod, "PRODUCTION_DRAFTS", tmp_path / "prod_drafts.json"):
            result = preflight(str(kc), staging)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# seed_smoke_draft tests
# ---------------------------------------------------------------------------


class TestSeedSmokeDraft:
    def test_creates_draft_when_not_exists(self, tmp_staging: Path, production_drafts: Path) -> None:
        repo = LabDraftRepository(tmp_staging / "lab_drafts.json")
        draft = seed_smoke_draft(repo, production_drafts)
        assert draft.lab_id == SMOKE_LAB_ID
        assert repo.get(SMOKE_LAB_ID) is not None

    def test_updates_draft_when_already_exists(self, tmp_staging: Path, production_drafts: Path) -> None:
        repo = LabDraftRepository(tmp_staging / "lab_drafts.json")
        seed_smoke_draft(repo, production_drafts)
        # Seed again — should not raise
        draft2 = seed_smoke_draft(repo, production_drafts)
        assert draft2.lab_id == SMOKE_LAB_ID

    def test_raises_when_smoke_draft_not_in_source(self, tmp_staging: Path, tmp_path: Path) -> None:
        source = tmp_path / "empty.json"
        source.write_text(json.dumps({"other-id": MINIMAL_SMOKE_DRAFT}))
        repo = LabDraftRepository(tmp_staging / "lab_drafts.json")
        with pytest.raises(RuntimeError, match=SMOKE_LAB_ID):
            seed_smoke_draft(repo, source)

    def test_draft_has_published_status(self, tmp_staging: Path, production_drafts: Path) -> None:
        repo = LabDraftRepository(tmp_staging / "lab_drafts.json")
        draft = seed_smoke_draft(repo, production_drafts)
        from backend.labgen.models import PublishStatus
        assert draft.publish_status == PublishStatus.PUBLISHED


# ---------------------------------------------------------------------------
# init_verifier_creds tests
# ---------------------------------------------------------------------------


class TestInitVerifierCreds:
    def test_success(self, tmp_cred_root: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        expected = {"success": True, "data": {"vm_id": 400, "credential_generation": 1, "k3s_endpoint": "<redacted>", "smoke_passed": True}, "error": None}
        with patch("smoke_script.initialize_verifier_for_vm_host_side", return_value=expected):
            result = init_verifier_creds(400, "/fake/kubeconfig.yaml", store)
        assert result["success"] is True
        assert result["data"]["credential_generation"] == 1

    def test_returns_failure_dict_on_error(self, tmp_cred_root: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        expected = {"success": False, "data": None, "error": "kubeconfig read failed: No such file"}
        with patch("smoke_script.initialize_verifier_for_vm_host_side", return_value=expected):
            result = init_verifier_creds(400, "/nonexistent", store)
        assert result["success"] is False
        assert "kubeconfig read failed" in result["error"]

    def test_passes_store_and_factory_to_underlying_fn(self, tmp_cred_root: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        stub_factory = MagicMock()
        expected = {"success": True, "data": {"credential_generation": 2}, "error": None}
        with patch("smoke_script.initialize_verifier_for_vm_host_side", return_value=expected) as mock_fn:
            init_verifier_creds(400, "/fake/kc.yaml", store, _factory=stub_factory)
        mock_fn.assert_called_once_with(400, "/fake/kc.yaml", store=store, _factory=stub_factory)


# ---------------------------------------------------------------------------
# build_services tests
# ---------------------------------------------------------------------------


class TestBuildServices:
    def test_returns_expected_keys(self, tmp_staging: Path, tmp_cred_root: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        mock_ns = MagicMock()
        svcs = build_services(tmp_staging, store, "/fake/kc.yaml", ns_lifecycle=mock_ns)
        assert set(svcs.keys()) == {
            "draft_repo", "session_repo", "session_svc", "verifier_svc", "step_svc", "ns_lifecycle"
        }

    def test_uses_provided_ns_lifecycle(self, tmp_staging: Path, tmp_cred_root: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        mock_ns = MagicMock()
        svcs = build_services(tmp_staging, store, "/fake/kc.yaml", ns_lifecycle=mock_ns)
        assert svcs["ns_lifecycle"] is mock_ns

    def test_uses_provided_verifier_client_factory(self, tmp_staging: Path, tmp_cred_root: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        mock_ns = MagicMock()
        mock_factory = MagicMock()
        svcs = build_services(
            tmp_staging, store, "/fake/kc.yaml",
            ns_lifecycle=mock_ns,
            verifier_client_factory=mock_factory,
        )
        assert svcs["step_svc"] is not None


# ---------------------------------------------------------------------------
# run_smoke tests
# ---------------------------------------------------------------------------


def _make_mock_session(
    session_id: str = "test-session-id",
    namespace: str = "lab-test-session-id",
    status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
    cleanup_verified: bool = True,
    failure_reason: Optional[str] = None,
) -> MagicMock:
    s = MagicMock(spec=LabSessionState)
    s.session_id = session_id
    s.namespace = namespace
    s.lab_session_status = status
    s.cleanup_verified = cleanup_verified
    s.failure_reason = failure_reason
    return s


def _make_check_resp(
    all_passed: bool = True,
    advanced: bool = True,
    ready_to_complete: bool = True,
    verify_results: Optional[list] = None,
) -> MagicMock:
    cr = MagicMock(spec=StepCheckResponse)
    cr.all_passed = all_passed
    cr.advanced = advanced
    cr.ready_to_complete = ready_to_complete
    cr.verify_results = verify_results or []
    return cr


def _make_services(
    session: MagicMock,
    completed: MagicMock,
    check_resp: MagicMock,
    ns_exists_sequence: list[bool],
) -> dict:
    session_svc = MagicMock()
    session_svc.create_session.return_value = session
    session_svc.complete_session.return_value = completed

    step_svc = MagicMock()
    step_svc.check_step.return_value = check_resp

    ns_lifecycle = MagicMock()
    ns_lifecycle.namespace_exists.side_effect = ns_exists_sequence

    return {
        "session_svc": session_svc,
        "step_svc": step_svc,
        "ns_lifecycle": ns_lifecycle,
        "draft_repo": MagicMock(),
        "session_repo": MagicMock(),
        "verifier_svc": MagicMock(),
    }


class TestRunSmoke:
    def test_full_pass(self) -> None:
        session = _make_mock_session()
        completed = _make_mock_session(status=LabSessionStatus.LAB_CLOSED, cleanup_verified=True)
        check_resp = _make_check_resp()
        svcs = _make_services(session, completed, check_resp, ns_exists_sequence=[True, False])

        with patch("time.sleep"):
            result = run_smoke(svcs)

        assert result.passed is True
        assert result.steps["create_session"]["ok"] is True
        assert result.steps["namespace_exists"]["ok"] is True
        assert result.steps["check_step"]["ok"] is True
        assert result.steps["complete_session"]["ok"] is True

    def test_fails_when_session_not_active(self) -> None:
        session = _make_mock_session(status=LabSessionStatus.LAB_START_FAILED, failure_reason="adapter_unsafe")
        completed = _make_mock_session()
        check_resp = _make_check_resp()
        svcs = _make_services(session, completed, check_resp, ns_exists_sequence=[])

        with patch("time.sleep"):
            result = run_smoke(svcs)

        assert result.passed is False
        assert "session not active" in result.error
        assert result.steps["create_session"]["ok"] is False

    def test_fails_when_namespace_not_found(self) -> None:
        session = _make_mock_session()
        completed = _make_mock_session()
        check_resp = _make_check_resp()
        svcs = _make_services(session, completed, check_resp, ns_exists_sequence=[False])

        with patch("time.sleep"):
            result = run_smoke(svcs)

        assert result.passed is False
        assert "not found on K3s" in result.error

    def test_fails_when_step_check_fails(self) -> None:
        session = _make_mock_session()
        completed = _make_mock_session()
        vr = MagicMock(spec=VerifyResult)
        vr.verify_id = "verify-namespace-exists"
        vr.passed = False
        vr.error_code = "verifier_credential_missing"
        check_resp = _make_check_resp(all_passed=False, advanced=False, ready_to_complete=False, verify_results=[vr])
        svcs = _make_services(session, completed, check_resp, ns_exists_sequence=[True])

        with patch("time.sleep"):
            result = run_smoke(svcs)

        assert result.passed is False
        assert "step check failed" in result.error
        assert result.steps["check_step"]["ok"] is False

    def test_fails_when_cleanup_not_verified(self) -> None:
        session = _make_mock_session()
        completed = _make_mock_session(
            status=LabSessionStatus.LAB_CLEANUP_FAILED,
            cleanup_verified=False,
            failure_reason="namespace_cleanup_failed",
        )
        check_resp = _make_check_resp()
        svcs = _make_services(session, completed, check_resp, ns_exists_sequence=[True])

        with patch("time.sleep"):
            result = run_smoke(svcs)

        assert result.passed is False
        assert "cleanup not verified" in result.error

    def test_create_session_exception_is_caught(self) -> None:
        session_svc = MagicMock()
        session_svc.create_session.side_effect = RuntimeError("proxmox down")
        svcs = {
            "session_svc": session_svc,
            "step_svc": MagicMock(),
            "ns_lifecycle": MagicMock(),
            "draft_repo": MagicMock(),
            "session_repo": MagicMock(),
            "verifier_svc": MagicMock(),
        }
        with patch("time.sleep"):
            result = run_smoke(svcs)
        assert result.passed is False
        assert "create_session raised" in result.error

    def test_namespace_deleted_check_failure_is_non_fatal(self) -> None:
        session = _make_mock_session()
        completed = _make_mock_session(status=LabSessionStatus.LAB_CLOSED, cleanup_verified=True)
        check_resp = _make_check_resp()
        svcs = _make_services(session, completed, check_resp, ns_exists_sequence=[True])
        svcs["ns_lifecycle"].namespace_exists.side_effect = [True, RuntimeError("timeout")]

        with patch("time.sleep"):
            result = run_smoke(svcs)

        # namespace_deleted failure is non-fatal; overall smoke still passes
        assert result.passed is True
        assert result.steps["namespace_deleted"]["ok"] is False
        assert result.steps["namespace_deleted"].get("non_fatal") is True

    def test_step_id_forwarded_to_check_step(self) -> None:
        session = _make_mock_session()
        completed = _make_mock_session(status=LabSessionStatus.LAB_CLOSED, cleanup_verified=True)
        check_resp = _make_check_resp()
        svcs = _make_services(session, completed, check_resp, ns_exists_sequence=[True, False])

        with patch("time.sleep"):
            run_smoke(svcs, step_id="step-verify-namespace")

        svcs["step_svc"].check_step.assert_called_once_with(
            session.session_id, "step-verify-namespace", SMOKE_STUDENT
        )


# ---------------------------------------------------------------------------
# cleanup_staging tests
# ---------------------------------------------------------------------------


class TestCleanupStaging:
    def test_removes_cred_dir(self, tmp_cred_root: Path, tmp_staging: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        cred_dir = tmp_cred_root / "400"
        cred_dir.mkdir(parents=True)
        (cred_dir / "kubeconfig.yaml").write_text("kc")

        cleanup_staging(None, tmp_staging, store, 400)
        assert not cred_dir.exists()

    def test_removes_session_from_staging(self, tmp_cred_root: Path, tmp_staging: Path) -> None:
        session_id = "abc-123"
        sessions_file = tmp_staging / "lab_sessions.json"
        sessions_file.write_text(json.dumps({session_id: {"session_id": session_id}}))
        store = VerifierCredentialStore(tmp_cred_root)

        cleanup_staging(session_id, tmp_staging, store, 400)

        data = json.loads(sessions_file.read_text())
        assert session_id not in data

    def test_removes_smoke_draft_from_staging(self, tmp_cred_root: Path, tmp_staging: Path) -> None:
        drafts_file = tmp_staging / "lab_drafts.json"
        drafts_file.write_text(json.dumps({SMOKE_LAB_ID: {"lab_id": SMOKE_LAB_ID}}))
        store = VerifierCredentialStore(tmp_cred_root)

        cleanup_staging(None, tmp_staging, store, 400)

        data = json.loads(drafts_file.read_text())
        assert SMOKE_LAB_ID not in data

    def test_noop_when_cred_dir_missing(self, tmp_cred_root: Path, tmp_staging: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        cleanup_staging(None, tmp_staging, store, 400)

    def test_noop_when_session_id_is_none(self, tmp_cred_root: Path, tmp_staging: Path) -> None:
        store = VerifierCredentialStore(tmp_cred_root)
        cleanup_staging(None, tmp_staging, store, 400)
