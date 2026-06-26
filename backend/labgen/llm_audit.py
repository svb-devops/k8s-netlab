"""
LLM Call Audit Log v0.1.

Append-only JSON log for all admin-triggered LLM generation calls.
Records metadata only — never stores raw article text, LLM output, or secrets.

Design invariants:
  - Append-only: entries are never deleted or modified
  - No raw article text stored
  - No LLM raw output stored
  - No API keys or credentials stored
  - Failure entries are written even when generation fails
  - Safe to call from try/finally blocks
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_AUDIT_PATH = Path("data/llm_audit_log.json")

# Maximum characters for article title stored in audit log (truncate beyond this)
_MAX_AUDIT_TITLE_LEN = 200


class LLMAuditEntry:
    """
    Single audit record for one LLM generation call.

    Fields:
      audit_id        — unique ID for this record
      timestamp       — UTC ISO-8601
      admin_user      — username of the admin who triggered generation
      article_draft_id — source ArticleDraftLabContract.draft_id
      article_title   — truncated, safe for logs
      target_domain   — k8s | linux | unknown
      llm_mode        — fake_only | live_admin_only
      model_name      — model identifier (or "fake" for stub)
      success         — True if LabDraft was created
      failure_reason  — machine-readable code (or None on success)
      lab_draft_id    — LabDraft.lab_id if created (or None on failure)
      token_count_estimate — rough estimate if available (or None)
      operability_status  — DIRECTLY_LAB_READY | PARTIALLY_LAB_READY
    """

    __slots__ = (
        "audit_id",
        "timestamp",
        "admin_user",
        "article_draft_id",
        "article_title",
        "target_domain",
        "llm_mode",
        "model_name",
        "success",
        "failure_reason",
        "lab_draft_id",
        "token_count_estimate",
        "operability_status",
    )

    def __init__(
        self,
        *,
        admin_user: str,
        article_draft_id: str,
        article_title: str,
        target_domain: str,
        llm_mode: str,
        model_name: str,
        success: bool,
        failure_reason: Optional[str] = None,
        lab_draft_id: Optional[str] = None,
        token_count_estimate: Optional[int] = None,
        operability_status: str = "unknown",
    ) -> None:
        self.audit_id = str(uuid.uuid4())
        self.timestamp = datetime.now(tz=timezone.utc).isoformat()
        self.admin_user = admin_user
        self.article_draft_id = article_draft_id
        self.article_title = article_title[:_MAX_AUDIT_TITLE_LEN]
        self.target_domain = target_domain
        self.llm_mode = llm_mode
        self.model_name = model_name
        self.success = success
        self.failure_reason = failure_reason
        self.lab_draft_id = lab_draft_id
        self.token_count_estimate = token_count_estimate
        self.operability_status = operability_status

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "admin_user": self.admin_user,
            "article_draft_id": self.article_draft_id,
            "article_title": self.article_title,
            "target_domain": self.target_domain,
            "llm_mode": self.llm_mode,
            "model_name": self.model_name,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "lab_draft_id": self.lab_draft_id,
            "token_count_estimate": self.token_count_estimate,
            "operability_status": self.operability_status,
        }


class LLMAuditRepository:
    """
    Append-only audit log backed by a JSON array file.

    Thread-safe via flock_update. Each write appends one entry.
    Reads return the full list (most recent last).
    """

    def __init__(self, audit_path: Optional[Path] = None) -> None:
        self._path = audit_path or _DEFAULT_AUDIT_PATH

    def append(self, entry: LLMAuditEntry) -> None:
        """Append a single audit entry. Never raises — failures are logged only."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            # Exclusive lock: open (or create) the main file, then read+append+write atomically
            with open(self._path, "a+") as lock_fh:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
                try:
                    lock_fh.seek(0)
                    content = lock_fh.read().strip()
                    data: list = json.loads(content) if content else []
                    if not isinstance(data, list):
                        data = []
                    data.append(entry.to_dict())
                    tmp_str = str(tmp)
                    with open(tmp_str, "w") as f:
                        json.dump(data, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_str, str(self._path))
                finally:
                    fcntl.flock(lock_fh, fcntl.LOCK_UN)
            logger.info(
                "LLMAuditRepository.append: audit_id=%s admin=%s domain=%s success=%s",
                entry.audit_id,
                entry.admin_user,
                entry.target_domain,
                entry.success,
            )
        except Exception:
            logger.exception(
                "LLMAuditRepository.append: failed to write audit entry audit_id=%s",
                entry.audit_id,
            )

    def list_all(self) -> list[dict]:
        """Return all audit entries (most recent last). Empty list if file missing."""
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def get_by_id(self, audit_id: str) -> Optional[dict]:
        """Return a single entry by audit_id, or None if not found."""
        for entry in self.list_all():
            if entry.get("audit_id") == audit_id:
                return entry
        return None
