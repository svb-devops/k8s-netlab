"""
LabGen Draft API routes.

Route layer delegates storage to LabDraftRepository and generation to
LabDraftGeneratorStub. No business logic lives here beyond request
validation and HTTP status mapping.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from backend import config
from backend.auth import auth_manager
from backend.auth_deps import get_current_user
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.lab_session_service import (
    LabNotReadyToComplete,
    LabSessionService,
    PrecheckFailed,
    RealVMTracker,
    SessionAlreadyTerminated,
    SessionNotFound,
    VMTrackerPort,
)
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
from backend.labgen.models import (
    AdminReviewDiff,
    AdminReviewDiffChange,
    BlockingLevel,
    CleanupSpec,
    ImageResolutionResult,
    LabDraft,
    LabSessionState,
    PublishStatus,
    Step,
    ValidatorResult,
    ValidatorStatus,
    VerifyResult,
    VerifyTemplate,
)
from backend.labgen.image_resolver import ImageResolver
from backend.labgen.publish_service import PublishService
from backend.labgen.repository import LabDraftRepository
from backend.labgen.review_diff import AdminReviewDiffRepository
from backend.labgen.static_validator import StaticValidator
from backend.labgen.stub_generator import LabDraftGeneratorStub
from backend.labgen.step_progression_service import (
    StepAccessDenied,
    StepCheckResponse,
    StepDraftUnavailable,
    StepNotCurrent,
    StepProgressionService,
    StepSessionNotActive,
    StepSessionNotFound,
)
from backend.labgen.failure_reasons import FailureReason
from backend.labgen.models import RuntimeAuditEvent
from backend.labgen.runtime_audit import RuntimeAuditRepository, RuntimeAuditService
from backend.labgen.verifier import VerifierService
from backend.labgen.verifier_credentials import VerifierCredentialStore
from backend.labgen.draft_preview import DraftPreviewService, DraftPreviewSnapshot
from backend.labgen.image_readiness import ImageReadinessService
from backend.labgen.publish_decision import PublishDecision, PublishDecisionService, PublishDecisionStatus
from backend.labgen.learner_catalog import (
    LearnerCatalogService,
    LearnerLabCatalogItem,
    LearnerLabDetail,
    LearnerLabEligibility,
)
from backend.labgen.learner_session_snapshot import (
    LearnerSessionListItem,
    LearnerSessionSnapshot,
    LearnerSessionSnapshotService,
    SnapshotAccessDenied,
    SnapshotNotFound,
)
from backend.labgen.api_contract import ApiContractPack, build_contract_pack

router = APIRouter(prefix="/api/labgen", tags=["labgen"])


# ---------------------------------------------------------------------------
# Dependency providers  (override in tests via app.dependency_overrides)
# ---------------------------------------------------------------------------


_repo: Optional[LabDraftRepository] = None
_generator: Optional[LabDraftGeneratorStub] = None
_validator: Optional[StaticValidator] = None
_diff_repo: Optional[AdminReviewDiffRepository] = None
_publish_svc: Optional[PublishService] = None
_session_repo: Optional[LabSessionRepository] = None
_session_svc: Optional[LabSessionService] = None
_image_resolver: Optional[ImageResolver] = None
_verifier_svc: Optional[VerifierService] = None
_step_progression_svc: Optional[StepProgressionService] = None
_audit_repo: Optional[RuntimeAuditRepository] = None
_preview_svc: Optional[DraftPreviewService] = None


def get_repository() -> LabDraftRepository:
    global _repo
    if _repo is None:
        _repo = LabDraftRepository()
    return _repo


def get_generator() -> LabDraftGeneratorStub:
    global _generator
    if _generator is None:
        _generator = LabDraftGeneratorStub()
    return _generator


def get_validator() -> StaticValidator:
    global _validator
    if _validator is None:
        _validator = StaticValidator()
    return _validator


def get_session_repository() -> LabSessionRepository:
    global _session_repo
    if _session_repo is None:
        _session_repo = LabSessionRepository()
    return _session_repo


def get_image_resolver() -> ImageResolver:
    global _image_resolver
    if _image_resolver is None:
        _image_resolver = ImageResolver()
    return _image_resolver


def get_session_service() -> LabSessionService:
    global _session_svc
    if _session_svc is None:
        _session_svc = LabSessionService(
            session_repo=get_session_repository(),
            draft_repo=get_repository(),
            vm_tracker=RealVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=get_image_resolver(),
            audit_svc=RuntimeAuditService(repo=get_audit_repository()),
        )
    return _session_svc


def get_publish_service() -> PublishService:
    global _publish_svc
    if _publish_svc is None:
        _publish_svc = PublishService(
            validator=StaticValidator(),
            image_resolver=ImageResolver(),
        )
    return _publish_svc


def get_diff_repository() -> AdminReviewDiffRepository:
    global _diff_repo
    if _diff_repo is None:
        _diff_repo = AdminReviewDiffRepository()
    return _diff_repo


def get_verifier_service() -> VerifierService:
    global _verifier_svc
    if _verifier_svc is None:
        from backend.labgen.k8s_verifier_client import K8sVerifierClientFactory

        _verifier_svc = VerifierService(
            session_repo=get_session_repository(),
            credential_store=VerifierCredentialStore(),
            k8s_client_factory=K8sVerifierClientFactory,
        )
    return _verifier_svc


def get_audit_repository() -> RuntimeAuditRepository:
    global _audit_repo
    if _audit_repo is None:
        _audit_repo = RuntimeAuditRepository()
    return _audit_repo


def get_step_progression_service() -> StepProgressionService:
    global _step_progression_svc
    if _step_progression_svc is None:
        _step_progression_svc = StepProgressionService(
            session_repo=get_session_repository(),
            draft_repo=get_repository(),
            verifier_svc=get_verifier_service(),
            audit_svc=RuntimeAuditService(repo=get_audit_repository()),
        )
    return _step_progression_svc


def get_preview_service() -> DraftPreviewService:
    global _preview_svc
    if _preview_svc is None:
        _preview_svc = DraftPreviewService(
            repo=get_repository(),
            validator=StaticValidator(),
            image_readiness_svc=ImageReadinessService(),
        )
    return _preview_svc


def get_catalog_service(
    repo: LabDraftRepository = Depends(get_repository),
) -> LearnerCatalogService:
    """Per-request factory — test repo overrides propagate via Depends(get_repository)."""
    from backend.labgen.lab_session_repository import LabSessionRepository as _SessionRepo
    return LearnerCatalogService(
        draft_repo=repo,
        validator=StaticValidator(),
        session_repo=_SessionRepo(),
    )


def get_decision_service(
    repo: LabDraftRepository = Depends(get_repository),
) -> PublishDecisionService:
    """Per-request factory so that test repo overrides propagate correctly."""
    return PublishDecisionService(
        preview_svc=DraftPreviewService(
            repo=repo,
            validator=StaticValidator(),
            image_readiness_svc=ImageReadinessService(),
        )
    )


def get_snapshot_service(
    repo: LabDraftRepository = Depends(get_repository),
) -> LearnerSessionSnapshotService:
    """Per-request factory — test repo overrides propagate via Depends(get_repository)."""
    return LearnerSessionSnapshotService(
        session_repo=LabSessionRepository(),
        draft_repo=repo,
    )


async def require_admin_user(
    username: str = Depends(get_current_user),
) -> str:
    if not auth_manager.is_admin(username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for LabGen draft management",
        )
    return username


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateDraftRequest(BaseModel):
    source_article_id: str
    title: str
    description: str
    estimated_duration_minutes: int = 30
    prerequisites: list[str] = []


class PatchDraftRequest(BaseModel):
    """Only admin-editable fields.  Omit a field to leave it unchanged."""
    title: Optional[str] = None
    description: Optional[str] = None
    estimated_duration_minutes: Optional[int] = None
    prerequisites: Optional[list[str]] = None
    steps: Optional[list[Step]] = None
    cleanup: Optional[CleanupSpec] = None
    image_resolution: Optional[list[ImageResolutionResult]] = None
    # publish_status may be set to draft/review_required/publish_blocked;
    # setting to "published" is rejected (use the publish endpoint instead).
    publish_status: Optional[PublishStatus] = None


# ---------------------------------------------------------------------------
# Business-logic helpers
# ---------------------------------------------------------------------------


def _compute_publish_status(results: list[ValidatorResult]) -> PublishStatus:
    failed = [r for r in results if r.status == ValidatorStatus.FAILED]
    if any(r.blocking_level == BlockingLevel.PUBLISH_BLOCKING for r in failed):
        return PublishStatus.PUBLISH_BLOCKED
    if any(r.blocking_level == BlockingLevel.REVIEW_REQUIRED for r in failed):
        return PublishStatus.REVIEW_REQUIRED
    return PublishStatus.DRAFT


def _build_diff(
    draft: LabDraft,
    update_data_json: dict,
    admin_user: str,
) -> Optional[AdminReviewDiff]:
    """Return an AdminReviewDiff if any fields actually changed, else None."""
    old_data = draft.model_dump(mode="json")
    changes = []
    for field, new_val in update_data_json.items():
        if field == "updated_at":
            continue
        old_val = old_data.get(field)
        if old_val != new_val:
            changes.append(AdminReviewDiffChange(
                field_path=field,
                change_type="edit",
                original_value=json.dumps(old_val, default=str),
                edited_value=json.dumps(new_val, default=str),
            ))
    if not changes:
        return None
    return AdminReviewDiff(
        lab_draft_id=draft.lab_id,
        admin_user=admin_user,
        reviewed_at=datetime.now(tz=timezone.utc),
        review_duration_seconds=0,
        changes=changes,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/drafts", response_model=LabDraft, status_code=status.HTTP_201_CREATED)
async def create_draft(
    body: CreateDraftRequest,
    admin: str = Depends(require_admin_user),
    repo: LabDraftRepository = Depends(get_repository),
    generator: LabDraftGeneratorStub = Depends(get_generator),
) -> LabDraft:
    draft = generator.generate(
        source_article_id=body.source_article_id,
        title=body.title,
        description=body.description,
        estimated_duration_minutes=body.estimated_duration_minutes,
        prerequisites=body.prerequisites,
    )
    return repo.create(draft)


@router.get("/drafts/{lab_id}", response_model=LabDraft)
async def get_draft(
    lab_id: str,
    admin: str = Depends(require_admin_user),
    repo: LabDraftRepository = Depends(get_repository),
) -> LabDraft:
    draft = repo.get(lab_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft


@router.patch("/drafts/{lab_id}", response_model=LabDraft)
async def patch_draft(
    lab_id: str,
    body: PatchDraftRequest,
    admin: str = Depends(require_admin_user),
    repo: LabDraftRepository = Depends(get_repository),
    diff_repo: AdminReviewDiffRepository = Depends(get_diff_repository),
) -> LabDraft:
    draft = repo.get(lab_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    update_data = body.model_dump(exclude_unset=True)

    if update_data.get("publish_status") == PublishStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="publish_status cannot be set to 'published' directly — use the publish endpoint",
        )

    # Compute diff before applying the update (old state vs incoming changes)
    update_data_json = body.model_dump(mode="json", exclude_unset=True)
    diff = _build_diff(draft, update_data_json, admin)

    update_data["updated_at"] = datetime.now(tz=timezone.utc)
    updated = draft.model_copy(update=update_data)
    result = repo.update(updated)

    if diff is not None:
        diff_repo.append(diff)

    return result


@router.post("/drafts/{lab_id}/validate", response_model=LabDraft)
async def validate_draft(
    lab_id: str,
    admin: str = Depends(require_admin_user),
    repo: LabDraftRepository = Depends(get_repository),
    sv: StaticValidator = Depends(get_validator),
) -> LabDraft:
    draft = repo.get(lab_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    # validate() mutates draft.pollution_level, shared_namespace_candidate, reason
    results = sv.validate(draft)

    draft.validator_results = results
    draft.publish_status = _compute_publish_status(results)
    draft.updated_at = datetime.now(tz=timezone.utc)

    return repo.update(draft)


@router.get("/drafts/{lab_id}/diffs", response_model=list[AdminReviewDiff])
async def list_draft_diffs(
    lab_id: str,
    admin: str = Depends(require_admin_user),
    repo: LabDraftRepository = Depends(get_repository),
    diff_repo: AdminReviewDiffRepository = Depends(get_diff_repository),
) -> list[AdminReviewDiff]:
    if repo.get(lab_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return diff_repo.list_by_draft(lab_id)


@router.get("/drafts/{lab_id}/preview", response_model=DraftPreviewSnapshot)
async def get_draft_preview(
    lab_id: str,
    admin: str = Depends(require_admin_user),
    svc: DraftPreviewService = Depends(get_preview_service),
) -> DraftPreviewSnapshot:
    snapshot = svc.build_snapshot(lab_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return snapshot


@router.get("/drafts/{lab_id}/publish-decision", response_model=PublishDecision)
async def get_publish_decision(
    lab_id: str,
    admin: str = Depends(require_admin_user),
    decision_svc: PublishDecisionService = Depends(get_decision_service),
) -> PublishDecision:
    """
    Read-only: evaluate whether this draft may be published.
    Does not publish, does not start a lab, does not create sessions or audit events.
    """
    decision = decision_svc.evaluate(lab_id)
    if any(i.code == "DRAFT_NOT_FOUND" for i in decision.issues):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return decision


@router.post("/drafts/{lab_id}/publish", response_model=LabDraft)
async def publish_draft(
    lab_id: str,
    admin: str = Depends(require_admin_user),
    repo: LabDraftRepository = Depends(get_repository),
    svc: PublishService = Depends(get_publish_service),
    decision_svc: PublishDecisionService = Depends(get_decision_service),
) -> LabDraft:
    draft = repo.get(lab_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    # Gate: evaluate before publishing — no force-publish bypass allowed.
    # TOCTOU note: PublishService.publish() always re-runs StaticValidator atomically
    # under the flock write lock, so any concurrent PATCH cannot silently bypass the
    # real validator.  Optimistic locking is explicitly out-of-scope per Contract v0.1.
    decision = decision_svc.evaluate(lab_id)
    if decision.status == PublishDecisionStatus.BLOCKED:
        # Return only the actionable fields in the 409 body; omit preview_summary
        # to keep the error payload minimal and avoid leaking non-essential detail.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "status": decision.status.value,
                "is_publishable": decision.is_publishable,
                "draft_id": decision.draft_id,
                "issues": [i.model_dump() for i in decision.issues],
            },
        )

    updated = svc.publish(draft)
    saved = repo.update(updated)

    # Defense-in-depth: if publish service somehow blocked despite ALLOWED decision
    if saved.publish_status == PublishStatus.PUBLISH_BLOCKED:
        blocking = [
            r.check_id for r in saved.validator_results
            if r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"publish_blocking failures: {', '.join(blocking)}",
        )

    return saved


# ===========================================================================
# Contract Pack — GET /api/labgen/contract-pack  (admin-only, read-only)
# ===========================================================================


@router.get(
    "/contract-pack",
    response_model=ApiContractPack,
    summary="Frontend Integration Contract Pack v0.1",
    tags=["labgen"],
)
async def get_contract_pack(
    admin: str = Depends(require_admin_user),
) -> ApiContractPack:
    """
    Return the API contract pack for frontend/UI integration.

    READ-ONLY: does not publish, start, create sessions, or emit audit events.
    """
    return build_contract_pack()


# ===========================================================================
# LLM Provider Boundary — GET /api/labgen/llm-provider/status  (admin-only)
#                          POST /api/labgen/llm-provider/dry-run (admin-only)
# ===========================================================================

from backend.labgen.llm_provider_boundary import (  # noqa: E402
    DryRunLLMProviderAdapter,
    DryRunTimeoutSimulated,
    LLMProviderBoundaryService,
    LLMProviderMode,
    LLMProviderRequest,
    _ALLOWED_INJECT_MODES,
)

_llm_provider_svc: Optional[LLMProviderBoundaryService] = None


def get_llm_provider_service() -> LLMProviderBoundaryService:
    global _llm_provider_svc
    if _llm_provider_svc is None:
        _llm_provider_svc = LLMProviderBoundaryService.create_from_env()
    return _llm_provider_svc


class LLMProviderStatusResponse(BaseModel):
    provider_name: str
    mode: str
    live_enabled: bool
    dry_run_available: bool
    timeout_ms: int
    max_output_tokens: int
    safety_policy_summary: str
    warnings: list[str]


class DryRunRequest(BaseModel):
    sanitized_prompt: str = Field(..., min_length=1, max_length=2000)
    inject_mode: str = Field(default="valid_candidate", max_length=40)

    @field_validator("inject_mode")
    @classmethod
    def _validate_inject_mode(cls, v: str) -> str:
        if v not in _ALLOWED_INJECT_MODES:
            raise ValueError(
                f"inject_mode {v!r} must be one of {sorted(_ALLOWED_INJECT_MODES)}"
            )
        return v


class DryRunResponse(BaseModel):
    provider_name: str
    mode: str
    candidate_json: Optional[dict] = None
    warnings: list[str] = Field(default_factory=list)
    usage_summary: Optional[str] = None
    rejected_reason: Optional[str] = None


_SAFETY_POLICY_SUMMARY = (
    "Prohibited: raw output, chain of thought, hidden prompts, provider data, API keys. "
    "sanitize_text() applied to all dynamic content."
)


@router.get(
    "/llm-provider/status",
    response_model=LLMProviderStatusResponse,
    summary="LLM provider boundary status (admin-only diagnostics)",
    tags=["labgen"],
)
async def get_llm_provider_status(
    admin: str = Depends(require_admin_user),
    svc: LLMProviderBoundaryService = Depends(get_llm_provider_service),
) -> LLMProviderStatusResponse:
    """
    READ-ONLY: returns provider config status.
    Never returns API keys, raw output, hidden prompts, or provider metadata.
    """
    cfg = svc.config
    warnings: list[str] = []
    if cfg.mode in (LLMProviderMode.DISABLED, LLMProviderMode.LIVE_DISABLED):
        warnings.append(
            f"LLM provider mode is {cfg.mode.value} — generation uses fake/template path."
        )
    return LLMProviderStatusResponse(
        provider_name=cfg.provider_name.value,
        mode=cfg.mode.value,
        live_enabled=False,
        dry_run_available=svc.dry_run_available,
        timeout_ms=cfg.timeout_ms,
        max_output_tokens=cfg.max_output_tokens,
        safety_policy_summary=_SAFETY_POLICY_SUMMARY,
        warnings=warnings,
    )


@router.post(
    "/llm-provider/dry-run",
    response_model=DryRunResponse,
    summary="Test provider boundary with dry-run — no draft created, no real LLM",
    tags=["labgen"],
)
async def run_llm_provider_dry_run(
    body: DryRunRequest,
    admin: str = Depends(require_admin_user),
) -> DryRunResponse:
    """
    Dry-run the provider boundary.

    Admin-only. Does NOT create a draft. Does NOT touch the repository.
    Does NOT call a real LLM. Does NOT return raw output.
    """
    cfg = LLMProviderBoundaryService.create_from_env().config
    from backend.labgen.llm_provider_boundary import LLMProviderConfig

    dry_run_config = LLMProviderConfig(
        provider_name=cfg.provider_name,
        mode=LLMProviderMode.DRY_RUN,
        timeout_ms=cfg.timeout_ms,
        max_output_tokens=cfg.max_output_tokens,
    )
    svc = LLMProviderBoundaryService(
        config=dry_run_config,
        dry_run_adapter=DryRunLLMProviderAdapter(inject_mode=body.inject_mode),
    )
    pr = LLMProviderRequest(
        purpose="draft_generation",
        sanitized_user_prompt=body.sanitized_prompt,
    )
    try:
        resp = svc.call(pr)
    except DryRunTimeoutSimulated:
        resp_name = cfg.provider_name.value
        return DryRunResponse(
            provider_name=resp_name,
            mode=LLMProviderMode.DRY_RUN.value,
            rejected_reason="timeout_simulated",
            warnings=["dry-run: provider timeout was simulated"],
        )

    return DryRunResponse(
        provider_name=resp.provider_name.value,
        mode=resp.mode.value,
        candidate_json=resp.candidate_json,
        warnings=resp.warnings,
        usage_summary=resp.usage_summary,
        rejected_reason=resp.rejected_reason,
    )


# ===========================================================================
# Lab Session routes — /api/lab-sessions  and  /internal/lab-sessions
# ===========================================================================

lab_session_router = APIRouter(prefix="/api/lab-sessions", tags=["lab-sessions"])
internal_router = APIRouter(prefix="/internal/lab-sessions", tags=["internal"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    lab_id: str
    vm_id: str


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


async def require_internal_token(x_admin_token: str = Header(default=None)) -> None:
    if not config.ADMIN_TOKEN or x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@lab_session_router.post("", response_model=LabSessionState, status_code=status.HTTP_201_CREATED)
async def create_lab_session(
    body: CreateSessionRequest,
    username: str = Depends(get_current_user),
    svc: LabSessionService = Depends(get_session_service),
) -> LabSessionState:
    try:
        return svc.create_session(
            lab_id=body.lab_id,
            vm_id=body.vm_id,
            student_username=username,
        )
    except PrecheckFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"precheck_failures": exc.failures},
        )


@lab_session_router.get("/{session_id}", response_model=LabSessionState)
async def get_lab_session(
    session_id: str,
    username: str = Depends(get_current_user),
    svc: LabSessionService = Depends(get_session_service),
) -> LabSessionState:
    try:
        session = svc._require_session(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session.student_username != username and not auth_manager.is_admin(username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return session


@lab_session_router.post("/{session_id}/complete", response_model=LabSessionState)
async def complete_lab_session(
    session_id: str,
    username: str = Depends(get_current_user),
    svc: LabSessionService = Depends(get_session_service),
) -> LabSessionState:
    # Fetch session first to verify ownership before mutating
    try:
        session = svc._require_session(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session.student_username != username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the session owner can complete it")

    try:
        return svc.complete_session(session_id)
    except SessionAlreadyTerminated:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already terminated")
    except LabNotReadyToComplete:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=FailureReason.LAB_NOT_READY_TO_COMPLETE.value)


@lab_session_router.post("/{session_id}/abort", response_model=LabSessionState)
async def abort_lab_session(
    session_id: str,
    username: str = Depends(get_current_user),
    svc: LabSessionService = Depends(get_session_service),
) -> LabSessionState:
    try:
        session = svc._require_session(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session.student_username != username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the session owner can abort it")

    try:
        return svc.abort_session(session_id)
    except SessionAlreadyTerminated:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already terminated")


@internal_router.post("/{session_id}/cleanup", response_model=LabSessionState)
async def internal_cleanup(
    session_id: str,
    _: None = Depends(require_internal_token),
    svc: LabSessionService = Depends(get_session_service),
) -> LabSessionState:
    try:
        return svc.run_cleanup(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


# ===========================================================================
# Verifier routes — /internal/verifier
# ===========================================================================

verifier_router = APIRouter(prefix="/internal/verifier", tags=["internal"])


class VerifierCheckRequest(BaseModel):
    session_id: str
    template: VerifyTemplate


@verifier_router.post("/check", response_model=VerifyResult)
async def verifier_check(
    body: VerifierCheckRequest,
    _: None = Depends(require_internal_token),
    svc: VerifierService = Depends(get_verifier_service),
) -> VerifyResult:
    return svc.check(body.session_id, body.template)


# ===========================================================================
# Step progression — POST /api/lab-sessions/{id}/steps/{step_id}/check
# ===========================================================================


@lab_session_router.post(
    "/{session_id}/steps/{step_id}/check",
    response_model=StepCheckResponse,
)
async def check_step(
    session_id: str,
    step_id: str,
    username: str = Depends(get_current_user),
    svc: StepProgressionService = Depends(get_step_progression_service),
) -> StepCheckResponse:
    try:
        return svc.check_step(session_id, step_id, username)
    except StepSessionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    except StepSessionNotActive as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except StepAccessDenied:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    except StepDraftUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except StepNotCurrent as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@lab_session_router.get("/{session_id}/audit-events", response_model=list[RuntimeAuditEvent])
async def get_audit_events(
    session_id: str,
    username: str = Depends(get_current_user),
    svc: LabSessionService = Depends(get_session_service),
    audit_repo: RuntimeAuditRepository = Depends(get_audit_repository),
) -> list[RuntimeAuditEvent]:
    try:
        session = svc._require_session(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session.student_username != username and not auth_manager.is_admin(username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return audit_repo.list_by_session(session_id)


# ===========================================================================
# Learner session list — GET /api/lab-sessions
# ===========================================================================


@lab_session_router.get("", response_model=list[LearnerSessionListItem])
async def list_lab_sessions(
    status: Optional[str] = None,
    lab_id: Optional[str] = None,
    username: str = Depends(get_current_user),
    svc: LearnerSessionSnapshotService = Depends(get_snapshot_service),
) -> list[LearnerSessionListItem]:
    """Return a learner-safe summary list of the current user's lab sessions."""
    return svc.list_my_sessions(
        actor_user=username,
        status_filter=status,
        lab_id_filter=lab_id,
    )


