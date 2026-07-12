"""
Constrained kubectl command executor for learner lab sessions.

Security model:
  - Only kubectl commands are accepted (no shell, no other binaries).
  - Blocked subcommands: exec, port-forward, proxy, attach, cp, debug, run, plugin.
  - Blocked flags: --all-namespaces / -A (cross-namespace access).
  - Blocked output formats for secrets: -o yaml, -o json (prevent data leak).
  - All -o yaml / -o json output is blocked for consistency.
  - Blocked commands: config view, create token, auth can-i, get/describe/delete
    cluster-scoped resources (namespaces, nodes, clusterroles, etc.).
  - Command is parsed with shlex.split — never passed to shell (no injection).
  - --kubeconfig is always injected by the executor; user-supplied --kubeconfig is blocked.
  - -n / --namespace supplied by the user are silently stripped; the executor always
    injects its own --namespace, so user-supplied values are ignored regardless of target.
  - Max output: 64 KB (excess is truncated).
  - Max command duration: configurable timeout (default 30s).

Audit:
  - Every execute() call logs session_id, username, namespace, command,
    exit_code, and elapsed time.
  - Blocked commands are logged but the actual token/kubeconfig path is not.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB
DEFAULT_TIMEOUT_SECONDS = 30

# Subcommands that could escape the namespace or expose host internals
_BLOCKED_SUBCOMMANDS: frozenset[str] = frozenset({
    "exec", "port-forward", "proxy", "attach", "cp", "debug", "run", "plugin",
})

# Raw patterns applied to the full command string (case-insensitive)
_BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    # config subcommand would show the kubeconfig
    re.compile(r"^kubectl\s+config\b", re.IGNORECASE),
    # SA token creation
    re.compile(r"^kubectl\s+create\s+token\b", re.IGNORECASE),
    # auth subcommand
    re.compile(r"^kubectl\s+auth\b", re.IGNORECASE),
    # cluster-scoped resources the SA has no RBAC for (defence-in-depth)
    # Match both singular (namespace) and plural (namespaces), plus abbreviated (ns)
    re.compile(r"^kubectl\s+(?:get|describe|delete|edit)\s+(?:namespaces?|ns|nodes?|clusterroles?|clusterrolebindings?|persistentvolumes?|storageclasses?)\b", re.IGNORECASE),
    # all-namespaces flag
    re.compile(r"\s--all-namespaces\b", re.IGNORECASE),
    re.compile(r"\s+-A\b"),
    # apply/replace from a URL (arbitrary resource creation, possible SSRF) —
    # covers both subcommands, since "replace -f <url>" is equally capable of
    # fetching and applying an arbitrary manifest.
    re.compile(r"\b(?:apply|replace)\b.*https?://"),
    # Override kubeconfig (would break sandboxing); -n/--namespace is stripped in execute()
    re.compile(r"\s--kubeconfig\b"),
]

# Only these output formats may be used; all others (yaml, json, jsonpath, go-template, …)
# risk exposing secret values. Checked against parsed tokens, not raw string, to prevent
# bypasses like -o=yaml, -ojson, or --output yaml (space variant).
_ALLOWED_OUTPUT_FORMATS: frozenset[str] = frozenset({"wide", "name"})

# Service type values that must never be reachable: NodePort/LoadBalancer bind
# a port on every cluster node's host network, bypassing namespace isolation
# entirely; ExternalName is a DNS-based SSRF vector. Only ClusterIP is
# permitted. These are the only two escalation vectors left after
# LEARNER_ALLOWED_PERMISSIONS deliberately withholds update/patch on services
# (see learner_credentials.py) — RBAC itself rejects any patch/edit/replace
# attempt at the K8s API layer regardless of CLI syntax, which is what
# actually closes off the patch-based path after five rounds of safety
# review kept finding new bypasses trying to block it via string parsing
# (see CHANGELOG for the full history). Only the create-time forms need
# blocking here because create is still granted.
_BLOCKED_SERVICE_TYPES: frozenset[str] = frozenset({"nodeport", "loadbalancer", "externalname"})


def _check_service_type_escalation(parts: list[str]) -> tuple[bool, str]:
    """Token-based check (not raw-string regex) for the "create service
    <type>" positional form and the "expose --type=" flag form. Must operate
    on shlex-parsed tokens, not the unparsed command string — a regex using
    \\s/\\b word boundaries on the raw string can be defeated by simply
    quoting the keyword (e.g. create service "nodeport" ...): shlex strips
    the quotes uniformly before the value ever reaches kubectl, but the raw
    string still has them, breaking the boundary match (found in
    sixth-round safety review — this replaced an earlier regex-based
    version that had exactly this bypass)."""
    if len(parts) >= 4 and parts[1] == "create" and parts[2] == "service":
        if parts[3].lower() in _BLOCKED_SERVICE_TYPES:
            return False, "Only ClusterIP services may be created in this lab environment."

    i = 0
    while i < len(parts):
        token = parts[i]
        value: Optional[str] = None
        if token == "--type":
            if i + 1 < len(parts):
                value = parts[i + 1].lower()
        elif token.startswith("--type="):
            value = token[len("--type="):].lower()
        if value in _BLOCKED_SERVICE_TYPES:
            return False, "Only ClusterIP services may be created in this lab environment."
        i += 1
    return True, ""


def _has_raw_flag(parts: list[str]) -> bool:
    """Token-based check (not raw-string regex, same quoting-bypass
    reasoning as _check_service_type_escalation) for --raw, which sends an
    unformatted HTTP request straight to the API server — bypassing the -o
    yaml/json block entirely (that check only inspects -o/--output tokens,
    which --raw doesn't use). A learner could use
    `kubectl get --raw /api/v1/namespaces/<ns>/secrets` to dump every Secret
    in their namespace in full, defeating the whole "no -o yaml/json"
    secret-protection model. Pre-existing gap (not introduced by the
    services/endpoints RBAC change), found and fixed in the same review
    pass since it's a live secret-exposure hole."""
    for token in parts:
        if token == "--raw" or token.startswith("--raw="):
            return True
    return False


def _strip_namespace_flags(parts: list[str]) -> list[str]:
    """Remove -n / --namespace flags so the executor's own --namespace injection wins."""
    result: list[str] = []
    i = 0
    while i < len(parts):
        token = parts[i]
        if token == "-n" or token == "--namespace":
            i += 2  # skip flag and its value
            continue
        if token.startswith("-n") and len(token) > 2 and not token.startswith("--"):
            # -nkube-system form
            i += 1
            continue
        if token.startswith("--namespace="):
            i += 1
            continue
        result.append(token)
        i += 1
    return result


def _check_output_format(parts: list[str]) -> tuple[bool, str]:
    """Return (allowed, reason) after checking every -o / --output token in the parsed args."""
    i = 0
    while i < len(parts):
        token = parts[i]
        fmt: Optional[str] = None

        if token in ("-o",):
            # -o <format>  (next token)
            if i + 1 < len(parts):
                fmt = parts[i + 1].lower()
        elif token.startswith("-o="):
            # -o=<format>
            fmt = token[3:].lower()
        elif token.startswith("-o") and len(token) > 2:
            # -oyaml  (no separator)
            fmt = token[2:].lower()
        elif token in ("--output",):
            # --output <format>  (next token)
            if i + 1 < len(parts):
                fmt = parts[i + 1].lower()
        elif token.startswith("--output="):
            # --output=<format>
            fmt = token[9:].lower()

        if fmt is not None and fmt not in _ALLOWED_OUTPUT_FORMATS:
            return False, (
                "This output format is not permitted in the lab environment. "
                "Use 'kubectl get <resource>' without -o / --output, "
                "or use -o wide or -o name."
            )
        i += 1
    return True, ""


@dataclass
class CommandResult:
    allowed: bool
    block_reason: Optional[str]  # set when allowed=False
    output: str                  # stdout+stderr from kubectl
    exit_code: int               # 0 on success, non-zero on error or block


def validate_command(cmd: str) -> tuple[bool, str]:
    """
    Return (allowed, reason).  reason is empty string when allowed=True.

    Validates that:
    1. The command starts with 'kubectl' (nothing else allowed).
    2. No blocked subcommand is the first arg after kubectl.
    3. No blocked pattern matches anywhere in the command string.
    """
    stripped = cmd.strip()
    if not stripped:
        return True, ""

    if not stripped.startswith("kubectl"):
        return False, "Only kubectl commands are allowed in this lab terminal."

    # Parse with shlex to get proper argument list
    try:
        parts = shlex.split(stripped)
    except ValueError as exc:
        return False, f"Cannot parse command: {exc}"

    # No global flag is permitted immediately after "kubectl" — every check
    # below (_BLOCKED_SUBCOMMANDS, _check_service_type_escalation, etc.)
    # assumes parts[1] is the subcommand. kubectl (via cobra/pflag) allows
    # global flags like --v=0 or --request-timeout anywhere, including
    # before the subcommand — inserting one there shifts every fixed-index
    # check by one or more positions and silently defeats it (e.g.
    # "kubectl --v=0 exec ..." would bypass the exec block below; found in
    # seventh-round safety review while fixing an equivalent bypass in the
    # Service-type-escalation check). No legitimate lab command needs a
    # global flag before the subcommand, so this is rejected outright rather
    # than attempting to enumerate and skip every possible global flag.
    if len(parts) >= 2 and parts[1].startswith("-"):
        return False, (
            "Global flags before the subcommand are not supported in this "
            "lab terminal. Start with 'kubectl <verb> ...'."
        )

    if len(parts) >= 2 and parts[1] in _BLOCKED_SUBCOMMANDS:
        return False, (
            f"The '{parts[1]}' subcommand is not available in this lab environment. "
            "Use kubectl create / get / describe / delete / apply."
        )

    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(stripped):
            return False, (
                "This command or option is not permitted in the lab environment. "
                "Tip: use 'kubectl get <resource>' without -o yaml/json, "
                "and stay within your lab namespace."
            )

    # Token-based output format check: catches -o=yaml, -ojson, -o jsonpath, --output yaml, etc.
    allowed, reason = _check_output_format(parts)
    if not allowed:
        return False, reason

    # Token-based checks (not raw-string regex — see their docstrings for why).
    allowed, reason = _check_service_type_escalation(parts)
    if not allowed:
        return False, reason

    if _has_raw_flag(parts):
        return False, "The --raw flag is not permitted in this lab environment."

    return True, ""


async def execute(
    cmd: str,
    kubeconfig_path: str,
    namespace: str,
    session_id: str,
    username: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CommandResult:
    """
    Validate and execute a kubectl command in the learner's namespace.

    The kubeconfig_path and namespace are always injected; any attempt by
    the user to override them is blocked by validate_command().

    Returns a CommandResult with output (stdout+stderr combined) and exit_code.
    """
    allowed, reason = validate_command(cmd)
    if not allowed:
        logger.info(
            "Learner command blocked: session=%s user=%s ns=%s reason=%s",
            session_id, username, namespace, reason,
        )
        return CommandResult(allowed=False, block_reason=reason, output="", exit_code=1)

    stripped = cmd.strip()
    if not stripped:
        return CommandResult(allowed=True, block_reason=None, output="", exit_code=0)

    # Parse args after 'kubectl'
    try:
        parts = shlex.split(stripped)
    except ValueError as exc:
        return CommandResult(allowed=True, block_reason=None, output=f"Parse error: {exc}\n", exit_code=1)

    kubectl_args = _strip_namespace_flags(parts[1:])  # strip user -n/--namespace; executor injects its own

    full_cmd = [
        "/usr/local/bin/kubectl",
        "--kubeconfig", kubeconfig_path,
        "--namespace", namespace,
        *kubectl_args,
    ]

    import time
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            raw_output, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning(
                "Learner command timed out: session=%s user=%s ns=%s cmd=%s",
                session_id, username, namespace, stripped,
            )
            return CommandResult(
                allowed=True,
                block_reason=None,
                output=f"Error: command timed out after {timeout_seconds}s\n",
                exit_code=124,
            )

        exit_code = proc.returncode or 0
        output = raw_output[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        if len(raw_output) > MAX_OUTPUT_BYTES:
            output += "\n[output truncated]\n"

        elapsed = time.monotonic() - t0
        logger.info(
            "Learner command: session=%s user=%s ns=%s exit=%d elapsed=%.2fs cmd=%s",
            session_id, username, namespace, exit_code, elapsed, stripped,
        )
        return CommandResult(allowed=True, block_reason=None, output=output, exit_code=exit_code)

    except FileNotFoundError:
        return CommandResult(
            allowed=True,
            block_reason=None,
            output="Error: kubectl binary not found. Contact the operator.\n",
            exit_code=127,
        )
    except Exception as exc:
        logger.error(
            "Learner command error: session=%s user=%s ns=%s exc=%s",
            session_id, username, namespace, exc,
        )
        return CommandResult(
            allowed=True,
            block_reason=None,
            output=f"Error: {exc}\n",
            exit_code=1,
        )
