"""
Regression tests for no_vm_assigned error UX: labgen-lab-init.js + app.js.

Bug (Controlled Soft Launch): When a new user clicks "Start Lab" on the article lab page
and has no K8s VM yet, the backend returns 422 no_vm_assigned. The frontend rendered
a plain red text message with no actionable path, causing users to abandon the flow.

After VM creation the user had no way back to the lab (stranded on /app).

Fix:
- labgen-lab-init.js: detect no_vm_assigned, link to /app?next=<lab_url> (not new tab)
- app.js: after VM creation success, if ?next= points to /labgen-lab.html, redirect there
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.static

JS_DIR = Path(__file__).parent.parent / "frontend" / "js"


def _read(name: str) -> str:
    return (JS_DIR / name).read_text(encoding="utf-8")


class TestNoVmAssignedErrorHandling:
    """labgen-lab-init.js must handle no_vm_assigned with an actionable path."""

    def test_no_vm_assigned_code_is_checked(self):
        js = _read("labgen-lab-init.js")
        assert "no_vm_assigned" in js

    def test_link_to_app_includes_next_param(self):
        """When no_vm_assigned, link must use /app?next= so user returns after VM creation."""
        js = _read("labgen-lab-init.js")
        assert "'/app?next='" in js or '"/app?next="' in js or "/app?next=" in js, (
            "labgen-lab-init.js must pass ?next= to /app so the user is redirected "
            "back to the lab page after VM creation"
        )

    def test_no_vm_block_encodes_current_url(self):
        """The ?next= value must be encoded from the current page URL."""
        js = _read("labgen-lab-init.js")
        assert "encodeURIComponent" in js and "window.location.href" in js

    def test_no_vm_branch_is_separate_from_generic_error(self):
        js = _read("labgen-lab-init.js")
        no_vm_idx = js.find("no_vm_assigned")
        generic_idx = js.find("text-red-400")
        assert no_vm_idx != -1, "no_vm_assigned code check missing"
        assert generic_idx != -1, "Generic red error text path must still exist for non-no_vm errors"
        no_vm_region = js[max(0, no_vm_idx - 50): no_vm_idx + 200]
        assert "if" in no_vm_region or "===" in no_vm_region

    def test_action_element_rendered_for_no_vm(self):
        js = _read("labgen-lab-init.js")
        assert "<a" in js and "/app" in js


class TestAppJsNextParamRedirect:
    """app.js must redirect to ?next= after VM creation if it points to /labgen-lab.html."""

    def test_app_reads_next_param_after_create(self):
        """app.js must read ?next= from URL after successful VM creation."""
        js = _read("app.js")
        assert "next" in js and "URLSearchParams" in js

    def test_app_validates_next_prefix(self):
        """app.js must only redirect to /labgen-lab.html (not arbitrary URLs)."""
        js = _read("app.js")
        assert "/labgen-lab.html" in js, (
            "app.js must validate that ?next= starts with /labgen-lab.html "
            "to prevent open redirect"
        )

    def test_app_redirects_on_safe_next(self):
        """app.js must call window.location.href = safeNext after VM creation success."""
        js = _read("app.js")
        # safeNext variable must be set and used for redirect
        assert "safeNext" in js, "app.js must define a safeNext variable for the validated ?next= URL"
        safe_idx = js.find("safeNext")
        region = js[safe_idx: safe_idx + 200]
        assert "location.href" in region, "safeNext must be used in a window.location.href redirect"

    def test_app_no_redirect_when_no_next_param(self):
        """Without ?next=, app.js must show the normal success modal (not redirect)."""
        js = _read("app.js")
        assert "showSuccess" in js, "Normal success path must still exist when no ?next= param"
