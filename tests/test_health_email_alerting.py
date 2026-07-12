"""
Tests for Resend email send-failure alerting in /api/health.

Previously a Resend send failure only produced a `logger.warning` line —
nobody gets paged for a log line, so a long-term send outage (e.g. a
revoked API key or exhausted quota) went unnoticed until a student
complained. /api/health now surfaces recent failures (backend/email_client.py
records them; this file adds the read-side aggregation).

Validates:
  - "email" section present in /api/health response
  - status is "ok" when no recent failures
  - status is "degraded" once failures_last_24h crosses the threshold
  - failures older than 24h are not counted
  - health check never exposes email addresses or failure detail beyond a count
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.static


def _write_failures(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"failures": entries}))


class TestEmailHealth:
    def _call(self, monkeypatch: pytest.MonkeyPatch, failure_log: Path) -> dict[str, Any]:
        import backend.email_client as email_mod
        from backend.api_routes import _check_email_health

        monkeypatch.setattr(email_mod, "_FAILURE_LOG", failure_log)
        return _check_email_health()

    def test_status_ok_when_no_failure_log(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        result = self._call(monkeypatch, tmp_path / "email_send_failures.json")
        assert result["status"] == "ok"
        assert result["failures_last_24h"] == 0
        assert result["warnings"] == []

    def test_status_ok_below_threshold(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        failure_log = tmp_path / "email_send_failures.json"
        now = datetime.now(timezone.utc)
        _write_failures(failure_log, [
            {"timestamp": now.isoformat(), "reason": "http_422"},
            {"timestamp": now.isoformat(), "reason": "http_422"},
        ])
        result = self._call(monkeypatch, failure_log)
        assert result["status"] == "ok"
        assert result["failures_last_24h"] == 2

    def test_status_degraded_at_threshold(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        failure_log = tmp_path / "email_send_failures.json"
        now = datetime.now(timezone.utc)
        _write_failures(failure_log, [
            {"timestamp": now.isoformat(), "reason": "http_500"} for _ in range(3)
        ])
        result = self._call(monkeypatch, failure_log)
        assert result["status"] == "degraded"
        assert result["failures_last_24h"] == 3
        assert any("3" in w for w in result["warnings"])

    def test_failures_older_than_24h_not_counted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        failure_log = tmp_path / "email_send_failures.json"
        stale = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        _write_failures(failure_log, [
            {"timestamp": stale, "reason": "http_500"} for _ in range(5)
        ])
        result = self._call(monkeypatch, failure_log)
        assert result["status"] == "ok"
        assert result["failures_last_24h"] == 0

    def test_never_exposes_email_addresses_or_raw_entries(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        failure_log = tmp_path / "email_send_failures.json"
        now = datetime.now(timezone.utc)
        _write_failures(failure_log, [
            {"timestamp": now.isoformat(), "reason": "network_error: student@example.com unreachable"}
        ])
        result = self._call(monkeypatch, failure_log)
        assert "student@example.com" not in json.dumps(result)
        assert "failures" not in result  # only the aggregate count, not raw entries


class TestHealthEndpointIncludesEmailSection:
    @pytest.fixture(scope="module")
    def app(self):
        from backend.main import app as _app
        return _app

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_health_response_has_email_section(self, client) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "email" in body
        assert "status" in body["email"]
        assert "failures_last_24h" in body["email"]
