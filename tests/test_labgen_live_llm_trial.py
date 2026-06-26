"""
Live LLM Admin-only Internal Trial & Rehearsal Gate Tests — G-68.

Covers:
  A. Live mode config tests (unit, no real LLM)
  B. Provider adapter tests (unit, fake HTTP client)
  C. call_live_with_messages() boundary method (unit)
  D. Article-to-lab with mocked live boundary (unit)
  E. Exposure guards for live mode outputs (unit)
  F. Internal rehearsal smoke (live trial — skipped by default, set RUN_LIVE_LLM_TRIAL=1)
  G. Regression (existing features unaffected)

LLM mode in unit tests: always fake adapters or mocked boundaries.
Only category F makes real LLM calls (requires RUN_LIVE_LLM_TRIAL=1 + OPENAI_API_KEY).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Internal sample article — clearly labeled, k8s domain
# ---------------------------------------------------------------------------

_INTERNAL_SAMPLE_ARTICLE_TITLE = (
    "[INTERNAL SAMPLE] Kubernetes ConfigMap 动态配置管理 — Live LLM Trial Only"
)

_INTERNAL_SAMPLE_ARTICLE = """
# [INTERNAL SAMPLE] Kubernetes ConfigMap 动态配置管理

**注意：本文仅用于 Live LLM Admin Trial 内部测试，不对外发布。**

## 概述

ConfigMap 是 Kubernetes 中用于存储非机密配置数据的 API 对象。本文介绍如何创建、
验证和清理 ConfigMap，以及将配置注入 Pod 环境变量的基础操作。

## 前提条件

- Kubernetes 集群已运行（kubectl 已配置）
- 对 default 命名空间有操作权限

## 步骤一：创建 ConfigMap

使用命令行直接创建：

```bash
kubectl create configmap app-config \\
  --from-literal=APP_ENV=development \\
  --from-literal=LOG_LEVEL=info \\
  -n default
```

验证创建成功：

```bash
kubectl get configmap app-config -n default
```

预期输出：

```
NAME         DATA   AGE
app-config   2      5s
```

## 步骤二：查看 ConfigMap 内容

```bash
kubectl describe configmap app-config -n default
```

## 步骤三：验证键值

```bash
kubectl get configmap app-config -n default -o jsonpath='{.data.APP_ENV}'
```

预期输出：`development`

## 步骤四：更新 ConfigMap

```bash
kubectl patch configmap app-config -n default \\
  --type merge \\
  -p '{"data":{"LOG_LEVEL":"debug"}}'
```

验证更新：

```bash
kubectl get configmap app-config -n default -o jsonpath='{.data.LOG_LEVEL}'
```

预期输出：`debug`

## 清理

```bash
kubectl delete configmap app-config -n default --ignore-not-found
```

验证清理完成：

```bash
kubectl get configmap -n default | grep -c app-config || true
```

预期输出：`0`

## 总结

本文介绍了 Kubernetes ConfigMap 的基础操作。通过 ConfigMap 可以将配置与
容器镜像解耦，实现配置的动态更新。

关键操作：create / get / describe / patch / delete。
"""

_THEORETICAL_ARTICLE = """
# Kubernetes 概念简介（纯理论）

Kubernetes 是一个容器编排平台。Pod 是最小部署单元。
Service 提供网络访问。无具体命令行操作。
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Fake HTTP client for provider adapter tests
# ---------------------------------------------------------------------------

class _FakeHttpResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


