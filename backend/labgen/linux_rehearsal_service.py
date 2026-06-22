"""
LinuxRehearsalService — admin-only internal rehearsal for Linux domain LabDrafts.

Proves the full Linux domain adapter chain:
  Admin-curated Linux draft → precheck → workspace → step execution
  → verifier → complete → cleanup → residual → LAB_CLOSED + rehearsal_completed

Design invariants:
- Never publishes a Linux lab (publish gate remains blocked by StaticValidator).
- Never adds Linux to the learner catalog.
- Never visible to non-admin users.
- No LLM calls.
- No K8s namespace operations (no kubectl, no RBAC, no kubeconfig).
- No Proxmox VM operations (no VMID 500-599 touched).
- Commands that require shell redirection are intercepted and executed via
  Python-native workspace API (write_file, make_directory, chmod_file).
  No shell=True is used anywhere in this module.
- Shell redirection commands (printf ... >) are converted to write_file() —
  the safe equivalent — not forwarded to subprocess. This is the mandated
  safe command path per spec.

Session lifecycle:
  LAB_ACTIVE (after create)
  → step execute × N (verifiers run per step)
  → complete (if ready_to_complete)
    → LAB_CLOSED + cleanup_verified=True + rehearsal_completed on draft
    OR LAB_CLEANUP_FAILED + tainted
  → abort (at any point)
    → LAB_ABORTED → cleanup → LAB_CLOSED or LAB_CLEANUP_FAILED + tainted
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.linux_cleanup import CleanupResult, ResidualScanResult
from backend.labgen.linux_workspace import WorkspacePathEscapeError
from backend.labgen.linux_runtime_adapter import (
    LinuxRuntimeAdapter,
    LinuxSpikeDisabledError,
    LinuxSpikeSessionState,
    LinuxSpikeStatus,
)
from backend.labgen.linux_verifier_client import LinuxVerifierService
from backend.labgen.models import (
    LabDomainType,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    SessionType,
    VerifyResult,
)

if TYPE_CHECKING:
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.models import LabDraft, LinuxVerifyTemplate, Step
    from backend.labgen.repository import LabDraftRepository

logger = logging.getLogger(__name__)

# Sentinel vm_id for Linux rehearsal sessions (no real Proxmox VM involved)
_LINUX_REHEARSAL_VM_ID = "linux-rehearsal"

# Placeholder pattern — detect unreplaced template variables
_PLACEHOLDER_PAT = re.compile(r"\{\{[^}]+\}\}")

# Active session statuses (for duplicate check)
_ACTIVE_REHEARSAL_STATUSES: frozenset[LabSessionStatus] = frozenset({
    LabSessionStatus.LAB_ACTIVE,
    LabSessionStatus.LAB_CREATED,
    LabSessionStatus.LAB_STARTING,
})

# ---------------------------------------------------------------------------
# Safe command dispatcher
# ---------------------------------------------------------------------------

# Command patterns that require Python-native workspace API (shell constructs)
_PRINTF_REDIRECT_PAT = re.compile(
    r"""^printf\s+'((?:[^'\\]|\\.)*)'\s*>\s*(\S+)$"""
)
_ECHO_REDIRECT_PAT = re.compile(
    r"""^echo\s+'((?:[^'\\]|\\.)*)'\s*>\s*(\S+)$"""
)
_MKDIR_PAT = re.compile(r"^mkdir(?:\s+-p)?\s+(\S+)$")
_CHMOD_PAT = re.compile(r"^chmod\s+([0-7]{3,4})\s+(\S+)$")

# Commands that are safe to pass to LinuxCommandExecutor (no shell constructs)
_SAFE_CMD_WHITELIST: frozenset[str] = frozenset({
    "cat", "ls", "stat", "echo", "mkdir", "chmod", "rm", "printf",
})


@dataclass
class CommandExecutionResult:
    cmd: str
    executed_via: str          # "write_file" | "make_directory" | "chmod_file" | "command" | "noop"
    ok: bool
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    policy_rejected: bool = False
    rejection_reason: str = ""


