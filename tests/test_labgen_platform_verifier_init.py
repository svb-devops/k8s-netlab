"""Tests for PlatformVerifierInitializer in verifier_credentials.py
and initialize_verifier_for_vm_host_side in vm_manager.py.

All tests are static (no real K3s, no real Proxmox, no network).
K8s API calls are replaced via the injectable PlatformK8sApiFactory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.static

from backend.labgen.models import VerifierCredentialMetadata
import yaml

from backend.labgen.verifier_credentials import (
    PlatformK8sApiFactory,
    PlatformVerifierInitializer,
    VerifierCredentialStore,
    _CLUSTER_ROLE_MANIFEST,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_PLATFORM_KUBECONFIG = """\
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: dGVzdGNh
    server: https://k3s-staging.test:6443
  name: k3s-lab
contexts:
- context:
    cluster: k3s-lab
    user: default
  name: default@k3s-lab
current-context: default@k3s-lab
kind: Config
users:
- name: default
  user:
    token: platform-token-redacted
"""

_FAKE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.fakepayload.fakesig"


def _make_token_response(token: str = _FAKE_TOKEN) -> MagicMock:
    resp = MagicMock()
    resp.status = MagicMock()
    resp.status.token = token
    return resp


class _StubK8sApiFactory(PlatformK8sApiFactory):
    """Test double: returns mock CoreV1Api and RbacAuthorizationV1Api objects."""

    def __init__(
        self,
        token: str = _FAKE_TOKEN,
        sa_409: bool = False,
        role_delete_error: int = 0,   # delete_cluster_role returns this non-404 error
        role_create_error: int = 0,   # create_cluster_role returns this error
        sa_error: int = 0,
        token_error: int = 0,
        empty_token: bool = False,
    ) -> None:
        from kubernetes.client.exceptions import ApiException

        self.core = MagicMock()
        self.rbac = MagicMock()

        if sa_error:
            self.core.create_namespaced_service_account.side_effect = ApiException(
                status=sa_error, reason="Error"
            )
        elif sa_409:
            self.core.create_namespaced_service_account.side_effect = ApiException(
                status=409, reason="AlreadyExists"
            )

        # delete+create pattern: delete_cluster_role is always called first (404 → ignored),
        # then create_cluster_role is called. replace_cluster_role must NEVER be called
        # (K3s v1.34.4 RBAC informer cache bug: PUT breaks authorization evaluator).
        if role_delete_error:
            self.rbac.delete_cluster_role.side_effect = ApiException(
                status=role_delete_error, reason="Error"
            )
        if role_create_error:
            self.rbac.create_cluster_role.side_effect = ApiException(
                status=role_create_error, reason="Error"
            )

        if token_error:
            self.core.create_namespaced_service_account_token.side_effect = ApiException(
                status=token_error, reason="Error"
            )
        elif empty_token:
            empty_resp = MagicMock()
            empty_resp.status.token = ""
            self.core.create_namespaced_service_account_token.return_value = empty_resp
        else:
            self.core.create_namespaced_service_account_token.return_value = (
                _make_token_response(token)
            )

    def build(self, kubeconfig_content: str) -> tuple[Any, Any]:
        return self.core, self.rbac


@pytest.fixture()
def store(tmp_path: Path) -> VerifierCredentialStore:
    return VerifierCredentialStore(base_dir=tmp_path / "creds")


# ---------------------------------------------------------------------------
# PlatformVerifierInitializer.ensure_verifier_identity
# ---------------------------------------------------------------------------


class TestPlatformVerifierInitializerEnsureIdentity:
    def _make(
        self, store: VerifierCredentialStore, **factory_kwargs: Any
    ) -> tuple[PlatformVerifierInitializer, _StubK8sApiFactory]:
        factory = _StubK8sApiFactory(**factory_kwargs)
        return PlatformVerifierInitializer(store=store, factory=factory), factory

    def test_credentials_stored_after_success(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        assert store.exists("401")

    def test_server_extracted_from_kubeconfig(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        _, meta = store.load("401")
        assert meta.k3s_endpoint == "https://k3s-staging.test:6443"

    def test_credential_generation_starts_at_one(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        _, meta = store.load("401")
        assert meta.credential_generation == 1

    def test_credential_generation_increments_on_rerun(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        _, meta = store.load("401")
        assert meta.credential_generation == 2

    def test_kubeconfig_contains_token(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        kubeconfig_content, _ = store.load("401")
        assert "token:" in kubeconfig_content

    def test_kubeconfig_contains_server_url(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        kubeconfig_content, _ = store.load("401")
        assert "k3s-staging.test:6443" in kubeconfig_content

    def test_kubeconfig_contains_ca_data(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        kubeconfig_content, _ = store.load("401")
        assert "dGVzdGNh" in kubeconfig_content

    def test_vm_id_validated_numeric(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        with pytest.raises(ValueError, match="numeric"):
            init.ensure_verifier_identity("../../etc/passwd", _PLATFORM_KUBECONFIG)

    def test_sa_409_is_idempotent(self, store: VerifierCredentialStore) -> None:
        """409 AlreadyExists on SA create must not raise — idempotent apply."""
        init, _ = self._make(store, sa_409=True)
        meta = init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        assert meta.credential_generation == 1
        assert store.exists("401")

    def test_cluster_role_uses_delete_then_create(self, store: VerifierCredentialStore) -> None:
        """delete+create is used (not replace) — idempotent and avoids K3s RBAC cache bug."""
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        factory.rbac.delete_cluster_role.assert_called_once()
        factory.rbac.create_cluster_role.assert_called_once()
        factory.rbac.replace_cluster_role.assert_not_called()
        assert store.exists("401")

    def test_sa_non_409_raises_runtime_error(self, store: VerifierCredentialStore) -> None:
        """Non-409 K8s errors propagate as RuntimeError."""
        init, _ = self._make(store, sa_error=500)
        with pytest.raises(RuntimeError, match="ServiceAccount"):
            init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)

    def test_cluster_role_delete_non404_error_raises_runtime_error(self, store: VerifierCredentialStore) -> None:
        """Non-404 errors from delete_cluster_role propagate as RuntimeError."""
        init, _ = self._make(store, role_delete_error=403)
        with pytest.raises(RuntimeError, match="ClusterRole"):
            init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)

    def test_cluster_role_delete_404_is_silently_ignored(self, store: VerifierCredentialStore) -> None:
        """delete_cluster_role 404 is silently ignored — CR didn't exist yet, create proceeds."""
        from kubernetes.client.exceptions import ApiException

        init, factory = self._make(store)
        factory.rbac.delete_cluster_role.side_effect = ApiException(status=404, reason="NotFound")
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        factory.rbac.delete_cluster_role.assert_called_once()
        factory.rbac.create_cluster_role.assert_called_once()
        assert store.exists("401")

    def test_cluster_role_create_error_raises_runtime_error(self, store: VerifierCredentialStore) -> None:
        """Errors from create_cluster_role propagate as RuntimeError."""
        init, _ = self._make(store, role_create_error=500)
        with pytest.raises(RuntimeError, match="ClusterRole"):
            init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)

    def test_token_api_error_raises_runtime_error(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store, token_error=503)
        with pytest.raises(RuntimeError, match="token"):
            init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)

    def test_empty_token_raises_runtime_error(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store, empty_token=True)
        with pytest.raises(RuntimeError, match="empty token"):
            init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)

    def test_cluster_role_includes_secrets_resource(self, store: VerifierCredentialStore) -> None:
        # secret_exists verifier requires list permission on secrets.
        # Regression: ClusterRole was missing secrets — caused 403 on secret_exists check.
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        factory.rbac.create_cluster_role.assert_called_once()
        cr_arg = factory.rbac.create_cluster_role.call_args[0][0]
        all_resources = [r for rule in cr_arg.rules for r in (rule.resources or [])]
        assert "secrets" in all_resources

    def test_cluster_role_secrets_has_no_get_verb(self, store: VerifierCredentialStore) -> None:
        # Principle of least privilege: secret_exists uses list_namespaced_secret only.
        # The secrets rule must not grant get (which would allow reading .data).
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        cr_arg = factory.rbac.create_cluster_role.call_args[0][0]
        secrets_rule = next(
            (r for r in cr_arg.rules if "secrets" in (r.resources or [])), None
        )
        assert secrets_rule is not None
        assert "get" not in (secrets_rule.verbs or [])

    def test_cluster_role_includes_deployments_resource(self, store: VerifierCredentialStore) -> None:
        # deployment_ready verifier requires list permission on apps/deployments.
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        cr_arg = factory.rbac.create_cluster_role.call_args[0][0]
        apps_rule = next(
            (r for r in cr_arg.rules if "apps" in (r.api_groups or [])), None
        )
        assert apps_rule is not None
        assert "deployments" in (apps_rule.resources or [])

    def test_cluster_role_deployments_has_no_get_verb(self, store: VerifierCredentialStore) -> None:
        # deployment_ready uses list_namespaced_deployment, not read_namespaced_deployment.
        # apps/deployments rule must not grant get — list is sufficient and reduces blast radius.
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        cr_arg = factory.rbac.create_cluster_role.call_args[0][0]
        apps_rule = next(
            (r for r in cr_arg.rules if "apps" in (r.api_groups or [])), None
        )
        assert apps_rule is not None
        assert "get" not in (apps_rule.verbs or [])

    def test_cluster_role_no_get_verb_on_core_resources(self, store: VerifierCredentialStore) -> None:
        # All verifier methods use list+field_selector; 'get' is not needed anywhere.
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        cr_arg = factory.rbac.create_cluster_role.call_args[0][0]
        for rule in cr_arg.rules:
            assert "get" not in (rule.verbs or []), (
                f"ClusterRole rule grants 'get' on {rule.resources}: "
                "verifier uses list+field_selector only"
            )

    def test_cluster_role_no_namespaces_resource(self, store: VerifierCredentialStore) -> None:
        # namespace_exists uses list_namespaced_config_map; namespaces cluster-resource unneeded.
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        cr_arg = factory.rbac.create_cluster_role.call_args[0][0]
        all_resources = [r for rule in cr_arg.rules for r in (rule.resources or [])]
        assert "namespaces" not in all_resources

    def test_cluster_role_no_endpoints_resource(self, store: VerifierCredentialStore) -> None:
        # endpoints is not used by any verifier method.
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        cr_arg = factory.rbac.create_cluster_role.call_args[0][0]
        all_resources = [r for rule in cr_arg.rules for r in (rule.resources or [])]
        assert "endpoints" not in all_resources

    def test_sa_create_called_with_kube_system(self, store: VerifierCredentialStore) -> None:
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        factory.core.create_namespaced_service_account.assert_called_once()
        call_args = factory.core.create_namespaced_service_account.call_args
        assert call_args[0][0] == "kube-system"

    def test_token_request_called_for_lab_verifier(self, store: VerifierCredentialStore) -> None:
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        factory.core.create_namespaced_service_account_token.assert_called_once()
        call_args = factory.core.create_namespaced_service_account_token.call_args
        assert call_args[0][0] == "lab-verifier"
        assert call_args[0][1] == "kube-system"

    def test_metadata_schema_version_is_one(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        _, meta = store.load("401")
        assert meta.schema_version == "1.0"

    def test_metadata_vm_id_matches(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("425", _PLATFORM_KUBECONFIG)
        assert store.exists("425")
        _, meta = store.load("425")
        assert meta.vm_id == "425"

    def test_different_vm_ids_isolated(self, store: VerifierCredentialStore) -> None:
        init, _ = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        init.ensure_verifier_identity("402", _PLATFORM_KUBECONFIG)
        assert store.exists("401")
        assert store.exists("402")

    def test_replace_cluster_role_never_called(self, store: VerifierCredentialStore) -> None:
        # Regression: K3s v1.34.4 replace_cluster_role (PUT) breaks the RBAC authorization
        # evaluator cache — SA tokens receive 403 Forbidden after reprovision even when the
        # ClusterRole is correctly indexed.  delete+create emits clean DELETE+ADD informer
        # events that the RBAC evaluator processes correctly.
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        factory.rbac.replace_cluster_role.assert_not_called()

    def test_sdk_object_matches_manifest_string(self, store: VerifierCredentialStore) -> None:
        # Cross-path parity: the V1ClusterRole SDK object passed to create_cluster_role
        # must encode the same resource+verb sets as _CLUSTER_ROLE_MANIFEST.
        # Prevents the two apply paths from silently diverging on future edits.
        init, factory = self._make(store)
        init.ensure_verifier_identity("401", _PLATFORM_KUBECONFIG)
        cr_sdk = factory.rbac.create_cluster_role.call_args[0][0]

        manifest_doc = yaml.safe_load(_CLUSTER_ROLE_MANIFEST)
        manifest_rules = manifest_doc.get("rules", [])

        # Build canonical (frozenset-of-frozensets) representation for each path
        def rules_signature(rules_iter) -> frozenset:
            result = set()
            for rule in rules_iter:
                if hasattr(rule, "api_groups"):
                    groups = frozenset(rule.api_groups or [])
                    resources = frozenset(rule.resources or [])
                    verbs = frozenset(rule.verbs or [])
                else:
                    groups = frozenset(rule.get("apiGroups", []))
                    resources = frozenset(rule.get("resources", []))
                    verbs = frozenset(rule.get("verbs", []))
                result.add((groups, resources, verbs))
            return frozenset(result)

        sdk_sig = rules_signature(cr_sdk.rules)
        manifest_sig = rules_signature(manifest_rules)
        assert sdk_sig == manifest_sig, (
            "V1ClusterRole SDK object and _CLUSTER_ROLE_MANIFEST YAML diverged — "
            "both paths must encode identical apiGroups/resources/verbs sets"
        )


# ---------------------------------------------------------------------------
# initialize_verifier_for_vm_host_side (vm_manager.py)
# ---------------------------------------------------------------------------


class TestInitializeVerifierHostSide:
    def _make_kubeconfig_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "home_lab_mvp.kubeconfig"
        p.write_text(_PLATFORM_KUBECONFIG)
        return p

    def _call(
        self,
        tmp_path: Path,
        vm_id: int = 401,
        factory_kwargs: dict | None = None,
    ) -> dict:
        kc_path = self._make_kubeconfig_file(tmp_path)
        store = VerifierCredentialStore(base_dir=tmp_path / "creds")
        factory = _StubK8sApiFactory(**(factory_kwargs or {}))

        from backend.vm_manager import initialize_verifier_for_vm_host_side
        return initialize_verifier_for_vm_host_side(
            vm_id,
            str(kc_path),
            store=store,
            _factory=factory,
        )

    def test_success_returns_success_true(self, tmp_path: Path) -> None:
        result = self._call(tmp_path)
        assert result["success"] is True
        assert result["error"] is None

    def test_success_data_has_vm_id(self, tmp_path: Path) -> None:
        result = self._call(tmp_path, vm_id=401)
        assert result["data"]["vm_id"] == 401

    def test_success_data_redacts_k3s_endpoint(self, tmp_path: Path) -> None:
        result = self._call(tmp_path)
        assert result["data"]["k3s_endpoint"] == "<redacted>"

    def test_success_data_smoke_passed(self, tmp_path: Path) -> None:
        result = self._call(tmp_path)
        assert result["data"]["smoke_passed"] is True

    def test_staging_vmid_accepted(self, tmp_path: Path) -> None:
        result = self._call(tmp_path, vm_id=400)
        assert result["success"] is True

    def test_invalid_vm_id_too_low_raises_value_error(self, tmp_path: Path) -> None:
        kc_path = self._make_kubeconfig_file(tmp_path)
        store = VerifierCredentialStore(base_dir=tmp_path / "creds")
        from backend.vm_manager import initialize_verifier_for_vm_host_side
        with pytest.raises(ValueError, match="Invalid VM ID"):
            initialize_verifier_for_vm_host_side(99, str(kc_path), store=store)

    def test_missing_kubeconfig_returns_failure(self, tmp_path: Path) -> None:
        store = VerifierCredentialStore(base_dir=tmp_path / "creds")
        from backend.vm_manager import initialize_verifier_for_vm_host_side
        result = initialize_verifier_for_vm_host_side(
            401,
            str(tmp_path / "does_not_exist.kubeconfig"),
            store=store,
        )
        assert result["success"] is False
        assert "kubeconfig read failed" in result["error"]

    def test_k8s_error_returns_failure(self, tmp_path: Path) -> None:
        result = self._call(tmp_path, factory_kwargs={"sa_error": 500})
        assert result["success"] is False
        assert result["error"] is not None

    def test_credential_stored_on_success(self, tmp_path: Path) -> None:
        kc_path = self._make_kubeconfig_file(tmp_path)
        store = VerifierCredentialStore(base_dir=tmp_path / "creds")
        factory = _StubK8sApiFactory()

        from backend.vm_manager import initialize_verifier_for_vm_host_side
        initialize_verifier_for_vm_host_side(401, str(kc_path), store=store, _factory=factory)
        assert store.exists("401")
