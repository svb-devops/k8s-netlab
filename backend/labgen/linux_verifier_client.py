"""
LinuxVerifyClientAdapter — verifier for Linux domain steps (hardened).

Performs workspace-scoped filesystem checks for each LinuxVerifyType.
This is the Linux domain peer of K8sVerifierClientAdapter.

Design contracts:
- All path resolution goes through LinuxWorkspaceManager.resolve_path().
- No subprocess, no shell=True, no arbitrary command execution.
- No host absolute paths in learner-visible results.
- Sensitive content is never echoed in detail; content mismatch detail is redacted.
- max_output_bytes limits how much file content is read per check.
- WorkspacePathEscapeError propagates to LinuxVerifierService for safe failure.
- No K8s namespaces, RBAC, kubeconfig, or cluster operations involved.
- Workspace must be active; tainted or closed sessions fail closed.

TOCTOU mitigations (Hardening v0.1):
- lstat() used for existence checks — does not follow the final symlink component.
- Symlinks rejected fail-closed: any symlink at the target path causes failure.
- _recheck_containment() called before file open — re-resolves path and re-checks
  workspace containment to catch symlinks added after initial resolve_path().
- O_NOFOLLOW used at open() — OS-level prevention of final-component symlink follow.
- These three layers together close the practical TOCTOU attack surface.

Remaining limitation:
- Intermediate path component TOCTOU: if an intermediate directory in the workspace
  is replaced with a symlink after resolve_path() but before open(), neither
  _recheck_containment() nor O_NOFOLLOW can catch it without OS-level openat().
  Severity: LOW — workspace is not exposed to concurrent learner processes in v0.1.
  Production hardening requires container isolation (user namespaces) or Python
  openat()-based path traversal.

NOT production-ready:
- Spike proves the adapter boundary pattern; workspace isolation is process-level only.
- No OS-level network or process isolation (cgroups, seccomp, user namespaces).
"""

from __future__ import annotations

import errno
import io
import logging
import os
import stat as stat_module
from typing import Optional, TYPE_CHECKING

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.linux_workspace import (
    LinuxWorkspaceManager,
    WorkspacePathEscapeError,
    WorkspaceSession,
)
from backend.labgen.models import LinuxVerifyTemplate, LinuxVerifyType, VerifyResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_MAX_DETAIL_LEN: int = 256      # learner-visible detail max chars
_RESIDUAL_SAMPLE_MAX: int = 3   # max residual paths shown in detail


# ---------------------------------------------------------------------------
# Module-level safety helpers
# ---------------------------------------------------------------------------


def _recheck_containment(abs_path: str, workspace_path: str) -> None:
    """Re-resolve abs_path and re-verify workspace containment.

    Called right before a filesystem operation to reduce the TOCTOU window
    between resolve_path() and the actual open/stat call.

    Raises WorkspacePathEscapeError if the path is no longer within workspace.
    Does NOT eliminate intermediate path component TOCTOU (see module docstring).
    """
    real_now = os.path.realpath(abs_path)
    workspace_real = os.path.realpath(workspace_path)
    if not (real_now.startswith(workspace_real + os.sep) or real_now == workspace_real):
        raise WorkspacePathEscapeError(
            "containment_recheck_failed",
            "Path escaped workspace containment after re-resolution (TOCTOU mitigation)",
        )


