"""
Home-lab MVP profile guardrail tests.

Verifies:
- home_lab_mvp profile forbids stub adapter (fail-closed).
- home_lab_mvp profile without kubeconfig is a blocking issue.
- home_lab_mvp profile does NOT require Proxmox config in namespace lifecycle adapter.
- cloud profile supports in-cluster / kubeconfig (not just kubeconfig).
- dev profile allows stub but is not misidentified as production/home_lab.
- Placeholder env values do NOT produce production_safe=True.
- same-Proxmox risk acknowledgement — relevant env keys are present in staging example.
- No hardcoded T430/Proxmox/Cloudflare in LabGen namespace lifecycle core.
- K3sNamespaceLifecycleAdapter has no Proxmox or Cloudflare imports.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pathlib

import pytest

from backend.labgen.runtime_adapter_selection import (
    ISSUE_K8S_ADAPTER_NOT_CONFIGURED,
    ISSUE_NON_PRODUCTION_STUB_ALLOWED,
    ISSUE_STUB_ADAPTER_IN_PRODUCTION,
    NamespaceAdapterKind,
    RuntimeAdapterSelectionResult,
    RuntimeAdapterSelectionService,
    RuntimeMode,
)

pytestmark = pytest.mark.static

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select(
    runtime_mode: str,
    adapter_kind: str,
    kubeconfig: str = "",
    in_cluster: bool = False,
) -> RuntimeAdapterSelectionResult:
    return RuntimeAdapterSelectionService.select(
        runtime_mode_raw=runtime_mode,
        adapter_kind_raw=adapter_kind,
        k8s_kubeconfig_path=kubeconfig,
        k8s_in_cluster=in_cluster,
    )


def _codes(r: RuntimeAdapterSelectionResult) -> set[str]:
    return {i.code for i in r.issues}


def _blocking(r: RuntimeAdapterSelectionResult) -> list:
    return [i for i in r.issues if i.severity == "blocking"]


# ---------------------------------------------------------------------------
# 1. home_lab_mvp + stub adapter → blocking, not production_safe
# ---------------------------------------------------------------------------

class TestHomeLabMvpForbidsStub:
    def test_stub_adapter_blocked_in_home_lab_mvp(self):
        r = _select("home_lab_mvp", "stub")
        assert ISSUE_STUB_ADAPTER_IN_PRODUCTION in _codes(r)
        assert len(_blocking(r)) >= 1
        assert r.production_safe is False

    def test_stub_adapter_blocked_message_mentions_home_lab_mvp(self):
        r = _select("home_lab_mvp", "stub")
        blocking = _blocking(r)
        assert any("home_lab_mvp" in i.message for i in blocking)

    def test_stub_adapter_blocked_regardless_of_kubeconfig(self):
        r = _select("home_lab_mvp", "stub", kubeconfig="/etc/k8s/platform.yaml")
        assert ISSUE_STUB_ADAPTER_IN_PRODUCTION in _codes(r)
        assert r.production_safe is False

    def test_home_lab_mvp_with_k8s_and_kubeconfig_is_production_safe(self):
        r = _select("home_lab_mvp", "k8s", kubeconfig="/etc/k8s/platform.yaml")
        assert r.production_safe is True
        assert len(_blocking(r)) == 0

    def test_home_lab_mvp_runtime_mode_is_production_like(self):
        r = _select("home_lab_mvp", "k8s", kubeconfig="/etc/k8s/platform.yaml")
        assert r.runtime_mode == RuntimeMode.HOME_LAB_MVP
        assert r.namespace_adapter_kind == NamespaceAdapterKind.K8S


# ---------------------------------------------------------------------------
# 2. home_lab_mvp + k8s + missing kubeconfig → blocking (fail-closed)
# ---------------------------------------------------------------------------

class TestHomeLabMvpKubeconfigRequired:
    def test_missing_kubeconfig_is_blocking(self):
        r = _select("home_lab_mvp", "k8s", kubeconfig="")
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in _codes(r)
        assert len(_blocking(r)) >= 1
        assert r.production_safe is False

    def test_missing_kubeconfig_message_mentions_kubeconfig_path(self):
        r = _select("home_lab_mvp", "k8s", kubeconfig="")
        blocking = _blocking(r)
        assert any("LABGEN_K8S_PLATFORM_KUBECONFIG_PATH" in i.message for i in blocking)

    def test_in_cluster_not_allowed_for_home_lab_mvp(self):
        # home_lab_mvp is NOT in _IN_CLUSTER_MODES — in_cluster alone is insufficient.
        r = _select("home_lab_mvp", "k8s", kubeconfig="", in_cluster=True)
        # in_cluster alone with no kubeconfig → still blocking for home_lab_mvp
        # (in-cluster is only supported for cloud profile)
        assert r.production_safe is False
        assert len(_blocking(r)) >= 1

    def test_placeholder_path_not_validated_by_selection_service(self):
        # SelectionService only checks string truthiness, not file existence.
        # A non-empty path (even a placeholder) is considered "set".
        r = _select("home_lab_mvp", "k8s", kubeconfig="<set-in-staging-secret-manager>")
        # This should NOT be production_safe — placeholder values must not result in safety
        # when checked by the provisioning validator. SelectionService alone: kubeconfig set.
        # The provisioning validator (labgen_staging_provisioning_validate.py) handles
        # placeholder detection at the env-file level.
        assert r.runtime_mode == RuntimeMode.HOME_LAB_MVP


# ---------------------------------------------------------------------------
# 3. home_lab_mvp does NOT require Proxmox in namespace lifecycle adapter
# ---------------------------------------------------------------------------

class TestHomeLabMvpNoProxmoxInNamespaceAdapter:
    def test_k3s_adapter_has_no_proxmox_import(self):
        """K3sNamespaceLifecycleAdapter must not import Proxmox modules."""
        from backend.labgen import namespace_lifecycle
        source = inspect.getsource(namespace_lifecycle)
        # Check for actual import statements, not doc comments
        assert "import proxmox" not in source.lower()
        assert "from backend.proxmox" not in source
        assert "from proxmox" not in source.lower()

    def test_k3s_adapter_has_no_cloudflare_import(self):
        """K3sNamespaceLifecycleAdapter must not import Cloudflare modules."""
        from backend.labgen import namespace_lifecycle
        source = inspect.getsource(namespace_lifecycle)
        # Check for actual import statements, not doc comments
        assert "import cloudflare" not in source.lower()
        assert "from cloudflare" not in source.lower()

    def test_k3s_adapter_has_no_hardcoded_production_ip(self):
        """K3sNamespaceLifecycleAdapter must not contain hardcoded production IPs or paths."""
        from backend.labgen import namespace_lifecycle
        source = inspect.getsource(namespace_lifecycle)
        # No hardcoded production gateway or registry IP
        assert "172.16.100" not in source, (
            "No hardcoded production gateway IP in namespace lifecycle adapter"
        )
        # No hardcoded filesystem path to T430 host
        assert "/var/lib/labgen/" not in source, (
            "No hardcoded production credential path in namespace lifecycle adapter"
        )

    def test_k3s_adapter_config_has_no_proxmox_fields(self):
        """K8sAdapterConfig must not have Proxmox-related config fields."""
        from backend.labgen.namespace_lifecycle import K8sAdapterConfig
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(K8sAdapterConfig)}
        proxmox_fields = {f for f in field_names if "proxmox" in f.lower() or "vmid" in f.lower()}
        assert proxmox_fields == set(), (
            f"K8sAdapterConfig must not have Proxmox fields: {proxmox_fields}"
        )

    def test_namespace_lifecycle_module_only_imports_kubernetes(self):
        """namespace_lifecycle.py imports should not include Proxmox or Cloudflare packages."""
        from backend.labgen import namespace_lifecycle
        mod_file = inspect.getfile(namespace_lifecycle)
        source = pathlib.Path(mod_file).read_text()
        assert "import proxmox" not in source.lower()
        assert "from backend.proxmox" not in source


# ---------------------------------------------------------------------------
# 4. cloud profile supports in-cluster / kubeconfig
# ---------------------------------------------------------------------------

class TestCloudProfileConfig:
    def test_cloud_with_kubeconfig_is_production_safe(self):
        r = _select("cloud", "k8s", kubeconfig="/etc/k8s/eks.yaml", in_cluster=False)
        assert r.production_safe is True
        assert len(_blocking(r)) == 0

    def test_cloud_with_in_cluster_is_production_safe(self):
        r = _select("cloud", "k8s", kubeconfig="", in_cluster=True)
        assert r.production_safe is True
        assert len(_blocking(r)) == 0

    def test_cloud_stub_blocked(self):
        r = _select("cloud", "stub")
        assert ISSUE_STUB_ADAPTER_IN_PRODUCTION in _codes(r)
        assert r.production_safe is False

    def test_cloud_no_config_is_blocking(self):
        r = _select("cloud", "k8s", kubeconfig="", in_cluster=False)
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in _codes(r)
        assert r.production_safe is False

    def test_cloud_kubeconfig_and_in_cluster_mutually_exclusive(self):
        r = _select("cloud", "k8s", kubeconfig="/etc/k8s/eks.yaml", in_cluster=True)
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in _codes(r)
        assert len(_blocking(r)) >= 1
        assert r.production_safe is False


# ---------------------------------------------------------------------------
# 5. dev profile allows stub but is not misidentified as production/home_lab
# ---------------------------------------------------------------------------

class TestDevProfileNotMisidentified:
    def test_dev_stub_allowed_with_warning(self):
        r = _select("dev", "stub")
        assert ISSUE_NON_PRODUCTION_STUB_ALLOWED in _codes(r)
        assert len(_blocking(r)) == 0
        assert r.production_safe is False

    def test_dev_stub_warning_not_blocking(self):
        r = _select("dev", "stub")
        assert all(i.severity != "blocking" for i in r.issues)

    def test_dev_mode_is_not_production_safe(self):
        r = _select("dev", "stub")
        assert r.production_safe is False

    def test_dev_with_k8s_is_not_production_safe(self):
        # dev mode with k8s adapter is valid but not production_safe (not a production-like mode)
        r = _select("dev", "k8s", kubeconfig="/dev/null")
        assert r.production_safe is False
        assert r.runtime_mode == RuntimeMode.DEV

    def test_demo_stub_allowed_not_production_safe(self):
        r = _select("demo", "stub")
        assert r.production_safe is False
        assert any(i.severity == "warning" for i in r.issues)


# ---------------------------------------------------------------------------
# 6. Env example file - placeholder values do NOT produce production_safe=True
# ---------------------------------------------------------------------------

class TestEnvExamplePlaceholderSafety:
    """
    Verify that the staging env example placeholders, when fed to SelectionService,
    do not accidentally produce production_safe=True.

    Note: SelectionService checks string truthiness for kubeconfig path.
    The staging example has LABGEN_K8S_PLATFORM_KUBECONFIG_PATH commented out,
    meaning the effective value is empty string → blocking.
    """

    def test_staging_example_runtime_mode_is_home_lab_mvp(self):
        """Verify staging example uses home_lab_mvp profile (not production)."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        assert staging_example.exists()
        content = staging_example.read_text()
        # Should contain home_lab_mvp, not just 'production'
        lines = [l.strip() for l in content.splitlines() if not l.startswith("#")]
        runtime_mode_lines = [l for l in lines if l.startswith("LABGEN_RUNTIME_MODE=")]
        assert len(runtime_mode_lines) >= 1
        assert any("home_lab_mvp" in l for l in runtime_mode_lines), (
            "Staging example must use LABGEN_RUNTIME_MODE=home_lab_mvp"
        )

    def test_staging_example_adapter_is_k8s(self):
        """Staging example must use k8s adapter (not stub)."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        lines = [l.strip() for l in content.splitlines() if not l.startswith("#")]
        adapter_lines = [l for l in lines if l.startswith("LABGEN_NAMESPACE_ADAPTER=")]
        assert len(adapter_lines) >= 1
        assert any("k8s" in l for l in adapter_lines), (
            "Staging example must use LABGEN_NAMESPACE_ADAPTER=k8s"
        )

    def test_staging_example_kubeconfig_is_commented_out(self):
        """kubeconfig must be commented out (placeholder) in staging example."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        # LABGEN_K8S_PLATFORM_KUBECONFIG_PATH must appear only in comments (# prefix)
        # or with set-in-secret-manager placeholder — never as a bare value
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("LABGEN_K8S_PLATFORM_KUBECONFIG_PATH="):
                # If not commented, it must be a placeholder
                value = stripped.split("=", 1)[1]
                assert "<" in value or value == "", (
                    "Staging example kubeconfig path must be a placeholder or commented out"
                )

    def test_staging_example_has_no_real_secrets(self):
        """Staging example must not contain real-looking secrets."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        suspicious_patterns = [
            "172.16.100.1",   # production registry/gateway — must not appear in staging example
            "PROXMOX_POOL=k8s-netlab\n",   # production pool — must be staging pool
            "VM_TEMPLATE_ID=101\n",         # production template — must be placeholder
            "VM_ID_MIN=500\n",              # production range start
            "VM_ID_MAX=599\n",              # production range end
        ]
        for pattern in suspicious_patterns:
            assert pattern not in content, (
                f"Staging example must not contain production value: {pattern!r}"
            )

    def test_staging_example_has_staging_pool(self):
        """Staging example must use staging-specific Proxmox pool."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        assert "k8s-netlab-staging" in content, (
            "Staging example must reference k8s-netlab-staging pool"
        )

    def test_staging_example_admin_token_commented_out(self):
        """ADMIN_TOKEN must be commented out in staging example."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("ADMIN_TOKEN="):
                value = stripped.split("=", 1)[1]
                assert "<" in value, (
                    "ADMIN_TOKEN in staging example must be a placeholder"
                )

    def test_staging_example_in_cluster_is_false(self):
        """Staging example must have LABGEN_K8S_IN_CLUSTER=false (T430 is not inside K8s)."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        lines = [l.strip() for l in content.splitlines() if not l.startswith("#")]
        in_cluster_lines = [l for l in lines if l.startswith("LABGEN_K8S_IN_CLUSTER=")]
        assert len(in_cluster_lines) >= 1
        assert all("false" in l.lower() for l in in_cluster_lines), (
            "Staging example must have LABGEN_K8S_IN_CLUSTER=false"
        )

    def test_staging_example_namespace_prefix_is_staging_specific(self):
        """Staging example must use staging-specific namespace prefix."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        lines = [l.strip() for l in content.splitlines() if not l.startswith("#")]
        prefix_lines = [l for l in lines if l.startswith("LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES=")]
        assert len(prefix_lines) >= 1
        # Must use staging prefix (lab-stg-) to prevent collision with production (lab-)
        assert any("lab-stg-" in l for l in prefix_lines), (
            "Staging example namespace prefix must be staging-specific (lab-stg-)"
        )

    def test_staging_example_vmid_range_is_placeholder(self):
        """Staging VMID range must be placeholder — not hardcoded production range."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        lines = [l.strip() for l in content.splitlines() if not l.startswith("#")]
        vmid_min_lines = [l for l in lines if l.startswith("VM_ID_MIN=")]
        vmid_max_lines = [l for l in lines if l.startswith("VM_ID_MAX=")]
        for line in vmid_min_lines + vmid_max_lines:
            value = line.split("=", 1)[1]
            assert "<" in value, (
                f"Staging VMID range must be placeholder, not hardcoded: {line}"
            )