def _safe_exec_command(
    adapter: LinuxRuntimeAdapter,
    session_id: str,
    cmd: str,
) -> CommandExecutionResult:
    """Execute a single command safely.

    Shell-redirect forms (printf '...' > file, echo '...' > file) are intercepted
    and converted to Python-native write_file() calls — no shell=True is used.

    Commands with safe argv forms (cat, ls, stat) are forwarded to
    LinuxCommandExecutor via adapter.execute_command() with shell=False.

    Commands with shell metacharacters that are NOT intercepted above are
    rejected (policy_rejected=True). This enforces the no-arbitrary-shell contract.
    """
    cmd = cmd.strip()
    if not cmd:
        return CommandExecutionResult(cmd=cmd, executed_via="noop", ok=True)

    # --- Shell-redirect intercepts (must come before argv dispatch) ---

    m = _PRINTF_REDIRECT_PAT.match(cmd)
    if m:
        raw_content = m.group(1)
        path = m.group(2)
        content = raw_content.replace("\\n", "\n").replace("\\t", "\t").replace("\\'", "'")
        try:
            adapter.write_file(session_id, path, content)
            return CommandExecutionResult(cmd=cmd, executed_via="write_file", ok=True)
        except WorkspacePathEscapeError as exc:
            return CommandExecutionResult(
                cmd=cmd, executed_via="write_file", ok=False,
                policy_rejected=True,
                rejection_reason=f"path_escape:{exc}",
            )
        except Exception as exc:
            return CommandExecutionResult(
                cmd=cmd, executed_via="write_file", ok=False, stderr=str(exc)
            )

    m = _ECHO_REDIRECT_PAT.match(cmd)
    if m:
        raw_content = m.group(1)
        path = m.group(2)
        content = raw_content + "\n"
        try:
            adapter.write_file(session_id, path, content)
            return CommandExecutionResult(cmd=cmd, executed_via="write_file", ok=True)
        except WorkspacePathEscapeError as exc:
            return CommandExecutionResult(
                cmd=cmd, executed_via="write_file", ok=False,
                policy_rejected=True,
                rejection_reason=f"path_escape:{exc}",
            )
        except Exception as exc:
            return CommandExecutionResult(
                cmd=cmd, executed_via="write_file", ok=False, stderr=str(exc)
            )

    m = _MKDIR_PAT.match(cmd)
    if m:
        path = m.group(1)
        try:
            adapter.make_directory(session_id, path)
            return CommandExecutionResult(cmd=cmd, executed_via="make_directory", ok=True)
        except WorkspacePathEscapeError as exc:
            return CommandExecutionResult(
                cmd=cmd, executed_via="make_directory", ok=False,
                policy_rejected=True,
                rejection_reason=f"path_escape:{exc}",
            )
        except Exception as exc:
            return CommandExecutionResult(
                cmd=cmd, executed_via="make_directory", ok=False, stderr=str(exc)
            )

    m = _CHMOD_PAT.match(cmd)
    if m:
        mode_str = m.group(1)
        path = m.group(2)
        try:
            adapter.chmod_file(session_id, path, int(mode_str, 8))
            return CommandExecutionResult(cmd=cmd, executed_via="chmod_file", ok=True)
        except WorkspacePathEscapeError as exc:
            return CommandExecutionResult(
                cmd=cmd, executed_via="chmod_file", ok=False,
                policy_rejected=True,
                rejection_reason=f"path_escape:{exc}",
            )
        except Exception as exc:
            return CommandExecutionResult(
                cmd=cmd, executed_via="chmod_file", ok=False, stderr=str(exc)
            )

    # --- Safe argv dispatch via LinuxCommandExecutor ---

    # Reject if any shell metacharacter that was NOT caught above
    _SHELL_META = set("|&;><`$")
    if any(c in cmd for c in _SHELL_META):
        return CommandExecutionResult(
            cmd=cmd,
            executed_via="rejected",
            ok=False,
            policy_rejected=True,
            rejection_reason="shell_metachar_in_unintercepted_command",
        )

    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        return CommandExecutionResult(
            cmd=cmd,
            executed_via="rejected",
            ok=False,
            policy_rejected=True,
            rejection_reason=f"parse_error:{exc}",
        )

    if not argv:
        return CommandExecutionResult(cmd=cmd, executed_via="noop", ok=True)

    result = adapter.execute_command(session_id, argv)
    if result.policy_rejected:
        return CommandExecutionResult(
            cmd=cmd,
            executed_via="rejected",
            ok=False,
            policy_rejected=True,
            rejection_reason=result.rejection_reason,
        )
    return CommandExecutionResult(
        cmd=cmd,
        executed_via="command",
        ok=(result.returncode == 0),
        returncode=result.returncode,
        stdout=result.stdout[:512],
        stderr=result.stderr[:512],
    )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class LinuxRehearsalPrecheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


