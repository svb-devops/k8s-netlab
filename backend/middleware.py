"""
K8S NetLab - Custom Middleware

RequestIDMiddleware: injects X-Request-ID into every request/response.
JsonFormatter: formats log records as single-line JSON for structured logging.
"""

import json
import logging
import traceback
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Attach a unique request-id to every HTTP request/response.

    - Reads X-Request-ID from the incoming request if present.
    - Otherwise generates a new UUID4.
    - Stores the id in request.state.request_id.
    - Echoes it back in the X-Request-ID response header.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class JsonFormatter(logging.Formatter):
    """
    Emit each log record as a single-line JSON object.

    Fields:
        timestamp  — ISO-8601 UTC
        level      — DEBUG / INFO / WARNING / ERROR / CRITICAL
        logger     — logger name
        message    — formatted log message
        exc_info   — traceback string (only when an exception is attached)
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = "".join(traceback.format_exception(*record.exc_info)).strip()
        return json.dumps(payload, ensure_ascii=False)
