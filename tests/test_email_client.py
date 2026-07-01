"""Unit tests for backend/email_client.py."""

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
