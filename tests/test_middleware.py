"""Tests for custom middleware: RequestIDMiddleware and JsonFormatter."""

import json
import logging
import uuid
from io import StringIO
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware import RequestIDMiddleware, JsonFormatter


# ============================================================
# RequestIDMiddleware tests
# ============================================================

@pytest.fixture
def app_with_middleware():
    """Minimal FastAPI app with RequestIDMiddleware."""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def test_request_id_header_present(app_with_middleware):
    """Every response must include X-Request-ID."""
    client = TestClient(app_with_middleware)
    resp = client.get("/ping")
    assert "x-request-id" in resp.headers


def test_request_id_is_valid_uuid4(app_with_middleware):
    """The generated request-id must be a valid UUID4."""
    client = TestClient(app_with_middleware)
    resp = client.get("/ping")
    rid = resp.headers["x-request-id"]
    parsed = uuid.UUID(rid)
    assert parsed.version == 4


def test_request_id_unique_per_request(app_with_middleware):
    """Each request gets a distinct request-id."""
    client = TestClient(app_with_middleware)
    ids = {client.get("/ping").headers["x-request-id"] for _ in range(5)}
    assert len(ids) == 5


def test_client_supplied_request_id_is_echoed(app_with_middleware):
    """If the client sends X-Request-ID, the same value is echoed back."""
    client = TestClient(app_with_middleware)
    custom_id = str(uuid.uuid4())
    resp = client.get("/ping", headers={"X-Request-ID": custom_id})
    assert resp.headers["x-request-id"] == custom_id


# ============================================================
# JsonFormatter tests
# ============================================================

def test_json_formatter_outputs_valid_json():
    """JsonFormatter must emit one valid JSON object per log record."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("test.json_formatter")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False

    log.info("hello world")

    output = stream.getvalue().strip()
    parsed = json.loads(output)
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert "timestamp" in parsed
    assert "logger" in parsed


def test_json_formatter_includes_exc_info():
    """JsonFormatter must include exc_info when an exception is logged."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("test.json_formatter_exc")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False

    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("caught error")

    parsed = json.loads(stream.getvalue().strip())
    assert "exc_info" in parsed
    assert "ValueError" in parsed["exc_info"]


# ============================================================
# SecurityHeadersMiddleware tests
# ============================================================

from backend.middleware import SecurityHeadersMiddleware  # noqa: E402


