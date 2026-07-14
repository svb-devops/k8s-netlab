"""
WebSocket handler for the learner kubectl terminal.

Security model:
  - Authenticated via session_token cookie (same mechanism as /ws/terminal/{vm_id}).
  - Only the session owner may open the terminal.
  - Session must be LAB_ACTIVE; connection is refused for any other state.
  - Session state is polled every SESSION_POLL_INTERVAL seconds; connection is
    closed gracefully if the session leaves LAB_ACTIVE.
  - K8s sessions: learner credentials (SA, Role, RoleBinding, kubeconfig) are
    created lazily on first connection and reclaimed on disconnect.
  - Linux sessions (vm_id='linux-sandbox'): commands execute locally in the
    workspace directory via LinuxRuntimeAdapter. Simple `>` output redirection
    is parsed before policy enforcement so the redirect operator never reaches
    the allowlist checker.
  - No raw kubeconfig content is sent to the client or logged.
  - Idle timeout: IDLE_TIMEOUT_SECONDS of inactivity closes the connection.

Protocol (JSON messages only):
  Client → Server:  {"type": "command", "cmd": "<command>"}
  Server → Client:
    {"type": "ready",   "namespace": "..." | null, "msg": "..."}
    {"type": "output",  "text": "...", "exit_code": 0}
    {"type": "blocked", "text": "reason"}
    {"type": "error",   "text": "reason"}
    {"type": "closed",  "reason": "session_ended|idle_timeout|auth_error|workspace_error|not_configured"}
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from backend import config
from backend.auth import auth_manager
from backend.labgen import kubectl_executor, learner_credentials
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.models import LabSessionStatus

if TYPE_CHECKING:
    from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter

logger = logging.getLogger(__name__)

SESSION_POLL_INTERVAL = 10      # seconds between session-state polls
IDLE_TIMEOUT_SECONDS = 600      # 10 minutes idle → disconnect
MAX_CMD_LENGTH = 2048           # bytes; longer input is silently truncated

# Sentinel vm_id for Linux learner sessions (matches lab_session_service.py)
LINUX_LEARNER_VM_SENTINEL = "linux-sandbox"

# Shell metacharacters that must not appear in a redirect target path
_REDIRECT_PATH_DANGEROUS: frozenset[str] = frozenset(';|&<>$`"\\{}()!*? \t\n\r')


def _parse_output_redirect(cmd_str: str) -> tuple[str, Optional[str]]:
    """Parse simple ``cmd > file`` output redirection from a command string.

    Returns ``(cmd_without_redirect, output_path)`` when a redirect is found,
    or ``(cmd_str, None)`` when there is no redirect or the redirect target
    looks unsafe (contains spaces or shell metacharacters).

    Only handles plain ``>`` (not ``>>``, ``2>``, ``&>``).  Deliberate
    simplicity — guided lab steps never need shell-level complexity here.
    """
    idx = cmd_str.find(' > ')
    if idx < 0:
        return cmd_str, None
    file_part = cmd_str[idx + 3:].strip()
    if not file_part or any(c in file_part for c in _REDIRECT_PATH_DANGEROUS):
        return cmd_str, None
    return cmd_str[:idx].strip(), file_part


def _run_linux_cmd(
    linux_adapter: "LinuxRuntimeAdapter",
    session_id: str,
    workspace_path: str,
    cmd_str: str,
) -> dict[str, Any]:
    """Execute one Linux command, handling ``>`` output redirection.

    Runs synchronously (called via ``run_in_executor``).

    Returns a dict:
      ``{"blocked": bool, "text": str, "exit_code": int, "block_reason": str}``
    """
    import shlex as _shlex

    cmd_part, output_file = _parse_output_redirect(cmd_str)

    try:
        argv = _shlex.split(cmd_part)
    except ValueError as exc:
        return {"blocked": True, "text": f"Parse error: {exc}", "exit_code": 1, "block_reason": "parse_error"}

    if not argv:
        return {"blocked": False, "text": "", "exit_code": 0, "block_reason": ""}

    result = linux_adapter.execute_command(session_id, argv)

    if result.policy_rejected:
        return {
            "blocked": True,
            "text": f"Command not allowed: {result.rejection_reason}",
            "exit_code": 1,
            "block_reason": result.rejection_reason,
        }

    if output_file is not None:
        workspace = Path(workspace_path).resolve()
        out_path = (workspace / output_file).resolve()
        try:
            out_path.relative_to(workspace)
        except ValueError:
            return {
                "blocked": True,
                "text": "Redirect target escapes workspace.",
                "exit_code": 1,
                "block_reason": "path_traversal",
            }
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(result.stdout)
        except OSError as exc:
            return {"blocked": False, "text": f"Write error: {exc}\n", "exit_code": 1, "block_reason": ""}
        return {"blocked": False, "text": result.stderr or "", "exit_code": result.returncode, "block_reason": ""}

    output = result.stdout
    if result.stderr:
        output += result.stderr
    if result.timed_out:
        output += "\n[Command timed out]\n"
    return {"blocked": False, "text": output, "exit_code": result.returncode, "block_reason": ""}


async def _send(ws: WebSocket, msg: dict) -> None:
    try:
        await ws.send_json(msg)
    except Exception:
        pass


async def _close(ws: WebSocket, reason: str) -> None:
    await _send(ws, {"type": "closed", "reason": reason})
    try:
        await ws.close(code=1000)
    except Exception:
        pass


async def lab_kubectl_websocket(
    websocket: WebSocket,
    session_id: str,
    session_repo: LabSessionRepository,
    linux_adapter: Optional["LinuxRuntimeAdapter"] = None,
) -> None:
    """
    WebSocket handler for the learner terminal (K8s and Linux sessions).

    Authentication and ownership checks are performed here (not by the caller).
    The WebSocket is accepted here so we can send structured error messages before closing.

    K8s sessions (vm_id != 'linux-sandbox') continue through the existing kubectl
    credential path.  Linux sessions are routed to _handle_linux_terminal().

    Args:
        websocket:     FastAPI WebSocket connection (not yet accepted).
        session_id:    Lab session ID from the URL path.
        session_repo:  Injected session repository (overridable in tests).
        linux_adapter: LinuxRuntimeAdapter singleton, or None if Linux not configured.
    """
    await websocket.accept()

    # ── Layer 1: require session_token cookie ──────────────────────────────
    session_token = websocket.cookies.get("session_token")
    if not session_token:
        logger.warning("lab_kubectl WS rejected: no session_token (session=%s)", session_id)
        await _close(websocket, "auth_error")
        return

    # ── Layer 2: verify session token ──────────────────────────────────────
    username = auth_manager.verify_session(session_token)
    if not username:
        logger.warning("lab_kubectl WS rejected: invalid/expired token (session=%s)", session_id)
        await _close(websocket, "auth_error")
        return

    # ── Layer 3: load lab session ──────────────────────────────────────────
    session = session_repo.get(session_id)
    if session is None:
        logger.warning("lab_kubectl WS rejected: session not found (session=%s user=%s)", session_id, username)
        await _close(websocket, "session_not_found")
        return

    # ── Layer 4: ownership check ───────────────────────────────────────────
    if session.student_username != username:
        logger.warning(
            "lab_kubectl WS rejected: ownership mismatch (session=%s owner=%s requester=%s)",
            session_id, session.student_username, username,
        )
        await _close(websocket, "auth_error")
        return

    # ── Layer 5: session must be LAB_ACTIVE ───────────────────────────────
    if session.lab_session_status != LabSessionStatus.LAB_ACTIVE:
        logger.info(
            "lab_kubectl WS rejected: session not active (session=%s status=%s user=%s)",
            session_id, session.lab_session_status, username,
        )
        await _close(websocket, "session_not_active")
        return

    # ── Linux learner session: route to Linux terminal ─────────────────────
    if session.vm_id == LINUX_LEARNER_VM_SENTINEL:
        if linux_adapter is None:
            logger.error(
                "linux terminal WS: adapter not configured (session=%s user=%s)",
                session_id, username,
            )
            await _send(websocket, {
                "type": "error",
                "text": "Linux terminal not available: runtime not configured.\n",
            })
            await _close(websocket, "not_configured")
            return
        await _handle_linux_terminal(websocket, session, session_id, username, session_repo, linux_adapter)
        return

    namespace: str = session.namespace or f"lab-{session_id}"
    platform_kubeconfig: str = config.LABGEN_K8S_PLATFORM_KUBECONFIG_PATH

    if not platform_kubeconfig:
        logger.error("lab_kubectl WS: LABGEN_K8S_PLATFORM_KUBECONFIG_PATH not configured")
        await _send(websocket, {"type": "error", "text": "Terminal not available: platform not configured.\n"})
        await _close(websocket, "not_configured")
        return

    # ── Create learner credentials (idempotent) ────────────────────────────
    kubeconfig_path: Optional[str] = None
    try:
        loop = asyncio.get_running_loop()
        kubeconfig_path = await loop.run_in_executor(
            None,
            lambda: learner_credentials.ensure_learner_credentials(
                session_id, namespace, platform_kubeconfig
            ),
        )
    except Exception as exc:
        logger.error(
            "lab_kubectl WS: failed to create learner credentials (session=%s ns=%s): %s",
            session_id, namespace, exc,
        )
        await _send(websocket, {"type": "error", "text": "Terminal setup failed. Contact the operator.\n"})
        await _close(websocket, "credential_error")
        return

    logger.info(
        "lab_kubectl WS: connection opened (session=%s user=%s ns=%s)",
        session_id, username, namespace,
    )

    # ── Send ready message ─────────────────────────────────────────────────
    # The security notice ("use this terminal for the current lab only, do not
    # enter real secrets") is a static HTML banner in labgen-session.html, not
    # part of this operational message — printing it into the terminal buffer
    # wrapped at the client's current column width and read as ragged/misaligned.
    await _send(websocket, {
        "type": "ready",
        "namespace": namespace,
        "msg": (
            f"Lab terminal ready. Namespace: {namespace}\n"
            "Use kubectl commands to complete your lab steps.\n"
        ),
    })

    # ── Command loop ───────────────────────────────────────────────────────
    import time as _time
    last_activity = _time.monotonic()

    try:
        while True:
            # Poll for incoming message.  SESSION_POLL_INTERVAL drives session-state
            # checks; idle timeout is tracked separately via last_activity.
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=SESSION_POLL_INTERVAL,
                )
                last_activity = _time.monotonic()
            except asyncio.TimeoutError:
                # Check idle timeout first
                if _time.monotonic() - last_activity > IDLE_TIMEOUT_SECONDS:
                    logger.info(
                        "lab_kubectl WS: idle timeout (session=%s user=%s)",
                        session_id, username,
                    )
                    await _send(websocket, {
                        "type": "error",
                        "text": f"Terminal disconnected after {IDLE_TIMEOUT_SECONDS}s of inactivity.\n",
                    })
                    await _close(websocket, "idle_timeout")
                    return

                # No message in SESSION_POLL_INTERVAL — check session state
                current = session_repo.get(session_id)
                if current is None or current.lab_session_status != LabSessionStatus.LAB_ACTIVE:
                    logger.info(
                        "lab_kubectl WS: session no longer active, closing (session=%s user=%s)",
                        session_id, username,
                    )
                    await _send(websocket, {
                        "type": "error",
                        "text": "Lab session has ended. Terminal disconnecting.\n",
                    })
                    await _close(websocket, "session_ended")
                    return
                continue  # session still active, keep waiting
            except (WebSocketDisconnect, ConnectionClosed):
                break

            # Parse message
            import json as _json
            try:
                msg = _json.loads(raw)
            except _json.JSONDecodeError:
                await _send(websocket, {"type": "error", "text": "Invalid message format.\n"})
                continue

            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type", "")

            if msg_type == "command":
                cmd = str(msg.get("cmd", ""))[:MAX_CMD_LENGTH].strip()
                if not cmd:
                    continue

                # Verify session still active before executing
                current = session_repo.get(session_id)
                if current is None or current.lab_session_status != LabSessionStatus.LAB_ACTIVE:
                    await _send(websocket, {
                        "type": "error",
                        "text": "Lab session is no longer active.\n",
                    })
                    await _close(websocket, "session_ended")
                    return

                result = await kubectl_executor.execute(
                    cmd=cmd,
                    kubeconfig_path=kubeconfig_path,
                    namespace=namespace,
                    session_id=session_id,
                    username=username,
                )

                if not result.allowed:
                    await _send(websocket, {
                        "type": "blocked",
                        "text": f"{result.block_reason}\n",
                    })
                else:
                    await _send(websocket, {
                        "type": "output",
                        "text": result.output,
                        "exit_code": result.exit_code,
                    })

            # Unknown message types are silently ignored

    except (WebSocketDisconnect, ConnectionClosed):
        pass
    except Exception as exc:
        logger.error(
            "lab_kubectl WS: unexpected error (session=%s user=%s): %s",
            session_id, username, exc,
        )
        await _send(websocket, {"type": "error", "text": f"Terminal error: {exc}\n"})

    finally:
        # Reclaim learner credentials; errors are logged but not re-raised.
        if kubeconfig_path is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: learner_credentials.reclaim_learner_credentials(
                        session_id, namespace, platform_kubeconfig
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "lab_kubectl WS: credential reclaim failed (session=%s): %s",
                    session_id, exc,
                )

        logger.info(
            "lab_kubectl WS: connection closed (session=%s user=%s ns=%s)",
            session_id, username, namespace,
        )
        try:
            await websocket.close()
        except Exception:
            pass


# ── Linux learner terminal ─────────────────────────────────────────────────────


async def _handle_linux_terminal(
    websocket: WebSocket,
    session: Any,
    session_id: str,
    username: str,
    session_repo: LabSessionRepository,
    linux_adapter: "LinuxRuntimeAdapter",
) -> None:
    """Handle a WebSocket terminal connection for a Linux learner session.

    Uses LinuxRuntimeAdapter.execute_command() for policy-enforced local execution
    inside the session workspace (``/tmp/labgen-linux-sandboxes/{session_id}/``).
    Simple ``>`` output redirection is handled before policy checks.
    """
    from backend.labgen.linux_runtime_adapter import LinuxSpikeSessionNotFoundError

    try:
        spike_session = linux_adapter.get_session(session_id)
        workspace_path = spike_session.workspace_path
    except LinuxSpikeSessionNotFoundError:
        logger.error(
            "linux terminal WS: workspace not found in adapter (session=%s user=%s) — "
            "service may have restarted after workspace was created",
            session_id, username,
        )
        await _send(websocket, {
            "type": "error",
            "text": "Linux workspace not found. The service may have restarted. Contact the operator.\n",
        })
        await _close(websocket, "workspace_error")
        return

    logger.info(
        "linux terminal WS: connection opened (session=%s user=%s workspace=%s)",
        session_id, username, workspace_path,
    )

    # See the equivalent kubectl 'ready' message above — same reasoning for
    # dropping the security notice line here.
    await _send(websocket, {
        "type": "ready",
        "namespace": None,
        "msg": (
            "Linux sandbox terminal ready.\n"
            "Use shell commands to complete your lab steps.\n"
        ),
    })

    import time as _time
    last_activity = _time.monotonic()

    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=SESSION_POLL_INTERVAL,
                )
                last_activity = _time.monotonic()
            except asyncio.TimeoutError:
                if _time.monotonic() - last_activity > IDLE_TIMEOUT_SECONDS:
                    logger.info(
                        "linux terminal WS: idle timeout (session=%s user=%s)",
                        session_id, username,
                    )
                    await _send(websocket, {
                        "type": "error",
                        "text": f"Terminal disconnected after {IDLE_TIMEOUT_SECONDS}s of inactivity.\n",
                    })
                    await _close(websocket, "idle_timeout")
                    return
                current = session_repo.get(session_id)
                if current is None or current.lab_session_status != LabSessionStatus.LAB_ACTIVE:
                    logger.info(
                        "linux terminal WS: session no longer active (session=%s user=%s)",
                        session_id, username,
                    )
                    await _send(websocket, {"type": "error", "text": "Lab session has ended. Terminal disconnecting.\n"})
                    await _close(websocket, "session_ended")
                    return
                continue
            except (WebSocketDisconnect, ConnectionClosed):
                break

            import json as _json
            try:
                msg = _json.loads(raw)
            except _json.JSONDecodeError:
                await _send(websocket, {"type": "error", "text": "Invalid message format.\n"})
                continue

            if not isinstance(msg, dict):
                continue

            if msg.get("type") != "command":
                continue

            cmd_str = str(msg.get("cmd", ""))[:MAX_CMD_LENGTH].strip()
            if not cmd_str:
                continue

            current = session_repo.get(session_id)
            if current is None or current.lab_session_status != LabSessionStatus.LAB_ACTIVE:
                await _send(websocket, {"type": "error", "text": "Lab session is no longer active.\n"})
                await _close(websocket, "session_ended")
                return

            loop = asyncio.get_running_loop()
            cmd_result = await loop.run_in_executor(
                None,
                lambda c=cmd_str: _run_linux_cmd(linux_adapter, session_id, workspace_path, c),  # type: ignore[misc]  # mypy cannot infer default-arg lambda; not a core runtime path
            )

            if cmd_result["blocked"]:
                await _send(websocket, {"type": "blocked", "text": cmd_result["text"] + "\n"})
            else:
                await _send(websocket, {
                    "type": "output",
                    "text": cmd_result["text"],
                    "exit_code": cmd_result["exit_code"],
                })

    except (WebSocketDisconnect, ConnectionClosed):
        pass

    logger.info(
        "linux terminal WS: connection closed (session=%s user=%s)",
        session_id, username,
    )
