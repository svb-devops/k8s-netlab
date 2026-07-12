"""Unit tests for backend/email_client.py."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.static


def _resp(status_code: int, payload: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = payload
    return mock


class TestSendVerificationEmail:
    @pytest.mark.asyncio
    async def test_returns_false_when_resend_api_key_unset(self):
        with patch("backend.email_client.config") as cfg:
            cfg.RESEND_API_KEY = ""
            from backend.email_client import send_verification_email
            result = await send_verification_email("student@example.com", "123456")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        resp = _resp(200, {"id": "email_abc123"})
        with patch("backend.email_client.config") as cfg, \
             patch("backend.email_client.httpx.AsyncClient") as mock_client_cls:
            cfg.RESEND_API_KEY = "re_test_key"
            cfg.RESEND_FROM_EMAIL = "onboarding@resend.dev"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.email_client import send_verification_email
            result = await send_verification_email("student@example.com", "123456")

        assert result is True
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer re_test_key"
        body = call_kwargs.kwargs["json"]
        assert body["to"] == ["student@example.com"]
        assert body["from"] == "onboarding@resend.dev"
        assert "123456" in body["html"]

    @pytest.mark.asyncio
    async def test_returns_false_on_http_error(self):
        resp = _resp(422, {"message": "invalid recipient"})
        with patch("backend.email_client.config") as cfg, \
             patch("backend.email_client.httpx.AsyncClient") as mock_client_cls:
            cfg.RESEND_API_KEY = "re_test_key"
            cfg.RESEND_FROM_EMAIL = "onboarding@resend.dev"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.email_client import send_verification_email
            result = await send_verification_email("student@example.com", "123456")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_network_exception(self):
        with patch("backend.email_client.config") as cfg, \
             patch("backend.email_client.httpx.AsyncClient") as mock_client_cls:
            cfg.RESEND_API_KEY = "re_test_key"
            cfg.RESEND_FROM_EMAIL = "onboarding@resend.dev"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.email_client import send_verification_email
            result = await send_verification_email("student@example.com", "123456")

        assert result is False


# ============================================================
# Failure recording — feeds the /api/health admin alert
# ============================================================
# Previously a Resend send failure only produced a `logger.warning` line —
# nobody gets paged for a log line, so long-term send outages (e.g. a
# revoked API key) went unnoticed until a student complained. These
# failures must now persist to a small file so /api/health can surface
# them (see tests/test_health_email_alerting.py).

class TestFailureLogIsolation:
    def test_default_failure_log_is_not_the_production_path(self):
        """A test that triggers a failure without explicitly patching
        _FAILURE_LOG must not write to the real production
        data/email_send_failures.json — the tests/conftest.py autouse
        fixture must redirect it for every test in the suite, otherwise
        running `pytest tests/test_email_client.py` pollutes prod data."""
        import backend.email_client as email_client_mod

        real_prod_path = (
            Path(email_client_mod.__file__).parent.parent / "data" / "email_send_failures.json"
        )
        assert email_client_mod._FAILURE_LOG != real_prod_path

    @pytest.mark.asyncio
    async def test_failure_without_explicit_patch_does_not_touch_production_file(self):
        import backend.email_client as email_client_mod

        real_prod_path = (
            Path(email_client_mod.__file__).parent.parent / "data" / "email_send_failures.json"
        )
        before = real_prod_path.read_text() if real_prod_path.exists() else None

        with patch("backend.email_client.config") as cfg, \
             patch("backend.email_client.httpx.AsyncClient") as mock_client_cls:
            cfg.RESEND_API_KEY = "re_test_key"
            cfg.RESEND_FROM_EMAIL = "onboarding@resend.dev"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.email_client import send_verification_email
            await send_verification_email("student@example.com", "123456")

        after = real_prod_path.read_text() if real_prod_path.exists() else None
        assert before == after, "production email_send_failures.json must not change"


class TestFailureRecording:
    @pytest.mark.asyncio
    async def test_network_exception_records_failure(self, tmp_path):
        failure_log = tmp_path / "email_send_failures.json"
        with patch("backend.email_client.config") as cfg, \
             patch("backend.email_client.httpx.AsyncClient") as mock_client_cls, \
             patch("backend.email_client._FAILURE_LOG", failure_log):
            cfg.RESEND_API_KEY = "re_test_key"
            cfg.RESEND_FROM_EMAIL = "onboarding@resend.dev"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.email_client import send_verification_email
            await send_verification_email("student@example.com", "123456")

        assert failure_log.exists()
        data = json.loads(failure_log.read_text())
        assert len(data["failures"]) == 1
        assert "timestamp" in data["failures"][0]

    @pytest.mark.asyncio
    async def test_http_error_records_failure(self, tmp_path):
        failure_log = tmp_path / "email_send_failures.json"
        resp = _resp(422, {"message": "invalid recipient"})
        with patch("backend.email_client.config") as cfg, \
             patch("backend.email_client.httpx.AsyncClient") as mock_client_cls, \
             patch("backend.email_client._FAILURE_LOG", failure_log):
            cfg.RESEND_API_KEY = "re_test_key"
            cfg.RESEND_FROM_EMAIL = "onboarding@resend.dev"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.email_client import send_verification_email
            await send_verification_email("student@example.com", "123456")

        data = json.loads(failure_log.read_text())
        assert len(data["failures"]) == 1
        assert "422" in data["failures"][0]["reason"]

    @pytest.mark.asyncio
    async def test_success_does_not_record_failure(self, tmp_path):
        failure_log = tmp_path / "email_send_failures.json"
        resp = _resp(200, {"id": "email_abc123"})
        with patch("backend.email_client.config") as cfg, \
             patch("backend.email_client.httpx.AsyncClient") as mock_client_cls, \
             patch("backend.email_client._FAILURE_LOG", failure_log):
            cfg.RESEND_API_KEY = "re_test_key"
            cfg.RESEND_FROM_EMAIL = "onboarding@resend.dev"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.email_client import send_verification_email
            await send_verification_email("student@example.com", "123456")

        assert not failure_log.exists()

    @pytest.mark.asyncio
    async def test_old_failures_pruned_after_24h(self, tmp_path):
        from datetime import datetime, timedelta, timezone

        failure_log = tmp_path / "email_send_failures.json"
        stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        failure_log.write_text(json.dumps({"failures": [{"timestamp": stale, "reason": "old"}]}))

        with patch("backend.email_client.config") as cfg, \
             patch("backend.email_client.httpx.AsyncClient") as mock_client_cls, \
             patch("backend.email_client._FAILURE_LOG", failure_log):
            cfg.RESEND_API_KEY = "re_test_key"
            cfg.RESEND_FROM_EMAIL = "onboarding@resend.dev"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.email_client import send_verification_email
            await send_verification_email("student@example.com", "123456")

        data = json.loads(failure_log.read_text())
        assert len(data["failures"]) == 1
        assert data["failures"][0]["reason"] != "old"
