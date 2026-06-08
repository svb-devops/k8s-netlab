"""
Verifier credential lifecycle — store, executor port, identity manager skeleton.

File layout under creds/vm_creds/{vm_id}/:
  kubeconfig.yaml  — kubeconfig content (chmod 600)
  metadata.json    — VerifierCredentialMetadata (chmod 600)

Security constraints:
  - kubeconfig content MUST NOT appear in log output
  - verifier kubeconfig is for step verification only; namespace lifecycle
    uses the platform kubeconfig (see namespace_lifecycle.py)
  - vm_id is validated against ^[0-9]+$ to prevent path traversal
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from backend.labgen.models import (
    SchemaVersionedModel,
    VerifierCredentialMetadata,
)

# VM IDs in this project are numeric integers (500-599); reject anything else.
_VM_ID_RE = re.compile(r"^[0-9]+$")


def _validate_vm_id(vm_id: str) -> None:
    if not _VM_ID_RE.match(vm_id):
        raise ValueError(f"Invalid vm_id {vm_id!r}: must be numeric")


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
# VerifierIdentityManager skeleton
# ---------------------------------------------------------------------------


class VerifierIdentityManager:
    """Manages verifier identity lifecycle per VM.

    Skeleton — real implementation requires SSH access to the VM and
    K3s kubeconfig extraction.  All methods raise NotImplementedError until
    implemented.

    Constraint: kubeconfig content MUST NOT be logged at any call site.
    """

    def __init__(
        self,
        store: VerifierCredentialStore,
        executor: VMCommandExecutorPort,
    ) -> None:
        self._store = store
        self._executor = executor

    def ensure_verifier_identity(self, vm_id: str) -> VerifierCredentialMetadata:
        """Ensure a verifier kubeconfig exists for vm_id; create or refresh if needed."""
        raise NotImplementedError(
            "VerifierIdentityManager.ensure_verifier_identity not yet implemented"
        )

    def export_verifier_kubeconfig(self, vm_id: str) -> str:
        """Return raw kubeconfig YAML string.  Caller must never log the return value."""
        raise NotImplementedError(
            "VerifierIdentityManager.export_verifier_kubeconfig not yet implemented"
        )

    def run_smoke_test(self, vm_id: str) -> VerifierSmokeTestResult:
        """Run structural smoke checks against the verifier kubeconfig (no real K3s)."""
        raise NotImplementedError(
            "VerifierIdentityManager.run_smoke_test not yet implemented"
        )
