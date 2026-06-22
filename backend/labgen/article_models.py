"""
Article-to-Lab MVP Contract Schema — all models for the article ingestion pipeline.

Design invariants:
  - Raw article text MUST NOT be persisted (raw_text_persisted defaults to False)
  - ArticleDraftLabContract is NOT the same as LabDraft (published lab contract)
  - All feasibility/safety decisions are fail-closed
  - Learners NEVER see source grounding, unsupported inferences, or admin decisions
  - LLM/stub output cannot bypass admin review or StaticValidator
  - cloud domain is blocked by default in v0.1
  - Only k8s domain proceeds to implementation in v0.1
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


ARTICLE_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ArticleSourceType(str, Enum):
    PASTED_TEXT = "pasted_text"
    MARKDOWN = "markdown"
    README = "readme"
    INTERNAL_DOC = "internal_doc"
    OTHER = "other"


class FeasibilityStatus(str, Enum):
    DIRECTLY_LAB_READY = "directly_lab_ready"
    PARTIALLY_LAB_READY = "partially_lab_ready"
    NOT_LAB_READY = "not_lab_ready"


class SafetyFlag(str, Enum):
    CONTAINS_SECRET_LIKE_CONTENT = "contains_secret_like_content"
    REQUIRES_REAL_CREDENTIALS = "requires_real_credentials"
    REQUIRES_PRODUCTION_ENVIRONMENT = "requires_production_environment"
    DESTRUCTIVE_OPERATION = "destructive_operation"
    UNSAFE_NETWORK_BEHAVIOR = "unsafe_network_behavior"
    EXTERNAL_SERVICE_DEPENDENCY = "external_service_dependency"
    UNCLEAR_CLEANUP = "unclear_cleanup"
    UNVERIFIABLE_OUTCOME = "unverifiable_outcome"
    COPYRIGHT_UNCLEAR = "copyright_unclear"
    UNSUPPORTED_DOMAIN = "unsupported_domain"
    EXCESSIVE_COST = "excessive_cost"
    DANGEROUS_OR_ILLEGAL = "dangerous_or_illegal"
    SENSITIVE_PERSONAL_DATA = "sensitive_personal_data"


class VerifierFeasibility(str, Enum):
    REUSABLE_EXISTING = "reusable_existing"
    NEEDS_PARAMETERIZATION = "needs_parameterization"
    NEEDS_NEW_PRIMITIVE = "needs_new_primitive"
    NOT_VERIFIABLE = "not_verifiable"
    UNSAFE_TO_VERIFY = "unsafe_to_verify"


class FeasibilityEvaluatedBy(str, Enum):
    STUB = "stub"
    RULE_BASED = "rule_based"
    LLM_DRAFT = "llm_draft"
    HUMAN = "human"


class TargetDomain(str, Enum):
    K8S = "k8s"
    LINUX = "linux"
    DOCKER = "docker"
    NETWORKING = "networking"
    DATABASE = "database"
    CICD = "cicd"
    CLOUD = "cloud"
    UNKNOWN = "unknown"


class ArticleRuntimeType(str, Enum):
    K8S_NAMESPACE = "k8s_namespace"
    LINUX_VM = "linux_vm"
    CONTAINER = "container"
    DOCKER_COMPOSE = "docker_compose"
    NETWORK_NAMESPACE = "network_namespace"
    DATABASE_INSTANCE = "database_instance"
    UNKNOWN = "unknown"


class VerifierCandidateState(str, Enum):
    REUSABLE_EXISTING = "reusable_existing"
    NEEDS_PARAMETERIZATION = "needs_parameterization"
    NEEDS_NEW_PRIMITIVE = "needs_new_primitive"
    NOT_VERIFIABLE = "not_verifiable"
    UNSAFE_TO_VERIFY = "unsafe_to_verify"


class UnsupportedInferenceSeverity(str, Enum):
    NOTE = "note"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKER = "blocker"


class ArticleDraftStatus(str, Enum):
    DRAFT = "draft"
    NEEDS_CHANGES = "needs_changes"
    REJECTED = "rejected"
    APPROVED_FOR_STATIC_VALIDATION = "approved_for_static_validation"
    APPROVED_FOR_INTERNAL_REHEARSAL = "approved_for_internal_rehearsal"
    APPROVED_FOR_PUBLISH_CANDIDATE = "approved_for_publish_candidate"


class AdminDecisionValue(str, Enum):
    PENDING = "pending"
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


# ---------------------------------------------------------------------------
# High-risk safety flags — always fail-closed
# ---------------------------------------------------------------------------

_HARD_REJECT_FLAGS: frozenset[SafetyFlag] = frozenset({
    SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT,
    SafetyFlag.DANGEROUS_OR_ILLEGAL,
})

_REJECT_OR_MISSING_FLAGS: frozenset[SafetyFlag] = frozenset({
    SafetyFlag.REQUIRES_REAL_CREDENTIALS,
})

_CANNOT_PUBLISH_FLAGS: frozenset[SafetyFlag] = frozenset({
    SafetyFlag.UNCLEAR_CLEANUP,
})

# Domains blocked from proceeding to publish in v0.1
_BLOCKED_DOMAINS_V1: frozenset[TargetDomain] = frozenset({
    TargetDomain.CLOUD,
})

# Domains allowed to proceed to draft/implementation in v0.1
# LINUX is schema-ready; publish is blocked by StaticValidator until runtime is implemented
_ALLOWED_DRAFT_DOMAINS_V1: frozenset[TargetDomain] = frozenset({
    TargetDomain.K8S,
    TargetDomain.LINUX,
})


# ---------------------------------------------------------------------------
# ArticleSourceMetadata
# ---------------------------------------------------------------------------


class ArticleSourceMetadata(BaseModel):
    """
    Metadata about the submitted article.

    Constraints:
    - raw article text MUST NOT be persisted (raw_text_persisted defaults False)
    - content_hash MUST be present
    - user confirmations MUST both be True before feasibility assessment
    - source_url is metadata only — v0.1 does not scrape URLs
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    source_type: ArticleSourceType = ArticleSourceType.PASTED_TEXT
    title: Optional[str] = None
    author: Optional[str] = None
    source_url: Optional[str] = None  # metadata only; triggers no scraping
    submitted_by_user_id: str
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    content_hash: str  # SHA-256 of raw text; required
    content_length: int  # character count of original text
    language: Optional[str] = None
    user_confirmed_right_to_use: bool = False
    user_confirmed_no_secrets: bool = False
    raw_text_persisted: bool = False  # invariant: always False in v0.1
    retention_policy_version: str = "v0.1"