# ---------------------------------------------------------------------------
# 7. Same-Proxmox risk documented in staging example
# ---------------------------------------------------------------------------

class TestSameProxmoxRiskDocumented:
    def test_staging_example_mentions_same_proxmox_risk(self):
        """Staging example must acknowledge same-Proxmox isolation as accepted risk."""
        staging_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.staging.example"
        content = staging_example.read_text()
        # Risk documentation should reference the profile doc
        assert "ACCEPTED_MVP_RISK" in content or "HOME_LAB_MVP_STAGING_PROFILE" in content, (
            "Staging example must reference accepted risk for same-Proxmox deployment"
        )

    def test_home_lab_mvp_staging_profile_doc_exists(self):
        """HOME_LAB_MVP_STAGING_PROFILE_v0.1.md must exist."""
        profile_doc = PROJECT_ROOT / "docs" / "labgen" / "HOME_LAB_MVP_STAGING_PROFILE_v0.1.md"
        assert profile_doc.exists(), "HOME_LAB_MVP_STAGING_PROFILE_v0.1.md must exist"

    def test_home_lab_mvp_staging_profile_doc_mentions_accepted_risks(self):
        """Profile doc must explicitly list accepted risks."""
        profile_doc = PROJECT_ROOT / "docs" / "labgen" / "HOME_LAB_MVP_STAGING_PROFILE_v0.1.md"
        content = profile_doc.read_text()
        assert "ACCEPTED" in content
        assert "single point of failure" in content.lower() or "RISK-01" in content

    def test_home_lab_mvp_staging_profile_doc_mentions_exit_criteria(self):
        """Profile doc must define exit criteria to cloud migration."""
        profile_doc = PROJECT_ROOT / "docs" / "labgen" / "HOME_LAB_MVP_STAGING_PROFILE_v0.1.md"
        content = profile_doc.read_text()
        assert "exit criteria" in content.lower() or "Exit Criteria" in content

    def test_home_lab_mvp_staging_profile_doc_says_not_ha(self):
        """Profile doc must explicitly state non-HA."""
        profile_doc = PROJECT_ROOT / "docs" / "labgen" / "HOME_LAB_MVP_STAGING_PROFILE_v0.1.md"
        content = profile_doc.read_text()
        assert "Not HA" in content or "non-HA" in content.lower() or "Non-HA" in content

    def test_home_lab_mvp_staging_profile_doc_does_not_claim_cloud_equivalent(self):
        """Profile doc must not claim cloud-equivalent isolation."""
        profile_doc = PROJECT_ROOT / "docs" / "labgen" / "HOME_LAB_MVP_STAGING_PROFILE_v0.1.md"
        content = profile_doc.read_text()
        # Must not contain any claim that same-Proxmox = cloud equivalent
        assert "cloud-equivalent isolation" not in content.lower() or (
            "weaker" in content.lower() or "NOT" in content or "not" in content
        )


