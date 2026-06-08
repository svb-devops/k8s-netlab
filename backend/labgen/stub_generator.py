"""
LabDraftGeneratorStub — creates a minimal valid LabDraft without LLM.

All step content is placeholder text for the admin to complete.
Used for MVP until the two-stage LLM pipeline is implemented.
"""

from __future__ import annotations

from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    RuntimeRequirements,
    Step,
)

_TODO = "[管理员待填写]"


class LabDraftGeneratorStub:
    """
    Generate a minimal valid LabDraft from request metadata.
    No LLM is involved.
    """

    def generate(
        self,
        source_article_id: str,
        title: str,
        description: str,
        estimated_duration_minutes: int = 30,
        prerequisites: list[str] | None = None,
    ) -> LabDraft:
        step = Step(
            step_id="step-1",
            order=1,
            why=_TODO,
            do=_TODO,
            observe=_TODO,
            explain=ExplainField(concept=_TODO, observation=_TODO),
        )
        return LabDraft(
            source_article_id=source_article_id,
            title=title,
            description=description,
            estimated_duration_minutes=estimated_duration_minutes,
            prerequisites=prerequisites or [],
            runtime_requirements=RuntimeRequirements(),
            steps=[step],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
