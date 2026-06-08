"""
AdminReviewDiffRepository — append-only flock-based storage for admin review diffs.

Backed by data/lab_review_diffs.json, same pattern as LabDraftRepository.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.labgen.models import AdminReviewDiff
from backend.storage_utils import safe_read_json, safe_update_json

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/lab_review_diffs.json")


class AdminReviewDiffRepository:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path

    def append(self, diff: AdminReviewDiff) -> AdminReviewDiff:
        def _add(data: dict) -> dict:
            key = diff.lab_draft_id
            if key not in data:
                data[key] = []
            data[key].append(diff.model_dump(mode="json"))
            return data

        safe_update_json(self._path, _add)
        return diff

    def list_by_draft(self, lab_draft_id: str) -> list[AdminReviewDiff]:
        data = safe_read_json(self._path)
        result = []
        for raw in data.get(lab_draft_id, []):
            try:
                result.append(AdminReviewDiff.model_validate(raw))
            except Exception as exc:
                logger.error(
                    "AdminReviewDiffRepository.list_by_draft(%s) failed: %s",
                    lab_draft_id,
                    exc,
                )
        return result
