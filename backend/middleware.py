"""
K8S NetLab - Custom Middleware

RequestIDMiddleware: injects X-Request-ID into every request/response.
JsonFormatter: formats log records as single-line JSON for structured logging.
"""

import json
import logging
import time
import traceback
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_request_logger = logging.getLogger(__name__)

# Standard LogRecord attributes to exclude when merging extra fields
_LOGRECORD_ATTRS = frozenset({
    "name", "msg", "args", "created", "filename", "funcName", "levelname",
    "levelno", "lineno", "module", "msecs", "message", "pathname", "process",
    "processName", "relativeCreated", "stack_info", "thread", "threadName",
    "exc_info", "exc_text", "taskName",
})


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Attach a unique request-id to every HTTP request/response and log each
    request with method, path, status_code, and duration_ms.

    - Reads X-Request-ID from the incoming request if present.
    - Otherwise generates a new UUID4.
    - Stores the id in request.state.request_id.
    - Echoes it back in the X-Request-ID response header.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        _request_logger.info(
            f"{request.method} {request.url.path} {response.status_code}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "request_id": request_id,
            },
        )
        return response


_CSP = (
    "default-src 'self'; "
    "script-src 'self' cdn.tailwindcss.com cdn.jsdelivr.net; "
    "style-src 'self' cdn.jsdelivr.net; "
    # same-origin fetch + WebSocket (ws/wss to the same host)
    "connect-src 'self' ws: wss:; "
    "img-src 'self' data:; "
    "font-src 'self' cdn.jsdelivr.net; "
    # Harden against plugin exploits and base-tag injection
    "object-src 'none'; "
    "base-uri 'self';"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Attach defensive HTTP security headers to every response.

    Headers applied:
      - X-Content-Type-Options: nosniff        — prevent MIME sniffing
      - X-Frame-Options: DENY                  — prevent clickjacking
      - Referrer-Policy: strict-origin-when-cross-origin
      - Content-Security-Policy                — restrict resource origins
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
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
        # Merge any extra fields passed via logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key not in _LOGRECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)