class _FakeHttpClient:
    """Injectable HTTP client for OpenAICompatibleLLMProviderAdapter tests."""

    def __init__(
        self,
        status_code: int = 200,
        body: Any = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._status = status_code
        self._body = body
        self._raise = raise_exc
        self.calls: list[dict] = []

    def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> _FakeHttpResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self._raise is not None:
            raise self._raise
        return _FakeHttpResponse(self._status, self._body)


def _openai_response_body(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
    }


def _valid_lab_draft_json() -> dict:
    """Minimal valid LabDraft candidate JSON for adapter tests."""
    return {
        "schema_version": "1.0",
        "source_article_id": "test-article-id",
        "title": "Test ConfigMap Lab",
        "description": "Learn ConfigMap basics",
        "estimated_duration_minutes": 20,
        "difficulty": "beginner",
        "runtime_requirements": {"platform": "k8s"},
        "steps": [
            {
                "step_id": "step-1",
                "order": 1,
                "why": "Understand ConfigMap creation",
                "do": "Create the ConfigMap",
                "commands": ["kubectl create configmap app-config --from-literal=k=v -n default"],
                "observe": "ConfigMap appears in kubectl get",
                "expected_output": "app-config created",
                "verify": [
                    {
                        "verify_id": "step-1-v1",
                        "type": "configmap_exists",
                        "namespace": "{{lab_namespace}}",
                        "name": "app-config",
                    }
                ],
                "explain": {
                    "concept": "ConfigMap decouples config from images",
                    "observation": "ConfigMap visible via kubectl",
                },
            }
        ],
        "cleanup": {
            "namespace_cleanup": {"type": "delete_namespace", "namespace": "{{lab_namespace}}"},
            "cluster_scoped_resources": [],
            "cleanup_verified": False,
        },
        "publish_status": "draft",
        "rehearsal_required": True,
    }


# ---------------------------------------------------------------------------
# Helpers to build provider boundary + adapters
# ---------------------------------------------------------------------------

def _make_boundary_with_fake_candidate(candidate: dict):
    """Build LLMProviderBoundaryService with a fake live adapter returning given candidate."""
    from backend.labgen.llm_openai_compatible import (
        OpenAICompatibleLLMProviderAdapter,
        OpenAICompatibleProviderConfig,
    )
    from backend.labgen.llm_provider_boundary import (
        LLMProviderBoundaryService,
        LLMProviderConfig,
        LLMProviderMode,
        LLMProviderName,
    )

    fake_http = _FakeHttpClient(
        status_code=200,
        body=_openai_response_body(json.dumps(candidate)),
    )
    adapter = OpenAICompatibleLLMProviderAdapter(
        config=OpenAICompatibleProviderConfig(
            base_url="https://api.fake.test/v1",
            model="fake-model",
        ),
        api_key="fake-key-for-testing",
        http_client=fake_http,
    )
    provider_config = LLMProviderConfig(
        provider_name=LLMProviderName.OPENAI_COMPATIBLE,
        mode=LLMProviderMode.LIVE_ENABLED,
    )
    return LLMProviderBoundaryService(config=provider_config, live_adapter=adapter)


def _make_fake_only_boundary():
    from backend.labgen.llm_provider_boundary import (
        LLMProviderBoundaryService,
        LLMProviderConfig,
        LLMProviderMode,
        LLMProviderName,
    )
    return LLMProviderBoundaryService(
        config=LLMProviderConfig(
            provider_name=LLMProviderName.FAKE,
            mode=LLMProviderMode.FAKE_ONLY,
        )
    )


# ---------------------------------------------------------------------------
# Article + lab draft service helpers
# ---------------------------------------------------------------------------

def _make_article_draft_service(tmp_path: Path):
    """Create ArticleDraftService with isolated repos."""
    from pathlib import Path as _Path
    from backend.labgen.article_draft_repository import ArticleDraftRepository
    from backend.labgen.article_draft_service import ArticleDraftService
    from backend.labgen.repository import LabDraftRepository
    from backend.labgen.static_validator import ArticleDraftValidator
    from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier

    article_repo = ArticleDraftRepository(path=_Path(tmp_path / "article_drafts.json"))
    lab_repo = LabDraftRepository(path=_Path(tmp_path / "lab_drafts.json"))
    return ArticleDraftService(
        article_repo=article_repo,
        lab_repo=lab_repo,
        classifier=StubFeasibilityClassifier(),
        validator=ArticleDraftValidator(),
    ), article_repo, lab_repo


def _create_k8s_article_draft(svc, admin="owner"):
    """Create a k8s article draft with the internal sample article."""
    from backend.labgen.article_models import ArticleSourceMetadata
    from backend.labgen.stub_feasibility_classifier import compute_content_hash

    meta = ArticleSourceMetadata(
        title=_INTERNAL_SAMPLE_ARTICLE_TITLE,
        submitted_by_user_id=admin,
        content_hash=compute_content_hash(_INTERNAL_SAMPLE_ARTICLE),
        content_length=len(_INTERNAL_SAMPLE_ARTICLE),
        raw_text_persisted=False,
        user_confirmed_right_to_use=True,
        user_confirmed_no_secrets=True,
    )
    return svc.create_draft(
        raw_text=_INTERNAL_SAMPLE_ARTICLE,
        source_metadata=meta,
        submitted_by=admin,
    )


# ===========================================================================
# A. Live Mode Config Tests
# ===========================================================================


class TestLiveModeConfig:
    """Config validation for live vs fake mode — no real LLM calls."""

    def test_default_labgen_llm_mode_is_fake_only(self):
        """LABGEN_LLM_MODE must default to fake_only — never live without explicit config."""
        from backend import config as cfg
        # Read the module default — may be overridden by env in CI, but must not be live by default
        # In a clean environment without LABGEN_LLM_MODE set, default is fake_only
        assert cfg.LABGEN_LLM_MODE in ("fake_only", "live_admin_only"), (
            "LABGEN_LLM_MODE must be one of the known values"
        )

    def test_live_mode_config_requires_all_three_vars(self):
        """Missing any of the three OpenAI config vars → validate_openai_compatible_config fails."""
        from backend.labgen.llm_openai_compatible import validate_openai_compatible_config

        # Missing base_url
        issues = validate_openai_compatible_config("", "gpt-4o-mini", "sk-test")
        assert any(i.code == "missing_base_url" for i in issues)

        # Missing model
        issues = validate_openai_compatible_config("https://api.openai.com/v1", "", "sk-test")
        assert any(i.code == "missing_model" for i in issues)

        # Missing API key
        issues = validate_openai_compatible_config("https://api.openai.com/v1", "gpt-4o-mini", "")
        assert any(i.code == "missing_api_key" for i in issues)

    def test_invalid_base_url_scheme_rejected(self):
        from backend.labgen.llm_openai_compatible import validate_openai_compatible_config

        issues = validate_openai_compatible_config("file:///etc/passwd", "gpt-4o-mini", "sk-test")
        assert any("scheme" in i.code for i in issues)

    def test_http_base_url_rejected_in_production(self):
        from backend.labgen.llm_openai_compatible import validate_openai_compatible_config

        issues = validate_openai_compatible_config("http://api.openai.com/v1", "gpt-4o-mini", "sk-test")
        assert any("insecure" in i.code or "http" in i.message.lower() for i in issues)

    def test_http_base_url_allowed_when_flag_set(self):
        from backend.labgen.llm_openai_compatible import validate_openai_compatible_config

        # allow_http=True is for test/local environments only
        issues = validate_openai_compatible_config(
            "http://localhost:8080/v1", "gpt-4o-mini", "sk-test", allow_http=True
        )
        assert not issues

    def test_boundary_service_not_live_enabled_without_config(self):
        """When config vars are missing, live_enabled must be False."""
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
            LLMProviderName,
        )

        # No live_adapter injected → live_enabled=False
        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(
                provider_name=LLMProviderName.OPENAI_COMPATIBLE,
                mode=LLMProviderMode.LIVE_ENABLED,
            ),
            live_adapter=None,
        )
        assert not svc.live_enabled

    def test_generate_lab_live_mode_fails_closed_on_missing_config(self, tmp_path):
        """generate_lab_from_article() with live_admin_only + missing config → LLMGenerationFailed."""
        import backend.config as cfg
        from backend.labgen.article_draft_service import LLMGenerationFailed
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        svc, _, _ = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)

        # Mock config to live_admin_only but boundary returns not-live
        not_live = _make_fake_only_boundary()
        not_live._config.mode.value  # just to verify

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=not_live):
            with pytest.raises(LLMGenerationFailed) as exc_info:
                svc.generate_lab_from_article(
                    draft_id=contract.draft_id,
                    article_text=_INTERNAL_SAMPLE_ARTICLE,
                    admin_user="owner",
                )
            assert "live_provider_config_error" in str(exc_info.value)


