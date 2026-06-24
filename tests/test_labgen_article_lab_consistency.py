"""
G-60: Article-Lab Content Consistency tests.

Covers:
  A. topic_consistency.py — keyword matching logic
  B. StaticValidator — article_lab_topic_consistency check
  C. Step command / verifier consistency for Linux lab (step 3 specifically)
  D. CTA response includes topic_consistency_warning field
  E. Real Linux lab data: article binding matches lab domain
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

import pytest

from backend.labgen.topic_consistency import check_article_lab_consistency

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# A. topic_consistency.py — keyword matching
# ---------------------------------------------------------------------------


class TestTopicConsistencyKeywords:
    def test_linux_title_matches_linux_domain(self) -> None:
        result = check_article_lab_consistency(
            target_domain="linux",
            article_title="Linux 文件与权限基础：创建、查看并修改权限",
            article_url=None,
        )
        assert result is None

    def test_linux_title_chmod_matches_linux(self) -> None:
        result = check_article_lab_consistency(
            target_domain="linux",
            article_title="Understanding chmod and file permissions",
            article_url=None,
        )
        assert result is None

    def test_linux_title_shell_matches_linux(self) -> None:
        result = check_article_lab_consistency(
            target_domain="linux",
            article_title="Shell scripting basics",
            article_url=None,
        )
        assert result is None

    def test_linux_url_slug_matches_linux(self) -> None:
        result = check_article_lab_consistency(
            target_domain="linux",
            article_title=None,
            article_url="https://lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics",
        )
        assert result is None

    def test_k8s_title_matches_k8s_domain(self) -> None:
        result = check_article_lab_consistency(
            target_domain="k8s",
            article_title="Kubernetes 多层 Web 应用容器化部署",
            article_url=None,
        )
        assert result is None

    def test_k8s_pod_keyword_matches_k8s(self) -> None:
        result = check_article_lab_consistency(
            target_domain="k8s",
            article_title="Getting started with Pod and Deployment",
            article_url=None,
        )
        assert result is None

    def test_k8s_article_to_linux_domain_returns_warning(self) -> None:
        result = check_article_lab_consistency(
            target_domain="linux",
            article_title="欢迎来到 K8S NetLab",
            article_url="https://lab.cloudnetops.tech/article.html?slug=welcome-to-k8s-netlab",
        )
        assert result is not None
        assert "k8s" in result.lower() or "linux" in result.lower()

    def test_linux_article_to_k8s_domain_returns_warning(self) -> None:
        result = check_article_lab_consistency(
            target_domain="k8s",
            article_title="Linux chmod 权限详解",
            article_url=None,
        )
        assert result is not None

    def test_no_article_bound_returns_none(self) -> None:
        result = check_article_lab_consistency(
            target_domain="linux",
            article_title=None,
            article_url=None,
        )
        assert result is None

    def test_unknown_domain_returns_none(self) -> None:
        result = check_article_lab_consistency(
            target_domain="docker",
            article_title="Some article",
            article_url=None,
        )
        assert result is None

    def test_empty_domain_returns_none(self) -> None:
        result = check_article_lab_consistency(
            target_domain=None,
            article_title="Some article",
            article_url=None,
        )
        assert result is None

    def test_case_insensitive_keyword_match(self) -> None:
        result = check_article_lab_consistency(
            target_domain="linux",
            article_title="LINUX File Permissions Guide",
            article_url=None,
        )
        assert result is None

    def test_generic_unrecognized_title_returns_warning(self) -> None:
        result = check_article_lab_consistency(
            target_domain="linux",
            article_title="Getting started with cloud computing",
            article_url=None,
        )
        assert result is not None
        assert "linux" in result.lower()


# ---------------------------------------------------------------------------
# B. StaticValidator — article_lab_topic_consistency check
# ---------------------------------------------------------------------------


class TestStaticValidatorConsistency:
    def _make_linux_draft_with_article(
        self,
        article_title: Optional[str] = None,
        article_url: Optional[str] = None,
    ):
        from backend.labgen.models import (
            BlockingLevel,
            ExplainField,
            LabDomainType,
            LabDraft,
            LinuxSandboxPolicy,
            LinuxVerifyTemplate,
            LinuxVerifyType,
            PublishStatus,
            RuntimeRequirements,
            Step,
            ValidatorResult,
            ValidatorStatus,
        )
        step = Step(
            step_id="s1",
            order=1,
            why="why",
            do="do",
            observe="obs",
            explain=ExplainField(concept="c", observation="o"),
            linux_verify=[
                LinuxVerifyTemplate(
                    verify_id="v1",
                    type=LinuxVerifyType.LINUX_FILE_EXISTS,
                    target_path="demo/file.txt",
                ),
            ],
        )
        return LabDraft(
            source_article_id="art-test",
            title="Linux Files and Permissions",
            description="A Linux test lab",
            estimated_duration_minutes=10,
            target_domain=LabDomainType.LINUX,
            runtime_requirements=RuntimeRequirements(),
            steps=[step],
            linux_sandbox_policy=LinuxSandboxPolicy(runtime_type="linux_sandbox"),
            publish_status=PublishStatus.PUBLISHED,
            validator_results=[ValidatorResult(
                check_id="content.no_placeholders",
                blocking_level=BlockingLevel.PUBLISH_BLOCKING,
                field_path="",
                status=ValidatorStatus.PASSED,
                message="ok",
            )],
            article_title=article_title,
            article_url=article_url,
        )

    def test_matching_article_produces_pass(self) -> None:
        from backend.labgen.static_validator import StaticValidator
        draft = self._make_linux_draft_with_article(
            article_title="Linux 文件与权限基础",
        )
        results = StaticValidator().validate(draft)
        consistency = [r for r in results if r.check_id == "content.article_lab_topic_consistency"]
        assert len(consistency) == 1
        assert consistency[0].status.value == "passed"

    def test_mismatched_article_produces_draft_warning(self) -> None:
        from backend.labgen.models import BlockingLevel, ValidatorStatus
        from backend.labgen.static_validator import StaticValidator
        draft = self._make_linux_draft_with_article(
            article_title="欢迎来到 K8S NetLab",
            article_url="https://lab.cloudnetops.tech/article.html?slug=welcome-to-k8s-netlab",
        )
        results = StaticValidator().validate(draft)
        consistency = [r for r in results if r.check_id == "content.article_lab_topic_consistency"]
        assert len(consistency) == 1
        assert consistency[0].status == ValidatorStatus.FAILED
        assert consistency[0].blocking_level == BlockingLevel.DRAFT_WARNING

    def test_no_article_bound_produces_pass(self) -> None:
        from backend.labgen.static_validator import StaticValidator
        draft = self._make_linux_draft_with_article()
        results = StaticValidator().validate(draft)
        consistency = [r for r in results if r.check_id == "content.article_lab_topic_consistency"]
        assert len(consistency) == 1
        assert consistency[0].status.value == "passed"

    def test_draft_warning_does_not_block_publish(self) -> None:
        """article_lab_topic_consistency is draft_warning — must not prevent publish."""
        from backend.labgen.models import BlockingLevel, PublishStatus, ValidatorStatus
        from backend.labgen.static_validator import StaticValidator
        draft = self._make_linux_draft_with_article(
            article_title="欢迎来到 K8S NetLab",
        )
        results = StaticValidator().validate(draft)
        # No publish_blocking failures from the consistency check
        blocking = [
            r for r in results
            if r.check_id == "content.article_lab_topic_consistency"
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
        ]
        assert blocking == []


# ---------------------------------------------------------------------------
# C. Step command / verifier consistency for Linux lab
# ---------------------------------------------------------------------------


LINUX_LAB_ID = "6c439064-4cad-4229-addb-36927128d565"


class TestLinuxLabStepVerifierConsistency:
    @pytest.fixture
    def linux_lab(self):
        from backend.labgen.models import LabDraft
        with open("data/lab_drafts.json") as f:
            raw = json.load(f)
        return LabDraft.model_validate(raw[LINUX_LAB_ID])

    def test_step3_command_uses_chmod_600(self, linux_lab) -> None:
        step3 = next(s for s in linux_lab.steps if s.step_id == "lfp-step-3")
        chmod_cmds = [c for c in step3.commands if "chmod" in c]
        assert chmod_cmds, "step 3 must have a chmod command"
        for cmd in chmod_cmds:
            assert "600" in cmd, f"chmod command must use 600, got: {cmd}"
            assert "644" not in cmd, f"chmod must not reference 644, got: {cmd}"

    def test_step3_verifier_expects_600(self, linux_lab) -> None:
        step3 = next(s for s in linux_lab.steps if s.step_id == "lfp-step-3")
        modes = [v.expected_mode for v in step3.linux_verify if v.expected_mode is not None]
        assert modes, "step 3 must have at least one mode verifier"
        for mode in modes:
            assert mode == "600", f"verifier expected_mode must be 600, got: {mode}"

    def test_step3_do_field_consistent_with_verifier(self, linux_lab) -> None:
        step3 = next(s for s in linux_lab.steps if s.step_id == "lfp-step-3")
        # do field must reference 600, not 644
        if step3.do:
            assert "644" not in step3.do, f"step 3 do field must not mention 644, got: {step3.do}"

    def test_step3_observe_consistent_with_verifier(self, linux_lab) -> None:
        step3 = next(s for s in linux_lab.steps if s.step_id == "lfp-step-3")
        if step3.observe:
            # observe should reference 600 as the expected output
            assert "600" in step3.observe, f"step 3 observe must reference expected output 600"

    def test_all_steps_verifier_types_are_linux_domain(self, linux_lab) -> None:
        from backend.labgen.models import LinuxVerifyType
        for step in linux_lab.steps:
            for v in step.linux_verify:
                assert isinstance(v.type, LinuxVerifyType), (
                    f"step {step.step_id} verifier {v.verify_id} must be LinuxVerifyType"
                )

    def test_step3_no_verify_k8s_templates(self, linux_lab) -> None:
        """Linux step must not have K8s verify templates mixed in."""
        step3 = next(s for s in linux_lab.steps if s.step_id == "lfp-step-3")
        assert step3.verify == [], "step 3 must not have K8s verify templates"


# ---------------------------------------------------------------------------
# D. CTA response includes topic_consistency_warning
# ---------------------------------------------------------------------------


class TestCTATopicConsistencyWarning:
    def _make_draft(self, article_title=None, article_url=None, domain="linux"):
        from backend.labgen.models import (
            BlockingLevel,
            ExplainField,
            LabDomainType,
            LabDraft,
            LinuxSandboxPolicy,
            LinuxVerifyTemplate,
            LinuxVerifyType,
            PublishStatus,
            RuntimeRequirements,
            Step,
            ValidatorResult,
            ValidatorStatus,
        )
        step = Step(
            step_id="s1",
            order=1,
            why="why",
            do="do",
            observe="obs",
            explain=ExplainField(concept="c", observation="o"),
            linux_verify=[
                LinuxVerifyTemplate(
                    verify_id="v1",
                    type=LinuxVerifyType.LINUX_FILE_EXISTS,
                    target_path="f",
                ),
            ],
        )
        return LabDraft(
            source_article_id="art-test",
            title="Lab Title",
            description="desc",
            estimated_duration_minutes=10,
            target_domain=LabDomainType(domain),
            runtime_requirements=RuntimeRequirements(),
            steps=[step],
            linux_sandbox_policy=LinuxSandboxPolicy(runtime_type="linux_sandbox"),
            publish_status=PublishStatus.PUBLISHED,
            cta_enabled=True,
            article_title=article_title,
            article_url=article_url,
        )

    def _make_cta(self, draft):
        from backend.labgen.routes import _build_cta
        return _build_cta(draft)

    def test_cta_has_no_warning_for_matching_article(self) -> None:
        draft = self._make_draft(
            article_title="Linux 文件与权限基础",
            article_url=None,
        )
        cta = self._make_cta(draft)
        assert cta.topic_consistency_warning is None

    def test_cta_has_warning_for_mismatched_article(self) -> None:
        draft = self._make_draft(
            article_title="欢迎来到 K8S NetLab",
            article_url="https://lab.cloudnetops.tech/article.html?slug=welcome-to-k8s-netlab",
        )
        cta = self._make_cta(draft)
        assert cta.topic_consistency_warning is not None
        assert len(cta.topic_consistency_warning) > 20

    def test_cta_has_no_warning_when_no_article(self) -> None:
        draft = self._make_draft()
        cta = self._make_cta(draft)
        assert cta.topic_consistency_warning is None

    def test_cta_warning_field_in_response_model(self) -> None:
        """LabDraftCTAResponse must have topic_consistency_warning field."""
        from backend.labgen.routes import LabDraftCTAResponse
        fields = LabDraftCTAResponse.model_fields
        assert "topic_consistency_warning" in fields

    def test_cta_still_includes_all_other_fields(self) -> None:
        draft = self._make_draft(
            article_title="Linux 文件基础",
        )
        cta = self._make_cta(draft)
        assert cta.plain_cta
        assert cta.markdown_cta
        assert cta.html_cta
        assert cta.copyable_text
        assert cta.deep_link


# ---------------------------------------------------------------------------
# E. Real Linux lab: article binding matches lab domain
# ---------------------------------------------------------------------------


class TestLinuxLabArticleBinding:
    @pytest.fixture
    def linux_lab(self):
        from backend.labgen.models import LabDraft
        with open("data/lab_drafts.json") as f:
            raw = json.load(f)
        return LabDraft.model_validate(raw[LINUX_LAB_ID])

    def test_linux_lab_has_article_url(self, linux_lab) -> None:
        assert linux_lab.article_url is not None
        assert linux_lab.article_url.startswith("https://")

    def test_linux_lab_article_url_not_k8s_welcome(self, linux_lab) -> None:
        """Must not still point to the K8s welcome article."""
        assert "welcome-to-k8s-netlab" not in (linux_lab.article_url or ""), (
            "article_url must not reference welcome-to-k8s-netlab (K8s article on Linux lab)"
        )

    def test_linux_lab_article_topic_matches_lab_domain(self, linux_lab) -> None:
        warning = check_article_lab_consistency(
            target_domain="linux",
            article_title=linux_lab.article_title,
            article_url=linux_lab.article_url,
        )
        assert warning is None, (
            f"article should match linux domain but got warning: {warning}"
        )

    def test_linux_lab_cta_enabled(self, linux_lab) -> None:
        assert linux_lab.cta_enabled is True

    def test_linux_lab_article_channel_valid(self, linux_lab) -> None:
        valid_channels = {"official_site", "wechat", "zhihu", "csdn", "github", "other"}
        if linux_lab.article_channel:
            assert linux_lab.article_channel in valid_channels
