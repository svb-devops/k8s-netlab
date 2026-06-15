"""
WebSocket handler for the learner kubectl terminal.

Security model:
  - Authenticated via session_token cookie (same mechanism as /ws/terminal/{vm_id}).
  - Only the session owner may open the terminal.
  - Session must be LAB_ACTIVE; connection is refused for any other state.
  - Session state is polled every SESSION_POLL_INTERVAL seconds; connection is
    closed gracefully if the session leaves LAB_ACTIVE.
  - Learner credentials (SA, Role, RoleBinding, kubeconfig) are created lazily
    on first connection and reclaimed on disconnect.
  - No raw kubeconfig content is sent to the client or logged.
  - Idle timeout: IDLE_TIMEOUT_SECONDS of inactivity closes the connection.

Protocol (JSON messages only):
  Client → Server:  {"type": "command", "cmd": "<kubectl command>"}
  Server → Client:
    {"type": "ready",   "namespace": "...", "msg": "..."}
    {"type": "output",  "text": "...", "exit_code": 0}
    {"type": "blocked", "text": "reason"}
    {"type": "error",   "text": "reason"}
    {"type": "closed",  "reason": "session_ended|idle_timeout|auth_error"}
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from backend import config
from backend.auth import auth_manager
from backend.labgen import kubectl_executor, learner_credentials
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.models import LabSessionStatus

logger = logging.getLogger(__name__)

SESSION_POLL_INTERVAL = 10      # seconds between session-state polls
IDLE_TIMEOUT_SECONDS = 600      # 10 minutes idle → disconnect
MAX_CMD_LENGTH = 2048           # bytes; longer input is silently truncated


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
) -> None:
    """
    WebSocket handler for the learner kubectl terminal.

    Authentication and ownership checks are performed here (not by the caller).
    The WebSocket is accepted here so we can send structured error messages before closing.

    Args:
        websocket:    FastAPI WebSocket connection (not yet accepted).
        session_id:   Lab session ID from the URL path.
        session_repo: Injected session repository (overridable in tests).
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
    await _send(websocket, {
        "type": "ready",
        "namespace": namespace,
        "msg": (
            f"Lab terminal ready. Namespace: {namespace}\n"
            "Use kubectl commands to complete your lab steps.\n"
            "⚠  Use this terminal for the current lab only. Do not enter real secrets.\n"
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