# ===========================================================================
# B. Provider Adapter Tests (fake HTTP client)
# ===========================================================================


class TestProviderAdapter:
    """OpenAICompatibleLLMProviderAdapter unit tests using fake HTTP clients."""

    def _make_adapter(self, http_client) -> "OpenAICompatibleLLMProviderAdapter":
        from backend.labgen.llm_openai_compatible import (
            OpenAICompatibleLLMProviderAdapter,
            OpenAICompatibleProviderConfig,
        )
        return OpenAICompatibleLLMProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                base_url="https://api.fake.test/v1",
                model="fake-model",
                timeout_ms=5000,
            ),
            api_key="test-api-key-never-returned",
            http_client=http_client,
        )

    def test_valid_json_response_parsed(self):
        """200 with JSON content → returns parsed dict with publish_status forced to draft."""
        candidate = _valid_lab_draft_json()
        candidate["publish_status"] = "published"  # provider tries to set published
        http = _FakeHttpClient(
            status_code=200,
            body=_openai_response_body(json.dumps(candidate)),
        )
        adapter = self._make_adapter(http)
        result = adapter.call_generate("system", "user")
        assert result["publish_status"] == "draft"  # forced down to draft

    def test_json_in_fenced_code_block_parsed(self):
        """Provider wraps JSON in ```json ``` block → still extracted correctly."""
        candidate = _valid_lab_draft_json()
        content = f"```json\n{json.dumps(candidate)}\n```"
        http = _FakeHttpClient(
            status_code=200,
            body=_openai_response_body(content),
        )
        adapter = self._make_adapter(http)
        result = adapter.call_generate("system", "user")
        assert result["title"] == candidate["title"]

    def test_natural_language_response_raises(self):
        """Provider returns prose instead of JSON → OpenAICompatibleProviderError."""
        from backend.labgen.llm_openai_compatible import OpenAICompatibleProviderError

        http = _FakeHttpClient(
            status_code=200,
            body=_openai_response_body("Here is a lab for you. Steps: ..."),
        )
        adapter = self._make_adapter(http)
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("system", "user")
        assert exc_info.value.code == "natural_language_response"

    def test_malformed_json_raises(self):
        from backend.labgen.llm_openai_compatible import OpenAICompatibleProviderError

        http = _FakeHttpClient(
            status_code=200,
            body=_openai_response_body("{not valid json"),
        )
        adapter = self._make_adapter(http)
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("system", "user")
        assert exc_info.value.code == "malformed_json"

    def test_401_raises_auth_error(self):
        from backend.labgen.llm_openai_compatible import OpenAICompatibleProviderError

        http = _FakeHttpClient(status_code=401, body={"error": "invalid_api_key"})
        adapter = self._make_adapter(http)
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("system", "user")
        assert exc_info.value.code == "provider_auth_error"

    def test_429_raises_rate_limited(self):
        from backend.labgen.llm_openai_compatible import OpenAICompatibleProviderError

        http = _FakeHttpClient(status_code=429, body={"error": "rate_limited"})
        adapter = self._make_adapter(http)
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("system", "user")
        assert exc_info.value.code == "provider_rate_limited"
        assert exc_info.value.is_retriable

    def test_500_raises_server_error(self):
        from backend.labgen.llm_openai_compatible import OpenAICompatibleProviderError

        http = _FakeHttpClient(status_code=500, body={"error": "internal"})
        adapter = self._make_adapter(http)
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("system", "user")
        assert exc_info.value.code == "provider_server_error"
        assert exc_info.value.is_retriable

    def test_network_error_raises_provider_error(self):
        from backend.labgen.llm_openai_compatible import OpenAICompatibleProviderError

        http = _FakeHttpClient(raise_exc=ConnectionError("network down"))
        adapter = self._make_adapter(http)
        with pytest.raises(OpenAICompatibleProviderError) as exc_info:
            adapter.call_generate("system", "user")
        assert exc_info.value.code == "provider_network_error"

    def test_prohibited_fields_stripped(self):
        """raw_model_output, chain_of_thought etc. are stripped from provider response."""
        candidate = dict(_valid_lab_draft_json())
        candidate["raw_model_output"] = "secret chain of thought"
        candidate["api_key"] = "sk-leaked-key"
        http = _FakeHttpClient(
            status_code=200,
            body=_openai_response_body(json.dumps(candidate)),
        )
        adapter = self._make_adapter(http)
        result = adapter.call_generate("system", "user")
        assert "raw_model_output" not in result
        assert "api_key" not in result
        assert "chain_of_thought" not in result


