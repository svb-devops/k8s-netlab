"""
LLM Provider Boundary Hardening v0.1.

Defines the safe boundary between LabGen generation pipeline and LLM providers.
No real LLM is called. No API keys are read. No network requests are made.

Design invariants:
  - Default mode is FAKE_ONLY: routes to template-based deterministic generation
  - DRY_RUN mode: DryRunLLMProviderAdapter returns deterministic candidate_json
  - LIVE providers exist as config enum values only — CANNOT be activated
  - No raw_model_output, chain-of-thought, hidden prompt, or provider metadata in responses
  - All candidate_json output must pass Pydantic + StaticValidator before use
  - API keys are never read, stored, logged, or returned
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Provider vocabulary
# ---------------------------------------------------------------------------


class LLMProviderName(str, Enum):
    FAKE = "fake"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    CUSTOM = "custom"


class LLMProviderMode(str, Enum):
    DISABLED = "disabled"
    FAKE_ONLY = "fake_only"
    DRY_RUN = "dry_run"
    LIVE_DISABLED = "live_disabled"


# ---------------------------------------------------------------------------
# Config model — no API key fields
# ---------------------------------------------------------------------------

_MAX_TIMEOUT_MS = 60_000
_DEFAULT_TIMEOUT_MS = 30_000
_MAX_OUTPUT_TOKENS = 8192
_DEFAULT_OUTPUT_TOKENS = 4096

_LIVE_PROVIDER_NAMES: frozenset[LLMProviderName] = frozenset({
    LLMProviderName.OPENAI,
    LLMProviderName.ANTHROPIC,
    LLMProviderName.GEMINI,
})

_VALID_MODES: frozenset[str] = frozenset(m.value for m in LLMProviderMode)
_VALID_NAMES: frozenset[str] = frozenset(n.value for n in LLMProviderName)


class LLMProviderConfig(BaseModel):
    """
    Provider configuration.

    API keys are intentionally absent — this model must never carry secrets.
    Live providers exist as enum values only; they cannot be activated.
    # TODO: when a live provider is needed, add API key injection via a
    #       separate credential store, never via this config model.
    """

    provider_name: LLMProviderName = LLMProviderName.FAKE
    mode: LLMProviderMode = LLMProviderMode.FAKE_ONLY
    timeout_ms: int = Field(default=_DEFAULT_TIMEOUT_MS, ge=1000, le=_MAX_TIMEOUT_MS)
    max_output_tokens: int = Field(default=_DEFAULT_OUTPUT_TOKENS, ge=64, le=_MAX_OUTPUT_TOKENS)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

_MAX_PROMPT_LEN = 2000
_MAX_CONSTRAINTS_LEN = 500
_ALLOWED_PURPOSES = frozenset({"draft_generation", "draft_repair"})


class LLMProviderRequest(BaseModel):
    """
    Sanitized request to the provider boundary.
    sanitized_user_prompt must be pre-sanitized by the caller.
    """

    purpose: str
    selected_template_id: Optional[str] = None
    sanitized_user_prompt: str = Field(..., min_length=1, max_length=_MAX_PROMPT_LEN)
    constraints_summary: str = Field(default="", max_length=_MAX_CONSTRAINTS_LEN)
    max_output_tokens: Optional[int] = Field(default=None, ge=64, le=_MAX_OUTPUT_TOKENS)
    timeout_ms: Optional[int] = Field(default=None, ge=1000, le=_MAX_TIMEOUT_MS)
    correlation_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("purpose")
    @classmethod
    def _validate_purpose(cls, v: str) -> str:
        if v not in _ALLOWED_PURPOSES:
            raise ValueError(f"purpose must be one of {_ALLOWED_PURPOSES}, got {v!r}")
        return v


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class LLMProviderResponse(BaseModel):
    """
    Response from the provider boundary.

    Invariants:
      - raw_output_available is always False (raw output is never passed through)
      - candidate_json must be further validated by Pydantic + StaticValidator
      - No chain-of-thought, hidden prompt, provider metadata, or API keys
    """

    provider_name: LLMProviderName
    mode: LLMProviderMode
    candidate_json: Optional[dict] = None
    warnings: list[str] = Field(default_factory=list)
    usage_summary: Optional[str] = None   # safe text only, e.g. "dry-run (no provider calls)"
    raw_output_available: bool = False     # invariant: always False
    rejected_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------


class LLMProviderError(BaseModel):
    code: str
    message: str
    is_retriable: bool = False


# ---------------------------------------------------------------------------
# Safety policy
# ---------------------------------------------------------------------------


class LLMProviderSafetyPolicy(BaseModel):
    prohibited_response_fields: list[str] = Field(default_factory=list)
    sanitizer_applied: bool = True
    live_providers_enabled: bool = False


# ---------------------------------------------------------------------------
# Redaction patterns
# ---------------------------------------------------------------------------

_REDACT_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._=+/\-]{8,}"),
    re.compile(
        r"(?i)(token|password|secret|private_key|credential|kubeconfig|api_key)\s*[=:]\s*\S+"
    ),
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    re.compile(r"Traceback \(most recent call last\)[^\n]*(?:\n[^\n]+)*"),
    re.compile(
        r"(?i)(stack\s+trace|raw\s+exception|chain.of.thought|hidden\s+prompt|provider\s+metadata)"
        r"\s*[=:\-]?\s*\S.*"
    ),
    # OpenAI / Anthropic key patterns
    re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def _redact(text: str) -> str:
    cleaned = text
    for pat in _REDACT_PATTERNS:
        cleaned = pat.sub("[REDACTED]", cleaned)
    return cleaned


def _redact_warnings(warnings: list[str]) -> list[str]:
    return [_redact(w) for w in warnings]


# ---------------------------------------------------------------------------
# DryRun adapter — deterministic, no network, no API keys
# ---------------------------------------------------------------------------

_ALLOWED_INJECT_MODES: frozenset[str] = frozenset({
    "valid_candidate",
    "invalid_candidate",
    "malformed",
    "timeout",
    "provider_disabled",
    "safety_rejection",
    "sensitive_output",
})


class DryRunTimeoutSimulated(Exception):
    """Raised by DryRunLLMProviderAdapter when inject_mode='timeout'."""


class DryRunLLMProviderAdapter:
    """
    Dry-run adapter for testing the provider boundary without real network calls.

    Not a replacement for FakeDraftGenerationAdapter. Used to test the boundary
    layer itself. Never calls a real LLM. Never reads API keys.

    inject_mode controls output:
      "valid_candidate"    → valid candidate_json (passes Pydantic + StaticValidator)
      "invalid_candidate"  → parseable but StaticValidator fails (cleanup=None)
      "malformed"          → fails Pydantic (title is int, steps is str)
      "timeout"            → raises DryRunTimeoutSimulated
      "provider_disabled"  → returns rejected_reason="provider_disabled"
      "safety_rejection"   → returns rejected_reason="safety_policy_rejected"
      "sensitive_output"   → valid candidate + credential-like strings in warnings
                             (verifies that redaction is applied by the service)
    """

    def __init__(self, inject_mode: str = "valid_candidate") -> None:
        if inject_mode not in _ALLOWED_INJECT_MODES:
            raise ValueError(
                f"inject_mode {inject_mode!r} not in allowed set {_ALLOWED_INJECT_MODES}"
            )
        self._mode = inject_mode

    def call(
        self, request: LLMProviderRequest, config: LLMProviderConfig
    ) -> LLMProviderResponse:
        if self._mode == "timeout":
            raise DryRunTimeoutSimulated("dry-run: simulated provider timeout")

        if self._mode == "provider_disabled":
            return LLMProviderResponse(
                provider_name=config.provider_name,
                mode=config.mode,
                rejected_reason="provider_disabled",
                warnings=["dry-run: provider_disabled injected"],
            )

        if self._mode == "safety_rejection":
            return LLMProviderResponse(
                provider_name=config.provider_name,
                mode=config.mode,
                rejected_reason="safety_policy_rejected",
                warnings=["dry-run: safety policy rejected the request"],
            )

        if self._mode == "malformed":
            return LLMProviderResponse(
                provider_name=config.provider_name,
                mode=config.mode,
                candidate_json={"title": 12345, "steps": "not-a-list"},
                warnings=["dry-run: malformed candidate injected"],
            )

        if self._mode == "invalid_candidate":
            return LLMProviderResponse(
                provider_name=config.provider_name,
                mode=config.mode,
                candidate_json=_build_dry_run_candidate(request, strip_cleanup=True),
                warnings=["dry-run: cleanup removed — StaticValidator will fail"],
            )

        if self._mode == "sensitive_output":
            return LLMProviderResponse(
                provider_name=config.provider_name,
                mode=config.mode,
                candidate_json=_build_dry_run_candidate(request),
                warnings=[
                    "note: api_key=sk-abcdefghijklmnopqrstuvwxyz123456 in context",
                    "internal: token=eyJhbGciOiJSUzI1NiJ9.fake.payload seen in output",
                ],
            )

        # "valid_candidate" (default)
        return LLMProviderResponse(
            provider_name=config.provider_name,
            mode=config.mode,
            candidate_json=_build_dry_run_candidate(request),
            warnings=["dry-run: deterministic candidate — not a real LLM output"],
            usage_summary="dry-run (no provider calls)",
        )


def _build_dry_run_candidate(
    request: LLMProviderRequest, strip_cleanup: bool = False
) -> dict:
    """Build a minimal LabDraft-compatible candidate dict for dry-run tests."""
    from backend.labgen.generation_templates import GenerationTemplateRegistry

    registry = GenerationTemplateRegistry()
    selection = registry.select(request.sanitized_user_prompt, None, None)
    template = registry.get_by_id(selection.selected_template_id)
    candidate = template.build_candidate(request.sanitized_user_prompt, None, None)
    if strip_cleanup:
        candidate["cleanup"] = None
    return candidate


# ---------------------------------------------------------------------------
# Provider boundary service
# ---------------------------------------------------------------------------


class LLMProviderBoundaryService:
    """
    Entry point for all LLM provider interactions in LabGen.

    Default mode (FAKE_ONLY): deterministic template-based candidates, no network.
    DRY_RUN mode: DryRunLLMProviderAdapter, no network.
    Live providers (OPENAI/ANTHROPIC/GEMINI): always return a disabled error.

    Redaction is applied to all warning strings before returning.
    API keys are never read, stored, or returned by this service.
    """

    def __init__(
        self,
        config: LLMProviderConfig,
        dry_run_adapter: Optional[DryRunLLMProviderAdapter] = None,
    ) -> None:
        self._config = config
        self._dry_run_adapter = dry_run_adapter or DryRunLLMProviderAdapter()

    @classmethod
    def create_from_env(cls) -> "LLMProviderBoundaryService":
        """
        Build from environment variables via backend.config.
        Falls back to FAKE_ONLY + FAKE on invalid/unknown values.
        """
        from backend import config as cfg

        raw_mode = cfg.LABGEN_LLM_PROVIDER_MODE
        raw_name = cfg.LABGEN_LLM_PROVIDER_NAME

        mode = (
            LLMProviderMode(raw_mode)
            if raw_mode in _VALID_MODES
            else LLMProviderMode.FAKE_ONLY
        )
        name = (
            LLMProviderName(raw_name)
            if raw_name in _VALID_NAMES
            else LLMProviderName.FAKE
        )

        provider_config = LLMProviderConfig(
            provider_name=name,
            mode=mode,
            timeout_ms=min(cfg.LABGEN_LLM_TIMEOUT_MS, _MAX_TIMEOUT_MS),
            max_output_tokens=min(cfg.LABGEN_LLM_MAX_OUTPUT_TOKENS, _MAX_OUTPUT_TOKENS),
        )
        return cls(config=provider_config)

    @property
    def config(self) -> LLMProviderConfig:
        return self._config

    @property
    def dry_run_available(self) -> bool:
        return self._config.mode == LLMProviderMode.DRY_RUN

    @property
    def safety_policy(self) -> LLMProviderSafetyPolicy:
        return LLMProviderSafetyPolicy(
            prohibited_response_fields=[
                "raw_model_output",
                "chain_of_thought",
                "hidden_prompt",
                "provider_metadata",
                "api_key",
                "provider_trace_id",
            ],
            sanitizer_applied=True,
            live_providers_enabled=False,
        )

    def call(self, request: LLMProviderRequest) -> LLMProviderResponse:
        """
        Dispatch the request per current mode.

        Never raises for provider failures — those are returned as rejected_reason.
        DryRunTimeoutSimulated may propagate; callers must catch and convert it.
        """
        mode = self._config.mode
        name = self._config.provider_name

        if mode == LLMProviderMode.DISABLED:
            return LLMProviderResponse(
                provider_name=name,
                mode=mode,
                rejected_reason="provider_disabled",
            )

        if mode == LLMProviderMode.LIVE_DISABLED or name in _LIVE_PROVIDER_NAMES:
            return LLMProviderResponse(
                provider_name=name,
                mode=LLMProviderMode.LIVE_DISABLED,
                rejected_reason="live_provider_disabled",
                warnings=["Live LLM providers are disabled in this environment."],
            )

        if mode == LLMProviderMode.FAKE_ONLY:
            return self._fake_response(request)

        if mode == LLMProviderMode.DRY_RUN:
            raw = self._dry_run_adapter.call(request, self._config)
            return raw.model_copy(
                update={"warnings": _redact_warnings(raw.warnings)}
            )

        # Unknown mode — safe fallback, never 500
        return LLMProviderResponse(
            provider_name=name,
            mode=mode,
            rejected_reason="unknown_mode",
        )

    # ------------------------------------------------------------------

    def _fake_response(self, request: LLMProviderRequest) -> LLMProviderResponse:
        from backend.labgen.generation_templates import GenerationTemplateRegistry

        registry = GenerationTemplateRegistry()
        selection = registry.select(request.sanitized_user_prompt, None, None)
        template = registry.get_by_id(selection.selected_template_id)
        candidate = template.build_candidate(request.sanitized_user_prompt, None, None)
        return LLMProviderResponse(
            provider_name=self._config.provider_name,
            mode=self._config.mode,
            candidate_json=candidate,
            warnings=["fake provider: deterministic template-based output"],
            usage_summary="fake (no provider calls)",
        )