# ===========================================================================
# Learner session snapshot — GET /api/lab-sessions/{session_id}/snapshot
# ===========================================================================


@lab_session_router.get("/{session_id}/snapshot", response_model=LearnerSessionSnapshot)
async def get_session_snapshot(
    session_id: str,
    username: str = Depends(get_current_user),
    svc: LearnerSessionSnapshotService = Depends(get_snapshot_service),
) -> LearnerSessionSnapshot:
    """Return a learner-safe read-only snapshot of the session runtime state.

    READ-ONLY: does not start, check steps, complete, abort, cleanup, or create audit events.
    """
    try:
        return svc.build_snapshot(
            session_id=session_id,
            actor_user=username,
            is_admin=auth_manager.is_admin(username),
        )
    except SnapshotNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    except SnapshotAccessDenied:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


# ===========================================================================
# Lab Draft Generation — POST /api/lab-drafts/generate
# ===========================================================================

lab_draft_gen_router = APIRouter(prefix="/api/lab-drafts", tags=["lab-drafts"])

from backend.labgen.draft_repair import (  # noqa: E402
    DeterministicFakeDraftRepairAdapter,
    LabDraftRepairPort,
)
from backend.labgen.llm_generation import (  # noqa: E402
    DraftCandidateParseError,
    DraftGenerationRejected,
    DraftRepairResultView,
    FakeDraftGenerationAdapter,
    GenerateLabDraftResponse,
    LabDraftGenerationBody,
    LabDraftGenerationPort,
    LabDraftGenerationRequest,
    LabDraftGenerationService,
    build_candidate_summary,
)