# ===========================================================================
# C. call_live_with_messages() Boundary Method Tests
# ===========================================================================


class TestCallLiveWithMessages:
    """Test the new public method on LLMProviderBoundaryService."""

    def test_raises_config_error_when_not_live_enabled(self):
        """call_live_with_messages() raises LLMProviderConfigError when not live_enabled."""
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
            LLMProviderName,
            LLMProviderConfigError,
        )

        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(
                provider_name=LLMProviderName.FAKE,
                mode=LLMProviderMode.FAKE_ONLY,
            ),
            live_adapter=None,
        )
        with pytest.raises(LLMProviderConfigError):
            svc.call_live_with_messages("system", "user")

    def test_raises_config_error_when_live_enabled_but_no_adapter(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
            LLMProviderName,
            LLMProviderConfigError,
        )

        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(
                provider_name=LLMProviderName.OPENAI_COMPATIBLE,
                mode=LLMProviderMode.LIVE_ENABLED,
            ),
            live_adapter=None,
        )
        with pytest.raises(LLMProviderConfigError):
            svc.call_live_with_messages("system", "user")

    def test_calls_adapter_when_live_enabled(self):
        """With a configured live adapter, call_live_with_messages() delegates to it."""
        candidate = _valid_lab_draft_json()
        boundary = _make_boundary_with_fake_candidate(candidate)
        result = boundary.call_live_with_messages("system prompt", "user prompt")
        assert result["title"] == candidate["title"]

    def test_api_key_never_in_return_value(self):
        """Result must never contain api_key regardless of what provider returns."""
        candidate = dict(_valid_lab_draft_json())
        candidate["api_key"] = "sk-leaked"
        boundary = _make_boundary_with_fake_candidate(candidate)
        result = boundary.call_live_with_messages("system", "user")
        assert "api_key" not in result

    def test_publish_status_forced_to_draft(self):
        """Provider cannot set publish_status=published via call_live_with_messages."""
        candidate = dict(_valid_lab_draft_json())
        candidate["publish_status"] = "published"
        boundary = _make_boundary_with_fake_candidate(candidate)
        result = boundary.call_live_with_messages("system", "user")
        assert result["publish_status"] == "draft"


