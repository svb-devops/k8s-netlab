"""
P0 Reader Path Repair — frontend regression tests for labgen-lab-init.js /
labgen-vm-wait.js / labgenClient.js.

Mirrors the string-assertion style of test_labgen_lab_no_vm_cta.py (no JS
runtime in this test suite — see that file's docstring for why). Pins:

- vm_provisioning / vm_provisioning_failed codes are handled, and handled
  *separately* from the untouched no_vm_assigned branch (regression: the old
  branch must still exist verbatim for labs not in the auto-provision
  allowlist).
- The polling helper is imported and used.
- The generic retry message never mentions VMID/Proxmox/no_vm_assigned/`/app`.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.static

JS_DIR = Path(__file__).parent.parent / "frontend" / "js"


def _read(name: str) -> str:
    return (JS_DIR / name).read_text(encoding="utf-8")


class TestAutoProvisioningCodesHandled:
    def test_vm_provisioning_code_is_checked(self):
        js = _read("labgen-lab-init.js")
        assert "vm_provisioning" in js

    def test_vm_provisioning_failed_code_is_checked(self):
        js = _read("labgen-lab-init.js")
        assert "vm_provisioning_failed" in js

    def test_no_vm_assigned_branch_still_present(self):
        """Regression: labs outside the auto-provision allowlist still get the
        old /app redirect — this branch must not be removed or merged away."""
        js = _read("labgen-lab-init.js")
        assert "no_vm_assigned" in js
        assert "/app?next=" in js

    def test_auto_provisioning_branch_is_distinct_from_no_vm_assigned(self):
        js = _read("labgen-lab-init.js")
        vm_prov_idx = js.find("e.code === 'vm_provisioning'")
        no_vm_idx = js.find("e.code === 'no_vm_assigned'")
        assert vm_prov_idx != -1
        assert no_vm_idx != -1
        assert vm_prov_idx != no_vm_idx

    def test_imports_polling_helper(self):
        js = _read("labgen-lab-init.js")
        assert "waitForVmProvisioning" in js
        assert "/js/labgen-vm-wait.js" in js

    def test_polls_before_retrying_start_lab(self):
        js = _read("labgen-lab-init.js")
        wait_idx = js.find("waitForVmProvisioning(")
        assert wait_idx != -1
        retry_region = js[wait_idx: wait_idx + 700]
        assert "startLab(" in retry_region

    def test_polling_failure_does_not_strand_the_button(self):
        """Regression (Codex P2): if waitForVmProvisioning() itself rejects
        (status endpoint 5xx / network error), the button must be re-enabled,
        not left disabled forever on '正在准备实验环境…'."""
        js = _read("labgen-lab-init.js")
        fn_idx = js.find("async function _startAfterAutoProvisioning")
        assert fn_idx != -1
        fn_body = js[fn_idx: fn_idx + 900]
        wait_call_idx = fn_body.find("waitForVmProvisioning(")
        assert wait_call_idx != -1
        try_idx = fn_body.rfind("try {", 0, wait_call_idx)
        assert try_idx != -1, (
            "waitForVmProvisioning() call must be wrapped in try/catch so a "
            "rejected poll still re-enables the Start Lab button"
        )
        catch_region = fn_body[wait_call_idx: wait_call_idx + 450]
        assert "catch" in catch_region
        assert "btn.disabled = false" in catch_region

    def test_generic_retry_message_never_leaks_internal_concepts(self):
        js = _read("labgen-lab-init.js")
        text_idx = js.find("errDiv.textContent = '实验环境准备遇到问题")
        assert text_idx != -1, "generic retry message textContent assignment not found"
        line = js[text_idx: js.find("\n", text_idx)]
        for forbidden in ("VMID", "vm_id", "Proxmox", "/app", "no_vm_assigned"):
            assert forbidden not in line


class TestLabgenClientVmProvisioningStatus:
    def test_client_has_get_vm_provisioning_status(self):
        js = _read("labgenClient.js")
        assert "getVmProvisioningStatus" in js
        assert "/api/lab-sessions/vm-provisioning-status" in js


class TestLabgenVmWaitHelper:
    def test_waits_for_terminal_status(self):
        js = _read("labgen-vm-wait.js")
        assert "'ready'" in js
        assert "'failed'" in js

    def test_has_timeout_and_returns_timeout_status(self):
        js = _read("labgen-vm-wait.js")
        assert "timeoutMs" in js
        assert "'timeout'" in js
