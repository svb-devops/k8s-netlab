"""
AI Draft Review & Repair Loop — models, port, and deterministic fake adapter.

Design invariants:
  - Repair adapter MUST NOT call real LLMs, read API keys, or make network requests.
  - Repair adapter MUST NOT return raw_model_output, traceback, kubeconfig, or credential content.
  - Repair adapter MUST NOT produce fields outside Contract v0.1.
  - Service is responsible for re-running Pydantic + StaticValidator on repaired candidate.
  - repaired_validation_status is set by the SERVICE after actual validation, not by the adapter.
"""

from __future__ import annotations

import abc
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from backend.labgen.generation_templates import GenerationTemplateRegistry


# ---------------------------------------------------------------------------
# Issue models
# ---------------------------------------------------------------------------


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class IssueSource(str, Enum):
    PYDANTIC = "pydantic"
    STATIC_VALIDATOR = "static_validator"
    SAFETY = "safety"


class DraftReviewIssue(BaseModel):
    code: str
    message: str
    path: Optional[str] = None
    severity: IssueSeverity
    source: IssueSource


class DraftReviewResult(BaseModel):
    is_valid: bool
    issues: list[DraftReviewIssue] = Field(default_factory=list)
    sanitized_summary: str
    selected_template_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Repair request / result models
# ---------------------------------------------------------------------------


class DraftRepairRequest(BaseModel):
    original_candidate: dict
    review_result: DraftReviewResult
    selected_template_id: Optional[str] = None
    requester_user_id: str
    max_repair_attempts: int = Field(default=1, ge=1, le=2)


class DraftRepairResult(BaseModel):
    # Set by the adapter — the raw candidate dict it wants the service to validate.
    # None if the adapter refuses to produce a candidate (see rejected_reason).
    repaired_candidate: Optional[dict] = None

    # Set by the SERVICE after running Pydantic + StaticValidator:
    #   "not_attempted" | "passed" | "still_invalid" | "malformed" | "repair_failed"
    repaired_validation_status: str = "not_attempted"

    # True when the adapter produced a candidate (even if still invalid or malformed).
    # False when the adapter refused or the repaired candidate failed Pydantic parse.
    repair_applied: bool = False

    repair_warnings: list[str] = Field(default_factory=list)
    rejected_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Port interface
# ---------------------------------------------------------------------------


class LabDraftRepairPort(abc.ABC):
    @abc.abstractmethod
    def repair_draft_candidate(
        self, request: DraftRepairRequest
    ) -> DraftRepairResult:
        """
        Attempt to produce a repaired candidate dict.

        MUST NOT:
          - call real LLMs or make network requests
          - read live API keys from the environment
          - return raw_model_output / traceback / kubeconfig / credential content
          - produce fields outside Contract v0.1
          - set repaired_validation_status (that is the service's responsibility)
        """


# ---------------------------------------------------------------------------
# Deterministic fake adapter — testing + MVP placeholder
# ---------------------------------------------------------------------------


class DeterministicFakeDraftRepairAdapter(LabDraftRepairPort):
    """
    Deterministic repair adapter.  No LLM, no network, no API keys.

    inject_mode controls behaviour:
      "success"       → valid template-based candidate (passes Pydantic + StaticValidator)
      "still_invalid" → passes Pydantic, fails StaticValidator (cleanup=None)
      "malformed"     → fails Pydantic (title is int, steps is str)
      "sensitive"     → valid candidate but credential-like strings in warnings
    """

    def __init__(self, inject_mode: str = "success") -> None:
        self._mode = inject_mode
        self._registry = GenerationTemplateRegistry()

    def repair_draft_candidate(
        self, request: DraftRepairRequest
    ) -> DraftRepairResult:
        if self._mode == "malformed":
            return DraftRepairResult(
                repaired_candidate={"title": 99999, "steps": "broken"},
                repair_applied=True,
                repair_warnings=["fake repair: generated malformed output"],
            )

        if self._mode == "still_invalid":
            # Valid Pydantic structure but missing cleanup — fails cleanup.declared
            candidate = self._build_valid_candidate()
            candidate["cleanup"] = None
            return DraftRepairResult(
                repaired_candidate=candidate,
                repair_applied=True,
                repair_warnings=["fake repair: still could not fix cleanup constraint"],
            )

        if self._mode == "sensitive":
            candidate = self._build_valid_candidate()
            return DraftRepairResult(
                repaired_candidate=candidate,
                repair_applied=True,
                repair_warnings=[
                    "repair used token=eyJhbGciOiJSUzI1NiJ9.fake.payload",
                    "repair: password=hunter2 seen in context window",
                ],
            )

        # "success" (default)
        return DraftRepairResult(
            repaired_candidate=self._build_valid_candidate(),
            repair_applied=True,
            repair_warnings=["fake repair: applied template-based fix"],
        )

    def _build_valid_candidate(self) -> dict:
        selection = self._registry.select("repaired lab candidate", None, None)
        template = self._registry.get_by_id(selection.selected_template_id)
        return template.build_candidate("repaired lab candidate", None, None)