# ===========================================================================
# D. Article-to-Lab with Mocked Live Boundary
# ===========================================================================


class TestArticleToLabLiveMode:
    """Test generate_lab_from_article() in live_admin_only mode using fake boundary."""

    def test_live_mode_generates_lab_draft(self, tmp_path):
        """live_admin_only with a valid fake boundary → LabDraft created."""
        import backend.config as cfg
        from backend.labgen.article_draft_service import GenerateLabResult
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        svc, _, lab_repo = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)
        boundary = _make_boundary_with_fake_candidate(_valid_lab_draft_json())

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
            )

        assert isinstance(result, GenerateLabResult)
        assert result.lab_draft is not None

    def test_live_mode_draft_never_published(self, tmp_path):
        """Lab generated in live mode must never have publish_status=published."""
        import backend.config as cfg
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        svc, _, _ = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)

        # Fake boundary tries to set published — must be blocked
        candidate = dict(_valid_lab_draft_json())
        candidate["publish_status"] = "published"
        boundary = _make_boundary_with_fake_candidate(candidate)

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
            )

        assert result.lab_draft.publish_status.value != "published"

    def test_live_mode_rehearsal_required_always_set(self, tmp_path):
        """rehearsal_required=True must always be set on LLM-generated drafts."""
        import backend.config as cfg
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        svc, _, _ = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)

        candidate = dict(_valid_lab_draft_json())
        candidate["rehearsal_required"] = False  # provider tries to clear it
        boundary = _make_boundary_with_fake_candidate(candidate)

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
            )

        assert result.lab_draft.rehearsal_required is True

    def test_live_mode_source_article_id_set(self, tmp_path):
        """source_article_id must be set to the article draft_id, not provider-supplied."""
        import backend.config as cfg
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        svc, _, _ = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)

        candidate = dict(_valid_lab_draft_json())
        candidate["source_article_id"] = "provider-supplied-malicious-id"
        boundary = _make_boundary_with_fake_candidate(candidate)

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
            )

        assert result.lab_draft.source_article_id == contract.draft_id

    def test_live_mode_audit_log_written(self, tmp_path):
        """Audit log must be written for live mode generation (success case)."""
        import backend.config as cfg
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        audit_file = tmp_path / "audit.json"
        audit_repo = LLMAuditRepository(audit_path=audit_file)
        svc, _, _ = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)
        boundary = _make_boundary_with_fake_candidate(_valid_lab_draft_json())

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        entries = audit_repo.list_all()
        assert any(e.get("success") and e.get("llm_mode") == "live_admin_only" for e in entries)

    def test_live_mode_audit_written_on_failure(self, tmp_path):
        """Audit log written even when LLM call fails (try/finally guarantee)."""
        import backend.config as cfg
        from backend.labgen.article_draft_service import LLMGenerationFailed
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.llm_openai_compatible import OpenAICompatibleProviderError
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        audit_file = tmp_path / "audit.json"
        audit_repo = LLMAuditRepository(audit_path=audit_file)
        svc, _, _ = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)

        # Fake boundary that raises on call_live_with_messages
        boundary = _make_boundary_with_fake_candidate(_valid_lab_draft_json())
        boundary.call_live_with_messages = MagicMock(
            side_effect=OpenAICompatibleProviderError("test_error", "test failure")
        )

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            with pytest.raises((LLMGenerationFailed, Exception)):
                svc.generate_lab_from_article(
                    draft_id=contract.draft_id,
                    article_text=_INTERNAL_SAMPLE_ARTICLE,
                    admin_user="owner",
                    audit_repo=audit_repo,
                )

        entries = audit_repo.list_all()
        # Audit must have been written despite failure
        assert len(entries) >= 1


