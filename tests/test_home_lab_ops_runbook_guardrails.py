"""
Home-Lab MVP Ops Runbook Guardrail Tests.

Verifies that HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md:
- Exists in docs/labgen/
- Specifies initialize_verifier_for_vm_host_side as the required path for home_lab_mvp
- Explicitly forbids the QEMU-agent verifier init path (initialize_verifier_for_vm) for home_lab_mvp
- References platform kubeconfig
- Specifies staging VMID range 400-499
- Specifies production VMID 500-599 must not be touched
- States home_lab_mvp is non-HA
- Contains no TODO/FIXME
- Contains no ClusterRoleBinding as a required default path
- Is consistent with vm_manager.py function signatures
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytestmark = pytest.mark.static

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNBOOK_PATH = PROJECT_ROOT / "docs" / "labgen" / "HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md"


@pytest.fixture(scope="module")
def runbook_content() -> str:
    assert RUNBOOK_PATH.exists(), (
        f"HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md must exist at {RUNBOOK_PATH}"
    )
    return RUNBOOK_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Runbook existence
# ---------------------------------------------------------------------------

class TestRunbookExists:
    def test_runbook_file_exists(self):
        assert RUNBOOK_PATH.exists(), (
            "HOME_LAB_MVP_OPS_RUNBOOK_v0.1.md must exist in docs/labgen/"
        )

    def test_runbook_is_not_empty(self, runbook_content):
        assert len(runbook_content.strip()) > 500, "Runbook must have substantial content"

    def test_runbook_has_title(self, runbook_content):
        assert "Home-Lab MVP Ops Runbook" in runbook_content


# ---------------------------------------------------------------------------
# 2. Correct verifier initialization path for home_lab_mvp
# ---------------------------------------------------------------------------

class TestVerifierInitPath:
    def test_runbook_specifies_host_side_function(self, runbook_content):
        assert "initialize_verifier_for_vm_host_side" in runbook_content, (
            "Runbook must specify initialize_verifier_for_vm_host_side as the correct "
            "verifier initialization function for home_lab_mvp"
        )

    def test_runbook_forbids_qemu_agent_path_for_home_lab_mvp(self, runbook_content):
        # Runbook must explicitly say the QEMU-agent path is forbidden/not for home_lab_mvp
        forbidden_indicators = [
            "FORBIDDEN",
            "forbidden",
            "Do not use",
            "do not use",
            "must not",
            "MUST NOT",
        ]
        context_terms = [
            "initialize_verifier_for_vm",
            "QEMU",
            "QEMU-agent",
            "QEMU agent",
        ]
        # At least one prohibition phrase must appear alongside QEMU or the function name
        content_lower = runbook_content.lower()
        has_prohibition = any(f.lower() in content_lower for f in forbidden_indicators)
        has_qemu_context = (
            "qemu" in content_lower or
            "initialize_verifier_for_vm(" in runbook_content  # bare call = the forbidden one
        )
        assert has_prohibition and has_qemu_context, (
            "Runbook must explicitly forbid or warn against using initialize_verifier_for_vm "
            "(QEMU-agent path) for home_lab_mvp"
        )

    def test_runbook_explains_why_qemu_path_fails(self, runbook_content):
        # Must explain that 127.0.0.1 or the QEMU path produces an unreachable endpoint
        has_127 = "127.0.0.1" in runbook_content
        has_unreachable = any(
            term in runbook_content.lower()
            for term in ["unreachable", "not reachable", "cannot reach", "vm-local"]
        )
        assert has_127 or has_unreachable, (
            "Runbook must explain why QEMU-agent path fails for home_lab_mvp "
            "(server points to 127.0.0.1 which is unreachable from host)"
        )

    def test_runbook_specifies_platform_kubeconfig(self, runbook_content):
        assert "platform_kubeconfig_path" in runbook_content or \
               "platform kubeconfig" in runbook_content.lower(), (
            "Runbook must reference platform_kubeconfig_path (the required argument "
            "to initialize_verifier_for_vm_host_side)"
        )

    def test_runbook_does_not_require_cluster_role_binding_as_default(self, runbook_content):
        # ClusterRoleBinding may be mentioned but must not be a default required step
        if "ClusterRoleBinding" in runbook_content:
            # If mentioned, it must be in a "not required" or "not default" context
            idx = runbook_content.index("ClusterRoleBinding")
            surrounding = runbook_content[max(0, idx - 100):idx + 200].lower()
            assert any(
                neg in surrounding
                for neg in ["not", "no clusterrolebinding", "unless", "do not", "avoid"]
            ), (
                "ClusterRoleBinding must not be a required default step in the runbook"
            )

    def test_host_side_function_exists_in_vm_manager(self):
        """Cross-check: initialize_verifier_for_vm_host_side must exist in vm_manager.py."""
        vm_manager = PROJECT_ROOT / "backend" / "vm_manager.py"
        assert vm_manager.exists()
        content = vm_manager.read_text(encoding="utf-8")
        assert "def initialize_verifier_for_vm_host_side(" in content, (
            "initialize_verifier_for_vm_host_side must be defined in backend/vm_manager.py"
        )

    def test_host_side_function_accepts_platform_kubeconfig_arg(self):
        """Cross-check: host-side function must accept platform_kubeconfig_path argument."""
        vm_manager = PROJECT_ROOT / "backend" / "vm_manager.py"
        content = vm_manager.read_text(encoding="utf-8")
        fn_start = content.index("def initialize_verifier_for_vm_host_side(")
        fn_signature_window = content[fn_start:fn_start + 400]
        assert "platform_kubeconfig_path" in fn_signature_window, (
            "initialize_verifier_for_vm_host_side must accept platform_kubeconfig_path parameter"
        )

    def test_qemu_agent_function_still_exists_for_student_vms(self):
        """QEMU-agent function must still exist (it's valid for student VMs, just not home_lab_mvp)."""
        vm_manager = PROJECT_ROOT / "backend" / "vm_manager.py"
        content = vm_manager.read_text(encoding="utf-8")
        assert "def initialize_verifier_for_vm(" in content, (
            "initialize_verifier_for_vm (QEMU-agent) must still exist in vm_manager.py "
            "for student VM scenarios"
        )


# ---------------------------------------------------------------------------
# 3. VMID range boundaries
# ---------------------------------------------------------------------------

class TestVmidBoundaries:
    def test_runbook_specifies_staging_vmid_range_400_to_499(self, runbook_content):
        # Must contain 400-499 or 400–499 reference (staging range)
        has_range = "400–499" in runbook_content or "400-499" in runbook_content
        has_400 = "400" in runbook_content and "499" in runbook_content
        assert has_range or has_400, (
            "Runbook must specify staging VMID range 400-499"
        )

    def test_runbook_specifies_production_vmid_500_to_599_must_not_be_touched(self, runbook_content):
        # Must reference production range 500-599 with prohibition
        content_lower = runbook_content.lower()
        has_prod_range = "500–599" in runbook_content or "500-599" in runbook_content
        has_prohibition = any(
            phrase in content_lower
            for phrase in [
                "must not be touched",
                "must never",
                "never touch",
                "do not touch",
                "must not touch",
                "untouched",
            ]
        )
        assert has_prod_range, "Runbook must reference production VMID range 500-599"
        assert has_prohibition, (
            "Runbook must explicitly prohibit touching production VMID 500-599"
        )

    def test_runbook_staging_vm_in_staging_range(self, runbook_content):
        # Must mention VM 401 (or staging VMID) in staging pool context
        has_vm401 = "401" in runbook_content
        has_staging = "staging" in runbook_content.lower()
        assert has_vm401 and has_staging, (
            "Runbook must reference staging VM (e.g., VM 401) in staging pool context"
        )


# ---------------------------------------------------------------------------
# 4. Non-HA declaration
# ---------------------------------------------------------------------------

class TestNonHaDeclaration:
    def test_runbook_states_not_ha(self, runbook_content):
        has_not_ha = (
            "Not HA" in runbook_content or
            "non-HA" in runbook_content.lower() or
            "Non-HA" in runbook_content or
            "not HA" in runbook_content or
            "no HA" in runbook_content.lower() or
            "no SLA" in runbook_content.lower()
        )
        assert has_not_ha, (
            "Runbook must explicitly state that home_lab_mvp is non-HA "
            "(not a high-availability production environment)"
        )

    def test_runbook_does_not_claim_ha_production(self, runbook_content):
        # Must not claim to be HA or production-grade (affirmative claims without negation)
        # "not HA production" / "non-HA" are acceptable — checking for positive affirmations
        content_lower = runbook_content.lower()
        forbidden_affirmations = [
            "production-grade sla",
            "enterprise sla",
            "is ha production",
            "confirmed ha",
            "fully ha",
        ]
        for claim in forbidden_affirmations:
            assert claim not in content_lower, (
                f"Runbook must not positively affirm home_lab_mvp as HA or production-grade: "
                f"found {claim!r}"
            )


# ---------------------------------------------------------------------------
# 5. No TODO/FIXME
# ---------------------------------------------------------------------------

class TestNoTodoFixme:
    def test_runbook_has_no_todo(self, runbook_content):
        # Check for TODO as a standalone marker (not part of a word like "TODO-List")
        todo_matches = re.findall(r'\bTODO\b', runbook_content)
        assert not todo_matches, (
            f"Runbook must not contain TODO markers. Found {len(todo_matches)} instance(s)."
        )

    def test_runbook_has_no_fixme(self, runbook_content):
        fixme_matches = re.findall(r'\bFIXME\b', runbook_content)
        assert not fixme_matches, (
            f"Runbook must not contain FIXME markers. Found {len(fixme_matches)} instance(s)."
        )


# ---------------------------------------------------------------------------
# 6. No secret leakage in runbook
# ---------------------------------------------------------------------------

class TestNoSecretLeakage:
    def test_runbook_no_kubeconfig_content(self, runbook_content):
        # Should not contain actual kubeconfig YAML content (apiVersion, certificate-authority-data)
        secret_indicators = [
            "certificate-authority-data:",
            "client-certificate-data:",
            "client-key-data:",
            "token: ey",  # JWT token prefix
        ]
        for indicator in secret_indicators:
            assert indicator not in runbook_content, (
                f"Runbook must not contain actual kubeconfig secret data: found {indicator!r}"
            )

    def test_runbook_no_hardcoded_password(self, runbook_content):
        # Should not contain K8sLab@2026 or similar actual passwords
        assert "K8sLab@" not in runbook_content, (
            "Runbook must not contain hardcoded VM SSH password"
        )

    def test_runbook_placeholder_format_for_admin_token(self, runbook_content):
        # Admin token must appear as placeholder in commands, not as actual value
        if "ADMIN_TOKEN" in runbook_content:
            # If admin token is referenced, it must use placeholder syntax
            lines_with_token = [
                l for l in runbook_content.splitlines()
                if "ADMIN_TOKEN" in l or "admin-token" in l.lower()
            ]
            for line in lines_with_token:
                # Actual 64-char hex token would be suspicious
                # Acceptable: <staging-admin-token>, <set-in-secret-manager>, $ADMIN_TOKEN
                has_placeholder = "<" in line or "$" in line or "#" in line.lstrip()
                has_suspicious_value = bool(re.search(r'[0-9a-f]{32,}', line))
                if has_suspicious_value and not has_placeholder:
                    pytest.fail(
                        f"Runbook may contain actual admin token value in line: {line[:80]}"
                    )


# ---------------------------------------------------------------------------
# 7. OPS-INIT-001 resolution documented
# ---------------------------------------------------------------------------

class TestOpsInit001Resolved:
    def test_runbook_references_ops_init_001(self, runbook_content):
        assert "OPS-INIT-001" in runbook_content, (
            "Runbook must reference OPS-INIT-001 and its resolution"
        )

    def test_second_pilot_result_references_ops_init_001(self):
        result_doc = PROJECT_ROOT / "docs" / "labgen" / "SECOND_PILOT_USER_ONBOARDING_RESULT_v0.1.md"
        assert result_doc.exists()
        content = result_doc.read_text(encoding="utf-8")
        assert "OPS-INIT-001" in content, (
            "SECOND_PILOT_USER_ONBOARDING_RESULT_v0.1.md must reference OPS-INIT-001"
        )

    def test_runbook_path_referenced_in_second_pilot_result(self):
        result_doc = PROJECT_ROOT / "docs" / "labgen" / "SECOND_PILOT_USER_ONBOARDING_RESULT_v0.1.md"
        content = result_doc.read_text(encoding="utf-8")
        assert "OPS_RUNBOOK" in content or "ops_runbook" in content.lower() or \
               "HOME_LAB_MVP_OPS_RUNBOOK" in content or "Runbook" in content, (
            "SECOND_PILOT_USER_ONBOARDING_RESULT_v0.1.md should reference the ops runbook"
        )


# ---------------------------------------------------------------------------
# 8. Cloud portability preserved
# ---------------------------------------------------------------------------

class TestCloudPortability:
    def test_runbook_has_cloud_portability_section(self, runbook_content):
        has_portability = (
            "Cloud Portability" in runbook_content or
            "cloud portability" in runbook_content.lower() or
            "cloud migration" in runbook_content.lower()
        )
        assert has_portability, (
            "Runbook must contain a cloud portability or cloud migration section"
        )

    def test_runbook_does_not_hardcode_proxmox_in_core_logic_claim(self, runbook_content):
        # Runbook may reference Proxmox for ops commands, but must acknowledge
        # that core LabGen logic has no Proxmox coupling
        has_portability_claim = (
            "K3sNamespaceLifecycleAdapter" in runbook_content or
            "no Proxmox coupling" in runbook_content or
            "Kubernetes API only" in runbook_content or
            "provider-agnostic" in runbook_content.lower() or
            "Proxmox-specific" in runbook_content
        )
        assert has_portability_claim, (
            "Runbook must acknowledge that core LabGen namespace lifecycle has no Proxmox coupling"
        )

    def test_runbook_maps_host_side_init_to_cloud(self, runbook_content):
        # Must explain that initialize_verifier_for_vm_host_side works on cloud too
        has_cloud_mapping = (
            "EKS" in runbook_content or
            "ACK" in runbook_content or
            "cloud-managed kubeconfig" in runbook_content.lower() or
            ("cloud" in runbook_content.lower() and
             "initialize_verifier_for_vm_host_side" in runbook_content)
        )
        assert has_cloud_mapping, (
            "Runbook must explain how initialize_verifier_for_vm_host_side maps to cloud profiles"
        )


# ---------------------------------------------------------------------------
# 9. Emergency stop section is present
# ---------------------------------------------------------------------------

class TestEmergencyStop:
    def test_runbook_has_emergency_stop_section(self, runbook_content):
        has_emergency = (
            "Emergency Stop" in runbook_content or
            "emergency stop" in runbook_content.lower()
        )
        assert has_emergency, "Runbook must contain an emergency stop section"

    def test_emergency_stop_restricts_to_staging_range(self, runbook_content):
        # Emergency stop must only stop VMID 400-499, not 500-599
        content_lower = runbook_content.lower()
        has_staging_restriction = (
            "400" in runbook_content and
            "499" in runbook_content and
            ("production" in content_lower or "500" in runbook_content)
        )
        assert has_staging_restriction, (
            "Emergency stop section must restrict VM operations to staging VMID range (400-499) "
            "and explicitly not touch production range"
        )


# ---------------------------------------------------------------------------
# 10. Staging pool referenced
# ---------------------------------------------------------------------------

class TestStagingPool:
    def test_runbook_references_staging_pool(self, runbook_content):
        assert "k8s-netlab-staging" in runbook_content, (
            "Runbook must reference k8s-netlab-staging as the staging pool"
        )

    def test_runbook_references_verifier_credential_root(self, runbook_content):
        assert "verifier-credentials" in runbook_content or \
               "LABGEN_VERIFIER_CREDENTIAL_ROOT" in runbook_content, (
            "Runbook must reference verifier credential root path"
        )