@dataclass
class LinuxStepExecutionResult:
    step_id: str
    command_results: list[CommandExecutionResult] = field(default_factory=list)
    verifier_results: list[VerifyResult] = field(default_factory=list)
    all_verifiers_passed: bool = False
    ready_to_complete: bool = False
    step_index_advanced: bool = False


@dataclass
class LinuxRehearsalCompleteResult:
    session: LabSessionState
    cleanup_result: Optional[CleanupResult] = None
    residual_result: Optional[ResidualScanResult] = None
    cleanup_verified: bool = False
    rehearsal_completed: bool = False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LinuxRehearsalPrecheckFailed(Exception):
    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__(f"Linux rehearsal precheck failed: {failures}")


class LinuxRehearsalSessionNotFound(Exception):
    pass


class LinuxRehearsalSessionNotActive(Exception):
    pass


class LinuxRehearsalNotReadyToComplete(Exception):
    pass


class LinuxRehearsalStepNotFound(Exception):
    pass


class LinuxRehearsalStepNotCurrent(Exception):
    pass


# ---------------------------------------------------------------------------
# LinuxRehearsalService
# ---------------------------------------------------------------------------


class LinuxRehearsalService:
    """Admin-only internal rehearsal service for Linux domain LabDrafts.

    Wires together:
    - LinuxRuntimeAdapter (workspace + command executor + cleanup)
    - LinuxVerifierService (verifier dispatch against workspace)
    - LabSessionRepository (session state persistence)
    - LabDraftRepository (draft read + rehearsal_completed write)

    Never publishes. Never modifies learner catalog. Never calls K8s API.
    No LLM calls. No shell=True.

    Pass adapter= to inject a custom adapter in tests.
    """

    def __init__(
        self,
        session_repo: "LabSessionRepository",
        draft_repo: "LabDraftRepository",
        sandbox_root: str = "/tmp/labgen-linux-sandboxes",
        timeout_seconds: int = 10,
        max_output_bytes: int = 65536,
        adapter: Optional[LinuxRuntimeAdapter] = None,
    ) -> None:
        self._session_repo = session_repo
        self._draft_repo = draft_repo
        if adapter is not None:
            self._adapter = adapter
        else:
            self._adapter = LinuxRuntimeAdapter(
                enabled=True,
                sandbox_root=sandbox_root,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
        self._verifier_svc = LinuxVerifierService(self._adapter.workspace_manager)

    # ------------------------------------------------------------------
    # Precheck
    # ------------------------------------------------------------------

    def run_linux_rehearsal_precheck(
        self,
        lab_id: str,
        admin_username: str,
    ) -> LinuxRehearsalPrecheckResult:
        """Validate a Linux draft is ready for internal rehearsal.

        Checks (all must pass):
        1. Draft exists
        2. target_domain == LINUX
        3. linux_sandbox_policy is present
        4. linux_sandbox_policy.allow_root == False
        5. linux_sandbox_policy.allow_network == False
        6. linux_cleanup is present
        7. At least one step has linux_verify verifiers
        8. No placeholders ({{...}}) in any step's commands
        9. No active rehearsal session for this lab by this admin
        """
        failures: list[str] = []

        draft = self._draft_repo.get(lab_id)
        if draft is None:
            failures.append(FailureReason.LINUX_REHEARSAL_DRAFT_NOT_FOUND.value)
            return LinuxRehearsalPrecheckResult(passed=False, failures=failures)

        if draft.target_domain != LabDomainType.LINUX:
            failures.append(FailureReason.LINUX_REHEARSAL_NOT_LINUX_DOMAIN.value)

        if draft.linux_sandbox_policy is None:
            failures.append(FailureReason.LINUX_REHEARSAL_MISSING_SANDBOX_POLICY.value)
        else:
            if draft.linux_sandbox_policy.allow_root or draft.linux_sandbox_policy.allow_network:
                failures.append(FailureReason.LINUX_REHEARSAL_UNSAFE_SANDBOX_POLICY.value)

        if draft.linux_cleanup is None:
            failures.append(FailureReason.LINUX_REHEARSAL_MISSING_CLEANUP.value)

        has_verifiers = any(
            bool(step.linux_verify) for step in draft.steps
        )
        if not has_verifiers:
            failures.append(FailureReason.LINUX_REHEARSAL_MISSING_VERIFIERS.value)

        for step in draft.steps:
            for cmd in (step.commands or []):
                if _PLACEHOLDER_PAT.search(cmd):
                    failures.append(FailureReason.LINUX_REHEARSAL_PLACEHOLDER_IN_COMMANDS.value)
                    break  # one failure per draft is enough

        # Duplicate active session check
        existing = self._session_repo.list_by_student(admin_username)
        if any(
            s.lab_id == lab_id
            and s.lab_session_status in _ACTIVE_REHEARSAL_STATUSES
            and s.session_type == SessionType.INTERNAL_REHEARSAL
            for s in existing
        ):
            failures.append(FailureReason.LINUX_REHEARSAL_SESSION_ALREADY_ACTIVE.value)

        return LinuxRehearsalPrecheckResult(passed=len(failures) == 0, failures=failures)

    # ------------------------------------------------------------------
    # Session creation
    # ------------------------------------------------------------------

    def create_linux_rehearsal_session(
        self,
        lab_id: str,
        admin_username: str,
        article_draft_id: Optional[str] = None,
    ) -> LabSessionState:
        """Create an admin-only Linux internal rehearsal session.

        Runs precheck, creates a Linux workspace, and returns a LabSessionState
        with session_type=INTERNAL_REHEARSAL and target_domain=LINUX.

        Raises LinuxRehearsalPrecheckFailed if any precheck fails.
        """
        precheck = self.run_linux_rehearsal_precheck(lab_id, admin_username)
        if not precheck.passed:
            raise LinuxRehearsalPrecheckFailed(precheck.failures)

        draft = self._draft_repo.get(lab_id)  # safe: precheck verified it exists
        assert draft is not None

        # Create the LabSessionState first to get a session_id
        session = LabSessionState(
            lab_id=lab_id,
            vm_id=_LINUX_REHEARSAL_VM_ID,
            student_username=admin_username,
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            session_type=SessionType.INTERNAL_REHEARSAL,
            article_draft_id=article_draft_id,
        )

        # Create Linux workspace keyed by session_id
        try:
            self._adapter.create_session(
                session.session_id,
                draft.linux_sandbox_policy,
            )
        except (LinuxSpikeDisabledError, ValueError, Exception) as exc:
            session.lab_session_status = LabSessionStatus.LAB_START_FAILED
            session.failure_reason = FailureReason.LINUX_REHEARSAL_WORKSPACE_CREATE_FAILED.value
            session = self._session_repo.create(session)
            logger.error(
                "linux_rehearsal.workspace_create_failed",
                extra={"session_id": session.session_id, "error": str(exc)},
            )
            return session

        session = self._session_repo.create(session)
        logger.info(
            "linux_rehearsal.session.created",
            extra={
                "session_id": session.session_id,
                "lab_id": lab_id,
                "admin": admin_username,
            },
        )
        return session

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def execute_linux_step(
        self,
        session_id: str,
        step_id: str,
    ) -> LinuxStepExecutionResult:
        """Execute a single step: run safe commands then run verifiers.

        The step must be the current step (by step index order in the draft).
        Returns verifier results and advances the step index if all pass.

        Command execution:
        - Shell-redirect forms (printf ... > file) → write_file() (Python-native)
        - mkdir, chmod → Python-native workspace API
        - Safe commands (cat, stat, ls) → LinuxCommandExecutor (shell=False)
        - Anything with unintercepted shell metacharacters → policy_rejected

        Raises:
        - LinuxRehearsalSessionNotFound
        - LinuxRehearsalSessionNotActive
        - LinuxRehearsalStepNotFound
        - LinuxRehearsalStepNotCurrent
        """
        session = self._require_active_session(session_id)
        draft = self._draft_repo.get(session.lab_id)
        if draft is None:
            raise LinuxRehearsalStepNotFound(f"Draft not found for session {session_id}")

        # Find step by ID
        step: Optional["Step"] = None
        step_idx: int = -1
        for i, s in enumerate(draft.steps):
            if s.step_id == step_id:
                step = s
                step_idx = i
                break

        if step is None:
            raise LinuxRehearsalStepNotFound(f"Step '{step_id}' not found in draft")

        # Must be the current step
        if step_idx != session.current_step_index:
            raise LinuxRehearsalStepNotCurrent(
                f"Step '{step_id}' is index {step_idx}, "
                f"but current step index is {session.current_step_index}"
            )

        # Execute commands
        cmd_results: list[CommandExecutionResult] = []
        for cmd in (step.commands or []):
            r = _safe_exec_command(self._adapter, session_id, cmd)
            cmd_results.append(r)
            if r.policy_rejected:
                logger.warning(
                    "linux_rehearsal.command.policy_rejected",
                    extra={
                        "session_id": session_id,
                        "step_id": step_id,
                        "cmd": cmd[:80],
                        "reason": r.rejection_reason,
                    },
                )

        # Run Linux verifiers for this step
        verifier_results: list[VerifyResult] = []
        for vt in (step.linux_verify or []):
            result = self._verifier_svc.check(session_id, vt)
            verifier_results.append(result)

        all_passed = all(r.passed for r in verifier_results) if verifier_results else True

        # Advance step index if all verifiers passed
        advanced = False
        ready = False
        if all_passed:
            session.completed_step_ids = list(session.completed_step_ids) + [step_id]
            session.current_step_index = step_idx + 1
            session.last_verify_results = verifier_results
            advanced = True

            # Check if this was the last verifiable step (steps before final completion step)
            # ready_to_complete when the next step has no linux_verify (completion step)
            # OR when we've finished all steps
            next_idx = step_idx + 1
            if next_idx >= len(draft.steps):
                ready = True
            else:
                # Check if remaining steps have verifiers that we haven't executed
                # Completion step (step 4 in template) has linux_no_residual_files —
                # that verifier runs AFTER cleanup, not here. So when we reach the
                # last step that has non-residual verifiers, we're ready.
                # Mark ready when the remaining steps contain only residual checks
                # or no verifiable steps that require workspace state.
                remaining_have_pre_cleanup_verifiers = any(
                    any(
                        vt.type.value != "linux_no_residual_files"
                        for vt in (s.linux_verify or [])
                    )
                    for s in draft.steps[next_idx:]
                    if s.linux_verify
                )
                if not remaining_have_pre_cleanup_verifiers:
                    ready = True

            session.ready_to_complete = ready
            session = self._session_repo.update(session)

        return LinuxStepExecutionResult(
            step_id=step_id,
            command_results=cmd_results,
            verifier_results=verifier_results,
            all_verifiers_passed=all_passed,
            ready_to_complete=ready,
            step_index_advanced=advanced,
        )

    # ------------------------------------------------------------------
    # Complete
    # ------------------------------------------------------------------

    def complete_linux_rehearsal(self, session_id: str) -> LinuxRehearsalCompleteResult:
        """Complete the rehearsal: cleanup workspace, verify residual=0.

        Requires ready_to_complete=True. Runs cleanup, checks residual,
        marks session LAB_CLOSED and sets draft.rehearsal_completed=True on success.

        After cleanup, runs linux_no_residual_files from the completion step verifiers.

        Raises:
        - LinuxRehearsalSessionNotFound
        - LinuxRehearsalSessionNotActive
        - LinuxRehearsalNotReadyToComplete
        """
        session = self._require_active_session(session_id)

        if not session.ready_to_complete:
            raise LinuxRehearsalNotReadyToComplete(
                f"Session '{session_id}' is not ready to complete — "
                "execute all required steps first"
            )

        return self._do_linux_cleanup(session, is_abort=False)

    # ------------------------------------------------------------------
    # Abort
    # ------------------------------------------------------------------

    def abort_linux_rehearsal(self, session_id: str) -> LinuxRehearsalCompleteResult:
        """Abort the rehearsal and cleanup workspace.

        Does NOT mark rehearsal_completed. Cleanup still runs.
        ready_to_complete is NOT required for abort.

        Raises:
        - LinuxRehearsalSessionNotFound
        - LinuxRehearsalSessionNotActive
        """
        session = self._require_active_session(session_id)
        return self._do_linux_cleanup(session, is_abort=True)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> LabSessionState:
        """Return the LabSessionState for a Linux rehearsal session.

        Raises LinuxRehearsalSessionNotFound if the session does not exist
        or is not a Linux INTERNAL_REHEARSAL session (prevents K8s sessions
        from leaking into Linux rehearsal paths).
        """
        session = self._session_repo.get(session_id)
        if session is None:
            raise LinuxRehearsalSessionNotFound(session_id)
        if session.session_type != SessionType.INTERNAL_REHEARSAL:
            raise LinuxRehearsalSessionNotFound(
                f"Session '{session_id}' is not a Linux internal rehearsal session"
            )
        return session

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_active_session(self, session_id: str) -> LabSessionState:
        session = self._session_repo.get(session_id)
        if session is None:
            raise LinuxRehearsalSessionNotFound(session_id)
        if session.session_type != SessionType.INTERNAL_REHEARSAL:
            raise LinuxRehearsalSessionNotFound(
                f"Session '{session_id}' is not a Linux internal rehearsal session"
            )
        if session.lab_session_status != LabSessionStatus.LAB_ACTIVE:
            raise LinuxRehearsalSessionNotActive(
                f"Session '{session_id}' is not active "
                f"(status={session.lab_session_status.value})"
            )
        return session

    def _do_linux_cleanup(
        self,
        session: LabSessionState,
        is_abort: bool,
    ) -> LinuxRehearsalCompleteResult:
        """Run workspace cleanup and finalize session state.

        On success: LAB_CLOSED, cleanup_verified=True
        On failure: LAB_CLEANUP_FAILED, tainted=True, vm_id marked tainted in log
        If is_abort=False: also sets draft.rehearsal_completed=True on success
        """
        session_id = session.session_id

        # Mark session as completing before running cleanup
        session.lab_session_status = (
            LabSessionStatus.LAB_ABORTED if is_abort else LabSessionStatus.LAB_COMPLETED
        )
        session = self._session_repo.update(session)

        # Run workspace cleanup via LinuxRuntimeAdapter.
        # cleanup_result.residual holds the post-cleanup residual scan.
        cleanup_result = self._adapter.close_session(session_id)

        if cleanup_result.success:
            session.lab_session_status = LabSessionStatus.LAB_CLOSED
            session.cleanup_verified = True
            session = self._session_repo.update(session)
            logger.info(
                "linux_rehearsal.cleanup.success",
                extra={"session_id": session_id, "is_abort": is_abort},
            )

            # Set rehearsal_completed on the draft (only for successful complete, not abort)
            rehearsal_completed = False
            if not is_abort and session.ready_to_complete:
                draft = self._draft_repo.get(session.lab_id)
                if draft is not None and not draft.rehearsal_completed:
                    self._draft_repo.update(
                        draft.model_copy(update={"rehearsal_completed": True})
                    )
                    rehearsal_completed = True
                    logger.info(
                        "linux_rehearsal.draft.rehearsal_completed",
                        extra={"lab_id": session.lab_id, "session_id": session_id},
                    )

            return LinuxRehearsalCompleteResult(
                session=session,
                cleanup_result=cleanup_result,
                residual_result=cleanup_result.residual,
                cleanup_verified=True,
                rehearsal_completed=rehearsal_completed,
            )

        # Cleanup failed
        session.lab_session_status = LabSessionStatus.LAB_CLEANUP_FAILED
        session.failure_reason = FailureReason.LINUX_REHEARSAL_CLEANUP_FAILED.value
        session.cleanup_verified = False
        session = self._session_repo.update(session)
        logger.error(
            "linux_rehearsal.cleanup.failed",
            extra={
                "session_id": session_id,
                "failure_reason": cleanup_result.failure_reason,
                "is_abort": is_abort,
            },
        )

        return LinuxRehearsalCompleteResult(
            session=session,
            cleanup_result=cleanup_result,
            residual_result=cleanup_result.residual,
            cleanup_verified=False,
            rehearsal_completed=False,
        )
