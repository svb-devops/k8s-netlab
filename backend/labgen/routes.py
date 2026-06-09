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
from pydantic import BaseModel

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


@router.post("/drafts/{lab_id}/publish", response_model=LabDraft)
async def publish_draft(
    lab_id: str,
    admin: str = Depends(require_admin_user),
    repo: LabDraftRepository = Depends(get_repository),
    svc: PublishService = Depends(get_publish_service),
) -> LabDraft:
    draft = repo.get(lab_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    updated = svc.publish(draft)
    saved = repo.update(updated)

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
# Lab Draft Generation — POST /api/lab-drafts/generate
# ===========================================================================

lab_draft_gen_router = APIRouter(prefix="/api/lab-drafts", tags=["lab-drafts"])

from backend.labgen.llm_generation import (  # noqa: E402
    DraftCandidateParseError,
    DraftGenerationRejected,
    FakeDraftGenerationAdapter,
    GenerateLabDraftResponse,
    LabDraftGenerationBody,
    LabDraftGenerationPort,
    LabDraftGenerationRequest,
    LabDraftGenerationService,
    build_candidate_summary,
)

_generation_svc: Optional[LabDraftGenerationService] = None


def get_generation_service() -> LabDraftGenerationService:
    global _generation_svc
    if _generation_svc is None:
        _generation_svc = LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=get_repository(),
        )
    return _generation_svc


@lab_draft_gen_router.post(
    "/generate",
    response_model=GenerateLabDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_lab_draft(
    body: LabDraftGenerationBody,
    username: str = Depends(get_current_user),
    svc: LabDraftGenerationService = Depends(get_generation_service),
) -> GenerateLabDraftResponse:
    request = LabDraftGenerationRequest(
        **body.model_dump(), requester_user_id=username
    )

    try:
        draft, validator_results, warnings = svc.generate_and_create(request)
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
        r.status == ValidatorStatus.FAILED for r in validator_results
    )
    return GenerateLabDraftResponse(
        draft_id=draft.lab_id,
        validation_status="validation_failed" if has_failures else "passed",
        validation_errors=[
            {
                "check_id": r.check_id,
                "blocking_level": r.blocking_level.value,
                "field_path": r.field_path,
                "message": r.message,
            }
            for r in validator_results
            if r.status == ValidatorStatus.FAILED
        ],
        warnings=warnings,
        candidate_summary=build_candidate_summary(draft),
    )