_generation_svc: Optional[LabDraftGenerationService] = None
_repair_port: Optional[LabDraftRepairPort] = None


def get_generation_service() -> LabDraftGenerationService:
    global _generation_svc
    if _generation_svc is None:
        _generation_svc = LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=get_repository(),
        )
    return _generation_svc


def get_repair_port() -> LabDraftRepairPort:
    global _repair_port
    if _repair_port is None:
        _repair_port = DeterministicFakeDraftRepairAdapter()
    return _repair_port


@lab_draft_gen_router.post(
    "/generate",
    response_model=GenerateLabDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_lab_draft(
    body: LabDraftGenerationBody,
    username: str = Depends(get_current_user),
    svc: LabDraftGenerationService = Depends(get_generation_service),
    repair: LabDraftRepairPort = Depends(get_repair_port),
) -> GenerateLabDraftResponse:
    request = LabDraftGenerationRequest(
        **body.model_dump(), requester_user_id=username
    )

    try:
        outcome = svc.generate_with_repair(
            request=request,
            enable_repair=body.enable_repair,
            max_repair_attempts=body.max_repair_attempts,
            repair_port=repair if body.enable_repair else None,
        )
    except DraftGenerationRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "validation_status": "rejected",
                "rejected_reason": exc.reason,
                "validation_errors": [],
                "warnings": [],
            },
        )
    except DraftCandidateParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "validation_status": "parse_error",
                "validation_errors": exc.errors,
                "warnings": [],
            },
        )

    has_failures = any(
        r.status == ValidatorStatus.FAILED for r in outcome.validator_results
    )
    return GenerateLabDraftResponse(
        draft_id=outcome.draft.lab_id if outcome.draft else None,
        validation_status="validation_failed" if has_failures else "passed",
        validation_errors=[
            {
                "check_id": r.check_id,
                "blocking_level": r.blocking_level.value,
                "field_path": r.field_path,
                "message": r.message,
            }
            for r in outcome.validator_results
            if r.status == ValidatorStatus.FAILED
        ],
        warnings=outcome.warnings,
        selected_template_id=outcome.template_id,
        candidate_summary=(
            build_candidate_summary(outcome.draft, template_id=outcome.template_id)
            if outcome.draft else None
        ),
        review_result=outcome.review_result,
        repair_result=(
            DraftRepairResultView(
                repaired_validation_status=outcome.repair_result.repaired_validation_status,
                repair_applied=outcome.repair_result.repair_applied,
                repair_warnings=outcome.repair_result.repair_warnings,
                rejected_reason=outcome.repair_result.rejected_reason,
            )
            if outcome.repair_result is not None else None
        ),
        repair_attempted=outcome.repair_attempted,
        repair_applied=outcome.repair_applied,
    )


