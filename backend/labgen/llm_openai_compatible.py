"""
OpenAI-Compatible LLM Provider Adapter v0.1.

Implements LabDraftGenerationPort using an OpenAI-compatible chat completions API.
Disabled by default — only active when LABGEN_LLM_PROVIDER_MODE=live_enabled
and all required config is valid.

Design invariants:
  - Never calls the real network in unit tests (injectable HTTP client)
  - Never stores or returns the API key
  - Never returns raw_model_output, hidden_prompt, chain_of_thought to callers
  - All provider errors are structured and sanitized before propagation
  - Candidate publish_status is always forced to DRAFT (never PUBLISHED)
  - Response parser rejects natural language; optional fenced-code-block extraction is tested
  - Repair live adapter is OUT_OF_SCOPE for this version (see provider status)
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

_ALLOWED_DEV_SCHEMES = frozenset({"http", "https"})
_BLOCKED_SCHEMES = frozenset({"file", "ftp", "gopher", "data", "javascript"})

_PROHIBITED_RESPONSE_FIELDS = frozenset({
    "raw_model_output",
    "hidden_prompt",
    "chain_of_thought",
    "provider_metadata",
    "provider_trace_id",
    "api_key",
    "authorization",
})


class OpenAICompatibleConfigIssue(BaseModel):
    code: str
    message: str


class OpenAICompatibleProviderConfig(BaseModel):
    """
    Sanitized config for the OpenAI-compatible provider.
    API key is intentionally absent — it is injected at call time only.
    """

    base_url: str
    model: str
    timeout_ms: int = 30_000
    max_output_tokens: int = 4096

    @property
    def base_url_origin(self) -> str:
        """Return scheme+host only — safe for diagnostics."""
        try:
            p = urlparse(self.base_url)
            return f"{p.scheme}://{p.netloc}"
        except Exception:
            return "[invalid]"


def validate_openai_compatible_config(
    base_url: str,
    model: str,
    api_key: str,
    *,
    allow_http: bool = False,
) -> list[OpenAICompatibleConfigIssue]:
    """
    Validate config without making network calls.
    Returns a list of issues (empty = valid).
    API key is checked for presence only — value is not logged or returned.
    """
    issues: list[OpenAICompatibleConfigIssue] = []

    # base_url validation
    if not base_url:
        issues.append(OpenAICompatibleConfigIssue(
            code="missing_base_url",
            message="LABGEN_LLM_OPENAI_BASE_URL is not set",
        ))
    else:
        try:
            parsed = urlparse(base_url)
            scheme = (parsed.scheme or "").lower()
            if scheme in _BLOCKED_SCHEMES:
                issues.append(OpenAICompatibleConfigIssue(
                    code="invalid_base_url_scheme",
                    message=f"base_url scheme '{scheme}' is not allowed",
                ))
            elif scheme not in _ALLOWED_DEV_SCHEMES:
                issues.append(OpenAICompatibleConfigIssue(
                    code="invalid_base_url_scheme",
                    message=f"base_url scheme '{scheme}' is not allowed; use https",
                ))
            elif scheme == "http" and not allow_http:
                issues.append(OpenAICompatibleConfigIssue(
                    code="insecure_base_url",
                    message="base_url uses http — https is required in production",
                ))
            if not parsed.netloc:
                issues.append(OpenAICompatibleConfigIssue(
                    code="invalid_base_url_host",
                    message="base_url has an empty host",
                ))
        except Exception:
            issues.append(OpenAICompatibleConfigIssue(
                code="invalid_base_url",
                message="base_url could not be parsed",
            ))

    # model validation
    if not model:
        issues.append(OpenAICompatibleConfigIssue(
            code="missing_model",
            message="LABGEN_LLM_OPENAI_MODEL is not set",
        ))

    # API key presence check — value not logged
    if not api_key:
        issues.append(OpenAICompatibleConfigIssue(
            code="missing_api_key",
            message="LABGEN_LLM_OPENAI_API_KEY is not set",
        ))

    return issues


# ---------------------------------------------------------------------------
# HTTP client protocol — injectable for testing
# ---------------------------------------------------------------------------


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    def json(self) -> Any: ...
    def text(self) -> str: ...


class _HttpClientProtocol(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict,
        json: dict,
        timeout: float,
    ) -> _HttpResponse: ...


class _HttpxClient:
    """Real implementation using httpx (already a project dependency)."""

    def post(
        self,
        url: str,
        *,
        headers: dict,
        json: dict,
        timeout: float,
    ) -> Any:
        import httpx  # lazy import — not imported at module level to keep test isolation clean

        response = httpx.post(url, headers=headers, json=json, timeout=timeout)
        return response


# ---------------------------------------------------------------------------
# Provider error types
# ---------------------------------------------------------------------------


class OpenAICompatibleProviderError(Exception):
    """Structured provider error — never contains raw HTTP body or API key."""

    def __init__(self, code: str, message: str, is_retriable: bool = False) -> None:
        self.code = code
        self.message = message
        self.is_retriable = is_retriable
        super().__init__(message)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

_FENCE_PATTERN = re.compile(
    r"```(?:json)?\s*\n?([\s\S]*?)\n?```",
    re.IGNORECASE,
)


def _extract_json_from_fenced_block(text: str) -> Optional[str]:
    """Extract first fenced JSON block content, if any."""
    match = _FENCE_PATTERN.search(text)
    return match.group(1).strip() if match else None


def _strip_prohibited_fields(candidate: dict) -> tuple[dict, list[str]]:
    """Remove prohibited fields from candidate. Returns (cleaned_dict, stripped_keys)."""
    stripped: list[str] = []
    cleaned = {}
    for k, v in candidate.items():
        if k in _PROHIBITED_RESPONSE_FIELDS:
            stripped.append(k)
        else:
            cleaned[k] = v
    return cleaned, stripped


def parse_provider_response(raw_text: str) -> dict:
    """
    Parse the raw text returned by the provider into a candidate dict.

    Accepted formats:
      1. Plain JSON object
      2. JSON object wrapped in a single markdown fenced code block

    Rejected:
      - Natural language text (even if it contains JSON somewhere)
      - Non-object JSON (array, string, etc.)
      - Malformed JSON
      - JSON containing prohibited fields (stripped with warning — caller gets warnings)

    Raises OpenAICompatibleProviderError on any parse failure.

    Returns cleaned candidate dict (prohibited fields removed, publish_status forced to draft).
    """
    text = raw_text.strip()

    # Reject if response looks like natural language (starts with a word, not '{' or '```')
    if text and text[0] not in ('{', '`', '['):
        raise OpenAICompatibleProviderError(
            code="natural_language_response",
            message="provider returned natural language instead of JSON",
        )

    # Try fenced block extraction first
    fenced_content = _extract_json_from_fenced_block(text)
    json_text = fenced_content if fenced_content is not None else text

    # Parse JSON
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise OpenAICompatibleProviderError(
            code="malformed_json",
            message=f"provider returned malformed JSON: {_safe_json_error(exc)}",
        ) from exc

    if not isinstance(parsed, dict):
        raise OpenAICompatibleProviderError(
            code="non_object_response",
            message=f"provider returned JSON {type(parsed).__name__}, expected object",
        )

    # Strip prohibited fields (never raise — just strip)
    cleaned, _stripped = _strip_prohibited_fields(parsed)

    # Force publish_status to draft — provider must not control publish
    if "publish_status" in cleaned:
        cleaned["publish_status"] = "draft"

    return cleaned


def _safe_json_error(exc: json.JSONDecodeError) -> str:
    """Extract safe error message from JSONDecodeError, no raw content."""
    return f"line {exc.lineno} col {exc.colno}: {exc.msg}"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class OpenAICompatibleLLMProviderAdapter:
    """
    Calls an OpenAI-compatible chat completions endpoint to generate lab draft candidates.

    Disabled by default. Only instantiated when:
      - LABGEN_LLM_PROVIDER_MODE=live_enabled
      - config has no validation issues

    API key is injected at construction time and never returned.
    HTTP client is injected for test isolation — tests use a fake client.

    Repair live adapter: OUT_OF_SCOPE for v0.1.
    The provider_status endpoint will report repair_supported=False.
    """

    def __init__(
        self,
        config: OpenAICompatibleProviderConfig,
        api_key: str,
        http_client: Optional[_HttpClientProtocol] = None,
    ) -> None:
        self._config = config
        self._api_key = api_key  # never returned, never logged
        self._http_client: _HttpClientProtocol = http_client or _HttpxClient()

    @property
    def config(self) -> OpenAICompatibleProviderConfig:
        return self._config

    def call_generate(
        self,
        system_message: str,
        user_message: str,
    ) -> dict:
        """
        Call the provider and return a parsed, sanitized candidate dict.

        Raises OpenAICompatibleProviderError on any failure.
        Never returns: raw HTTP body, API key, Authorization header,
        raw_model_output, chain_of_thought, hidden_prompt.
        """
        url = self._chat_completions_url()
        payload = self._build_payload(system_message, user_message)
        headers = self._build_headers()

        timeout_s = self._config.timeout_ms / 1000.0

        try:
            response = self._http_client.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_s,
            )
        except Exception as exc:
            exc_type = type(exc).__name__
            # Check for timeout by type name — avoids importing httpx at module level
            if "Timeout" in exc_type or "timeout" in str(exc).lower():
                raise OpenAICompatibleProviderError(
                    code="provider_timeout",
                    message="provider request timed out",
                    is_retriable=True,
                ) from exc
            raise OpenAICompatibleProviderError(
                code="provider_network_error",
                message="network error reaching provider",
                is_retriable=True,
            ) from exc

        status = response.status_code

        if status == 401:
            raise OpenAICompatibleProviderError(
                code="provider_auth_error",
                message="provider rejected credentials (401)",
                is_retriable=False,
            )
        if status == 429:
            raise OpenAICompatibleProviderError(
                code="provider_rate_limited",
                message="provider rate limit exceeded (429)",
                is_retriable=True,
            )
        if status >= 500:
            raise OpenAICompatibleProviderError(
                code="provider_server_error",
                message=f"provider returned server error ({status})",
                is_retriable=True,
            )
        if status != 200:
            raise OpenAICompatibleProviderError(
                code="provider_unexpected_status",
                message=f"provider returned unexpected status {status}",
                is_retriable=False,
            )

        # Extract content string from OpenAI-format response
        raw_text = self._extract_content(response)

        # Parse and sanitize
        return parse_provider_response(raw_text)

    def _chat_completions_url(self) -> str:
        base = self._config.base_url.rstrip("/")
        return f"{base}/chat/completions"

    def _build_payload(self, system_message: str, user_message: str) -> dict:
        return {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": self._config.max_output_tokens,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _extract_content(self, response: Any) -> str:
        """
        Extract the assistant message content from an OpenAI-format response.
        Raises OpenAICompatibleProviderError if the structure is unexpected.
        Never returns the full response object.
        """
        try:
            body = response.json()
        except Exception:
            raise OpenAICompatibleProviderError(
                code="provider_response_not_json",
                message="provider returned a non-JSON response body",
            )

        if not isinstance(body, dict):
            raise OpenAICompatibleProviderError(
                code="provider_response_not_object",
                message="provider response body was not a JSON object",
            )

        # Safety policy: check for obvious safety rejection signals
        finish_reason = (
            body.get("choices", [{}])[0].get("finish_reason", "")
            if body.get("choices")
            else ""
        )
        if finish_reason in ("content_filter", "safety"):
            raise OpenAICompatibleProviderError(
                code="provider_safety_rejected",
                message="provider safety policy rejected the request",
                is_retriable=False,
            )

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise OpenAICompatibleProviderError(
                code="provider_unexpected_response_structure",
                message="provider response did not contain expected choices[0].message.content",
            )

        if not isinstance(content, str):
            raise OpenAICompatibleProviderError(
                code="provider_content_not_string",
                message="provider message content was not a string",
            )

        return content


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_openai_compatible_adapter_from_env() -> Optional[OpenAICompatibleLLMProviderAdapter]:
    """
    Build adapter from environment variables.
    Returns None if config is invalid (caller should surface config issues separately).
    API key is read from env at call time and never stored in config objects.
    """
    from backend import config as cfg

    issues = validate_openai_compatible_config(
        base_url=cfg.LABGEN_LLM_OPENAI_BASE_URL,
        model=cfg.LABGEN_LLM_OPENAI_MODEL,
        api_key=cfg.LABGEN_LLM_OPENAI_API_KEY,
    )
    if issues:
        return None

    provider_config = OpenAICompatibleProviderConfig(
        base_url=cfg.LABGEN_LLM_OPENAI_BASE_URL,
        model=cfg.LABGEN_LLM_OPENAI_MODEL,
        timeout_ms=cfg.LABGEN_LLM_TIMEOUT_MS,
        max_output_tokens=cfg.LABGEN_LLM_MAX_OUTPUT_TOKENS,
    )
    return OpenAICompatibleLLMProviderAdapter(
        config=provider_config,
        api_key=cfg.LABGEN_LLM_OPENAI_API_KEY,
    )
