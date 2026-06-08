"""Unit tests for LabDraftRepository — exercises real file I/O via tmp_path."""

import pytest

pytestmark = pytest.mark.static

from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    RuntimeRequirements,
    Step,
)
from backend.labgen.repository import LabDraftRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(**kw) -> LabDraft:
    defaults = dict(
        source_article_id="art-1",
        title="Test Lab",
        description="desc",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=[Step(
            step_id="s1", order=1, why="w", do="d", observe="o",
            explain=ExplainField(concept="c", observation="o"),
        )],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
    )
    defaults.update(kw)
    return LabDraft(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLabDraftRepository:
    def test_create_and_get_roundtrip(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        draft = _make_draft(title="My Lab")
        repo.create(draft)
        loaded = repo.get(draft.lab_id)
        assert loaded is not None
        assert loaded.lab_id == draft.lab_id
        assert loaded.title == "My Lab"

    def test_get_returns_none_for_missing_id(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        assert repo.get("nonexistent-id") is None

    def test_get_returns_none_on_empty_file(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        # File doesn't exist yet
        assert repo.get("any-id") is None

    def test_update_overwrites_draft(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        draft = _make_draft(title="Original")
        repo.create(draft)

        updated = draft.model_copy(update={"title": "Updated"})
        repo.update(updated)

        loaded = repo.get(draft.lab_id)
        assert loaded.title == "Updated"

    def test_multiple_drafts_stored_independently(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        d1 = _make_draft(title="Lab A")
        d2 = _make_draft(title="Lab B")
        repo.create(d1)
        repo.create(d2)

        assert repo.get(d1.lab_id).title == "Lab A"
        assert repo.get(d2.lab_id).title == "Lab B"

    def test_create_returns_same_draft(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        draft = _make_draft()
        returned = repo.create(draft)
        assert returned.lab_id == draft.lab_id

    def test_update_returns_same_draft(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        draft = _make_draft()
        repo.create(draft)
        returned = repo.update(draft)
        assert returned.lab_id == draft.lab_id

    def test_schema_version_preserved_across_serialization(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        draft = _make_draft()
        repo.create(draft)
        loaded = repo.get(draft.lab_id)
        assert loaded.schema_version == "1.0"

    def test_nested_objects_preserved(self, tmp_path):
        repo = LabDraftRepository(path=tmp_path / "drafts.json")
        draft = _make_draft()
        repo.create(draft)
        loaded = repo.get(draft.lab_id)
        assert len(loaded.steps) == 1
        assert loaded.steps[0].step_id == "s1"
        assert loaded.cleanup.namespace_cleanup.type == "delete_namespace"