# ---------------------------------------------------------------------------
# Learner Lab Catalog API  — GET /api/labs  (any authenticated user)
# ---------------------------------------------------------------------------

learner_catalog_router = APIRouter(prefix="/api/labs", tags=["labs"])


@learner_catalog_router.get("", response_model=list[LearnerLabCatalogItem])
async def list_labs(
    current_user: str = Depends(get_current_user),
    svc: LearnerCatalogService = Depends(get_catalog_service),
) -> list[LearnerLabCatalogItem]:
    """
    List all published labs. Only PUBLISHED labs are returned; drafts are never revealed.
    Available to any authenticated user (learner or admin — both receive the learner-safe view).
    """
    return svc.list_published_labs(actor_user=current_user)


@learner_catalog_router.get("/{lab_id}", response_model=LearnerLabDetail)
async def get_lab_detail(
    lab_id: str,
    current_user: str = Depends(get_current_user),
    svc: LearnerCatalogService = Depends(get_catalog_service),
) -> LearnerLabDetail:
    """
    Return learner-safe detail for a published lab, including start eligibility.
    Returns 404 for both missing and unpublished labs — does not reveal draft existence.
    """
    detail = svc.get_published_lab_detail(lab_id=lab_id, actor_user=current_user)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lab not found")
    return detail


