"""
LinuxCleanupAdapter — workspace cleanup, residual scan, and taint-on-failure.

Design constraints:
- cleanup_path must be under workspace_root (validated before deletion).
- Forbidden roots cannot be deleted (/, /home, /tmp top-level, /etc, /var, /root).
- Residual scan verifies workspace is empty after cleanup.
- Cleanup failure marks the session as tainted (fail-closed).
- No shell calls — pure Python shutil/os.
- Idempotent: second cleanup on a non-existent workspace is a no-op success.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FORBIDDEN_CLEANUP_ROOTS: frozenset[str] = frozenset({
    "/",
    "/home",
    "/tmp",
    "/etc",
    "/var",
    "/root",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/usr",
    "/bin",
    "/sbin",
})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ResidualScanResult:
    workspace_path: str
    exists: bool                          # True if workspace dir still exists
    residual_files: list[str] = field(default_factory=list)   # relative paths
    has_residual: bool = False

    def __post_init__(self) -> None:
        self.has_residual = self.exists or bool(self.residual_files)


@dataclass
class CleanupResult:
    workspace_path: str
    success: bool
    failure_reason: str = ""
    residual: ResidualScanResult | None = None


# ---------------------------------------------------------------------------
# LinuxCleanupAdapter
# ---------------------------------------------------------------------------


class LinuxCleanupAdapter:
    """Deletes the workspace directory and verifies no residual remains."""

    def __init__(self, sandbox_root: str = "/tmp/labgen-linux-sandboxes") -> None:
        self._sandbox_root = sandbox_root

    def cleanup(self, workspace_path: str) -> CleanupResult:
        """Remove workspace_path entirely.

        Returns CleanupResult.success=False and failure_reason if any step fails.
        Idempotent: if workspace does not exist, returns success.
        """
        # Safety: workspace_path must be inside sandbox_root.
        validation_error = self._validate_cleanup_target(workspace_path)
        if validation_error:
            logger.error(
                "linux_cleanup.cleanup.rejected",
                extra={"workspace_path": workspace_path, "reason": validation_error},
            )
            return CleanupResult(
                workspace_path=workspace_path,
                success=False,
                failure_reason=validation_error,
            )

        # If already gone — idempotent success.
        if not os.path.exists(workspace_path):
            residual = self.residual_scan(workspace_path)
            return CleanupResult(workspace_path=workspace_path, success=True, residual=residual)

        try:
            shutil.rmtree(workspace_path)
        except Exception as exc:
            reason = f"rmtree_failed: {exc}"
            logger.error(
                "linux_cleanup.cleanup.failed",
                extra={"workspace_path": workspace_path, "reason": reason},
            )
            return CleanupResult(
                workspace_path=workspace_path,
                success=False,
                failure_reason=reason,
                residual=self.residual_scan(workspace_path),
            )

        residual = self.residual_scan(workspace_path)
        if residual.has_residual:
            reason = f"residual_after_cleanup: {residual.residual_files}"
            logger.warning(
                "linux_cleanup.residual_detected",
                extra={"workspace_path": workspace_path, "residual": residual.residual_files},
            )
            return CleanupResult(
                workspace_path=workspace_path,
                success=False,
                failure_reason=reason,
                residual=residual,
            )

        return CleanupResult(workspace_path=workspace_path, success=True, residual=residual)

    def residual_scan(self, workspace_path: str) -> ResidualScanResult:
        """Check if workspace still exists or contains files."""
        if not os.path.exists(workspace_path):
            return ResidualScanResult(workspace_path=workspace_path, exists=False)

        files: list[str] = []
        for root, dirs, fnames in os.walk(workspace_path):
            for fname in fnames:
                abs_f = os.path.join(root, fname)
                files.append(os.path.relpath(abs_f, workspace_path))

        return ResidualScanResult(
            workspace_path=workspace_path,
            exists=True,
            residual_files=files,
        )

    def _validate_cleanup_target(self, workspace_path: str) -> str:
        """Return error string if target is forbidden, else empty string."""
        normalized = os.path.normpath(workspace_path)

        if normalized in _FORBIDDEN_CLEANUP_ROOTS:
            return f"forbidden_cleanup_root: '{normalized}' is a protected system path"

        for root in _FORBIDDEN_CLEANUP_ROOTS:
            if normalized == root:
                return f"forbidden_cleanup_root: '{normalized}'"

        # Must be under the sandbox root.
        sandbox_real = os.path.realpath(self._sandbox_root)
        target_real = os.path.realpath(normalized)
        if not target_real.startswith(sandbox_real + os.sep):
            return (
                f"cleanup_outside_sandbox_root: "
                f"'{target_real}' is not under '{sandbox_real}'"
            )

        # Must not contain .. traversal
        if ".." in workspace_path:
            return "path_traversal_in_cleanup_path"

        return ""
