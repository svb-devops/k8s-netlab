"""Tests for backend/labgen/models.py — Pydantic schema validation."""

import uuid
from datetime import datetime

import pytest

pytestmark = pytest.mark.static

from backend.labgen.models import (
    SCHEMA_VERSION,
    AdminReviewDiff,
    AdminReviewDiffChange,
    BlockingLevel,
    CleanupNamespace,
    CleanupSpec,
    ClusterScopedResource,
    ConnectionState,
    ExplainConfidence,
    ExplainField,
    ImageResolutionResult,
    ImageStatus,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PollutionLevel,
    PublishStatus,
    RuntimeRequirements,
    Step,
    ValidatorResult,
    ValidatorStatus,
    VerifierCredentialMetadata,
    VerifyTemplate,
    VerifyType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_explain(**kwargs) -> ExplainField:
    defaults = dict(concept="TCP handshake", observation="connection established")
    defaults.update(kwargs)
    return ExplainField(**defaults)


def _make_verify(**kwargs) -> VerifyTemplate:
    defaults = dict(verify_id="v1", type=VerifyType.POD_RUNNING, name="nginx")
    defaults.update(kwargs)
    return VerifyTemplate(**defaults)


def _make_step(**kwargs) -> Step:
    defaults = dict(
        step_id="step-1",
        order=1,
        why="demonstrate networking",
        do="apply manifest",
        observe="pod running",
        explain=_make_explain(),
    )
    defaults.update(kwargs)
    return Step(**defaults)


def _make_cleanup(**kwargs) -> CleanupSpec:
    return CleanupSpec(namespace_cleanup=CleanupNamespace(), **kwargs)


def _make_draft(**kwargs) -> LabDraft:
    defaults = dict(
        source_article_id="article-1",
        title="Intro to Networking",
        description="Learn basics",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=[_make_step()],
        cleanup=_make_cleanup(),
    )
    defaults.update(kwargs)
    return LabDraft(**defaults)


# ---------------------------------------------------------------------------
# schema_version
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_all_versioned_models_have_default(self):
        assert ValidatorResult(
            check_id="x", status=ValidatorStatus.PASSED,
            blocking_level=BlockingLevel.DRAFT_WARNING, field_path="", message=""
        ).schema_version == SCHEMA_VERSION

        assert VerifyTemplate(verify_id="v1", type=VerifyType.POD_RUNNING, name="pod").schema_version == SCHEMA_VERSION
        assert _make_step().schema_version == SCHEMA_VERSION
        assert RuntimeRequirements().schema_version == SCHEMA_VERSION
        assert ImageResolutionResult(image_intent="nginx", requested_image="nginx:1.25").schema_version == SCHEMA_VERSION
        assert _make_draft().schema_version == SCHEMA_VERSION

    def test_schema_version_is_1_0(self):
        assert SCHEMA_VERSION == "1.0"


# ---------------------------------------------------------------------------
# VerifyType enum
# ---------------------------------------------------------------------------


class TestVerifyType:
    def test_all_mvp_types_present(self):
        expected = {
            "pod_running", "pod_ready", "service_exists", "deployment_ready",
            "configmap_exists", "secret_exists", "namespace_exists",
            "node_ready", "pvc_bound", "job_completed",
        }
        actual = {v.value for v in VerifyType}
        assert actual == expected

    def test_shell_types_not_in_enum(self):
        values = {v.value for v in VerifyType}
        assert "shell_command" not in values
        assert "exec" not in values
        assert "secret_key_exists" not in values
        assert "secret_value_equals" not in values


# ---------------------------------------------------------------------------
# VerifyTemplate
# ---------------------------------------------------------------------------


class TestVerifyTemplate:
    def test_defaults(self):
        vt = _make_verify()
        assert vt.namespace == "{{lab_namespace}}"
        assert vt.cluster_scope is False
        assert vt.manual_review_required is False
        assert "dedicated_vm" in vt.supported_runtimes

    def test_cluster_scope_true(self):
        vt = _make_verify(cluster_scope=True, manual_review_required=True)
        assert vt.cluster_scope is True
        assert vt.manual_review_required is True


# ---------------------------------------------------------------------------
# ExplainField
# ---------------------------------------------------------------------------


class TestExplainField:
    def test_defaults(self):
        ex = _make_explain()
        assert ex.confidence == ExplainConfidence.UNVERIFIED
        assert ex.admin_verified is False
        assert ex.published_to_student is False

    def test_admin_verified(self):
        ex = _make_explain(admin_verified=True, confidence=ExplainConfidence.ADMIN_VERIFIED)
        assert ex.admin_verified is True
        assert ex.confidence == ExplainConfidence.ADMIN_VERIFIED


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------


class TestStep:
    def test_defaults(self):
        step = _make_step()
        assert step.commands == []
        assert step.verify == []
        assert step.schema_version == SCHEMA_VERSION

    def test_with_commands_and_verify(self):
        step = _make_step(
            commands=["kubectl apply -f deploy.yaml"],
            verify=[_make_verify()],
        )
        assert len(step.commands) == 1
        assert len(step.verify) == 1


# ---------------------------------------------------------------------------
# CleanupSpec
# ---------------------------------------------------------------------------


class TestCleanupSpec:
    def test_namespace_cleanup_defaults(self):
        c = CleanupNamespace()
        assert c.type == "delete_namespace"
        assert c.namespace == "{{lab_namespace}}"

    def test_cleanup_spec_defaults(self):
        cs = _make_cleanup()
        assert cs.cleanup_verified is False
        assert cs.cluster_scoped_resources == []

    def test_cluster_scoped_resource_optional_cleanup(self):
        res = ClusterScopedResource(kind="ClusterRole", name="demo-reader", api_group="rbac.authorization.k8s.io")
        assert res.cleanup is None

    def test_cluster_scoped_resource_with_cleanup(self):
        res = ClusterScopedResource(
            kind="ClusterRole", name="demo-reader",
            api_group="rbac.authorization.k8s.io", cleanup="delete",
        )
        assert res.cleanup == "delete"


# ---------------------------------------------------------------------------
# RuntimeRequirements
# ---------------------------------------------------------------------------


class TestRuntimeRequirements:
    def test_defaults(self):
        rr = RuntimeRequirements()
        assert rr.runtime == "dedicated_vm"
        assert rr.pollution_level == PollutionLevel.UNKNOWN
        assert rr.shared_namespace_candidate is False
        assert rr.namespace_template == "lab-{{lab_id}}-{{session_id}}"


# ---------------------------------------------------------------------------
# ImageResolutionResult
# ---------------------------------------------------------------------------


class TestImageResolutionResult:
    def test_defaults(self):
        img = ImageResolutionResult(image_intent="nginx", requested_image="nginx:1.25")
        assert img.image_status == ImageStatus.UNRESOLVED
        assert img.existence_check_passed is None
        assert img.recheck_after_hours == 24

    def test_resolved(self):
        img = ImageResolutionResult(
            image_intent="nginx",
            requested_image="nginx:1.25",
            resolved_image="172.16.100.1:5000/nginx:1.25-alpine",
            image_status=ImageStatus.RESOLVED,
            existence_check_passed=True,
        )
        assert img.image_status == ImageStatus.RESOLVED
        assert img.existence_check_passed is True

    def test_blocked(self):
        img = ImageResolutionResult(
            image_intent="nginx", requested_image="nginx:latest",
            image_status=ImageStatus.BLOCKED,
        )
        assert img.image_status == ImageStatus.BLOCKED


# ---------------------------------------------------------------------------
# LabDraft
# ---------------------------------------------------------------------------


class TestLabDraft:
    def test_defaults(self):
        draft = _make_draft()
        assert draft.schema_version == SCHEMA_VERSION
        assert draft.publish_status == PublishStatus.DRAFT
        assert draft.pollution_level == PollutionLevel.UNKNOWN
        assert draft.shared_namespace_candidate is False
        assert draft.image_resolution == []
        assert draft.validator_results == []
        assert uuid.UUID(draft.lab_id)  # valid UUID

    def test_lab_id_is_unique(self):
        d1, d2 = _make_draft(), _make_draft()
        assert d1.lab_id != d2.lab_id

    def test_publish_status_enum(self):
        draft = _make_draft(publish_status=PublishStatus.REVIEW_REQUIRED)
        assert draft.publish_status == PublishStatus.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# AdminReviewDiff
# ---------------------------------------------------------------------------


class TestAdminReviewDiff:
    def test_basic(self):
        diff = AdminReviewDiff(
            lab_draft_id="draft-1",
            admin_user="admin",
            reviewed_at=datetime.utcnow(),
            review_duration_seconds=120,
        )
        assert diff.schema_version == SCHEMA_VERSION
        assert diff.changes == []

    def test_change_types(self):
        change = AdminReviewDiffChange(
            field_path="steps[0].explain.concept",
            change_type="edit",
            original_value="old concept",
            edited_value="new concept",
        )
        assert change.change_type == "edit"
        assert change.original_value == "old concept"


# ---------------------------------------------------------------------------
# VerifierCredentialMetadata
# ---------------------------------------------------------------------------


class TestVerifierCredentialMetadata:
    def test_defaults(self):
        meta = VerifierCredentialMetadata(
            vm_id="vm-500",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow(),
            k3s_endpoint="https://vm-ip-example:6443",
        )
        assert meta.credential_type == "verifier"
        assert meta.permission_profile == "namespace_readonly_v1"
        assert meta.credential_generation == 1
        assert meta.revoked_at is None
        assert meta.schema_version == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# LabSessionState
# ---------------------------------------------------------------------------


class TestLabSessionState:
    def test_defaults(self):
        state = LabSessionState(lab_id="lab-1", vm_id="vm-500", student_username="alice")
        assert state.lab_session_status == LabSessionStatus.LAB_CREATED
        assert state.connection_state == ConnectionState.DISCONNECTED
        assert state.started_at is None
        assert uuid.UUID(state.session_id)
        assert state.schema_version == SCHEMA_VERSION

    def test_terminal_states_present(self):
        terminal = {
            LabSessionStatus.LAB_CLOSED,
            LabSessionStatus.LAB_START_FAILED,
            LabSessionStatus.LAB_CLEANUP_FAILED,
        }
        for s in terminal:
            state = LabSessionState(
                lab_id="lab-1", vm_id="vm-500", student_username="alice",
                lab_session_status=s,
            )
            assert state.lab_session_status == s