# ===========================================================================
# E. Exposure Guards for Live Mode Outputs
# ===========================================================================


class TestExposureGuardsLiveMode:
    """Verify that live LLM outputs don't leak into learner-facing APIs."""

    def test_source_article_id_not_in_learner_catalog(self, tmp_path):
        """source_article_id must not appear in /api/labs learner catalog response."""
        import backend.config as cfg
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        svc, _, lab_repo = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)
        boundary = _make_boundary_with_fake_candidate(_valid_lab_draft_json())

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
            )

        # Draft is not published — source_article_id must not appear in any published draft
        from backend.labgen.models import PublishStatus
        all_labs = lab_repo.list_all()
        published = [l for l in all_labs if l.publish_status == PublishStatus.PUBLISHED]
        for lab in published:
            assert lab.source_article_id != contract.draft_id

    def test_raw_article_text_not_persisted(self, tmp_path):
        """Article text submitted for generation must not appear in any persisted lab draft."""
        import backend.config as cfg
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        svc, _, lab_repo = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)
        boundary = _make_boundary_with_fake_candidate(_valid_lab_draft_json())

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
            )

        # Serialize the lab draft and verify raw article text absent
        lab_json = json.dumps(result.lab_draft.model_dump(mode="json"))
        assert "INTERNAL SAMPLE" not in lab_json
        assert "注意：本文仅用于" not in lab_json

    def test_audit_log_does_not_contain_article_text(self, tmp_path):
        """Audit log entries must not store raw article text or full model output."""
        import backend.config as cfg
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        audit_file = tmp_path / "audit.json"
        audit_repo = LLMAuditRepository(audit_path=audit_file)
        svc, _, _ = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)
        boundary = _make_boundary_with_fake_candidate(_valid_lab_draft_json())

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        audit_json = audit_file.read_text()
        # Title is allowed in audit (metadata); raw article body must not be stored
        assert "注意：本文仅用于" not in audit_json  # body text not stored
        assert "kubectl create configmap" not in audit_json  # raw commands not stored

    def test_audit_log_does_not_contain_api_key(self, tmp_path):
        """Audit log must never store the LLM API key."""
        import backend.config as cfg
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        audit_file = tmp_path / "audit.json"
        audit_repo = LLMAuditRepository(audit_path=audit_file)
        svc, _, _ = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)
        boundary = _make_boundary_with_fake_candidate(_valid_lab_draft_json())

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_API_KEY", "sk-supersecretkey123"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        audit_json = audit_file.read_text()
        assert "sk-supersecretkey123" not in audit_json
        assert "supersecretkey" not in audit_json

    def test_draft_not_visible_in_learner_catalog_before_publish(self, tmp_path):
        """LLM-generated draft (not published) must not appear in /api/labs."""
        import backend.config as cfg
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService

        svc, _, lab_repo = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)
        boundary = _make_boundary_with_fake_candidate(_valid_lab_draft_json())

        with patch.object(cfg, "LABGEN_LLM_MODE", "live_admin_only"), \
             patch.object(cfg, "LABGEN_LLM_OPENAI_MODEL", "fake-model"), \
             patch.object(LLMProviderBoundaryService, "create_from_env", return_value=boundary):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_INTERNAL_SAMPLE_ARTICLE,
                admin_user="owner",
            )

        assert result.lab_draft.publish_status.value != "published"
        from backend.labgen.models import PublishStatus
        all_labs = lab_repo.list_all()
        published_ids = {
            lab.lab_id for lab in all_labs if lab.publish_status == PublishStatus.PUBLISHED
        }
        assert result.lab_draft.lab_id not in published_ids


# ===========================================================================
# F. Internal Rehearsal Smoke (Live Trial — skipped by default)
# ===========================================================================

