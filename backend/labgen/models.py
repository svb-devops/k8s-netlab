"""
LabGen Pydantic models — all objects require schema_version per Contract §3.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VerifyType(str, Enum):
    POD_RUNNING = "pod_running"
    POD_READY = "pod_ready"
    SERVICE_EXISTS = "service_exists"
    DEPLOYMENT_READY = "deployment_ready"
    CONFIGMAP_EXISTS = "configmap_exists"
    SECRET_EXISTS = "secret_exists"
    NAMESPACE_EXISTS = "namespace_exists"
    NODE_READY = "node_ready"
    PVC_BOUND = "pvc_bound"
    JOB_COMPLETED = "job_completed"


class ImageStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    BLOCKED = "blocked"


class PollutionLevel(str, Enum):
    NAMESPACE_ONLY = "namespace_only"
    CLUSTER_SCOPED = "cluster_scoped"
    NODE_LEVEL = "node_level"
    UNKNOWN = "unknown"


class PublishStatus(str, Enum):
    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    PUBLISH_BLOCKED = "publish_blocked"
    PUBLISHED = "published"


class ValidatorStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


class BlockingLevel(str, Enum):
    DRAFT_WARNING = "draft_warning"
    REVIEW_REQUIRED = "review_required"
    PUBLISH_BLOCKING = "publish_blocking"
    RUNTIME_BLOCKING = "runtime_blocking"


class ExplainConfidence(str, Enum):
    UNVERIFIED = "unverified"
    ADMIN_VERIFIED = "admin_verified"


class LabSessionStatus(str, Enum):
    LAB_CREATED = "LAB_CREATED"
    LAB_STARTING = "LAB_STARTING"
    VM_PRECHECK_RUNNING = "VM_PRECHECK_RUNNING"
    LAB_START_FAILED = "LAB_START_FAILED"
    IMAGE_CHECK_RUNNING = "IMAGE_CHECK_RUNNING"
    NAMESPACE_CREATING = "NAMESPACE_CREATING"
    NAMESPACE_READY = "NAMESPACE_READY"
    VERIFIER_BINDING_CREATING = "VERIFIER_BINDING_CREATING"
    LAB_ACTIVE = "LAB_ACTIVE"
    LAB_COMPLETED = "LAB_COMPLETED"
    LAB_ABORTED = "LAB_ABORTED"
    LAB_TIMEOUT = "LAB_TIMEOUT"
    CLEANUP_REQUESTED = "CLEANUP_REQUESTED"
    NAMESPACE_TERMINATING_WAIT = "NAMESPACE_TERMINATING_WAIT"
    LAB_CLEANUP_FAILED = "LAB_CLEANUP_FAILED"
    CLEANUP_VERIFICATION_RUNNING = "CLEANUP_VERIFICATION_RUNNING"
    CLEANUP_VERIFIED = "CLEANUP_VERIFIED"
    LAB_CLOSED = "LAB_CLOSED"


class ConnectionState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


class SessionType(str, Enum):
    LEARNER = "learner"
    INTERNAL_REHEARSAL = "internal_rehearsal"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class SchemaVersionedModel(BaseModel):
    schema_version: str = Field(default=SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# VerifyResult  (§verifier)
# ---------------------------------------------------------------------------


class VerifyResult(SchemaVersionedModel):
    session_id: str
    verify_id: str
    verify_type: str
    passed: bool
    error_code: Optional[str] = None
    failure_reason: Optional[str] = None
    detail: str = ""


# ---------------------------------------------------------------------------
# ValidatorResult  (§9)
# ---------------------------------------------------------------------------


class ValidatorResult(SchemaVersionedModel):
    check_id: str
    status: ValidatorStatus
    blocking_level: BlockingLevel
    field_path: str
    message: str


# ---------------------------------------------------------------------------
# VerifyTemplate  (§6)
# ---------------------------------------------------------------------------


class VerifyTemplate(SchemaVersionedModel):
    verify_id: str
    type: VerifyType
    namespace: str = "{{lab_namespace}}"
    name: str
    label_selector: Optional[str] = None
    cluster_scope: bool = False
    supported_runtimes: list[str] = Field(default_factory=lambda: ["dedicated_vm"])
    blocking_level_on_fail: BlockingLevel = BlockingLevel.PUBLISH_BLOCKING
    manual_review_required: bool = False
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# ExplainField / Step  (§5)
# ---------------------------------------------------------------------------


class ExplainField(BaseModel):
    concept: str
    observation: str
    confidence: ExplainConfidence = ExplainConfidence.UNVERIFIED
    admin_verified: bool = False
    published_to_student: bool = False


class Step(SchemaVersionedModel):
    step_id: str
    order: int
    why: str
    do: str
    commands: list[str] = Field(default_factory=list)
    observe: str
    explain: ExplainField
    verify: list[VerifyTemplate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# CleanupSpec  (§18)
# ---------------------------------------------------------------------------


class ClusterScopedResource(BaseModel):
    kind: str
    name: str
    api_group: str
    # None = not declared; validator checks this must be set before publish
    cleanup: Optional[str] = None


class CleanupNamespace(BaseModel):
    type: str = "delete_namespace"
    namespace: str = "{{lab_namespace}}"


class CleanupSpec(BaseModel):
    namespace_cleanup: CleanupNamespace
    cluster_scoped_resources: list[ClusterScopedResource] = Field(default_factory=list)
    cleanup_verified: bool = False


# ---------------------------------------------------------------------------
# RuntimeRequirements  (§8)
# ---------------------------------------------------------------------------


class RuntimeRequirements(SchemaVersionedModel):
    runtime: str = "dedicated_vm"
    namespace_template: str = "lab-{{lab_id}}-{{session_id}}"
    cluster_scoped_resources: list[ClusterScopedResource] = Field(default_factory=list)
    pollution_level: PollutionLevel = PollutionLevel.UNKNOWN
    shared_namespace_candidate: bool = False
    shared_namespace_candidate_reason: str = ""


# ---------------------------------------------------------------------------
# ImageResolutionResult  (§7)
# ---------------------------------------------------------------------------


class ImageResolutionResult(SchemaVersionedModel):
    image_intent: str
    requested_image: str
    resolved_image: Optional[str] = None
    image_status: ImageStatus = ImageStatus.UNRESOLVED
    existence_checked_at: Optional[datetime] = None
    existence_check_passed: Optional[bool] = None
    recheck_after_hours: int = 24


# ---------------------------------------------------------------------------
# LabDraft  (§4)
# ---------------------------------------------------------------------------


class LabDraft(SchemaVersionedModel):
    lab_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_article_id: str
    title: str
    description: str
    estimated_duration_minutes: int
    prerequisites: list[str] = Field(default_factory=list)
    runtime_requirements: RuntimeRequirements
    steps: list[Step]
    cleanup: Optional[CleanupSpec] = None
    image_resolution: list[ImageResolutionResult] = Field(default_factory=list)
    # Derived by StaticValidator — LLM must not set these
    pollution_level: PollutionLevel = PollutionLevel.UNKNOWN
    shared_namespace_candidate: bool = False
    shared_namespace_candidate_reason: str = ""
    publish_status: PublishStatus = PublishStatus.DRAFT
    validator_results: list[ValidatorResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# AdminReviewDiff  (§16)
# ---------------------------------------------------------------------------


class AdminReviewDiffChange(BaseModel):
    field_path: str
    change_type: str  # edit | approve | reject | confirm
    original_value: Optional[str] = None
    edited_value: Optional[str] = None
    note: Optional[str] = None


class AdminReviewDiff(SchemaVersionedModel):
    lab_draft_id: str
    admin_user: str
    reviewed_at: datetime
    review_duration_seconds: int
    changes: list[AdminReviewDiffChange] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# VerifierCredentialMetadata  (§14)
# ---------------------------------------------------------------------------


class VerifierCredentialMetadata(SchemaVersionedModel):
    vm_id: str
    created_at: datetime
    expires_at: datetime
    k3s_endpoint: str
    credential_type: str = "verifier"
    permission_profile: str = "namespace_readonly_v1"
    credential_generation: int = 1
    revoked_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# LabSessionState  (§11)
# ---------------------------------------------------------------------------


class LabSessionState(SchemaVersionedModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    lab_id: str
    vm_id: str
    student_username: str
    lab_session_status: LabSessionStatus = LabSessionStatus.LAB_CREATED
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    namespace: Optional[str] = None
    failure_reason: Optional[str] = None
    cleanup_verified: bool = False
    current_step_index: int = 0
    completed_step_ids: list[str] = Field(default_factory=list)
    ready_to_complete: bool = False
    last_verify_results: list[VerifyResult] = Field(default_factory=list)
    session_type: SessionType = SessionType.LEARNER
    article_draft_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Runtime Audit
# ---------------------------------------------------------------------------


class RuntimeAuditEventType(str, Enum):
    LAB_START_SUCCESS = "lab_start_success"
    LAB_START_FAILED = "lab_start_failed"
    STEP_CHECK_PASSED = "step_check_passed"
    STEP_CHECK_FAILED = "step_check_failed"
    LAB_COMPLETE = "lab_complete"
    LAB_ABORT = "lab_abort"
    CLEANUP_SUCCESS = "cleanup_success"
    CLEANUP_FAILED = "cleanup_failed"
    VM_TAINTED = "vm_tainted"


class RuntimeAuditEvent(SchemaVersionedModel):
    """Append-only audit record. metadata MUST NOT contain tokens, passwords, or credential material."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    event_type: RuntimeAuditEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    failure_reason: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