@learner_catalog_router.get("/{lab_id}/start-eligibility", response_model=LearnerLabEligibility)
async def get_start_eligibility(
    lab_id: str,
    current_user: str = Depends(get_current_user),
    svc: LearnerCatalogService = Depends(get_catalog_service),
) -> LearnerLabEligibility:
    """
    Evaluate whether the current user may start this lab.
    READ-ONLY: does not create sessions, namespaces, audit events, or VM operations.
    is_startable=true does NOT guarantee start will succeed — start re-runs image TTL recheck.
    Returns 404 for missing or unpublished labs.
    """
    eligibility = svc.evaluate_start_eligibility(lab_id=lab_id, actor_user=current_user)
    if eligibility is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lab not found")
    return eligibility


# ===========================================================================
# Demo Seed API — POST /api/labgen/demo/seed  (admin-only, dev/demo use only)
# ===========================================================================

from backend.labgen.demo_seed import (  # noqa: E402
    DemoSeedRequest,
    DemoSeedResult,
    DemoSeedService,
)

demo_seed_router = APIRouter(
    prefix="/api/labgen/demo",
    tags=["labgen-demo"],
)


def get_demo_seed_service(
    draft_repo: LabDraftRepository = Depends(get_repository),
    session_repo: LabSessionRepository = Depends(get_session_repository),
) -> DemoSeedService:
    return DemoSeedService(draft_repo=draft_repo, session_repo=session_repo)


