"""
Runtime adapter selection service.

Determines which NamespaceLifecyclePort implementation to use based on
LABGEN_RUNTIME_MODE and LABGEN_NAMESPACE_ADAPTER configuration.

Design contracts:
- Pure configuration analysis: no K8s calls, no namespace creation, no session state.
- production mode requires k8s adapter + LABGEN_K8S_PLATFORM_KUBECONFIG_PATH set.
- production mode with stub adapter is a blocking issue (fail closed at lab start).
- test/dev/demo mode with stub adapter emits a warning but is allowed.
- Invalid mode/adapter values are blocking issues (not silent fallbacks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.labgen.namespace_lifecycle import NamespaceLifecyclePort


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RuntimeMode(str, Enum):
    TEST = "test"
    DEV = "dev"
    DEMO = "demo"
    PRODUCTION = "production"


class NamespaceAdapterKind(str, Enum):
    STUB = "stub"
    K8S = "k8s"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class RuntimeAdapterSelectionIssue:
    code: str       # stable machine code, e.g. STUB_ADAPTER_IN_PRODUCTION
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
    """
    Evaluates the runtime adapter configuration and returns a selection result.

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
        )

    @classmethod
    def select(
        cls,
        runtime_mode_raw: str,
        adapter_kind_raw: str,
        k8s_kubeconfig_path: str = "",
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
            valid = [k.value for k in NamespaceAdapterKind]
            issues.append(RuntimeAdapterSelectionIssue(
                code=ISSUE_INVALID_ADAPTER_KIND,
                severity="blocking",
                message=(
                    f"Unknown LABGEN_NAMESPACE_ADAPTER value '{adapter_kind_raw}'. "
                    f"Valid values: {valid}"
                ),
            ))
            adapter_kind = NamespaceAdapterKind.STUB  # safe fallback

        # Mode-specific validation
        if runtime_mode == RuntimeMode.PRODUCTION:
            if adapter_kind == NamespaceAdapterKind.STUB:
                issues.append(RuntimeAdapterSelectionIssue(
                    code=ISSUE_STUB_ADAPTER_IN_PRODUCTION,
                    severity="blocking",
                    message=(
                        "StubNamespaceLifecycleAdapter must not be used in production mode. "
                        "Set LABGEN_NAMESPACE_ADAPTER=k8s and provide "
                        "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH."
                    ),
                ))
            elif adapter_kind == NamespaceAdapterKind.K8S and not k8s_kubeconfig_path:
                issues.append(RuntimeAdapterSelectionIssue(
                    code=ISSUE_K8S_ADAPTER_NOT_CONFIGURED,
                    severity="blocking",
                    message=(
                        "LABGEN_NAMESPACE_ADAPTER=k8s requires "
                        "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH to be set."
                    ),
                ))
        else:
            # Non-production: stub is allowed, but emit a warning
            if adapter_kind == NamespaceAdapterKind.STUB:
                issues.append(RuntimeAdapterSelectionIssue(
                    code=ISSUE_NON_PRODUCTION_STUB_ALLOWED,
                    severity="warning",
                    message=(
                        f"StubNamespaceLifecycleAdapter is active in {runtime_mode.value} mode. "
                        "No real K8s operations will occur. "
                        "This adapter must not be used in production."
                    ),
                ))

        # production_safe: true only when production + k8s + kubeconfig + no blocking issues
        blocking = [i for i in issues if i.severity == "blocking"]
        production_safe = (
            runtime_mode == RuntimeMode.PRODUCTION
            and adapter_kind == NamespaceAdapterKind.K8S
            and bool(k8s_kubeconfig_path)
            and len(blocking) == 0
        )

        return RuntimeAdapterSelectionResult(
            runtime_mode=runtime_mode,
            namespace_adapter_kind=adapter_kind,
            production_safe=production_safe,
            issues=issues,
        )

    @staticmethod
    def build_adapter(result: RuntimeAdapterSelectionResult) -> "NamespaceLifecyclePort":
        """Instantiate the selected adapter.

        Does NOT validate production safety — callers must check result.production_safe
        and handle accordingly (e.g. reject lab start if unsafe in production).
        Does NOT make network calls.
        Does NOT read kubeconfig files.
        """
        from backend.labgen.namespace_lifecycle import (
            K3sNamespaceLifecycleAdapter,
            StubNamespaceLifecycleAdapter,
        )
        if result.namespace_adapter_kind == NamespaceAdapterKind.K8S:
            return K3sNamespaceLifecycleAdapter()
        return StubNamespaceLifecycleAdapter()
