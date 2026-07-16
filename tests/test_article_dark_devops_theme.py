"""
Regression tests for the dark DevOps-style redesign of the public article page
(frontend/article.html + frontend/js/article.js).

Owner feedback (2026-07-16): after seeing a dark-themed Artifact mockup of the
CrashLoopBackOff article, asked why the real article.html was still light —
it had never been included in the earlier labgen-catalog/lab/session dark
theme redesign. This extends the same devops-* token system (already defined
in frontend/js/tailwind-config.js) to article.html only, per explicit scope
choice (landing.html/index.html stay light).
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.static

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


class TestArticlePageDarkTheme:
    def test_article_html_uses_devops_bg_token(self):
        html = _read("article.html")
        assert "bg-devops-bg" in html

    def test_article_html_loads_plex_and_jetbrains_mono_fonts(self):
        html = _read("article.html")
        assert "IBM+Plex+Sans" in html
        assert "JetBrains+Mono" in html

    def test_article_js_lab_cta_uses_dark_tokens(self):
        js = (FRONTEND_DIR / "js" / "article.js").read_text(encoding="utf-8")
        assert "bg-devops-surface" in js
        assert "text-devops-text" in js
        assert "bg-gradient-to-br from-blue-50" not in js, "must not keep the old light CTA gradient"

    def test_article_js_comment_form_uses_dark_tokens(self):
        js = (FRONTEND_DIR / "js" / "article.js").read_text(encoding="utf-8")
        assert "bg-devops-surface rounded-xl" in js
        assert "bg-white rounded-xl border border-gray-200 p-5" not in js, "must not keep the old light comment card"


class TestScopeContainedToArticlePage:
    """The dark theme change must not leak into pages outside article.html."""

    def test_landing_html_still_light_no_devops_tokens(self):
        html = _read("landing.html")
        assert "devops-bg" not in html

    def test_index_html_still_light_no_devops_tokens(self):
        html = _read("index.html")
        assert "devops-bg" not in html

    def test_article_js_only_referenced_by_article_html(self):
        for page in FRONTEND_DIR.glob("*.html"):
            if page.name == "article.html":
                continue
            assert "article.js" not in page.read_text(encoding="utf-8"), (
                f"{page.name} references article.js — dark-theme article.js changes "
                "would leak into this page too"
            )
