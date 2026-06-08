"""
Verifier credential lifecycle — store, executor port, identity manager.

File layout under creds/vm_creds/{vm_id}/:
  kubeconfig.yaml  — kubeconfig content (chmod 600)
  metadata.json    — VerifierCredentialMetadata (chmod 600)

Security constraints:
  - kubeconfig content MUST NOT appear in log output (enforced at call sites)
  - verifier kubeconfig is for step verification only; namespace lifecycle
    uses the platform kubeconfig (see namespace_lifecycle.py)
  - vm_id is validated against ^[0-9]+$ to prevent path traversal
  - No ClusterRoleBinding or namespace RoleBinding is created here
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import Field

from backend.labgen.models import (
    SchemaVersionedModel,
    VerifierCredentialMetadata,
)

# VM IDs in this project are numeric integers (500-599); reject anything else.
_VM_ID_RE = re.compile(r"^[0-9]+$")

# Strict format validators for values interpolated into kubeconfig YAML.
# These guard against YAML injection if a VM returns malformed kubectl output.
_SERVER_URL_RE = re.compile(r"^https?://[A-Za-z0-9.\-:]+$")
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=]+$")
_JWT_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-_.]+$")


def _validate_vm_id(vm_id: str) -> None:
    if not _VM_ID_RE.match(vm_id):
        raise ValueError(f"Invalid vm_id {vm_id!r}: must be numeric")


# ---------------------------------------------------------------------------
# Kubernetes manifest constants (applied via kubectl apply — idempotent)
# ---------------------------------------------------------------------------

# ServiceAccount for verifier identity (kube-system namespace)
_SA_MANIFEST = (
    "apiVersion: v1\n"
    "kind: ServiceAccount\n"
    "metadata:\n"
    "  name: lab-verifier\n"
    "  namespace: kube-system\n"
)

# ClusterRole grants read-only access to namespaces and common resources.
# No ClusterRoleBinding is created here — binding is done per-lab at session start.
_CLUSTER_ROLE_MANIFEST = (
    "apiVersion: rbac.authorization.k8s.io/v1\n"
    "kind: ClusterRole\n"
    "metadata:\n"
    "  name: lab-verifier-namespace-readonly\n"
    "rules:\n"
    "- apiGroups: [\"\"]\n"
    "  resources: [\"namespaces\", \"pods\", \"services\", \"configmaps\", \"endpoints\"]\n"
    "  verbs: [\"get\", \"list\", \"watch\"]\n"
    "- apiGroups: [\"apps\"]\n"
    "  resources: [\"deployments\", \"daemonsets\", \"statefulsets\", \"replicasets\"]\n"
    "  verbs: [\"get\", \"list\", \"watch\"]\n"
)


def _kubectl_apply_cmd(manifest: str) -> list[str]:
    """Build a command that applies a YAML manifest via python3 + kubectl apply -f -.

    Uses python3 subprocess so stdin piping works reliably via QEMU agent.
    The manifest content is embedded as a repr() literal — no shell quoting issues.
    """
    script = (
        "import subprocess as _s, sys as _sys;"
        f" _r=_s.run(['kubectl','apply','-f','-'],input={manifest!r}.encode(),"
        "capture_output=True,timeout=30);"
        "print(_r.stdout.decode(),end='');"
        "print(_r.stderr.decode(),file=_sys.stderr,end='');"
        "exit(_r.returncode)"
    )
    return ["python3", "-c", script]


def _build_kubeconfig(server: str, ca_data: str, token: str) -> str:
    """Assemble a kubeconfig YAML string for the lab-verifier service account.

    Validates each field against a strict regex before interpolation to prevent
    YAML injection if a VM returns malformed kubectl output.
    Caller MUST NOT log the return value — it contains a bearer token.
    """
    server = server.strip()
    ca_data = ca_data.strip()
    token = token.strip()
    if not _SERVER_URL_RE.match(server):
        raise ValueError(f"K3s server URL has unexpected format: {server!r}")
    if not _BASE64_RE.match(ca_data):
        raise ValueError("Cluster CA data is not valid base64")
    if not _JWT_TOKEN_RE.match(token):
        raise ValueError("Service account token contains unexpected characters")
    return (
        "apiVersion: v1\n"
        "kind: Config\n"
        "clusters:\n"
        "- cluster:\n"
        f"    server: {server}\n"
        f"    certificate-authority-data: {ca_data}\n"
        "  name: k3s-lab\n"
        "contexts:\n"
        "- context:\n"
        "    cluster: k3s-lab\n"
        "    user: lab-verifier\n"
        "  name: lab-verifier@k3s-lab\n"
        "current-context: lab-verifier@k3s-lab\n"
        "users:\n"
        "- name: lab-verifier\n"
        "  user:\n"
        f"    token: {token}\n"
    )


# ---------------------------------------------------------------------------
# Credential store  (creds/vm_creds/{vm_id}/)
# ---------------------------------------------------------------------------


class VerifierCredentialStore:
    """Filesystem store for per-VM verifier kubeconfigs.

    Stored under base_dir/{vm_id}/  with restrictive permissions (dir 700, files 600).
    vm_id MUST be numeric (validated); path traversal is rejected.
    NEVER write kubeconfig content to logs — callers must enforce this.
    """

    def __init__(self, base_dir: str | Path = "creds/vm_creds") -> None:
        self._base = Path(base_dir)

    # ------------------------------------------------------------------
    # Internal paths
    # ------------------------------------------------------------------

    def _vm_dir(self, vm_id: str) -> Path:
        _validate_vm_id(vm_id)
        return self._base / vm_id

    def _kubeconfig_path(self, vm_id: str) -> Path:
        return self._vm_dir(vm_id) / "kubeconfig.yaml"

    def _metadata_path(self, vm_id: str) -> Path:
        return self._vm_dir(vm_id) / "metadata.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        vm_id: str,
        kubeconfig_yaml: str,
        metadata: VerifierCredentialMetadata,
    ) -> None:
        """Persist kubeconfig and metadata with restrictive permissions (700/600).

        Uses atomic write (temp-file + rename) so files are never visible
        with loose permissions.
        """
        vm_dir = self._vm_dir(vm_id)
        vm_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(vm_dir, 0o700)

        self._atomic_write(vm_dir, "kubeconfig.yaml", kubeconfig_yaml)
        self._atomic_write(vm_dir, "metadata.json", metadata.model_dump_json())

    def load(self, vm_id: str) -> tuple[str, VerifierCredentialMetadata]:
        """Return (kubeconfig_yaml, metadata).  Raises FileNotFoundError if missing."""
        if not self.exists(vm_id):
            raise FileNotFoundError(f"No verifier credentials found for VM {vm_id}")
        kubeconfig = self._kubeconfig_path(vm_id).read_text()
        metadata = VerifierCredentialMetadata.model_validate_json(
            self._metadata_path(vm_id).read_text()
        )
        return kubeconfig, metadata

    def delete(self, vm_id: str) -> None:
        """Remove the entire vm_id directory (kubeconfig.yaml + metadata.json)."""
        vm_dir = self._vm_dir(vm_id)
        if vm_dir.is_dir() and not vm_dir.is_symlink():
            shutil.rmtree(vm_dir)

    def exists(self, vm_id: str) -> bool:
        """True only when both files are present (guards against partial writes)."""
        return (
            self._kubeconfig_path(vm_id).exists()
            and self._metadata_path(vm_id).exists()
        )

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    @staticmethod
    def _atomic_write(directory: Path, filename: str, content: str) -> None:
        """Write content atomically with mode 0o600: temp-file → fchmod → rename."""
        fd, tmp_path = tempfile.mkstemp(dir=directory)
        try:
            os.write(fd, content.encode())
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        os.replace(tmp_path, directory / filename)


# ---------------------------------------------------------------------------
# VMCommandExecutorPort
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class VMCommandExecutorPort(ABC):
    @abstractmethod
    def execute(self, vm_id: str, command: list[str]) -> CommandResult: ...


class StubVMCommandExecutor(VMCommandExecutorPort):
    """Configurable in-process stub.  Records calls for assertion.  Tests only."""

    def __init__(
        self,
        exit_code: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[tuple[str, list[str]]] = []

    def execute(self, vm_id: str, command: list[str]) -> CommandResult:
        self.calls.append((vm_id, list(command)))
        return CommandResult(exit_code=self.exit_code, stdout=self.stdout, stderr=self.stderr)


# ---------------------------------------------------------------------------
# Smoke test result models
# ---------------------------------------------------------------------------


class SmokeCheckResult(SchemaVersionedModel):
    check_name: str
    passed: bool
    detail: str = ""


class VerifierSmokeTestResult(SchemaVersionedModel):
    vm_id: str
    passed: bool
    checks: list[SmokeCheckResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# VerifierIdentityManager
# ---------------------------------------------------------------------------


class VerifierIdentityManager:
    """Manages verifier identity lifecycle per VM via injected executor.

    Constraint: kubeconfig content MUST NOT be logged at any call site.
    No ClusterRoleBinding or namespace RoleBinding is created — permissions
    are bound per-lab at session start.
    """

    def __init__(
        self,
        store: VerifierCredentialStore,
        executor: VMCommandExecutorPort,
    ) -> None:
        self._store = store
        self._executor = executor

    def ensure_verifier_identity(self, vm_id: str) -> VerifierCredentialMetadata:
        """Apply lab-verifier SA + ClusterRole, extract kubeconfig, save to store.

        Idempotent: kubectl apply is a no-op if resources already exist.
        Increments credential_generation on re-run.
        """
        # Apply ServiceAccount (idempotent via kubectl apply)
        r = self._executor.execute(vm_id, _kubectl_apply_cmd(_SA_MANIFEST))
        if not r.succeeded:
            raise RuntimeError(
                f"Failed to apply lab-verifier ServiceAccount: exit_code={r.exit_code}"
            )

        # Apply ClusterRole (idempotent, no binding created)
        r = self._executor.execute(vm_id, _kubectl_apply_cmd(_CLUSTER_ROLE_MANIFEST))
        if not r.succeeded:
            raise RuntimeError(
                f"Failed to apply lab-verifier-namespace-readonly ClusterRole: exit_code={r.exit_code}"
            )

        # Retrieve K3s API server URL
        r = self._executor.execute(vm_id, [
            "kubectl", "config", "view", "--minify", "-o",
            "jsonpath={.clusters[0].cluster.server}",
        ])
        if not r.succeeded or not r.stdout.strip():
            raise RuntimeError(
                f"Failed to retrieve K3s server URL: exit_code={r.exit_code}"
            )
        server = r.stdout.strip()

        # Retrieve cluster CA certificate (base64-encoded)
        r = self._executor.execute(vm_id, [
            "kubectl", "config", "view", "--minify", "--raw", "-o",
            "jsonpath={.clusters[0].cluster.certificate-authority-data}",
        ])
        if not r.succeeded:
            raise RuntimeError(
                f"Failed to retrieve cluster CA data: exit_code={r.exit_code}"
            )
        ca_data = r.stdout.strip()

        # Create a long-lived service account token (content must never be logged)
        r = self._executor.execute(vm_id, [
            "kubectl", "create", "token", "lab-verifier",
            "-n", "kube-system", "--duration=8760h",
        ])
        if not r.succeeded or not r.stdout.strip():
            raise RuntimeError(
                f"Failed to create lab-verifier token: exit_code={r.exit_code}"
            )
        token = r.stdout.strip()

        # Build kubeconfig — NEVER log this value
        kubeconfig = _build_kubeconfig(server, ca_data, token)

        # Increment generation on re-run (credentials rotation)
        gen = 1
        if self._store.exists(vm_id):
            _, existing_meta = self._store.load(vm_id)
            gen = existing_meta.credential_generation + 1

        now = datetime.now(tz=timezone.utc)
        metadata = VerifierCredentialMetadata(
            vm_id=vm_id,
            created_at=now,
            expires_at=now + timedelta(hours=8760),
            k3s_endpoint=server,
            credential_generation=gen,
        )
        self._store.save(vm_id, kubeconfig, metadata)
        return metadata

    def export_verifier_kubeconfig(self, vm_id: str) -> str:
        """Return raw kubeconfig YAML from store.  Caller MUST NOT log the return value."""
        kubeconfig, _ = self._store.load(vm_id)
        return kubeconfig

    def run_smoke_test(self, vm_id: str) -> VerifierSmokeTestResult:
        """Structural smoke checks — no real K3s API calls."""
        checks: list[SmokeCheckResult] = []

        exists = self._store.exists(vm_id)
        checks.append(SmokeCheckResult(check_name="credentials_exist", passed=exists))
        if not exists:
            return VerifierSmokeTestResult(vm_id=vm_id, passed=False, checks=checks)

        kubeconfig, metadata = self._store.load(vm_id)

        checks.append(SmokeCheckResult(
            check_name="has_clusters",
            passed="clusters:" in kubeconfig,
        ))
        checks.append(SmokeCheckResult(
            check_name="has_users",
            passed="users:" in kubeconfig,
        ))
        checks.append(SmokeCheckResult(
            check_name="has_token",
            passed="token:" in kubeconfig,
        ))
        checks.append(SmokeCheckResult(
            check_name="has_k3s_endpoint",
            passed=bool(metadata.k3s_endpoint),
        ))

        all_passed = all(c.passed for c in checks)
        return VerifierSmokeTestResult(vm_id=vm_id, passed=all_passed, checks=checks)
