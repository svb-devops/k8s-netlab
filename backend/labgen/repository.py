"""
LabDraftRepository — flock-based JSON storage for LabDraft objects.

Backed by data/lab_drafts.json, same pattern as the rest of the project.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from backend.labgen.models import LabDraft
from backend.storage_utils import safe_read_json, safe_update_json

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/lab_drafts.json")


class LabDraftRepository:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path

    def create(self, draft: LabDraft) -> LabDraft:
        def _add(data: dict) -> dict:
            data[draft.lab_id] = draft.model_dump(mode="json")
            return data

        safe_update_json(self._path, _add)
        return draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        data = safe_read_json(self._path)
        raw = data.get(lab_id)
        if raw is None:
            return None
        try:
            return LabDraft.model_validate(raw)
        except Exception as exc:
            logger.error("LabDraftRepository.get(%s) deserialization failed: %s", lab_id, exc)
            return None

    def update(self, draft: LabDraft) -> LabDraft:
        def _upd(data: dict) -> dict:
            data[draft.lab_id] = draft.model_dump(mode="json")
            return data

        safe_update_json(self._path, _upd)
        return draft

    def list_all(self) -> list[LabDraft]:
        data = safe_read_json(self._path)
        result = []
        for lab_id, raw in data.items():
            try:
                result.append(LabDraft.model_validate(raw))
            except Exception as exc:
                logger.error("LabDraftRepository.list_all(%s) deserialization failed: %s", lab_id, exc)
        return result
