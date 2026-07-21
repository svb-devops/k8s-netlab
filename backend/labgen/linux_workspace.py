"""
LinuxWorkspaceManager — per-session workspace lifecycle for the Linux spike.

Design constraints:
- Every session gets an isolated directory under _SPIKE_SANDBOX_ROOT.
- workspace_root must never be /, /home, /tmp (top-level), /etc, /var, /root.
- Path resolution enforces no .. traversal and no absolute escapes.
- Spike workspaces live under /tmp/labgen-linux-sandboxes/<session_id>/.
- Not exposed to learners; not connected to publish gate; not catalog-visible.
- No shell calls, no subprocess — pure Python os/shutil.

NOT production-ready: network isolation and process isolation are NOT enforced
at the OS level.  This is a backend spike proving the adapter interface, not a
deployed container sandbox.
"""

from __future__ import annotations

import os
import shutil
import stat
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants — all path restrictions are enforced here, not scattered.
# ---------------------------------------------------------------------------

_SPIKE_SANDBOX_ROOT: str = "/tmp/labgen-linux-sandboxes"

# Forbidden roots that must never be used as sandbox_root or workspace_root.
_FORBIDDEN_WORKSPACE_ROOTS: frozenset[str] = frozenset({
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

# Explicitly allowed sandbox roots that are sub-directories of forbidden roots
# but are designated safe because they are owned and controlled by LabGen.
# This allowlist is the ONLY exception to the forbidden root check.
_ALLOWED_SANDBOX_ROOTS: frozenset[str] = frozenset({
    "/tmp/labgen-linux-sandboxes",
})

# Maximum length for session_id to avoid FS path length issues.
_SESSION_ID_MAX_LEN: int = 64


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WorkspaceError(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class WorkspacePathEscapeError(WorkspaceError):
    """Raised when a resolved path escapes the workspace_root."""


class WorkspaceRootForbiddenError(WorkspaceError):
    """Raised when workspace_root resolves to a forbidden/system directory."""


# ---------------------------------------------------------------------------
# WorkspaceSession
# ---------------------------------------------------------------------------


@dataclass
class WorkspaceSession:
    session_id: str
    workspace_path: str          # absolute, under _SPIKE_SANDBOX_ROOT
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    closed: bool = False
    tainted: bool = False
    taint_reason: str = ""

    def is_active(self) -> bool:
        return not self.closed and not self.tainted


# ---------------------------------------------------------------------------
# LinuxWorkspaceManager
# ---------------------------------------------------------------------------


class LinuxWorkspaceManager:
    """Creates and manages per-session workspace directories.

    Spike semantics:
    - workspace_path = /tmp/labgen-linux-sandboxes/<session_id>
    - session_id must be safe (UUID-like) to avoid directory traversal.
    - All path resolution goes through resolve_path().
    """

    def __init__(
        self,
        sandbox_root: str = _SPIKE_SANDBOX_ROOT,
        owner_uid: int | None = None,
        owner_gid: int | None = None,
    ) -> None:
        # Validate sandbox_root at construction time so that a misconfigured
        # sandbox_root (e.g. /home/user/custom-sandboxes) is rejected immediately,
        # before any session is created.  This catches the depth-2+ forbidden-root
        # case that per-workspace-path validation cannot see.
        #
        # Exception: paths in _ALLOWED_SANDBOX_ROOTS are LabGen-owned directories
        # that are explicitly allowed even if their parent is a forbidden root
        # (e.g. /tmp/labgen-linux-sandboxes is under /tmp but is the designated
        # spike sandbox directory).
        normalized_root = os.path.normpath(sandbox_root)
        # A sandbox_root is allowed if it IS one of the allowed roots OR is under one.
        # e.g. /tmp/labgen-linux-sandboxes/pytest-xxx is under /tmp/labgen-linux-sandboxes → OK.
        under_allowed = any(
            normalized_root == a or normalized_root.startswith(a + os.sep)
            for a in _ALLOWED_SANDBOX_ROOTS
        )
        if not under_allowed:
            for forbidden in _FORBIDDEN_WORKSPACE_ROOTS:
                if normalized_root == forbidden or normalized_root.startswith(forbidden + os.sep):
                    raise WorkspaceRootForbiddenError(
                        "forbidden_sandbox_root",
                        f"sandbox_root '{sandbox_root}' is or is under a forbidden system root "
                        f"'{forbidden}'. Use a path not under system directories, "
                        f"or one of the allowed sandbox roots: {sorted(_ALLOWED_SANDBOX_ROOTS)}",
                    )
        self._sandbox_root = sandbox_root
        # If set, every session workspace directory is chowned to this
        # UID/GID after creation (see backend.labgen.linux_runner_identity),
        # so the unprivileged runner process that executes learner commands
        # can actually read/write inside it — os.makedirs() below creates the
        # directory as whatever this (root) API process's own UID is, which
        # would otherwise leave a root:root, mode 0700 directory the runner
        # cannot enter at all.
        self._owner_uid = owner_uid
        self._owner_gid = owner_gid
        self._sessions: dict[str, WorkspaceSession] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, session_id: str | None = None) -> WorkspaceSession:
        """Create a new isolated workspace directory and return a WorkspaceSession."""
        sid = session_id if session_id is not None else str(uuid.uuid4())
        self._validate_session_id(sid)

        workspace_path = os.path.join(self._sandbox_root, sid)
        self._validate_workspace_root(workspace_path)

        os.makedirs(workspace_path, mode=0o700, exist_ok=False)
        if self._owner_uid is not None and self._owner_gid is not None:
            os.chown(workspace_path, self._owner_uid, self._owner_gid)

        session = WorkspaceSession(session_id=sid, workspace_path=workspace_path)
        self._sessions[sid] = session
        return session

    def get_session(self, session_id: str) -> WorkspaceSession | None:
        return self._sessions.get(session_id)

    def close_session(self, session: WorkspaceSession) -> None:
        session.closed = True

    def mark_tainted(self, session: WorkspaceSession, reason: str) -> None:
        session.tainted = True
        session.taint_reason = reason
        session.closed = True

    # ------------------------------------------------------------------
    # Path resolution — the single point of truth for path safety.
    # ------------------------------------------------------------------

    def resolve_path(self, session: WorkspaceSession, relative_path: str) -> str:
        """Resolve a workspace-relative path to an absolute path.

        Raises WorkspacePathEscapeError if the resolved path escapes workspace_root.
        Rejects absolute paths, empty paths, and .. traversal.
        """
        if not relative_path:
            raise WorkspacePathEscapeError(
                "empty_path",
                "Path must not be empty",
            )
        if os.path.isabs(relative_path):
            raise WorkspacePathEscapeError(
                "absolute_path_rejected",
                f"Absolute path '{relative_path}' is not allowed; use workspace-relative paths only",
            )
        if ".." in Path(relative_path).parts:
            raise WorkspacePathEscapeError(
                "path_traversal_rejected",
                f"Path traversal '..' detected in '{relative_path}'",
            )

        resolved = os.path.realpath(os.path.join(session.workspace_path, relative_path))
        workspace_real = os.path.realpath(session.workspace_path)

        if not resolved.startswith(workspace_real + os.sep) and resolved != workspace_real:
            raise WorkspacePathEscapeError(
                "path_escape_rejected",
                f"Resolved path '{resolved}' escapes workspace root '{workspace_real}'",
            )
        return resolved

    # ------------------------------------------------------------------
    # Filesystem operations — Python-native, no shell.
    # ------------------------------------------------------------------

    def make_directory(self, session: WorkspaceSession, rel_path: str) -> str:
        """Create directory (mkdir -p equivalent). Returns absolute path."""
        abs_path = self.resolve_path(session, rel_path)
        os.makedirs(abs_path, mode=0o755, exist_ok=True)
        return abs_path

    def write_file(self, session: WorkspaceSession, rel_path: str, content: str) -> str:
        """Write text content to a file. Creates parent dirs as needed."""
        abs_path = self.resolve_path(session, rel_path)
        parent = os.path.dirname(abs_path)
        if parent and parent != session.workspace_path:
            self.resolve_path(session, os.path.relpath(parent, session.workspace_path))
        os.makedirs(os.path.dirname(abs_path), mode=0o755, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return abs_path

    def read_file(self, session: WorkspaceSession, rel_path: str, max_bytes: int = 65536) -> str:
        """Read file content (cat equivalent)."""
        abs_path = self.resolve_path(session, rel_path)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)

    def chmod_file(self, session: WorkspaceSession, rel_path: str, mode_octal: int) -> None:
        """Set file permissions (chmod equivalent)."""
        abs_path = self.resolve_path(session, rel_path)
        os.chmod(abs_path, mode_octal)

    def stat_mode(self, session: WorkspaceSession, rel_path: str) -> str:
        """Return octal mode string (e.g. '600') for a file."""
        abs_path = self.resolve_path(session, rel_path)
        file_stat = os.stat(abs_path)
        mode_bits = file_stat.st_mode & 0o777
        return oct(mode_bits)[2:]

    def file_exists(self, session: WorkspaceSession, rel_path: str) -> bool:
        """Check if a file exists (workspace-relative)."""
        try:
            abs_path = self.resolve_path(session, rel_path)
        except WorkspacePathEscapeError:
            return False
        return os.path.isfile(abs_path)

    def directory_exists(self, session: WorkspaceSession, rel_path: str) -> bool:
        """Check if a directory exists (workspace-relative)."""
        try:
            abs_path = self.resolve_path(session, rel_path)
        except WorkspacePathEscapeError:
            return False
        return os.path.isdir(abs_path)

    def list_files_recursive(self, session: WorkspaceSession) -> list[str]:
        """Return all file paths (and symlinks) relative to workspace_root.

        Aligned with no_residual_files(): symlink-to-dirs are included in the
        result and not traversed. followlinks=False prevents escape via symlink.
        """
        workspace = session.workspace_path
        result: list[str] = []
        for root, dirs, files in os.walk(workspace, followlinks=False):
            for fname in files:
                abs_f = os.path.join(root, fname)
                result.append(os.path.relpath(abs_f, workspace))
            non_symlink_dirs = []
            for d in dirs:
                abs_d = os.path.join(root, d)
                try:
                    if stat.S_ISLNK(os.lstat(abs_d).st_mode):
                        result.append(os.path.relpath(abs_d, workspace))
                    else:
                        non_symlink_dirs.append(d)
                except OSError:
                    non_symlink_dirs.append(d)
            dirs[:] = non_symlink_dirs
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not session_id or len(session_id) > _SESSION_ID_MAX_LEN:
            raise WorkspaceError(
                "invalid_session_id",
                f"session_id must be non-empty and ≤ {_SESSION_ID_MAX_LEN} chars",
            )
        # Allow UUID format and safe alphanumeric + hyphen
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        bad = set(session_id) - allowed
        if bad:
            raise WorkspaceError(
                "unsafe_session_id",
                f"session_id contains unsafe characters: {sorted(bad)}",
            )

    @staticmethod
    def _validate_workspace_root(workspace_path: str) -> None:
        # Reject workspace_path that IS exactly a forbidden root.
        # Subdirectories of the designated sandbox_root (e.g. /tmp/labgen-linux-sandboxes/<id>)
        # are allowed — the sandbox_root is validated separately in __init__.
        normalized = os.path.normpath(workspace_path)
        if normalized in _FORBIDDEN_WORKSPACE_ROOTS:
            raise WorkspaceRootForbiddenError(
                "forbidden_workspace_root",
                f"workspace_path '{workspace_path}' is a forbidden system root",
            )