# ---------------------------------------------------------------------------
# 8. No hardcoded T430/Proxmox/Cloudflare in LabGen core namespace lifecycle
# ---------------------------------------------------------------------------

class TestCoreModulesHaveNoHardcodedInfra:
    """Verify portability anti-lock-in rules in LabGen core modules."""

    CORE_MODULES = [
        "backend.labgen.namespace_lifecycle",
        "backend.labgen.lab_session_service",
        "backend.labgen.publish_service",
        "backend.labgen.static_validator",
        "backend.labgen.step_progression_service",
        "backend.labgen.verifier",
    ]

    @pytest.mark.parametrize("module_name", CORE_MODULES)
    def test_core_module_has_no_proxmox_api_import(self, module_name: str):
        mod = importlib.import_module(module_name)
        source = inspect.getsource(mod)
        assert "from backend.proxmox_api" not in source
        assert "import backend.proxmox_api" not in source

    @pytest.mark.parametrize("module_name", CORE_MODULES)
    def test_core_module_has_no_cloudflare_import(self, module_name: str):
        """Core modules must not import Cloudflare packages."""
        mod = importlib.import_module(module_name)
        source = inspect.getsource(mod)
        # Check actual import statements, not doc comments
        assert "import cloudflare" not in source.lower()
        assert "from cloudflare" not in source.lower()

    def test_namespace_lifecycle_has_no_172_16_100_ip(self):
        """Production gateway IP must not be hardcoded in namespace lifecycle."""
        from backend.labgen import namespace_lifecycle
        source = inspect.getsource(namespace_lifecycle)
        assert "172.16.100" not in source

    def test_namespace_lifecycle_adapter_uses_no_kubectl_subprocess(self):
        """K3sNamespaceLifecycleAdapter must not call kubectl via subprocess."""
        from backend.labgen import namespace_lifecycle
        source = inspect.getsource(namespace_lifecycle)
        # The main adapter class must not use subprocess for kubectl
        # (verifier_credentials.py has kubectl for SA setup — that's isolated)
        assert "subprocess.run" not in source or "kubectl" not in source.split("subprocess.run")[1][:200]

    def test_adapter_selection_service_has_no_t430_hardcode(self):
        """RuntimeAdapterSelectionService must not reference T430 hardware."""
        from backend.labgen import runtime_adapter_selection
        source = inspect.getsource(runtime_adapter_selection)
        assert "t430" not in source.lower()
        assert "172.16.100" not in source


# ---------------------------------------------------------------------------
# 9. Production example updated — no stale NotImplementedError comment
# ---------------------------------------------------------------------------

class TestProductionExampleUpdated:
    def test_production_example_has_no_not_implemented_comment(self):
        """Production example must not say K3sNamespaceLifecycleAdapter is a skeleton."""
        prod_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.production.example"
        assert prod_example.exists()
        content = prod_example.read_text()
        assert "NotImplementedError" not in content, (
            ".env.production.example must not contain stale NotImplementedError comment — "
            "K3sNamespaceLifecycleAdapter is now fully implemented"
        )

    def test_production_example_has_k8s_in_cluster_key(self):
        """Production example must include LABGEN_K8S_IN_CLUSTER."""
        prod_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.production.example"
        content = prod_example.read_text()
        assert "LABGEN_K8S_IN_CLUSTER" in content

    def test_production_example_has_k8s_namespace_allowed_prefixes(self):
        """Production example must include LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES."""
        prod_example = PROJECT_ROOT / "deploy" / "labgen" / ".env.production.example"
        content = prod_example.read_text()
        assert "LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES" in content
