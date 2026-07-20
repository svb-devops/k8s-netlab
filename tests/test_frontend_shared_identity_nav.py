"""
Regression tests for the LabGen <-> 网络实验室 (11-experiment app) journey.

Bug: landing.js and article.js each re-implement an almost identical
/api/auth/me identity-rendering block (nav-actions markup differs only in
light/dark CSS classes) instead of sharing one module. LabGen sessions that
reach LAB_COMPLETED have no path back to the full 网络实验室 (/app), so
readers who finish a LabGen walkthrough are never nudged toward the deeper
product. Terminology ("LabGen 实验", "Home") does not match the locked
naming: 网络实验室 (11 official experiments) vs 故障排查练习 (LabGen).

Fix:
1. frontend/js/nav-auth.js holds the single /api/auth/me render function;
   landing.js and article.js both import it instead of duplicating markup.
2. labgen-session.html carries a CTA element that links to /app; the
   completion-state branch in labgen-session-init.js reveals it.
3. index.html and labgen-catalog.html use the locked terminology.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.static

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
JS_DIR = FRONTEND_DIR / "js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestSharedNavAuthModule:
    """landing.js and article.js must share one identity-rendering module."""

    def test_nav_auth_module_exists(self):
        assert (JS_DIR / "nav-auth.js").exists(), (
            "frontend/js/nav-auth.js must exist as the single source of "
            "truth for rendering the /api/auth/me identity block"
        )

    def test_nav_auth_module_exports_render_function(self):
        js = _read(JS_DIR / "nav-auth.js")
        assert "export" in js and "renderNavAuth" in js, (
            "nav-auth.js must export a renderNavAuth function for other "
            "pages to import"
        )

    def test_landing_js_imports_shared_module(self):
        js = _read(JS_DIR / "landing.js")
        assert "nav-auth.js" in js, (
            "landing.js must import the shared nav-auth module instead of "
            "duplicating the /api/auth/me identity markup"
        )

    def test_article_js_imports_shared_module(self):
        js = _read(JS_DIR / "article.js")
        assert "nav-auth.js" in js, (
            "article.js must import the shared nav-auth module instead of "
            "duplicating the /api/auth/me identity markup"
        )

    def test_landing_html_loads_landing_js_as_module(self):
        html = _read(FRONTEND_DIR / "landing.html")
        assert '<script type="module" src="/js/landing.js">' in html, (
            "landing.html must load landing.js as an ES module so it can "
            "import nav-auth.js"
        )

    def test_article_html_loads_article_js_as_module(self):
        html = _read(FRONTEND_DIR / "article.html")
        assert '<script type="module" src="/js/article.js">' in html, (
            "article.html must load article.js as an ES module so it can "
            "import nav-auth.js"
        )


class TestLabgenCompletionConversionCta:
    """A finished LabGen session must offer a path to the full 网络实验室."""

    def test_session_html_has_cta_element(self):
        html = _read(FRONTEND_DIR / "labgen-session.html")
        assert 'id="session-cta-network-lab"' in html, (
            "labgen-session.html must contain a CTA element (hidden by "
            "default) linking to /app for completed sessions"
        )
        assert 'href="/app"' in html

    def test_session_init_reveals_cta_on_completion(self):
        js = _read(JS_DIR / "labgen-session-init.js")
        assert "session-cta-network-lab" in js, (
            "labgen-session-init.js must reveal the CTA element when the "
            "session reaches LAB_COMPLETED"
        )

    def test_completion_cta_gated_to_completed_and_closed_states_only(self):
        """The CTA must not appear for LAB_ABORTED / LAB_CLEANUP_FAILED — a
        failed or aborted session is not a "you're ready for more" moment."""
        js = _read(JS_DIR / "labgen-session-init.js")
        match = re.search(r"function _updateCompletionCta\(.*?\n}", js, re.DOTALL)
        assert match, "_updateCompletionCta function not found"
        fn_body = match.group(0)
        assert "LAB_COMPLETED" in fn_body and "LAB_CLOSED" in fn_body, (
            "_updateCompletionCta must gate on LAB_COMPLETED/LAB_CLOSED"
        )
        assert "LAB_ABORTED" not in fn_body and "LAB_CLEANUP_FAILED" not in fn_body, (
            "_updateCompletionCta must not reveal the CTA for LAB_ABORTED or "
            "LAB_CLEANUP_FAILED — those are not a completion state"
        )


class TestLockedTerminology:
    """11 official experiments = 网络实验室; LabGen = 故障排查练习."""

    def test_index_html_labels_labgen_entry_point(self):
        html = _read(FRONTEND_DIR / "index.html")
        assert "故障排查练习" in html, (
            "index.html must label the LabGen entry point as 故障排查练习 "
            "per the locked naming convention"
        )

    def test_labgen_catalog_labels_return_link(self):
        html = _read(FRONTEND_DIR / "labgen-catalog.html")
        assert "网络实验室" in html, (
            "labgen-catalog.html's return-to-/app link must say 网络实验室, "
            "not a generic 'Home', so users know what they're returning to"
        )