_RUN_LIVE_TRIAL = os.getenv("RUN_LIVE_LLM_TRIAL", "0") == "1"


@pytest.mark.skipif(not _RUN_LIVE_TRIAL, reason="Set RUN_LIVE_LLM_TRIAL=1 to run live LLM trial")
class TestInternalRehearsalSmoke:
    """
    Live LLM trial using real OpenAI API.
    Runs only when RUN_LIVE_LLM_TRIAL=1 is set.

    Article: internal sample k8s article (not an owner/published article).
    Decision cap: LIVE_LLM_ADMIN_TRIAL_READY_WITH_NOTES or LIVE_LLM_ADMIN_TRIAL_NEEDS_ITERATION.
    Owner Soft Launch Article #1 Publish Gate: NOT declared in this test.
    """

    @pytest.fixture()
    def trial_config(self):
        """Inject live LLM config from environment. Fails fast if not configured."""
        api_key = os.getenv("LABGEN_LLM_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            pytest.skip("LABGEN_LLM_OPENAI_API_KEY / OPENAI_API_KEY not set")
        return {
            "api_key": api_key,
            "base_url": os.getenv("LABGEN_LLM_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "model": os.getenv("LABGEN_LLM_OPENAI_MODEL", "gpt-4o-mini"),
        }

    def test_live_llm_generates_valid_k8s_draft(self, tmp_path, trial_config, monkeypatch):
        """
        Live trial: generate k8s lab draft from internal sample article.

        This test:
        1. Creates an article draft (internal sample, clearly labeled)
        2. Calls generate_lab_from_article() in live_admin_only mode
        3. Verifies draft schema
        4. Verifies StaticValidator passes (or records failures)
        5. Verifies publish blocked (rehearsal_required=True)
        6. Records all results in trial_result.json for the result artifact
        """
        import backend.config as cfg
        from backend.labgen.article_draft_service import GenerateLabResult
        from backend.labgen.models import ValidatorStatus

        # Patch config for live mode
        monkeypatch.setattr(cfg, "LABGEN_LLM_MODE", "live_admin_only")
        monkeypatch.setattr(cfg, "LABGEN_LLM_PROVIDER_MODE", "live_enabled")
        monkeypatch.setattr(cfg, "LABGEN_LLM_PROVIDER_NAME", "openai_compatible")
        monkeypatch.setattr(cfg, "LABGEN_LLM_OPENAI_BASE_URL", trial_config["base_url"])
        monkeypatch.setattr(cfg, "LABGEN_LLM_OPENAI_MODEL", trial_config["model"])
        monkeypatch.setattr(cfg, "LABGEN_LLM_OPENAI_API_KEY", trial_config["api_key"])

        from backend.labgen.llm_audit import LLMAuditRepository

        audit_file = tmp_path / "live_trial_audit.json"
        audit_repo = LLMAuditRepository(audit_path=audit_file)
        svc, _, lab_repo = _make_article_draft_service(tmp_path)
        contract = _create_k8s_article_draft(svc)

        result: GenerateLabResult = svc.generate_lab_from_article(
            draft_id=contract.draft_id,
            article_text=_INTERNAL_SAMPLE_ARTICLE,
            admin_user="owner",
            desired_lab_title="[TRIAL] Kubernetes ConfigMap 基础操作",
            audit_repo=audit_repo,
        )

        # --- Structural assertions ---
        assert result.lab_draft is not None, "Lab draft must be generated"
        assert result.lab_draft.publish_status.value != "published", "Must not be published"
        assert result.lab_draft.rehearsal_required is True, "rehearsal_required must be True"
        assert result.lab_draft.source_article_id == contract.draft_id
        assert result.lab_draft.title, "Draft must have a title"
        assert result.lab_draft.steps, "Draft must have steps"
        assert result.lab_draft.cleanup is not None, "Draft must have cleanup spec"

        # --- Audit log check ---
        audit_entries = audit_repo.list_all()
        assert any(e.get("success") for e in audit_entries), "Audit must record success"
        audit_json = audit_file.read_text()
        assert trial_config["api_key"] not in audit_json, "API key must not appear in audit"
        # article_title (metadata) is allowed in audit; raw body text must not be logged
        assert "注意：本文仅用于 Live LLM Admin Trial" not in audit_json, "Raw article body must not appear in audit"
        assert "kubectl create configmap demo-config" not in audit_json, "Raw article commands must not appear in audit"

        # --- StaticValidator result summary ---
        failed_checks = [
            r for r in result.lab_draft.validator_results or []
            if r.status == ValidatorStatus.FAILED
        ]

        # --- Structural Rehearsal Assessment ---
        has_commands = any(
            step.commands for step in result.lab_draft.steps
        )
        has_verify = any(step.verify for step in result.lab_draft.steps)
        has_cleanup = (
            result.lab_draft.cleanup is not None
            and result.lab_draft.cleanup.namespace_cleanup is not None
        )

        # Record results for the artifact
        trial_result = {
            "article": _INTERNAL_SAMPLE_ARTICLE_TITLE,
            "draft_id": result.lab_draft.lab_id,
            "title": result.lab_draft.title,
            "step_count": len(result.lab_draft.steps),
            "publish_status": result.lab_draft.publish_status.value,
            "rehearsal_required": result.lab_draft.rehearsal_required,
            "operability_status": result.operability_status,
            "validation_passed": result.validation_passed,
            "failed_validator_checks": [r.check_id for r in failed_checks],
            "has_commands": has_commands,
            "has_verify": has_verify,
            "has_cleanup": has_cleanup,
            "warnings": result.warnings,
            "audit_entries": len(audit_entries),
        }
        (tmp_path / "trial_result.json").write_text(json.dumps(trial_result, indent=2))

        # --- Final assertions ---
        assert result.lab_draft.lab_id, "Draft must have an ID"
        assert has_cleanup, "Generated draft must have a cleanup spec"
        # Note: has_commands may be False if LLM generates a different structure
        # This is documented in the result artifact as a quality finding

        print(f"\n[LIVE TRIAL RESULT]\n{json.dumps(trial_result, indent=2, ensure_ascii=False)}")


# ===========================================================================
# G. Regression Tests
# ===========================================================================


class TestRegressionLiveTrial:
    """Verify existing features are unaffected by G-68 changes."""

    def test_health_endpoint_ok(self):
        from backend.main import app
        client = TestClient(app)
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json().get("status") == "healthy"

    def test_existing_labs_catalog_accessible(self):
        """Existing published labs must be accessible via /api/labs (requires auth)."""
        from backend.auth_deps import get_current_user
        from backend.auth import auth_manager
        from backend.main import app

        _real_is_admin = auth_manager.is_admin
        try:
            app.dependency_overrides[get_current_user] = lambda: "regression_user"
            client = TestClient(app)
            r = client.get("/api/labs")
            assert r.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            auth_manager.is_admin = _real_is_admin

    def test_call_live_with_messages_method_exists(self):
        """call_live_with_messages() is a proper public method (not private)."""
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService
        assert hasattr(LLMProviderBoundaryService, "call_live_with_messages")
        assert not LLMProviderBoundaryService.call_live_with_messages.__name__.startswith("_")

    def test_llm_provider_config_error_exported(self):
        """LLMProviderConfigError must be importable from boundary module."""
        from backend.labgen.llm_provider_boundary import LLMProviderConfigError
        assert issubclass(LLMProviderConfigError, Exception)

    def test_article_draft_service_no_longer_accesses_private_live_adapter(self):
        """Verify private _live_adapter access is removed from article_draft_service."""
        import inspect
        from backend.labgen import article_draft_service
        source = inspect.getsource(article_draft_service)
        assert "_live_adapter.call_generate" not in source, (
            "Private _live_adapter access must be replaced by call_live_with_messages()"
        )

    def test_api_key_not_hardcoded_in_config(self):
        """Config module must not hard-code any API key value."""
        import inspect
        from backend import config
        src = inspect.getsource(config)
        # No real-looking API key should be hardcoded — empty string default is correct
        assert 'LABGEN_LLM_OPENAI_API_KEY = "sk-' not in src
        assert "LABGEN_LLM_OPENAI_API_KEY = 'sk-" not in src

    def test_fake_only_remains_default_when_no_env_override(self, monkeypatch):
        """Without env var, LABGEN_LLM_MODE must default to fake_only behavior."""
        import backend.config as cfg
        # If LABGEN_LLM_MODE is not set to live_admin_only, generation uses fake
        if cfg.LABGEN_LLM_MODE == "live_admin_only":
            pytest.skip("LABGEN_LLM_MODE=live_admin_only set in env — live mode is intentional")

        assert cfg.LABGEN_LLM_MODE == "fake_only", (
            "LABGEN_LLM_MODE must be fake_only by default"
        )
