"""
K8S NetLab - Public Articles API

GET  /api/articles                      — list published articles (public)
GET  /api/articles/{slug}               — article detail + comments (public)
GET  /api/articles/{slug}/lab-cta       — reader-safe lab CTA for article (public)
POST /api/articles/{slug}/comments      — post a comment (login required)
"""

import logging
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import config
from backend.auth import auth_manager
from backend.auth_directus import verify_directus_token

if TYPE_CHECKING:
    from backend.labgen.models import LabDraft
    from backend.labgen.repository import LabDraftRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/articles", tags=["articles"])

_DIRECTUS_TIMEOUT = 5.0
_LIST_FIELDS = "id,slug,title,excerpt,published_at"
_DETAIL_FIELDS = "id,slug,title,excerpt,content,published_at"
_COMMENT_FIELDS = "id,author,content,created_at"


# ── helpers ────────────────────────────────────────────────────────────────────

async def _directus_get(path: str, params: dict) -> Optional[dict]:
    if not config.DIRECTUS_URL:
        raise HTTPException(status_code=503, detail="CMS 未配置")
    try:
        async with httpx.AsyncClient(timeout=_DIRECTUS_TIMEOUT) as client:
            resp = await client.get(f"{config.DIRECTUS_URL}{path}", params=params)
    except Exception as exc:
        logger.warning("Directus GET %s failed: %s", path, exc)
        raise HTTPException(status_code=503, detail="CMS 暂时不可用")
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="CMS 返回错误")
    return cast(dict[Any, Any], resp.json())


async def _directus_post(path: str, payload: dict[str, Any]) -> dict[Any, Any]:
    if not config.DIRECTUS_URL:
        raise HTTPException(status_code=503, detail="CMS 未配置")
    try:
        async with httpx.AsyncClient(timeout=_DIRECTUS_TIMEOUT) as client:
            resp = await client.post(f"{config.DIRECTUS_URL}{path}", json=payload)
    except Exception as exc:
        logger.warning("Directus POST %s failed: %s", path, exc)
        raise HTTPException(status_code=503, detail="CMS 暂时不可用")
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="评论提交失败")
    return cast(dict[Any, Any], resp.json())


async def _resolve_user(
    authorization: Optional[str],
    session_token: Optional[str],
) -> Optional[str]:
    """Return username from Bearer token or session cookie, or None."""
    if authorization and authorization.startswith("Bearer "):
        result = await verify_directus_token(authorization[7:])
        if result:
            return result[0]
        return None
    if session_token:
        return auth_manager.verify_session(session_token)
    return None


# ── models ─────────────────────────────────────────────────────────────────────

class CommentRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


# ── routes ─────────────────────────────────────────────────────────────────────

@router.get("", summary="List published articles")
async def list_articles() -> JSONResponse:
    data = await _directus_get("/items/articles", {
        "filter[status][_eq]": "published",
        "fields": _LIST_FIELDS,
        "sort": "-published_at",
    })
    return JSONResponse({"articles": data.get("data", []) if data else []})


@router.get("/{slug}", summary="Get article detail with comments")
async def get_article(slug: str) -> JSONResponse:
    # Article
    data = await _directus_get("/items/articles", {
        "filter[slug][_eq]": slug,
        "filter[status][_eq]": "published",
        "fields": _DETAIL_FIELDS,
        "limit": "1",
    })
    items = data.get("data", []) if data else []
    if not items:
        raise HTTPException(status_code=404, detail="文章不存在")
    article = items[0]

    # Comments
    comments_data = await _directus_get("/items/comments", {
        "filter[article_id][_eq]": str(article["id"]),
        "filter[status][_eq]": "published",
        "fields": _COMMENT_FIELDS,
        "sort": "created_at",
    })
    article["comments"] = comments_data.get("data", []) if comments_data else []

    return JSONResponse(article)


