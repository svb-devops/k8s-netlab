"""
LinuxCommandExecutor — controlled subprocess execution with strict command policy.

Design constraints:
- NEVER use shell=True.  All commands are passed as argument lists to subprocess.
- Command allowlist enforced BEFORE execution.
- All path arguments validated BEFORE execution (no absolute, no ..).
- Forbidden commands rejected with observable reason.
- max_output_bytes and timeout_seconds enforced.
- No network commands, no root-required commands, no shell metacharacters.

NOT production-ready: this is a spike-level executor demonstrating the policy layer.
Process isolation (cgroups, seccomp, namespaces) is NOT implemented.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Command policy constants
# ---------------------------------------------------------------------------

# Commands allowed in the spike.  First token of argv must be in this set.
ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "pwd",
    "ls",
    "mkdir",
    "touch",
    "echo",
    "cat",
    "chmod",
    "stat",
    "find",
    "rm",
    "cp",
    "mv",
    "wc",
    "head",
    "tail",
    "grep",
    "diff",
    "test",
    "[",
})

# Commands denied regardless of context.  Checked before allowlist to fail fast.
DENIED_COMMANDS: frozenset[str] = frozenset({
    "sudo", "su", "doas",
    "systemctl", "service", "init", "rc-service",
    "ssh", "scp", "sftp", "rsync",
    "curl", "wget", "nc", "netcat", "nmap", "ping", "traceroute",
    "apt", "apt-get", "dpkg", "yum", "dnf", "apk", "rpm",
    "pip", "pip3", "pip2",
    "python", "python3", "python2",  # prevents script execution
    "bash", "sh", "dash", "zsh", "ksh",
    "perl", "ruby", "node", "nodejs",
    "docker", "podman", "kubectl", "helm",
    "dd", "mkfs", "fdisk", "parted",
    "mount", "umount",
    "chroot",
    "useradd", "usermod", "userdel", "passwd",
    "crontab",
    "at",
    "kill", "killall", "pkill",
    "iptables", "nftables", "ip",
    "awk", "sed",  # not in allowlist but also explicitly denied
})

# Shell metacharacters that must NOT appear in any argument.
_SHELL_METACHARACTERS: frozenset[str] = frozenset({
    ";", "&", "|", "`", "$", "(", ")", "{", "}", "<", ">", "\\", "!",
    "\n", "\r",
})

# Forbidden absolute path prefixes — path args starting with these are rejected.
_FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    "/etc", "/root", "/var", "/proc", "/sys", "/dev", "/boot",
    "/usr", "/bin", "/sbin", "/lib", "/lib64", "/run",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CommandPolicyError(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class CommandDeniedError(CommandPolicyError):
    """Command is on the deny list."""


class CommandNotAllowedError(CommandPolicyError):
    """Command is not on the allowlist."""


class CommandPathEscapeError(CommandPolicyError):
    """A path argument would escape the workspace or access a forbidden path."""


class CommandMetacharError(CommandPolicyError):
    """A shell metacharacter was detected in an argument."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    argv: list[str]
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    policy_rejected: bool = False
    rejection_reason: str = ""


# ---------------------------------------------------------------------------
# LinuxCommandExecutor
# ---------------------------------------------------------------------------


