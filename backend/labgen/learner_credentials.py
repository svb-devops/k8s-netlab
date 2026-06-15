"""
Per-session learner kubectl credentials.

Creates a namespace-scoped ServiceAccount, Role, and RoleBinding for each
active lab session.  The session-scoped kubeconfig is stored server-side
only — never sent to the client or logged.

File layout:
  /var/lib/labgen-staging/learner-kubeconfigs/{session_id}/config  (chmod 600)

RBAC granted to the learner SA (namespace-scoped only):
  - configmaps:   create / get / list / watch / delete / update / patch
  - secrets:      create / get / list / watch / delete
  - pods:         get / list / watch  (controller creates them; learner only reads)
  - events:       get / list / watch
  - deployments:  create / get / list / watch / delete / update / patch
  - replicasets:  get / list / watch

Security constraints:
  - Kubeconfig content MUST NOT appear in log output.
  - session_id must match ^[0-9a-f-]{36}$ (UUID) to prevent path traversal.
  - All K8s calls use an ApiClient built from the platform kubeconfig content;
    global k8s_config is never mutated (thread-safe for concurrent sessions).
  - Token expiry: 3600 seconds (1 hour).
  - Credentials are reclaimed on session close/abort; residual cleanup is the
    operator's responsibility if the server crashes mid-session.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

import yaml
from kubernetes import client as k8s_client
from kubernetes.client.exceptions import ApiException
from kubernetes.config.kube_config import KubeConfigLoader

logger = logging.getLogger(__name__)

_CRED_BASE_DIR = Path("/var/lib/labgen-staging/learner-kubeconfigs")
_SA_NAME = "lab-learner"
_ROLE_NAME = "lab-learner-role"
_RB_NAME = "lab-learner-rolebinding"
_TOKEN_EXPIRY_SECONDS = 3600

# Validate session_id is a UUID (36 chars: 8-4-4-4-12 hex + dashes).
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"Invalid session_id {session_id!r}: must be UUID format")


def _build_api_client(platform_kubeconfig_path: str) -> k8s_client.ApiClient:
    """Build an ApiClient from the platform kubeconfig file (does not mutate global state)."""
    with open(platform_kubeconfig_path) as f:
        config_dict = yaml.safe_load(f)
    cfg = k8s_client.Configuration()
    loader = KubeConfigLoader(config_dict=config_dict)
    loader.load_and_set(cfg)
    return k8s_client.ApiClient(configuration=cfg)


def _ensure_sa(core_v1: k8s_client.CoreV1Api, namespace: str) -> None:
    sa = k8s_client.V1ServiceAccount(
        metadata=k8s_client.V1ObjectMeta(name=_SA_NAME, namespace=namespace)
    )
    try:
        core_v1.create_namespaced_service_account(namespace, sa)
        logger.debug("Created learner SA %s in %s", _SA_NAME, namespace)
    except ApiException as exc:
        if exc.status != 409:  # 409 = AlreadyExists — idempotent
            raise


def _ensure_role(rbac_v1: k8s_client.RbacAuthorizationV1Api, namespace: str) -> None:
    role = k8s_client.V1Role(
        metadata=k8s_client.V1ObjectMeta(name=_ROLE_NAME, namespace=namespace),
        rules=[
            k8s_client.V1PolicyRule(
                api_groups=[""],
                resources=["configmaps"],
                verbs=["create", "get", "list", "watch", "delete", "update", "patch"],
            ),
            k8s_client.V1PolicyRule(
                api_groups=[""],
                resources=["secrets"],
                verbs=["create", "get", "list", "watch", "delete"],
            ),
            k8s_client.V1PolicyRule(
                api_groups=[""],
                resources=["pods", "events"],
                verbs=["get", "list", "watch"],
            ),
            k8s_client.V1PolicyRule(
                api_groups=["apps"],
                resources=["deployments"],
                verbs=["create", "get", "list", "watch", "delete", "update", "patch"],
            ),
            k8s_client.V1PolicyRule(
                api_groups=["apps"],
                resources=["replicasets"],
                verbs=["get", "list", "watch"],
            ),
        ],
    )
    try:
        rbac_v1.create_namespaced_role(namespace, role)
        logger.debug("Created learner Role %s in %s", _ROLE_NAME, namespace)
    except ApiException as exc:
        if exc.status != 409:
            raise


def _ensure_rolebinding(rbac_v1: k8s_client.RbacAuthorizationV1Api, namespace: str) -> None:
    rb = k8s_client.V1RoleBinding(
        metadata=k8s_client.V1ObjectMeta(name=_RB_NAME, namespace=namespace),
        role_ref=k8s_client.V1RoleRef(
            api_group="rbac.authorization.k8s.io",
            kind="Role",
            name=_ROLE_NAME,
        ),
        subjects=[
            k8s_client.RbacV1Subject(
                kind="ServiceAccount",
                name=_SA_NAME,
                namespace=namespace,
            )
        ],
    )
    try:
        rbac_v1.create_namespaced_role_binding(namespace, rb)
        logger.debug("Created learner RoleBinding %s in %s", _RB_NAME, namespace)
    except ApiException as exc:
        if exc.status != 409:
            raise


def _create_sa_token(core_v1: k8s_client.CoreV1Api, namespace: str) -> str:
    """Create a short-lived token for the learner SA."""
    token_request = k8s_client.AuthenticationV1TokenRequest(
        spec=k8s_client.V1TokenRequestSpec(
            expiration_seconds=_TOKEN_EXPIRY_SECONDS,
        )
    )
    response = core_v1.create_namespaced_service_account_token(
        _SA_NAME, namespace, token_request
    )
    return str(response.status.token)


def _write_kubeconfig(session_id: str, namespace: str, token: str, platform_kubeconfig_path: str) -> Path:
    """Build a session-scoped kubeconfig and write it to disk (chmod 600)."""
    with open(platform_kubeconfig_path) as f:
        platform_cfg = yaml.safe_load(f)

    cluster_info = platform_cfg["clusters"][0]["cluster"]
    server: str = cluster_info["server"]
    ca_data: str = cluster_info["certificate-authority-data"]

    kubeconfig = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": "k3s", "cluster": {"server": server, "certificate-authority-data": ca_data}}],
        "contexts": [{"name": "learner-ctx", "context": {"cluster": "k3s", "namespace": namespace, "user": "lab-learner"}}],
        "current-context": "learner-ctx",
        "users": [{"name": "lab-learner", "user": {"token": token}}],
    }

    cred_dir = _CRED_BASE_DIR / session_id
    cred_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cred_dir, 0o700)

    config_path = cred_dir / "config"
    # Write to temp then rename for atomicity
    fd, tmp_path = tempfile.mkstemp(dir=cred_dir)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(kubeconfig, f, default_flow_style=False)
        os.chmod(tmp_path, 0o600)
        os.rename(tmp_path, config_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    logger.info("Learner kubeconfig written for session %s (namespace=%s)", session_id, namespace)
    return config_path


def ensure_learner_credentials(
    session_id: str,
    namespace: str,
    platform_kubeconfig_path: str,
) -> str:
    """
    Idempotently create SA, Role, and RoleBinding in the lab namespace,
    then generate a short-lived kubeconfig.

    Returns the absolute path to the session-scoped kubeconfig file.
    Raises ValueError for invalid session_id.
    Raises ApiException / IOError on K8s or filesystem errors.
    """
    _validate_session_id(session_id)

    api_client = _build_api_client(platform_kubeconfig_path)
    core_v1 = k8s_client.CoreV1Api(api_client=api_client)
    rbac_v1 = k8s_client.RbacAuthorizationV1Api(api_client=api_client)

    _ensure_sa(core_v1, namespace)
    _ensure_role(rbac_v1, namespace)
    _ensure_rolebinding(rbac_v1, namespace)

    token = _create_sa_token(core_v1, namespace)
    path = _write_kubeconfig(session_id, namespace, token, platform_kubeconfig_path)
    return str(path)


def reclaim_learner_credentials(
    session_id: str,
    namespace: str,
    platform_kubeconfig_path: str,
) -> None:
    """
    Delete SA, Role, and RoleBinding from the namespace and remove the
    local kubeconfig file.  Errors are logged but not re-raised so that
    session cleanup is not blocked by a partial K8s failure.
    """
    _validate_session_id(session_id)

    try:
        api_client = _build_api_client(platform_kubeconfig_path)
        core_v1 = k8s_client.CoreV1Api(api_client=api_client)
        rbac_v1 = k8s_client.RbacAuthorizationV1Api(api_client=api_client)

        for delete_fn, name, kind in [
            (lambda: core_v1.delete_namespaced_service_account(_SA_NAME, namespace), _SA_NAME, "SA"),
            (lambda: rbac_v1.delete_namespaced_role(_ROLE_NAME, namespace), _ROLE_NAME, "Role"),
            (lambda: rbac_v1.delete_namespaced_role_binding(_RB_NAME, namespace), _RB_NAME, "RoleBinding"),
        ]:
            try:
                delete_fn()
                logger.debug("Deleted learner %s %s from %s", kind, name, namespace)
            except ApiException as exc:
                if exc.status != 404:
                    logger.warning("Failed to delete learner %s %s/%s: %s", kind, name, namespace, exc)
    except Exception as exc:
        logger.warning("Learner K8s reclaim error for session %s: %s", session_id, exc)

    # Always attempt local kubeconfig removal
    cred_dir = _CRED_BASE_DIR / session_id
    try:
        config_file = cred_dir / "config"
        if config_file.exists():
            os.unlink(config_file)
        if cred_dir.exists():
            cred_dir.rmdir()
        logger.info("Learner kubeconfig reclaimed for session %s", session_id)
    except Exception as exc:
        logger.warning("Learner kubeconfig removal failed for session %s: %s", session_id, exc)


def get_kubeconfig_path(session_id: str) -> Optional[Path]:
    """Return the kubeconfig path if it exists, else None."""
    path = _CRED_BASE_DIR / session_id / "config"
    return path if path.exists() else None
