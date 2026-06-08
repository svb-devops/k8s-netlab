"""
PublishService — orchestrates publish validation for LabDraft.

Always re-runs StaticValidator and registry existence checks on publish.
review_required results do not block MVP publish.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.labgen.image_resolver import ImageResolver
from backend.labgen.models import (
    BlockingLevel,
    LabDraft,
    PublishStatus,
    ValidatorStatus,
)
from backend.labgen.static_validator import StaticValidator


class PublishService:
    def __init__(self, validator: StaticValidator, image_resolver: ImageResolver) -> None:
        self._validator = validator
        self._image_resolver = image_resolver

    def publish(self, draft: LabDraft) -> LabDraft:
        # Always re-run StaticValidator (never trust stale results)
        results = self._validator.validate(draft)

        # Always re-run registry existence check for all images
        draft.image_resolution = [
            self._image_resolver.check_registry_existence(img)
            for img in draft.image_resolution
        ]

        has_blocking_failure = any(
            r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
            for r in results
        )

        draft.validator_results = results
        draft.publish_status = (
            PublishStatus.PUBLISH_BLOCKED if has_blocking_failure else PublishStatus.PUBLISHED
        )
        draft.updated_at = datetime.now(tz=timezone.utc)

        return draft
