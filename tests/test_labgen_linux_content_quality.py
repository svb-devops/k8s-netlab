"""
G-48: Linux Content Quality Iteration — regression tests.

Validates:
  A. Model schema: troubleshoot, experiment_background, completion_summary optional fields
  B. Learner catalog API: experiment_background + completion_summary in LearnerLabDetail
  C. check_count: includes linux_verify count for Linux domain labs
  D. Session snapshot: step_troubleshoot for current step
  E. Backward compat: existing K8s labs unaffected
  F. Content fill: Linux lab draft has non-empty quality fields
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest

from backend.labgen.learner_catalog import LearnerCatalogService, LearnerLabDetail
from backend.labgen.learner_session_snapshot import _build_step_statuses
from backend.labgen.models import (
    BlockingLevel,
    ExplainField,
    LabDraft,
    LabDomainType,
    LabSessionState,
    LabSessionStatus,
    LinuxSandboxPolicy,
    LinuxVerifyTemplate,
    LinuxVerifyType,
    PublishStatus,
    RuntimeRequirements,
    Step,
    ValidatorResult,
    ValidatorStatus,
)
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _linux_policy() -> LinuxSandboxPolicy:
    return LinuxSandboxPolicy(runtime_type="linux_sandbox")


def _make_step(
    step_id: str = "s1",
    order: int = 1,
    troubleshoot: str = "",
    linux_verify: list | None = None,
) -> Step:
    return Step(
        step_id=step_id,
        order=order,
        why=f"why for {step_id}",
        do=f"do for {step_id}",
        observe=f"observe for {step_id}",
        explain=ExplainField(concept="c", observation="o"),
        troubleshoot=troubleshoot,
        linux_verify=linux_verify or [],
    )


def _make_linux_draft(
    experiment_background: str = "",
    completion_summary: str = "",
    steps: list[Step] | None = None,
) -> LabDraft:
    if steps is None:
        steps = [_make_step()]
    return LabDraft(
        source_article_id="art-test",
        title="Linux Test Lab",
        description="A Linux test lab",
        estimated_duration_minutes=10,
        target_domain=LabDomainType.LINUX,
        runtime_requirements=RuntimeRequirements(),
        steps=steps,
        linux_sandbox_policy=_linux_policy(),
        experiment_background=experiment_background,
        completion_summary=completion_summary,
        publish_status=PublishStatus.PUBLISHED,
        validator_results=[ValidatorResult(
            check_id="content.no_placeholders",
            blocking_level=BlockingLevel.PUBLISH_BLOCKING,
            field_path="",
            status=ValidatorStatus.PASSED,
            message="ok",
        )],
    )


class _MemDraftRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def get(self, lab_id: str):
        return self._store.get(lab_id)

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


def _svc(repo: _MemDraftRepo) -> LearnerCatalogService:
    return LearnerCatalogService(repo, StaticValidator())


def _make_active_session(lab: LabDraft, username: str = "learner") -> LabSessionState:
    return LabSessionState(
        session_id=str(uuid.uuid4()),
        lab_id=lab.lab_id,
        student_username=username,
        vm_id="linux-sandbox",
        lab_session_status=LabSessionStatus.LAB_ACTIVE,
        current_step_index=0,
    )


# ---------------------------------------------------------------------------
# A. Model schema
# ---------------------------------------------------------------------------


class TestModelSchema:
    def test_step_has_troubleshoot_field(self) -> None:
        s = _make_step(troubleshoot="If stuck, try rerunning the command.")
        assert s.troubleshoot == "If stuck, try rerunning the command."

    def test_step_troubleshoot_defaults_to_empty(self) -> None:
        s = Step(
            step_id="s1",
            order=1,
            why="why",
            do="do",
            observe="obs",
            explain=ExplainField(concept="c", observation="o"),
        )
        assert s.troubleshoot == ""

    def test_draft_has_experiment_background_field(self) -> None:
        d = _make_linux_draft(experiment_background="Linux is the kernel powering most servers.")
        assert d.experiment_background == "Linux is the kernel powering most servers."

    def test_draft_has_completion_summary_field(self) -> None:
        d = _make_linux_draft(completion_summary="You created, read, and protected a file.")
        assert d.completion_summary == "You created, read, and protected a file."

    def test_experiment_background_defaults_to_empty(self) -> None:
        d = _make_linux_draft()
        assert d.experiment_background == ""

    def test_completion_summary_defaults_to_empty(self) -> None:
        d = _make_linux_draft()
        assert d.completion_summary == ""

    def test_k8s_draft_still_deserializes_without_new_fields(self) -> None:
        """Existing K8s draft dicts without new fields must round-trip cleanly."""
        raw = {
            "schema_version": "1.0",
            "lab_id": str(uuid.uuid4()),
            "source_article_id": "art-001",
            "title": "K8s Test",
            "description": "desc",
            "estimated_duration_minutes": 10,
            "target_domain": "k8s",
            "runtime_requirements": {"schema_version": "1.0"},
            "steps": [{
                "schema_version": "1.0",
                "step_id": "s1",
                "order": 1,
                "why": "why",
                "do": "do",
                "observe": "obs",
                "explain": {"schema_version": "1.0", "concept": "c", "observation": "o"},
                "verify": [],
                "linux_verify": [],
            }],
            "publish_status": "published",
        }
        draft = LabDraft.model_validate(raw)
        assert draft.experiment_background == ""
        assert draft.completion_summary == ""
        assert draft.steps[0].troubleshoot == ""


# ---------------------------------------------------------------------------
# B. Learner catalog API: experiment_background + completion_summary
# ---------------------------------------------------------------------------


class TestLearnerCatalogNewFields:
    def test_experiment_background_in_lab_detail(self) -> None:
        repo = _MemDraftRepo()
        draft = _make_linux_draft(experiment_background="Linux powers servers worldwide.")
        repo.create(draft)
        detail = _svc(repo).get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.experiment_background == "Linux powers servers worldwide."

    def test_completion_summary_in_lab_detail(self) -> None:
        repo = _MemDraftRepo()
        draft = _make_linux_draft(completion_summary="You completed the lab successfully.")
        repo.create(draft)
        detail = _svc(repo).get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.completion_summary == "You completed the lab successfully."

    def test_empty_fields_are_none_in_response(self) -> None:
        """Empty string fields become None in the learner response (cleaner API)."""
        repo = _MemDraftRepo()
        draft = _make_linux_draft(experiment_background="", completion_summary="")
        repo.create(draft)
        detail = _svc(repo).get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.experiment_background is None
        assert detail.completion_summary is None

    def test_credential_patterns_redacted_in_new_fields(self) -> None:
        """sanitize_text redacts token-like patterns from experiment_background."""
        repo = _MemDraftRepo()
        draft = _make_linux_draft(
            experiment_background="Background. token=eyJhbGciOiJSUzI1NiJ9.payload.sig",
        )
        repo.create(draft)
        detail = _svc(repo).get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.experiment_background is not None
        # JWT-like string should be redacted
        assert "eyJhbGciOiJSUzI1NiJ9" not in detail.experiment_background


# ---------------------------------------------------------------------------
# C. check_count includes linux_verify
# ---------------------------------------------------------------------------


class TestCheckCountLinuxVerify:
    def test_check_count_for_linux_step_uses_linux_verify(self) -> None:
        repo = _MemDraftRepo()
        step = _make_step(
            linux_verify=[
                LinuxVerifyTemplate(
                    verify_id="v1",
                    type=LinuxVerifyType.LINUX_DIRECTORY_EXISTS,
                    target_path="demo",
                ),
                LinuxVerifyTemplate(
                    verify_id="v2",
                    type=LinuxVerifyType.LINUX_FILE_EXISTS,
                    target_path="demo/file.txt",
                ),
            ],
        )
        draft = _make_linux_draft(steps=[step])
        repo.create(draft)
        detail = _svc(repo).get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.steps_preview[0].check_count == 2

    def test_check_count_combines_verify_and_linux_verify(self) -> None:
        """Step with both K8s and Linux verifiers: count = sum of both."""
        from backend.labgen.models import VerifyTemplate, VerifyType
        repo = _MemDraftRepo()
        step = Step(
            step_id="s1",
            order=1,
            why="why",
            do="do",
            observe="obs",
            explain=ExplainField(concept="c", observation="o"),
            verify=[VerifyTemplate(verify_id="kv1", type=VerifyType.POD_RUNNING, name="nginx")],
            linux_verify=[
                LinuxVerifyTemplate(verify_id="lv1", type=LinuxVerifyType.LINUX_FILE_EXISTS, target_path="f"),
            ],
        )
        draft = _make_linux_draft(steps=[step])
        repo.create(draft)
        detail = _svc(repo).get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.steps_preview[0].check_count == 2

    def test_check_count_k8s_step_unchanged(self) -> None:
        """K8s steps with only verify templates: check_count = len(verify)."""
        from backend.labgen.models import VerifyTemplate, VerifyType
        repo = _MemDraftRepo()
        step = Step(
            step_id="s1",
            order=1,
            why="why",
            do="do",
            observe="obs",
            explain=ExplainField(concept="c", observation="o"),
            verify=[
                VerifyTemplate(verify_id="v1", type=VerifyType.POD_RUNNING, name="nginx"),
                VerifyTemplate(verify_id="v2", type=VerifyType.SERVICE_EXISTS, name="svc"),
            ],
        )
        draft = LabDraft(
            source_article_id="art",
            title="K8s Lab",
            description="desc",
            estimated_duration_minutes=10,
            runtime_requirements=RuntimeRequirements(),
            steps=[step],
            publish_status=PublishStatus.PUBLISHED,
            validator_results=[ValidatorResult(
                check_id="content.no_placeholders",
                blocking_level=BlockingLevel.PUBLISH_BLOCKING,
                field_path="",
                status=ValidatorStatus.PASSED,
                message="ok",
            )],
        )
        repo.create(draft)
        detail = _svc(repo).get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.steps_preview[0].check_count == 2


# ---------------------------------------------------------------------------
# D. Session snapshot: step_troubleshoot
# ---------------------------------------------------------------------------


class TestSessionSnapshotTroubleshoot:
    def test_step_troubleshoot_present_for_current_step(self) -> None:
        step = _make_step(step_id="s1", troubleshoot="If stuck, check the path.")
        draft = _make_linux_draft(steps=[step])
        session = _make_active_session(draft)

        _, statuses = _build_step_statuses(session, draft.steps)

        current = next(s for s in statuses if s.is_current)
        assert current.step_troubleshoot == "If stuck, check the path."

    def test_step_troubleshoot_none_for_passed_steps(self) -> None:
        step1 = _make_step(step_id="s1", troubleshoot="Hint for step 1.")
        step2 = _make_step(step_id="s2", order=2, troubleshoot="Hint for step 2.")
        draft = _make_linux_draft(steps=[step1, step2])
        session = _make_active_session(draft)
        session.completed_step_ids = ["s1"]
        session.current_step_index = 1

        _, statuses = _build_step_statuses(session, draft.steps)

        passed = next(s for s in statuses if s.step_id == "s1")
        assert passed.step_troubleshoot is None

    def test_step_troubleshoot_none_for_locked_steps(self) -> None:
        step1 = _make_step(step_id="s1", troubleshoot="Hint 1.")
        step2 = _make_step(step_id="s2", order=2, troubleshoot="Hint 2.")
        draft = _make_linux_draft(steps=[step1, step2])
        session = _make_active_session(draft)

        _, statuses = _build_step_statuses(session, draft.steps)

        locked = next(s for s in statuses if s.step_id == "s2")
        assert locked.step_troubleshoot is None

    def test_step_troubleshoot_empty_string_becomes_none(self) -> None:
        step = _make_step(step_id="s1", troubleshoot="")
        draft = _make_linux_draft(steps=[step])
        session = _make_active_session(draft)

        _, statuses = _build_step_statuses(session, draft.steps)

        current = next(s for s in statuses if s.is_current)
        assert current.step_troubleshoot is None

    def test_step_troubleshoot_credential_redacted(self) -> None:
        """sanitize_text redacts credential-like patterns from troubleshoot hints."""
        step = _make_step(
            step_id="s1",
            troubleshoot="Hint. token=eyJhbGciOiJSUzI1NiJ9.payload.sig",
        )
        draft = _make_linux_draft(steps=[step])
        session = _make_active_session(draft)

        _, statuses = _build_step_statuses(session, draft.steps)

        current = next(s for s in statuses if s.is_current)
        assert current.step_troubleshoot is not None
        assert "eyJhbGciOiJSUzI1NiJ9" not in current.step_troubleshoot


# ---------------------------------------------------------------------------
# E. Backward compat: existing K8s lab snapshots unaffected
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_k8s_step_troubleshoot_defaults_to_none_in_snapshot(self) -> None:
        step = Step(
            step_id="s1",
            order=1,
            why="why",
            do="do",
            observe="obs",
            explain=ExplainField(concept="c", observation="o"),
        )
        draft = LabDraft(
            source_article_id="art",
            title="K8s Lab",
            description="desc",
            estimated_duration_minutes=10,
            runtime_requirements=RuntimeRequirements(),
            steps=[step],
            publish_status=PublishStatus.PUBLISHED,
        )
        session = LabSessionState(
            session_id=str(uuid.uuid4()),
            lab_id=draft.lab_id,
            student_username="user",
            vm_id="vm-401",
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            current_step_index=0,
        )
        _, statuses = _build_step_statuses(session, draft.steps)
        current = next(s for s in statuses if s.is_current)
        assert current.step_troubleshoot is None

    def test_k8s_lab_detail_experiment_background_is_none(self) -> None:
        repo = _MemDraftRepo()
        draft = LabDraft(
            source_article_id="art",
            title="K8s Lab",
            description="desc",
            estimated_duration_minutes=10,
            runtime_requirements=RuntimeRequirements(),
            steps=[_make_step()],
            publish_status=PublishStatus.PUBLISHED,
            validator_results=[ValidatorResult(
                check_id="content.no_placeholders",
                blocking_level=BlockingLevel.PUBLISH_BLOCKING,
                field_path="",
                status=ValidatorStatus.PASSED,
                message="ok",
            )],
        )
        repo.create(draft)
        detail = _svc(repo).get_published_lab_detail(draft.lab_id, "user")
        assert detail is not None
        assert detail.experiment_background is None
        assert detail.completion_summary is None


# ---------------------------------------------------------------------------
# F. Content fill: real Linux lab has non-empty quality fields
# ---------------------------------------------------------------------------


LINUX_LAB_ID = "6c439064-4cad-4229-addb-36927128d565"


class TestLinuxLabContentFill:
    @pytest.fixture
    def linux_draft(self) -> LabDraft:
        with open("data/lab_drafts.json") as f:
            raw = json.load(f)
        return LabDraft.model_validate(raw[LINUX_LAB_ID])

    def test_experiment_background_non_empty(self, linux_draft: LabDraft) -> None:
        assert linux_draft.experiment_background, "experiment_background must be filled"
        assert len(linux_draft.experiment_background) >= 50

    def test_completion_summary_non_empty(self, linux_draft: LabDraft) -> None:
        assert linux_draft.completion_summary, "completion_summary must be filled"
        assert len(linux_draft.completion_summary) >= 50

    def test_all_steps_have_troubleshoot(self, linux_draft: LabDraft) -> None:
        for step in linux_draft.steps:
            assert step.troubleshoot, f"Step {step.step_id} must have troubleshoot content"
            assert len(step.troubleshoot) >= 40

    def test_no_placeholders_in_new_fields(self, linux_draft: LabDraft) -> None:
        import re
        placeholder = re.compile(r"\[TODO\]|\[PLACEHOLDER\]|\[TBD\]", re.I)
        assert not placeholder.search(linux_draft.experiment_background or "")
        assert not placeholder.search(linux_draft.completion_summary or "")
        for step in linux_draft.steps:
            assert not placeholder.search(step.troubleshoot or "")
