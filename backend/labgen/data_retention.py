"""
LabGen Data Retention Tool

Implements read-only reporting, dry-run archive, and actual archive/cleanup for:
  - lab_drafts.json       (zombie draft identification)
  - lab_review_diffs.json (orphaned diff groups archival)
  - llm_audit_log.json    (rotation by age)
  - lab_runtime_audit.json (rotation by age)

Usage:
    from backend.labgen.data_retention import DataRetentionService
    svc = DataRetentionService()
    report = svc.report()          # read-only analysis
    svc.run(dry_run=True)          # plan, no changes
    svc.run(dry_run=False)         # execute
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_ARCHIVE_DIR = _DATA_DIR / "archive"

# ---------------------------------------------------------------------------
# Retention policy constants (all configurable via constructor)
# ---------------------------------------------------------------------------

ZOMBIE_DRAFT_TTL_DAYS: int = 30
AUDIT_RETENTION_DAYS: int = 90
RUNTIME_AUDIT_RETENTION_DAYS: int = 90


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RetentionReport:
    generated_at: str = ""
    lab_drafts: dict[str, Any] = field(default_factory=dict)
    lab_review_diffs: dict[str, Any] = field(default_factory=dict)
    llm_audit_log: dict[str, Any] = field(default_factory=dict)
    lab_runtime_audit: dict[str, Any] = field(default_factory=dict)
    protected_records: list[str] = field(default_factory=list)


@dataclass
class RetentionResult:
    dry_run: bool = True
    lab_drafts_archived: int = 0
    lab_review_diffs_archived: int = 0
    llm_audit_entries_archived: int = 0
    lab_runtime_entries_archived: int = 0
    archive_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_json_locked(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _write_json_locked(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".retention_tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    tmp.replace(path)


def _parse_iso(ts: str | None) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _age_days(ts: str | None) -> float:
    dt = _parse_iso(ts)
    if dt is None:
        return float("inf")
    return (datetime.now(tz=timezone.utc) - dt).total_seconds() / 86400


# ---------------------------------------------------------------------------
# DataRetentionService
# ---------------------------------------------------------------------------


class DataRetentionService:
    def __init__(
        self,
        data_dir: Path = _DATA_DIR,
        archive_dir: Path = _ARCHIVE_DIR,
        zombie_ttl_days: int = ZOMBIE_DRAFT_TTL_DAYS,
        audit_retention_days: int = AUDIT_RETENTION_DAYS,
    ) -> None:
        self.data_dir = data_dir
        self.archive_dir = archive_dir
        self.zombie_ttl_days = zombie_ttl_days
        self.audit_retention_days = audit_retention_days

    # ------------------------------------------------------------------
    # Protected records
    # ------------------------------------------------------------------

    def _get_protected_draft_ids(self, drafts: list[dict[str, Any]]) -> set[str]:
        """Draft IDs that must never be archived."""
        protected: set[str] = set()

        for d in drafts:
            lid = d.get("lab_id", "")
            if not lid:
                continue
            # Always protect published drafts
            if d.get("publish_status") == "published":
                protected.add(lid)
            # Protect rehearsal-completed drafts
            if d.get("rehearsal_completed"):
                protected.add(lid)

        return protected

    # ------------------------------------------------------------------
    # Zombie draft identification
    # ------------------------------------------------------------------

    def _identify_zombie_drafts(
        self,
        drafts: list[dict[str, Any]],
        protected_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Identify draft-status drafts eligible for archival."""
        zombies: list[dict[str, Any]] = []
        for d in drafts:
            lid = d.get("lab_id", "")
            if lid in protected_ids:
                continue
            if d.get("publish_status") != "draft":
                continue
            age = _age_days(d.get("updated_at") or d.get("created_at"))
            if age >= self.zombie_ttl_days:
                zombies.append(d)
        return zombies

    # ------------------------------------------------------------------
    # Orphaned review diffs
    # ------------------------------------------------------------------

    def _identify_orphaned_diffs(
        self,
        diffs_data: dict[str, Any],
        existing_draft_ids: set[str],
        protected_ids: set[str],
    ) -> list[str]:
        """Keys in lab_review_diffs that have no matching draft and are not protected."""
        orphaned: list[str] = []
        for key in diffs_data:
            if key in protected_ids:
                continue
            if key not in existing_draft_ids:
                orphaned.append(key)
        return orphaned

    # ------------------------------------------------------------------
    # Audit log rotation
    # ------------------------------------------------------------------

    def _identify_old_audit_entries(
        self,
        entries: list[Any],
        ts_field: str,
        retention_days: int,
    ) -> tuple[list[Any], list[Any]]:
        """Split entries into (keep, archive) based on age."""
        keep: list[Any] = []
        archive: list[Any] = []
        for entry in entries:
            if not isinstance(entry, dict):
                keep.append(entry)
                continue
            age = _age_days(entry.get(ts_field))
            if age <= retention_days:
                keep.append(entry)
            else:
                archive.append(entry)
        return keep, archive

    # ------------------------------------------------------------------
    # Public API: report
    # ------------------------------------------------------------------

    def report(self) -> RetentionReport:
        rpt = RetentionReport(generated_at=datetime.now(tz=timezone.utc).isoformat())

        # lab_drafts
        drafts_path = self.data_dir / "lab_drafts.json"
        raw_drafts = _read_json_locked(drafts_path)
        drafts: list[dict[str, Any]] = raw_drafts if isinstance(raw_drafts, list) else list(raw_drafts.values())
        protected = self._get_protected_draft_ids(drafts)
        zombies = self._identify_zombie_drafts(drafts, protected)
        rpt.lab_drafts = {
            "total": len(drafts),
            "published": sum(1 for d in drafts if d.get("publish_status") == "published"),
            "draft_status": sum(1 for d in drafts if d.get("publish_status") == "draft"),
            "zombie_eligible": len(zombies),
            "protected": len(protected),
        }

        # lab_review_diffs
        diffs_path = self.data_dir / "lab_review_diffs.json"
        diffs_data: dict[str, Any] = _read_json_locked(diffs_path)
        existing_ids = {d.get("lab_id", "") for d in drafts}
        orphaned = self._identify_orphaned_diffs(diffs_data, existing_ids, protected)
        total_diff_entries = sum(len(v) for v in diffs_data.values() if isinstance(v, list))
        orphaned_entries = sum(len(diffs_data.get(k, [])) for k in orphaned if isinstance(diffs_data.get(k), list))
        rpt.lab_review_diffs = {
            "total_draft_keys": len(diffs_data),
            "total_diff_entries": total_diff_entries,
            "orphaned_draft_keys": len(orphaned),
            "orphaned_diff_entries": orphaned_entries,
            "protected_keys": len(protected & set(diffs_data.keys())),
            "file_size_mb": round(diffs_path.stat().st_size / 1024 / 1024, 2),
        }

        # llm_audit_log (list of audit records; timestamp field = "timestamp")
        audit_path = self.data_dir / "llm_audit_log.json"
        if audit_path.exists():
            audit_data = _read_json_locked(audit_path)
            audit_entries: list[Any] = audit_data if isinstance(audit_data, list) else []
            _, old_audit = self._identify_old_audit_entries(
                audit_entries, "timestamp", self.audit_retention_days
            )
            rpt.llm_audit_log = {
                "total": len(audit_entries),
                "eligible_for_archive": len(old_audit),
                "retention_days": self.audit_retention_days,
                "file_size_kb": round(audit_path.stat().st_size / 1024, 1),
            }

        # lab_runtime_audit (dict keyed by session_id; each value is list of events)
        runtime_path = self.data_dir / "lab_runtime_audit.json"
        if runtime_path.exists():
            runtime_data = _read_json_locked(runtime_path)
            if isinstance(runtime_data, dict):
                runtime_entries = [e for events in runtime_data.values() for e in (events if isinstance(events, list) else [])]
            else:
                runtime_entries = runtime_data if isinstance(runtime_data, list) else []
            _, old_runtime = self._identify_old_audit_entries(
                runtime_entries, "timestamp", self.audit_retention_days
            )
            rpt.lab_runtime_audit = {
                "total": len(runtime_entries),
                "eligible_for_archive": len(old_runtime),
                "retention_days": self.audit_retention_days,
                "file_size_kb": round(runtime_path.stat().st_size / 1024, 1),
                "structure": "dict" if isinstance(runtime_data, dict) else "list",
            }

        rpt.protected_records = sorted(protected)
        return rpt

    # ------------------------------------------------------------------
    # Public API: run
    # ------------------------------------------------------------------

    def run(self, dry_run: bool = True) -> RetentionResult:
        result = RetentionResult(dry_run=dry_run)
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")

        if not dry_run:
            self.archive_dir.mkdir(parents=True, exist_ok=True)

        # --- lab_review_diffs: archive orphaned draft groups ---
        diffs_path = self.data_dir / "lab_review_diffs.json"
        drafts_path = self.data_dir / "lab_drafts.json"
        raw_drafts = _read_json_locked(drafts_path)
        drafts = raw_drafts if isinstance(raw_drafts, list) else list(raw_drafts.values())
        protected = self._get_protected_draft_ids(drafts)
        existing_ids = {d.get("lab_id", "") for d in drafts}

        diffs_data: dict[str, Any] = _read_json_locked(diffs_path)
        orphaned_keys = self._identify_orphaned_diffs(diffs_data, existing_ids, protected)
        orphaned_count = sum(len(diffs_data.get(k, [])) for k in orphaned_keys if isinstance(diffs_data.get(k), list))

        if orphaned_keys:
            if not dry_run:
                # Archive orphaned groups
                archive_path = self.archive_dir / f"lab_review_diffs_orphaned_{stamp}.json"
                orphaned_data = {k: diffs_data[k] for k in orphaned_keys if k in diffs_data}
                _write_json_locked(archive_path, orphaned_data)
                result.archive_paths.append(str(archive_path))

                # Write pruned diffs file
                pruned = {k: v for k, v in diffs_data.items() if k not in orphaned_keys}
                _write_json_locked(diffs_path, pruned)
                logger.info(
                    "lab_review_diffs: archived %d orphaned groups (%d entries) → %s",
                    len(orphaned_keys), orphaned_count, archive_path,
                )
            result.lab_review_diffs_archived = orphaned_count

        # --- llm_audit_log: rotate old entries ---
        audit_path = self.data_dir / "llm_audit_log.json"
        if audit_path.exists():
            audit_data = _read_json_locked(audit_path)
            audit_entries = audit_data if isinstance(audit_data, list) else []
            keep_audit, old_audit = self._identify_old_audit_entries(
                audit_entries, "timestamp", self.audit_retention_days
            )
            if old_audit and not dry_run:
                archive_path = self.archive_dir / f"llm_audit_log_{stamp}.json"
                _write_json_locked(archive_path, old_audit)
                _write_json_locked(audit_path, keep_audit)
                result.archive_paths.append(str(archive_path))
            result.llm_audit_entries_archived = len(old_audit)

        # --- lab_runtime_audit: rotate old entries ---
        runtime_path = self.data_dir / "lab_runtime_audit.json"
        if runtime_path.exists():
            runtime_data = _read_json_locked(runtime_path)
            runtime_entries = runtime_data if isinstance(runtime_data, list) else []
            keep_runtime, old_runtime = self._identify_old_audit_entries(
                runtime_entries, "timestamp", self.audit_retention_days
            )
            if old_runtime and not dry_run:
                archive_path = self.archive_dir / f"lab_runtime_audit_{stamp}.json"
                _write_json_locked(archive_path, old_runtime)
                _write_json_locked(runtime_path, keep_runtime)
                result.archive_paths.append(str(archive_path))
            result.lab_runtime_entries_archived = len(old_runtime)

        return result
