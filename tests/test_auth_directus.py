"""
Tests for backend.auth_directus

Covers Directus token verification with cache behaviour.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


pytestmark = pytest.mark.static


class TestVerifyDirectusToken:
    @pytest.mark.asyncio
    async def test_returns_none_when_directus_url_not_set(self):
        """DIRECTUS_URL が空の場合は None を返す（Directus 無効）。"""
        with patch("backend.auth_directus.config") as mock_cfg:
            mock_cfg.DIRECTUS_URL = ""
            mock_cfg.DIRECTUS_TOKEN_CACHE_TTL = 60
            from backend.auth_directus import verify_directus_token
            result = await verify_directus_token("some-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_username_and_is_admin_on_valid_token(self):
        """Directus /users/me が 200 を返すと (username, is_admin) タプルを返す。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "first_name": "alice",
                "email": "alice@lab.cloudnetops.tech",
                "role": {"name": "Student"},
            }
        }

        with patch("backend.auth_directus.config") as mock_cfg, \
             patch("backend.auth_directus._cache", {}), \
             patch("backend.auth_directus.httpx.AsyncClient") as mock_client_cls:
            mock_cfg.DIRECTUS_URL = "http://127.0.0.1:8055"
            mock_cfg.DIRECTUS_TOKEN_CACHE_TTL = 60
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from backend.auth_directus import verify_directus_token
            result = await verify_directus_token("valid-token")

        assert result == ("alice", False)

    @pytest.mark.asyncio
    async def test_admin_role_sets_is_admin_true(self):
        """role.name が 'Administrator' のとき is_admin=True を返す。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "first_name": "admin",
                "email": "admin@cloudnetops.tech",
                "role": {"name": "Administrator"},
            }
        }

        with patch("backend.auth_directus.config") as mock_cfg, \
             patch("backend.auth_directus._cache", {}), \
             patch("backend.auth_directus.httpx.AsyncClient") as mock_client_cls:
            mock_cfg.DIRECTUS_URL = "http://127.0.0.1:8055"
            mock_cfg.DIRECTUS_TOKEN_CACHE_TTL = 60
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from backend.auth_directus import verify_directus_token
            result = await verify_directus_token("admin-token")

        assert result is not None
        _, is_admin = result
        assert is_admin is True

    @pytest.mark.asyncio
    async def test_returns_none_on_401(self):
        """Directus が 401 を返すと None を返す（トークン無効）。"""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("backend.auth_directus.config") as mock_cfg, \
             patch("backend.auth_directus._cache", {}), \
             patch("backend.auth_directus.httpx.AsyncClient") as mock_client_cls:
            mock_cfg.DIRECTUS_URL = "http://127.0.0.1:8055"
            mock_cfg.DIRECTUS_TOKEN_CACHE_TTL = 60
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from backend.auth_directus import verify_directus_token
            result = await verify_directus_token("bad-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        """ネットワークエラー発生時は None を返す（Directus 未起動でもサービス継続）。"""
        with patch("backend.auth_directus.config") as mock_cfg, \
             patch("backend.auth_directus._cache", {}), \
             patch("backend.auth_directus.httpx.AsyncClient") as mock_client_cls:
            mock_cfg.DIRECTUS_URL = "http://127.0.0.1:8055"
            mock_cfg.DIRECTUS_TOKEN_CACHE_TTL = 60
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            mock_client_cls.return_value = mock_client

            from backend.auth_directus import verify_directus_token
            result = await verify_directus_token("any-token")

        assert result is None


class TestEvictToken:
    def test_evict_removes_cached_entry(self):
        """evict_token は指定トークンのキャッシュエントリを削除する。"""
        import time
        from backend.auth_directus import _CacheEntry, _cache, evict_token

        _cache["test-token"] = _CacheEntry(
            username="alice", email="alice@test.com", is_admin=False,
            expires_at=time.monotonic() + 60
        )
        evict_token("test-token")
        assert "test-token" not in _cache

    def test_evict_nonexistent_token_is_noop(self):
        """存在しないトークンの evict はエラーなしで無視される。"""
        from backend.auth_directus import evict_token
        evict_token("nonexistent-token")  # should not raise
