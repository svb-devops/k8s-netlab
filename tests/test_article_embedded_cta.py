"""
G-61: Article Detail Embedded CTA Component tests.

Covers:
  A. GET /api/articles/{slug}/lab-cta API — happy path and negative cases
  B. _find_lab_by_article_slug() unit tests — slug matching logic
  C. _validateCtaUrl() frontend safety gate (static, checked via inline re-impl)
  D. article.html / article.js static safety checks
  E. Exposure rules: source_article_id, raw text, admin notes absent
  F. Regression: existing endpoints unaffected
"""

from __future__ import annotations

import re
import uuid
from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.articles_routes import (
    ArticleLabCTAResponse,
    _find_lab_by_article_slug,
    get_lab_draft_repository,
)
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDomainType,
    LabDraft,
    PublishStatus,
    RuntimeRequirements,
    Step,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LINUX_ARTICLE_URL = "https://lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics"
K8S_ARTICLE_URL = "https://lab.cloudnetops.tech/article.html?slug=welcome-to-k8s-netlab"


def _make_step() -> Step:
    return Step(
        step_id="s1",
        order=1,
        why="why",
        do="do",
        observe="observe",
        explain=ExplainField(concept="c", observation="o"),
    )


def _make_published_draft(
    *,
    article_url: Optional[str] = None,
    article_title: Optional[str] = None,
    cta_enabled: bool = True,
    publish_status: PublishStatus = PublishStatus.PUBLISHED,
    domain: LabDomainType = LabDomainType.LINUX,
    title: str = "Linux 文件与权限基础",
    description: str = "学习 chmod、stat、mkdir 等命令",
    estimated_duration_minutes: int = 30,
) -> LabDraft:
    return LabDraft(
        source_article_id="internal-art-003",
        title=title,
        description=description,
        estimated_duration_minutes=estimated_duration_minutes,
        target_domain=domain,
        runtime_requirements=RuntimeRequirements(),
        steps=[_make_step()],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=publish_status,
        rehearsal_required=False,
        rehearsal_completed=False,
        article_url=article_url,
        article_title=article_title,
        article_channel="official_site" if article_url else None,
        cta_enabled=cta_enabled,
    )


class _MemRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_repo() -> _MemRepo:
    return _MemRepo()


@pytest.fixture()
def client(mem_repo):
    from backend.main import app

    app.dependency_overrides[get_lab_draft_repository] = lambda: mem_repo
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.pop(get_lab_draft_repository, None)


# ---------------------------------------------------------------------------
# A. API tests — GET /api/articles/{slug}/lab-cta
# ---------------------------------------------------------------------------


