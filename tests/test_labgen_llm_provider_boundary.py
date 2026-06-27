"""
LLM Provider Boundary Hardening v0.1 — unit tests.

Tests: config defaults, provider boundary dispatch, dry-run adapter,
       generation service integration, and sanitizer coverage.

No real LLM calls. No API keys. No network requests.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# A. Config / defaults
# ---------------------------------------------------------------------------


class TestLLMProviderConfigDefaults:
    def test_default_mode_is_fake_only(self):
        from backend.labgen.llm_provider_boundary import LLMProviderConfig, LLMProviderMode

        cfg = LLMProviderConfig()
        assert cfg.mode == LLMProviderMode.FAKE_ONLY

    def test_default_provider_is_fake(self):
        from backend.labgen.llm_provider_boundary import LLMProviderConfig, LLMProviderName

        cfg = LLMProviderConfig()
        assert cfg.provider_name == LLMProviderName.FAKE

    def test_default_timeout_ms(self):
        from backend.labgen.llm_provider_boundary import LLMProviderConfig

        cfg = LLMProviderConfig()
        assert cfg.timeout_ms == 30000

    def test_default_max_output_tokens(self):
        from backend.labgen.llm_provider_boundary import LLMProviderConfig

        cfg = LLMProviderConfig()
        assert cfg.max_output_tokens == 4096

    def test_timeout_clamped_at_60000(self):
        from pydantic import ValidationError

        from backend.labgen.llm_provider_boundary import LLMProviderConfig

        with pytest.raises(ValidationError):
            LLMProviderConfig(timeout_ms=99999)

    def test_max_output_tokens_clamped_at_8192(self):
        from pydantic import ValidationError

        from backend.labgen.llm_provider_boundary import LLMProviderConfig

        with pytest.raises(ValidationError):
            LLMProviderConfig(max_output_tokens=99999)

    def test_live_providers_exist_as_enum_values(self):
        from backend.labgen.llm_provider_boundary import LLMProviderName

        assert LLMProviderName.OPENAI.value == "openai"
        assert LLMProviderName.ANTHROPIC.value == "anthropic"
        assert LLMProviderName.GEMINI.value == "gemini"

    def test_invalid_mode_name_safe_fallback(self):
        """create_from_env falls back to FAKE_ONLY on invalid LABGEN_LLM_PROVIDER_MODE."""
        from unittest.mock import patch

        import backend.config as cfg
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService, LLMProviderMode

        with patch.object(cfg, "LABGEN_LLM_PROVIDER_MODE", "INVALID_MODE"):
            svc = LLMProviderBoundaryService.create_from_env()
            assert svc.config.mode == LLMProviderMode.FAKE_ONLY

    def test_invalid_provider_name_safe_fallback(self):
        from unittest.mock import patch

        import backend.config as cfg
        from backend.labgen.llm_provider_boundary import LLMProviderBoundaryService, LLMProviderName

        with patch.object(cfg, "LABGEN_LLM_PROVIDER_NAME", "gpt-99-turbo"):
            svc = LLMProviderBoundaryService.create_from_env()
            assert svc.config.provider_name == LLMProviderName.FAKE

    def test_no_api_key_in_config_model(self):
        """LLMProviderConfig must not have any API key fields."""
        from backend.labgen.llm_provider_boundary import LLMProviderConfig

        field_names = set(LLMProviderConfig.model_fields.keys())
        forbidden = {"api_key", "secret", "token", "password", "key"}
        assert not forbidden.intersection(field_names), (
            f"API key fields found in LLMProviderConfig: {forbidden.intersection(field_names)}"
        )


# ---------------------------------------------------------------------------
# B. Provider boundary dispatch
# ---------------------------------------------------------------------------


class TestProviderBoundaryDispatch:
    def _make_request(self, prompt: str = "k8s networking lab") -> "LLMProviderRequest":
        from backend.labgen.llm_provider_boundary import LLMProviderRequest

        return LLMProviderRequest(
            purpose="draft_generation",
            sanitized_user_prompt=prompt,
        )

    def test_disabled_mode_returns_rejected_reason(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )

        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DISABLED)
        )
        resp = svc.call(self._make_request())
        assert resp.rejected_reason == "provider_disabled"
        assert resp.candidate_json is None

    def test_live_disabled_mode_returns_rejected_reason(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )

        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.LIVE_DISABLED)
        )
        resp = svc.call(self._make_request())
        assert resp.rejected_reason == "live_provider_disabled"

    def test_live_provider_name_always_disabled(self):
        """Even if mode=fake_only, a live provider name triggers the disabled path."""
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
            LLMProviderName,
        )

        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(
                provider_name=LLMProviderName.OPENAI,
                mode=LLMProviderMode.FAKE_ONLY,
            )
        )
        resp = svc.call(self._make_request())
        assert resp.rejected_reason == "live_provider_disabled"

    def test_anthropic_provider_name_always_disabled(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
            LLMProviderName,
        )

        for name in (LLMProviderName.OPENAI, LLMProviderName.ANTHROPIC, LLMProviderName.GEMINI):
            svc = LLMProviderBoundaryService(
                config=LLMProviderConfig(
                    provider_name=name, mode=LLMProviderMode.FAKE_ONLY
                )
            )
            resp = svc.call(self._make_request())
            assert resp.rejected_reason == "live_provider_disabled", f"Expected disabled for {name}"

    def test_fake_only_returns_valid_candidate(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )

        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.FAKE_ONLY)
        )
        resp = svc.call(self._make_request())
        assert resp.rejected_reason is None
        assert resp.candidate_json is not None
        assert isinstance(resp.candidate_json, dict)

    def test_fake_only_candidate_passes_pydantic(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )
        from backend.labgen.models import LabDraft

        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.FAKE_ONLY)
        )
        resp = svc.call(self._make_request())
        draft = LabDraft.model_validate(resp.candidate_json)
        assert draft.title

    def test_raw_output_available_always_false(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )

        for mode in (LLMProviderMode.FAKE_ONLY, LLMProviderMode.DISABLED):
            svc = LLMProviderBoundaryService(
                config=LLMProviderConfig(mode=mode)
            )
            resp = svc.call(self._make_request())
            assert resp.raw_output_available is False, f"raw_output_available=True in {mode}"

    def test_safety_policy_live_providers_never_enabled(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
        )

        svc = LLMProviderBoundaryService(config=LLMProviderConfig())
        assert svc.safety_policy.live_providers_enabled is False

    def test_dry_run_available_only_in_dry_run_mode(self):
        from backend.labgen.llm_provider_boundary import (
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )

        for mode, expected in [
            (LLMProviderMode.FAKE_ONLY, False),
            (LLMProviderMode.DISABLED, False),
            (LLMProviderMode.DRY_RUN, True),
            (LLMProviderMode.LIVE_DISABLED, False),
        ]:
            svc = LLMProviderBoundaryService(config=LLMProviderConfig(mode=mode))
            assert svc.dry_run_available == expected, f"Wrong dry_run_available for {mode}"


# ---------------------------------------------------------------------------
# C. DryRun adapter
# ---------------------------------------------------------------------------


class TestDryRunAdapter:
    def _make_request(self) -> "LLMProviderRequest":
        from backend.labgen.llm_provider_boundary import LLMProviderRequest

        return LLMProviderRequest(
            purpose="draft_generation",
            sanitized_user_prompt="test prompt for dry run",
        )

    def _make_svc(self, inject_mode: str) -> "LLMProviderBoundaryService":
        from backend.labgen.llm_provider_boundary import (
            DryRunLLMProviderAdapter,
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )

        return LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
            dry_run_adapter=DryRunLLMProviderAdapter(inject_mode=inject_mode),
        )

    def test_valid_candidate_returns_candidate_json(self):
        svc = self._make_svc("valid_candidate")
        resp = svc.call(self._make_request())
        assert resp.candidate_json is not None
        assert resp.rejected_reason is None

    def test_valid_candidate_passes_pydantic(self):
        from backend.labgen.models import LabDraft

        svc = self._make_svc("valid_candidate")
        resp = svc.call(self._make_request())
        draft = LabDraft.model_validate(resp.candidate_json)
        assert draft.title

    def test_invalid_candidate_has_no_cleanup(self):
        svc = self._make_svc("invalid_candidate")
        resp = svc.call(self._make_request())
        assert resp.candidate_json is not None
        assert resp.candidate_json.get("cleanup") is None

    def test_malformed_returns_bad_types(self):
        svc = self._make_svc("malformed")
        resp = svc.call(self._make_request())
        assert resp.candidate_json is not None
        assert resp.candidate_json["steps"] == "not-a-list"

    def test_timeout_raises_dry_run_timeout_simulated(self):
        from backend.labgen.llm_provider_boundary import DryRunTimeoutSimulated

        svc = self._make_svc("timeout")
        with pytest.raises(DryRunTimeoutSimulated):
            svc.call(self._make_request())

    def test_provider_disabled_returns_rejected_reason(self):
        svc = self._make_svc("provider_disabled")
        resp = svc.call(self._make_request())
        assert resp.rejected_reason == "provider_disabled"
        assert resp.candidate_json is None

    def test_safety_rejection_returns_rejected_reason(self):
        svc = self._make_svc("safety_rejection")
        resp = svc.call(self._make_request())
        assert resp.rejected_reason == "safety_policy_rejected"

    def test_sensitive_output_warnings_redacted(self):
        """Sensitive-looking warnings must be redacted before reaching callers."""
        svc = self._make_svc("sensitive_output")
        resp = svc.call(self._make_request())
        for w in resp.warnings:
            assert "sk-" not in w, f"Unredacted API key in warning: {w}"
            assert "eyJ" not in w, f"Unredacted JWT in warning: {w}"

    def test_invalid_inject_mode_raises(self):
        from backend.labgen.llm_provider_boundary import DryRunLLMProviderAdapter

        with pytest.raises(ValueError, match="inject_mode"):
            DryRunLLMProviderAdapter(inject_mode="not_a_valid_mode")

    def test_raw_output_available_always_false_in_dry_run(self):
        svc = self._make_svc("valid_candidate")
        resp = svc.call(self._make_request())
        assert resp.raw_output_available is False


# ---------------------------------------------------------------------------
# D. Generation service integration
# ---------------------------------------------------------------------------


class TestGenerationServiceIntegration:
    """Verify default generation behaviour is unchanged when no boundary is injected."""

    def _make_svc_default(self):
        from backend.labgen.llm_generation import (
            FakeDraftGenerationAdapter,
            LabDraftGenerationService,
        )
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.static_validator import StaticValidator

        repo = LabDraftRepository.__new__(LabDraftRepository)
        repo._path = None
        created = []

        original_create = repo.create

        def _fake_create(draft):
            created.append(draft)
            return draft

        repo.create = _fake_create
        repo._created = created

        return LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=repo,
        )

    def _make_request(self) -> "LabDraftGenerationRequest":
        from backend.labgen.llm_generation import LabDraftGenerationRequest

        return LabDraftGenerationRequest(
            user_prompt="k8s pod networking basics",
            requester_user_id="test-user",
        )

    def test_default_generate_uses_fake_adapter(self):
        svc = self._make_svc_default()
        assert svc._provider_boundary is None

    def test_provider_boundary_not_injected_by_default(self):
        from backend.labgen.llm_generation import LabDraftGenerationService

        import inspect
        sig = inspect.signature(LabDraftGenerationService.__init__)
        params = list(sig.parameters.keys())
        assert "provider_boundary" in params

    def test_dry_run_candidate_goes_through_pydantic_and_validator(self):
        from backend.labgen.llm_generation import (
            LabDraftGenerationRequest,
            LabDraftGenerationService,
            FakeDraftGenerationAdapter,
        )
        from backend.labgen.llm_provider_boundary import (
            DryRunLLMProviderAdapter,
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.static_validator import StaticValidator

        created = []

        class _FakeRepo(LabDraftRepository):
            def __init__(self):
                pass

            def create(self, draft):
                created.append(draft)
                return draft

        boundary = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
            dry_run_adapter=DryRunLLMProviderAdapter(inject_mode="valid_candidate"),
        )
        svc = LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=_FakeRepo(),
            provider_boundary=boundary,
        )
        request = LabDraftGenerationRequest(
            user_prompt="dry run lab candidate", requester_user_id="admin"
        )
        draft, results, warnings, template_id = svc.generate_and_create(request)
        assert draft is not None
        assert len(created) == 1

    def test_invalid_dry_run_candidate_does_not_publish(self):
        from backend.labgen.llm_generation import (
            LabDraftGenerationRequest,
            LabDraftGenerationService,
            FakeDraftGenerationAdapter,
        )
        from backend.labgen.llm_provider_boundary import (
            DryRunLLMProviderAdapter,
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )
        from backend.labgen.models import PublishStatus
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.static_validator import StaticValidator

        class _FakeRepo(LabDraftRepository):
            def __init__(self):
                pass

            def create(self, draft):
                return draft

        boundary = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
            dry_run_adapter=DryRunLLMProviderAdapter(inject_mode="invalid_candidate"),
        )
        svc = LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=_FakeRepo(),
            provider_boundary=boundary,
        )
        request = LabDraftGenerationRequest(
            user_prompt="invalid candidate lab", requester_user_id="admin"
        )
        draft, results, warnings, template_id = svc.generate_and_create(request)
        assert draft.publish_status != PublishStatus.PUBLISHED

    def test_malformed_dry_run_candidate_raises_parse_error(self):
        from backend.labgen.llm_generation import (
            DraftCandidateParseError,
            LabDraftGenerationRequest,
            LabDraftGenerationService,
            FakeDraftGenerationAdapter,
        )
        from backend.labgen.llm_provider_boundary import (
            DryRunLLMProviderAdapter,
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.static_validator import StaticValidator

        class _FakeRepo(LabDraftRepository):
            def __init__(self):
                pass

        boundary = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
            dry_run_adapter=DryRunLLMProviderAdapter(inject_mode="malformed"),
        )
        svc = LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=_FakeRepo(),
            provider_boundary=boundary,
        )
        request = LabDraftGenerationRequest(
            user_prompt="malformed lab", requester_user_id="admin"
        )
        with pytest.raises(DraftCandidateParseError):
            svc.generate_and_create(request)

    def test_provider_timeout_raises_draft_generation_rejected(self):
        from backend.labgen.llm_generation import (
            DraftGenerationRejected,
            LabDraftGenerationRequest,
            LabDraftGenerationService,
            FakeDraftGenerationAdapter,
        )
        from backend.labgen.llm_provider_boundary import (
            DryRunLLMProviderAdapter,
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.static_validator import StaticValidator

        class _FakeRepo(LabDraftRepository):
            def __init__(self):
                pass

        boundary = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
            dry_run_adapter=DryRunLLMProviderAdapter(inject_mode="timeout"),
        )
        svc = LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=_FakeRepo(),
            provider_boundary=boundary,
        )
        request = LabDraftGenerationRequest(
            user_prompt="timeout lab", requester_user_id="admin"
        )
        with pytest.raises(DraftGenerationRejected):
            svc.generate_and_create(request)

    def test_provider_disabled_raises_draft_generation_rejected(self):
        from backend.labgen.llm_generation import (
            DraftGenerationRejected,
            LabDraftGenerationRequest,
            LabDraftGenerationService,
            FakeDraftGenerationAdapter,
        )
        from backend.labgen.llm_provider_boundary import (
            DryRunLLMProviderAdapter,
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.static_validator import StaticValidator

        class _FakeRepo(LabDraftRepository):
            def __init__(self):
                pass

        boundary = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
            dry_run_adapter=DryRunLLMProviderAdapter(inject_mode="provider_disabled"),
        )
        svc = LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=_FakeRepo(),
            provider_boundary=boundary,
        )
        request = LabDraftGenerationRequest(
            user_prompt="disabled lab", requester_user_id="admin"
        )
        with pytest.raises(DraftGenerationRejected):
            svc.generate_and_create(request)

    def test_provider_failure_does_not_corrupt_repo_on_error(self):
        """When provider raises, repo.create must not have been called."""
        from backend.labgen.llm_generation import (
            DraftGenerationRejected,
            LabDraftGenerationRequest,
            LabDraftGenerationService,
            FakeDraftGenerationAdapter,
        )
        from backend.labgen.llm_provider_boundary import (
            DryRunLLMProviderAdapter,
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
        )
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.static_validator import StaticValidator

        created = []

        class _SpyRepo(LabDraftRepository):
            def __init__(self):
                pass

            def create(self, draft):
                created.append(draft)
                return draft

        boundary = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
            dry_run_adapter=DryRunLLMProviderAdapter(inject_mode="timeout"),
        )
        svc = LabDraftGenerationService(
            port=FakeDraftGenerationAdapter(),
            validator=StaticValidator(),
            repo=_SpyRepo(),
            provider_boundary=boundary,
        )
        with pytest.raises(DraftGenerationRejected):
            svc.generate_and_create(
                LabDraftGenerationRequest(
                    user_prompt="timeout lab", requester_user_id="admin"
                )
            )
        assert len(created) == 0, "repo.create must not be called on provider timeout"


# ---------------------------------------------------------------------------
# E. Sanitizer / raw output prohibition
# ---------------------------------------------------------------------------


class TestSanitizerCoverage:
    def test_redact_removes_bearer_token(self):
        from backend.labgen.llm_provider_boundary import _redact

        raw = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.fake.payload"
        result = _redact(raw)
        assert "Bearer" not in result or "[REDACTED]" in result

    def test_redact_removes_api_key_pattern(self):
        from backend.labgen.llm_provider_boundary import _redact

        raw = "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"
        result = _redact(raw)
        assert "sk-" not in result

    def test_redact_removes_jwt(self):
        from backend.labgen.llm_provider_boundary import _redact

        raw = "token: eyJhbGciOiJSUzI1NiJ9.somePayload.signatureHere"
        result = _redact(raw)
        assert "eyJ" not in result

    def test_redact_removes_password_assignment(self):
        from backend.labgen.llm_provider_boundary import _redact

        raw = "password=hunter2 in context window"
        result = _redact(raw)
        assert "hunter2" not in result

    def test_redact_warnings_all_strings_cleaned(self):
        from backend.labgen.llm_provider_boundary import _redact_warnings

        raw = [
            "ok message",
            "token=eyJhbGciOiJSUzI1NiJ9.fake.payload leak",
            "another ok",
        ]
        cleaned = _redact_warnings(raw)
        assert cleaned[0] == "ok message"
        assert "eyJ" not in cleaned[1]
        assert cleaned[2] == "another ok"

    def test_sensitive_output_mode_redacted_by_service(self):
        """BoundaryService must redact sensitive-looking dry-run warnings."""
        from backend.labgen.llm_provider_boundary import (
            DryRunLLMProviderAdapter,
            LLMProviderBoundaryService,
            LLMProviderConfig,
            LLMProviderMode,
            LLMProviderRequest,
        )

        svc = LLMProviderBoundaryService(
            config=LLMProviderConfig(mode=LLMProviderMode.DRY_RUN),
            dry_run_adapter=DryRunLLMProviderAdapter(inject_mode="sensitive_output"),
        )
        resp = svc.call(
            LLMProviderRequest(
                purpose="draft_generation",
                sanitized_user_prompt="sensitive test",
            )
        )
        joined = " ".join(resp.warnings)
        assert "sk-" not in joined
        assert "eyJ" not in joined


# ---------------------------------------------------------------------------
# F. LLMProviderRequest validation
# ---------------------------------------------------------------------------


class TestLLMProviderRequestValidation:
    def test_valid_request_accepted(self):
        from backend.labgen.llm_provider_boundary import LLMProviderRequest

        req = LLMProviderRequest(
            purpose="draft_generation",
            sanitized_user_prompt="k8s networking lab",
        )
        assert req.purpose == "draft_generation"

    def test_invalid_purpose_rejected(self):
        from pydantic import ValidationError

        from backend.labgen.llm_provider_boundary import LLMProviderRequest

        with pytest.raises(ValidationError):
            LLMProviderRequest(
                purpose="publish_draft",
                sanitized_user_prompt="k8s lab",
            )

    def test_prompt_too_long_rejected(self):
        from pydantic import ValidationError

        from backend.labgen.llm_provider_boundary import LLMProviderRequest

        with pytest.raises(ValidationError):
            LLMProviderRequest(
                purpose="draft_generation",
                sanitized_user_prompt="x" * 2001,
            )

    def test_repair_purpose_accepted(self):
        from backend.labgen.llm_provider_boundary import LLMProviderRequest

        req = LLMProviderRequest(
            purpose="draft_repair",
            sanitized_user_prompt="repair this draft",
        )
        assert req.purpose == "draft_repair"


# ---------------------------------------------------------------------------
# G. Regression: existing generate/repair tests still pass
# ---------------------------------------------------------------------------


class TestRegressionDefaultGeneration:
    """Default (no boundary) generate path must be unchanged."""

    def test_fake_adapter_valid_mode_produces_draft(self):
        from backend.labgen.llm_generation import (
            FakeDraftGenerationAdapter,
            LabDraftGenerationRequest,
        )

        adapter = FakeDraftGenerationAdapter(inject_mode="valid")
        request = LabDraftGenerationRequest(
            user_prompt="regression test", requester_user_id="tester"
        )
        result = adapter.generate_lab_draft_candidate(request)
        assert result.rejected_reason is None
        assert result.candidate

    def test_fake_adapter_rejected_mode(self):
        from backend.labgen.llm_generation import (
            FakeDraftGenerationAdapter,
            LabDraftGenerationRequest,
        )

        adapter = FakeDraftGenerationAdapter(inject_mode="rejected")
        request = LabDraftGenerationRequest(
            user_prompt="test", requester_user_id="tester"
        )
        result = adapter.generate_lab_draft_candidate(request)
        assert result.rejected_reason is not None
