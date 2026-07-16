"""
LabGen — automatic VM provisioning for Start Lab (P0 Reader Path Repair).

When a First-Wave lab's Start Lab flow detects a user with no assigned VM
(no_vm_assigned), this module auto-triggers a background VM creation instead
of requiring the user to visit the old /app platform manually. It is a thin,
decoupled layer sitting entirely *before* LabGen session creation — it does
not touch LabSessionStatus or any session state machine.

Idempotency: the entire "check in-flight job / decide to trigger" step runs
inside a single storage_utils.safe_update_json() call, which holds an
exclusive flock for the whole read-modify-write cycle. Two concurrent
requests can never both observe "no in-flight job" and both trigger a clone —
the second request's updater always sees the first request's just-written
job record.

Storage: data/labgen_vm_provisioning.json (flock JSON, same pattern as every
other data/*.json file), keyed by username.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Coroutine, Dict, Optional, cast

from backend.storage_utils import safe_read_json, safe_update_json
from backend.task_registry import register as register_task
from backend.vm_manager import (
    NoAvailableVMId,
    SystemCapacityExceeded,
    VMQuotaExceeded,
    VMRateLimited,
    provision_vm_for_user,
)

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent.parent.parent / "data" / "labgen_vm_provisioning.json"

# create_vm's own asyncio.wait_for budget is 360s; a job still "provisioning"
# past this age is assumed to have died with the process (e.g. non-graceful
# restart) and is safe to retrigger — a fresh vm_id is assigned, so this never
# overwrites or races with whatever the dead job may have left behind.
STALE_AFTER_SECONDS: int = 600

_ERROR_MESSAGES: Dict[str, str] = {
    "quota_exceeded": "实验环境准备遇到问题，请稍后重试",
    "capacity_exceeded": "当前实验环境较为繁忙，请稍候几分钟后重试",
    "rate_limited": "请求过于频繁，请稍后重试",
    "timeout": "实验环境准备时间较长，请稍后重试",
    "no_available_id": "实验环境准备遇到问题，请稍后重试",
    "unknown": "实验环境准备遇到问题，请稍后重试或联系支持",
}

# Strong references for fire-and-forget background tasks — asyncio.create_task
# alone doesn't keep the Task alive against GC before it completes (matches
# backend/auth_routes.py:29-35).
_background_tasks: set[asyncio.Task] = set()


def _fire(coro: Coroutine[Any, Any, None]) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _new_job(now: float) -> Dict[str, Any]:
    return {
        "status": "provisioning",
        "started_at": now,
        "finished_at": None,
        "vm_id": None,
        "error_category": None,
    }


def read_job(username: str) -> Optional[Dict[str, Any]]:
    """Read-only lookup — never triggers provisioning. Safe for the polling endpoint."""
    data = safe_read_json(_DATA_FILE, default={})
    return data.get(username)


def invalidate_job(username: str) -> None:
    """Clear a job record so the next get_or_start_provisioning() call
    triggers a fresh background task, even if the current record says
    "ready". Used when a "ready" job's VM no longer exists (e.g. the old
    platform's 30-minute VM auto-expiry ran before the user came back to
    Start Lab again) — the job isn't wrong about *history*, but it no longer
    reflects a usable VM, so it must not keep telling the poller "ready"
    forever with nothing to show for it.
    """
    def _updater(data: Dict[str, Any]) -> Dict[str, Any]:
        data.pop(username, None)
        return data

    safe_update_json(_DATA_FILE, _updater)


def get_or_start_provisioning(username: str) -> Dict[str, Any]:
    """
    Idempotent entry point. Returns the current job for `username` — either a
    just-created one (background task fired) or an existing in-flight/ready one.

    The decision of whether to trigger a new background task is made *inside*
    the safe_update_json updater (i.e. under the exclusive flock); the actual
    `_fire()` call happens outside the lock, after safe_update_json returns,
    so we never hold a lock across an asyncio.create_task call.
    """
    trigger_holder: Dict[str, bool] = {"should_trigger": False}
    job_holder: Dict[str, Any] = {}

    def _updater(data: Dict[str, Any]) -> Dict[str, Any]:
        now = time.time()
        existing = data.get(username)

        if existing is not None:
            if existing["status"] == "ready":
                job_holder["job"] = existing
                return data
            if existing["status"] == "provisioning":
                age = now - existing["started_at"]
                if age < STALE_AFTER_SECONDS:
                    job_holder["job"] = existing
                    return data
                logger.warning(
                    f"Stale provisioning job for user '{username}' (age={age:.0f}s), retriggering"
                )
            # status == "failed", or stale "provisioning" -> fall through to retrigger

        new_job = _new_job(now)
        data[username] = new_job
        job_holder["job"] = new_job
        trigger_holder["should_trigger"] = True
        return data

    safe_update_json(_DATA_FILE, _updater)

    if trigger_holder["should_trigger"]:
        _fire(_run_provisioning(username))

    return cast(Dict[str, Any], job_holder["job"])


def _mark_ready(username: str, vm_id: int) -> None:
    def _updater(data: Dict[str, Any]) -> Dict[str, Any]:
        job = dict(data.get(username, {}))
        job.update(status="ready", finished_at=time.time(), vm_id=vm_id)
        data[username] = job
        return data

    safe_update_json(_DATA_FILE, _updater)


def _mark_failed(username: str, error_category: str) -> None:
    def _updater(data: Dict[str, Any]) -> Dict[str, Any]:
        job = dict(data.get(username, {}))
        job.update(status="failed", finished_at=time.time(), error_category=error_category)
        data[username] = job
        return data

    safe_update_json(_DATA_FILE, _updater)


async def _run_provisioning(username: str) -> None:
    """Background task: create a real VM for `username` via the shared core
    (backend.vm_manager.provision_vm_for_user), reusing the same quota/rate-limit/
    Proxmox-clone/track pipeline as the manual /api/vms/create endpoint — no
    second provisioning implementation.

    Known non-blocking edge case (safety-reviewed, judged acceptable): if
    provision_vm_for_user's underlying thread keeps running past the 360s
    asyncio.wait_for budget and *later* succeeds, this job is already marked
    "failed"/"timeout" and _mark_ready() is never called for that late
    success — the job record stays permanently wrong. This never strands the
    user: create_lab_session checks VMTracker directly (not this job's
    status) before deciding whether to re-enter the provisioning branch, so
    the next Start Lab click sees the tracked VM and proceeds normally. Only
    this job-store bookkeeping is stale, which is a diagnostics concern, not
    a user-facing one.

    Also by design: a "failed" job retriggers unconditionally on the very
    next get_or_start_provisioning() call (no cooldown, unlike "provisioning"
    jobs which respect STALE_AFTER_SECONDS) — bounded by provision_vm_for_user's
    own per-user rate limiter, so a rapid retry loop hits that limit rather
    than creating unbounded load.
    """
    loop = asyncio.get_running_loop()
    try:
        data = await asyncio.wait_for(
            register_task(loop.run_in_executor(None, provision_vm_for_user, username)),
            timeout=360,
        )
        _mark_ready(username, vm_id=data["vm_id"])
    except VMQuotaExceeded:
        _mark_failed(username, "quota_exceeded")
    except SystemCapacityExceeded:
        _mark_failed(username, "capacity_exceeded")
    except VMRateLimited:
        _mark_failed(username, "rate_limited")
    except NoAvailableVMId:
        _mark_failed(username, "no_available_id")
    except asyncio.TimeoutError:
        _mark_failed(username, "timeout")
    except Exception:
        logger.exception(f"Auto-provisioning failed for user '{username}'")
        _mark_failed(username, "unknown")


def safe_message_for(error_category: Optional[str]) -> str:
    """Map an internal error_category to a user-safe message. Never returns
    the raw exception text — see _ERROR_MESSAGES."""
    return _ERROR_MESSAGES.get(error_category or "unknown", _ERROR_MESSAGES["unknown"])
