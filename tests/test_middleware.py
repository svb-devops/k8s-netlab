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
