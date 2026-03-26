"""
K8S NetLab - In-flight VM Task Registry

Tracks asyncio Futures for long-running VM operations (create / delete).
The lifespan shutdown calls drain() to wait for them before the process exits,
preventing orphaned VMs caused by mid-operation SIGTERM.
"""

import asyncio
import logging
from typing import Set

logger = logging.getLogger(__name__)

# Module-level set of in-flight futures.
_pending: Set[asyncio.Future] = set()


def register(fut: "asyncio.Future") -> "asyncio.Future":
    """
    Register a future and return it unchanged.

    Adds a done-callback that automatically removes the future from the
    pending set when it completes (success, failure, or cancellation).
    """
    _pending.add(fut)
    fut.add_done_callback(_pending.discard)
    return fut


async def drain(timeout: float = 30.0) -> None:
    """
    Wait for all registered in-flight futures to complete.

    Called during lifespan shutdown. Logs a warning if the timeout is reached
    before all tasks finish, but does not raise — the process will exit anyway.
    """
    if not _pending:
        return

    count = len(_pending)
    logger.info(f"Graceful shutdown: waiting for {count} in-flight VM task(s)…")

    try:
        await asyncio.wait_for(
            asyncio.gather(*list(_pending), return_exceptions=True),
            timeout=timeout,
        )
        logger.info("Graceful shutdown: all in-flight VM tasks finished")
    except asyncio.TimeoutError:
        logger.warning(
            f"Graceful shutdown timeout ({timeout}s): "
            f"{len(_pending)} VM task(s) still running — forcing exit"
        )
