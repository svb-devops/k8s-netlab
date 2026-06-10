"""
Demo Scenario Seed Pack v0.1.

Deterministic, LLM-free, K3s-free seed service for local development,
product demonstration, and frontend manual testing.

Design invariants:
  - All records identified by deterministic string IDs (demo-* prefix).
  - No real LLM, no real K8s/VM operations, no real namespace/credential creation.
  - All session objects are constructed in-memory and written directly to repo.
  - Published drafts pass through PublishService (StaticValidator + ImageResolver).
  - Blocked/unresolved/not-found drafts have deterministic image_resolution injected
    and are validated by StaticValidator without going through PublishService.
  - Repeated seed is idempotent: upsert (overwrite) for reset=False/True alike.
  - reset=True: delete demo-owned records first, then rebuild.
  - reset=False: overwrite in place (same result since IDs are deterministic).
  - Response never contains credentials, secrets, raw model output, or runtime internals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from backend.labgen.generation_templates import GenerationTemplateId, GenerationTemplateRegistry
from backend.labgen.image_resolver import ImageResolver
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.models import (
    BlockingLevel,
    ImageResolutionResult,
    ImageStatus,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    ValidatorStatus,
)
from backend.labgen.publish_service import PublishService
from backend.labgen.repository import LabDraftRepository
from backend.labgen.static_validator import StaticValidator

# ---------------------------------------------------------------------------
# Deterministic IDs — fixed per scenario; never change across runs
# ---------------------------------------------------------------------------

DEMO_DRAFT_ID_PYTHON = "demo-python-basics-v1"
DEMO_DRAFT_ID_HTTP = "demo-http-api-basics-v1"
DEMO_DRAFT_ID_DATA_BLOCKED = "demo-data-transform-blocked-v1"
DEMO_DRAFT_ID_PYTHON_UNRESOLVED = "demo-python-unresolved-v1"
DEMO_DRAFT_ID_HTTP_NOT_FOUND = "demo-http-not-found-v1"

DEMO_SESSION_ID_ACTIVE = "demo-session-active-v1"
DEMO_SESSION_ID_READY = "demo-session-ready-v1"
DEMO_SESSION_ID_CLEANUP_FAILED = "demo-session-cleanup-failed-v1"

# Fake VM ID — does not correspond to any real Proxmox VM
DEMO_VM_ID = "demo-vm-001"

# Demo student — does not need to exist in users.json; admins can view any session
DEMO_STUDENT_USERNAME = "demo-student"

# Step IDs from PYTHON_BASICS template — hardcoded to avoid template dependency at runtime
_PYTHON_BASICS_STEP_IDS = ["pb-step-1", "pb-step-2", "pb-step-3"]

# All demo-owned draft and session IDs — used for targeted delete on reset=True
_ALL_DEMO_DRAFT_IDS = [
    DEMO_DRAFT_ID_PYTHON,
    DEMO_DRAFT_ID_HTTP,
    DEMO_DRAFT_ID_DATA_BLOCKED,
    DEMO_DRAFT_ID_PYTHON_UNRESOLVED,
    DEMO_DRAFT_ID_HTTP_NOT_FOUND,
]
_ALL_DEMO_SESSION_IDS = [
    DEMO_SESSION_ID_ACTIVE,
    DEMO_SESSION_ID_READY,
    DEMO_SESSION_ID_CLEANUP_FAILED,
]


# ---------------------------------------------------------------------------
# Deterministic demo image_resolution fixtures — no real registry secrets
# ---------------------------------------------------------------------------

def _blocked_image() -> ImageResolutionResult:
    """Demonstrates IMAGE_READINESS_BLOCKED: external registry image is forbidden."""
    return ImageResolutionResult(
        image_intent="pandas",
        requested_image="docker.io/library/pandas:latest",
        resolved_image=None,
        image_status=ImageStatus.BLOCKED,
        existence_check_passed=None,
    )


def _unresolved_image() -> ImageResolutionResult:
    """Demonstrates IMAGE_READINESS_UNRESOLVED: intent has no whitelist mapping."""
    return ImageResolutionResult(
        image_intent="matplotlib",
        requested_image="matplotlib:3.8.0",
        resolved_image=None,
        image_status=ImageStatus.UNRESOLVED,
        existence_check_passed=None,
    )


def _not_found_image() -> ImageResolutionResult:
    """Demonstrates IMAGE_READINESS_NOT_FOUND: resolved but not present in registry."""
    return ImageResolutionResult(
        image_intent="httpie",
        requested_image="httpie:3.2",
        resolved_image="172.16.100.1:5000/httpie:3.2",
        image_status=ImageStatus.RESOLVED,
        existence_check_passed=False,
    )


# ---------------------------------------------------------------------------
# Enums and models
# ---------------------------------------------------------------------------


class DemoSeedScenarioId(str, Enum):
    PYTHON_BASICS_PUBLISHED = "PYTHON_BASICS_PUBLISHED"
    HTTP_API_BASICS_PUBLISHED = "HTTP_API_BASICS_PUBLISHED"
    DATA_TRANSFORM_IMAGE_BLOCKED_DRAFT = "DATA_TRANSFORM_IMAGE_BLOCKED_DRAFT"
    PYTHON_IMAGE_UNRESOLVED_DRAFT = "PYTHON_IMAGE_UNRESOLVED_DRAFT"
    HTTP_IMAGE_NOT_FOUND_DRAFT = "HTTP_IMAGE_NOT_FOUND_DRAFT"
    RUNTIME_ACTIVE_SESSION = "RUNTIME_ACTIVE_SESSION"
    RUNTIME_READY_TO_COMPLETE_SESSION = "RUNTIME_READY_TO_COMPLETE_SESSION"
    RUNTIME_CLEANUP_FAILED_TAINTED_SESSION = "RUNTIME_CLEANUP_FAILED_TAINTED_SESSION"


ALL_DEMO_SCENARIOS: list[DemoSeedScenarioId] = list(DemoSeedScenarioId)


class DemoNextStep(BaseModel):
    label: str
    path: str


class DemoSeedResult(BaseModel):
    seeded_scenarios: list[str]
    created_or_updated_draft_ids: list[str]
    created_or_updated_lab_ids: list[str]  # published draft IDs only (visible in catalog)
    created_or_updated_session_ids: list[str]
    warnings: list[str] = Field(default_factory=list)
    next_steps: list[DemoNextStep] = Field(default_factory=list)
    checked_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


class DemoSeedRequest(BaseModel):
    scenarios: Optional[list[DemoSeedScenarioId]] = None  # default: all
    reset: bool = False
    include_runtime_sessions: bool = True


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DemoSeedService:
    """
    Orchestrates seeding of all demo scenarios.

    Accepts injected repos so tests can use in-memory backends.
    No real LLM, no real K8s/VM, no real namespace/credential operations.
    """

    def __init__(
        self,
        draft_repo: LabDraftRepository,
        session_repo: LabSessionRepository,
    ) -> None:
        self._draft_repo = draft_repo
        self._session_repo = session_repo
        self._registry = GenerationTemplateRegistry()
        self._validator = StaticValidator()
        self._image_resolver = ImageResolver()
        self._publish_svc = PublishService(
            validator=self._validator,
            image_resolver=self._image_resolver,
        )

    def seed(
        self,
        scenarios: Optional[list[DemoSeedScenarioId]] = None,
        reset: bool = False,
        include_runtime_sessions: bool = True,
    ) -> DemoSeedResult:
        target = scenarios if scenarios is not None else ALL_DEMO_SCENARIOS
        warnings: list[str] = []

        if reset:
            self._delete_demo_records()

        draft_ids: list[str] = []
        lab_ids: list[str] = []  # published only
        session_ids: list[str] = []
        seeded: list[str] = []

        for scenario in target:
            if scenario == DemoSeedScenarioId.PYTHON_BASICS_PUBLISHED:
                draft = self._seed_published_draft(
                    DEMO_DRAFT_ID_PYTHON, GenerationTemplateId.PYTHON_BASICS
                )
                draft_ids.append(draft.lab_id)
                if draft.publish_status == PublishStatus.PUBLISHED:
                    lab_ids.append(draft.lab_id)
                else:
                    warnings.append(
                        f"PYTHON_BASICS draft did not reach PUBLISHED: {draft.publish_status.value}"
                    )
                seeded.append(scenario.value)

            elif scenario == DemoSeedScenarioId.HTTP_API_BASICS_PUBLISHED:
                draft = self._seed_published_draft(
                    DEMO_DRAFT_ID_HTTP, GenerationTemplateId.HTTP_API_BASICS
                )
                draft_ids.append(draft.lab_id)
                if draft.publish_status == PublishStatus.PUBLISHED:
                    lab_ids.append(draft.lab_id)
                else:
                    warnings.append(
                        f"HTTP_API_BASICS draft did not reach PUBLISHED: {draft.publish_status.value}"
                    )
                seeded.append(scenario.value)

            elif scenario == DemoSeedScenarioId.DATA_TRANSFORM_IMAGE_BLOCKED_DRAFT:
                draft, w = self._seed_image_blocked_draft(DEMO_DRAFT_ID_DATA_BLOCKED)
                draft_ids.append(draft.lab_id)
                warnings.extend(w)
                seeded.append(scenario.value)

            elif scenario == DemoSeedScenarioId.PYTHON_IMAGE_UNRESOLVED_DRAFT:
                draft, w = self._seed_image_unresolved_draft(DEMO_DRAFT_ID_PYTHON_UNRESOLVED)
                draft_ids.append(draft.lab_id)
                warnings.extend(w)
                seeded.append(scenario.value)

            elif scenario == DemoSeedScenarioId.HTTP_IMAGE_NOT_FOUND_DRAFT:
                draft, w = self._seed_image_not_found_draft(DEMO_DRAFT_ID_HTTP_NOT_FOUND)
                draft_ids.append(draft.lab_id)
                warnings.extend(w)
                seeded.append(scenario.value)

            elif scenario == DemoSeedScenarioId.RUNTIME_ACTIVE_SESSION:
                if not include_runtime_sessions:
                    continue
                session = self._seed_active_session()
                session_ids.append(session.session_id)
                seeded.append(scenario.value)

            elif scenario == DemoSeedScenarioId.RUNTIME_READY_TO_COMPLETE_SESSION:
                if not include_runtime_sessions:
                    continue
                session = self._seed_ready_to_complete_session()
                session_ids.append(session.session_id)
                seeded.append(scenario.value)

            elif scenario == DemoSeedScenarioId.RUNTIME_CLEANUP_FAILED_TAINTED_SESSION:
                if not include_runtime_sessions:
                    continue
                session = self._seed_cleanup_failed_session()
                session_ids.append(session.session_id)
                seeded.append(scenario.value)

        next_steps = self._build_next_steps(lab_ids, draft_ids, session_ids)

        return DemoSeedResult(
            seeded_scenarios=seeded,
            created_or_updated_draft_ids=draft_ids,
            created_or_updated_lab_ids=lab_ids,
            created_or_updated_session_ids=session_ids,
            warnings=warnings,
            next_steps=next_steps,
        )

    # ------------------------------------------------------------------
    # Draft scenarios
    # ------------------------------------------------------------------

    def _seed_published_draft(
        self, draft_id: str, template_id: GenerationTemplateId
    ) -> LabDraft:
        template = self._registry.get_by_id(template_id)
        candidate_dict = template.build_candidate(user_prompt="")
        candidate_dict["lab_id"] = draft_id
        draft = LabDraft.model_validate(candidate_dict)

        # Always pass through PublishService — reruns StaticValidator + image checks
        published = self._publish_svc.publish(draft)

        return self._upsert_draft(published)

    def _seed_image_blocked_draft(self, draft_id: str) -> tuple[LabDraft, list[str]]:
        """
        DATA_TRANSFORM scenario: inject a BLOCKED image into image_resolution.

        Demonstrates IMAGE_READINESS_BLOCKED gate: an external/forbidden image
        blocks both StaticValidator (image.all_resolved) and ImageReadinessService.
        Does NOT call PublishService (image resolver would attempt real resolution).
        """
        template = self._registry.get_by_id(GenerationTemplateId.DATA_TRANSFORM_BASICS)
        candidate_dict = template.build_candidate(user_prompt="")
        candidate_dict["lab_id"] = draft_id
        draft = LabDraft.model_validate(candidate_dict)

        # Inject deterministic BLOCKED image — no real registry secrets
        draft = draft.model_copy(update={"image_resolution": [_blocked_image()]})

        return self._validate_and_block_draft(draft, "DATA_TRANSFORM IMAGE_BLOCKED")

    def _seed_image_unresolved_draft(self, draft_id: str) -> tuple[LabDraft, list[str]]:
        """
        PYTHON scenario: inject an UNRESOLVED image.

        Demonstrates IMAGE_READINESS_UNRESOLVED: intent exists but no whitelist mapping.
        StaticValidator's image.all_resolved fails (PUBLISH_BLOCKING).
        """
        template = self._registry.get_by_id(GenerationTemplateId.PYTHON_BASICS)
        candidate_dict = template.build_candidate(user_prompt="")
        candidate_dict["lab_id"] = draft_id
        draft = LabDraft.model_validate(candidate_dict)

        # Inject deterministic UNRESOLVED image
        draft = draft.model_copy(update={"image_resolution": [_unresolved_image()]})

        return self._validate_and_block_draft(draft, "PYTHON IMAGE_UNRESOLVED")

    def _seed_image_not_found_draft(self, draft_id: str) -> tuple[LabDraft, list[str]]:
        """
        HTTP scenario: inject a RESOLVED-but-missing image.

        Demonstrates IMAGE_READINESS_NOT_FOUND: image resolves to internal registry
        URL but existence check fails (not pushed yet).
        StaticValidator's image.all_exist_in_registry fails (PUBLISH_BLOCKING).
        """
        template = self._registry.get_by_id(GenerationTemplateId.HTTP_API_BASICS)
        candidate_dict = template.build_candidate(user_prompt="")
        candidate_dict["lab_id"] = draft_id
        draft = LabDraft.model_validate(candidate_dict)

        # Inject deterministic NOT_FOUND image (resolved URL, existence_check_passed=False)
        draft = draft.model_copy(update={"image_resolution": [_not_found_image()]})

        return self._validate_and_block_draft(draft, "HTTP IMAGE_NOT_FOUND")

    def _validate_and_block_draft(
        self, draft: LabDraft, scenario_label: str
    ) -> tuple[LabDraft, list[str]]:
        """
        Run StaticValidator, set publish_status=PUBLISH_BLOCKED if any PUBLISH_BLOCKING
        failure found, then upsert. Used by all image-readiness-blocked scenarios.
        """
        results = self._validator.validate(draft)
        draft.validator_results = results

        has_blocking = any(
            r.status == ValidatorStatus.FAILED
            and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
            for r in results
        )
        draft.publish_status = (
            PublishStatus.PUBLISH_BLOCKED if has_blocking else PublishStatus.DRAFT
        )

        warnings: list[str] = []
        if not has_blocking:
            warnings.append(
                f"{scenario_label} scenario: expected PUBLISH_BLOCKED but StaticValidator "
                "found no blocking failures — image injection may not be triggering the gate"
            )

        return self._upsert_draft(draft), warnings

    # ------------------------------------------------------------------
    # Session scenarios
    # ------------------------------------------------------------------

    def _seed_active_session(self) -> LabSessionState:
        now = datetime.now(tz=timezone.utc)
        session = LabSessionState(
            session_id=DEMO_SESSION_ID_ACTIVE,
            lab_id=DEMO_DRAFT_ID_PYTHON,
            vm_id=DEMO_VM_ID,
            student_username=DEMO_STUDENT_USERNAME,
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            started_at=now,
            namespace=f"lab-{DEMO_SESSION_ID_ACTIVE}",
            current_step_index=0,
        )
        return self._upsert_session(session)

    def _seed_ready_to_complete_session(self) -> LabSessionState:
        now = datetime.now(tz=timezone.utc)
        session = LabSessionState(
            session_id=DEMO_SESSION_ID_READY,
            lab_id=DEMO_DRAFT_ID_PYTHON,
            vm_id=DEMO_VM_ID,
            student_username=DEMO_STUDENT_USERNAME,
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            started_at=now,
            namespace=f"lab-{DEMO_SESSION_ID_READY}",
            # All steps completed; index points past last step
            current_step_index=len(_PYTHON_BASICS_STEP_IDS),
            completed_step_ids=list(_PYTHON_BASICS_STEP_IDS),
            ready_to_complete=True,
        )
        return self._upsert_session(session)

    def _seed_cleanup_failed_session(self) -> LabSessionState:
        now = datetime.now(tz=timezone.utc)
        session = LabSessionState(
            session_id=DEMO_SESSION_ID_CLEANUP_FAILED,
            lab_id=DEMO_DRAFT_ID_HTTP,
            vm_id=DEMO_VM_ID,
            student_username=DEMO_STUDENT_USERNAME,
            lab_session_status=LabSessionStatus.LAB_CLEANUP_FAILED,
            started_at=now,
            ended_at=now,
            namespace=f"lab-{DEMO_SESSION_ID_CLEANUP_FAILED}",
            failure_reason="namespace_cleanup_failed",
            cleanup_verified=False,
        )
        return self._upsert_session(session)

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _upsert_draft(self, draft: LabDraft) -> LabDraft:
        if self._draft_repo.get(draft.lab_id) is None:
            return self._draft_repo.create(draft)
        return self._draft_repo.update(draft)

    def _upsert_session(self, session: LabSessionState) -> LabSessionState:
        if self._session_repo.get(session.session_id) is None:
            return self._session_repo.create(session)
        return self._session_repo.update(session)

    def _delete_demo_records(self) -> None:
        """Delete all demo-owned records. Only affects IDs in _ALL_DEMO_*."""
        for draft_id in _ALL_DEMO_DRAFT_IDS:
            self._draft_repo.delete(draft_id)
        for session_id in _ALL_DEMO_SESSION_IDS:
            self._session_repo.delete(session_id)

    # ------------------------------------------------------------------
    # next_steps builder
    # ------------------------------------------------------------------

    def _build_next_steps(
        self,
        lab_ids: list[str],
        draft_ids: list[str],
        session_ids: list[str],
    ) -> list[DemoNextStep]:
        steps: list[DemoNextStep] = []
        for draft_id in draft_ids:
            steps.append(DemoNextStep(
                label=f"Admin draft review: {draft_id}",
                path=f"/labgen-admin.html?draftId={draft_id}",
            ))
        if lab_ids:
            steps.append(DemoNextStep(
                label="Learner catalog (all published labs)",
                path="/labgen-catalog.html",
            ))
        for lab_id in lab_ids:
            steps.append(DemoNextStep(
                label=f"Learner lab detail: {lab_id}",
                path=f"/labgen-lab.html?labId={lab_id}",
            ))
        for session_id in session_ids:
            steps.append(DemoNextStep(
                label=f"Learner session snapshot: {session_id}",
                path=f"/labgen-session.html?sessionId={session_id}",
            ))
        return steps
