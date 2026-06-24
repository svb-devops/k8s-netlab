"""
Regression tests for LabGen navigation accessibility from the main /app page.

Bug: Users who log in to /app see the K8s VM interface with no path to LabGen labs.
Repeated pilots (G-50, G-51, G-56) encountered this problem.

Fix:
1. index.html header must contain a link to /labgen-catalog.html
2. app.js must handle ?lab= query param and redirect to /labgen-lab.html?labId=...
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.static

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
JS_DIR = FRONTEND_DIR / "js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestIndexHtmlLabGenNavigation:
    """index.html must expose a navigation path to LabGen labs."""

    def test_labgen_catalog_link_present_in_header(self):
        """Header must contain a visible link to /labgen-catalog.html."""
        html = _read(FRONTEND_DIR / "index.html")
        # Must have a link pointing to the LabGen catalog page
        assert "/labgen-catalog.html" in html, (
            "index.html header must include a link to /labgen-catalog.html "
            "so users can navigate from the K8s page to LabGen labs"
        )

    def test_labgen_link_is_in_header_section(self):
        """The LabGen link must appear before </header>, not buried in the page body."""
        html = _read(FRONTEND_DIR / "index.html")
        header_end = html.find("</header>")
        assert header_end > 0, "index.html must have a </header> closing tag"
        header_section = html[:header_end]
        assert "/labgen-catalog.html" in header_section, (
            "The /labgen-catalog.html link must be in the header, not buried in body"
        )


class TestAppJsLabQueryParamRedirect:
    """app.js must redirect ?lab= query param to the correct LabGen lab page."""

    def test_lab_query_param_handled(self):
        """app.js must check for ?lab= URLSearchParam and redirect appropriately."""
        js = _read(JS_DIR / "app.js")
        # Must reference the lab query param
        has_lab_param = (
            "URLSearchParams" in js or "searchParams" in js or "get('lab')" in js or 'get("lab")' in js
        )
        assert has_lab_param, (
            "app.js must handle the ?lab= query parameter "
            "so that /app?lab=<labId> redirects to /labgen-lab.html?labId=<labId>"
        )

    def test_labgen_lab_redirect_target(self):
        """app.js must redirect to /labgen-lab.html when ?lab= is present."""
        js = _read(JS_DIR / "app.js")
        assert "labgen-lab.html" in js, (
            "app.js must include /labgen-lab.html as the redirect target "
            "when ?lab= query param is detected"
        )