@router.post("/{slug}/comments", summary="Post a comment (login required)")
async def post_comment(
    slug: str,
    body: CommentRequest,
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
) -> JSONResponse:
    username = await _resolve_user(authorization, session_token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请登录后再评论",
        )

    # Get article id
    data = await _directus_get("/items/articles", {
        "filter[slug][_eq]": slug,
        "filter[status][_eq]": "published",
        "fields": "id",
        "limit": "1",
    })
    items = data.get("data", []) if data else []
    if not items:
        raise HTTPException(status_code=404, detail="文章不存在")
    article_id = items[0]["id"]

    result = await _directus_post("/items/comments", {
        "article_id": article_id,
        "author": username,
        "content": body.content,
        "status": "published",
    })

    comment = result.get("data", {})
    return JSONResponse({"success": True, "comment": comment}, status_code=201)


# ---------------------------------------------------------------------------
# GET /api/articles/{slug}/lab-cta — reader-safe lab CTA lookup
# ---------------------------------------------------------------------------


class ArticleLabCTAResponse(BaseModel):
    """Reader-safe lab CTA response — never contains source_article_id or raw text."""
    has_cta: bool
    lab_id: Optional[str] = None
    lab_title: Optional[str] = None
    lab_summary: Optional[str] = None
    difficulty: Optional[str] = None
    estimated_duration: Optional[int] = None
    domain: Optional[str] = None
    cta_url: Optional[str] = None
    cta_text: str = "进入实验"
    sandbox_note: str = "实验运行在临时隔离环境中，完成后自动销毁。"
    cleanup_note: str = "完成实验后环境自动清理，数据不保留。"


def get_lab_draft_repository() -> "LabDraftRepository":
    """FastAPI dependency — override in tests via app.dependency_overrides."""
    from backend.labgen.routes import get_repository
    return get_repository()


def _find_lab_by_article_slug(slug: str, repo: "LabDraftRepository") -> Optional["LabDraft"]:
    """Return the first PUBLISHED+cta_enabled draft whose article_url slug param matches."""
    from backend.labgen.models import LabDraft as _LabDraft, PublishStatus
    for draft in repo.list_all():
        if draft.publish_status != PublishStatus.PUBLISHED:
            continue
        if not getattr(draft, "cta_enabled", False):
            continue
        article_url = getattr(draft, "article_url", None) or ""
        if not article_url:
            continue
        try:
            qs = parse_qs(urlparse(article_url).query)
            if qs.get("slug") == [slug]:
                return draft
        except Exception:
            continue
    return None


@router.get("/{slug}/lab-cta", response_model=ArticleLabCTAResponse, summary="Get reader-safe lab CTA for article")
async def get_article_lab_cta(
    slug: str,
    repo: "LabDraftRepository" = Depends(get_lab_draft_repository),
) -> ArticleLabCTAResponse:
    """
    Reader-safe endpoint — no auth required.
    Returns CTA data when the article has a PUBLISHED lab with cta_enabled=True.
    Never returns: source_article_id, raw article text, admin notes, draft/internal labs.
    Returns has_cta=False (not 404) when no matching lab exists.
    """
    from backend.labgen.llm_generation import sanitize_text
    from backend.labgen.models import LabDraft as _LabDraft

    draft: Optional[_LabDraft] = _find_lab_by_article_slug(slug, repo)
    if draft is None:
        return ArticleLabCTAResponse(has_cta=False)

    lab_id = draft.lab_id
    cta_url = f"/labgen-lab.html?labId={lab_id}"
    domain_value = draft.target_domain.value if draft.target_domain else None

    return ArticleLabCTAResponse(
        has_cta=True,
        lab_id=lab_id,
        lab_title=sanitize_text(draft.title)[:200],
        lab_summary=sanitize_text(draft.description)[:300],
        difficulty=None,
        estimated_duration=draft.estimated_duration_minutes,
        domain=domain_value,
        cta_url=cta_url,
        cta_text="进入实验",
        sandbox_note="实验运行在临时隔离环境中，完成后自动销毁。",
        cleanup_note="完成实验后环境自动清理，数据不保留。",
    )
