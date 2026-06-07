"""
Tests for backend.auth_deps

Covers FastAPI dependencies:
  - get_current_user: no token → 401, invalid session → 401, valid → username
  - get_current_user: Bearer token → Directus verify
  - get_current_user_optional: no token → None, valid → username
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_no_token_raises_401(self):
        """session_token と authorization が両方 None の場合 401 を返す（未ログイン）。"""
        from backend.auth_deps import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization=None, session_token=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_session_raises_401(self):
        """session_token 存在但 verify_session 返回 None 时必须抛 401（会话失效回归）。"""
        from backend.auth_deps import get_current_user

        with patch("backend.auth_deps.auth_manager") as mock_mgr:
            mock_mgr.verify_session.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization=None, session_token="expired-token")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_session_returns_username(self):
        """有效 session_token 必须返回对应用户名。"""
        from backend.auth_deps import get_current_user

        with patch("backend.auth_deps.auth_manager") as mock_mgr:
            mock_mgr.verify_session.return_value = "alice"
            result = await get_current_user(authorization=None, session_token="valid-token")
        assert result == "alice"

    @pytest.mark.asyncio
    async def test_bearer_token_calls_directus(self):
        """Authorization: Bearer <token> 时走 Directus 验证路径。"""
        from backend.auth_deps import get_current_user

        with patch("backend.auth_deps.verify_directus_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = ("alice", False)
            result = await get_current_user(authorization="Bearer valid-directus-token", session_token=None)
        assert result == "alice"
        mock_verify.assert_called_once_with("valid-directus-token")

    @pytest.mark.asyncio
    async def test_invalid_bearer_token_raises_401(self):
        """Directus token 验证失败时抛 401。"""
        from backend.auth_deps import get_current_user

        with patch("backend.auth_deps.verify_directus_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization="Bearer bad-token", session_token=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_bearer_takes_priority_over_cookie(self):
        """Bearer token 优先于 session cookie，两者都存在时用 Bearer。"""
        from backend.auth_deps import get_current_user

        with patch("backend.auth_deps.verify_directus_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = ("alice_directus", True)
            result = await get_current_user(
                authorization="Bearer directus-token",
                session_token="cookie-token",
            )
        assert result == "alice_directus"


class TestGetCurrentUserOptional:
    @pytest.mark.asyncio
    async def test_no_token_returns_none(self):
        """session_token 和 authorization 均为 None 时返回 None（可选认证端点回归）。"""
        from backend.auth_deps import get_current_user_optional

        result = await get_current_user_optional(authorization=None, session_token=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_session_returns_username(self):
        """有效 session_token 必须返回用户名。"""
        from backend.auth_deps import get_current_user_optional

        with patch("backend.auth_deps.auth_manager") as mock_mgr:
            mock_mgr.verify_session.return_value = "bob"
            result = await get_current_user_optional(authorization=None, session_token="valid-token")
        assert result == "bob"

    @pytest.mark.asyncio
    async def test_bearer_token_returns_username(self):
        """Bearer token 验证成功时返回用户名。"""
        from backend.auth_deps import get_current_user_optional

        with patch("backend.auth_deps.verify_directus_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = ("bob", False)
            result = await get_current_user_optional(
                authorization="Bearer valid-token", session_token=None
            )
        assert result == "bob"
