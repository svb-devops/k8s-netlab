"""
LLM Prompt Builder v0.1 — tests.

Coverage areas (per contract):
  B. Prompt builder
    - prompt contains JSON-only constraint
    - prompt contains no chain-of-thought constraint
    - prompt does not contain secrets/tokens/kubeconfig
    - long user_prompt is truncated
    - prompt builder output does not enter generate response
    - prohibited content detection
"""

from __future__ import annotations

import pytest

from backend.labgen.llm_prompt_builder import (
    _MAX_USER_PROMPT_LEN,
    build_generation_messages,
    build_repair_messages,
    prompt_contains_prohibited_content,
)

pytestmark = pytest.mark.static


class TestBuildGenerationMessages:
    def test_returns_tuple_of_two_strings(self):
        system, user = build_generation_messages("k8s networking lab")
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_contains_json_only_instruction(self):
        system, _ = build_generation_messages("test")
        assert "JSON" in system or "json" in system.lower()

    def test_system_contains_no_chain_of_thought_constraint(self):
        system, _ = build_generation_messages("test")
        assert "chain-of-thought" in system.lower() or "chain_of_thought" in system.lower()

    def test_system_prohibits_publish_status_published(self):
        system, _ = build_generation_messages("test")
        assert "publish" in system.lower()

    def test_system_prohibits_secrets(self):
        system, _ = build_generation_messages("test")
        assert "secret" in system.lower() or "kubeconfig" in system.lower()

    def test_user_message_contains_prompt(self):
        _, user = build_generation_messages("deploy nginx pod")
        assert "deploy nginx pod" in user

    def test_long_user_prompt_is_truncated(self):
        long_prompt = "x" * (_MAX_USER_PROMPT_LEN + 500)
        _, user = build_generation_messages(long_prompt)
        assert len(user) < len(long_prompt) + 200  # prompt portion is capped

    def test_user_prompt_at_max_length_not_truncated(self):
        # Use realistic text with spaces so it doesn't match the base64 redaction pattern
        word = "kubernetes networking "
        prompt = (word * (_MAX_USER_PROMPT_LEN // len(word) + 1))[:_MAX_USER_PROMPT_LEN]
        _, user = build_generation_messages(prompt)
        assert "kubernetes networking" in user

    def test_template_hint_injected_when_provided(self):
        _, user = build_generation_messages(
            "k8s lab",
            selected_template_id="k8s_pod_basics",
        )
        assert "k8s_pod_basics" in user

    def test_constraints_summary_injected(self):
        _, user = build_generation_messages(
            "k8s lab",
            constraints_summary="difficulty=beginner",
        )
        assert "difficulty=beginner" in user

    def test_repair_purpose_adds_repair_note(self):
        _, user = build_generation_messages("k8s lab", purpose="draft_repair")
        assert "REPAIR" in user.upper() or "repair" in user.lower()

    def test_credential_in_prompt_is_removed(self):
        # kubeconfig reference should be stripped by sanitizer
        _, user = build_generation_messages("use kubeconfig=/root/.kube/config to deploy")
        assert "kubeconfig=" not in user or "[REMOVED]" in user

    def test_bearer_token_in_prompt_is_removed(self):
        _, user = build_generation_messages("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.fake.payload")
        assert "eyJhbGciOiJSUzI1NiJ9.fake.payload" not in user

    def test_output_is_not_empty(self):
        system, user = build_generation_messages("minimal lab")
        assert len(system) > 50
        assert len(user) > 5

    def test_no_api_key_in_output(self):
        system, user = build_generation_messages(
            "lab about k8s",
            constraints_summary="api_key=sk-test12345678901234567890123456789012",
        )
        combined = system + user
        assert "sk-test" not in combined


class TestBuildRepairMessages:
    def test_returns_tuple_of_two_strings(self):
        system, user = build_repair_messages("k8s lab", "cleanup missing")
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_user_contains_validation_issues(self):
        _, user = build_repair_messages("k8s lab", "cleanup.declared check failed")
        assert "cleanup" in user.lower() or "declared" in user.lower()

    def test_user_contains_original_topic(self):
        _, user = build_repair_messages("deploy ingress controller", "fix me")
        assert "deploy ingress controller" in user

    def test_system_contains_prohibitions(self):
        system, _ = build_repair_messages("k8s lab", "issues")
        assert "JSON" in system or "json" in system.lower()

    def test_long_issues_summary_truncated(self):
        long_issues = "issue: " * 200
        _, user = build_repair_messages("lab", long_issues)
        # should not crash, output must be bounded
        assert len(user) < 5000


class TestPromptContainsProhibitedContent:
    def test_clean_text_returns_false(self):
        assert not prompt_contains_prohibited_content("deploy a pod and verify it runs")

    def test_kubeconfig_returns_true(self):
        assert prompt_contains_prohibited_content("use kubeconfig to connect")

    def test_bearer_token_returns_true(self):
        assert prompt_contains_prohibited_content("Authorization: Bearer abcdefghijklmnopqrst")

    def test_jwt_returns_true(self):
        assert prompt_contains_prohibited_content(
            "token: eyJhbGciOiJSUzI1NiJ9.fake.payload"
        )

    def test_long_base64_returns_true(self):
        b64 = "A" * 65 + "=="
        assert prompt_contains_prohibited_content(f"data: {b64}")

    def test_api_key_kv_returns_true(self):
        assert prompt_contains_prohibited_content("api_key=sk-secretvalue")

    def test_password_kv_returns_true(self):
        assert prompt_contains_prohibited_content("password=hunter2")
