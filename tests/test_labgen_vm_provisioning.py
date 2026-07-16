"""
Tests for backend/labgen/vm_provisioning.py — LabGen's auto VM provisioning
for the Start Lab "no_vm_assigned" flow (P0 Reader Path Repair).

Covers:
  - Idempotency: repeated/concurrent calls trigger at most one background task
  - Stale in-flight jobs (process restart) allow retriggering
  - ready/failed jobs never retrigger
  - _run_provisioning maps every provision_vm_for_user failure mode to a safe
    error_category, never leaking the raw exception
  - read_job() is a pure read, never triggers provisioning
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.labgen import vm_provisioning
from backend.vm_manager import (
    NoAvailableVMId,
    SystemCapacityExceeded,
    VMQuotaExceeded,
    VMRateLimited,
)

pytestmark = pytest.mark.static


@pytest.fixture(autouse=True)
def _isolated_data_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vm_provisioning, "_DATA_FILE", tmp_path / "labgen_vm_provisioning.json")


@pytest.fixture(autouse=True)
def _no_real_background_task(monkeypatch):
    """Idempotency tests only care about the trigger decision, not the actual
    async task execution — replace _fire with a plain counter so these tests
    don't need a running event loop and can be called from worker threads."""
    calls = []

    def _stub_fire(coro):
        calls.append(coro)
        coro.close()  # never actually scheduled — avoid "never awaited" warnings

    monkeypatch.setattr(vm_provisioning, "_fire", _stub_fire)
    return calls


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestGetOrStartProvisioning:
    def test_first_call_creates_job_and_triggers(self, _no_real_background_task):
        job = vm_provisioning.get_or_start_provisioning("alice")

        assert job["status"] == "provisioning"
        assert len(_no_real_background_task) == 1

    def test_second_call_while_provisioning_reuses_job_no_retrigger(self, _no_real_background_task):
        first = vm_provisioning.get_or_start_provisioning("alice")
        second = vm_provisioning.get_or_start_provisioning("alice")

        assert second["started_at"] == first["started_at"]
        assert len(_no_real_background_task) == 1  # not triggered again

    def test_ready_job_does_not_retrigger(self, _no_real_background_task):
        vm_provisioning.get_or_start_provisioning("alice")
        vm_provisioning._mark_ready("alice", vm_id=500)

        job = vm_provisioning.get_or_start_provisioning("alice")

        assert job["status"] == "ready"
        assert job["vm_id"] == 500
        assert len(_no_real_background_task) == 1  # still just the first trigger

    def test_stale_provisioning_job_allows_retrigger(self, _no_real_background_task, monkeypatch):
        vm_provisioning.get_or_start_provisioning("alice")
        assert len(_no_real_background_task) == 1

        # Simulate a job that's been "provisioning" for longer than STALE_AFTER_SECONDS
        # (e.g. the process restarted mid-clone and lost the in-memory task).
        def _backdate(data):
            job = dict(data["alice"])
            job["started_at"] -= vm_provisioning.STALE_AFTER_SECONDS + 1
            data["alice"] = job
            return data

        from backend.storage_utils import safe_update_json
        safe_update_json(vm_provisioning._DATA_FILE, _backdate)

        job = vm_provisioning.get_or_start_provisioning("alice")

        assert job["status"] == "provisioning"
        assert len(_no_real_background_task) == 2  # retriggered

    def test_failed_job_allows_retrigger(self, _no_real_background_task):
        vm_provisioning.get_or_start_provisioning("alice")
        vm_provisioning._mark_failed("alice", "unknown")

        job = vm_provisioning.get_or_start_provisioning("alice")

        assert job["status"] == "provisioning"
        assert len(_no_real_background_task) == 2

    def test_different_users_do_not_share_jobs(self, _no_real_background_task):
        vm_provisioning.get_or_start_provisioning("alice")
        vm_provisioning.get_or_start_provisioning("bob")

        assert len(_no_real_background_task) == 2

    def test_concurrent_calls_only_trigger_once(self, _no_real_background_task):
        """Real concurrent threads hitting the same flock-guarded file must only
        ever produce one triggered job — this is the property that actually
        prevents two Proxmox clones for the same user."""
        barrier = threading.Barrier(8)

        def _call():
            barrier.wait()
            return vm_provisioning.get_or_start_provisioning("alice")

        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = list(pool.map(lambda _: _call(), range(8)))

        assert len(_no_real_background_task) == 1
        started_ats = {j["started_at"] for j in jobs}
        assert len(started_ats) == 1  # every thread got the same job record


