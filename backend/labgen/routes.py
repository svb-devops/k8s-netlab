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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.auth import auth_manager
from backend.auth_deps import get_current_user
from backend.labgen.models import (
    AdminReviewDiff,
    AdminReviewDiffChange,
    BlockingLevel,
    CleanupSpec,
    ImageResolutionResult,
    LabDraft,
    PublishStatus,
    Step,
    ValidatorResult,
    ValidatorStatus,
)
from backend.labgen.repository import LabDraftRepository
from backend.labgen.review_diff import AdminReviewDiffRepository
from backend.labgen.static_validator import StaticValidator
from backend.labgen.stub_generator import LabDraftGeneratorStub

router = APIRouter(prefix="/api/labgen", tags=["labgen"])


# ---------------------------------------------------------------------------
# Dependency providers  (override in tests via app.dependency_overrides)
# ---------------------------------------------------------------------------


_repo: Optional[LabDraftRepository] = None
_generator: Optional[LabDraftGeneratorStub] = None
_validator: Optional[StaticValidator] = None
_diff_repo: Optional[AdminReviewDiffRepository] = None


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


def get_diff_repository() -> AdminReviewDiffRepository:
    global _diff_repo
    if _diff_repo is None:
        _diff_repo = AdminReviewDiffRepository()
    return _diff_repo


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