@demo_seed_router.post(
    "/seed",
    response_model=DemoSeedResult,
    status_code=status.HTTP_200_OK,
    summary="[DEMO-ONLY] Seed demo scenario data",
    description=(
        "Seeds deterministic demo scenarios for local development and product demonstrations. "
        "DEMO-ONLY: not for production use. Admin access required. "
        "Does not call real LLM, real K8s, or real VMs. "
        "Repeatable and idempotent. Response never contains credentials or secrets."
    ),
)
async def seed_demo_data(
    body: DemoSeedRequest,
    admin: str = Depends(require_admin_user),
    svc: DemoSeedService = Depends(get_demo_seed_service),
) -> DemoSeedResult:
    return svc.seed(
        scenarios=body.scenarios,
        reset=body.reset,
        include_runtime_sessions=body.include_runtime_sessions,
    )


# ===========================================================================
# Image API — POST /api/images/resolve  and  POST /api/images/check-existence
# ===========================================================================


class ImageResolveRequest(BaseModel):
    """Batch image resolve request."""
    images: list[dict]  # each: {requested_image: str, image_intent?: str}


class ImageCheckExistenceRequest(BaseModel):
    """Batch registry existence check request."""
    images: list[ImageResolutionResult]


image_router = APIRouter(prefix="/api/images", tags=["images"])