@pytest.fixture
def app_with_security_headers():
    """Minimal FastAPI app with SecurityHeadersMiddleware."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def test_security_headers_x_content_type(app_with_security_headers):
    """X-Content-Type-Options: nosniff must be set on every response."""
    client = TestClient(app_with_security_headers)
    resp = client.get("/ping")
    assert resp.headers.get("x-content-type-options") == "nosniff"


def test_security_headers_x_frame_options(app_with_security_headers):
    """X-Frame-Options: DENY must be set on every response."""
    client = TestClient(app_with_security_headers)
    resp = client.get("/ping")
    assert resp.headers.get("x-frame-options") == "DENY"


def test_security_headers_referrer_policy(app_with_security_headers):
    """Referrer-Policy must be set on every response."""
    client = TestClient(app_with_security_headers)
    resp = client.get("/ping")
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_security_headers_csp_present(app_with_security_headers):
    """Content-Security-Policy must be present."""
    client = TestClient(app_with_security_headers)
    resp = client.get("/ping")
    csp = resp.headers.get("content-security-policy", "")
    assert csp, "Content-Security-Policy header is missing"
    assert "default-src" in csp


def test_security_headers_csp_blocks_objects(app_with_security_headers):
    """CSP must include object-src 'none' to block Flash/ActiveX."""
    client = TestClient(app_with_security_headers)
    resp = client.get("/ping")
    csp = resp.headers.get("content-security-policy", "")
    assert "object-src 'none'" in csp


def test_csp_script_src_does_not_contain_unsafe_inline(app_with_security_headers):
    """script-src 不得包含 'unsafe-inline'——防止 XSS 脚本注入（N 回归）。
    注：style-src 允许 'unsafe-inline' 以支持 Tailwind CDN 动态样式注入。"""
    client = TestClient(app_with_security_headers)
    resp = client.get("/ping")
    csp = resp.headers.get("content-security-policy", "")
    # 提取 script-src 指令并单独检查
    script_src = next((d.strip() for d in csp.split(";") if "script-src" in d), "")
    assert "'unsafe-inline'" not in script_src, (
        f"script-src must not contain 'unsafe-inline'. Got: {script_src}"
    )


def test_csp_style_src_allows_unsafe_inline_for_tailwind(app_with_security_headers):
    """style-src 必须包含 'unsafe-inline' — Tailwind Play CDN 通过动态注入 <style> 标签工作，
    缺少此指令会导致所有 Tailwind 样式被 CSP 拦截，页面视觉完全崩溃（回归）。"""
    client = TestClient(app_with_security_headers)
    resp = client.get("/ping")
    csp = resp.headers.get("content-security-policy", "")
    style_src = next((d.strip() for d in csp.split(";") if "style-src" in d), "")
    assert "'unsafe-inline'" in style_src, (
        f"style-src must contain 'unsafe-inline' for Tailwind CDN. Got: {style_src}"
    )


# ============================================================
# M 回归：请求日志包含 duration_ms 和 status_code
# ============================================================

def test_request_log_includes_duration_ms_and_status_code():
    """RequestIDMiddleware 必须将每个请求的 duration_ms 和 status_code 写入 JSON 日志（M 回归）。"""
    from io import StringIO
    from backend.middleware import RequestIDMiddleware, JsonFormatter

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    req_logger = logging.getLogger("backend.middleware")
    req_logger.addHandler(handler)
    req_logger.setLevel(logging.DEBUG)
    req_logger.propagate = False

    client = TestClient(app)
    client.get("/ping")

    req_logger.removeHandler(handler)

    lines = [line for line in stream.getvalue().strip().split("\n") if line]
    http_log = None
    for line in lines:
        parsed = json.loads(line)
        if "duration_ms" in parsed:
            http_log = parsed
            break

    assert http_log is not None, "No HTTP request log line with 'duration_ms' found"
    assert "status_code" in http_log, "HTTP log must include 'status_code'"
    assert http_log["status_code"] == 200
    assert isinstance(http_log["duration_ms"], (int, float))
    assert http_log["duration_ms"] >= 0


def test_json_formatter_does_not_raise_on_non_serializable_extra():
    """JsonFormatter.format() 对非 JSON 可序列化的 extra 字段不得抛 TypeError，
    否则 Python logging 会静默丢弃整条日志记录（日志丢失回归）。"""
    from datetime import datetime as _dt

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("test.non_serializable_extra")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False

    # datetime is not JSON-serializable by default; must not crash
    log.info("timestamp event", extra={"ts": _dt.now()})
    log.removeHandler(handler)

    output = stream.getvalue().strip()
    assert output, (
        "Log record was silently dropped — JsonFormatter likely raised TypeError "
        "on non-serializable extra field. Add default=str to json.dumps."
    )
    parsed = json.loads(output)
    assert parsed["message"] == "timestamp event"
    assert "ts" in parsed


def test_json_formatter_includes_extra_fields():
    """JsonFormatter 必须将 logger.info(extra={...}) 中的字段合并到输出 JSON（M 回归）。"""
    from io import StringIO
    from backend.middleware import JsonFormatter

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("test.extra_fields")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False

    log.info("request complete", extra={"status_code": 201, "duration_ms": 42.5})
    log.removeHandler(handler)

    parsed = json.loads(stream.getvalue().strip())
    assert parsed["status_code"] == 201
    assert parsed["duration_ms"] == 42.5
