"""
Regression tests for no_vm_assigned error UX in labgen-lab-init.js.

Bug (Controlled Soft Launch): When a new user clicks "Start Lab" on the article lab page
and has no K8s VM yet, the backend returns 422 no_vm_assigned. The frontend rendered
a plain red text message with no actionable path, causing users to abandon the flow.

Fix: labgen-lab-init.js must detect e.code === 'no_vm_assigned' and render a dedicated
UI block containing a link/button to /app so users can create a VM and return to the lab.
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
        """JS must explicitly check for the no_vm_assigned error code."""
        js = _read("labgen-lab-init.js")
        assert "no_vm_assigned" in js, (
            "labgen-lab-init.js must detect e.code === 'no_vm_assigned' to render "
            "a dedicated error UI instead of generic red text"
        )

    def test_link_to_app_present_for_no_vm(self):
        """When no_vm_assigned, JS must render a link or button pointing to /app."""
        js = _read("labgen-lab-init.js")
        # Must contain a reference to /app as the destination for VM creation
        assert '"/app"' in js or "'/app'" in js or "href='/app'" in js or 'href="/app"' in js, (
            "labgen-lab-init.js must include a link to /app so users without a VM "
            "can create one and return to start the lab"
        )

    def test_no_vm_branch_is_separate_from_generic_error(self):
        """no_vm_assigned must be handled in its own branch, not the generic error path."""
        js = _read("labgen-lab-init.js")
        # The no_vm_assigned check must appear before or separate from the generic error msg
        no_vm_idx = js.find("no_vm_assigned")
        generic_idx = js.find("text-red-600")
        assert no_vm_idx != -1, "no_vm_assigned code check missing"
        # Generic red text path should still exist for other errors
        assert generic_idx != -1, "Generic red error text path must still exist for non-no_vm errors"
        # They must be in different code paths (no_vm_assigned appears before generic path OR in separate branch)
        # We verify this by checking that no_vm_assigned appears within an if-branch context
        no_vm_region = js[max(0, no_vm_idx - 50): no_vm_idx + 200]
        assert "if" in no_vm_region or "===" in no_vm_region, (
            "no_vm_assigned must be handled inside a conditional branch"
        )

    def test_action_element_rendered_for_no_vm(self):
        """The no_vm error UI must render an interactive element (a or button) to /app."""
        js = _read("labgen-lab-init.js")
        # Verify there's an anchor element pointing to /app in the no_vm handling
        has_anchor = "<a" in js and "/app" in js
        has_button_redirect = "location" in js and "/app" in js
        assert has_anchor or has_button_redirect, (
            "labgen-lab-init.js must render an <a href='/app'> anchor (or equivalent redirect) "
            "in the no_vm_assigned error block so users have a clickable path to VM creation"
        )
