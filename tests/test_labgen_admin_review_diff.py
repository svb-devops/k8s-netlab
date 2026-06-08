"""Tests for AdminReviewDiff — repository unit tests + API integration tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.models import (
    AdminReviewDiff,
    AdminReviewDiffChange,
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    RuntimeRequirements,
    Step,
)
from backend.labgen.review_diff import AdminReviewDiffRepository
from backend.labgen.routes import (
    get_diff_repository,
    get_repository,
    require_admin_user,
)

pytestmark = pytest.mark.static


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


def _make_diff(lab_draft_id: str, admin_user: str = "admin", **kw) -> AdminReviewDiff:
    return AdminReviewDiff(
        lab_draft_id=lab_draft_id,
        admin_user=admin_user,
        reviewed_at=datetime.now(tz=timezone.utc),
        review_duration_seconds=0,
        changes=kw.get("changes", []),
    )


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _MemRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft


class _MemDiffRepo:
    def __init__(self) -> None:
        self._store: dict[str, list[AdminReviewDiff]] = {}

    def append(self, diff: AdminReviewDiff) -> AdminReviewDiff:
        key = diff.lab_draft_id
        if key not in self._store:
            self._store[key] = []
        self._store[key].append(diff)
        return diff

    def list_by_draft(self, lab_draft_id: str) -> list[AdminReviewDiff]:
        return list(self._store.get(lab_draft_id, []))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_repo() -> _MemRepo:
    return _MemRepo()


@pytest.fixture()
def mem_diff_repo() -> _MemDiffRepo:
    return _MemDiffRepo()


@pytest.fixture()
def client(mem_repo, mem_diff_repo):
    from backend.main import app

    app.dependency_overrides[get_repository] = lambda: mem_repo
    app.dependency_overrides[get_diff_repository] = lambda: mem_diff_repo
    app.dependency_overrides[require_admin_user] = lambda: "testadmin"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def non_admin_client():
    from backend.main import app
    from backend.auth_deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: "regularuser"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


def _insert_draft(mem_repo: _MemRepo, **kw) -> LabDraft:
    draft = _make_draft(**kw)
    mem_repo.create(draft)
    return draft


# ---------------------------------------------------------------------------
# Repository unit tests
# ---------------------------------------------------------------------------


class TestAdminReviewDiffRepository:
    def test_append_and_list_roundtrip(self, tmp_path):
        repo = AdminReviewDiffRepository(path=tmp_path / "diffs.json")
        diff = _make_diff("draft-1", admin_user="alice")
        repo.append(diff)
        result = repo.list_by_draft("draft-1")
        assert len(result) == 1
        assert result[0].lab_draft_id == "draft-1"
        assert result[0].admin_user == "alice"

    def test_list_returns_empty_for_unknown_draft(self, tmp_path):
        repo = AdminReviewDiffRepository(path=tmp_path / "diffs.json")
        repo.append(_make_diff("draft-1"))
        assert repo.list_by_draft("draft-99") == []

    def test_list_returns_empty_on_missing_file(self, tmp_path):
        repo = AdminReviewDiffRepository(path=tmp_path / "diffs.json")
        assert repo.list_by_draft("any-id") == []

    def test_multiple_diffs_same_draft_in_order(self, tmp_path):
        repo = AdminReviewDiffRepository(path=tmp_path / "diffs.json")
        d1 = _make_diff("draft-1", admin_user="alice")
        d2 = _make_diff("draft-1", admin_user="bob")
        repo.append(d1)
        repo.append(d2)
        result = repo.list_by_draft("draft-1")
        assert len(result) == 2
        assert result[0].admin_user == "alice"
        assert result[1].admin_user == "bob"

    def test_diffs_for_different_drafts_independent(self, tmp_path):
        repo = AdminReviewDiffRepository(path=tmp_path / "diffs.json")
        repo.append(_make_diff("draft-A"))
        repo.append(_make_diff("draft-B"))
        assert len(repo.list_by_draft("draft-A")) == 1
        assert len(repo.list_by_draft("draft-B")) == 1

    def test_append_returns_same_diff(self, tmp_path):
        repo = AdminReviewDiffRepository(path=tmp_path / "diffs.json")
        diff = _make_diff("draft-1")
        returned = repo.append(diff)
        assert returned.lab_draft_id == diff.lab_draft_id

    def test_schema_version_preserved_across_serialization(self, tmp_path):
        repo = AdminReviewDiffRepository(path=tmp_path / "diffs.json")
        diff = _make_diff("draft-1")
        repo.append(diff)
        result = repo.list_by_draft("draft-1")
        assert result[0].schema_version == "1.0"

    def test_changes_preserved_across_serialization(self, tmp_path):
        repo = AdminReviewDiffRepository(path=tmp_path / "diffs.json")
        change = AdminReviewDiffChange(
            field_path="title",
            change_type="edit",
            original_value='"Old Title"',
            edited_value='"New Title"',
        )
        diff = _make_diff("draft-1", changes=[change])
        repo.append(diff)
        result = repo.list_by_draft("draft-1")
        assert len(result[0].changes) == 1
        assert result[0].changes[0].field_path == "title"


# ---------------------------------------------------------------------------
# API: PATCH auto-records diff
# ---------------------------------------------------------------------------


class TestPatchRecordsDiff:
    def test_patch_title_creates_diff(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Original")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "Updated"})
        diffs = mem_diff_repo.list_by_draft(draft.lab_id)
        assert len(diffs) == 1

    def test_diff_has_correct_admin_user(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo)
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New"})
        diff = mem_diff_repo.list_by_draft(draft.lab_id)[0]
        assert diff.admin_user == "testadmin"

    def test_diff_has_correct_field_path(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New"})
        diff = mem_diff_repo.list_by_draft(draft.lab_id)[0]
        assert diff.changes[0].field_path == "title"

    def test_diff_change_type_is_edit(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New"})
        diff = mem_diff_repo.list_by_draft(draft.lab_id)[0]
        assert diff.changes[0].change_type == "edit"

    def test_diff_has_original_and_edited_value(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old Title")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New Title"})
        change = mem_diff_repo.list_by_draft(draft.lab_id)[0].changes[0]
        assert "Old Title" in change.original_value
        assert "New Title" in change.edited_value

    def test_diff_multiple_fields_in_one_entry(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old", description="Old desc")
        client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"title": "New", "description": "New desc"},
        )
        diffs = mem_diff_repo.list_by_draft(draft.lab_id)
        assert len(diffs) == 1
        assert len(diffs[0].changes) == 2

    def test_empty_patch_no_diff_recorded(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo)
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={})
        assert mem_diff_repo.list_by_draft(draft.lab_id) == []

    def test_patch_same_value_no_diff_recorded(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Test Lab")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "Test Lab"})
        assert mem_diff_repo.list_by_draft(draft.lab_id) == []

    def test_patch_increments_diff_count_per_call(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="T1")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "T2"})
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "T3"})
        assert len(mem_diff_repo.list_by_draft(draft.lab_id)) == 2

    def test_diff_review_duration_seconds_is_zero(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New"})
        diff = mem_diff_repo.list_by_draft(draft.lab_id)[0]
        assert diff.review_duration_seconds == 0

    def test_diff_lab_draft_id_matches(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New"})
        diff = mem_diff_repo.list_by_draft(draft.lab_id)[0]
        assert diff.lab_draft_id == draft.lab_id


# ---------------------------------------------------------------------------
# API: GET /api/labgen/drafts/{id}/diffs
# ---------------------------------------------------------------------------


class TestGetDiffs:
    def test_returns_empty_list_for_new_draft(self, client, mem_repo):
        draft = _insert_draft(mem_repo)
        r = client.get(f"/api/labgen/drafts/{draft.lab_id}/diffs")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_diffs_after_patch(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New"})
        r = client.get(f"/api/labgen/drafts/{draft.lab_id}/diffs")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_diff_response_has_schema_version(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New"})
        r = client.get(f"/api/labgen/drafts/{draft.lab_id}/diffs")
        assert r.json()[0]["schema_version"] == "1.0"

    def test_diff_response_has_required_fields(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="Old")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "New"})
        r = client.get(f"/api/labgen/drafts/{draft.lab_id}/diffs")
        entry = r.json()[0]
        assert "lab_draft_id" in entry
        assert "admin_user" in entry
        assert "reviewed_at" in entry
        assert "changes" in entry

    def test_404_for_missing_draft(self, client):
        r = client.get("/api/labgen/drafts/nonexistent-id/diffs")
        assert r.status_code == 404

    def test_requires_admin(self, non_admin_client):
        r = non_admin_client.get("/api/labgen/drafts/some-id/diffs")
        assert r.status_code == 403

    def test_multiple_diffs_returned_in_order(self, client, mem_repo, mem_diff_repo):
        draft = _insert_draft(mem_repo, title="T1")
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "T2"})
        client.patch(f"/api/labgen/drafts/{draft.lab_id}", json={"title": "T3"})
        r = client.get(f"/api/labgen/drafts/{draft.lab_id}/diffs")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