class LinuxCommandExecutor:
    """Execute a single allowlisted command inside a workspace directory.

    Does NOT support shell redirection, piping, or command chaining.
    For file write operations, use LinuxWorkspaceManager.write_file() instead.
    """

    def __init__(
        self,
        timeout_seconds: int = 10,
        max_output_bytes: int = 65536,
        runner_uid: int | None = None,
        runner_gid: int | None = None,
    ) -> None:
        """
        runner_uid/runner_gid: if given, every learner command is executed as
        this UID/GID instead of inheriting the caller's own identity (see
        backend.labgen.linux_runner_identity.resolve_runner_identity — the
        production wiring in routes.get_linux_runtime_adapter() always passes
        a validated, non-root identity here). Left as None only for existing
        unit tests that exercise the command-policy layer and don't care about
        real privilege separation.
        """
        self._timeout = timeout_seconds
        self._max_output_bytes = max_output_bytes
        self._runner_uid = runner_uid
        self._runner_gid = runner_gid

    def execute(
        self,
        argv: list[str],
        workspace_root: str,
    ) -> ExecutionResult:
        """Run argv in workspace_root with strict policy enforcement.

        Returns ExecutionResult with policy_rejected=True and rejection_reason
        if any policy check fails (no exception raised — caller inspects result).
        """
        if not argv:
            return ExecutionResult(
                argv=argv,
                stdout="",
                stderr="",
                returncode=1,
                policy_rejected=True,
                rejection_reason="empty_argv",
            )

        # Policy checks — return early with rejection result (never raise to caller).
        reject = self._check_policy(argv, workspace_root)
        if reject:
            return reject

        # Execute — no shell, cwd=workspace_root, minimal env.
        # user/group/extra_groups/umask are native subprocess.Popen kwargs
        # (Python 3.9+), implemented in CPython without a Python-level
        # preexec_fn callback — deliberately avoided here because this method
        # runs inside a thread-pool executor (backend/labgen/lab_kubectl_ws.py
        # calls it via run_in_executor), and preexec_fn is documented as
        # unsafe to combine with multi-threaded callers (fork() only carries
        # over the calling thread, risking deadlock on any lock another
        # thread held at fork time).
        popen_kwargs: dict = {}
        if self._runner_uid is not None:
            popen_kwargs["user"] = self._runner_uid
            popen_kwargs["group"] = self._runner_gid
            popen_kwargs["extra_groups"] = []
            popen_kwargs["umask"] = 0o077
        try:
            proc = subprocess.run(
                argv,
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env={"PATH": "/usr/bin:/bin", "HOME": workspace_root},
                shell=False,
                **popen_kwargs,
            )
            stdout = proc.stdout[:self._max_output_bytes]
            stderr = proc.stderr[:self._max_output_bytes]
            return ExecutionResult(
                argv=argv,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                argv=argv,
                stdout="",
                stderr="",
                returncode=-1,
                timed_out=True,
            )
        except FileNotFoundError:
            return ExecutionResult(
                argv=argv,
                stdout="",
                stderr=f"command not found: {argv[0]}",
                returncode=127,
            )

    # ------------------------------------------------------------------
    # Policy validation
    # ------------------------------------------------------------------

    def _check_policy(
        self,
        argv: list[str],
        workspace_root: str,
    ) -> ExecutionResult | None:
        """Return a rejection ExecutionResult if any policy check fails, else None."""
        cmd = argv[0]

        # 1. Denied list takes priority.
        if cmd in DENIED_COMMANDS:
            return self._reject(argv, "command_denied", f"'{cmd}' is on the denied command list")

        # 2. Allowlist check.
        if cmd not in ALLOWED_COMMANDS:
            return self._reject(argv, "command_not_allowed", f"'{cmd}' is not in the allowed command list")

        # 3. Shell metacharacter check on all arguments.
        for arg in argv:
            for ch in _SHELL_METACHARACTERS:
                if ch in arg:
                    return self._reject(
                        argv,
                        "shell_metachar_detected",
                        f"Shell metacharacter '{ch}' detected in argument '{arg}'",
                    )

        # 4. Path argument validation for all args that look like paths.
        for arg in argv[1:]:
            path_reject = self._check_path_arg(arg, workspace_root)
            if path_reject:
                return self._reject(argv, path_reject[0], path_reject[1])

        return None

    def _check_path_arg(
        self, arg: str, workspace_root: str
    ) -> tuple[str, str] | None:
        """Return (reason, message) if the path arg is unsafe, else None."""
        # Skip option flags.
        if arg.startswith("-"):
            return None
        # Skip non-path-looking strings (digits, simple words).
        if "/" not in arg and ".." not in arg:
            return None

        # Absolute path check.
        if Path(arg).is_absolute():
            for forbidden in _FORBIDDEN_PATH_PREFIXES:
                if arg == forbidden or arg.startswith(forbidden + "/"):
                    return (
                        "forbidden_path",
                        f"Path '{arg}' accesses a forbidden system directory",
                    )
            # Absolute path not in forbidden list: still reject (must use relative paths).
            # Use trailing separator to prevent prefix confusion between sibling sessions.
            # e.g. /sandbox/session-abc-evil must not match /sandbox/session-abc + sep check.
            import os as _os
            workspace_with_sep = workspace_root.rstrip(_os.sep) + _os.sep
            if not (arg == workspace_root or arg.startswith(workspace_with_sep)):
                return (
                    "absolute_path_outside_workspace",
                    f"Absolute path '{arg}' is outside the workspace",
                )

        # Path traversal.
        if ".." in Path(arg).parts:
            return ("path_traversal", f"Path traversal '..' detected in argument '{arg}'")

        return None

    @staticmethod
    def _reject(argv: list[str], reason: str, message: str) -> ExecutionResult:
        return ExecutionResult(
            argv=argv,
            stdout="",
            stderr=message,
            returncode=1,
            policy_rejected=True,
            rejection_reason=reason,
        )
