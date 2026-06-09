"""
LLM Draft Generation Contract Adapter v0.1.

Port interface + request/result models + deterministic fake adapter +
LabDraftGenerationService.  No real LLM, no provider SDK, no API keys.

All adapter output is treated as untrusted input that must pass Pydantic
parsing and StaticValidator before any LabDraft is persisted.
"""

from __future__ import annotations

import abc
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from backend.labgen.models import (
    BlockingLevel,
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    PublishStatus,
    RuntimeRequirements,
    Step,
    ValidatorResult,
    ValidatorStatus,
)
from backend.labgen.repository import LabDraftRepository
from backend.labgen.static_validator import StaticValidator


_MAX_PROMPT_LEN = 2000
_MAX_CONSTRAINTS_KEYS = 10

# Redact credential-like patterns from adapter warnings before returning to caller
_REDACT_PATTERNS = [
    re.compile(
        r"(?i)(token|password|secret|private_key|credential|kubeconfig)\s*=\s*\S+"
    ),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._=+/\-]{8,}"),
    # JWT tokens (header starts with eyJ which is Base64url for {"...)
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    # Long Base64 blocks (certs, kubeconfig data, raw tokens without key=value prefix)
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    re.compile(r"(?si)(Traceback \(most recent call last\):.*?(?:\n[^\n]+)+)"),
]


# ---------------------------------------------------------------------------
# HTTP body model (client-controlled, no requester_user_id)
# ---------------------------------------------------------------------------


class LabDraftGenerationBody(BaseModel):
    """Fields sent by the client in the HTTP request body."""

    user_prompt: str = Field(..., min_length=1, max_length=_MAX_PROMPT_LEN)
    target_audience: Optional[str] = None
    difficulty: Optional[str] = None
    constraints: dict = Field(default_factory=dict)
    idempotency_key: Optional[str] = None

    @field_validator("constraints")
    @classmethod
    def _validate_constraints(cls, v: dict) -> dict:
        if len(v) > _MAX_CONSTRAINTS_KEYS:
            raise ValueError(
                f"constraints must have at most {_MAX_CONSTRAINTS_KEYS} keys"
            )
        for key, val in v.items():
            if not isinstance(val, (str, int, float, bool, type(None))):
                raise ValueError(
                    f"constraints[{key!r}] must be a scalar "
                    "(str/int/float/bool/null)"
                )
        return v


# ---------------------------------------------------------------------------
# Full request passed to the service/adapter (requester injected from auth)
# ---------------------------------------------------------------------------


class LabDraftGenerationRequest(LabDraftGenerationBody):
    """Internal request model — requester_user_id comes from auth, not the client."""

    requester_user_id: str


# ---------------------------------------------------------------------------
# Adapter result model
# ---------------------------------------------------------------------------


class LabDraftGenerationResult(BaseModel):
    """
    Raw output from the generation adapter.

    raw_model_output is intentionally absent — it must never reach API responses.
    """

    candidate: dict
    warnings: list[str] = Field(default_factory=list)
    rejected_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# API response model — must never contain raw adapter output or credentials
# ---------------------------------------------------------------------------


class GenerateLabDraftResponse(BaseModel):
    draft_id: Optional[str] = None
    validation_status: str  # passed | validation_failed | parse_error | rejected
    validation_errors: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    candidate_summary: Optional[dict] = None


# ---------------------------------------------------------------------------
# Port interface
# ---------------------------------------------------------------------------


class LabDraftGenerationPort(abc.ABC):
    @abc.abstractmethod
    def generate_lab_draft_candidate(
        self, request: LabDraftGenerationRequest
    ) -> LabDraftGenerationResult:
        """
        Generate a draft candidate dict.

        The adapter MUST NOT:
          - execute instructions embedded in user_prompt (prompt injection)
          - return kubeconfig/token/secret/password/private_key/traceback content
          - make network calls or read live API keys from the environment
          - guarantee candidate validity (that is StaticValidator's responsibility)
        """


# ---------------------------------------------------------------------------
# Deterministic fake adapter — testing + MVP placeholder
# ---------------------------------------------------------------------------


