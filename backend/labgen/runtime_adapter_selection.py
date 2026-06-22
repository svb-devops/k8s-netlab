"""
Runtime adapter selection service.

Determines which NamespaceLifecyclePort implementation to use based on
LABGEN_RUNTIME_MODE and LABGEN_NAMESPACE_ADAPTER configuration.

Deployment profiles:
  dev / test / demo  — stub adapter allowed (no real K8s ops).
  home_lab_mvp       — K3s on a physical server; stub forbidden; kubeconfig required.
  cloud              — EKS / ACK / managed K8s; stub forbidden;
                       kubeconfig OR in-cluster config required.
  production         — same semantics as home_lab_mvp (legacy alias, kept for compatibility).

Design contracts:
- Pure configuration analysis: no K8s calls, no namespace creation, no session state.
- home_lab_mvp / cloud / production mode with stub adapter is a blocking issue (fail closed).
- test/dev/demo mode with stub adapter emits a warning but is allowed.
- Invalid mode/adapter values are blocking issues (not silent fallbacks).
- No hardcoded host assumptions; all values come from env/config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from backend.labgen.namespace_lifecycle import K8sAdapterConfig, NamespaceLifecyclePort


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RuntimeMode(str, Enum):
    TEST = "test"
    DEV = "dev"
    DEMO = "demo"
    PRODUCTION = "production"
    HOME_LAB_MVP = "home_lab_mvp"
    CLOUD = "cloud"


class NamespaceAdapterKind(str, Enum):
    STUB = "stub"
    K8S = "k8s"
    LINUX = "linux"   # spike-level; not production-ready; not learner-visible


# ---------------------------------------------------------------------------
# Production-like modes: stub forbidden, real K8s adapter required.
# ---------------------------------------------------------------------------

_PRODUCTION_LIKE_MODES: frozenset[RuntimeMode] = frozenset({
    RuntimeMode.PRODUCTION,
    RuntimeMode.HOME_LAB_MVP,
    RuntimeMode.CLOUD,
})

# Modes that support in-cluster Kubernetes config (no kubeconfig file).
_IN_CLUSTER_MODES: frozenset[RuntimeMode] = frozenset({
    RuntimeMode.CLOUD,
})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class RuntimeAdapterSelectionIssue:
    code: str       # stable machine code
    severity: str   # "blocking" | "warning"
    message: str    # human-readable; must not contain credential values


@dataclass
class RuntimeAdapterSelectionResult:
    runtime_mode: RuntimeMode
    namespace_adapter_kind: NamespaceAdapterKind
    production_safe: bool
    issues: list[RuntimeAdapterSelectionIssue] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Issue codes (stable — never rename after release)
# ---------------------------------------------------------------------------

ISSUE_STUB_ADAPTER_IN_PRODUCTION = "STUB_ADAPTER_IN_PRODUCTION"
ISSUE_K8S_ADAPTER_NOT_CONFIGURED = "K8S_ADAPTER_NOT_CONFIGURED"
ISSUE_INVALID_RUNTIME_MODE = "INVALID_RUNTIME_MODE"
ISSUE_INVALID_ADAPTER_KIND = "INVALID_ADAPTER_KIND"
ISSUE_NON_PRODUCTION_STUB_ALLOWED = "NON_PRODUCTION_STUB_ALLOWED"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RuntimeAdapterSelectionService:
    """Evaluates the runtime adapter configuration and returns a selection result.

    Does NOT create adapters, namespaces, or sessions.
    Does NOT make network calls.
    Does NOT access kubeconfig files.
    """

    @classmethod
    def create_from_config(cls) -> RuntimeAdapterSelectionResult:
        """Read config module and return a selection result."""
        from backend import config as _cfg
        return cls.select(
            runtime_mode_raw=_cfg.LABGEN_RUNTIME_MODE,
            adapter_kind_raw=_cfg.LABGEN_NAMESPACE_ADAPTER,
            k8s_kubeconfig_path=_cfg.LABGEN_K8S_PLATFORM_KUBECONFIG_PATH,
            k8s_in_cluster=_cfg.LABGEN_K8S_IN_CLUSTER,
        )

    @classmethod
    def select(
        cls,
        runtime_mode_raw: str,
        adapter_kind_raw: str,
        k8s_kubeconfig_path: str = "",
        k8s_in_cluster: bool = False,
    ) -> RuntimeAdapterSelectionResult:
        """Pure selection logic — testable without importing config."""
        issues: list[RuntimeAdapterSelectionIssue] = []

        # Parse runtime_mode
        try:
            runtime_mode = RuntimeMode(runtime_mode_raw)
        except ValueError:
            valid = [m.value for m in RuntimeMode]
            issues.append(RuntimeAdapterSelectionIssue(
                code=ISSUE_INVALID_RUNTIME_MODE,
                severity="blocking",
                message=(
                    f"Unknown LABGEN_RUNTIME_MODE value '{runtime_mode_raw}'. "
                    f"Valid values: {valid}"
                ),
            ))
            runtime_mode = RuntimeMode.DEV  # safe fallback for further evaluation

        # Parse adapter_kind
        try:
            adapter_kind = NamespaceAdapterKind(adapter_kind_raw)
        except ValueError:
            valid_kinds = [k.value for k in NamespaceAdapterKind]
            issues.append(RuntimeAdapterSelectionIssue(
                code=ISSUE_INVALID_ADAPTER_KIND,
                severity="blocking",
                message=(
                    f"Unknown LABGEN_NAMESPACE_ADAPTER value '{adapter_kind_raw}'. "
                    f"Valid values: {valid_kinds}"
                ),
            ))
            adapter_kind = NamespaceAdapterKind.STUB  # safe fallback

        # Reject mutually exclusive K8s config — both set means misconfiguration.
        # K8sAdapterConfig.__post_init__ also rejects this, but we must catch it here
        # so that production_safe is never True when build_adapter() would crash.
        if k8s_kubeconfig_path and k8s_in_cluster:
            issues.append(RuntimeAdapterSelectionIssue(
                code=ISSUE_K8S_ADAPTER_NOT_CONFIGURED,
                severity="blocking",
                message=(
                    "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH and LABGEN_K8S_IN_CLUSTER=true "
                    "are mutually exclusive. Set exactly one."
                ),
            ))

        if runtime_mode in _PRODUCTION_LIKE_MODES:
            # Stub and Linux spike are forbidden in all production-like profiles.
            if adapter_kind == NamespaceAdapterKind.STUB:
                issues.append(RuntimeAdapterSelectionIssue(
                    code=ISSUE_STUB_ADAPTER_IN_PRODUCTION,
                    severity="blocking",
                    message=(
                        f"StubNamespaceLifecycleAdapter must not be used in "
                        f"{runtime_mode.value} mode. "
                        "Set LABGEN_NAMESPACE_ADAPTER=k8s and provide a kubeconfig or "
                        "in-cluster config."
                    ),
                ))
            elif adapter_kind == NamespaceAdapterKind.LINUX:
                issues.append(RuntimeAdapterSelectionIssue(
                    code=ISSUE_STUB_ADAPTER_IN_PRODUCTION,
                    severity="blocking",
                    message=(
                        f"LinuxContainerLifecycleAdapter (spike) must not be used in "
                        f"{runtime_mode.value} mode. "
                        "Linux runtime is not production-ready. "
                        "Set LABGEN_NAMESPACE_ADAPTER=k8s for production-like profiles."
                    ),
                ))
            elif adapter_kind == NamespaceAdapterKind.K8S:
                # cloud supports in-cluster; home_lab_mvp and production require kubeconfig.
                if runtime_mode in _IN_CLUSTER_MODES:
                    if not k8s_kubeconfig_path and not k8s_in_cluster:
                        issues.append(RuntimeAdapterSelectionIssue(
                            code=ISSUE_K8S_ADAPTER_NOT_CONFIGURED,
                            severity="blocking",
                            message=(
                                f"LABGEN_NAMESPACE_ADAPTER=k8s in {runtime_mode.value} mode "
                                "requires LABGEN_K8S_PLATFORM_KUBECONFIG_PATH or "
                                "LABGEN_K8S_IN_CLUSTER=true."
                            ),
                        ))
                else:
                    if not k8s_kubeconfig_path:
                        issues.append(RuntimeAdapterSelectionIssue(
                            code=ISSUE_K8S_ADAPTER_NOT_CONFIGURED,
                            severity="blocking",
                            message=(
                                f"LABGEN_NAMESPACE_ADAPTER=k8s in {runtime_mode.value} mode "
                                "requires LABGEN_K8S_PLATFORM_KUBECONFIG_PATH to be set."
                            ),
                        ))
        else:
            # Non-production-like: stub and Linux spike are allowed with a warning.
            if adapter_kind == NamespaceAdapterKind.STUB:
                issues.append(RuntimeAdapterSelectionIssue(
                    code=ISSUE_NON_PRODUCTION_STUB_ALLOWED,
                    severity="warning",
                    message=(
                        f"StubNamespaceLifecycleAdapter is active in {runtime_mode.value} mode. "
                        "No real K8s operations will occur. "
                        "This adapter must not be used in production-like profiles."
                    ),
                ))
            elif adapter_kind == NamespaceAdapterKind.LINUX:
                issues.append(RuntimeAdapterSelectionIssue(
                    code=ISSUE_NON_PRODUCTION_STUB_ALLOWED,
                    severity="warning",
                    message=(
                        f"LinuxContainerLifecycleAdapter (spike) is active in "
                        f"{runtime_mode.value} mode. "
                        "Linux runtime is not production-ready and not learner-visible. "
                        "This adapter must not be used in production-like profiles."
                    ),
                ))

        # production_safe: true only when production-like + k8s + valid config + no blocking
        blocking = [i for i in issues if i.severity == "blocking"]
        cloud_config_ok = bool(k8s_kubeconfig_path) or (
            runtime_mode in _IN_CLUSTER_MODES and k8s_in_cluster
        )
        non_cloud_config_ok = bool(k8s_kubeconfig_path)
        k8s_config_ok = (
            cloud_config_ok if runtime_mode in _IN_CLUSTER_MODES else non_cloud_config_ok
        )
        production_safe = (
            runtime_mode in _PRODUCTION_LIKE_MODES
            and adapter_kind == NamespaceAdapterKind.K8S
            and k8s_config_ok
            and len(blocking) == 0
        )

        return RuntimeAdapterSelectionResult(
            runtime_mode=runtime_mode,
            namespace_adapter_kind=adapter_kind,
            production_safe=production_safe,
            issues=issues,
        )

    @staticmethod
    def build_adapter(
        result: RuntimeAdapterSelectionResult,
        adapter_config: "Optional[K8sAdapterConfig]" = None,
    ) -> "NamespaceLifecyclePort":
        """Instantiate the selected adapter.

        For K8S adapter kind: pass adapter_config explicitly, or it is built from
        the application config module via K8sAdapterConfig.from_config().

        Does NOT validate production safety — callers must check result.production_safe
        and handle accordingly (e.g. reject lab start if unsafe in production).
        Does NOT make network calls.
        Does NOT read kubeconfig files at this point (lazy client init on first API call).
        """
        from backend.labgen.namespace_lifecycle import (
            K3sNamespaceLifecycleAdapter,
            K8sAdapterConfig,
            StubNamespaceLifecycleAdapter,
        )
        if result.namespace_adapter_kind == NamespaceAdapterKind.K8S:
            cfg = adapter_config if adapter_config is not None else K8sAdapterConfig.from_config()
            return K3sNamespaceLifecycleAdapter(cfg)
        if result.namespace_adapter_kind == NamespaceAdapterKind.LINUX:
            # Hard guard: LINUX adapter must never be instantiated in production-like modes.
            # This prevents a misconfigured LABGEN_NAMESPACE_ADAPTER=linux from silently
            # returning a broken adapter whose every method raises NotImplementedError.
            if result.runtime_mode in _PRODUCTION_LIKE_MODES:
                raise RuntimeError(
                    f"LinuxContainerLifecycleAdapter must not be used in "
                    f"{result.runtime_mode.value} mode. "
                    "Linux runtime is not production-ready. "
                    "Set LABGEN_NAMESPACE_ADAPTER=k8s."
                )
            from backend.labgen.namespace_lifecycle import LinuxContainerLifecycleAdapter
            return LinuxContainerLifecycleAdapter()
        return StubNamespaceLifecycleAdapter()
