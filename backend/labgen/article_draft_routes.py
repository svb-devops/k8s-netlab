"""
Article-to-Lab Draft API routes.

All endpoints are admin-only. Learners never see ArticleDraftLabContracts.
Route layer delegates all business logic to ArticleDraftService.

Endpoints:
  POST   /api/labgen/article-drafts                  Create draft from article text
  GET    /api/labgen/article-drafts                   List all drafts
  GET    /api/labgen/article-drafts/{id}              Get draft
  PATCH  /api/labgen/article-drafts/{id}              Update draft fields
  POST   /api/labgen/article-drafts/{id}/review       Record admin decision
  POST   /api/labgen/article-drafts/{id}/validate     Run ArticleDraftValidator
  POST   /api/labgen/article-drafts/{id}/advance      Advance status step
  POST   /api/labgen/article-drafts/{id}/convert      Convert to LabDraft
  DELETE /api/labgen/article-drafts/{id}              Delete draft
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.auth import auth_manager
from backend.auth_deps import get_current_user
from backend.labgen.article_draft_service import (
    ArticleDraftGuardrailBlocked,
    ArticleDraftNotFound,
    ArticleDraftService,
    ArticleDraftTransitionForbidden,
    ArticleOperabilityRejected,
    LLMGenerationFailed,
    LLMDraftParseError,
)
from backend.labgen.article_models import (
    AdminDecisionValue,
    ArticleDraftLabContract,
    ArticleDraftStatus,
    ArticleLabRuntimeRequirement,
    ArticleSourceMetadata,
    ArticleSourceType,
    SourceGroundingSnippet,
    VerifierCandidate,
)
from backend.labgen.models import LabDraft
from backend.labgen.stub_feasibility_classifier import compute_content_hash

router = APIRouter(prefix="/api/labgen/article-drafts", tags=["labgen-article-drafts"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def _require_admin(username: str = Depends(get_current_user)) -> str:
    if not auth_manager.is_admin(username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return username


# ---------------------------------------------------------------------------
# Dependency injection (overridable in tests)
# ---------------------------------------------------------------------------

_article_draft_service: Optional[ArticleDraftService] = None


def get_article_draft_service() -> ArticleDraftService:
    global _article_draft_service
    if _article_draft_service is None:
        _article_draft_service = ArticleDraftService()
    return _article_draft_service


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


_ALLOWED_PUBLISH_CHANNELS = frozenset({
    "official_site", "wechat", "zhihu", "csdn", "github", "other"
})

_ALLOWED_TARGET_DOMAINS = frozenset({"k8s", "linux"})


class CreateArticleDraftRequest(BaseModel):
    """
    Admin submits article text for feasibility assessment and draft creation.

    raw_text is processed and classified; it is NEVER persisted.
    source_metadata.raw_text_persisted must be False (default).

    Phase 1 Soft Launch additions:
      - target_domain: k8s | linux (required for operability gate accuracy)
      - copyright_confirmed: must be True before submission is accepted
      - intended_reader, publish_channel, safety_notes, desired_lab_title
    """

    raw_text: str
    title: Optional[str] = None
    author: Optional[str] = None
    source_url: Optional[str] = None
    source_type: ArticleSourceType = ArticleSourceType.PASTED_TEXT
    language: Optional[str] = None
    user_confirmed_right_to_use: bool = False
    user_confirmed_no_secrets: bool = False
    # Phase 1 Soft Launch fields
    target_domain: Optional[str] = None          # k8s | linux (hints feasibility classifier)
    intended_reader: Optional[str] = None        # e.g. "intermediate k8s practitioner"
    publish_channel: Optional[str] = None        # official_site | wechat | zhihu | csdn | github | other
    copyright_confirmed: bool = False            # admin confirms right to use content
    safety_notes: Optional[str] = None          # admin safety notes (not stored in raw form)
    desired_lab_title: Optional[str] = None     # admin-suggested lab title for LLM generation


class PatchArticleDraftRequest(BaseModel):
    """Admin-editable fields. Omit to leave unchanged."""

    learning_objective: Optional[str] = None
    environment_requirements: Optional[list[str]] = None
    learner_steps: Optional[list[str]] = None
    expected_artifacts: Optional[list[str]] = None
    cleanup_requirements: Optional[list[str]] = None
    safety_constraints: Optional[list[str]] = None
    terminal_requirements: Optional[list[str]] = None
    estimated_duration_minutes: Optional[int] = None
    review_notes: Optional[list[str]] = None
    # Pipeline-critical fields: admin must populate before advancing to publish candidate
    source_grounding: Optional[list[SourceGroundingSnippet]] = None
    required_runtime: Optional[ArticleLabRuntimeRequirement] = None
    verifier_candidates: Optional[list[VerifierCandidate]] = None


class AdminReviewRequest(BaseModel):
    """Record an admin review decision on an article draft."""

    decision: AdminDecisionValue
    comments: list[str] = []
    required_changes: list[str] = []
    confirmed_source_grounding: bool = False
    confirmed_safety: bool = False
    confirmed_cleanup: bool = False
    confirmed_verifier_strategy: bool = False
    confirmed_no_raw_secret: bool = False
    confirmed_no_direct_publish: bool = False


class AdvanceStatusRequest(BaseModel):
    """Advance the draft status by one step."""

    target_status: ArticleDraftStatus


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _not_found(draft_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Article draft not found: {draft_id}",
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _conflict(detail: str, extra: dict | None = None) -> HTTPException:
    content = {"detail": detail}
    if extra:
        content.update(extra)
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=content,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ArticleDraftLabContract,
    status_code=status.HTTP_201_CREATED,
)
async def create_article_draft(
    req: CreateArticleDraftRequest,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> ArticleDraftLabContract:
    """
    Classify article text and create an ArticleDraftLabContract.

    raw_text is used for classification only and is never persisted.
    content_hash is computed here and stored in source_metadata.

    Phase 1 Soft Launch: copyright_confirmed=True is required.
    target_domain (k8s|linux) improves operability gate accuracy.
    """
    if not req.raw_text or not req.raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="raw_text must not be empty",
        )

    # copyright_confirmed gate (Phase 1 Soft Launch requirement)
    if not req.copyright_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="copyright_confirmed must be True — confirm right to use article content",
        )

    # Internal sample marker blocker — prevents test/trial articles from entering the
    # production publish pipeline.  Real owner articles must not carry this prefix.
    if req.title and req.title.strip().upper().startswith("[INTERNAL SAMPLE]"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Article title must not use [INTERNAL SAMPLE] marker — submit a real owner-authored article",
        )

    # target_domain validation
    if req.target_domain is not None:
        if req.target_domain.lower() not in _ALLOWED_TARGET_DOMAINS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"target_domain must be one of: {sorted(_ALLOWED_TARGET_DOMAINS)}",
            )

    # publish_channel validation
    if req.publish_channel is not None:
        if req.publish_channel.lower() not in _ALLOWED_PUBLISH_CHANNELS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"publish_channel must be one of: {sorted(_ALLOWED_PUBLISH_CHANNELS)}",
            )

    content_hash = compute_content_hash(req.raw_text)

    source_metadata = ArticleSourceMetadata(
        source_type=req.source_type,
        title=req.title,
        author=req.author,
        source_url=req.source_url,
        submitted_by_user_id=admin,
        content_hash=content_hash,
        content_length=len(req.raw_text),
        language=req.language,
        user_confirmed_right_to_use=req.user_confirmed_right_to_use,
        user_confirmed_no_secrets=req.user_confirmed_no_secrets,
        raw_text_persisted=False,
    )

    return svc.create_draft(
        raw_text=req.raw_text,
        source_metadata=source_metadata,
        submitted_by=admin,
    )


@router.get("", response_model=list[ArticleDraftLabContract])
async def list_article_drafts(
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> list[ArticleDraftLabContract]:
    return svc.list_drafts()


@router.get("/{draft_id}", response_model=ArticleDraftLabContract)
async def get_article_draft(
    draft_id: str,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> ArticleDraftLabContract:
    try:
        return svc.get_draft(draft_id)
    except ArticleDraftNotFound:
        raise _not_found(draft_id)


@router.patch("/{draft_id}", response_model=ArticleDraftLabContract)
async def patch_article_draft(
    draft_id: str,
    req: PatchArticleDraftRequest,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> ArticleDraftLabContract:
    # Use getattr to preserve Pydantic model instances (model_dump converts them to dicts)
    updates = {k: getattr(req, k) for k in req.model_fields_set if getattr(req, k) is not None}
    try:
        return svc.update_draft(draft_id, updates, updated_by=admin)
    except ArticleDraftNotFound:
        raise _not_found(draft_id)
    except ArticleDraftTransitionForbidden as exc:
        raise _forbidden(str(exc))


@router.post("/{draft_id}/review", response_model=ArticleDraftLabContract)
async def record_admin_review(
    draft_id: str,
    req: AdminReviewRequest,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> ArticleDraftLabContract:
    try:
        return svc.record_admin_decision(
            draft_id=draft_id,
            decision=req.decision,
            reviewer_id=admin,
            comments=req.comments,
            required_changes=req.required_changes,
            confirmed_source_grounding=req.confirmed_source_grounding,
            confirmed_safety=req.confirmed_safety,
            confirmed_cleanup=req.confirmed_cleanup,
            confirmed_verifier_strategy=req.confirmed_verifier_strategy,
            confirmed_no_raw_secret=req.confirmed_no_raw_secret,
            confirmed_no_direct_publish=req.confirmed_no_direct_publish,
        )
    except ArticleDraftNotFound:
        raise _not_found(draft_id)
    except ArticleDraftTransitionForbidden as exc:
        raise _forbidden(str(exc))
    except ArticleDraftGuardrailBlocked as exc:
        raise _conflict(
            "Guardrail checks blocked the review action",
            {"blocked_checks": exc.blocked_checks},
        )


@router.post("/{draft_id}/validate", response_model=list[dict])
async def validate_article_draft(
    draft_id: str,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> list[dict]:
    try:
        return svc.validate_draft(draft_id)
    except ArticleDraftNotFound:
        raise _not_found(draft_id)


@router.post("/{draft_id}/advance", response_model=ArticleDraftLabContract)
async def advance_draft_status(
    draft_id: str,
    req: AdvanceStatusRequest,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> ArticleDraftLabContract:
    """
    Advance draft status by one step.

    APPROVED_FOR_STATIC_VALIDATION → APPROVED_FOR_INTERNAL_REHEARSAL:
      target_status = approved_for_internal_rehearsal

    APPROVED_FOR_INTERNAL_REHEARSAL → APPROVED_FOR_PUBLISH_CANDIDATE:
      target_status = approved_for_publish_candidate
    """
    try:
        if req.target_status == ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL:
            return svc.advance_to_internal_rehearsal(draft_id)
        elif req.target_status == ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE:
            return svc.advance_to_publish_candidate(draft_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot advance to {req.target_status} via this endpoint — use /review instead",
            )
    except ArticleDraftNotFound:
        raise _not_found(draft_id)
    except ArticleDraftTransitionForbidden as exc:
        raise _forbidden(str(exc))
    except ArticleDraftGuardrailBlocked as exc:
        raise _conflict(
            "Guardrail checks blocked status advance",
            {"blocked_checks": exc.blocked_checks},
        )


@router.post("/{draft_id}/convert", response_model=LabDraft, status_code=status.HTTP_201_CREATED)
async def convert_to_lab_draft(
    draft_id: str,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> LabDraft:
    """
    Convert APPROVED_FOR_PUBLISH_CANDIDATE article draft → LabDraft (DRAFT status).

    Does NOT publish the resulting LabDraft.
    Admin must still run StaticValidator + publish flow before learners can see it.
    """
    try:
        return svc.convert_to_lab_draft(draft_id, converted_by=admin)
    except ArticleDraftNotFound:
        raise _not_found(draft_id)
    except ArticleDraftTransitionForbidden as exc:
        raise _forbidden(str(exc))


class GenerateLabFromArticleRequest(BaseModel):
    """
    Admin re-submits article text to trigger LLM-based LabDraft generation.

    article_text is used for LLM generation only — it is NEVER persisted.
    The feasibility result from the stored ArticleDraftLabContract gates generation.

    LABGEN_LLM_MODE controls whether fake or live LLM is used:
      fake_only       — deterministic template-based generation (default)
      live_admin_only — calls real LLM (requires LABGEN_LLM_OPENAI_* config)
    """

    article_text: str
    desired_lab_title: Optional[str] = None


class GenerateLabFromArticleResponse(BaseModel):
    lab_draft_id: str
    operability_status: str          # directly_lab_ready | partially_lab_ready
    validation_passed: bool          # no PUBLISH_BLOCKING validator results
    warnings: list[str]
    audit_id: str
    llm_mode: str                    # fake_only | live_admin_only (active mode)


@router.post(
    "/{draft_id}/generate-lab",
    response_model=GenerateLabFromArticleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_lab_from_article(
    draft_id: str,
    req: GenerateLabFromArticleRequest,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> GenerateLabFromArticleResponse:
    """
    Generate a LabDraft from an article using the configured LLM mode.

    Requires:
      - Admin authentication
      - Existing ArticleDraftLabContract (from POST /api/labgen/article-drafts)
      - Article feasibility NOT_LAB_READY → 422
      - article_text re-submitted (never stored, used for generation only)

    Generated LabDraft is always DRAFT status. Admin must:
      - Review / edit via PATCH /api/labgen/drafts/{lab_id}
      - Run StaticValidator via POST /api/labgen/drafts/{lab_id}/validate
      - Run Internal Rehearsal
      - Publish via POST /api/labgen/drafts/{lab_id}/publish

    LABGEN_LLM_MODE env var controls generation mode:
      fake_only       — deterministic, no real LLM (default, safe for tests)
      live_admin_only — calls real LLM (requires LABGEN_LLM_OPENAI_* configuration)
    """
    from backend import config as cfg

    if not req.article_text or not req.article_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="article_text must not be empty",
        )

    try:
        result = svc.generate_lab_from_article(
            draft_id=draft_id,
            article_text=req.article_text,
            admin_user=admin,
            desired_lab_title=req.desired_lab_title,
        )
    except ArticleDraftNotFound:
        raise _not_found(draft_id)
    except ArticleOperabilityRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "operability_rejected",
                "rejection_code": exc.rejection_code,
                "reasons": exc.reasons,
                "message": "Article is NOT_LAB_READY — LLM generation not allowed",
            },
        )
    except LLMGenerationFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "llm_generation_failed",
                "reason": exc.reason,
                "message": "LLM generation failed — check LABGEN_LLM_MODE and provider config",
            },
        )
    except LLMDraftParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "draft_parse_error",
                "parse_errors": exc.errors,
                "message": "LLM output could not be parsed as a valid LabDraft",
            },
        )

    return GenerateLabFromArticleResponse(
        lab_draft_id=result.lab_draft.lab_id,
        operability_status=result.operability_status,
        validation_passed=result.validation_passed,
        warnings=result.warnings,
        audit_id=result.audit_id,
        llm_mode=cfg.LABGEN_LLM_MODE,
    )


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article_draft(
    draft_id: str,
    admin: str = Depends(_require_admin),
    svc: ArticleDraftService = Depends(get_article_draft_service),
) -> None:
    try:
        svc.delete_draft(draft_id)
    except ArticleDraftNotFound:
        raise _not_found(draft_id)
    except ArticleDraftTransitionForbidden as exc:
        raise _forbidden(str(exc))
