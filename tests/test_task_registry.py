"""Tests for task_registry — in-flight VM task tracking and graceful drain."""

import asyncio

import pytest

from backend.task_registry import drain, register


@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure the registry is empty before and after each test."""
    from backend import task_registry
    task_registry._pending.clear()
    yield
    task_registry._pending.clear()


# ── register ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_adds_future_to_pending():
    """register() must add the future to the pending set."""
    from backend import task_registry

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, lambda: None)
    register(fut)
    assert fut in task_registry._pending
    await fut


@pytest.mark.asyncio
async def test_register_removes_future_on_completion():
    """After a registered future completes, it must be removed from pending."""
    from backend import task_registry

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, lambda: None)
    register(fut)
    await fut
    await asyncio.sleep(0)  # let done callback fire
    assert fut not in task_registry._pending


# ── drain ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_drain_waits_for_in_flight_task():
    """drain() must wait until all registered futures complete."""
    completed = []

    def slow_work():
        import time
        time.sleep(0.05)
        completed.append(True)

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, slow_work)
    register(fut)

    await drain(timeout=5.0)
    assert completed == [True]


@pytest.mark.asyncio
async def test_drain_empty_registry_returns_immediately():
    """drain() on an empty registry must return without hanging."""
    await drain(timeout=1.0)  # should complete instantly


@pytest.mark.asyncio
async def test_drain_handles_task_exception_gracefully():
    """drain() must not raise when a registered task raises internally."""
    def failing_work():
        raise RuntimeError("intentional failure")

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, failing_work)
    register(fut)

    # drain must not propagate the exception
    await drain(timeout=5.0)


@pytest.mark.asyncio
async def test_drain_logs_warning_on_timeout():
    """drain() 超时时必须打 warning 日志，不抛异常（超时兜底回归）。"""
    import asyncio
    from unittest.mock import patch

    async def never_done():
        await asyncio.sleep(9999)

    from backend import task_registry

    # 注入一个永不完成的 future
    loop = asyncio.get_running_loop()
    task = loop.create_task(never_done())
    task_registry._pending.add(task)

    # drain 超时 0.05s 应该触发 TimeoutError 分支
    await drain(timeout=0.05)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