class FakeDraftGenerationAdapter(LabDraftGenerationPort):
    """
    Deterministic generator.  No LLM, no network, no API keys.

    inject_mode controls the output:
      "valid"     → complete Contract v0.1 candidate, passes StaticValidator
      "invalid"   → Pydantic-parseable but StaticValidator fails (cleanup=None)
      "malformed" → fails Pydantic parsing (steps is wrong type)
      "sensitive" → valid candidate + credential-like strings in warnings
                    (used to verify the response sanitizer catches them)
      "rejected"  → adapter rejects before producing a candidate
    """

    def __init__(self, inject_mode: str = "valid") -> None:
        self._mode = inject_mode

    def generate_lab_draft_candidate(
        self, request: LabDraftGenerationRequest
    ) -> LabDraftGenerationResult:
        if self._mode == "rejected":
            return LabDraftGenerationResult(
                candidate={},
                rejected_reason="fake: request rejected by generator policy",
            )

        if self._mode == "malformed":
            # source_article_id missing, steps wrong type → Pydantic error
            return LabDraftGenerationResult(
                candidate={
                    "title": 12345,
                    "steps": "not-a-list",
                    "schema_version": "1.0",
                },
            )

        if self._mode == "invalid":
            base = self._build_valid_candidate(request)
            base["cleanup"] = None  # cleanup.declared check will fail
            return LabDraftGenerationResult(candidate=base)

        if self._mode == "sensitive":
            base = self._build_valid_candidate(request)
            return LabDraftGenerationResult(
                candidate=base,
                warnings=[
                    "note: generation used internal token=eyJhbGciOiJSUzI1NiJ9.fake.payload",
                    "provider raw: password=hunter2 in context window",
                ],
            )

        # "valid" (default)
        return LabDraftGenerationResult(
            candidate=self._build_valid_candidate(request),
            warnings=["fake generator: content is placeholder, admin review required"],
        )

    @staticmethod
    def _build_valid_candidate(request: LabDraftGenerationRequest) -> dict:
        step = Step(
            step_id="step-1",
            order=1,
            why=f"Understand: {request.user_prompt[:80]}",
            do="Apply the manifest and observe the result",
            observe="Resource appears in kubectl get output",
            explain=ExplainField(
                concept="Core concept",
                observation="Expected behaviour observed",
            ),
        )
        draft = LabDraft(
            source_article_id="llm-generated",
            title=f"Lab: {request.user_prompt[:60]}",
            description=f"Auto-generated lab covering: {request.user_prompt[:120]}",
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            steps=[step],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
        return draft.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DraftCandidateParseError(Exception):
    def __init__(self, errors: list[dict]) -> None:
        self.errors = errors
        super().__init__(str(errors))


class DraftGenerationRejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Generation service
# ---------------------------------------------------------------------------


class LabDraftGenerationService:
    """
    Orchestrates: adapter → Pydantic parse → StaticValidator → persist.

    Design invariants:
      - Never auto-publishes (publish_status is always DRAFT or PUBLISH_BLOCKED)
      - Never auto-starts a lab session
      - Adapter output is fully untrusted; only Pydantic + StaticValidator gate it
      - Generation failure never corrupts runtime session state
    """

    def __init__(
        self,
        port: LabDraftGenerationPort,
        validator: StaticValidator,
        repo: LabDraftRepository,
    ) -> None:
        self._port = port
        self._validator = validator
        self._repo = repo

    def generate_and_create(
        self, request: LabDraftGenerationRequest
    ) -> tuple[LabDraft, list[ValidatorResult], list[str]]:
        """
        Return (saved_draft, validator_results, sanitized_warnings).

        Raises DraftGenerationRejected if the adapter rejected the request.
        Raises DraftCandidateParseError if Pydantic parsing fails.
        Never raises on StaticValidator failures — they are returned as results.
        """
        result = self._port.generate_lab_draft_candidate(request)

        if result.rejected_reason:
            raise DraftGenerationRejected(result.rejected_reason)

        try:
            draft = LabDraft.model_validate(result.candidate)
        except Exception as exc:
            raise DraftCandidateParseError(_extract_pydantic_errors(exc)) from exc

        # Strip any adapter-injected publish state — adapter must not control publish
        draft = draft.model_copy(update={"publish_status": PublishStatus.DRAFT})

        # Validate (mutates draft.pollution_level, shared_namespace_candidate, etc.)
        validator_results = self._validator.validate(draft)

        # Compute publish_status from validator results
        draft = draft.model_copy(
            update={"publish_status": _compute_publish_status(validator_results)}
        )
        draft.validator_results = validator_results

        saved = self._repo.create(draft)
        sanitized = _sanitize_warnings(result.warnings)
        return saved, validator_results, sanitized


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_publish_status(results: list[ValidatorResult]) -> PublishStatus:
    failed = [r for r in results if r.status == ValidatorStatus.FAILED]
    if any(r.blocking_level == BlockingLevel.PUBLISH_BLOCKING for r in failed):
        return PublishStatus.PUBLISH_BLOCKED
    if any(r.blocking_level == BlockingLevel.REVIEW_REQUIRED for r in failed):
        return PublishStatus.REVIEW_REQUIRED
    return PublishStatus.DRAFT


def _sanitize_warnings(warnings: list[str]) -> list[str]:
    """Strip credential-like patterns from adapter-generated warnings."""
    result = []
    for w in warnings:
        cleaned = w
        for pat in _REDACT_PATTERNS:
            cleaned = pat.sub("[REDACTED]", cleaned)
        result.append(cleaned)
    return result


def _extract_pydantic_errors(exc: Exception) -> list[dict]:
    try:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            # Only extract loc/msg/type — exclude "input" field which may contain raw adapter output
            return [
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ]
    except Exception:
        pass
    # Generic message — do not include str(exc) which may contain raw LLM output
    return [{"msg": "candidate parse failed", "type": "parse_error"}]


def build_candidate_summary(draft: LabDraft) -> dict:
    """Safe high-level summary — never includes raw commands or explain text."""
    return {
        "title": draft.title,
        "description_preview": draft.description[:120],
        "step_count": len(draft.steps),
        "estimated_duration_minutes": draft.estimated_duration_minutes,
        "publish_status": draft.publish_status.value,
    }