class TestInvalidateJob:
    """Regression (Codex P1): a 'ready' job whose VM later disappeared (e.g.
    30-min auto-expiry) must be clearable so the next call starts fresh
    instead of reporting a phantom 'ready' forever."""

    def test_invalidate_then_get_or_start_triggers_fresh_job(self, _no_real_background_task):
        first = vm_provisioning.get_or_start_provisioning("alice")
        vm_provisioning._mark_ready("alice", vm_id=500)
        assert vm_provisioning.read_job("alice")["status"] == "ready"

        vm_provisioning.invalidate_job("alice")
        assert vm_provisioning.read_job("alice") is None

        second = vm_provisioning.get_or_start_provisioning("alice")
        assert second["status"] == "provisioning"
        assert second["started_at"] != first["started_at"]
        assert len(_no_real_background_task) == 2

    def test_invalidate_on_unknown_user_is_a_no_op(self):
        vm_provisioning.invalidate_job("nobody")  # must not raise
        assert vm_provisioning.read_job("nobody") is None


# ---------------------------------------------------------------------------
# read_job — pure read, never triggers
# ---------------------------------------------------------------------------


class TestReadJob:
    def test_no_job_returns_none(self):
        assert vm_provisioning.read_job("alice") is None

    def test_read_does_not_trigger(self, _no_real_background_task):
        vm_provisioning.read_job("alice")
        vm_provisioning.read_job("alice")

        assert vm_provisioning.read_job("alice") is None
        assert len(_no_real_background_task) == 0

    def test_returns_current_job(self, _no_real_background_task):
        vm_provisioning.get_or_start_provisioning("alice")

        job = vm_provisioning.read_job("alice")

        assert job["status"] == "provisioning"


# ---------------------------------------------------------------------------
# _run_provisioning — failure classification, never leaks raw exceptions
# ---------------------------------------------------------------------------


class TestRunProvisioning:
    async def test_success_marks_ready_with_vm_id(self, monkeypatch):
        monkeypatch.setattr(
            vm_provisioning, "provision_vm_for_user",
            lambda username: {"vm_id": 501, "name": "k8s-lab-501"},
        )

        await vm_provisioning._run_provisioning("alice")

        job = vm_provisioning.read_job("alice")
        assert job["status"] == "ready"
        assert job["vm_id"] == 501

    @pytest.mark.parametrize(
        "exc,category",
        [
            (VMQuotaExceeded(1, 1), "quota_exceeded"),
            (SystemCapacityExceeded(12, 12), "capacity_exceeded"),
            (VMRateLimited(300), "rate_limited"),
            (NoAvailableVMId("none left"), "no_available_id"),
            (RuntimeError("Proxmox exploded — secret detail"), "unknown"),
        ],
    )
    async def test_failure_marks_category_without_leaking_detail(self, monkeypatch, exc, category):
        def _raise(username):
            raise exc

        monkeypatch.setattr(vm_provisioning, "provision_vm_for_user", _raise)

        await vm_provisioning._run_provisioning("alice")

        job = vm_provisioning.read_job("alice")
        assert job["status"] == "failed"
        assert job["error_category"] == category
        # The raw exception text must never end up in the persisted job record.
        assert "Proxmox exploded" not in str(job)
        assert "secret detail" not in str(job)


# ---------------------------------------------------------------------------
# safe_message_for — user-facing text never leaks internals
# ---------------------------------------------------------------------------


class TestSafeMessageFor:
    @pytest.mark.parametrize(
        "category",
        ["quota_exceeded", "capacity_exceeded", "rate_limited", "timeout", "no_available_id", "unknown", None, "made_up_category"],
    )
    def test_never_leaks_internal_tokens(self, category):
        msg = vm_provisioning.safe_message_for(category)
        for forbidden in ("vmid", "vm_id", "proxmox", "/app", "no_vm_assigned", "Traceback"):
            assert forbidden.lower() not in msg.lower()