# ---------------------------------------------------------------------------
# FeasibilityResult
# ---------------------------------------------------------------------------


class FeasibilityResult(BaseModel):
    """
    Outcome of the Feasibility Gate assessment.

    Constraints:
    - NOT_LAB_READY → cannot create publishable lab
    - PARTIALLY_LAB_READY → cannot publish
    - DIRECTLY_LAB_READY → can enter draft/admin review; cannot direct-publish
    - safety_flags containing high-risk items → fail-closed
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    status: FeasibilityStatus
    reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    safety_flags: list[SafetyFlag] = Field(default_factory=list)
    target_domain_candidates: list[TargetDomain] = Field(default_factory=list)
    operability_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    verifier_feasibility: VerifierFeasibility = VerifierFeasibility.NOT_VERIFIABLE
    cleanup_feasibility: str = "unknown"
    runtime_feasibility: str = "unknown"
    rejection_code: Optional[str] = None
    evaluated_by: FeasibilityEvaluatedBy = FeasibilityEvaluatedBy.STUB
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def has_hard_reject_flag(self) -> bool:
        """Returns True if any safety_flag triggers an unconditional reject."""
        return bool(set(self.safety_flags) & _HARD_REJECT_FLAGS)

    def has_cannot_publish_flag(self) -> bool:
        """Returns True if any safety_flag blocks publish (but not necessarily feasibility)."""
        return bool(set(self.safety_flags) & (_HARD_REJECT_FLAGS | _CANNOT_PUBLISH_FLAGS))

    def can_enter_draft_pipeline(self) -> bool:
        """True only when feasibility and safety allow entering the draft pipeline."""
        if self.status == FeasibilityStatus.NOT_LAB_READY:
            return False
        if self.has_hard_reject_flag():
            return False
        return True


# ---------------------------------------------------------------------------
# SourceGroundingSnippet
# ---------------------------------------------------------------------------


class SourceGroundingSnippet(BaseModel):
    """
    Minimal verbatim excerpt from article stored for admin review only.

    Constraints:
    - excerpt must be minimal/necessary
    - contains_sensitive_content=True → excerpt must not be persisted
    - NEVER exposed to learners
    - deleted when parent ArticleDraftLabContract is deleted
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    snippet_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_section: Optional[str] = None
    excerpt: str  # minimal verbatim excerpt
    excerpt_hash: str  # hash of excerpt for audit
    supports_step_ids: list[str] = Field(default_factory=list)
    supports_verifier_ids: list[str] = Field(default_factory=list)
    character_range: Optional[tuple[int, int]] = None
    minimized: bool = True  # excerpt is already minimized
    contains_sensitive_content: bool = False


# ---------------------------------------------------------------------------
# UnsupportedInference
# ---------------------------------------------------------------------------


