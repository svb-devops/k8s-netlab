"""
ImageReadinessService — evaluates whether a draft's images are ready for publish.

Works from pre-computed ImageResolutionResult list (stored on the draft).
No network calls; no LLM; no K3s.

Result status semantics:
  READY        — all images resolved and existence-checked (or no images)
  BLOCKED      — at least one image has ImageStatus.BLOCKED
  UNRESOLVED   — at least one image has ImageStatus.UNRESOLVED (no BLOCKED)
  NOT_FOUND    — at least one RESOLVED image failed registry existence check
  CHECK_FAILED — evaluation raised an unexpected exception (safe fallback)
  UNKNOWN      — images present but status cannot be determined (should not occur in practice)

Design invariants:
  - Never leaks registry credentials, tokens, secrets, or stack traces.
  - All message strings pass through sanitize_text before being placed in issues.
  - Empty image list → READY (no images = nothing to block).
  - checks_deferred=True when any RESOLVED image has existence_check_passed=None.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from backend.labgen.models import ImageResolutionResult, ImageStatus

logger = logging.getLogger(__name__)


class ImageReadinessStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    UNRESOLVED = "UNRESOLVED"
    NOT_FOUND = "NOT_FOUND"
    CHECK_FAILED = "CHECK_FAILED"
    UNKNOWN = "UNKNOWN"


class ImageReadinessIssue(BaseModel):
    code: str
    message: str
    severity: str   # "error" | "warning"
    source: str     # "image_resolver" | "registry_check" | "service"
    path: Optional[str] = None


class ImageReadinessResult(BaseModel):
    status: ImageReadinessStatus
    resolved_image_count: int = 0
    unresolved_image_count: int = 0
    blocked_image_count: int = 0
    missing_image_count: int = 0   # RESOLVED but existence_check_passed=False
    issues: list[ImageReadinessIssue] = Field(default_factory=list)
    checked_at: str    # ISO 8601 UTC
    checks_deferred: bool = False  # True if any RESOLVED image skipped TTL recheck


class ImageReadinessService:
    """
    Evaluate image readiness from a pre-computed ImageResolutionResult list.

    Stateless and pure: same input → same output.  No external I/O.
    """

    def evaluate(self, images: list[ImageResolutionResult]) -> ImageReadinessResult:
        from backend.labgen.llm_generation import sanitize_text

        checked_at = datetime.now(tz=timezone.utc).isoformat()

        if not images:
            return ImageReadinessResult(
                status=ImageReadinessStatus.READY,
                checked_at=checked_at,
            )

        try:
            return self._evaluate_images(images, checked_at, sanitize_text)
        except Exception as exc:
            logger.warning("ImageReadinessService.evaluate raised unexpectedly: %s", exc)
            return ImageReadinessResult(
                status=ImageReadinessStatus.CHECK_FAILED,
                checked_at=checked_at,
                issues=[
                    ImageReadinessIssue(
                        code="IMAGE_CHECK_FAILED",
                        message="Image readiness check encountered an internal error",
                        severity="error",
                        source="service",
                    )
                ],
            )

    def _evaluate_images(
        self,
        images: list[ImageResolutionResult],
        checked_at: str,
        sanitize_text,
    ) -> ImageReadinessResult:
        issues: list[ImageReadinessIssue] = []
        resolved_count = 0
        unresolved_count = 0
        blocked_count = 0
        missing_count = 0
        checks_deferred = False

        for img in images:
            intent_label = img.image_intent or img.requested_image

            if img.image_status == ImageStatus.BLOCKED:
                blocked_count += 1
                issues.append(ImageReadinessIssue(
                    code="IMAGE_BLOCKED",
                    message=sanitize_text(
                        f"Image '{intent_label}' is blocked: "
                        "external registry or forbidden tag — "
                        "use internal registry with a pinned version"
                    ),
                    severity="error",
                    source="image_resolver",
                    path=f"image_resolution[{img.requested_image}]",
                ))

            elif img.image_status == ImageStatus.UNRESOLVED:
                unresolved_count += 1
                issues.append(ImageReadinessIssue(
                    code="IMAGE_UNRESOLVED",
                    message=sanitize_text(
                        f"Image '{intent_label}' could not be resolved to an internal "
                        "registry image — add it to the whitelist"
                    ),
                    severity="error",
                    source="image_resolver",
                    path=f"image_resolution[{img.requested_image}]",
                ))

            elif img.image_status == ImageStatus.RESOLVED:
                resolved_count += 1
                if img.existence_check_passed is False:
                    missing_count += 1
                    issues.append(ImageReadinessIssue(
                        code="IMAGE_NOT_FOUND",
                        message=sanitize_text(
                            f"Image '{intent_label}' resolved but not found in the "
                            "internal registry — ensure it has been pushed"
                        ),
                        severity="error",
                        source="registry_check",
                        path=f"image_resolution[{img.requested_image}]",
                    ))
                elif img.existence_check_passed is None:
                    checks_deferred = True

            else:
                issues.append(ImageReadinessIssue(
                    code="IMAGE_STATUS_UNKNOWN",
                    message=sanitize_text(
                        f"Image '{intent_label}' has an unknown status"
                    ),
                    severity="warning",
                    source="service",
                ))

        # Determine overall status: worst case wins
        if blocked_count > 0:
            overall = ImageReadinessStatus.BLOCKED
        elif unresolved_count > 0:
            overall = ImageReadinessStatus.UNRESOLVED
        elif missing_count > 0:
            overall = ImageReadinessStatus.NOT_FOUND
        elif any(i.code == "IMAGE_STATUS_UNKNOWN" for i in issues):
            overall = ImageReadinessStatus.UNKNOWN
        else:
            overall = ImageReadinessStatus.READY

        if checks_deferred and overall == ImageReadinessStatus.READY:
            issues.append(ImageReadinessIssue(
                code="RUNTIME_IMAGE_RECHECK_DEFERRED",
                message=sanitize_text(
                    "Registry existence checks were not run — "
                    "image availability will be re-verified at lab start"
                ),
                severity="warning",
                source="registry_check",
            ))

        return ImageReadinessResult(
            status=overall,
            resolved_image_count=resolved_count,
            unresolved_image_count=unresolved_count,
            blocked_image_count=blocked_count,
            missing_image_count=missing_count,
            issues=issues,
            checked_at=checked_at,
            checks_deferred=checks_deferred,
        )
