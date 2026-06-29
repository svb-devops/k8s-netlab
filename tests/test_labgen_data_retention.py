"""
Tests for DataRetentionService.

Validates:
  - report() is read-only (no side effects)
  - run(dry_run=True) plans but does not write
  - run(dry_run=False) archives orphaned diffs and rotates old audit entries
  - published lab diffs are never archived
  - zombie draft identification (TTL > threshold)
  - audit rotation by age
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.labgen.data_retention import DataRetentionService, _parse_iso, _age_days

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(days_ago: float) -> str:
    """ISO timestamp for N days ago."""
    dt = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def _make_draft(lab_id: str, status: str = "draft", days_ago: float = 5.0, rehearsal: bool = False) -> dict:
    return {
        "lab_id": lab_id,
        "publish_status": status,
        "updated_at": _ts(days_ago),
        "rehearsal_completed": rehearsal,
    }


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
def archive_dir(tmp_path: Path) -> Path:
    return tmp_path / "archive"


@pytest.fixture()
def svc(data_dir: Path, archive_dir: Path) -> DataRetentionService:
    return DataRetentionService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        zombie_ttl_days=30,
        audit_retention_days=90,
    )


# ---------------------------------------------------------------------------
# Unit: _parse_iso and _age_days
# ---------------------------------------------------------------------------


class TestParseIso:
    def test_z_suffix(self) -> None:
        dt = _parse_iso("2026-06-01T00:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_offset_aware(self) -> None:
        dt = _parse_iso("2026-06-01T00:00:00+00:00")
        assert dt is not None

    def test_naive_becomes_utc(self) -> None:
        dt = _parse_iso("2026-06-01T00:00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_none_returns_none(self) -> None:
        assert _parse_iso(None) is None

    def test_empty_returns_none(self) -> None:
        assert _parse_iso("") is None

    def test_age_days_recent(self) -> None:
        assert _age_days(_ts(1)) < 2

    def test_age_days_old(self) -> None:
        assert _age_days(_ts(100)) > 99

    def test_age_days_none_is_inf(self) -> None:
        assert _age_days(None) == float("inf")


# ---------------------------------------------------------------------------
# Report: read-only, no side effects
# ---------------------------------------------------------------------------


class TestReport:
    def test_report_does_not_modify_files(self, svc: DataRetentionService, data_dir: Path) -> None:
        published_id = "pub-001"
        draft_id = "drft-001"
        _write(data_dir / "lab_drafts.json", [
            _make_draft(published_id, status="published"),
            _make_draft(draft_id),
        ])
        _write(data_dir / "lab_review_diffs.json", {
            published_id: [{"lab_draft_id": published_id, "changes": []}],
            "orphan-xyz": [{"lab_draft_id": "orphan-xyz", "changes": []}],
        })
        _write(data_dir / "llm_audit_log.json", [])
        _write(data_dir / "lab_runtime_audit.json", [])

        before = os.path.getmtime(data_dir / "lab_review_diffs.json")
        rpt = svc.report()
        after = os.path.getmtime(data_dir / "lab_review_diffs.json")

        assert before == after, "report() must not modify files"
        assert rpt.lab_review_diffs["total_draft_keys"] == 2
        assert rpt.lab_review_diffs["orphaned_draft_keys"] == 1
        assert rpt.lab_review_diffs["protected_keys"] == 1

    def test_report_identifies_zombie_drafts(self, svc: DataRetentionService, data_dir: Path) -> None:
        _write(data_dir / "lab_drafts.json", [
            _make_draft("fresh", days_ago=5),       # not zombie
            _make_draft("old", days_ago=45),         # zombie
            _make_draft("pub", status="published"),  # protected
        ])
        _write(data_dir / "lab_review_diffs.json", {})
        _write(data_dir / "llm_audit_log.json", [])
        _write(data_dir / "lab_runtime_audit.json", [])

        rpt = svc.report()
        assert rpt.lab_drafts["zombie_eligible"] == 1
        assert rpt.lab_drafts["protected"] == 1

    def test_protected_records_include_rehearsal(self, svc: DataRetentionService, data_dir: Path) -> None:
        rehearsal_id = "rehearsal-001"
        _write(data_dir / "lab_drafts.json", [
            _make_draft(rehearsal_id, rehearsal=True),
        ])
        _write(data_dir / "lab_review_diffs.json", {})
        _write(data_dir / "llm_audit_log.json", [])
        _write(data_dir / "lab_runtime_audit.json", [])

        rpt = svc.report()
        assert rehearsal_id in rpt.protected_records


# ---------------------------------------------------------------------------
# Dry run: plans but does not write
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_modify_diffs_file(self, svc: DataRetentionService, data_dir: Path, archive_dir: Path) -> None:
        published_id = "pub-001"
        _write(data_dir / "lab_drafts.json", [_make_draft(published_id, status="published")])
        _write(data_dir / "lab_review_diffs.json", {
            published_id: [{"lab_draft_id": published_id}],
            "orphan-aaa": [{"lab_draft_id": "orphan-aaa"}],
        })
        _write(data_dir / "llm_audit_log.json", [])
        _write(data_dir / "lab_runtime_audit.json", [])

        original_size = os.path.getsize(data_dir / "lab_review_diffs.json")
        result = svc.run(dry_run=True)
        after_size = os.path.getsize(data_dir / "lab_review_diffs.json")

        assert original_size == after_size, "dry_run must not modify files"
        assert result.lab_review_diffs_archived == 1
        assert result.archive_paths == [], "dry_run must not produce archive files"
        assert not archive_dir.exists(), "dry_run must not create archive dir"


# ---------------------------------------------------------------------------
# Actual run: archives orphaned diffs, protects published
# ---------------------------------------------------------------------------


class TestActualRun:
    def test_orphaned_diffs_are_archived(self, svc: DataRetentionService, data_dir: Path, archive_dir: Path) -> None:
        published_id = "pub-001"
        orphan_id = "orphan-bbb"
        _write(data_dir / "lab_drafts.json", [_make_draft(published_id, status="published")])
        _write(data_dir / "lab_review_diffs.json", {
            published_id: [{"lab_draft_id": published_id}],
            orphan_id: [{"lab_draft_id": orphan_id}],
        })
        _write(data_dir / "llm_audit_log.json", [])
        _write(data_dir / "lab_runtime_audit.json", [])

        result = svc.run(dry_run=False)

        # Pruned file should only contain published draft
        remaining = json.loads((data_dir / "lab_review_diffs.json").read_text())
        assert published_id in remaining
        assert orphan_id not in remaining
        assert result.lab_review_diffs_archived == 1

        # Archive file should contain orphaned entry
        assert len(result.archive_paths) == 1
        archived = json.loads(Path(result.archive_paths[0]).read_text())
        assert orphan_id in archived

    def test_published_diffs_never_archived(self, svc: DataRetentionService, data_dir: Path) -> None:
        published_id = "pub-always"
        _write(data_dir / "lab_drafts.json", [_make_draft(published_id, status="published")])
        _write(data_dir / "lab_review_diffs.json", {
            published_id: [{"lab_draft_id": published_id, "important": True}],
        })
        _write(data_dir / "llm_audit_log.json", [])
        _write(data_dir / "lab_runtime_audit.json", [])

        result = svc.run(dry_run=False)

        remaining = json.loads((data_dir / "lab_review_diffs.json").read_text())
        assert published_id in remaining
        assert result.lab_review_diffs_archived == 0

    def test_old_audit_entries_rotated(self, svc: DataRetentionService, data_dir: Path, archive_dir: Path) -> None:
        _write(data_dir / "lab_drafts.json", [])
        _write(data_dir / "lab_review_diffs.json", {})
        _write(data_dir / "lab_runtime_audit.json", [])

        # Mix of recent and old entries
        entries = [
            {"timestamp": _ts(10), "event": "recent"},
            {"timestamp": _ts(100), "event": "old_1"},
            {"timestamp": _ts(200), "event": "old_2"},
        ]
        _write(data_dir / "llm_audit_log.json", entries)

        result = svc.run(dry_run=False)

        remaining = json.loads((data_dir / "llm_audit_log.json").read_text())
        assert len(remaining) == 1
        assert remaining[0]["event"] == "recent"
        assert result.llm_audit_entries_archived == 2

    def test_no_archive_file_when_nothing_to_archive(self, svc: DataRetentionService, data_dir: Path, archive_dir: Path) -> None:
        _write(data_dir / "lab_drafts.json", [])
        _write(data_dir / "lab_review_diffs.json", {})
        _write(data_dir / "llm_audit_log.json", [])
        _write(data_dir / "lab_runtime_audit.json", [])

        result = svc.run(dry_run=False)

        assert result.archive_paths == []
        assert result.lab_review_diffs_archived == 0
        assert result.llm_audit_entries_archived == 0
