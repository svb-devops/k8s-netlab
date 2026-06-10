"""
LLM Draft Generation Contract Adapter v0.1 + Review & Repair Loop.

Port interface + request/result models + deterministic fake adapter +
LabDraftGenerationService.  No real LLM, no provider SDK, no API keys.

All adapter output is treated as untrusted input that must pass Pydantic
parsing and StaticValidator before any LabDraft is persisted.
"""

from __future__ import annotations

import abc
import dataclasses
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from backend.labgen.draft_repair import (
    DraftRepairRequest,
    DraftRepairResult,
    DraftReviewIssue,
    DraftReviewResult,
    IssueSource,
    IssueSeverity,
    LabDraftRepairPort,
)
from backend.labgen.generation_templates import (
    GenerationTemplateId,
    GenerationTemplateRegistry,
)
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

# Redact credential-like patterns from adapter output before returning to caller.
# Applied to both generation warnings and repair warnings/summaries.
_REDACT_PATTERNS = [
    # Bearer before kv so "token: Bearer <val>" doesn't leave <val> exposed after kv match
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._=+/\-]{8,}"),
    # key=value or key: value credential patterns
    re.compile(
        r"(?i)(token|password|secret|private_key|credential|kubeconfig)\s*[=:]\s*\S+"
    ),
    # JWT tokens (header starts with eyJ — Base64url for {"...)
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    # Long Base64 blocks (certs, kubeconfig data, raw tokens without key=value prefix)
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    # Python tracebacks — matches both multi-line (with newlines) and single-line variants
    re.compile(r"Traceback \(most recent call last\)[^\n]*(?:\n[^\n]+)*"),
    # Stack trace / raw exception label lines
    re.compile(r"(?i)(stack\s+trace|raw\s+exception)\s*[=:\-]?\s*\S.*"),
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
    enable_repair: bool = False
    max_repair_attempts: int = Field(default=1, ge=1, le=2)

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
    template_id: Optional[str] = None  # set when template-based generation was used


# ---------------------------------------------------------------------------
# API response model — must never contain raw adapter output or credentials
# ---------------------------------------------------------------------------


class DraftRepairResultView(BaseModel):
    """
    API-safe projection of DraftRepairResult.
    repaired_candidate is intentionally absent — it is raw adapter output and
    must never be serialised into an HTTP response.
    """

    repaired_validation_status: str = "not_attempted"
    repair_applied: bool = False
    repair_warnings: list[str] = Field(default_factory=list)
    rejected_reason: Optional[str] = None


