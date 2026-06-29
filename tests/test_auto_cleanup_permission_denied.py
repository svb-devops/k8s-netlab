"""
Regression test: auto_cleanup_task must untrack VMs that fail deletion with 403
Forbidden instead of retrying indefinitely and spamming ERROR logs.

Reproduces: VM 400 (outside pool) causing per-minute ERROR log storm because
k8s-netlab API token lacked VM.Audit on that VMID.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

pytestmark = pytest.mark.static


def _make_mock_repo():
    repo = MagicMock()
    repo.has_active_session_for_vm.return_value = False
    return repo


async def _run_one_cleanup_iteration(
    expired_vms: list[str],
    delete_result: dict[str, Any],
    exempt_ids: frozenset[int] | None = None,
) -> MagicMock:
    """
    Run exactly one iteration of auto_cleanup_task's inner loop body
    (sleep once, process VMs, then cancel).
    Returns the mock vm_tracker for assertion.
    """
    import backend.main as main_mod

    sleep_count = 0

    async def _controlled_sleep(_delay: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    mock_tracker = MagicMock()
    mock_tracker.get_expired_vms.return_value = expired_vms

    override_exempt = exempt_ids if exempt_ids is not None else frozenset()

    with (
        patch("asyncio.sleep", side_effect=_controlled_sleep),
        patch.object(main_mod, "vm_tracker", mock_tracker),
        patch.object(main_mod, "auth_manager", MagicMock()),
        patch.object(main_mod, "_get_lab_session_repo", return_value=_make_mock_repo()),
        patch("backend.config.VM_CLEANUP_EXEMPT_IDS", override_exempt),
        patch("backend.config.VM_TEMPLATE_ID", 101),
        patch(
            "asyncio.get_running_loop",
            return_value=asyncio.get_event_loop(),
        ),
    ):
        # Patch delete_vm so run_in_executor returns the desired dict
        mock_delete = MagicMock(return_value=delete_result)
        with patch.object(main_mod, "delete_vm", mock_delete):
            try:
                await main_mod.auto_cleanup_task()
            except asyncio.CancelledError:
                pass

    return mock_tracker


class TestAutoCleanupPermission403:
    async def test_403_forbidden_untracks_vm(self) -> None:
        """VM that returns 403 Forbidden must be untracked, not retried."""
        mock_tracker = await _run_one_cleanup_iteration(
            expired_vms=["400"],
            delete_result={
                "success": False,
                "error": "403 Forbidden: Permission check failed (/vms/400, VM.Audit)",
            },
        )
        mock_tracker.untrack_vm.assert_called_once_with("400")

    async def test_permission_check_failed_string_untracks_vm(self) -> None:
        """'Permission check failed' pattern (without HTTP status in string) also untracks."""
        mock_tracker = await _run_one_cleanup_iteration(
            expired_vms=["400"],
            delete_result={
                "success": False,
                "error": "Permission check failed (/vms/400, VM.Destroy)",
            },
        )
        mock_tracker.untrack_vm.assert_called_once_with("400")

    async def test_forbidden_string_untracks_vm(self) -> None:
        """Generic 'Forbidden' in error string also triggers untrack."""
        mock_tracker = await _run_one_cleanup_iteration(
            expired_vms=["400"],
            delete_result={
                "success": False,
                "error": "Forbidden: insufficient privileges",
            },
        )
        mock_tracker.untrack_vm.assert_called_once_with("400")

    async def test_404_does_not_trigger_403_branch(self) -> None:
        """A plain VM-not-found error should still go through the existing not-found branch."""
        mock_tracker = await _run_one_cleanup_iteration(
            expired_vms=["501"],
            delete_result={
                "success": False,
                "error": "Configuration file 'nodes/pve/qemu/501.conf' does not exist",
            },
        )
        # untrack_vm must still be called (existing not-found branch)
        mock_tracker.untrack_vm.assert_called_once_with("501")

    async def test_non_permission_error_does_not_untrack(self) -> None:
        """Generic deletion errors must NOT cause untrack (error kept in tracker for ops)."""
        mock_tracker = await _run_one_cleanup_iteration(
            expired_vms=["502"],
            delete_result={
                "success": False,
                "error": "connection timeout to Proxmox host",
            },
        )
        mock_tracker.untrack_vm.assert_not_called()

    async def test_successful_delete_untracks_vm(self) -> None:
        """Successful deletion still untracks as before (regression guard)."""
        mock_tracker = await _run_one_cleanup_iteration(
            expired_vms=["503"],
            delete_result={"success": True, "error": None},
        )
        mock_tracker.untrack_vm.assert_called_once_with("503")

    async def test_exempt_vm_is_not_deleted(self) -> None:
        """Exempt VMs must be skipped entirely — delete_vm must not be called."""
        import backend.main as main_mod

        sleep_count = 0

        async def _controlled_sleep(_delay: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError()

        mock_tracker = MagicMock()
        mock_tracker.get_expired_vms.return_value = ["299"]
        mock_delete = MagicMock()

        with (
            patch("asyncio.sleep", side_effect=_controlled_sleep),
            patch.object(main_mod, "vm_tracker", mock_tracker),
            patch.object(main_mod, "auth_manager", MagicMock()),
            patch.object(main_mod, "_get_lab_session_repo", return_value=_make_mock_repo()),
            patch("backend.config.VM_CLEANUP_EXEMPT_IDS", frozenset({299})),
            patch("backend.config.VM_TEMPLATE_ID", 101),
            patch.object(main_mod, "delete_vm", mock_delete),
        ):
            try:
                await main_mod.auto_cleanup_task()
            except asyncio.CancelledError:
                pass

        mock_delete.assert_not_called()