@image_router.post(
    "/resolve",
    response_model=list[ImageResolutionResult],
    status_code=status.HTTP_200_OK,
    summary="Resolve image intents to internal registry images (batch)",
    description=(
        "Maps LLM image intents to concrete internal registry images via the whitelist. "
        "Admin only. Returns ImageResolutionResult for each input. "
        "Does NOT run registry existence checks — call /check-existence separately."
    ),
)
async def resolve_images(
    body: ImageResolveRequest,
    _admin: str = Depends(require_admin_user),
    resolver: ImageResolver = Depends(get_image_resolver),
) -> list[ImageResolutionResult]:
    requests = [
        (item.get("requested_image", ""), item.get("image_intent"))
        for item in body.images
    ]
    return resolver.resolve_images(requests)


@image_router.post(
    "/check-existence",
    response_model=list[ImageResolutionResult],
    status_code=status.HTTP_200_OK,
    summary="Check resolved images exist in internal registry (batch)",
    description=(
        "Runs registry existence checks for a list of already-resolved ImageResolutionResult objects. "
        "Only RESOLVED images are checked; BLOCKED/UNRESOLVED pass through unchanged. "
        "Admin only."
    ),
)
async def check_image_existence(
    body: ImageCheckExistenceRequest,
    _admin: str = Depends(require_admin_user),
    resolver: ImageResolver = Depends(get_image_resolver),
) -> list[ImageResolutionResult]:
    return [resolver.check_registry_existence(img) for img in body.images]