class UnsupportedInference(BaseModel):
    """
    Records a field/step that was inferred without sufficient source grounding.

    Constraints:
    - high/blocker severity → blocks publish
    - requires_admin_confirmation=True and unconfirmed → blocks publish
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    inference_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    reason: str
    affected_step_ids: list[str] = Field(default_factory=list)
    severity: UnsupportedInferenceSeverity = UnsupportedInferenceSeverity.MEDIUM
    requires_admin_confirmation: bool = True
    admin_confirmed: bool = False


# ---------------------------------------------------------------------------
# ArticleLabRuntimeRequirement
# ---------------------------------------------------------------------------


class ArticleLabRuntimeRequirement(BaseModel):
    """
    Runtime requirement for a generated lab draft.

    Differs from RuntimeRequirements (which is for published labs) — this
    captures what the article's experiment needs before a lab is created.

    Constraints:
    - cleanup_strategy MUST be present before publish
    - unknown runtime type blocks publish
    - network_access defaults to restricted
    - production_dependency blocks publish
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    domain: TargetDomain = TargetDomain.UNKNOWN
    runtime_type: ArticleRuntimeType = ArticleRuntimeType.UNKNOWN
    required_tools: list[str] = Field(default_factory=list)
    required_images: list[str] = Field(default_factory=list)
    required_packages: list[str] = Field(default_factory=list)
    network_access: str = "restricted"  # restricted | limited | open
    estimated_resource_cost: str = "low"  # low | medium | high
    isolation_level: str = "namespace"  # namespace | vm | container
    cleanup_strategy: Optional[str] = None  # required before publish
    unsupported_reasons: list[str] = Field(default_factory=list)
    production_dependency: bool = False  # blocks publish if True


# ---------------------------------------------------------------------------
# VerifierCandidate
# ---------------------------------------------------------------------------


class VerifierCandidate(BaseModel):
    """
    Candidate verifier strategy for a step in the article lab draft.

    Constraints:
    - unsafe_to_verify → cannot publish
    - needs_new_primitive → cannot auto-generate executable verifier code
    - review_required=True and unreviewed → cannot publish
    - safe_message_template MUST NOT contain secrets or raw objects
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    candidate_state: VerifierCandidateState = VerifierCandidateState.NOT_VERIFIABLE
    primitive_name: Optional[str] = None
    parameters: dict = Field(default_factory=dict)
    expected_artifact: str = ""
    safe_message_template: str = ""  # MUST NOT contain secrets or raw K8s objects
    unsafe_output_risks: list[str] = Field(default_factory=list)
    test_requirements: list[str] = Field(default_factory=list)
    review_required: bool = True
    admin_reviewed: bool = False


# ---------------------------------------------------------------------------
# AdminDecision
# ---------------------------------------------------------------------------


class AdminDecision(BaseModel):
    """
    Admin review decision for an ArticleDraftLabContract.

    Constraints:
    - APPROVE requires ALL confirmed_* fields to be True
    - pending/request_changes/reject → cannot publish
    - confirmed_no_direct_publish MUST be True to approve
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    decision: AdminDecisionValue = AdminDecisionValue.PENDING
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    comments: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    confirmed_source_grounding: bool = False
    confirmed_safety: bool = False
    confirmed_cleanup: bool = False
    confirmed_verifier_strategy: bool = False
    confirmed_no_raw_secret: bool = False
    confirmed_no_direct_publish: bool = False

    def is_fully_confirmed(self) -> bool:
        """All confirmation fields must be True for an approve decision to be valid."""
        return (
            self.confirmed_source_grounding
            and self.confirmed_safety
            and self.confirmed_cleanup
            and self.confirmed_verifier_strategy
            and self.confirmed_no_raw_secret
            and self.confirmed_no_direct_publish
        )


# ---------------------------------------------------------------------------
# ArticleStoragePolicy
# ---------------------------------------------------------------------------


