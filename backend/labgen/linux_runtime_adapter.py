"""
LinuxRuntimeAdapter — spike-level Linux runtime adapter.

Wires together LinuxWorkspaceManager, LinuxCommandExecutor, and LinuxCleanupAdapter
into a minimal session lifecycle that proves the Linux domain adapter pattern.

Design contracts:
- A session is isolated to its workspace.  No cross-session access.
- Command execution uses LinuxCommandExecutor (no shell=True, strict allowlist).
- File operations use LinuxWorkspaceManager native API (no shell redirection).
- Cleanup is via LinuxCleanupAdapter; failure marks session tainted.
- No publish gate bypass: Linux sessions are never visible to learner catalog.
- No LLM calls.
- Not connected to K8s namespace lifecycle.
- Not connected to Proxmox VM tracker.
- LABGEN_LINUX_SPIKE_ENABLED must be True for session creation (default False).

Taint policy:
- cleanup failure → tainted=True, taint_reason set.
- Tainted sessions are not retried; workspace is marked for manual review.

NOT production-ready:
- No OS-level network isolation (kernel network namespaces).
- No OS-level process isolation (cgroups, seccomp, user namespaces).
- No terminal attach (LinuxTerminalAdapter is a future task).
- No verifier execution (LinuxVerifierClientPort is a future task).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from backend.labgen.linux_cleanup import CleanupResult, LinuxCleanupAdapter, ResidualScanResult
from backend.labgen.linux_command_executor import ExecutionResult, LinuxCommandExecutor
from backend.labgen.linux_workspace import (
    LinuxWorkspaceManager,
    WorkspaceSession,
)
from backend.labgen.models import LinuxSandboxPolicy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flag (default off — spike is not learner-visible)
# ---------------------------------------------------------------------------

# Import-time default.  Tests override via LinuxRuntimeAdapter(enabled=True).
_LINUX_SPIKE_ENABLED_DEFAULT: bool = False


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


class LinuxSpikeStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    CLEANUP_FAILED = "cleanup_failed"
    TAINTED = "tainted"


@dataclass
class LinuxSpikeSessionState:
    session_id: str
    workspace_path: str
    status: LinuxSpikeStatus = LinuxSpikeStatus.ACTIVE
    tainted: bool = False
    taint_reason: str = ""
    cleanup_verified: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    closed_at: str = ""
    policy_snapshot: dict = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.status == LinuxSpikeStatus.ACTIVE


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LinuxSpikeDisabledError(RuntimeError):
    """Raised when Linux spike is not enabled."""


class LinuxSpikeSessionNotFoundError(KeyError):
    """Raised when session_id does not exist."""


class LinuxSpikeSessionNotActiveError(RuntimeError):
    """Raised when session is closed or tainted."""


# ---------------------------------------------------------------------------
# LinuxRuntimeAdapter
# ---------------------------------------------------------------------------


class LinuxRuntimeAdapter:
    """Spike-level Linux runtime adapter.

    Not learner-visible.  Not production-ready.
    Validates the adapter boundary pattern for the Linux domain proof.
    """

    def __init__(
        self,
        enabled: bool = _LINUX_SPIKE_ENABLED_DEFAULT,
        sandbox_root: str = "/tmp/labgen-linux-sandboxes",
        timeout_seconds: int = 10,
        max_output_bytes: int = 65536,
    ) -> None:
        self._enabled = enabled
        self._workspace_mgr = LinuxWorkspaceManager(sandbox_root=sandbox_root)
        self._cmd_executor = LinuxCommandExecutor(
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        self._cleanup_adapter = LinuxCleanupAdapter(sandbox_root=sandbox_root)
        self._sessions: dict[str, LinuxSpikeSessionState] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(
        self,
        session_id: str,
        policy: LinuxSandboxPolicy | None = None,
    ) -> LinuxSpikeSessionState:
        """Create a new workspace session.

        Raises LinuxSpikeDisabledError if spike is disabled.
        Raises ValueError if session_id is already in use.
        """
        if not self._enabled:
            raise LinuxSpikeDisabledError(
                "Linux runtime spike is disabled.  "
                "Set enabled=True for testing.  "
                "Linux labs are not available to learners."
            )
        if session_id in self._sessions:
            raise ValueError(f"Session '{session_id}' already exists")

        ws_session = self._workspace_mgr.create_session(session_id)

        policy_snapshot: dict = {}
        if policy is not None:
            policy_snapshot = {
                "allow_network": policy.allow_network,
                "allow_root": policy.allow_root,
                "workspace_root": policy.workspace_root,
                "max_session_seconds": policy.max_session_seconds,
            }
            # Hard constraint: policy cannot override security invariants.
            if policy.allow_root:
                raise ValueError(
                    "LinuxSandboxPolicy.allow_root must be False — "
                    "root access is forbidden in the spike runtime"
                )
            if policy.allow_network:
                raise ValueError(
                    "LinuxSandboxPolicy.allow_network must be False — "
                    "network access is forbidden in the spike runtime"
                )

        state = LinuxSpikeSessionState(
            session_id=session_id,
            workspace_path=ws_session.workspace_path,
            policy_snapshot=policy_snapshot,
        )
        self._sessions[session_id] = state
        logger.info(
            "linux_spike.session.created",
            extra={"session_id": session_id, "workspace_path": ws_session.workspace_path},
        )
        return state

    def get_session(self, session_id: str) -> LinuxSpikeSessionState:
        """Return session state or raise LinuxSpikeSessionNotFoundError."""
        if session_id not in self._sessions:
            raise LinuxSpikeSessionNotFoundError(f"Session '{session_id}' not found")
        return self._sessions[session_id]

    def close_session(self, session_id: str) -> CleanupResult:
        """Close session and cleanup workspace.  Marks tainted on cleanup failure."""
        state = self.get_session(session_id)
        if not state.is_active():
            # Idempotent: already closed or tainted.
            result = CleanupResult(workspace_path=state.workspace_path, success=True)
            logger.info(
                "linux_spike.session.close_idempotent",
                extra={"session_id": session_id, "status": state.status.value},
            )
            return result

        result = self._cleanup_adapter.cleanup(state.workspace_path)

        if result.success:
            state.status = LinuxSpikeStatus.CLOSED
            state.cleanup_verified = True
            state.closed_at = datetime.now(tz=timezone.utc).isoformat()
            ws = self._workspace_mgr.get_session(session_id)
            if ws:
                self._workspace_mgr.close_session(ws)
        else:
            state.status = LinuxSpikeStatus.CLEANUP_FAILED
            state.tainted = True
            state.taint_reason = result.failure_reason
            state.cleanup_verified = False
            ws = self._workspace_mgr.get_session(session_id)
            if ws:
                self._workspace_mgr.mark_tainted(ws, result.failure_reason)
            logger.error(
                "linux_spike.session.cleanup_failed",
                extra={
                    "session_id": session_id,
                    "failure_reason": result.failure_reason,
                },
            )

        return result

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def execute_command(self, session_id: str, argv: list[str]) -> ExecutionResult:
        """Execute a command in the session workspace.

        Raises LinuxSpikeSessionNotActiveError if session is not active.
        """
        state = self._require_active(session_id)
        result = self._cmd_executor.execute(argv, state.workspace_path)
        logger.info(
            "linux_spike.command.executed",
            extra={
                "session_id": session_id,
                "argv": argv,
                "returncode": result.returncode,
                "policy_rejected": result.policy_rejected,
            },
        )
        return result

    # ------------------------------------------------------------------
    # File operations (Python-native, no shell)
    # ------------------------------------------------------------------

    def make_directory(self, session_id: str, rel_path: str) -> str:
        ws = self._require_workspace_session(session_id)
        return self._workspace_mgr.make_directory(ws, rel_path)

    def write_file(self, session_id: str, rel_path: str, content: str) -> str:
        ws = self._require_workspace_session(session_id)
        return self._workspace_mgr.write_file(ws, rel_path, content)

    def read_file(self, session_id: str, rel_path: str) -> str:
        ws = self._require_workspace_session(session_id)
        return self._workspace_mgr.read_file(ws, rel_path)

    def chmod_file(self, session_id: str, rel_path: str, mode_octal: int) -> None:
        ws = self._require_workspace_session(session_id)
        self._workspace_mgr.chmod_file(ws, rel_path, mode_octal)

    def stat_mode(self, session_id: str, rel_path: str) -> str:
        ws = self._require_workspace_session(session_id)
        return self._workspace_mgr.stat_mode(ws, rel_path)

    def file_exists(self, session_id: str, rel_path: str) -> bool:
        ws = self._require_workspace_session(session_id)
        return self._workspace_mgr.file_exists(ws, rel_path)

    def directory_exists(self, session_id: str, rel_path: str) -> bool:
        ws = self._require_workspace_session(session_id)
        return self._workspace_mgr.directory_exists(ws, rel_path)

    # ------------------------------------------------------------------
    # Workspace manager access (for LinuxVerifierService co-location)
    # ------------------------------------------------------------------

    @property
    def workspace_manager(self) -> LinuxWorkspaceManager:
        """Return the underlying workspace manager.

        Used by LinuxVerifierService to share the same workspace state
        as this adapter without creating a second manager for the same sandbox.
        """
        return self._workspace_mgr

    # ------------------------------------------------------------------
    # Residual scan (without cleanup)
    # ------------------------------------------------------------------

    def residual_scan(self, session_id: str) -> ResidualScanResult:
        state = self.get_session(session_id)
        return self._cleanup_adapter.residual_scan(state.workspace_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_active(self, session_id: str) -> LinuxSpikeSessionState:
        state = self.get_session(session_id)
        if not state.is_active():
            raise LinuxSpikeSessionNotActiveError(
                f"Session '{session_id}' is not active (status={state.status.value})"
            )
        return state

    def _require_workspace_session(self, session_id: str) -> WorkspaceSession:
        self._require_active(session_id)
        ws = self._workspace_mgr.get_session(session_id)
        if ws is None:
            raise LinuxSpikeSessionNotFoundError(
                f"Workspace session for '{session_id}' not found in manager"
            )
        return ws
