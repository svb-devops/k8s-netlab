"""
RuntimeAdapterSelectionService — unit tests.

Tests cover:
A. Selection logic
   - test mode + stub → production_safe=False, NON_PRODUCTION_STUB_ALLOWED warning
   - dev mode + stub → allowed with warning
   - demo mode + stub → allowed with warning
   - production + stub → STUB_ADAPTER_IN_PRODUCTION blocking, production_safe=False
   - production + k8s + no kubeconfig → K8S_ADAPTER_NOT_CONFIGURED blocking
   - production + k8s + kubeconfig set → production_safe=True
   - invalid runtime_mode → INVALID_RUNTIME_MODE blocking
   - invalid adapter_kind → INVALID_ADAPTER_KIND blocking

B. build_adapter()
   - stub mode → StubNamespaceLifecycleAdapter instance
   - k8s mode → K3sNamespaceLifecycleAdapter instance

C. Issue severity classification
   - blocking issues are identified correctly
   - warning issues are identified correctly
   - non-production stub: warning only (no blocking)

D. create_from_config() integration
   - reads from config module

E. Regression
   - existing tests unaffected by new config vars (default dev mode)
"""

from __future__ import annotations

import pytest

from backend.labgen.runtime_adapter_selection import (
    ISSUE_INVALID_ADAPTER_KIND,
    ISSUE_INVALID_RUNTIME_MODE,
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

def _select(runtime_mode, adapter_kind, kubeconfig="", in_cluster=False):
    return RuntimeAdapterSelectionService.select(
        runtime_mode_raw=runtime_mode,
        adapter_kind_raw=adapter_kind,
        k8s_kubeconfig_path=kubeconfig,
        k8s_in_cluster=in_cluster,
    )


def _codes(result):
    return {i.code for i in result.issues}


def _blocking(result):
    return [i for i in result.issues if i.severity == "blocking"]


def _warnings(result):
    return [i for i in result.issues if i.severity == "warning"]


# ---------------------------------------------------------------------------
# A. Selection logic
# ---------------------------------------------------------------------------

class TestSelectionLogic:
    def test_test_mode_stub_not_production_safe(self):
        r = _select("test", "stub")
        assert r.runtime_mode == RuntimeMode.TEST
        assert r.namespace_adapter_kind == NamespaceAdapterKind.STUB
        assert r.production_safe is False

    def test_test_mode_stub_warning_not_blocking(self):
        r = _select("test", "stub")
        assert ISSUE_NON_PRODUCTION_STUB_ALLOWED in _codes(r)
        assert len(_blocking(r)) == 0
        assert len(_warnings(r)) == 1

    def test_dev_mode_stub_allowed_with_warning(self):
        r = _select("dev", "stub")
        assert r.production_safe is False
        assert ISSUE_NON_PRODUCTION_STUB_ALLOWED in _codes(r)
        assert len(_blocking(r)) == 0

    def test_demo_mode_stub_allowed_with_warning(self):
        r = _select("demo", "stub")
        assert r.production_safe is False
        assert ISSUE_NON_PRODUCTION_STUB_ALLOWED in _codes(r)
        assert len(_blocking(r)) == 0

    def test_production_stub_blocking(self):
        r = _select("production", "stub")
        assert ISSUE_STUB_ADAPTER_IN_PRODUCTION in _codes(r)
        assert len(_blocking(r)) == 1
        assert r.production_safe is False

    def test_production_k8s_missing_kubeconfig_blocking(self):
        r = _select("production", "k8s", kubeconfig="")
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in _codes(r)
        assert len(_blocking(r)) == 1
        assert r.production_safe is False

    def test_production_k8s_kubeconfig_set_production_safe(self):
        r = _select("production", "k8s", kubeconfig="/etc/k8s/platform.yaml")
        assert r.production_safe is True
        assert len(_blocking(r)) == 0
        # No issues at all for the happy path
        assert len(r.issues) == 0

    def test_invalid_runtime_mode_blocking(self):
        r = _select("garbage", "stub")
        assert ISSUE_INVALID_RUNTIME_MODE in _codes(r)
        assert len(_blocking(r)) >= 1

    def test_invalid_adapter_kind_blocking(self):
        r = _select("dev", "notanadapter")
        assert ISSUE_INVALID_ADAPTER_KIND in _codes(r)
        assert len(_blocking(r)) >= 1

    def test_invalid_mode_and_kind_both_blocking(self):
        r = _select("garbage", "notanadapter")
        assert ISSUE_INVALID_RUNTIME_MODE in _codes(r)
        assert ISSUE_INVALID_ADAPTER_KIND in _codes(r)
        assert len(_blocking(r)) == 2

    def test_result_has_checked_at(self):
        r = _select("dev", "stub")
        assert r.checked_at
        assert "T" in r.checked_at  # ISO format

    def test_runtime_mode_field(self):
        r = _select("dev", "stub")
        assert r.runtime_mode == RuntimeMode.DEV

    def test_adapter_kind_field(self):
        r = _select("dev", "stub")
        assert r.namespace_adapter_kind == NamespaceAdapterKind.STUB

    # Codex P1 regression: mutually exclusive K8s config must always block
    def test_kubeconfig_and_in_cluster_both_set_is_blocking(self):
        r = _select("home_lab_mvp", "k8s", kubeconfig="/etc/k8s/platform.yaml", in_cluster=True)
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in _codes(r)
        assert len(_blocking(r)) >= 1
        assert r.production_safe is False

    def test_kubeconfig_and_in_cluster_cloud_mode_is_blocking(self):
        r = _select("cloud", "k8s", kubeconfig="/etc/k8s/eks.yaml", in_cluster=True)
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in _codes(r)
        assert len(_blocking(r)) >= 1
        assert r.production_safe is False

    def test_kubeconfig_and_in_cluster_production_mode_is_blocking(self):
        r = _select("production", "k8s", kubeconfig="/etc/k8s/platform.yaml", in_cluster=True)
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in _codes(r)
        assert len(_blocking(r)) >= 1
        assert r.production_safe is False

    def test_kubeconfig_only_in_cloud_is_production_safe(self):
        r = _select("cloud", "k8s", kubeconfig="/etc/k8s/eks.yaml", in_cluster=False)
        assert r.production_safe is True
        assert len(_blocking(r)) == 0

    def test_in_cluster_only_in_cloud_is_production_safe(self):
        r = _select("cloud", "k8s", kubeconfig="", in_cluster=True)
        assert r.production_safe is True
        assert len(_blocking(r)) == 0

    def test_neither_kubeconfig_nor_in_cluster_in_cloud_is_blocking(self):
        r = _select("cloud", "k8s", kubeconfig="", in_cluster=False)
        assert ISSUE_K8S_ADAPTER_NOT_CONFIGURED in _codes(r)
        assert r.production_safe is False

    def test_mutual_exclusion_check_message_is_descriptive(self):
        r = _select("home_lab_mvp", "k8s", kubeconfig="/etc/k8s/platform.yaml", in_cluster=True)
        blocking = _blocking(r)
        assert any("mutually exclusive" in i.message.lower() for i in blocking)


# ---------------------------------------------------------------------------
# B. build_adapter()
# ---------------------------------------------------------------------------

def _k8s_adapter_config(kubeconfig: str = "/etc/k8s/platform.yaml"):
    from backend.labgen.namespace_lifecycle import K8sAdapterConfig
    return K8sAdapterConfig(
        kubeconfig_path=kubeconfig,
        allowed_namespace_prefixes=["lab-"],
    )


class TestBuildAdapter:
    def test_stub_mode_returns_stub_adapter(self):
        from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
        r = _select("dev", "stub")
        adapter = RuntimeAdapterSelectionService.build_adapter(r)
        assert isinstance(adapter, StubNamespaceLifecycleAdapter)

    def test_k8s_mode_returns_k3s_adapter(self):
        from backend.labgen.namespace_lifecycle import K3sNamespaceLifecycleAdapter
        r = _select("production", "k8s", kubeconfig="/etc/k8s/platform.yaml")
        adapter = RuntimeAdapterSelectionService.build_adapter(r, adapter_config=_k8s_adapter_config())
        assert isinstance(adapter, K3sNamespaceLifecycleAdapter)

    def test_production_stub_builds_stub_not_raises(self):
        # build_adapter() always succeeds — safety guard is in create_session()
        from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
        r = _select("production", "stub")
        adapter = RuntimeAdapterSelectionService.build_adapter(r)
        assert isinstance(adapter, StubNamespaceLifecycleAdapter)

    def test_home_lab_mvp_k8s_returns_k3s_adapter(self):
        from backend.labgen.namespace_lifecycle import K3sNamespaceLifecycleAdapter
        r = _select("home_lab_mvp", "k8s", kubeconfig="/etc/k8s/platform.yaml")
        adapter = RuntimeAdapterSelectionService.build_adapter(r, adapter_config=_k8s_adapter_config())
        assert isinstance(adapter, K3sNamespaceLifecycleAdapter)

    def test_cloud_k8s_returns_k3s_adapter(self):
        from backend.labgen.namespace_lifecycle import K3sNamespaceLifecycleAdapter
        r = _select("cloud", "k8s", kubeconfig="/etc/k8s/eks.yaml")
        adapter = RuntimeAdapterSelectionService.build_adapter(
            r, adapter_config=_k8s_adapter_config("/etc/k8s/eks.yaml")
        )
        assert isinstance(adapter, K3sNamespaceLifecycleAdapter)


# ---------------------------------------------------------------------------
# C. Issue severity classification
# ---------------------------------------------------------------------------

class TestIssueSeverity:
    def test_stub_in_production_is_blocking(self):
        r = _select("production", "stub")
        issue = next(i for i in r.issues if i.code == ISSUE_STUB_ADAPTER_IN_PRODUCTION)
        assert issue.severity == "blocking"

    def test_k8s_not_configured_is_blocking(self):
        r = _select("production", "k8s")
        issue = next(i for i in r.issues if i.code == ISSUE_K8S_ADAPTER_NOT_CONFIGURED)
        assert issue.severity == "blocking"

    def test_invalid_mode_is_blocking(self):
        r = _select("bad_mode", "stub")
        issue = next(i for i in r.issues if i.code == ISSUE_INVALID_RUNTIME_MODE)
        assert issue.severity == "blocking"

    def test_non_production_stub_is_warning(self):
        r = _select("dev", "stub")
        issue = next(i for i in r.issues if i.code == ISSUE_NON_PRODUCTION_STUB_ALLOWED)
        assert issue.severity == "warning"

    def test_issue_messages_contain_no_credential_values(self):
        # Messages must not contain raw env var values, tokens, or kubeconfig content
        for mode in ["test", "dev", "demo"]:
            r = _select(mode, "stub")
            for issue in r.issues:
                assert "eyJ" not in issue.message  # JWT token prefix
                assert "-----BEGIN" not in issue.message  # PEM header


# ---------------------------------------------------------------------------
# D. create_from_config() integration
# ---------------------------------------------------------------------------

class TestCreateFromConfig:
    def test_create_from_config_returns_result(self):
        r = RuntimeAdapterSelectionService.create_from_config()
        # Default config: LABGEN_RUNTIME_MODE=dev, LABGEN_NAMESPACE_ADAPTER=stub
        assert r.runtime_mode in list(RuntimeMode)
        assert r.namespace_adapter_kind in (NamespaceAdapterKind.STUB, NamespaceAdapterKind.K8S)
        assert isinstance(r.production_safe, bool)
        assert r.checked_at

    def test_create_from_config_default_is_dev_stub(self, monkeypatch):
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "LABGEN_RUNTIME_MODE", "dev")
        monkeypatch.setattr(_cfg, "LABGEN_NAMESPACE_ADAPTER", "stub")
        monkeypatch.setattr(_cfg, "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "")
        monkeypatch.setattr(_cfg, "LABGEN_K8S_IN_CLUSTER", False)
        r = RuntimeAdapterSelectionService.create_from_config()
        assert r.runtime_mode == RuntimeMode.DEV
        assert r.namespace_adapter_kind == NamespaceAdapterKind.STUB
        assert r.production_safe is False


# ---------------------------------------------------------------------------
# E. Production guard integration (via LabSessionService)
# ---------------------------------------------------------------------------

class TestProductionGuardInLabSessionService:
    """Verify that LabSessionService rejects create_session() in production unsafe config."""

    def _build_svc(self, selection_result, *, draft_repo=None, session_repo=None):
        from unittest.mock import MagicMock
        from backend.labgen.lab_session_service import LabSessionService, StubVMTracker
        from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
        from backend.labgen.image_resolver import ImageResolver

        if session_repo is None:
            session_repo = MagicMock()
            # create() returns the session passed to it
            session_repo.create.side_effect = lambda s: s

        if draft_repo is None:
            draft_repo = MagicMock()

        return LabSessionService(
            session_repo=session_repo,
            draft_repo=draft_repo,
            vm_tracker=StubVMTracker(),
            ns_lifecycle=StubNamespaceLifecycleAdapter(),
            image_resolver=ImageResolver(),
            adapter_selection=selection_result,
        )

    def test_production_unsafe_rejects_start(self):
        from backend.labgen.models import LabSessionStatus
        from backend.labgen.failure_reasons import FailureReason

        selection = _select("production", "stub")  # production_safe=False
        svc = self._build_svc(selection)
        result = svc.create_session("lab-1", "vm-1", "student")

        assert result.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert result.failure_reason == FailureReason.ADAPTER_UNSAFE_IN_PRODUCTION.value

    def test_production_unsafe_does_not_call_precheck(self):
        from unittest.mock import patch, MagicMock
        from backend.labgen.models import LabSessionStatus

        selection = _select("production", "stub")
        svc = self._build_svc(selection)

        with patch.object(svc, 'run_precheck') as mock_precheck:
            svc.create_session("lab-1", "vm-1", "student")
            mock_precheck.assert_not_called()

    def test_production_unsafe_does_not_create_namespace(self):
        from unittest.mock import MagicMock, patch
        from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter

        selection = _select("production", "stub")
        ns = StubNamespaceLifecycleAdapter()
        svc = self._build_svc(selection)
        svc._ns_lifecycle = ns

        svc.create_session("lab-1", "vm-1", "student")
        assert ns.created == []  # no namespace created

    def test_production_unsafe_does_not_create_rolebinding(self):
        from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter

        selection = _select("production", "stub")
        ns = StubNamespaceLifecycleAdapter()
        svc = self._build_svc(selection)
        svc._ns_lifecycle = ns

        svc.create_session("lab-1", "vm-1", "student")
        assert ns.rolebindings_created == []  # no rolebinding created

    def test_production_unsafe_emits_lab_start_failed_audit(self):
        from unittest.mock import MagicMock
        from backend.labgen.models import RuntimeAuditEventType

        selection = _select("production", "stub")
        audit_svc = MagicMock()
        svc = self._build_svc(selection)
        svc._audit_svc = audit_svc

        svc.create_session("lab-1", "vm-1", "student")
        audit_svc.record.assert_called_once()
        # _audit calls record(session_id, event_type, ...) — event_type is 2nd positional arg
        call_args = audit_svc.record.call_args
        assert call_args.args[1] == RuntimeAuditEventType.LAB_START_FAILED

    def test_invalid_runtime_mode_rejects_start(self):
        """INVALID_RUNTIME_MODE (blocking) must also reject start, even though the fallback
        runtime_mode is DEV (not PRODUCTION).  This is the codex P1 fix — the guard must
        check ANY blocking issue, not only production mode."""
        from backend.labgen.models import LabSessionStatus
        from backend.labgen.failure_reasons import FailureReason
        from unittest.mock import patch

        selection = _select("garbage", "stub")  # INVALID_RUNTIME_MODE, fallback to DEV
        assert any(i.severity == "blocking" for i in selection.issues)

        svc = self._build_svc(selection)

        with patch.object(svc, 'run_precheck') as mock_precheck:
            result = svc.create_session("lab-1", "vm-1", "student")
            mock_precheck.assert_not_called()

        assert result.lab_session_status == LabSessionStatus.LAB_START_FAILED
        assert result.failure_reason == FailureReason.ADAPTER_UNSAFE_IN_PRODUCTION.value

    def test_invalid_adapter_kind_rejects_start(self):
        """INVALID_ADAPTER_KIND (blocking) must reject start."""
        from backend.labgen.models import LabSessionStatus
        from unittest.mock import patch

        selection = _select("dev", "notanadapter")
        assert any(i.severity == "blocking" for i in selection.issues)

        svc = self._build_svc(selection)
        with patch.object(svc, 'run_precheck') as mock_precheck:
            result = svc.create_session("lab-1", "vm-1", "student")
            mock_precheck.assert_not_called()

        assert result.lab_session_status == LabSessionStatus.LAB_START_FAILED

    def test_dev_stub_does_not_block_start(self):
        """dev mode with stub adapter has only a warning (not blocking) → guard must not fire."""
        from unittest.mock import MagicMock, patch

        selection = _select("dev", "stub")
        assert not any(i.severity == "blocking" for i in selection.issues)  # sanity
        svc = self._build_svc(selection)

        with patch.object(svc, 'run_precheck') as mock_precheck:
            # Precheck raises to halt before real logic (we just want to confirm it was called)
            mock_precheck.side_effect = Exception("precheck called")
            with pytest.raises(Exception, match="precheck called"):
                svc.create_session("lab-1", "vm-1", "student")

        mock_precheck.assert_called_once()

    def test_no_adapter_selection_does_not_block_start(self):
        """adapter_selection=None (legacy / test construction) must not block."""
        from unittest.mock import MagicMock, patch

        svc = self._build_svc(None)

        with patch.object(svc, 'run_precheck') as mock_precheck:
            mock_precheck.side_effect = Exception("precheck called")
            with pytest.raises(Exception, match="precheck called"):
                svc.create_session("lab-1", "vm-1", "student")

        mock_precheck.assert_called_once()

    def test_production_safe_k8s_does_not_block_start(self):
        """production mode + k8s + kubeconfig set → production_safe=True → guard doesn't fire."""
        from unittest.mock import MagicMock, patch

        selection = _select("production", "k8s", kubeconfig="/etc/k8s/platform.yaml")
        assert selection.production_safe is True

        svc = self._build_svc(selection)

        with patch.object(svc, 'run_precheck') as mock_precheck:
            mock_precheck.side_effect = Exception("precheck called")
            with pytest.raises(Exception, match="precheck called"):
                svc.create_session("lab-1", "vm-1", "student")

        mock_precheck.assert_called_once()
