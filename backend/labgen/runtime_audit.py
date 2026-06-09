"""
RuntimeAuditRepository + RuntimeAuditService — append-only audit log for LabGen.

Storage: data/lab_runtime_audit.json (keyed by session_id → list of events)
metadata field MUST NOT contain: tokens, kubeconfig content, passwords, or any credential material.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from backend.labgen.models import RuntimeAuditEvent, RuntimeAuditEventType
from backend.storage_utils import safe_read_json, safe_update_json

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/lab_runtime_audit.json")


class RuntimeAuditRepository:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path

    def append(self, event: RuntimeAuditEvent) -> RuntimeAuditEvent:
        def _add(data: dict) -> dict:
            key = event.session_id
            if key not in data:
                data[key] = []
            data[key].append(event.model_dump(mode="json"))
            return data

        safe_update_json(self._path, _add)
        return event

    def list_by_session(self, session_id: str) -> list[RuntimeAuditEvent]:
        data = safe_read_json(self._path)
        result = []
        for raw in data.get(session_id, []):
            try:
                result.append(RuntimeAuditEvent.model_validate(raw))
            except Exception as exc:
                logger.error(
                    "RuntimeAuditRepository.list_by_session(%s) failed: %s",
                    session_id,
                    exc,
                )
        return result


class RuntimeAuditService:
    def __init__(self, repo: Optional[RuntimeAuditRepository] = None) -> None:
        self._repo = repo or RuntimeAuditRepository()

    def record(
        self,
        session_id: str,
        event_type: RuntimeAuditEventType,
        failure_reason: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        event = RuntimeAuditEvent(
            session_id=session_id,
            event_type=event_type,
            failure_reason=failure_reason,
            metadata=metadata or {},
        )
        try:
            self._repo.append(event)
        except Exception as exc:
            logger.error("RuntimeAuditService.record(%s, %s) failed: %s", session_id, event_type, exc)