class GenerateLabDraftResponse(BaseModel):
    draft_id: Optional[str] = None
    validation_status: str  # passed | validation_failed | parse_error | rejected
    validation_errors: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    selected_template_id: Optional[str] = None
    candidate_summary: Optional[dict] = None
    # Review & repair fields (null when repair was not attempted)
    review_result: Optional[DraftReviewResult] = None
    repair_result: Optional[DraftRepairResultView] = None
    repair_attempted: bool = False
    repair_applied: bool = False


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
      "valid"     → template-based Contract v0.1 candidate, passes StaticValidator
      "invalid"   → Pydantic-parseable but StaticValidator fails (cleanup=None)
      "malformed" → fails Pydantic parsing (steps is wrong type)
      "sensitive" → valid candidate + credential-like strings in warnings
                    (used to verify the response sanitizer catches them)
      "rejected"  → adapter rejects before producing a candidate
    """

    def __init__(self, inject_mode: str = "valid") -> None:
        self._mode = inject_mode
        self._registry = GenerationTemplateRegistry()

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

        # For valid/invalid/sensitive: use template selection
        selection = self._registry.select(
            request.user_prompt, request.target_audience, request.difficulty
        )
        template = self._registry.get_by_id(selection.selected_template_id)
        candidate = template.build_candidate(
            request.user_prompt, request.target_audience, request.difficulty
        )

        if self._mode == "invalid":
            candidate["cleanup"] = None  # cleanup.declared check will fail
            return LabDraftGenerationResult(
                candidate=candidate,
                template_id=selection.selected_template_id.value,
                warnings=list(selection.warnings),
            )

        if self._mode == "sensitive":
            warnings = list(selection.warnings) + [
                "note: generation used internal token=eyJhbGciOiJSUzI1NiJ9.fake.payload",
                "provider raw: password=hunter2 in context window",
            ]
            return LabDraftGenerationResult(
                candidate=candidate,
                template_id=selection.selected_template_id.value,
                warnings=warnings,
            )

        # "valid" (default)
        warnings = list(selection.warnings) or [
            "fake generator: content is placeholder, admin review required"
        ]
        return LabDraftGenerationResult(
            candidate=candidate,
            template_id=selection.selected_template_id.value,
            warnings=warnings,
        )

    @staticmethod
    def _build_valid_candidate(request: LabDraftGenerationRequest) -> dict:
        """Legacy static helper for test isolation — single-step minimal candidate."""
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
# Repair loop outcome (internal to service, not exposed in HTTP response)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RepairLoopOutcome:
    draft: Optional[LabDraft]
    validator_results: list[ValidatorResult]
    warnings: list[str]
    template_id: Optional[str]
    review_result: Optional[DraftReviewResult]
    repair_result: Optional[DraftRepairResult]
    repair_attempted: bool
    repair_applied: bool


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
      - Repair adapter output is also fully untrusted; always re-validated

    provider_boundary: optional LLMProviderBoundaryService.  When injected and
    dry_run_available is True, calls the boundary service to obtain a candidate_json
    instead of self._port.  Default behaviour (port only) is unchanged.
    """

    def __init__(
        self,
        port: LabDraftGenerationPort,
        validator: StaticValidator,
        repo: LabDraftRepository,
        provider_boundary=None,  # Optional[LLMProviderBoundaryService]
    ) -> None:
        self._port = port
        self._validator = validator
        self._repo = repo
        self._provider_boundary = provider_boundary

    def generate_and_create(
        self, request: LabDraftGenerationRequest
    ) -> tuple[LabDraft, list[ValidatorResult], list[str], Optional[str]]:
        """
        Return (saved_draft, validator_results, sanitized_warnings, template_id).

        Raises DraftGenerationRejected if the adapter rejected the request.
        Raises DraftCandidateParseError if Pydantic parsing fails.
        Never raises on StaticValidator failures — they are returned as results.
        """
        result = self._generate_result(request)

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
        return saved, validator_results, sanitized, result.template_id

    def review_candidate(
        self,
        candidate: dict,
        template_id: Optional[str] = None,
    ) -> tuple[Optional[LabDraft], DraftReviewResult]:
        """
        Parse and validate a candidate dict.  Returns (draft_or_None, review_result).
        Does NOT persist anything.  Safe to call without side effects.
        """
        try:
            draft = LabDraft.model_validate(candidate)
        except Exception as exc:
            errors = _extract_pydantic_errors(exc)
            issues = [
                DraftReviewIssue(
                    code=e.get("type", "parse_error"),
                    message=sanitize_text(e.get("msg", "parse error")),
                    path=(
                        ".".join(str(p) for p in e.get("loc", []))
                        if e.get("loc") else None
                    ),
                    severity=IssueSeverity.ERROR,
                    source=IssueSource.PYDANTIC,
                )
                for e in errors
            ]
            return None, DraftReviewResult(
                is_valid=False,
                issues=issues,
                sanitized_summary=f"parse failed: {len(issues)} error(s)",
                selected_template_id=template_id,
            )

        draft = draft.model_copy(update={"publish_status": PublishStatus.DRAFT})
        validator_results = self._validator.validate(draft)
        review = self._build_review_result(validator_results, template_id)
        return draft, review

    def generate_with_repair(
        self,
        request: LabDraftGenerationRequest,
        enable_repair: bool = False,
        max_repair_attempts: int = 1,
        repair_port: Optional[LabDraftRepairPort] = None,
    ) -> RepairLoopOutcome:
        """
        Generate → validate → optionally repair → validate again → persist.

        Raises DraftGenerationRejected if the adapter rejects the request.
        Raises DraftCandidateParseError if the INITIAL Pydantic parse fails.
          (Repair is only attempted for StaticValidator failures, not parse failures.)
        Never raises for repair-path failures — those are returned in the outcome.
        """
        # --- 1. Generate ---
        gen_result = self._generate_result(request)
        if gen_result.rejected_reason:
            raise DraftGenerationRejected(gen_result.rejected_reason)

        warnings = _sanitize_warnings(gen_result.warnings)
        template_id = gen_result.template_id

        # --- 2. Pydantic parse (always raises on failure, repair not attempted) ---
        try:
            draft = LabDraft.model_validate(gen_result.candidate)
        except Exception as exc:
            raise DraftCandidateParseError(_extract_pydantic_errors(exc)) from exc

        draft = draft.model_copy(update={"publish_status": PublishStatus.DRAFT})

        # --- 3. Validate initial candidate ---
        validator_results = self._validator.validate(draft)
        initial_valid = not any(
            r.status == ValidatorStatus.FAILED for r in validator_results
        )
        review_result = self._build_review_result(validator_results, template_id)

        if initial_valid or not enable_repair or repair_port is None:
            # No repair: persist and return (consistent with generate_and_create)
            draft = draft.model_copy(
                update={"publish_status": _compute_publish_status(validator_results)}
            )
            draft.validator_results = validator_results
            saved = self._repo.create(draft)
            return RepairLoopOutcome(
                draft=saved,
                validator_results=validator_results,
                warnings=warnings,
                template_id=template_id,
                review_result=review_result,
                repair_result=None,
                repair_attempted=False,
                repair_applied=False,
            )

        # --- 4. Repair attempt ---
        repair_req = DraftRepairRequest(
            original_candidate=gen_result.candidate,
            review_result=review_result,
            selected_template_id=template_id,
            requester_user_id=request.requester_user_id,
            max_repair_attempts=min(max_repair_attempts, 2),
        )
        try:
            raw_repair = repair_port.repair_draft_candidate(repair_req)
        except Exception:
            # Adapter raised — fall back to initial draft, never 500
            fallback_result = DraftRepairResult(
                repaired_validation_status="repair_failed",
                rejected_reason="adapter_error",
            )
            draft = draft.model_copy(
                update={"publish_status": _compute_publish_status(validator_results)}
            )
            draft.validator_results = validator_results
            saved = self._repo.create(draft)
            return RepairLoopOutcome(
                draft=saved,
                validator_results=validator_results,
                warnings=warnings,
                template_id=template_id,
                review_result=review_result,
                repair_result=fallback_result,
                repair_attempted=True,
                repair_applied=False,
            )

        # Sanitize repair warnings before they can reach the API response
        repair_result = raw_repair.model_copy(
            update={"repair_warnings": _sanitize_warnings(raw_repair.repair_warnings)}
        )

        # --- 5. Adapter refused or returned no candidate ---
        if repair_result.rejected_reason or repair_result.repaired_candidate is None:
            repair_result = repair_result.model_copy(
                update={
                    "repaired_validation_status": "repair_failed",
                    "repair_applied": False,
                }
            )
            # Consistent with current behaviour: persist the initial (invalid) draft
            draft = draft.model_copy(
                update={"publish_status": _compute_publish_status(validator_results)}
            )
            draft.validator_results = validator_results
            saved = self._repo.create(draft)
            return RepairLoopOutcome(
                draft=saved,
                validator_results=validator_results,
                warnings=warnings,
                template_id=template_id,
                review_result=review_result,
                repair_result=repair_result,
                repair_attempted=True,
                repair_applied=False,
            )

        # --- 6. Pydantic parse on repaired candidate ---
        try:
            repaired_draft = LabDraft.model_validate(
                repair_result.repaired_candidate
            )
        except Exception:
            # Repair produced unparseable output — fall back to initial draft
            repair_result = repair_result.model_copy(
                update={
                    "repaired_validation_status": "malformed",
                    "repair_applied": False,
                }
            )
            draft = draft.model_copy(
                update={"publish_status": _compute_publish_status(validator_results)}
            )
            draft.validator_results = validator_results
            saved = self._repo.create(draft)
            return RepairLoopOutcome(
                draft=saved,
                validator_results=validator_results,
                warnings=warnings,
                template_id=template_id,
                review_result=review_result,
                repair_result=repair_result,
                repair_attempted=True,
                repair_applied=False,
            )

        # --- 7. Validate repaired candidate ---
        repaired_draft = repaired_draft.model_copy(
            update={"publish_status": PublishStatus.DRAFT}
        )
        repaired_results = self._validator.validate(repaired_draft)
        repaired_has_failures = any(
            r.status == ValidatorStatus.FAILED for r in repaired_results
        )
        repaired_status = "still_invalid" if repaired_has_failures else "passed"

        repair_result = repair_result.model_copy(
            update={
                "repaired_validation_status": repaired_status,
                "repair_applied": True,
            }
        )

        # --- 8. Persist repaired draft (consistent: always persist when Pydantic passes) ---
        repaired_draft = repaired_draft.model_copy(
            update={"publish_status": _compute_publish_status(repaired_results)}
        )
        repaired_draft.validator_results = repaired_results
        saved = self._repo.create(repaired_draft)

        return RepairLoopOutcome(
            draft=saved,
            validator_results=repaired_results,
            warnings=warnings,
            template_id=template_id,
            review_result=review_result,
            repair_result=repair_result,
            repair_attempted=True,
            repair_applied=True,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_result(
        self, request: LabDraftGenerationRequest
    ) -> "LabDraftGenerationResult":
        """
        Dispatch generation to either provider_boundary (when dry_run_available)
        or the configured port (default: FakeDraftGenerationAdapter).

        When provider_boundary is active:
          - DryRunTimeoutSimulated is caught and converted to DraftGenerationRejected
          - LLMProviderResponse.candidate_json is wrapped in LabDraftGenerationResult
          - Redaction of warnings is already applied by the boundary service
        """
        if self._provider_boundary is not None and self._provider_boundary.dry_run_available:
            from backend.labgen.llm_provider_boundary import (
                DryRunTimeoutSimulated,
                LLMProviderRequest,
            )

            pr = LLMProviderRequest(
                purpose="draft_generation",
                sanitized_user_prompt=request.user_prompt,
                constraints_summary=(
                    ", ".join(f"{k}={v}" for k, v in request.constraints.items())
                    if request.constraints else ""
                ),
            )
            try:
                resp = self._provider_boundary.call(pr)
            except DryRunTimeoutSimulated as exc:
                raise DraftGenerationRejected(f"provider_timeout: {exc}") from exc
            except Exception as exc:
                raise DraftGenerationRejected("provider_error") from exc

            if resp.rejected_reason:
                raise DraftGenerationRejected(resp.rejected_reason)
            if resp.candidate_json is None:
                raise DraftGenerationRejected("provider_no_candidate")

            return LabDraftGenerationResult(
                candidate=resp.candidate_json,
                warnings=list(resp.warnings),
                template_id=resp.usage_summary,
            )

        return self._port.generate_lab_draft_candidate(request)

    def _build_review_result(
        self,
        validator_results: list[ValidatorResult],
        template_id: Optional[str] = None,
    ) -> DraftReviewResult:
        failed = [r for r in validator_results if r.status == ValidatorStatus.FAILED]
        issues = [
            DraftReviewIssue(
                code=r.check_id,
                message=sanitize_text(r.message),
                path=r.field_path if r.field_path else None,
                severity=(
                    IssueSeverity.ERROR
                    if r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
                    else IssueSeverity.WARNING
                ),
                source=IssueSource.STATIC_VALIDATOR,
            )
            for r in failed
        ]
        is_valid = not bool(failed)
        summary = "candidate valid" if is_valid else f"validation failed: {len(failed)} check(s)"
        return DraftReviewResult(
            is_valid=is_valid,
            issues=issues,
            sanitized_summary=summary,
            selected_template_id=template_id,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sanitize_text(text: str) -> str:
    """Apply _REDACT_PATTERNS to a single string. Safe for use in API responses."""
    cleaned = text
    for pat in _REDACT_PATTERNS:
        cleaned = pat.sub("[REDACTED]", cleaned)
    return cleaned


def _compute_publish_status(results: list[ValidatorResult]) -> PublishStatus:
    failed = [r for r in results if r.status == ValidatorStatus.FAILED]
    if any(r.blocking_level == BlockingLevel.PUBLISH_BLOCKING for r in failed):
        return PublishStatus.PUBLISH_BLOCKED
    if any(r.blocking_level == BlockingLevel.REVIEW_REQUIRED for r in failed):
        return PublishStatus.REVIEW_REQUIRED
    return PublishStatus.DRAFT


def _sanitize_warnings(warnings: list[str]) -> list[str]:
    """Strip credential-like patterns from adapter-generated warnings."""
    return [sanitize_text(w) for w in warnings]


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


def build_candidate_summary(
    draft: LabDraft, template_id: Optional[str] = None
) -> dict:
    """Safe high-level summary — never includes raw commands or explain text."""
    summary: dict = {
        "title": draft.title,
        "description_preview": draft.description[:120],
        "step_count": len(draft.steps),
        "objective_count": len(draft.steps),
        "estimated_duration_minutes": draft.estimated_duration_minutes,
        "publish_status": draft.publish_status.value,
    }
    if template_id is not None:
        summary["template_id"] = template_id
    return summary
