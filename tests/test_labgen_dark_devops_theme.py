"""
Regression tests for the dark DevOps-style redesign of the learner-facing lab
flow (labgen-catalog.html / labgen-lab.html / labgen-session.html).

Owner feedback (2026-07-15): the light Tailwind-default look was "太丑，没办法
放出去". Redesigned to a dark, terminal-inspired palette (near-black surfaces,
K8s blue accent, IBM Plex Sans + JetBrains Mono) consistent with common DevOps
tooling (GitHub Dark, Grafana, Kubernetes Dashboard).

These tests lock in the shell-level tokens so the three pages can't silently
drift back to the old light theme, and confirm the change stayed scoped to
these three pages (index.html, which shares app.css's .doc-drawer/.step-pill
with labgen-session.html, must be untouched).
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.static

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

_DARK_PAGES = ["labgen-catalog.html", "labgen-lab.html", "labgen-session.html"]


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


class TestDarkThemeAppliedToLearnerFlow:
    @pytest.mark.parametrize("page", _DARK_PAGES)
    def test_page_uses_devops_bg_token(self, page):
        html = _read(page)
        assert "bg-devops-bg" in html, f"{page} must use the dark devops-bg background token"

    @pytest.mark.parametrize("page", _DARK_PAGES)
    def test_page_loads_plex_and_jetbrains_mono_fonts(self, page):
        html = _read(page)
        assert "IBM+Plex+Sans" in html, f"{page} must load IBM Plex Sans"
        assert "JetBrains+Mono" in html, f"{page} must load JetBrains Mono"


class TestScopeContainedToThreePages:
    """The dark theme must not leak into pages outside the learner lab flow."""

    def test_index_html_still_light_no_devops_tokens(self):
        html = _read("index.html")
        assert "devops-bg" not in html, "index.html must stay on the light theme"

    def test_login_html_untouched(self):
        html = _read("login.html")
        assert "devops-bg" not in html

    def test_admin_html_untouched(self):
        html = _read("admin.html")
        assert "devops-bg" not in html


class TestTailwindConfigAdditivity:
    """New devops-* tokens must be additive, not replacing k8s-blue/k8s-dark."""

    def test_existing_tokens_preserved(self):
        js = (FRONTEND_DIR / "js" / "tailwind-config.js").read_text(encoding="utf-8")
        assert "'k8s-blue': '#326CE5'" in js
        assert "'k8s-dark': '#1E293B'" in js

    def test_devops_tokens_added(self):
        js = (FRONTEND_DIR / "js" / "tailwind-config.js").read_text(encoding="utf-8")
        for token in ("devops-bg", "devops-surface", "devops-border", "devops-text", "devops-muted"):
            assert f"'{token}'" in js, f"tailwind-config.js must define '{token}'"


class TestAppCssDarkOverridesScoped:
    """The .doc-drawer/.step-pill dark overrides must be scoped under
    body.theme-dark so index.html's light-mode drawer/pills are unaffected."""

    def test_dark_overrides_are_scoped_under_theme_dark(self):
        css = (FRONTEND_DIR / "css" / "app.css").read_text(encoding="utf-8")
        assert ".theme-dark .doc-drawer" in css
        assert ".theme-dark .step-pill" in css

    def test_base_doc_drawer_rule_still_light(self):
        """The unscoped .doc-drawer rule (used by index.html) must keep its
        original white background — only the .theme-dark-scoped override changes it."""
        css = (FRONTEND_DIR / "css" / "app.css").read_text(encoding="utf-8")
        base_rule_start = css.index(".doc-drawer {")
        base_rule_end = css.index("}", base_rule_start)
        base_rule = css[base_rule_start:base_rule_end]
        assert "background: #fff;" in base_rule

    def test_labgen_session_html_sets_theme_dark_body_class(self):
        html = _read("labgen-session.html")
        assert 'class="theme-dark' in html

    def test_index_html_does_not_set_theme_dark(self):
        html = _read("index.html")
        assert "theme-dark" not in html