def _open_nofollow(abs_path: str, max_bytes: int) -> str:
    """Open a file refusing to follow a symlink at the final path component.

    Uses O_NOFOLLOW so the OS rejects the open if abs_path is a symlink.
    Returns file content as a str (UTF-8, replacement chars for decode errors).

    Raises WorkspacePathEscapeError if abs_path is a symlink (ELOOP).
    Raises OSError for other open/read failures (caller handles).
    """
    try:
        fd = os.open(abs_path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise WorkspacePathEscapeError(
                "symlink_at_open",
                "Symlink detected at open time (O_NOFOLLOW rejected)",
            )
        raise
    with io.open(fd, mode="r", encoding="utf-8", errors="replace") as fh:
        return fh.read(max_bytes)


def _validate_octal_mode(mode_str: str) -> bool:
    """Return True iff mode_str is a valid octal permission string (e.g. '600', '755')."""
    return (
        bool(mode_str)
        and all(c in "01234567" for c in mode_str)
        and 1 <= len(mode_str) <= 4
    )


# ---------------------------------------------------------------------------
# LinuxVerifyClientAdapter  (primitive filesystem checker — hardened)
# ---------------------------------------------------------------------------


class LinuxVerifyClientAdapter:
    """Filesystem primitive checker — bound to a single WorkspaceSession.

    Hardening v0.1:
    - lstat() used throughout (does not follow final symlink component).
    - Symlinks at target path rejected fail-closed.
    - _recheck_containment() before each file open.
    - O_NOFOLLOW via _open_nofollow() for content reads.

    All paths must be workspace-relative. WorkspacePathEscapeError is raised
    (not swallowed) so LinuxVerifierService can convert it to a safe VerifyResult.

    No shell execution. Every operation uses Python stdlib os / stat / io.
    """

    def __init__(
        self,
        workspace_manager: LinuxWorkspaceManager,
        workspace_session: WorkspaceSession,
    ) -> None:
        self._wm = workspace_manager
        self._ws = workspace_session

    # ------------------------------------------------------------------
    # Primitives — may raise WorkspacePathEscapeError on bad paths
    # ------------------------------------------------------------------

    def file_exists(self, rel_path: str) -> tuple[bool, str]:
        """Return (True, "") if rel_path is a regular file (not a symlink).

        Raises WorkspacePathEscapeError for absolute or traversal paths.

        Hardening: lstat() runs on the ORIGINAL (unresolved) joined path so that
        symlinks at rel_path are detected regardless of where they point — even
        inside-workspace symlinks are rejected fail-closed ("symlink_rejected").
        resolve_path() still validates for traversal/escape before lstat().
        """
        self._wm.resolve_path(self._ws, rel_path)  # validates traversal/escape
        original_abs = os.path.join(self._ws.workspace_path, rel_path)
        try:
            st = os.lstat(original_abs)
        except FileNotFoundError:
            return False, "not_found"
        except OSError:
            return False, "stat_error"
        if stat_module.S_ISLNK(st.st_mode):
            return False, "symlink_rejected"
        if stat_module.S_ISREG(st.st_mode):
            return True, ""
        if stat_module.S_ISDIR(st.st_mode):
            return False, "exists_but_not_file"
        return False, "exists_but_not_file"

    def directory_exists(self, rel_path: str) -> tuple[bool, str]:
        """Return (True, "") if rel_path is a directory (not a symlink).

        Raises WorkspacePathEscapeError for absolute or traversal paths.

        Hardening: lstat() on original unresolved path — symlinks always rejected,
        including inside-workspace symlinks. See file_exists() for pattern notes.
        """
        self._wm.resolve_path(self._ws, rel_path)  # validates traversal/escape
        original_abs = os.path.join(self._ws.workspace_path, rel_path)
        try:
            st = os.lstat(original_abs)
        except FileNotFoundError:
            return False, "not_found"
        except OSError:
            return False, "stat_error"
        if stat_module.S_ISLNK(st.st_mode):
            return False, "symlink_rejected"
        if stat_module.S_ISDIR(st.st_mode):
            return True, ""
        return False, "exists_but_not_directory"

    def file_content_matches(
        self, rel_path: str, expected: str, max_bytes: int
    ) -> tuple[bool, str]:
        """Check if rel_path is a regular file containing expected string.

        Raises WorkspacePathEscapeError for absolute or traversal paths,
        or if a symlink is detected during containment recheck or open.

        Hardening:
        - lstat() on original unresolved path — symlinks always rejected.
        - _recheck_containment() before open (TOCTOU window reduction).
        - _open_nofollow() with O_NOFOLLOW (final-component symlink rejection).
        - Content is NEVER included in the returned reason string.
        """
        abs_path = self._wm.resolve_path(self._ws, rel_path)
        original_abs = os.path.join(self._ws.workspace_path, rel_path)
        try:
            st = os.lstat(original_abs)
        except FileNotFoundError:
            return False, "not_found"
        except OSError:
            return False, "stat_error"
        if stat_module.S_ISLNK(st.st_mode):
            return False, "symlink_rejected"
        if not stat_module.S_ISREG(st.st_mode):
            return False, "not_found"
        if st.st_size > max_bytes:
            return False, "file_too_large"
        # Re-check containment right before open (reduces TOCTOU window)
        _recheck_containment(abs_path, self._ws.workspace_path)
        try:
            content = _open_nofollow(abs_path, max_bytes)
        except WorkspacePathEscapeError:
            raise
        except OSError:
            return False, "read_error"
        if expected in content:
            return True, ""
        return False, "content_mismatch"

    def file_mode_matches(
        self, rel_path: str, expected_mode: str
    ) -> tuple[bool, str]:
        """Check if rel_path has the expected octal permission mode.

        Raises WorkspacePathEscapeError for absolute or traversal paths.
        expected_mode is a string of octal digits (e.g. "600", "755").

        Hardening: lstat() on original unresolved path — symlinks always rejected.
        Mode bits read from original inode (not symlink target). Does NOT chmod.
        """
        self._wm.resolve_path(self._ws, rel_path)  # validates traversal/escape
        original_abs = os.path.join(self._ws.workspace_path, rel_path)
        try:
            st = os.lstat(original_abs)
        except FileNotFoundError:
            return False, "not_found"
        except OSError:
            return False, "stat_error"
        if stat_module.S_ISLNK(st.st_mode):
            return False, "symlink_rejected"
        mode_bits = st.st_mode & 0o777
        actual_mode = oct(mode_bits)[2:]
        # Normalize: strip leading zeros ("0600" == "600")
        actual_norm = actual_mode.lstrip("0") or "0"
        expected_norm = expected_mode.lstrip("0") or "0"
        if actual_norm == expected_norm:
            return True, ""
        return False, f"expected={expected_mode},actual={actual_mode}"

    def no_residual_files(self) -> tuple[bool, str]:
        """Check that the workspace is removed or contains no files/symlinks.

        Does not accept a path argument — always checks the entire workspace root.

        Hardening:
        - os.walk(followlinks=False) — does not traverse into symlinked directories.
        - Symlinks-to-directories detected via lstat() and counted as residuals.
        - Permission errors during scan treated as failure (fail-closed).
        - Vanished files during scan handled gracefully (skipped).
        - Reported paths are relative to workspace (no host absolute path leakage).
        """
        workspace = self._ws.workspace_path
        if not os.path.exists(workspace):
            return True, ""
        residuals: list[str] = []
        try:
            for root, dirs, fnames in os.walk(workspace, followlinks=False):
                # Regular files and symlinks-to-files appear in fnames
                for fname in fnames:
                    abs_f = os.path.join(root, fname)
                    rel_f = os.path.relpath(abs_f, workspace)
                    residuals.append(rel_f)
                # Symlinks-to-dirs appear in dirs (not traversed); count as residuals
                non_symlink_dirs = []
                for d in dirs:
                    abs_d = os.path.join(root, d)
                    try:
                        if stat_module.S_ISLNK(os.lstat(abs_d).st_mode):
                            rel_d = os.path.relpath(abs_d, workspace)
                            residuals.append(rel_d)
                        else:
                            non_symlink_dirs.append(d)
                    except OSError:
                        non_symlink_dirs.append(d)
                # Only recurse into real directories
                dirs[:] = non_symlink_dirs
        except PermissionError:
            return False, "permission_error_during_scan"
        if not residuals:
            return True, ""
        sample = ", ".join(residuals[:_RESIDUAL_SAMPLE_MAX])
        return False, f"{len(residuals)}_files_remain:{sample}"


# ---------------------------------------------------------------------------
# LinuxVerifierService  (orchestration layer — analog of VerifierService)
# ---------------------------------------------------------------------------


class LinuxVerifierService:
    """Dispatches LinuxVerifyTemplate checks for a workspace session.

    Analog of VerifierService for the Linux domain.

    Session identity: workspace session key = lab session id (by convention).
    Callers must create the workspace session with the same id as the lab session.

    Does not check LabSessionState (no K8s-style credential store needed).
    Does not make network calls.
    Does not execute arbitrary shell commands.
    """

    def __init__(self, workspace_manager: LinuxWorkspaceManager) -> None:
        self._wm = workspace_manager

    def check(
        self,
        workspace_session_id: str,
        template: LinuxVerifyTemplate,
    ) -> VerifyResult:
        """Check a single LinuxVerifyTemplate against the workspace session.

        Returns a VerifyResult. On error, passed=False with a stable failure_reason.
        detail never contains host absolute paths, tokens, or raw file content.
        """

        def _fail(reason: FailureReason, detail: str = "") -> VerifyResult:
            code = reason.value
            return VerifyResult(
                session_id=workspace_session_id,
                verify_id=template.verify_id,
                verify_type=template.type.value,
                passed=False,
                error_code=code,
                failure_reason=code,
                detail=detail[:_MAX_DETAIL_LEN],
            )

        def _pass(detail: str = "") -> VerifyResult:
            return VerifyResult(
                session_id=workspace_session_id,
                verify_id=template.verify_id,
                verify_type=template.type.value,
                passed=True,
                detail=detail[:_MAX_DETAIL_LEN],
            )

        ws = self._wm.get_session(workspace_session_id)
        if ws is None:
            return _fail(FailureReason.LINUX_WORKSPACE_NOT_FOUND)

        if not ws.is_active():
            return _fail(FailureReason.LINUX_WORKSPACE_NOT_ACTIVE)

        adapter = LinuxVerifyClientAdapter(self._wm, ws)
        vtype = template.type
        rel_path = template.target_path

        # Pre-validate path for all types that use rel_path (not no_residual_files)
        if vtype != LinuxVerifyType.LINUX_NO_RESIDUAL_FILES and rel_path:
            try:
                self._wm.resolve_path(ws, rel_path)
            except WorkspacePathEscapeError as exc:
                logger.warning(
                    "linux_verifier.path_escape_rejected",
                    extra={
                        "session_id": workspace_session_id,
                        "verify_id": template.verify_id,
                        "escape_reason": exc.reason,
                    },
                )
                return _fail(FailureReason.LINUX_PATH_ESCAPE, f"path_escape:{exc.reason}")

        try:
            if vtype == LinuxVerifyType.LINUX_FILE_EXISTS:
                passed, reason = adapter.file_exists(rel_path)
                if passed:
                    return _pass(f"File '{rel_path}' exists in workspace.")
                if reason == "symlink_rejected":
                    return _fail(
                        FailureReason.LINUX_PATH_ESCAPE,
                        f"Path '{rel_path}' is a symlink and was rejected for safety.",
                    )
                if reason == "exists_but_not_file":
                    return _fail(
                        FailureReason.LINUX_FILE_NOT_FOUND,
                        f"Path '{rel_path}' exists but is not a regular file.",
                    )
                return _fail(
                    FailureReason.LINUX_FILE_NOT_FOUND,
                    f"File '{rel_path}' was not found in workspace.",
                )

            if vtype == LinuxVerifyType.LINUX_DIRECTORY_EXISTS:
                passed, reason = adapter.directory_exists(rel_path)
                if passed:
                    return _pass(f"Directory '{rel_path}' exists in workspace.")
                if reason == "symlink_rejected":
                    return _fail(
                        FailureReason.LINUX_PATH_ESCAPE,
                        f"Path '{rel_path}' is a symlink and was rejected for safety.",
                    )
                if reason == "exists_but_not_directory":
                    return _fail(
                        FailureReason.LINUX_DIRECTORY_NOT_FOUND,
                        f"Path '{rel_path}' exists but is not a directory.",
                    )
                return _fail(
                    FailureReason.LINUX_DIRECTORY_NOT_FOUND,
                    f"Directory '{rel_path}' was not found in workspace.",
                )

            if vtype == LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES:
                expected = template.expected_content
                if expected is None:
                    return _fail(
                        FailureReason.LINUX_VERIFY_TYPE_NOT_SUPPORTED,
                        "expected_content must be set for linux_file_content_matches.",
                    )
                passed, reason = adapter.file_content_matches(
                    rel_path, expected, max_bytes=template.max_output_bytes
                )
                if passed:
                    return _pass(f"File '{rel_path}' contains expected content.")
                if reason == "symlink_rejected":
                    return _fail(
                        FailureReason.LINUX_PATH_ESCAPE,
                        f"Path '{rel_path}' is a symlink and was rejected for safety.",
                    )
                if reason == "not_found":
                    return _fail(
                        FailureReason.LINUX_FILE_NOT_FOUND,
                        f"File '{rel_path}' was not found.",
                    )
                if reason == "file_too_large":
                    return _fail(
                        FailureReason.LINUX_FILE_TOO_LARGE,
                        f"File '{rel_path}' exceeds max read size. [content not checked]",
                    )
                # Content mismatch: redact actual content — never echo it
                return _fail(
                    FailureReason.LINUX_CONTENT_MISMATCH,
                    f"File '{rel_path}' content does not match expected. [content redacted]",
                )

            if vtype == LinuxVerifyType.LINUX_FILE_MODE_MATCHES:
                expected_mode = template.expected_mode
                if expected_mode is None:
                    return _fail(
                        FailureReason.LINUX_VERIFY_TYPE_NOT_SUPPORTED,
                        "expected_mode must be set for linux_file_mode_matches.",
                    )
                # Validate octal format before calling adapter
                if not _validate_octal_mode(expected_mode):
                    return _fail(
                        FailureReason.LINUX_VERIFY_TYPE_NOT_SUPPORTED,
                        f"expected_mode '{expected_mode}' is not a valid octal mode string.",
                    )
                passed, reason = adapter.file_mode_matches(rel_path, expected_mode)
                if passed:
                    return _pass(f"File '{rel_path}' has expected mode {expected_mode}.")
                if reason == "symlink_rejected":
                    return _fail(
                        FailureReason.LINUX_PATH_ESCAPE,
                        f"Path '{rel_path}' is a symlink and was rejected for safety.",
                    )
                if "not_found" in reason or reason == "stat_error":
                    return _fail(
                        FailureReason.LINUX_FILE_NOT_FOUND,
                        f"File '{rel_path}' was not found.",
                    )
                # Safe to include mode values; never include file content or host path
                return _fail(
                    FailureReason.LINUX_MODE_MISMATCH,
                    f"File '{rel_path}' mode mismatch ({reason}).",
                )

            if vtype == LinuxVerifyType.LINUX_NO_RESIDUAL_FILES:
                passed, reason = adapter.no_residual_files()
                if passed:
                    return _pass("Workspace has no residual files.")
                if reason == "permission_error_during_scan":
                    return _fail(
                        FailureReason.LINUX_RESIDUAL_FILES_FOUND,
                        "Workspace scan failed due to permission error.",
                    )
                return _fail(
                    FailureReason.LINUX_RESIDUAL_FILES_FOUND,
                    "Workspace contains residual files after cleanup.",
                )

        except WorkspacePathEscapeError as exc:
            # Secondary guard: catch any escape that slips through pre-validation
            logger.warning(
                "linux_verifier.path_escape_in_dispatch",
                extra={
                    "session_id": workspace_session_id,
                    "verify_id": template.verify_id,
                    "escape_reason": exc.reason,
                },
            )
            return _fail(FailureReason.LINUX_PATH_ESCAPE, f"path_escape:{exc.reason}")

        return _fail(
            FailureReason.LINUX_VERIFY_TYPE_NOT_SUPPORTED,
            f"Unsupported Linux verify type: {vtype.value}",
        )
