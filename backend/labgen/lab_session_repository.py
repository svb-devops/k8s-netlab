"""
LabSessionRepository — flock-based JSON storage for LabSessionState.

Backed by data/lab_sessions.json, same pattern as LabDraftRepository.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from backend.labgen.models import LabSessionState
from backend.storage_utils import safe_read_json, safe_update_json

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/lab_sessions.json")


class LabSessionRepository:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path

    def create(self, session: LabSessionState) -> LabSessionState:
        def _add(data: dict) -> dict:
            data[session.session_id] = session.model_dump(mode="json")
            return data

        safe_update_json(self._path, _add)
        return session

    def get(self, session_id: str) -> Optional[LabSessionState]:
        data = safe_read_json(self._path)
        raw = data.get(session_id)
        if raw is None:
            return None
        try:
            return LabSessionState.model_validate(raw)
        except Exception as exc:
            logger.error("LabSessionRepository.get(%s) failed: %s", session_id, exc)
            return None

    def update(self, session: LabSessionState) -> LabSessionState:
        def _upd(data: dict) -> dict:
            data[session.session_id] = session.model_dump(mode="json")
            return data

        safe_update_json(self._path, _upd)
        return session

    def delete(self, session_id: str) -> None:
        def _remove(data: dict) -> dict:
            data.pop(session_id, None)
            return data

        safe_update_json(self._path, _remove)

    def list_by_student(self, student_username: str) -> list[LabSessionState]:
        data = safe_read_json(self._path)
        result = []
        for raw in data.values():
            try:
                s = LabSessionState.model_validate(raw)
                if s.student_username == student_username:
                    result.append(s)
            except Exception as exc:
                logger.error("LabSessionRepository.list_by_student failed: %s", exc)
        return result

    def list_all(self) -> list[LabSessionState]:
        data = safe_read_json(self._path)
        result = []
        for raw in data.values():
            try:
                result.append(LabSessionState.model_validate(raw))
            except Exception as exc:
                logger.error("LabSessionRepository.list_all failed: %s", exc)
        return result

    def list_by_vm_id(self, vm_id: str) -> list[LabSessionState]:
        data = safe_read_json(self._path)
        result = []
        for raw in data.values():
            try:
                s = LabSessionState.model_validate(raw)
                if s.vm_id == vm_id:
                    result.append(s)
            except Exception as exc:
                logger.error("LabSessionRepository.list_by_vm_id failed: %s", exc)
        return result