class TestArticleLabCTAEndpoint:
    def test_published_cta_enabled_lab_returns_cta(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL, article_title="Linux 文件与权限")
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        assert r.status_code == 200
        data = r.json()
        assert data["has_cta"] is True
        assert data["lab_id"] == draft.lab_id
        assert data["lab_title"] == "Linux 文件与权限基础"
        assert data["estimated_duration"] == 30
        assert data["domain"] == "linux"
        assert data["cta_url"] == f"/labgen-lab.html?labId={draft.lab_id}"
        assert data["cta_text"] == "进入实验"
        assert "自动销毁" in data["sandbox_note"]

    def test_no_linked_lab_returns_has_cta_false(self, client, mem_repo):
        r = client.get("/api/articles/nonexistent-slug/lab-cta")
        assert r.status_code == 200
        assert r.json()["has_cta"] is False
        assert r.json().get("lab_id") is None

    def test_draft_lab_not_returned(self, client, mem_repo):
        draft = _make_published_draft(
            article_url=LINUX_ARTICLE_URL,
            publish_status=PublishStatus.DRAFT,
        )
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        assert r.status_code == 200
        assert r.json()["has_cta"] is False

    def test_publish_blocked_lab_not_returned(self, client, mem_repo):
        draft = _make_published_draft(
            article_url=LINUX_ARTICLE_URL,
            publish_status=PublishStatus.PUBLISH_BLOCKED,
        )
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        assert r.status_code == 200
        assert r.json()["has_cta"] is False

    def test_cta_disabled_lab_not_returned(self, client, mem_repo):
        draft = _make_published_draft(
            article_url=LINUX_ARTICLE_URL,
            cta_enabled=False,
        )
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        assert r.status_code == 200
        assert r.json()["has_cta"] is False

    def test_source_article_id_never_returned(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        data = r.json()
        assert "source_article_id" not in data

    def test_raw_article_text_never_returned(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        data = r.json()
        # article_url, article_title are admin fields — not in reader CTA response
        assert "article_url" not in data
        assert "article_title" not in data
        assert "article_channel" not in data

    def test_admin_notes_never_returned(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        data = r.json()
        for field in ("validator_results", "image_resolution", "publish_blocked_checks",
                      "source_article_id", "rehearsal_required", "rehearsal_completed"):
            assert field not in data

    def test_no_auth_required(self, client, mem_repo):
        # Endpoint is public — cookies not sent
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        assert r.status_code == 200

    def test_wrong_slug_does_not_match(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        # k8s slug should not match linux lab
        r = client.get("/api/articles/welcome-to-k8s-netlab/lab-cta")
        assert r.status_code == 200
        assert r.json()["has_cta"] is False

    def test_cta_url_is_safe_relative_path(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        data = r.json()
        cta_url = data.get("cta_url", "")
        assert cta_url.startswith("/labgen-lab.html?labId="), f"cta_url unsafe: {cta_url!r}"
        # Must not be absolute URL (no cross-origin risk)
        assert not cta_url.startswith("http"), f"cta_url must be relative: {cta_url!r}"

    def test_k8s_lab_with_k8s_article_returns_cta(self, client, mem_repo):
        draft = _make_published_draft(
            article_url=K8S_ARTICLE_URL,
            domain=LabDomainType.K8S,
            title="K8s 入门实验",
        )
        mem_repo.create(draft)
        r = client.get("/api/articles/welcome-to-k8s-netlab/lab-cta")
        assert r.status_code == 200
        data = r.json()
        assert data["has_cta"] is True
        assert data["domain"] == "k8s"

    def test_multiple_labs_only_published_cta_enabled_returned(self, client, mem_repo):
        draft_draft = _make_published_draft(
            article_url=LINUX_ARTICLE_URL,
            publish_status=PublishStatus.DRAFT,
        )
        mem_repo.create(draft_draft)
        draft_pub = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft_pub)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        assert r.status_code == 200
        data = r.json()
        assert data["has_cta"] is True
        assert data["lab_id"] == draft_pub.lab_id


# ---------------------------------------------------------------------------
# B. _find_lab_by_article_slug unit tests
# ---------------------------------------------------------------------------


class TestFindLabByArticleSlug:
    def test_matches_exact_slug(self, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        found = _find_lab_by_article_slug("linux-files-permissions-basics", mem_repo)
        assert found is not None
        assert found.lab_id == draft.lab_id

    def test_returns_none_for_nonexistent_slug(self, mem_repo):
        assert _find_lab_by_article_slug("does-not-exist", mem_repo) is None

    def test_returns_none_for_draft_lab(self, mem_repo):
        draft = _make_published_draft(
            article_url=LINUX_ARTICLE_URL,
            publish_status=PublishStatus.DRAFT,
        )
        mem_repo.create(draft)
        assert _find_lab_by_article_slug("linux-files-permissions-basics", mem_repo) is None

    def test_returns_none_when_cta_disabled(self, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL, cta_enabled=False)
        mem_repo.create(draft)
        assert _find_lab_by_article_slug("linux-files-permissions-basics", mem_repo) is None

    def test_returns_none_when_no_article_url(self, mem_repo):
        draft = _make_published_draft(article_url=None)
        mem_repo.create(draft)
        assert _find_lab_by_article_slug("linux-files-permissions-basics", mem_repo) is None

    def test_partial_slug_does_not_match(self, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        # "linux" is a substring but not the full slug value
        assert _find_lab_by_article_slug("linux", mem_repo) is None

    def test_empty_repo_returns_none(self, mem_repo):
        assert _find_lab_by_article_slug("linux-files-permissions-basics", mem_repo) is None


# ---------------------------------------------------------------------------
# C. CTA URL validation (mirrors _validateCtaUrl in article.js)
# ---------------------------------------------------------------------------

_VALID_CTA_PREFIX = "/labgen-lab.html?labId="

def _py_validate_cta_url(raw: str | None) -> str | None:
    """Python re-implementation of article.js _validateCtaUrl for static testing."""
    if isinstance(raw, str) and raw.startswith(_VALID_CTA_PREFIX):
        return raw
    return None


class TestCtaUrlValidation:
    def test_valid_lab_deep_link_passes(self):
        url = "/labgen-lab.html?labId=6c439064-4cad-4229-addb-36927128d565"
        assert _py_validate_cta_url(url) == url

    def test_javascript_xss_rejected(self):
        assert _py_validate_cta_url("javascript:alert(1)") is None

    def test_external_url_rejected(self):
        assert _py_validate_cta_url("https://evil.com") is None

    def test_empty_string_rejected(self):
        assert _py_validate_cta_url("") is None

    def test_none_rejected(self):
        assert _py_validate_cta_url(None) is None

    def test_data_url_rejected(self):
        assert _py_validate_cta_url("data:text/html,<script>alert(1)</script>") is None

    def test_different_path_rejected(self):
        assert _py_validate_cta_url("/lab.html?labId=abc") is None

    def test_valid_url_with_uuid(self):
        lab_id = str(uuid.uuid4())
        url = f"/labgen-lab.html?labId={lab_id}"
        assert _py_validate_cta_url(url) == url


# ---------------------------------------------------------------------------
# D. article.html / article.js static safety
# ---------------------------------------------------------------------------

class TestArticleHtmlStaticSafety:
    def test_lab_cta_container_slot_present(self):
        html = open("/root/k8s-netlab/frontend/article.html").read()
        assert 'id="lab-cta-container"' in html

    def test_lab_cta_container_before_comments(self):
        html = open("/root/k8s-netlab/frontend/article.html").read()
        cta_pos = html.index('id="lab-cta-container"')
        comments_pos = html.index('id="comments-section"')
        assert cta_pos < comments_pos, "CTA container must appear before comments section"

    def test_article_js_loads_lab_cta(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        assert "loadLabCTA" in js
        assert "renderLabCTA" in js

    def test_article_js_no_unsafe_innerhtml_on_api_data(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        # renderLabCTA must use textContent for data from API
        # Find renderLabCTA function body
        match = re.search(r'function renderLabCTA\(.*?\n}', js, re.DOTALL)
        assert match, "renderLabCTA function not found"
        fn_body = match.group(0)
        # innerHTML is allowed to CLEAR container (innerHTML = '') but must not
        # assign any untrusted API value via innerHTML
        # Acceptable: container.innerHTML = '' or block.innerHTML = ''
        # Unacceptable: *.innerHTML = data.* or untrusted variable
        inner_assigns = re.findall(r'\.innerHTML\s*=\s*(.+)', fn_body)
        for assign in inner_assigns:
            assert assign.strip() in ("''", '""', "''  // clear", '""  // clear'), (
                f"Unsafe innerHTML assignment in renderLabCTA: {assign!r}\n"
                "All dynamic content must use textContent or DOM construction."
            )

    def test_article_js_uses_textcontent_for_lab_title(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        assert "textContent = data.lab_title" in js or ".textContent = data.lab_title" in js

    def test_article_js_validates_cta_url_before_use(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        assert "_validateCtaUrl" in js
        assert "startsWith('/labgen-lab.html?labId=')" in js

    def test_article_js_handles_no_cta_gracefully(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        assert "if (!data.has_cta) return" in js

    def test_article_js_silent_on_fetch_failure(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        # loadLabCTA should catch exceptions silently
        match = re.search(r'async function loadLabCTA\(\).*?^}', js, re.DOTALL | re.MULTILINE)
        assert match, "loadLabCTA function not found"
        fn = match.group(0)
        assert "catch" in fn

    def test_article_js_unauthenticated_cta_includes_next_param(self):
        # Regression: CTA button for unauthenticated users must include ?next= redirect
        # so learners are sent back to the lab after registration/login.
        # Without this, new learners land on /app after register, breaking the
        # Article → CTA → Register → Lab UX flow.
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        match = re.search(r'function renderLabCTA\(.*?\n}', js, re.DOTALL)
        assert match, "renderLabCTA function not found"
        fn_body = match.group(0)
        # Must redirect to /login.html with ?next= param, not bare /login.html
        assert "'/login.html?next='" in fn_body or '"/login.html?next="' in fn_body, (
            "Unauthenticated CTA button must link to '/login.html?next=...' to preserve "
            "the Article → CTA → Register → Lab redirect chain."
        )
        assert "encodeURIComponent" in fn_body, (
            "The ?next= value must be URL-encoded via encodeURIComponent."
        )

    # G-66: MEDIUM-002 fix — header nav must be unified with embedded CTA on article page
    def test_article_js_init_auth_marks_lab_nav_with_stable_data_attribute(self):
        # initAuth must add data-lab-nav to the "进入实验室" anchor so renderLabCTA
        # can locate it with a selector that remains stable after href mutation.
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        match = re.search(r'async function initAuth\(\).*?^}', js, re.DOTALL | re.MULTILINE)
        assert match, "initAuth function not found"
        fn_body = match.group(0)
        assert "data-lab-nav" in fn_body, (
            "initAuth must add data-lab-nav attribute to the lab entry anchor. "
            "renderLabCTA uses this stable selector instead of the mutable href."
        )

    def test_article_js_header_nav_updated_to_linked_lab_when_cta_loaded(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        match = re.search(r'function renderLabCTA\(.*?\n}', js, re.DOTALL)
        assert match, "renderLabCTA function not found"
        fn_body = match.group(0)
        # renderLabCTA must use stable data-lab-nav selector (not mutable href)
        assert "data-lab-nav" in fn_body, (
            "renderLabCTA must locate header nav link via [data-lab-nav] stable attribute, "
            "not a[href='/app'] which becomes stale after the first href mutation. "
            "MEDIUM-002: 2/3 cohort learners were diverted by header nav competing with CTA."
        )

    def test_article_js_header_nav_update_uses_pre_validated_cta_url(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        match = re.search(r'function renderLabCTA\(.*?\n}', js, re.DOTALL)
        assert match, "renderLabCTA function not found"
        fn_body = match.group(0)
        # Must assign pre-validated ctaUrl (not raw data) to nav link href
        assert "navLabLink.href = ctaUrl" in fn_body, (
            "Header nav href must be set to the already-validated ctaUrl, "
            "never to raw data.cta_url or any other unvalidated string."
        )

    def test_article_js_header_nav_text_changes_to_配套实验(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        match = re.search(r'function renderLabCTA\(.*?\n}', js, re.DOTALL)
        assert match, "renderLabCTA function not found"
        fn_body = match.group(0)
        # Text must change to '进入配套实验' to distinguish from catalog entry point
        assert "进入配套实验" in fn_body, (
            "Header nav text must change to '进入配套实验' when CTA is loaded "
            "so readers can distinguish it from the general catalog link."
        )

    def test_article_js_header_nav_update_uses_safe_dom_textcontent(self):
        js = open("/root/k8s-netlab/frontend/js/article.js").read()
        match = re.search(r'function renderLabCTA\(.*?\n}', js, re.DOTALL)
        assert match, "renderLabCTA function not found"
        fn_body = match.group(0)
        # Must update text via .textContent, never .innerHTML
        assert "navLabLink.textContent" in fn_body, (
            "Header nav text update must use .textContent, not .innerHTML, "
            "to avoid XSS risk when setting nav button text."
        )


# ---------------------------------------------------------------------------
# E. Exposure rules (API contract safety)
# ---------------------------------------------------------------------------

class TestCTAExposureRules:
    def test_api_response_has_no_internal_fields(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        data = r.json()
        forbidden = [
            "source_article_id",
            "article_url",
            "article_title",
            "article_channel",
            "article_published_at",
            "validator_results",
            "image_resolution",
            "publish_blocked_checks",
            "rehearsal_required",
            "rehearsal_completed",
        ]
        for field in forbidden:
            assert field not in data, f"Internal field {field!r} must not appear in reader CTA response"

    def test_api_response_has_no_kubeconfig_or_secret(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        text = r.text.lower()
        for kw in ("kubeconfig", "private_key", "password", "token"):
            assert kw not in text, f"Sensitive keyword {kw!r} found in CTA response"

    def test_has_cta_false_response_has_no_lab_data(self, client, mem_repo):
        r = client.get("/api/articles/nonexistent-article/lab-cta")
        data = r.json()
        assert data["has_cta"] is False
        assert data.get("lab_id") is None
        assert data.get("cta_url") is None

    def test_cta_url_never_absolute(self, client, mem_repo):
        draft = _make_published_draft(article_url=LINUX_ARTICLE_URL)
        mem_repo.create(draft)
        r = client.get("/api/articles/linux-files-permissions-basics/lab-cta")
        cta_url = r.json().get("cta_url", "")
        assert not cta_url.startswith("http"), "cta_url must be a relative path"


# ---------------------------------------------------------------------------
# F. Regression: other article endpoints unaffected
# ---------------------------------------------------------------------------

class TestRegressionOtherEndpoints:
    def test_article_list_endpoint_still_requires_directus(self, client):
        # GET /api/articles without directus config → 503
        from unittest.mock import patch
        with patch("backend.articles_routes.config") as cfg:
            cfg.DIRECTUS_URL = ""
            r = client.get("/api/articles")
        assert r.status_code == 503

    def test_article_detail_endpoint_still_exists(self, client):
        from unittest.mock import patch, AsyncMock
        with patch("backend.articles_routes.config") as cfg, \
             patch("backend.articles_routes.httpx.AsyncClient") as mock_cls:
            cfg.DIRECTUS_URL = "http://localhost:8055"
            mc = AsyncMock()
            not_found = MagicMock()
            not_found.status_code = 200
            not_found.json.return_value = {"data": []}
            mc.get = AsyncMock(return_value=not_found)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            r = client.get("/api/articles/some-slug")
        assert r.status_code == 404  # article not found in directus mock

    def test_lab_cta_endpoint_does_not_break_article_routes_client(self, mem_repo):
        # Existing articles_routes tests create mini apps — ensure our DI additions
        # do not break when the router is included in a standalone FastAPI app
        from fastapi import FastAPI
        mini_app = FastAPI()
        from backend.articles_routes import router as articles_router
        mini_app.include_router(articles_router)
        mini_app.dependency_overrides[get_lab_draft_repository] = lambda: mem_repo
        c = TestClient(mini_app, raise_server_exceptions=True)
        r = c.get("/api/articles/linux-files-permissions-basics/lab-cta")
        assert r.status_code == 200
        assert r.json()["has_cta"] is False
