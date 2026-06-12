"""
Namespace lifecycle portability tests.

Verifies the portability contract:
- K3sNamespaceLifecycleAdapter uses the same Kubernetes API path for all deployment profiles.
- No Proxmox, T430, or Cloudflare Tunnel dependencies in the namespace lifecycle adapter.
- home_lab_mvp profile uses real K8s adapter (same code as cloud profile).
- cloud profile supports in-cluster config.
- Proxmox / registry / Cloudflare config is NOT required by the namespace adapter.
- No hardcoded host assumptions.
- Stub adapter blocked in home_lab_mvp / cloud / production profiles.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from backend.labgen.namespace_lifecycle import (
    K3sNamespaceLifecycleAdapter,
    K8sAdapterConfig,
    NamespaceAdapterConfigError,
    StubNamespaceLifecycleAdapter,
)
from backend.labgen.runtime_adapter_selection import (
    ISSUE_K8S_ADAPTER_NOT_CONFIGURED,
    ISSUE_NON_PRODUCTION_STUB_ALLOWED,
    ISSUE_STUB_ADAPTER_IN_PRODUCTION,
    NamespaceAdapterKind,
    RuntimeAdapterSelectionService,
    RuntimeMode,
)

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select(runtime_mode: str, adapter_kind: str, kubeconfig: str = "", in_cluster: bool = False):
    return RuntimeAdapterSelectionService.select(
        runtime_mode_raw=runtime_mode,
        adapter_kind_raw=adapter_kind,
        k8s_kubeconfig_path=kubeconfig,
        k8s_in_cluster=in_cluster,
    )


class StubClientLoader:
    def __init__(self) -> None:
        self.core_v1 = MagicMock()
        self.rbac_v1 = MagicMock()

    def build(self, config: K8sAdapterConfig):
        return self.core_v1, self.rbac_v1


def _k8s_config(kubeconfig: str = "/etc/k8s.yaml", in_cluster: bool = False) -> K8sAdapterConfig:
    if in_cluster:
        return K8sAdapterConfig(in_cluster=True, allowed_namespace_prefixes=["lab-"])
    return K8sAdapterConfig(
        kubeconfig_path=kubeconfig,
        allowed_namespace_prefixes=["lab-"],
    )


# ---------------------------------------------------------------------------
# Profile selection correctness
# ---------------------------------------------------------------------------

class TestDeploymentProfiles:
    def test_dev_stub_allowed_with_warning(self):
        r = _select("dev", "stub")
        assert r.runtime_mode == RuntimeMode.DEV
        assert not r.production_safe
        codes = {i.code for i in r.issues}
        assert ISSUE_NON_PRODUCTION_STUB_ALLOWED in codes
        blocking = [i for i in r.issues if i.severity == "blocking"]
        assert len(blocking) == 0

    def test_home_lab_mvp_stub_forbidden(self):
        r = _select("home_lab_mvp", "stub")
        assert r.production_safe is False
        codes = {i.code for i in r.issues}
        assert ISSUE_STUB_ADAPTER_IN_PRODUCTION in codes
        blocking = [i for i in r.issues if i.severity == "blocking"]
        assert len(blocking) >= 1

    def test_home_lab_mvp_k8s_no_kubeconfig_forbidden(self):
        r = _select("home_lab_mvp", "k8s", kubeconfig="")
        assert r.production_safe is False
        codes = {i.code for i in r.issues}
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in codes

    def test_home_lab_mvp_k8s_kubeconfig_production_safe(self):
        r = _select("home_lab_mvp", "k8s", kubeconfig="/etc/k8s/platform.yaml")
        assert r.production_safe is True
        assert len([i for i in r.issues if i.severity == "blocking"]) == 0

    def test_cloud_stub_forbidden(self):
        r = _select("cloud", "stub")
        assert r.production_safe is False
        codes = {i.code for i in r.issues}
        assert ISSUE_STUB_ADAPTER_IN_PRODUCTION in codes

    def test_cloud_k8s_kubeconfig_production_safe(self):
        r = _select("cloud", "k8s", kubeconfig="/etc/k8s/eks.yaml")
        assert r.production_safe is True

    def test_cloud_k8s_in_cluster_production_safe(self):
        r = _select("cloud", "k8s", in_cluster=True)
        assert r.production_safe is True

    def test_cloud_k8s_neither_kubeconfig_nor_in_cluster_blocked(self):
        r = _select("cloud", "k8s", kubeconfig="", in_cluster=False)
        assert r.production_safe is False
        codes = {i.code for i in r.issues}
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in codes

    def test_home_lab_mvp_in_cluster_not_sufficient(self):
        # home_lab_mvp requires kubeconfig path; in-cluster not accepted
        r = _select("home_lab_mvp", "k8s", kubeconfig="", in_cluster=True)
        assert r.production_safe is False
        codes = {i.code for i in r.issues}
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in codes

    def test_production_mode_backward_compatible(self):
        r = _select("production", "k8s", kubeconfig="/etc/k8s/platform.yaml")
        assert r.production_safe is True

    def test_production_stub_still_blocked(self):
        r = _select("production", "stub")
        codes = {i.code for i in r.issues}
        assert ISSUE_STUB_ADAPTER_IN_PRODUCTION in codes


# ---------------------------------------------------------------------------
# Same adapter code for all production-like profiles
# ---------------------------------------------------------------------------

class TestSameAdapterCodeForAllProfiles:
    def _build_with_fake_loader(self, profile: str, kubeconfig: str = "/etc/k8s.yaml"):
        r = _select(profile, "k8s", kubeconfig=kubeconfig)
        cfg = _k8s_config(kubeconfig=kubeconfig)
        adapter = RuntimeAdapterSelectionService.build_adapter(r, adapter_config=cfg)
        return adapter

    def test_home_lab_mvp_returns_k3s_adapter(self):
        adapter = self._build_with_fake_loader("home_lab_mvp")
        assert isinstance(adapter, K3sNamespaceLifecycleAdapter)

    def test_cloud_returns_k3s_adapter(self):
        adapter = self._build_with_fake_loader("cloud")
        assert isinstance(adapter, K3sNamespaceLifecycleAdapter)

    def test_production_returns_k3s_adapter(self):
        adapter = self._build_with_fake_loader("production")
        assert isinstance(adapter, K3sNamespaceLifecycleAdapter)

    def test_dev_stub_returns_stub_adapter(self):
        r = _select("dev", "stub")
        adapter = RuntimeAdapterSelectionService.build_adapter(r)
        assert isinstance(adapter, StubNamespaceLifecycleAdapter)

    def test_all_production_like_adapters_share_same_implementation(self):
        """home_lab_mvp and cloud use the identical K3sNamespaceLifecycleAdapter class."""
        cfg = _k8s_config()
        r_home = _select("home_lab_mvp", "k8s", kubeconfig="/etc/k8s.yaml")
        r_cloud = _select("cloud", "k8s", kubeconfig="/etc/k8s.yaml")
        a_home = RuntimeAdapterSelectionService.build_adapter(r_home, adapter_config=cfg)
        a_cloud = RuntimeAdapterSelectionService.build_adapter(r_cloud, adapter_config=cfg)
        assert type(a_home) is type(a_cloud)


# ---------------------------------------------------------------------------
# Portability: adapter does NOT require Proxmox / registry / Cloudflare config
# ---------------------------------------------------------------------------

class TestAdapterPortabilityIsolation:
    def _make_adapter(self) -> K3sNamespaceLifecycleAdapter:
        cfg = K8sAdapterConfig(
            kubeconfig_path="/etc/k8s/platform.yaml",
            allowed_namespace_prefixes=["lab-"],
        )
        stub_loader = StubClientLoader()
        return K3sNamespaceLifecycleAdapter(cfg, loader=stub_loader)

    def test_adapter_has_no_proxmox_attribute(self):
        adapter = self._make_adapter()
        assert not hasattr(adapter, "proxmox_host")
        assert not hasattr(adapter, "proxmox_token")
        assert not hasattr(adapter, "vm_id_range")

    def test_adapter_has_no_cloudflare_attribute(self):
        adapter = self._make_adapter()
        assert not hasattr(adapter, "cloudflare_tunnel")
        assert not hasattr(adapter, "cloudflare_token")

    def test_adapter_has_no_registry_attribute(self):
        adapter = self._make_adapter()
        assert not hasattr(adapter, "registry_mirror")
        assert not hasattr(adapter, "registry_url")

    def test_k8s_adapter_config_contains_no_proxmox_fields(self):
        cfg = _k8s_config()
        assert not hasattr(cfg, "proxmox_host")
        assert not hasattr(cfg, "vm_bridge")
        assert not hasattr(cfg, "cloudflare_tunnel")

    def test_kubeconfig_path_accepts_any_path_not_hardcoded(self):
        # Any path string is accepted — no hardcoded server assumptions
        for path in [
            "/etc/k8s/platform.yaml",
            "/var/lib/labgen/kubeconfig",
            "/home/ops/eks-kubeconfig",
            "/run/secrets/k8s.yaml",
        ]:
            cfg = K8sAdapterConfig(
                kubeconfig_path=path,
                allowed_namespace_prefixes=["lab-"],
            )
            assert cfg.kubeconfig_path == path


# ---------------------------------------------------------------------------
# in-cluster config support (cloud profile)
# ---------------------------------------------------------------------------

class TestInClusterConfig:
    def test_in_cluster_config_valid(self):
        cfg = K8sAdapterConfig(in_cluster=True, allowed_namespace_prefixes=["lab-"])
        assert cfg.in_cluster is True
        assert cfg.kubeconfig_path == ""

    def test_in_cluster_and_kubeconfig_path_mutually_exclusive(self):
        with pytest.raises(NamespaceAdapterConfigError):
            K8sAdapterConfig(
                kubeconfig_path="/etc/k8s.yaml",
                in_cluster=True,
                allowed_namespace_prefixes=["lab-"],
            )

    def test_cloud_profile_selects_in_cluster_config(self):
        r = _select("cloud", "k8s", kubeconfig="", in_cluster=True)
        assert r.production_safe is True
        cfg = K8sAdapterConfig(in_cluster=True, allowed_namespace_prefixes=["lab-"])
        adapter = RuntimeAdapterSelectionService.build_adapter(r, adapter_config=cfg)
        assert isinstance(adapter, K3sNamespaceLifecycleAdapter)

    def test_adapter_with_in_cluster_config_operates_on_api(self):
        cfg = K8sAdapterConfig(in_cluster=True, allowed_namespace_prefixes=["lab-"])
        stub_loader = StubClientLoader()
        adapter = K3sNamespaceLifecycleAdapter(cfg, loader=stub_loader)
        result = adapter.create_namespace("lab-abc")
        assert result is True
        stub_loader.core_v1.create_namespace.assert_called_once()
