"""
ArticleDraftRepository — flock-based JSON storage for ArticleDraftLabContract.

Backed by data/article_drafts.json, same pattern as LabDraftRepository.

Storage invariants:
  - raw_text_persisted is always False in persisted records
  - sensitive source grounding excerpts are never written
  - content_hash is always present
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from backend.labgen.article_models import ArticleDraftLabContract
from backend.storage_utils import safe_read_json, safe_update_json

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/article_drafts.json")


class ArticleDraftRepository:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path

    def create(self, contract: ArticleDraftLabContract) -> ArticleDraftLabContract:
        def _add(data: dict) -> dict:
            data[contract.draft_id] = contract.model_dump(mode="json")
            return data

        safe_update_json(self._path, _add)
        return contract

    def get(self, draft_id: str) -> Optional[ArticleDraftLabContract]:
        data = safe_read_json(self._path)
        raw = data.get(draft_id)
        if raw is None:
            return None
        try:
            return ArticleDraftLabContract.model_validate(raw)
        except Exception as exc:
            logger.error(
                "ArticleDraftRepository.get(%s) deserialization failed: %s", draft_id, exc
            )
            return None

    def update(self, contract: ArticleDraftLabContract) -> ArticleDraftLabContract:
        def _upd(data: dict) -> dict:
            data[contract.draft_id] = contract.model_dump(mode="json")
            return data

        safe_update_json(self._path, _upd)
        return contract

    def delete(self, draft_id: str) -> None:
        def _remove(data: dict) -> dict:
            data.pop(draft_id, None)
            return data

        safe_update_json(self._path, _remove)

    def list_all(self) -> list[ArticleDraftLabContract]:
        data = safe_read_json(self._path)
        result = []
        for draft_id, raw in data.items():
            try:
                result.append(ArticleDraftLabContract.model_validate(raw))
            except Exception as exc:
                logger.error(
                    "ArticleDraftRepository.list_all skip %s: %s", draft_id, exc
                )
        return result
