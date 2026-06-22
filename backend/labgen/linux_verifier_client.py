"""
LinuxVerifyClientAdapter — verifier for Linux domain steps.

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

NOT production-ready:
- Spike proves the adapter boundary pattern; workspace isolation is process-level only.
- No OS-level network or process isolation (cgroups, seccomp, user namespaces).
"""

from __future__ import annotations

import logging
import os
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
# LinuxVerifyClientAdapter  (primitive filesystem checker)
# ---------------------------------------------------------------------------


class LinuxVerifyClientAdapter:
    """Filesystem primitive checker — bound to a single WorkspaceSession.

    All paths must be workspace-relative.  WorkspacePathEscapeError is raised
    (not swallowed) so LinuxVerifierService can convert it to a safe VerifyResult.

    No shell execution.  Every operation uses Python stdlib os / stat / open.
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
        """Return (True, "") if rel_path is a regular file.

        Raises WorkspacePathEscapeError for absolute or traversal paths.
        Returns (False, "exists_but_not_file") if path exists but is not a file.
        Returns (False, "not_found") if path does not exist.
        """
        abs_path = self._wm.resolve_path(self._ws, rel_path)
        if os.path.isfile(abs_path):
            return True, ""
        if os.path.exists(abs_path):
            return False, "exists_but_not_file"
        return False, "not_found"

    def directory_exists(self, rel_path: str) -> tuple[bool, str]:
        """Return (True, "") if rel_path is a directory.

        Raises WorkspacePathEscapeError for absolute or traversal paths.
        Returns (False, "exists_but_not_directory") if path exists but is not a dir.
        Returns (False, "not_found") if path does not exist.
        """
        abs_path = self._wm.resolve_path(self._ws, rel_path)
        if os.path.isdir(abs_path):
            return True, ""
        if os.path.exists(abs_path):
            return False, "exists_but_not_directory"
        return False, "not_found"

    def file_content_matches(
        self, rel_path: str, expected: str, max_bytes: int
    ) -> tuple[bool, str]:
        """Check if rel_path is a file containing expected string.

        Raises WorkspacePathEscapeError for absolute or traversal paths.
        Returns (False, "not_found") if file missing.
        Returns (False, "file_too_large") if file exceeds max_bytes.
        Returns (False, "content_mismatch") if content does not contain expected.
        Content is NEVER included in the returned reason string.
        """
        abs_path = self._wm.resolve_path(self._ws, rel_path)
        if not os.path.isfile(abs_path):
            return False, "not_found"
        try:
            size = os.path.getsize(abs_path)
        except OSError:
            return False, "stat_error"
        if size > max_bytes:
            return False, "file_too_large"
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(max_bytes)
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
        expected_mode is a string like "600", "755" (octal digits, no leading "0o").
        Returns (False, "not_found") if file missing.
        Returns (False, "mode_mismatch") on mismatch (actual mode is safe to include).
        Does NOT chmod — read stat only.
        """
        abs_path = self._wm.resolve_path(self._ws, rel_path)
        if not os.path.exists(abs_path):
            return False, "not_found"
        try:
            file_stat = os.stat(abs_path)
        except OSError:
            return False, "stat_error"
        mode_bits = file_stat.st_mode & 0o777
        actual_mode = oct(mode_bits)[2:]
        # Normalize: strip leading zeros for comparison ("0600" == "600")
        actual_norm = actual_mode.lstrip("0") or "0"
        expected_norm = expected_mode.lstrip("0") or "0"
        if actual_norm == expected_norm:
            return True, ""
        return False, f"expected={expected_mode},actual={actual_mode}"

    def no_residual_files(self) -> tuple[bool, str]:
        """Check that the workspace is removed or empty.

        Does not accept a path argument — always checks the entire workspace root.
        Returns (True, "") if workspace directory does not exist (cleanup succeeded).
        Returns (True, "") if workspace exists but contains no files.
        Returns (False, safe_summary) if residual files found.
        Never scans outside the workspace root.
        """
        workspace = self._ws.workspace_path
        if not os.path.exists(workspace):
            return True, ""
        files: list[str] = []
        for root, _dirs, fnames in os.walk(workspace, followlinks=False):
            for fname in fnames:
                abs_f = os.path.join(root, fname)
                files.append(os.path.relpath(abs_f, workspace))
        if not files:
            return True, ""
        sample = ", ".join(files[:_RESIDUAL_SAMPLE_MAX])
        return False, f"{len(files)}_files_remain:{sample}"


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

        Returns a VerifyResult.  On error, passed=False with a stable failure_reason.
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
                # Do NOT include exc.args in the result — host path may be in the message
                return _fail(FailureReason.LINUX_PATH_ESCAPE, f"path_escape:{exc.reason}")

        try:
            if vtype == LinuxVerifyType.LINUX_FILE_EXISTS:
                passed, reason = adapter.file_exists(rel_path)
                if passed:
                    return _pass(f"File '{rel_path}' exists in workspace.")
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
                passed, reason = adapter.file_mode_matches(rel_path, expected_mode)
                if passed:
                    return _pass(f"File '{rel_path}' has expected mode {expected_mode}.")
                if "not_found" in reason:
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