class ArticleStoragePolicy(BaseModel):
    """
    Storage and retention policy for article-derived data.

    Invariants:
    - raw_text_persisted MUST default to False
    - forbidden_persisted_fields MUST include raw_article_text
    - sensitive rejection metadata MUST NOT include original content
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    raw_text_persisted: bool = False  # invariant: always False
    raw_text_retention: str = "ephemeral"  # ephemeral only
    draft_retention: str = "until_deleted"
    rejection_metadata_retention_days: int = 30
    audit_retention: str = "indefinite"
    delete_supported: bool = True
    purge_supported: bool = True
    persisted_fields: list[str] = Field(
        default_factory=lambda: [
            "content_hash",
            "source_metadata",
            "feasibility_result",
            "source_grounding_snippets",
            "draft_lab_contract",
            "admin_decision",
        ]
    )
    forbidden_persisted_fields: list[str] = Field(
        default_factory=lambda: [
            "raw_article_text",
            "secret_values",
            "private_keys",
            "api_keys",
            "credentials",
        ]
    )


# ---------------------------------------------------------------------------
# ArticleDraftLabContract
# ---------------------------------------------------------------------------


class ArticleDraftLabContract(BaseModel):
    """
    Article-to-Lab draft wrapper — NOT the same as a published LabDraft.

    This contract captures the output of the article analysis pipeline
    before admin review and StaticValidator. It is an intermediate artifact:
      Article text → (Feasibility Gate) → ArticleDraftLabContract
        → (Admin Review) → (StaticValidator) → (Internal Rehearsal)
        → LabDraft (published lab)

    Constraints:
    - NOT a learner-facing artifact; CANNOT enter the learner catalog directly
    - MUST pass admin_decision (APPROVE) before progressing
    - MUST pass StaticValidator before becoming a publish candidate
    - raw article text MUST NOT be stored as a field here or in children
    - Rejected / NOT_LAB_READY feasibility → cannot publish
    - PARTIALLY_LAB_READY → cannot publish
    - DIRECTLY_LAB_READY → draft/review only, not direct publish
    - LLM/stub output cannot set status > DRAFT without admin review
    """

    schema_version: str = Field(default=ARTICLE_SCHEMA_VERSION)
    draft_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_metadata: ArticleSourceMetadata
    feasibility_result: FeasibilityResult
    target_domain: TargetDomain = TargetDomain.UNKNOWN
    learning_objective: str = ""
    required_runtime: ArticleLabRuntimeRequirement = Field(
        default_factory=ArticleLabRuntimeRequirement
    )
    environment_requirements: list[str] = Field(default_factory=list)
    learner_steps: list[str] = Field(default_factory=list)  # step descriptions (not commands)
    expected_artifacts: list[str] = Field(default_factory=list)
    verifier_candidates: list[VerifierCandidate] = Field(default_factory=list)
    cleanup_requirements: list[str] = Field(default_factory=list)
    safety_constraints: list[str] = Field(default_factory=list)
    credential_policy: str = "no_real_credentials"
    terminal_requirements: list[str] = Field(default_factory=list)
    estimated_duration_minutes: int = 30
    source_grounding: list[SourceGroundingSnippet] = Field(default_factory=list)
    unsupported_inferences: list[UnsupportedInference] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    admin_decision: AdminDecision = Field(default_factory=AdminDecision)
    storage_policy: ArticleStoragePolicy = Field(default_factory=ArticleStoragePolicy)
    status: ArticleDraftStatus = ArticleDraftStatus.DRAFT
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    @model_validator(mode="after")
    def _check_raw_text_not_persisted(self) -> "ArticleDraftLabContract":
        if self.source_metadata.raw_text_persisted:
            raise ValueError(
                "source_metadata.raw_text_persisted must be False — "
                "raw article text must not be persisted"
            )
        if not self.storage_policy.raw_text_persisted is False:
            raise ValueError(
                "storage_policy.raw_text_persisted must be False"
            )
        return self

    def can_proceed_to_publish_candidate(self) -> bool:
        """
        Returns True only if all gates allow transitioning to
        APPROVED_FOR_PUBLISH_CANDIDATE status.
        """
        if self.feasibility_result.status == FeasibilityStatus.NOT_LAB_READY:
            return False
        if self.feasibility_result.status == FeasibilityStatus.PARTIALLY_LAB_READY:
            return False
        if self.feasibility_result.has_cannot_publish_flag():
            return False
        if self.admin_decision.decision != AdminDecisionValue.APPROVE:
            return False
        if not self.admin_decision.is_fully_confirmed():
            return False
        if self.target_domain in _BLOCKED_DOMAINS_V1:
            return False
        if self.target_domain == TargetDomain.UNKNOWN:
            return False
        if self.required_runtime.cleanup_strategy is None:
            return False
        if self.required_runtime.production_dependency:
            return False
        for inf in self.unsupported_inferences:
            if inf.severity in (
                UnsupportedInferenceSeverity.HIGH, UnsupportedInferenceSeverity.BLOCKER
            ):
                return False
            if inf.requires_admin_confirmation and not inf.admin_confirmed:
                return False
        for vc in self.verifier_candidates:
            if vc.candidate_state == VerifierCandidateState.UNSAFE_TO_VERIFY:
                return False
            if vc.review_required and not vc.admin_reviewed:
                return False
        if not self.source_grounding:
            return False
        for sg in self.source_grounding:
            if sg.contains_sensitive_content:
                return False
        return True
