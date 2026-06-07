"""Unit tests for backend/directus_client.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.static


# ── helpers ───────────────────────────────────────────────────────────────────

def _resp(status_code: int, payload: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = payload
    return mock


# ── fetch_experiment_list ─────────────────────────────────────────────────────

class TestFetchExperimentList:
    @pytest.mark.asyncio
    async def test_returns_none_when_directus_url_unset(self):
        with patch("backend.directus_client.config") as cfg:
            cfg.DIRECTUS_URL = ""
            from backend.directus_client import fetch_experiment_list
            result = await fetch_experiment_list()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_list_on_success(self):
        directus_items = [
            {"slug": "01", "title": "K8s 基础", "difficulty": 2,
             "duration": "30 分钟", "phase": 1, "sort_order": 1},
            {"slug": "02", "title": "Pod 网络", "difficulty": 3,
             "duration": "40 分钟", "phase": 1, "sort_order": 2},
        ]
        resp = _resp(200, {"data": directus_items})

        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import fetch_experiment_list
            result = await fetch_experiment_list()

        assert result is not None
        assert len(result) == 2
        assert result[0] == {"id": "01", "title": "K8s 基础", "difficulty": 2,
                             "duration": "30 分钟", "phase": 1}
        assert result[1]["id"] == "02"

    @pytest.mark.asyncio
    async def test_returns_none_on_http_error(self):
        resp = _resp(500, {})
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import fetch_experiment_list
            result = await fetch_experiment_list()

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_exception(self):
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import fetch_experiment_list
            result = await fetch_experiment_list()

        assert result is None


# ── fetch_experiment_detail ───────────────────────────────────────────────────

class TestFetchExperimentDetail:
    @pytest.mark.asyncio
    async def test_returns_none_when_directus_url_unset(self):
        with patch("backend.directus_client.config") as cfg:
            cfg.DIRECTUS_URL = ""
            from backend.directus_client import fetch_experiment_detail
            result = await fetch_experiment_detail("01")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_detail_on_success(self):
        item = {
            "slug": "01", "title": "K8s 基础", "difficulty": 2,
            "duration": "30 分钟", "phase": 1,
            "background": "## 背景", "content": "# 实验内容",
        }
        resp = _resp(200, {"data": [item]})
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import fetch_experiment_detail
            result = await fetch_experiment_detail("01")

        assert result is not None
        assert result["id"] == "01"
        assert result["title"] == "K8s 基础"
        assert result["content"] == "# 实验内容"
        assert result["background"] == "## 背景"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        resp = _resp(200, {"data": []})
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import fetch_experiment_detail
            result = await fetch_experiment_detail("99")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_http_error(self):
        resp = _resp(503, {})
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import fetch_experiment_detail
            result = await fetch_experiment_detail("01")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_exception(self):
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=ConnectionError("timeout"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import fetch_experiment_detail
            result = await fetch_experiment_detail("01")

        assert result is None


# ── directus_auth_login ───────────────────────────────────────────────────────

class TestDirectusAuthLogin:
    @pytest.mark.asyncio
    async def test_returns_none_when_directus_url_unset(self):
        with patch("backend.directus_client.config") as cfg:
            cfg.DIRECTUS_URL = ""
            from backend.directus_client import directus_auth_login
            result = await directus_auth_login("alice", "pw")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_token_on_success(self):
        resp = _resp(200, {"data": {"access_token": "tok123"}})
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import directus_auth_login
            result = await directus_auth_login("alice", "correct")

        assert result == "tok123"
        # Verify email format
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"]["email"] == "alice@lab.cloudnetops.tech"

    @pytest.mark.asyncio
    async def test_returns_none_on_invalid_credentials(self):
        resp = _resp(401, {"errors": [{"message": "Invalid credentials"}]})
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import directus_auth_login
            result = await directus_auth_login("alice", "wrong")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_exception(self):
        with patch("backend.directus_client.config") as cfg, \
             patch("backend.directus_client.httpx.AsyncClient") as mock_client_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("timeout"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.directus_client import directus_auth_login
            result = await directus_auth_login("alice", "pw")

        assert result is None
