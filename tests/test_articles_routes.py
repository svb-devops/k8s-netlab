"""HTTP integration tests for /api/articles/* routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.articles_routes import router

pytestmark = pytest.mark.static


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def _directus_list_resp(items):
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"data": items}
    return mock


def _directus_404():
    mock = MagicMock()
    mock.status_code = 404
    return mock


def _directus_created(item):
    mock = MagicMock()
    mock.status_code = 201
    mock.json.return_value = {"data": item}
    return mock


# ── GET /api/articles ─────────────────────────────────────────────────────────

class TestListArticles:
    def test_returns_empty_list_when_no_articles(self, client):
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.httpx.AsyncClient") as mock_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mc = AsyncMock()
            mc.get = AsyncMock(return_value=_directus_list_resp([]))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get("/api/articles")
        assert resp.status_code == 200
        assert resp.json()["articles"] == []

    def test_returns_articles_list(self, client):
        articles = [
            {"id": 1, "slug": "hello", "title": "Hello", "excerpt": "...", "published_at": "2026-01-01T00:00:00"},
        ]
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.httpx.AsyncClient") as mock_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mc = AsyncMock()
            mc.get = AsyncMock(return_value=_directus_list_resp(articles))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get("/api/articles")
        assert resp.status_code == 200
        assert len(resp.json()["articles"]) == 1
        assert resp.json()["articles"][0]["slug"] == "hello"

    def test_returns_503_when_directus_not_configured(self, client):
        with patch("backend.articles_routes.config") as cfg:
            cfg.DIRECTUS_URL = ""
            resp = client.get("/api/articles")
        assert resp.status_code == 503

    def test_returns_503_on_network_error(self, client):
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.httpx.AsyncClient") as mock_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mc = AsyncMock()
            mc.get = AsyncMock(side_effect=Exception("timeout"))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get("/api/articles")
        assert resp.status_code == 503


# ── GET /api/articles/{slug} ──────────────────────────────────────────────────

class TestGetArticle:
    def _setup_mock(self, mock_cls, article_items, comment_items):
        mc = AsyncMock()
        responses = [
            _directus_list_resp(article_items),
            _directus_list_resp(comment_items),
        ]
        mc.get = AsyncMock(side_effect=responses)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        return mc

    def test_returns_article_with_comments(self, client):
        article = {"id": 1, "slug": "hello", "title": "Hello", "excerpt": "x",
                   "content": "# content", "published_at": "2026-01-01T00:00:00"}
        comments = [{"id": 1, "author": "alice", "content": "great!", "created_at": "2026-01-02T00:00:00"}]
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.httpx.AsyncClient") as mock_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            self._setup_mock(mock_cls, [article], comments)
            resp = client.get("/api/articles/hello")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Hello"
        assert data["content"] == "# content"
        assert len(data["comments"]) == 1
        assert data["comments"][0]["author"] == "alice"

    def test_returns_404_when_article_not_found(self, client):
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.httpx.AsyncClient") as mock_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mc = AsyncMock()
            mc.get = AsyncMock(return_value=_directus_list_resp([]))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get("/api/articles/nonexistent")
        assert resp.status_code == 404


# ── POST /api/articles/{slug}/comments ───────────────────────────────────────

class TestPostComment:
    def test_authenticated_user_can_comment(self, client):
        article = {"id": 1, "slug": "hello", "title": "Hello",
                   "excerpt": "", "content": "", "published_at": None}
        new_comment = {"id": 5, "author": "alice", "content": "nice", "created_at": "2026-01-01T00:00:00"}

        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.httpx.AsyncClient") as mock_cls, \
             patch("backend.articles_routes.auth_manager") as mock_auth:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_auth.verify_session.return_value = "alice"

            mc = AsyncMock()
            mc.get = AsyncMock(return_value=_directus_list_resp([article]))
            mc.post = AsyncMock(return_value=_directus_created(new_comment))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            client.cookies.set("session_token", "valid-token")
            resp = client.post("/api/articles/hello/comments", json={"content": "nice"})

        assert resp.status_code == 201
        assert resp.json()["success"] is True
        assert resp.json()["comment"]["author"] == "alice"

    def test_unauthenticated_user_gets_401(self, client):
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.auth_manager") as mock_auth:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_auth.verify_session.return_value = None
            resp = client.post("/api/articles/hello/comments", json={"content": "hi"})
        assert resp.status_code == 401

    def test_empty_content_rejected(self, client):
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.auth_manager") as mock_auth:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_auth.verify_session.return_value = "alice"
            client.cookies.set("session_token", "valid-token")
            resp = client.post("/api/articles/hello/comments", json={"content": ""})
        assert resp.status_code == 422

    def test_comment_on_nonexistent_article_returns_404(self, client):
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.httpx.AsyncClient") as mock_cls, \
             patch("backend.articles_routes.auth_manager") as mock_auth:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mock_auth.verify_session.return_value = "alice"
            mc = AsyncMock()
            mc.get = AsyncMock(return_value=_directus_list_resp([]))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.cookies.set("session_token", "valid-token")
            resp = client.post("/api/articles/missing/comments", json={"content": "hi"})
        assert resp.status_code == 404
