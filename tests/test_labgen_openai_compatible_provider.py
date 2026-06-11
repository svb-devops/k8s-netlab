"""
OpenAI-Compatible LLM Provider Adapter v0.1 — tests.

Coverage areas (per contract):
  A. Config
  C. Provider adapter
  D. Generation integration (fake HTTP client)
  E. Diagnostics API
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.labgen.llm_openai_compatible import (
    OpenAICompatibleLLMProviderAdapter,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleProviderError,
    parse_provider_response,
    validate_openai_compatible_config,
)

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CANDIDATE = {
    "schema_version": "1.0",
    "source_article_id": "test-article",
    "title": "Test Lab",
    "description": "A test lab description for unit tests.",
    "estimated_duration_minutes": 20,
    "runtime_requirements": {"namespace_strategy": "dedicated"},
    "steps": [
        {
            "step_id": "step-1",
            "order": 1,
            "why": "Learn networking basics",
            "do": "kubectl apply -f pod.yaml",
            "observe": "Pod reaches Running state",
            "explain": {
                "concept": "Pod scheduling",
                "observation": "Kubernetes scheduled the pod on an available node",
            },
        }
    ],
    "cleanup": {"namespace_cleanup": {"mode": "delete"}},
}

_VALID_CONFIG = OpenAICompatibleProviderConfig(
    base_url="https://api.example.com/v1",
    model="test-model",
)

_VALID_API_KEY = "sk-test12345678901234567890123456789012"


def _make_fake_response(*, status_code: int = 200, body: Any = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {
        "choices": [{"message": {"content": json.dumps(_VALID_CANDIDATE)}, "finish_reason": "stop"}]
    }
    resp.text.return_value = ""
    return resp


def _make_adapter(
    fake_response: Any = None,
    *,
    status_code: int = 200,
    body: Any = None,
) -> OpenAICompatibleLLMProviderAdapter:
    mock_client = MagicMock()
    mock_client.post.return_value = fake_response or _make_fake_response(
        status_code=status_code,
        body=body,
    )
    return OpenAICompatibleLLMProviderAdapter(
        config=_VALID_CONFIG,
        api_key=_VALID_API_KEY,
        http_client=mock_client,
    )


# ---------------------------------------------------------------------------
# A. Config validation
# ---------------------------------------------------------------------------


class TestValidateOpenAICompatibleConfig:
    def test_valid_config_no_issues(self):
        issues = validate_openai_compatible_config(
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key="sk-validkey123456789012345678901234",
        )
        assert issues == []

    def test_missing_base_url_produces_issue(self):
        issues = validate_openai_compatible_config(
            base_url="", model="test-model", api_key="sk-key"
        )
        codes = [i.code for i in issues]
        assert "missing_base_url" in codes

    def test_missing_model_produces_issue(self):
        issues = validate_openai_compatible_config(
            base_url="https://api.example.com/v1", model="", api_key="sk-key"
        )
        codes = [i.code for i in issues]
        assert "missing_model" in codes

    def test_missing_api_key_produces_issue(self):
        issues = validate_openai_compatible_config(
            base_url="https://api.example.com/v1", model="test", api_key=""
        )
        codes = [i.code for i in issues]
        assert "missing_api_key" in codes

    def test_http_scheme_without_allow_http_produces_issue(self):
        issues = validate_openai_compatible_config(
            base_url="http://api.example.com/v1", model="test", api_key="sk-key"
        )
        codes = [i.code for i in issues]
        assert "insecure_base_url" in codes

    def test_http_scheme_with_allow_http_is_ok(self):
        issues = validate_openai_compatible_config(
            base_url="http://localhost:8080/v1",
            model="test",
            api_key="sk-key",
            allow_http=True,
        )
        codes = [i.code for i in issues]
        assert "insecure_base_url" not in codes

    def test_file_scheme_is_rejected(self):
        issues = validate_openai_compatible_config(
            base_url="file:///etc/passwd", model="test", api_key="sk-key"
        )
        codes = [i.code for i in issues]
        assert "invalid_base_url_scheme" in codes

    def test_gopher_scheme_is_rejected(self):
        issues = validate_openai_compatible_config(
            base_url="gopher://evil.example.com/", model="test", api_key="sk-key"
        )
        codes = [i.code for i in issues]
        assert "invalid_base_url_scheme" in codes

    def test_empty_host_produces_issue(self):
        issues = validate_openai_compatible_config(
            base_url="https:///v1", model="test", api_key="sk-key"
        )
        codes = [i.code for i in issues]
        assert "invalid_base_url_host" in codes

    def test_all_fields_missing_produces_three_issues(self):
        issues = validate_openai_compatible_config(base_url="", model="", api_key="")
        assert len(issues) >= 3

    def test_issue_message_does_not_contain_api_key_value(self):
        issues = validate_openai_compatible_config(
            base_url="https://api.example.com/v1",
            model="test",
            api_key="sk-supersecret12345678901234",
        )
        for issue in issues:
            assert "sk-supersecret" not in issue.message


class TestOpenAICompatibleProviderConfig:
    def test_base_url_origin_returns_scheme_and_host(self):
        cfg = OpenAICompatibleProviderConfig(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
        )
        assert cfg.base_url_origin == "https://api.deepseek.com"

    def test_base_url_origin_invalid_returns_safe_string(self):
        cfg = OpenAICompatibleProviderConfig(base_url="not-a-url", model="test")
        # Should not raise, return something safe
        assert isinstance(cfg.base_url_origin, str)


# ---------------------------------------------------------------------------
# C. Provider adapter
# ---------------------------------------------------------------------------


class TestAdapterCallGenerate:
    def test_valid_json_returns_candidate(self):
        adapter = _make_adapter()
        result = adapter.call_generate("system", "user")
        assert result["title"] == "Test Lab"

    def test_url_constructed_correctly(self):
        mock_client = MagicMock()
        mock_client.post.return_value = _make_fake_response()
        adapter = OpenAICompatibleLLMProviderAdapter(
            config=_VALID_CONFIG, api_key=_VALID_API_KEY, http_client=mock_client
        )
        adapter.call_generate("sys", "usr")
        call_args = mock_client.post.call_args
        assert call_args[0][0].endswith("/chat/completions")

    def test_no_api_key_in_returned_result(self):
        adapter = _make_adapter()
        result = adapter.call_generate("system", "user")
        dumped = json.dumps(result)
        assert _VALID_API_KEY not in dumped
        assert "sk-" not in dumped

    def test_http_401_raises_auth_error(self):
        adapter = _make_adapter(status_code=401, body={})
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("sys", "usr")
        assert exc_info.value.code == "provider_auth_error"

    def test_http_429_raises_rate_limited(self):
        adapter = _make_adapter(status_code=429, body={})
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("sys", "usr")
        assert exc_info.value.code == "provider_rate_limited"
        assert exc_info.value.is_retriable is True

    def test_http_500_raises_server_error(self):
        adapter = _make_adapter(status_code=500, body={})
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("sys", "usr")
        assert exc_info.value.code == "provider_server_error"

    def test_timeout_exception_raises_provider_timeout(self):
        class FakeTimeoutError(Exception):
            pass

        mock_client = MagicMock()
        mock_client.post.side_effect = FakeTimeoutError("ReadTimeout: timed out")
        adapter = OpenAICompatibleLLMProviderAdapter(
            config=_VALID_CONFIG, api_key=_VALID_API_KEY, http_client=mock_client
        )
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("sys", "usr")
        assert exc_info.value.code in ("provider_timeout", "provider_network_error")

    def test_content_filter_finish_reason_raises_safety_rejected(self):
        body = {
            "choices": [
                {"message": {"content": "{}"}, "finish_reason": "content_filter"}
            ]
        }
        adapter = _make_adapter(body=body)
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("sys", "usr")
        assert exc_info.value.code == "provider_safety_rejected"

    def test_error_message_does_not_contain_api_key(self):
        adapter = _make_adapter(status_code=401, body={})
        try:
            adapter.call_generate("sys", "usr")
        except OpenAICompatibleProviderError as exc:
            assert _VALID_API_KEY not in exc.message
            assert "sk-" not in exc.message

    def test_authorization_header_not_in_returned_candidate(self):
        # Candidate returned by adapter must not contain Authorization field
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {**_VALID_CANDIDATE, "authorization": "Bearer secret"}
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        adapter = _make_adapter(body=body)
        result = adapter.call_generate("sys", "usr")
        assert "authorization" not in result

    def test_raw_model_output_field_stripped(self):
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {**_VALID_CANDIDATE, "raw_model_output": "secret thinking"}
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        adapter = _make_adapter(body=body)
        result = adapter.call_generate("sys", "usr")
        assert "raw_model_output" not in result

    def test_chain_of_thought_field_stripped(self):
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {**_VALID_CANDIDATE, "chain_of_thought": "my reasoning"}
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        adapter = _make_adapter(body=body)
        result = adapter.call_generate("sys", "usr")
        assert "chain_of_thought" not in result

    def test_publish_status_forced_to_draft(self):
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {**_VALID_CANDIDATE, "publish_status": "published"}
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        adapter = _make_adapter(body=body)
        result = adapter.call_generate("sys", "usr")
        assert result.get("publish_status") == "draft"


# ---------------------------------------------------------------------------
# C. parse_provider_response
# ---------------------------------------------------------------------------


class TestParseProviderResponse:
    def test_plain_json_object_parses(self):
        result = parse_provider_response(json.dumps(_VALID_CANDIDATE))
        assert result["title"] == "Test Lab"

    def test_fenced_code_block_json_parses(self):
        fenced = f"```json\n{json.dumps(_VALID_CANDIDATE)}\n```"
        result = parse_provider_response(fenced)
        assert result["title"] == "Test Lab"

    def test_fenced_code_block_without_lang_parses(self):
        fenced = f"```\n{json.dumps(_VALID_CANDIDATE)}\n```"
        result = parse_provider_response(fenced)
        assert result["title"] == "Test Lab"

    def test_natural_language_rejected(self):
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            parse_provider_response("Here is your lab: some text without JSON")
        assert exc_info.value.code == "natural_language_response"

    def test_malformed_json_raises_error(self):
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            parse_provider_response("{not valid json}")
        assert exc_info.value.code == "malformed_json"

    def test_json_array_raises_non_object_error(self):
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            parse_provider_response('["a", "b", "c"]')
        assert exc_info.value.code == "non_object_response"

    def test_prohibited_fields_are_stripped(self):
        candidate = {**_VALID_CANDIDATE, "raw_model_output": "secret", "chain_of_thought": "why"}
        result = parse_provider_response(json.dumps(candidate))
        assert "raw_model_output" not in result
        assert "chain_of_thought" not in result

    def test_publish_status_forced_to_draft(self):
        candidate = {**_VALID_CANDIDATE, "publish_status": "published"}
        result = parse_provider_response(json.dumps(candidate))
        assert result["publish_status"] == "draft"

    def test_normal_fields_preserved(self):
        result = parse_provider_response(json.dumps(_VALID_CANDIDATE))
        assert result["schema_version"] == "1.0"
        assert result["source_article_id"] == "test-article"

    def test_error_message_does_not_contain_raw_json(self):
        """Malformed JSON error must not echo back the input."""
        bad_input = '{"title": "secret data", "bad json...'
        try:
            parse_provider_response(bad_input)
        except OpenAICompatibleProviderError as exc:
            assert "secret data" not in exc.message
